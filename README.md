# xed Scratch Tabs

A plugin for [xed](https://github.com/linuxmint/xed) (Linux Mint's text editor) that keeps your
unsaved "Unsaved Document" tabs across restarts, like Notepad++.

- **New tab (Ctrl+N), type, quit.** No "Save changes?" prompt for scratch tabs. Next time xed
  starts, they come back with their text, still marked unsaved, after the files Restore Tabs reopens.
- **× on a scratch tab** discards it (xed asks first if it has text). Close All does the same.
- **Ctrl+S / Save As** turns it into a normal file; the hidden copy is deleted.
- Text is saved ~2 s after you stop typing, so a crash loses at most a couple of seconds.
- Named files with unsaved edits still get xed's normal prompt.

## Install

Requires xed with Python plugin support (xed 3.8 on Linux Mint has it).

```sh
make install      # symlinks the plugin into ~/.local/share/xed/plugins/
```

Restart xed, then enable **Scratch Tabs** in Edit → Preferences → Plugins.
`make uninstall` removes it. Notes live in `~/.local/share/xed/scratch/`
(`$XDG_DATA_HOME/xed/scratch/`): one `<id>.txt` per note plus `index.json` for their order.

## Tests

```sh
make test     # storage unit tests
make itest    # end-to-end: real xed, headless (Broadway), isolated HOME/settings/D-Bus
```

`make itest` needs `broadwayd` (from GTK 3) and `dbus-run-session`. It never touches your own
xed session, settings or files. `docs/manual-test.md` lists what each test checks.

## Known limitations

- **Logout/shutdown with xed open:** xed blocks logout while any tab is unsaved, and scratch
  tabs stay marked unsaved, so you may get xed's prompt there. Your notes are already on disk
  and survive "Close without saving".
- **Restore Tabs quirk (not this plugin):** after launching xed with a file (e.g. double-click),
  Restore Tabs closes the first new tab you open. This plugin works around it for restored
  notes; a brand-new Ctrl+N tab may still get closed once.
- Only untitled tabs are kept; cursor position, highlighting mode and undo history are not.
- Restore Tabs only records its file list when a window is closed with ×, not on Ctrl+Q.

See `docs/spike-quit-hooks.md` for how each way of closing xed is handled.
