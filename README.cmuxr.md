# cmuxr

A [cmus](https://github.com/cmus/cmus) fork for [DomeD](https://github.com/jebot-git/DomeD),
with the original console engine, a default FLTK 1.4.5 GUI and a decoded-audio XR
floor. The retained PySide6/Qt6 GUI is an explicit runtime opt-in. Upstream history
and GPL-2.0-or-later licensing remain; the separate DomeD renderer retains MIT.

## Build and stage

The core needs its cmus dependencies (`./configure --help`): ncurses, selected
decoders and an audio output backend. Python 3 runs the launcher/engine bridge.
The default GUI additionally needs CMake 3.21+, C++17, the de-xr patched **FLTK
1.4.5** shared libraries, Fontconfig, GIO, Wayland/X11 headers and
`wayland-scanner`. The FLTK package must include OpenGL/image libraries and the
bitmap-font, app-ID/menu and Wayland dialog fixes described in
[FLTK notes](FLTK_EXPERIMENT.md). Qt/PySide6 is not needed for this frontend.

Build as your regular user and stage both parts:

```sh
DESTDIR="$PWD/stage" ./scripts/install-cmuxr.sh /usr/local
FLTK_PREFIX=/path/to/patched-fltk-1.4.5
cmake -S fltk -B build-fltk -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH="$FLTK_PREFIX"
cmake --build build-fltk --parallel
DESTDIR="$PWD/stage" cmake --install build-fltk --prefix /usr/local
```

The shell installer builds the console core and stages its plugins/data, Python
modules, launcher, desktop entry and manual. **It does not build `cmuxr-fltk`:**
the separate CMake step above is necessary for the default GUI. It installs
`cmuxr-core`, preserving the distribution's `cmus` executable. Review staged
files before privileged system installation. For direct source runs, use the
built `cmus` core and `build-fltk/cmuxr-fltk`; an installed GUI must be on `PATH`
or selected with `CMUXR_FLTK_BINARY`. Set `DE_XR_FLTK_PREFIX` to the matching
patched runtime prefix when the launcher cannot locate it automatically.

For the optional floor renderer, stage the integrated release build using a
compatible sibling DomeD checkout:

```sh
CMUXR_WITH_XR=1 CMUXR_DOMED_SOURCE=../DomeD \
  DESTDIR="$PWD/stage" ./scripts/install-cmuxr.sh /usr/local
```

This applies `integration/domed-music-floor.patch`, tests the floor module and
builds the renderer. It stages `cmuxr-floor`, `cmuxr-floor-renderer` and the
integrated `dome-xr`; review these shared renderer files before installation.
It does not restart an active desktop or headset session. The optional desktop
entry uses a 3 by 3 metre floor. Audio file associations advertise supported
formats without changing existing defaults; actual formats depend on core plugins.

## Launch and configuration

```sh
./cmuxr --no-gui                         # console engine, no GUI toolkit
DE_XR_FLTK_PREFIX=/path/to/patched-fltk-1.4.5 ./cmuxr --gui
cmuxr --console                          # console plus companion when available
cmuxr --gui --open "$HOME/Music/song.flac"
cmuxr --tray                             # hidden if a tray watcher exists
DE_XR_TOOLKIT=Qt6 cmuxr --gui             # explicit PySide6/Qt frontend
cmuxr-floor --size 3x3
cmuxr --floor off
```

An interactive terminal defaults to the console; a graphical nonterminal launch
opens FLTK. A display-less session uses the console. `--gui` does not mean Qt on
this branch, despite the old wording in launcher help. `--no-gui` prevents a GUI
companion. `--open FILE...` accepts local files/file URIs, plays the first and
queues additional selections in an existing engine when possible. Repeated GUI
launches wake the existing frontend. `--floor on|off` alone saves the preference
and exits; `cmuxr-floor` starts the renderer. Only `DE_XR_TOOLKIT=Qt6` opts into
Qt; CMake's toolkit selector is not used for this standalone FLTK subproject.

## FLTK controls

The native form provides asynchronous engine requests, paged/searchable
Playlist/Library/Queue views, seek and volume controls, spectrum, queue/library
commands, exported command menus and a StatusNotifierItem tray. With a tray
watcher, closing hides the window and activation reopens it. Without a watcher,
`--tray` falls back to a visible window. File choosers are native FLTK.

| Input | Action |
| --- | --- |
| Enter / Space | Play selected / play or pause |
| Ctrl+Left / Ctrl+Right | Previous / next track |
| Alt+Left / Alt+Right | Seek backward / forward |
| Ctrl+O / Ctrl+E | Add files / queue selected |
| Delete / F5 | Remove library entry / refresh |
| + / - | Volume up / down |
| Ctrl+Q | Quit |

Removal changes the music library, not audio files. DomeD supplies XR pointer
and keyboard input to the ordinary Wayland surface. Its palette and native
bitmap strike update live; application menus are exported with DBusMenu/KDE
AppMenu when supported. Bitmap shaping/bidi, glyph fallback, accessibility/IME
and fractional-scale coverage remain incomplete. Full real-library and
installation/relocation coverage remains outstanding; simulated XR tests do not
establish physical WiVRn streaming or headset behavior.

## Optional Qt6 interface

Install PySide6 separately and launch with `DE_XR_TOOLKIT=Qt6`. The retained Qt
form has a compact source selector, folder navigation/history and File,
Playback, Go, Library and View menus. Its folder shortcuts include Ctrl+O,
Ctrl+Shift+O, Alt+Left/Right/Up, Ctrl+L and F5. Ctrl+1/2 select library/playlist.
Those controls and `visible_entries` settings describe the Qt interface, not
FLTK feature parity. The frontend polls DomeD appearance settings. The compact
library design is inspired by qcmus; no qcmus source is copied.

## XR routing

`cmuxr-floor` reuses active DomeD XR or starts its renderer attached to DomeD's
control service. It falls back to a standalone OpenXR overlay only when DomeD
is absent, then yields if DomeD starts. If DomeD is present but unreachable,
startup reports an error. `--server http://127.0.0.1:PORT` explicitly selects a
loopback service and forbids fallback; otherwise `DOME_PREVIEW_PORT` selects the
port (default 49640). The floor launcher enables the preference and starts the
selected tray frontend if needed, unless `--no-player` was passed.
`XR_RUNTIME_JSON` selects a process-specific runtime. No display-manager or
currently running main XR application is restarted.

## Floor effect

Sixteen bands are measured from successfully submitted decoded PCM, without
capturing microphone or unrelated system audio. A bridge publishes spectrum
frames at up to 20 Hz, including during console-only playback. DomeD renders a
translucent sixteen-by-sixteen tile equalizer, five millimetres above the STAGE
floor. The visual reference is the coloured LED tile floor at
[Top Dance Floor](https://topdancefloor.com/disco-dance-floor/).

The floor disappears when disabled, paused, stopped, disconnected, or when data
is over 500 ms old. It takes one composition layer, captures no pointer input,
and appears below application/shell layers. Integer PCM with 8/16/24/32-bit
samples and either byte order is supported.

The renderer normally uses runtime STAGE bounds. Some WiVRn builds do not expose
room dimensions; `--size 3x3` explicitly supplies a width/depth while retaining
STAGE floor height and anchoring. The chosen extent is persisted as
`floor_size_m` and is also read by DomeD's own renderer. The application-menu
launcher uses this 3 by 3 metre extent. LOCAL space is never assumed to be a floor.

## Configuration

The launcher uses `$XDG_CONFIG_HOME/cmuxr` (default `~/.config/cmuxr`) and
`$XDG_RUNTIME_DIR/cmuxr-socket`. `CMUS_HOME` and `CMUS_SOCKET` override the engine
locations. Run one player per session; a repeated GUI launch opens its window.
Without a runtime directory, console operation uses a private per-user directory
under `/tmp`. XR spectrum transport requires `XDG_RUNTIME_DIR`.

`cmuxr/settings.json` stores `floor_enabled`, `floor_size_m`, and
`visible_entries` (4–20). DomeD's `dome/appearance.json` controls appearance.
The runtime file `cmuxr-floor.json` contains expiring spectrum frames.

## Validation

```sh
python3 -m unittest discover -s tests -v
./configure --help
./cmuxr --help
./cmuxr-floor --help
```

These include engine protocol/paging, spectrum PCM formats, and floor routing
fixtures; Qt-specific tests need PySide6. Read the individual test prerequisites
before running display/XR tests. FLTK CMake currently defines no CTest suite;
its suite-level fixtures live in the de-xr integration checkout. Physical floor
alignment depends on runtime STAGE calibration. No documentation update alone
validates a connected headset or starts/restarts a runtime.

## Command manuals and related projects

Manuals: [cmuxr.1](docs/man/cmuxr.1) and
[cmuxr-floor.1](docs/man/cmuxr-floor.1). After installation, use `man cmuxr`
and `man cmuxr-floor`.

Part of the [de-xr desktop](https://github.com/topics/de-xr):
[DomeD](https://github.com/jebot-git/DomeD) hosts the desktop/session and integrated floor,
[Ghostty XR](https://github.com/jebot-git/ghostty-xr) provides the terminal,
[mpvr](https://github.com/jebot-git/mpvr) video playback,
[fsvr](https://github.com/jebot-git/fsv-xr) file browsing,
[qimgvr](https://github.com/jebot-git/qimgvr) image viewing,
[Arc SBS](https://github.com/jebot-git/arc-sbs) depth conversion, and
[LightXR](https://github.com/jebot-git/LightXR) the optional login manager.
Each application has its own dependencies and can be used independently where
its selected backend permits.
