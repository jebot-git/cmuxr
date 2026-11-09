# SPDX-License-Identifier: GPL-2.0-or-later
"""Opt-in native menu regression on a private X display and session bus.

Run with CMUXR_MENU_BINARY=/absolute/path/to/cmuxr-fltk python3
tests/test_fltk_menu.py. Requires Xvfb, PyGObject, python-xlib and Pillow.
CMUXR_XVFB can select an extracted Xvfb; its libraries must be on LD_LIBRARY_PATH.
"""
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest


@unittest.skipUnless(os.environ.get('CMUXR_MENU_BINARY'), 'set CMUXR_MENU_BINARY for native UI tests')
class UniversalMenu(unittest.TestCase):
    def test_host_lifecycle_shortcuts_tray_and_modal_actions(self):
        from gi.repository import Gio, GLib
        from Xlib import X, XK, display, protocol
        from Xlib.ext import xtest
        from PIL import Image, ImageChops

        self.assertEqual(os.environ.get('CMUXR_MENU_PRIVATE_BUS'), '1')
        signal.pthread_sigmask(signal.SIG_SETMASK, [])
        children, logs = [], []
        with tempfile.TemporaryDirectory(prefix='cmuxr-menu-') as directory:
            root = Path(directory)
            root.chmod(0o700)
            server = socket.socket(socket.AF_UNIX)
            server.bind(str(root / 'core'))
            server.listen(8)
            stopped = threading.Event()
            commands = []
            state = {'shuffle': False, 'repeat': True}

            def core():
                while not stopped.is_set():
                    try:
                        connection, _ = server.accept()
                    except OSError:
                        return
                    with connection:
                        line = b''
                        while not line.endswith(b'\n'):
                            block = connection.recv(4096)
                            if not block:
                                break
                            line += block
                        value = line.decode().strip()
                        if value == 'status':
                            response = 'status stopped\n' + ''.join(
                                f'set {key} {str(checked).lower()}\n' for key, checked in state.items()) + '\n'
                        elif value.startswith('cmuxr-list '):
                            response = 'total 1\ntrack 0 /tmp/song.wav\n\n'
                        else:
                            commands.append(value)
                            if value.startswith('toggle '):
                                key = value.split()[1]
                                state[key] = not state[key]
                            response = '\n'
                        connection.sendall(response.encode())

            threading.Thread(target=core, daemon=True).start()
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

            def call(destination, path, interface, method, parameters=None):
                return bus.call_sync(destination, path, interface, method, parameters,
                                     None, Gio.DBusCallFlags.NONE, 1500, None).unpack()

            def name(method, value):
                params = GLib.Variant('(su)', (value, 0)) if method == 'RequestName' else GLib.Variant('(s)', (value,))
                return call('org.freedesktop.DBus', '/org/freedesktop/DBus',
                            'org.freedesktop.DBus', method, params)

            def wait(predicate):
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    while GLib.MainContext.default().pending():
                        GLib.MainContext.default().iteration(False)
                    result = predicate()
                    if result:
                        return result
                    time.sleep(.03)
                self.fail('Timed out waiting for native menu behavior')

            def start(args, env, **kwargs):
                log = tempfile.TemporaryFile(mode='w+')
                logs.append(log)
                child = subprocess.Popen(args, env=env, stdout=log, stderr=subprocess.STDOUT, **kwargs)
                children.append(child)
                return child

            xd = None
            registration = 0
            try:
                read_fd, write_fd = os.pipe()
                start([os.environ.get('CMUXR_XVFB', 'Xvfb'), '-displayfd', str(write_fd),
                       '-screen', '0', '1200x900x24', '-nolisten', 'tcp'], os.environ.copy(), pass_fds=(write_fd,))
                os.close(write_fd)
                with os.fdopen(read_fd) as pipe:
                    screen = ':' + pipe.readline().strip()
                env = dict(os.environ, DISPLAY=screen, FLTK_BACKEND='x11',
                           XDG_RUNTIME_DIR=directory, XDG_CONFIG_HOME=str(root / 'config'),
                           XDG_CURRENT_DESKTOP='Dome', CMUS_SOCKET=str(root / 'core'),
                           LIBGL_ALWAYS_SOFTWARE='1')
                for key in ('WAYLAND_DISPLAY', 'WAYLAND_SOCKET', 'CMUXR_CONTROL_FD'):
                    env.pop(key, None)
                player = start([os.environ['CMUXR_MENU_BINARY']], env)
                xd = display.Display(screen)

                def windows():
                    return [w for w in xd.screen().root.query_tree().children
                            if w.get_wm_class() and 'org.domed.cmuxr' in w.get_wm_class()]

                window = wait(lambda: next(iter(windows()), None))
                service_atom = xd.intern_atom('_KDE_NET_WM_APPMENU_SERVICE_NAME')
                path_atom = xd.intern_atom('_KDE_NET_WM_APPMENU_OBJECT_PATH')
                wait(lambda: window.get_full_property(service_atom, X.AnyPropertyType))
                service = window.get_full_property(service_atom, X.AnyPropertyType).value.decode()
                path = window.get_full_property(path_atom, X.AnyPropertyType).value.decode()

                def menu(method, parameters):
                    return call(service, path, 'com.canonical.dbusmenu', method, parameters)

                def entries():
                    _, tree = menu('GetLayout', GLib.Variant('(iias)', (0, -1, [])))
                    result = {}

                    def visit(node):
                        item, properties, nested = node
                        if 'label' in properties:
                            result[properties['label']] = (item, properties)
                        for child in nested:
                            visit(child)
                    visit(tree)
                    return result

                def event(label):
                    item = entries()[label][0]
                    menu('Event', GLib.Variant('(isvu)', (item, 'clicked', GLib.Variant('i', 0), 0)))

                def image():
                    geo = window.get_geometry()
                    raw = window.get_image(0, 0, geo.width, geo.height, X.ZPixmap, 0xffffffff)
                    return Image.frombytes('RGB', (geo.width, geo.height), raw.data, 'raw', 'BGRX')

                wait(lambda: entries()['Repeat'][1].get('toggle-state') == 1)
                time.sleep(.3)
                local = image()
                self.assertEqual(entries()['Quit'][1]['shortcut'], [['Super', 'Q']])
                self.assertFalse(entries()['Play selected'][1]['enabled'])
                event('Play selected')
                self.assertFalse(commands)
                name('RequestName', 'com.canonical.AppMenu.Registrar')
                wait(lambda: ImageChops.difference(local.crop((645, 60, 895, 100)),
                                                  image().crop((645, 35, 895, 75))).getbbox() is None)
                self.assertEqual(window.get_geometry().height, 700)

                window.set_input_focus(X.RevertToParent, X.CurrentTime)
                for key, kind in [('Control_L', X.KeyPress), ('Right', X.KeyPress),
                                  ('Right', X.KeyRelease), ('Control_L', X.KeyRelease)]:
                    xtest.fake_input(xd, kind, xd.keysym_to_keycode(XK.string_to_keysym(key)))
                xd.sync()
                wait(lambda: 'player-next' in commands)
                event('Shuffle')
                wait(lambda: entries()['Shuffle'][1]['toggle-state'] == 1)
                event('Toggle XR floor')
                wait(lambda: entries()['Toggle XR floor'][1]['toggle-state'] == 0)

                # The chooser callback must not delay the Event method reply.
                event('Add files')
                chooser = wait(lambda: next((w for w in xd.screen().root.query_tree().children
                                              if w.id != window.id and w.get_attributes().map_state == X.IsViewable), None))
                chooser.set_input_focus(X.RevertToParent, X.CurrentTime)
                for kind in (X.KeyPress, X.KeyRelease):
                    xtest.fake_input(xd, kind, xd.keysym_to_keycode(XK.string_to_keysym('Escape')))
                xd.sync()

                registered = []
                info = Gio.DBusNodeInfo.new_for_xml('<node><interface name="org.kde.StatusNotifierWatcher">'
                    '<method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method>'
                    '</interface></node>')

                def register(_bus, _sender, _path, _interface, _method, params, invocation):
                    registered.append(params.unpack()[0])
                    invocation.return_value(None)

                registration = bus.register_object('/StatusNotifierWatcher', info.interfaces[0], register, None, None)
                name('RequestName', 'org.kde.StatusNotifierWatcher')
                wait(lambda: registered)
                self.assertEqual(registered, [service])
                self.assertEqual(call(service, '/StatusNotifierItem',
                    'org.freedesktop.DBus.Properties', 'Get',
                    GLib.Variant('(ss)', ('org.kde.StatusNotifierItem', 'Menu'))), (path,))
                message = protocol.event.ClientMessage(window=window, client_type=xd.intern_atom('WM_PROTOCOLS'),
                    data=(32, [xd.intern_atom('WM_DELETE_WINDOW'), X.CurrentTime, 0, 0, 0]))
                window.send_event(message, event_mask=0)
                xd.sync()
                wait(lambda: not windows())
                event('Show player')
                window = wait(lambda: next(iter(windows()), None))
                wait(lambda: ImageChops.difference(local.crop((645, 60, 895, 100)),
                                                  image().crop((645, 35, 895, 75))).getbbox() is None)
                name('ReleaseName', 'com.canonical.AppMenu.Registrar')
                wait(lambda: ImageChops.difference(local.crop((645, 60, 895, 100)),
                                                  image().crop((645, 60, 895, 100))).getbbox() is None)
                event('Quit')
                wait(lambda: player.poll() is not None)
                self.assertEqual(player.returncode, 0)
            finally:
                if registration:
                    bus.unregister_object(registration)
                for value in ('org.kde.StatusNotifierWatcher', 'com.canonical.AppMenu.Registrar'):
                    name('ReleaseName', value)
                if xd:
                    xd.close()
                for child in reversed(children):
                    if child.poll() is None:
                        child.terminate()
                        try:
                            child.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait()
                stopped.set()
                server.close()
                if sys.exc_info()[0]:
                    for log in logs:
                        log.seek(0)
                        print(log.read(), file=sys.stderr)
                for log in logs:
                    log.close()


if __name__ == '__main__':
    if os.environ.get('CMUXR_MENU_BINARY') and os.environ.get('CMUXR_MENU_PRIVATE_BUS') != '1':
        os.execvpe('dbus-run-session', ['dbus-run-session', '--', sys.executable, *sys.argv],
                  dict(os.environ, CMUXR_MENU_PRIVATE_BUS='1'))
    unittest.main()
