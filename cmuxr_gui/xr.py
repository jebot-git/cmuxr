# SPDX-License-Identifier: GPL-2.0-or-later
"""Prefer the DomeD desktop; standalone OpenXR is a fallback only."""
import http.client
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def server_url(explicit=None):
    value = explicit or f"http://127.0.0.1:{os.environ.get('DOME_PREVIEW_PORT', '49640')}"
    parsed = urlsplit(value)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('DomeD server must be http://127.0.0.1:PORT')
    if not parsed.port or not 0 < parsed.port <= 65535:
        raise ValueError('DomeD server requires a valid port')
    return f'http://127.0.0.1:{parsed.port}'


def get_json(server, path):
    connection = http.client.HTTPConnection('127.0.0.1', urlsplit(server).port, timeout=.5)
    try:
        connection.request('GET', path)
        response = connection.getresponse()
        if response.status != 200:
            raise ConnectionError(f'DomeD returned HTTP {response.status}')
        return json.loads(response.read(2 * 1024 * 1024))
    finally:
        connection.close()


def dome_in_use():
    desktops = (os.environ.get('XDG_CURRENT_DESKTOP', '') + ':' + os.environ.get('XDG_SESSION_DESKTOP', '')).lower().split(':')
    if 'dome' in desktops or 'domed' in desktops:
        return True
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            if process.stat().st_uid == os.getuid() and (process / 'comm').read_text().strip() == 'dome-compositor':
                return True
        except OSError:
            pass
    return False


def route(explicit=None):
    server = server_url(explicit)
    try:
        integration = get_json(server, '/api/integrations/mpvr')
        # This endpoint is supplied by a native DomeD compositor, not dome-preview.
        if 'compositor_pid' not in integration or 'xr_socket' not in integration:
            raise ConnectionError('No native DomeD compositor at this address')
        return ('domed-existing' if integration.get('xr_active') else 'domed', server)
    except (OSError, ValueError, http.client.HTTPException) as error:
        if explicit or dome_in_use():
            raise RuntimeError(f'DomeD is in use but its control service is unavailable: {error}') from error
        return 'fallback', server
