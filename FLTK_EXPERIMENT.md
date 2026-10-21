# FLTK 1.4.5 experiment

OpenGL FLTK playback form with asynchronous core requests, paged/searchable lists, queue/library commands, spectrum, seek/volume, real command menus and a StatusNotifierItem tray.

This experimental default is preserved in the private `fltk-vr` source
collection. The collection provides a staged local installer with backups;
running desktop and display-manager sessions are never restarted by installation.

```sh
cmake -S fltk -B build-fltk -DCMAKE_PREFIX_PATH=<FLTK prefix>
cmake --build build-fltk --parallel 4
```

The Qt frontend remains selectable with `DE_XR_TOOLKIT=Qt6`.
Use the isolated FLTK **1.4.5** runtime in the parent `_toolkit`; prepend its `lib`
to `LD_LIBRARY_PATH` so the login session's older runtime cannot override it.
The parent `run` launcher handles this. Local bitmap family/style/strike, popup
dismissal, deferred window close, EGL depth and borderless app-ID patches are required.

Desktop core commands and DomeD XR pointer/keyboard paths are covered by isolated fixtures. Full real-library and installation/relocation regression remains outstanding.

Application menu commands are exported over DBusMenu/KDE AppMenu where applicable.
DomeD appearance updates apply live, including native FreeType bitmap strikes.
OpenGL widgets cache glyph textures after rasterization. Bitmap shaping/bidi and
per-glyph fallback, accessibility/IME and broad fractional-scale coverage remain
incomplete. Tests cover selected desktop and DomeD XR input paths, not every
interaction. The local WiVRn server has no connected client: physical Intel GPU
OpenXR validation uses an isolated Monado simulated HMD and does not validate
WiVRn network streaming.

The parent `README.md` contains the suite report, validation commands and remaining
limitations; evidence is in the parent `artifacts/` directory.

Native FLTK file choosers are used without GTK, Zenity or KDialog. Standard
FLTK dialogs inherit the DomeD bitmap font and live palette. The isolated
`first-configure` toolkit patch prevents transient dialogs from freezing while
waiting for a redundant second Wayland configure. Ordinary third-party FLTK
applications need the same appearance hook to follow DomeD automatically.
