# xed Scratch Tabs

A plugin for [xed](https://github.com/linuxmint/xed) (Linux Mint's text editor) that keeps your
unsaved "Unsaved Document" tabs across restarts, like Notepad++.

- **New tab (Ctrl+N), type, quit.** No "Save changes?" prompt for scratch tabs. Next time xed
  starts, they come back with their text, still marked unsaved, after the files Restore Tabs reopens.
- **Closing a scratch tab yourself** (its ×, Ctrl+W, or Close All) discards it. xed asks first if
  it has text; an empty tab closes silently.
- **Ctrl+S / Save As** turns it into a normal file, and the hidden copy is deleted at once.
  Cancelling the save dialog keeps the note.
- Text is saved ~2 s after you stop typing, so a crash loses at most a couple of seconds.
- Named files with unsaved edits still get xed's normal prompt.

## Install

Requires xed with Python plugin support (xed 3.8 on Linux Mint has it).

```sh
make install      # symlinks the plugin into ~/.local/share/xed/plugins/
```

Restart xed, then enable **Scratch Tabs** in Edit → Preferences → Plugins.
`make uninstall` removes it.

## Where notes live

`~/.local/share/xed/scratch/` (or `$XDG_DATA_HOME/xed/scratch/`), readable only by you:
one `<id>.txt` per note (UTF-8) plus `index.json` for their order. Every write is atomic.
If `index.json` is lost or damaged, every `.txt` note is still restored.

## How closing is handled

| What you do | What happens to scratch tabs |
|-------------|------------------------------|
| Window ×, Ctrl+Q, File → Quit | Saved silently, no prompt; restored next start. If xed prompts because of a named file and you Cancel, they stay marked unsaved. |
| Close one of several windows | Its notes are kept and come back next start. |
| Tab ×, Ctrl+W, Close All | Discarded (after xed's prompt if the tab has text). |
| Move a tab to another window | The note moves with it. |
| Another plugin closes a tab | The note is kept. |
| Logout / shutdown with xed open | xed may show its prompt (see limitations). Notes are already on disk. |

## Tests

```sh
make test     # storage unit tests
make itest    # end-to-end: real xed, headless
```

`make itest` runs a real xed with the Broadway backend in a throwaway sandbox (its own HOME,
settings and D-Bus session), driven by a test-only plugin in `tests/integration/driver/`. It never
touches your own xed session, settings or files. It needs `broadwayd` (from GTK 3) and
`dbus-run-session`, and takes about 2 minutes. It covers saving and debouncing, restore order and
startup, quitting and cancelling, closing tabs and windows, moving tabs, Save As, and surviving
`kill -9`.

## Known limitations

- **Logout/shutdown with xed open:** xed blocks logout while any tab is unsaved, and scratch
  tabs stay marked unsaved, so you may get xed's prompt there. Your notes survive
  "Close without saving".
- **Restore Tabs quirk (not this plugin):** after launching xed with a file (e.g. double-click),
  Restore Tabs closes the first new tab you open. This plugin works around it for restored
  notes; a brand-new Ctrl+N tab may still get closed once.
- Restore Tabs only records its file list when a window is closed with ×, not on Ctrl+Q.
- Only untitled tabs are kept; cursor position, highlighting mode and undo history are not.
- While the plugin is disabled, closing or saving a scratch tab doesn't remove its note, so it
  comes back when the plugin is re-enabled.
- One xed process at a time: two `xed --standalone` instances share the same notes folder.
