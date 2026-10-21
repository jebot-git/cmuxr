# SPDX-License-Identifier: GPL-2.0-or-later
"""FLTK frontend launcher; Python retains the existing telemetry/core lifecycle."""
import os
from pathlib import Path
import shutil
import subprocess


def run(tray_only=False, listener=None):
    root = Path(__file__).resolve().parents[1]
    executable = os.environ.get('CMUXR_FLTK_BINARY')
    if not executable:
        local = root / 'build-fltk/cmuxr-fltk'
        executable = str(local) if local.is_file() else shutil.which('cmuxr-fltk')
    if not executable:
        raise RuntimeError('Build the FLTK frontend: cmake -S fltk -B build-fltk -DCMAKE_PREFIX_PATH=<FLTK prefix>; cmake --build build-fltk')
    env = dict(os.environ)
    prefix = os.environ.get('DE_XR_FLTK_PREFIX')
    if not prefix:
        candidate = Path(executable).resolve().parents[2] / '_toolkit'
        if (candidate / 'lib/libfltk.so.1.4').is_file():
            prefix = str(candidate)
    if prefix:
        env['LD_LIBRARY_PATH'] = str(Path(prefix) / 'lib') + ':' + env.get('LD_LIBRARY_PATH', '')

    descriptors = ()
    if listener is not None:
        env['CMUXR_CONTROL_FD'] = str(listener.fileno())
        descriptors = (listener.fileno(),)
    # The native StatusNotifier extension falls back to a normal window when no watcher is available.
    with subprocess.Popen([executable, *(['--tray'] if tray_only else [])], env=env, pass_fds=descriptors) as child:
        try:
            return child.wait()
        except BaseException:
            child.terminate()
            child.wait(timeout=3)
            raise
