# Scratch Tabs: xed plugin design

Date: 2026-10-19
Status: draft, awaiting approval

## Intent

Make xed handle unsaved "Untitled Document" tabs the way Notepad++ handles
its unsaved tabs. The user jots scratch notes into new tabs and never wants
to name or save them. Today xed asks "Save changes?" on quit, so the notes
either get thrown away or force a save dialog. With this plugin, scratch
notes just persist: quit xed, reopen it, and they come back with their text.

Success: the user opens xed, presses Ctrl+N, types, quits, and gets no
prompt. Reopening xed brings the note back as an untitled, unsaved-looking
tab. This works every time.

## Goals

1. **Persist untitled tabs.** Every untitled tab (a document with no file
   location) has its text stored in a hidden folder. The user never sees the
   folder or picks a name.
2. **Look unchanged.** A scratch tab looks like an ordinary unsaved
   "Untitled Document N" tab, both before and after restore. There is no
   special icon or label.
3. **Quit without prompting.** Closing the xed window (or quitting) does
   *not* ask about scratch tabs. They are saved silently.
4. **Restore on startup.** When xed opens a window, all persisted scratch
   tabs reappear with their text, in their previous relative order, after
   the tabs restored by the existing Restore Tabs plugin.
5. **Explicit save converts to a normal file.** Ctrl+S / Save As on a
   scratch tab works as normal. Once the file is saved to disk, the hidden
   copy is deleted and the tab is an ordinary file from then on.
6. **× discards.** Closing a single scratch tab with × (or Ctrl+W) discards
   it permanently.
   - If the tab has text, xed's normal "Save / Close without saving /
     Cancel" prompt is shown.
   - If the tab is empty, it closes silently.
   - Once the tab is actually closed (not cancelled), the hidden copy is
     deleted.
7. **Crash tolerance.** Text is saved shortly after the user stops typing
   (about 2 seconds), so a crash loses at most a few seconds of work.

## Non-goals

- Persisting unsaved *edits to real files* (Notepad++ "backup" of modified
  named files). Only untitled tabs are in scope. Real files with unsaved
  edits keep xed's normal quit prompt.
- Restoring the exact interleaved order of saved files and scratch tabs.
  Scratch tabs come back grouped after the saved files.
- Replacing or modifying the existing Restore Tabs plugin.
- Restoring cursor position, scroll position, syntax highlighting language,
  or undo history of scratch tabs. (Nice to have; see "Left to the builder".)
- Sync across machines, history and versions, or a UI to browse old notes.

## Anti-goals (failure even if it "works")

- **Losing a note.** Any path where text the user typed silently disappears
  without their having pressed × and confirmed is a failure. Examples: a
  write gets interrupted, a restore fails, or two windows overwrite each
  other's data.
- **Suppressing the prompt for real files.** Quitting with a modified named
  file must still prompt.
- **Visible clutter.** Scratch files appearing in Recent Files, the file
  browser, or the window title as a path.
- **Duplicates.** The same note being restored twice (for example, restored
  and then saved again under a new ID while the old copy remains).

## Environment and constraints (verified on the user's machine)

- xed 3.8.9 (Linux Mint package `3.8.9+zena`), libpeas 1.36 with the
  `python3` loader available.
- GI typelib: `/usr/lib/x86_64-linux-gnu/xed/girepository-1.0/Xed-1.0.typelib`
  (`from gi.repository import Xed` works, as in the bundled `joinlines` and
  `textsize` plugins, which are good reference implementations).
- Bundled Python plugin reference: `/usr/lib/x86_64-linux-gnu/xed/plugins/textsize/`.
- Install location for the user's plugin: `~/.local/share/xed/plugins/`
  (does not exist yet). The plugin is enabled via xed Preferences → Plugins,
  stored in gsettings `org.x.editor.plugins active-plugins`.
- **Existing plugin to coexist with:** `restore-tabs` (C plugin,
  `xed-restore-tabs-plugin` 0.0.3, active). It stores saved file URIs in
  gsettings `com.github.tudo75.xed-restore-tabs-plugin uris` and reopens
  them at startup. It ignores untitled documents. Our plugin must not
  interfere with it, and our restored tabs should end up after its tabs.
- Source repo: `/home/huskic/repos/code-mine/xed-extensions/` (empty, not
  yet a git repo).

## Decided design

