# SPDX-License-Identifier: GPL-2.0-or-later
import math
import os
from pathlib import Path
import pty
import socket
import subprocess
import tempfile
import time
import unittest
import wave
import struct
from cmuxr_gui import backend

ROOT = Path(__file__).resolve().parents[1]

class PlayerIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = os.environ.copy()
        self.saved = {k:os.environ.get(k) for k in ('CMUS_SOCKET','XDG_CONFIG_HOME','XDG_RUNTIME_DIR')}
        self.env.update(CMUS_HOME=str(self.root/'config'),CMUS_SOCKET=str(self.root/'socket'),TERM='xterm-256color',CMUS_LIB_DIR=str(ROOT),CMUS_DATA_DIR=str(ROOT/'data'))
        (self.root/'config').mkdir()
        os.environ.update(CMUS_SOCKET=self.env['CMUS_SOCKET'],XDG_CONFIG_HOME=str(self.root),XDG_RUNTIME_DIR=str(self.root))
        self.master, slave = pty.openpty()
        self.proc = subprocess.Popen([str(ROOT/'cmus')],stdin=slave,stdout=slave,stderr=slave,env=self.env)
        os.close(slave)
        for _ in range(50):
            try:
                backend.status()
                break
            except OSError:
                time.sleep(.05)
        else:
            self.fail('Console engine failed to start')
        backend.request('set output_plugin=alsa')
        backend.request('set dsp.alsa.device=null')

    def tearDown(self):
        self.proc.terminate()
        self.proc.wait(timeout=5)
        os.close(self.master)
        for key,value in self.saved.items():
            if value is None:
                os.environ.pop(key,None)
            else:
                os.environ[key]=value
        self.tmp.cleanup()

    def test_pages_commands_and_console_protocol(self):
        # More than one GUI page, Unicode, whitespace, escaping and directory context.
        for n in range(140):
            path = self.root / f'{n:03d} žluťoučký \\ song.wav'
            with wave.open(str(path),'wb') as out:
                out.setparams((1,2,44100,0,'NONE','not compressed'))
                out.writeframes(b'\0\0'*128)
        backend.request('add -l '+str(self.root))
        for _ in range(100):
            total, first=backend.page('library',0)
            if total==140:
                break
            time.sleep(.05)
        self.assertEqual(total,140)
        self.assertEqual(len(first),128)
        total, last=backend.page('library',128)
        self.assertEqual(len(last),12)
        self.assertEqual(len(set(first.values()) | set(last.values())),140)
        self.assertTrue(all(Path(p).is_file() for p in first.values()))
        response=backend.request('cmuxr-list library 0 9999')
        self.assertTrue(response[0].startswith('error'))
        self.assertEqual(len(backend.status()['spectrum'].split()),16)
        backend.request('cmuxr-play library 139')
        self.assertEqual(backend.status()['file'],last[139])
        backend.play_directory(last[139])
        self.assertEqual(backend.status()['file'],last[139])
        directory_total, _ = backend.page('playlist',0)
        self.assertEqual(directory_total,140)
        backend.request('player-stop')
        self.assertEqual(backend.status()['status'],'stopped')
        self.check_qt_navigation()
        # Remove by escaped filename, independent of the current engine selection.
        removed = first[0]
        backend.remove_from_library(removed)
        self.assertTrue(Path(removed).is_file())
        self.assertEqual(backend.page('library', 0)[0], 139)
        with self.assertRaisesRegex(ValueError, 'not in library'):
            backend.remove_from_library(removed)
        backend.add_to_library([removed])
        for _ in range(100):
            if backend.page('library', 0)[0] == 140:
                break
            time.sleep(.05)
        self.assertEqual(backend.page('library', 0)[0], 140)
        backend.request('clear -l')
        self.assertEqual(backend.page('library', 0)[0], 0)
        self.assertTrue(Path(removed).is_file())

    def check_qt_navigation(self):
        try:
            os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest
            from cmuxr_gui.app import Player, Tasks
        except ImportError:
            return  # Qt remains optional for console-only builds.
        app = QApplication.instance() or QApplication(['cmuxr-test'])
        tasks = Tasks()
        player = Player(app,tasks)
        player.show_list()
        for _ in range(100):
            app.processEvents()
            if player.model.total == 140:
                break
            QTest.qWait(10)
        self.assertEqual(player.model.total,140)
        player.list.setCurrentIndex(player.model.index(0))
        QTest.keyClick(player.list,Qt.Key.Key_Up)
        self.assertEqual(player.list.currentIndex().row(),139)
        QTest.keyClick(player.list,Qt.Key.Key_Down)
        self.assertEqual(player.list.currentIndex().row(),0)
        QTest.keyClick(player.list,Qt.Key.Key_Right)
        for _ in range(100):
            app.processEvents()
            if player.model.directory is not None:
                break
            QTest.qWait(10)
        self.assertEqual(player.model.directory,self.root)
        self.assertEqual(player.source.currentText(), 'Browse directory')
        self.assertEqual(player.location.text(), str(self.root))
        # Alt+arrows operate navigation history even with focus in the track list.
        child = self.root / 'child'
        child.mkdir()
        player.open_directory(child)
        QTest.keyClick(player.list, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
        self.assertEqual(player.model.directory, self.root)
        QTest.keyClick(player.list, Qt.Key.Key_Right, Qt.KeyboardModifier.AltModifier)
        self.assertEqual(player.model.directory, child)
        QTest.keyClick(player.list, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)
        self.assertEqual(player.model.directory, self.root)
        player.open_directory(child)
        player.go_history(-1)
        player.show_source('library')
        self.assertFalse(player.forward_action.isEnabled())
        self.assertFalse(player.add_directory_action.isEnabled())
        player.open_directory(Path('/'))
        self.assertFalse(player.up_action.isEnabled())
        position = player.history_position
        player.open_directory(self.root / 'missing')
        self.assertEqual(player.model.directory, Path('/'))
        self.assertEqual(player.history_position, position)
        self.assertIn('Directory does not exist', player.message.text())
        player.show_source('library')
        for _ in range(100):
            app.processEvents()
            if player.model.total == 140 and player.model.cache:
                break
            QTest.qWait(10)
        player.list.setCurrentIndex(player.model.index(0))
        self.assertTrue(player.remove_action.isEnabled())
        # Delete edits the location when typing; it removes a track only in the list.
        player.location.setText('abc')
        player.location.setCursorPosition(0)
        player.location.setFocus()
        QTest.keyClick(player.location, Qt.Key.Key_Delete)
        self.assertEqual(player.location.text(), 'bc')
        self.assertEqual(backend.page('library', 0)[0], 140)
        selected = player.selected_path()
        player.list.setFocus()
        QTest.keyClick(player.list, Qt.Key.Key_Delete)
        for _ in range(100):
            app.processEvents()
            if backend.page('library', 0)[0] == 139:
                break
            QTest.qWait(10)
        self.assertEqual(backend.page('library', 0)[0], 139)
        self.assertTrue(Path(selected).is_file())
        backend.add_to_library([selected])
        for _ in range(100):
            if backend.page('library', 0)[0] == 140:
                break
            QTest.qWait(10)
        player.timer.stop()
        player.hide()
        tasks.pool.shutdown(wait=True,cancel_futures=True)
        app.processEvents()
        player.deleteLater()
        app.processEvents()

    def test_remote_injection_is_rejected(self):
        with self.assertRaises(ValueError):
            backend.request('status\nquit')

    def test_desktop_open_and_repeated_launch(self):
        try:
            import PySide6
        except ImportError:
            self.skipTest('Qt6 is optional')
        # Exercise cold engine startup, then hand a second file to the same GUI.
        self.proc.terminate()
        self.proc.wait(timeout=5)
        paths = [self.root / name for name in ('first ž # \\ song.wav', 'second song.wav')]
        for path in paths:
            with wave.open(str(path), 'wb') as out:
                out.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
                out.writeframes(b'\0\0' * 44100 * 10)
        env = dict(self.env, XDG_RUNTIME_DIR=str(self.root), XDG_CONFIG_HOME=str(self.root),
                   QT_QPA_PLATFORM='offscreen', DISPLAY=':cmuxr-test')
        gui = subprocess.Popen([str(ROOT/'cmuxr'), '--gui', '--open', paths[0].as_uri()],
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            for _ in range(100):
                if (self.root/'cmuxr-gui-socket').exists():
                    break
                if gui.poll() is not None:
                    self.fail(gui.stderr.read().decode())
                time.sleep(.05)
            self.assertEqual(backend.status()['file'], str(paths[0]))
            second = subprocess.run([str(ROOT/'cmuxr'), '--gui', '--open', str(paths[1])],
                                    env=env, capture_output=True, timeout=10)
            self.assertEqual(second.returncode, 0, second.stderr.decode())
            self.assertIsNone(gui.poll())
            self.assertEqual(backend.status()['file'], str(paths[1]))
        finally:
            gui.terminate()
            gui.communicate(timeout=10)

    def test_desktop_multiple_files(self):
        paths = []
        for name in ('first.wav', 'queued.wav'):
            path = self.root/name
            with wave.open(str(path), 'wb') as out:
                out.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
                out.writeframes(b'\0\0' * 44100 * 10)
            paths.append(str(path))
        backend.open_files(backend.media_paths(paths))
        self.assertEqual(backend.status()['file'], paths[0])
        backend.request('player-next')
        self.assertEqual(backend.status()['file'], paths[1])


class DesktopPaths(unittest.TestCase):
    def test_rejects_remote_uris_and_command_injection(self):
        for value in ('file://remote/song.wav', 'https://example.com/song.wav', 'song\nquit.wav'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                backend.media_paths([value])

    def test_library_paths_reject_command_injection(self):
        with self.assertRaises(ValueError):
            backend.add_to_library(['song\nquit.wav'])

if __name__=='__main__':
    unittest.main()
