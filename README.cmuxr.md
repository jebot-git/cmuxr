# cmuxr

A [cmus](https://github.com/cmus/cmus) fork for [DomeD](https://github.com/jebot-git/DomeD):
console playback, an optional Qt6 player and tray, and an audio-reactive XR floor.
Based on upstream commit `36ae5c4817985239619f2ca0cfe438d322298f3a`
(2026-10-03), pulled 2026-10-20. Upstream history and GPL-2.0-or-later licensing
are retained. The separately built DomeD renderer retains its MIT license.

## Build and install

Dependencies are those of cmus (`./configure --help`), including ncurses, a
decoder and an output backend. Python 3 is required for the launcher; PySide6
(Qt6) is optional for console playback. The tested configuration includes FFmpeg,
FLAC, Vorbis, WAV and ALSA. An ALSA pulse device can route audio through PipeWire.

Build as your user and stage a system installation:

```sh
DESTDIR="$PWD/stage" ./scripts/install-cmuxr.sh /usr/local
# Review stage/usr/local, then install its contents with administrator privileges.
```

For the XR application, use a compatible sibling DomeD checkout:

```sh
CMUXR_WITH_XR=1 CMUXR_DOMED_SOURCE=../DomeD \
  DESTDIR="$PWD/stage" ./scripts/install-cmuxr.sh /usr/local
```

The XR installer applies `integration/domed-music-floor.patch`, tests the floor
module, and builds the release renderer. It installs `cmuxr-floor`, its renderer,
and the same integrated renderer as `dome-xr`, so DomeD's own Start XR command
supports the effect. The installer defaults to `/usr/local`; an explicit prefix
is supported. It installs `cmuxr-core` without replacing the `cmus` executable.
Core plugins, themes and upstream manuals use cmus locations beneath the prefix.

The application menu contains **cmuxr** and, with XR enabled, **cmuxr XR Floor**.
cmuxr is also available in DomeD's **Default Applications** choices for MP3,
FLAC and Ogg audio. Select it there to use it for opening music files.
The desktop entry registers WAV, Opus, AAC and M4A audio as well; playback
requires the corresponding decoder in the installed core. Existing defaults
are preserved. Opening audio starts playback in the current player, or starts
a player if needed; additional selected files are queued.
Manual pages are installed for `man cmuxr` and `man cmuxr-floor`.
User configuration and music libraries remain separate from installed files.

## Run

```sh
cmuxr --console          # terminal player with tray when available
cmuxr --no-gui           # console only; no Qt imports
cmuxr --gui              # Qt6 player
cmuxr --gui --open ~/Music/song.flac  # also accepts local file:// URIs
cmuxr --tray             # hidden initially when a tray is available
cmuxr-floor --size 3x3   # DomeD first; standalone WiVRn fallback if DomeD is absent
cmuxr --floor off        # disable the visible effect persistently
cmuxr --floor on
```

DomeD is the primary XR host. The floor launcher reuses an active DomeD XR
session or starts its renderer against the DomeD control service. It uses a
standalone OpenXR overlay only when DomeD is not in use, and yields that overlay
when DomeD starts. If DomeD is present but its service cannot be reached, the
launcher reports an error instead of starting an unrelated overlay.
`DOME_PREVIEW_PORT` selects its local port (default 49640), or use
`cmuxr-floor --server http://127.0.0.1:PORT`. An explicit server never falls back.

The launcher enables the effect and starts a tray player if needed. Choose a
track and press Enter to play. It uses the current OpenXR runtime; set
`XR_RUNTIME_JSON` for a process-specific override. The headset session and the
main XR application continue running.

## Controls and appearance

The tray provides **Play / Pause**, **Stop**, **List**, an XR floor toggle, and
**Quit cmuxr**. Clicking its icon opens the list. Closing a window hides it to an
available tray; Quit stops playback. Without a tray, the window remains available.
The GUI starts the console engine on a pseudoterminal when needed.

* **Up / Down** select tracks and wrap at either end.
* **Space** pauses or resumes; **Enter** plays the selection.
* **Right** enters a directory or the selected track's directory.
* **Left** opens its parent, or the library from a playlist.
* The source selector opens the current playlist, library or playing directory.
* Mouse scrolling loads more entries and wraps at the ends.

The compact view defaults to ten visible entries. The model caches at most eight
128-entry library/playlist pages. Directory playback creates a separate playlist
containing its direct tracks; existing user playlists are preserved.

Both desktop and XR use the same Qt6 player. It polls DomeD appearance settings
for the light/dark scheme, accent, global font, font size and chrome opacity.
The compact controls and library concept are inspired by
[qcmus](https://github.com/neoaggelos/qcmus); no qcmus source is copied.

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
make -j4
python3 -m unittest discover -s tests -v
./scripts/integrate-domed.sh ../DomeD
```

Tests use a real console engine through its pseudoterminal and Unix socket for
paged listing, Unicode/escaped filenames, selection, directory context and stop.
With PySide6 they also check keyboard wrapping and directory navigation.
Spectrum tests cover silence and frequency discrimination across PCM formats.
XR routing tests cover DomeD reuse, service selection, fallback restrictions and
loopback validation. DomeD tests cover stale/disabled/paused frames and floor tiles.

The Qt6 frontend has been checked offscreen. A running WiVRn session accepted the
floor as a focused transparent overlay with headset audio and a 3 by 3 metre
extent. Physical room alignment still depends on the runtime's STAGE calibration.

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