These are decisions made in conversation. Items marked *(Claude's call)*
were proposed by Claude and not objected to.

### Plugin shape *(Claude's call)*

- One Python 3 plugin named `scratch-tabs`, as a `.plugin` file plus a
  Python module. It implements `Xed.WindowActivatable` for per-window
  behavior. It can also implement `Xed.AppActivatable` if app-level hooks
  are needed.
- The source lives in this repo. A simple install step (Makefile target or
  script) copies or symlinks it into `~/.local/share/xed/plugins/`.

### Storage *(Claude's call)*

- Directory: `$XDG_DATA_HOME/xed/scratch/` (defaults to
  `~/.local/share/xed/scratch/`).
- Each scratch tab gets a stable ID (UUID) attached to its document. Its
  text is stored as `<id>.txt` in UTF-8.
- `index.json` holds the ordered list of IDs (per window; see below).
- All writes are atomic: write a temp file, fsync, then rename.

### Saving

- A debounced save (about 2 s after the last change) on each scratch tab's
  buffer `changed` signal. *(Claude's call)*
- A forced save of all scratch tabs when the window is closing.

### Quit behavior

- When the window is about to close, the plugin first saves every scratch
  tab, then marks those buffers as unmodified. xed's close-confirmation
  logic then skips them, so only modified *named* files trigger the prompt.
- This must run **before** xed's own close-confirmation check. One way is
  to connect to the window's `delete-event` before xed's handler runs. The
  builder must verify the right hook (see Risks).
- If the user cancels quit in xed's prompt (because of a real file), the
  scratch tabs must go back to looking modified.

### Restore behavior

- When the plugin activates on a window at startup, it recreates each tab in
  `index.json` order: a new untitled document with the stored text, then
  sets the buffer's modified flag so the tab looks unsaved.
- Restored tabs go after the tabs restored by Restore Tabs.
- Restoring must not create an *extra* empty "Untitled Document 1" tab, or
  leave one behind. If xed opened an empty untitled tab at startup and we
  restore scratch tabs, the empty one should be reused or closed.

### Explicit save

- When a scratch document gets a real file location (the document's
  `saved` signal, or its location changing), the plugin deletes
  `<id>.txt`, removes the ID from the index, and stops tracking that
  document.

### Closing a single tab (×)

- xed's normal behavior already prompts for modified untitled tabs and
  closes empty ones silently. Keep that.
- When a tracked tab is removed because the user closed it (not because the
  window is closing), delete its `<id>.txt` and remove it from the index.
- The tab-removed path must tell "user closed tab" apart from "window is
  closing" so that quitting doesn't delete everything. The quit path sets a
  flag before tabs are torn down.

### Multiple windows

- Each xed window keeps its own set of scratch tabs.
- **Closing one window while others stay open** saves that window's scratch
  tabs silently, the same as quitting. They are not moved into the
  remaining window. They come back on the next cold start of xed.
  *(Claude's recommendation, accepted by the user)*
- On startup, all persisted scratch tabs are restored into the first window
  that opens. Restore happens once per app start, not on every new window.
  *(Claude's call)*
- Two open windows must never overwrite each other's data. The index must
  hold the union of all live and closed-but-persisted windows' tabs, or each
  window keeps its own index section. *(Claude's call)*

### Bulk close commands *(Claude's call, accepted by the user)*

- "Close All", "Close Others" and Ctrl+Shift+W count as discarding, the same
  as ×. xed's own prompt applies to each tab that has text, and the hidden
  copies of the closed tabs are deleted. No extra hook is needed.

### Startup trigger *(Claude's call, accepted by the user)*

- Scratch tabs are restored on every launch, including when xed is started
  to open a specific file (for example by double-clicking it). This matches
  Notepad++.

### Fallback if the quit prompt can't be skipped *(Claude's recommendation, accepted by the user)*

- If the spike shows a quit path where the plugin cannot run before xed's
  "Save changes?" check (likely logout or session end, possibly Ctrl+Q):
  - Keep Goal 2. Scratch tabs keep looking unsaved.
  - Accept that xed may show the prompt on that path.
  - The note must still survive. The debounced and forced saves mean the
    text is already on disk, and "Close without saving" must **not** delete
    the hidden copy when the whole window or app is closing.
- Do not fall back to keeping scratch buffers permanently "unmodified", and
  do not patch xed.

## Risks for the builder to verify first

1. **Hooking quit before the prompt.** Confirm in xed 3.8.9 source
   (`xed-window.c`, `xed-commands-file.c`, `_xed_cmd_file_quit` /
   `close_all_tabs` / `delete_event`) where the unsaved-documents check
   happens. Find which signal a Python plugin can reliably run code before.
   Check File → Quit, Ctrl+Q, the window × button, and logout/session end.
   This is the riskiest piece; spike it first.
2. **Restore ordering vs. Restore Tabs.** That plugin opens files
   asynchronously. Make sure our tabs land after its tabs, for example by
   restoring on an idle callback or after its loads finish.
3. **"Untitled Document N" numbering.** Make sure restored tabs get normal
   names and don't collide.
4. **Detecting conversion to a real file.** Confirm which signal fires once
   Save As has succeeded, and that a failed or cancelled Save As doesn't
   drop the scratch copy.

## Left to the builder

- Exact debounce interval, file naming, and index format.
- Whether to also persist cursor position or language (only if cheap).
- Logging, which should be minimal and go to stderr or the xed debug output.
- Test approach: unit tests for the storage layer (pure Python, no xed),
  plus a written manual test checklist for the in-xed behaviors.
