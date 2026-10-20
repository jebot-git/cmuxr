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
        player.timer.stop()
        player.hide()
        tasks.pool.shutdown(wait=True,cancel_futures=True)
        app.processEvents()
        player.deleteLater()
        app.processEvents()

    def test_remote_injection_is_rejected(self):
        with self.assertRaises(ValueError):
            backend.request('status\nquit')

if __name__=='__main__':
    unittest.main()
