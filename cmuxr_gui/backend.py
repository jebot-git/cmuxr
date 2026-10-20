# SPDX-License-Identifier: GPL-2.0-or-later
import json
import os
from pathlib import Path
import socket
import time
from urllib.parse import urlsplit, unquote


def media_paths(values):
    """Decode desktop file URIs before sending literal paths to the engine."""
    paths = []
    for value in values:
        if value.startswith('file:'):
            uri = urlsplit(value)
            if uri.netloc not in ('', 'localhost') or uri.query or uri.fragment:
                raise ValueError('Only local file URIs are supported')
            value = unquote(uri.path)
        elif '://' in value:
            raise ValueError('Open a local audio file')
        path = str(Path(value).expanduser().absolute())
        if any(char in path for char in '\r\n\0'):
            raise ValueError('Audio filenames cannot contain line breaks or NUL')
        if not Path(path).is_file():
            raise ValueError(f'Audio file does not exist: {path}')
        paths.append(path)
    return paths


def open_files(paths, timeout=5):
    """Play the first selection and queue the rest, also during engine startup."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            status()
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError('Player did not start')
            time.sleep(.05)
    for path in paths[1:]:
        request('add -q ' + path)
    if paths:
        request('player-play ' + paths[0])


def config_root():
    return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))


def runtime_root():
    return Path(os.environ.get('XDG_RUNTIME_DIR', f'/tmp/cmuxr-{os.getuid()}'))


def socket_path():
    return os.environ.get('CMUS_SOCKET', str(runtime_root() / 'cmuxr-socket'))


def unescape(value):
    result, i = [], 0
    while i < len(value):
        if value[i] == '\\' and i + 1 < len(value):
            i += 1
            result.append('\n' if value[i] == 'n' else value[i])
        else:
            result.append(value[i])
        i += 1
    return ''.join(result)


def request(command):
    if '\n' in command or '\r' in command:
        raise ValueError('Remote commands must occupy one line')
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(.7)
        client.connect(socket_path())
        client.sendall(command.encode() + b'\n')
        data = b''
        while not (data == b'\n' or data.endswith(b'\n\n')):
            chunk = client.recv(65536)
            if not chunk:
                raise ConnectionError('Player disconnected')
            data += chunk
            if len(data) > 4 * 1024 * 1024:
                raise ValueError('Player response too large')
    return data.decode('utf-8', errors='replace').splitlines()


def status():
    result = {}
    for line in request('status'):
        key, _, value = line.partition(' ')
        if key in ('set', 'tag'):
            key, _, value = value.partition(' ')
        result[key] = unescape(value)
    return result


def page(source, offset, limit=128):
    rows, total = {}, 0
    for line in request(f'cmuxr-list {source} {offset} {limit}'):
        if line.startswith('total '):
            total = int(line[6:])
        elif line.startswith('track '):
            _, index, filename = line.split(' ', 2)
            rows[int(index)] = unescape(filename)
        elif line.startswith('error'):
            raise ValueError(line)
    return total, rows


def add_to_library(paths):
    # Absolute filenames keep leading dashes out of the engine's option parser.
    for value in paths:
        path = str(Path(value).expanduser().absolute())
        if any(char in path for char in '\r\n\0'):
            raise ValueError('Library paths cannot contain line breaks or NUL')
        if not Path(path).exists():
            raise ValueError(f'Path does not exist: {path}')
        request('add -l ' + path)


def remove_from_library(path):
    # Identify the actual file, never a row that may have moved after a refresh.
    escaped = str(path).replace('\\', '\\\\').replace('\n', '\\n')
    response = request('cmuxr-remove ' + escaped)
    if any(line.startswith('error') for line in response):
        raise ValueError('\n'.join(response))


def settings():
    try:
        return json.loads((config_root() / 'cmuxr/settings.json').read_text())
    except (OSError, ValueError):
        return {'floor_enabled': True, 'visible_entries': 10}


def save_settings(value):
    target = config_root() / 'cmuxr/settings.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix('.tmp')
    tmp.write_text(json.dumps(value))
    tmp.replace(target)


def bridge(stop):
    """Also runs without Qt in console-only sessions; stale frames expire in DomeD."""
    root = runtime_root()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = root / 'cmuxr-floor.json'
    tmp = root / f'cmuxr-floor.{os.getpid()}.tmp'
    while not stop.is_set():
        try:
            current = status()
            bands = [float(x) for x in current.get('spectrum', '').split()]
            state = {'version': 1, 'timestamp': time.time(),
                     'enabled': bool(settings().get('floor_enabled', True)),
                     'playing': current.get('status') == 'playing', 'bands': bands}
            tmp.write_text(json.dumps(state))
            tmp.chmod(0o600)
            tmp.replace(target)
        except (OSError, ValueError):
            pass
        stop.wait(.05)
    tmp.unlink(missing_ok=True)


def play_directory(path):
    """Load a directory asynchronously, then select it as a playback playlist."""
    request('add -l ' + str(Path(path).parent))
    escaped = str(path).replace('\\', '\\\\').replace('\n', '\\n')
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = request('cmuxr-directory ' + escaped)
        if not response or response == ['']:
            return
        time.sleep(.1)
    raise TimeoutError('Directory is still loading; try playing it again')
