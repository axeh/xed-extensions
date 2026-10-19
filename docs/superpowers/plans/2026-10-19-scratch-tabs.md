# Scratch Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python xed plugin that silently saves untitled tabs to a hidden folder, skips the "Save changes?" prompt for them on quit, and restores them on the next start. An explicit Save turns a note into a normal file, and closing with × discards it.

**Architecture:** There are two layers.
- `store.py` is pure Python with no GI imports, so it's unit-testable without xed. It owns the files on disk: one `<id>.txt` per note plus an ordered `index.json`, all written atomically. There is one `ScratchStore` per process, shared by all windows.
- `__init__.py` is the GTK glue, a `Xed.WindowActivatable`. It tracks untitled documents, debounces saves, hooks the close and quit paths, restores notes once per process, and reacts to Save As and to tab removal.

**Tech Stack:** Python 3.12, PyGObject (`gi.repository`: `Xed 1.0`, `Gtk 3.0`, `GLib`, `GObject`), libpeas `python3` loader, `unittest` from the stdlib (pytest is not installed, and we add no dependencies), and `make`.

**Spec:** `docs/superpowers/specs/2026-10-19-scratch-tabs-design.md`

## Global Constraints

- Target xed 3.8.9 / libpeas 1.36, Python 3.12. There are no third-party Python dependencies.
- Plugin install dir: `~/.local/share/xed/plugins/`. Plugin module name is `scratch_tabs`, the `.plugin` file is `scratch-tabs.plugin`, and it uses `Loader=python3`.
- Storage dir: `$XDG_DATA_HOME/xed/scratch/`, falling back to `~/.local/share/xed/scratch/`. Notes are stored as `<id>.txt` in UTF-8. The order is kept in `index.json`.
- Every file write is atomic: write a temp file, fsync, then `os.replace`.
- Debounce: save 2 seconds after the last change (`SAVE_DELAY_MS = 2000`).
- Only untitled documents (`doc.is_untitled()`) are tracked. Named files are never touched, and their quit prompt must still appear.
- Restored tabs look like normal unsaved "Untitled Document N" tabs. Restoring happens once per process, after the tabs from the Restore Tabs plugin, and also when xed was launched with a file.
- Never patch xed, never keep scratch buffers permanently unmodified, and don't modify the `restore-tabs` plugin.

## Review Focus

These are the failure modes the spec implies that are most likely to bite, with what a user would expect:

1. **`index.json` missing or corrupt** (crash mid-write, manual edit). All `.txt` notes are still restored. Covered by `test_corrupt_index_recovers_orphans` and `test_missing_index_recovers_orphans` in Task 2.
2. **Quit cancelled** because a *named* file triggered the prompt and the user hit Cancel. Scratch tabs look modified again and no note is deleted. Covered by the manual check M5 in Task 5.
3. **Save As cancelled or failed** on a scratch tab. The note stays in the scratch store. Covered by the manual check M7 in Task 6.
4. **Non-ASCII text** (Croatian č ć š ž đ, emoji, CRLF). Notes round-trip byte for byte. Covered by `test_unicode_roundtrip` in Task 2.
5. **xed killed** (`kill -9`) a few seconds after typing. The note is restored, losing at most about 2 seconds of typing. Covered by the manual check M8 in Task 7.

---

## File Structure

```
Makefile                         # install / uninstall / test targets
scratch-tabs/scratch-tabs.plugin # libpeas descriptor
scratch-tabs/scratch_tabs/__init__.py  # ScratchTabsWindowActivatable (GTK glue)
scratch-tabs/scratch_tabs/store.py     # ScratchStore (pure Python)
tests/test_store.py              # unittest for store.py
docs/spike-quit-hooks.md         # Task 1 findings
docs/manual-test.md              # manual checklist (M1–M9), filled in across tasks
```

`make install` symlinks `scratch-tabs/scratch-tabs.plugin` and `scratch-tabs/scratch_tabs/` into `~/.local/share/xed/plugins/`, so edits take effect after restarting xed. `make test` runs `python3 -m unittest discover -s tests -t .` with `PYTHONPATH=scratch-tabs/scratch_tabs`.

---

### Task 1: Repo setup and quit-hook spike

This is the riskiest assumption in the spec, so it goes first. The spike is throwaway; only its findings doc is kept.

**Files:**
- Create: `Makefile`, `scratch-tabs/scratch-tabs.plugin`, `.gitignore` (`__pycache__/`)
- Create (throwaway, deleted at the end of the task): `scratch-tabs/scratch_tabs/__init__.py` spike version
- Create: `docs/spike-quit-hooks.md`

**Interfaces:**
- Produces: the decision recorded in `docs/spike-quit-hooks.md`, which lists for each quit path whether a plugin can run code *before* xed computes `get_unsaved_documents()` and shows its prompt. Tasks 3 and 5 hook exactly the paths marked "covered", using the mechanism recorded here.

- [ ] **Step 1: `git init`, add `.gitignore`, the `Makefile` (`install`, `uninstall`, `test` targets as described above), and `scratch-tabs.plugin`**

  The plugin file uses `Loader=python3`, `Module=scratch_tabs`, `IAge=3`, `Name=Scratch Tabs`, `Description=Keep untitled tabs across restarts, like Notepad++`. Use `/usr/lib/x86_64-linux-gnu/xed/plugins/textsize.plugin` as the format reference.

- [ ] **Step 2: Write the spike plugin**

  It's a `GObject.Object, Xed.WindowActivatable` with `window` as a `GObject.Property`. In `do_activate`, it does the following:
  - Connects `self.window.connect("delete-event", handler)`. The handler prints to stderr, then calls `doc.set_modified(False)` on every untitled document from `self.window.get_documents()` and returns `False`.
  - Looks up the `quit` and `close` actions on `Xed.App.get_default()` and on the window with `lookup_action`, prints which ones exist, and connects to their `activate` signal with a print.

  Read xed 3.8.9's `xed/xed-commands-file.c` and `xed/xed-window.c` (`apt source xed` or GitHub `linuxmint/xed` tag `3.8.9`). Find where `_xed_cmd_file_quit` and `file_close_all` / the delete-event handler compute unsaved documents.

- [ ] **Step 3: Run each quit path by hand and record the results**

  Install with `make install`, enable the plugin in Preferences → Plugins, and run `xed` from a terminal. Before each test, type into a new untitled tab. Test each path:
  - (a) the window's × button
  - (b) File → Close Window, if present
  - (c) Ctrl+Q / File → Quit
  - (d) closing one of two windows
  - (e) a logout or session end. Simulate it with `xed` running, then `cinnamon-session-quit --logout` in a VM or test session if available. Otherwise mark it "not tested".

  For each path, record two things: whether our handler printed *before* the prompt, and whether a prompt appeared for the untitled tab.

- [ ] **Step 4: For each path not covered by `delete-event`, try the fallback, which is re-pointing the accelerator or action**

  Register our own action, `app.scratch-quit`, which runs the handler and then activates the original `quit`. Point `Ctrl+Q` and the menu item at it with `Xed.App.get_default().set_accels_for_action`. If the menu can't be re-pointed, record that.

- [ ] **Step 5: Write `docs/spike-quit-hooks.md`**

  Write one row per path: path, covered (yes or no), mechanism, notes. End with the conclusion "Tasks 3 and 5 hook: …". Any path marked "no" falls under the spec's fallback: the prompt may show, and the note must still survive.

- [ ] **Step 6: Delete the spike `__init__.py` and commit**

```bash
git add .gitignore Makefile scratch-tabs/scratch-tabs.plugin docs/
git commit -m "chore: repo setup and quit-hook spike findings"
```

**Stop condition:** If not even the window × path can run before the prompt, stop and report to the user before continuing. Under the spec, the prompt would then appear on every quit.

---

### Task 2: `ScratchStore` (storage layer)

**Files:**
- Create: `scratch-tabs/scratch_tabs/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Produces:
  - `default_root() -> pathlib.Path` returns `$XDG_DATA_HOME/xed/scratch`, or `~/.local/share/xed/scratch`.
  - `class ScratchStore(root: pathlib.Path)` creates `root` with mode 0700 on first write.
  - `.new_id() -> str` returns `uuid4().hex`. It does not touch disk.
  - `.write(note_id: str, text: str) -> None` atomically writes `<id>.txt` and appends `note_id` to the index if it's missing (also an atomic write).
  - `.discard(note_id: str) -> None` deletes `<id>.txt` and removes it from the index. It's idempotent.
  - `.list_notes() -> list[tuple[str, str]]` returns `(id, text)` in index order, followed by orphan `*.txt` files not in the index (sorted by mtime). It skips notes whose text is empty, and deletes those files and index entries. It ignores `*.tmp` files.

- [ ] **Step 1: Write the failing tests in `tests/test_store.py`**

  Use a `unittest.TestCase` with a `tempfile.TemporaryDirectory()` root.
  - `test_write_then_list_returns_note`: after `write(a, "hello")`, `list_notes()` returns `[(a, "hello")]`.
  - `test_order_is_preserved`: write `a`, `b`, `c`, then rewrite `a`. The ids come back in the order `[a, b, c]`.
  - `test_discard_removes_note_and_is_idempotent`: after `discard(a)` twice with no error, `a` is not in the list and `a.txt` doesn't exist.
  - `test_empty_note_is_dropped`: after `write(a, "")`, `list_notes() == []` and `a.txt` doesn't exist afterwards.
  - `test_unicode_roundtrip`: the text `"čćšžđ ČĆŠŽĐ 🙂\r\nline2\n"` comes back exactly the same.
  - `test_corrupt_index_recovers_orphans`: write `a` and `b`, put `"{not json"` in `index.json`, and both notes are returned.
  - `test_missing_index_recovers_orphans`: write `a`, delete `index.json`, and `a` is returned.
  - `test_tmp_files_ignored`: a stray `x.txt.tmp` file doesn't show up in the list.
  - `test_default_root_uses_xdg`: with `XDG_DATA_HOME=/tmp/q` set via `unittest.mock.patch.dict(os.environ)`, the result is `Path("/tmp/q/xed/scratch")`.

- [ ] **Step 2: Run them and confirm they fail**

  Run: `make test`
  Expected: FAIL, `ModuleNotFoundError: No module named 'store'`. The tests do `import store` directly, and `make test` sets `PYTHONPATH=scratch-tabs/scratch_tabs`. That way the package `__init__.py`, which imports `gi`, is never loaded during tests.

- [ ] **Step 3: Implement `store.py` to match the interfaces above**

  The index is `{"version": 1, "order": [ids]}`. The atomic write helper is `_atomic_write(path: Path, data: str) -> None`. It writes `path.with_suffix(path.suffix + ".tmp")`, flushes, calls `os.fsync`, then `os.replace`. Read the files with `encoding="utf-8", newline=""` so CRLF survives.

- [ ] **Step 4: Run the tests**

  Run: `make test`
  Expected: `OK` (9 tests).

- [ ] **Step 5: Commit**

```bash
git add scratch-tabs/scratch_tabs/store.py tests/test_store.py Makefile
git commit -m "feat: scratch note storage with atomic writes and orphan recovery"
```

---

### Task 3: Plugin skeleton, tracking, and debounced save

**Files:**
- Create: `scratch-tabs/scratch_tabs/__init__.py`
- Create: `docs/manual-test.md` (M1–M3 for now)

**Interfaces:**
- Consumes: `ScratchStore`, `default_root` from Task 2 (`from .store import ScratchStore, default_root`), and the hook mechanism from `docs/spike-quit-hooks.md`.
- Produces (used by Tasks 4–6):
  - Module-level `_STORE = ScratchStore(default_root())` and `_RESTORED = False` (set once per process).
  - `class ScratchTabsWindowActivatable(GObject.Object, Xed.WindowActivatable)` with:
    - `self._ids: dict[Xed.Document, str]`, which maps each tracked untitled document to its note id
    - `self._timers: dict[Xed.Document, int]`, which holds pending GLib timeout ids
    - `self._closing: bool`, which is True while the window is closing or quitting
    - `_track(doc: Xed.Document, note_id: str | None = None) -> str` starts tracking (if `note_id` is None, it calls `_STORE.new_id()`), connects `changed` → `_schedule_save`, and returns the id
    - `_untrack(doc) -> str | None` disconnects handlers, cancels the timer, and returns the id
    - `_schedule_save(doc) -> None` (re)starts a `GLib.timeout_add(SAVE_DELAY_MS, ...)` timer
    - `_save_now(doc) -> None` writes the document's full text (`doc.get_text(start, end, True)`) to the store
    - `_save_all() -> None` calls `_save_now` for every tracked document and cancels its timers

- [ ] **Step 1: Implement the skeleton**

  In `do_activate`, connect the window's `tab-added` signal. If `tab.get_document().is_untitled()`, call `_track(doc)`. Also track untitled tabs that already exist. In `do_deactivate`, call `_save_all()` and disconnect everything; *do not* discard anything. Add a `"delete-event"` handler (and any other mechanism the spike found) that calls `_save_all()` and nothing else yet. Task 5 extends it.

- [ ] **Step 2: Install and smoke test**

  Run: `make install`, then `xed` from a terminal, and enable "Scratch Tabs" in Preferences → Plugins.
  Expected: no Python traceback on stderr.

- [ ] **Step 3: Write M1–M3 in `docs/manual-test.md` and run them**

  - **M1:** Press Ctrl+N and type "abc". After about 3 seconds, `~/.local/share/xed/scratch/` contains one `.txt` file with `abc`, and `index.json` lists its id.
  - **M2:** Type continuously for 5 seconds. The file's mtime only changes about 2 seconds after typing stops.
  - **M3:** Open a named file and edit it. Nothing for it appears in the scratch dir.

- [ ] **Step 4: Commit**

```bash
git add scratch-tabs/scratch_tabs/__init__.py docs/manual-test.md
git commit -m "feat: track untitled tabs and save them with a 2s debounce"
```

---

### Task 4: Restore on startup

**Files:**
- Modify: `scratch-tabs/scratch_tabs/__init__.py`
- Modify: `docs/manual-test.md` (add M4)

**Interfaces:**
- Consumes: `_STORE.list_notes()`, `_track(doc, note_id)`, and `_RESTORED` from Task 3.
- Produces: `_restore() -> bool`, which is a `GLib.idle_add` callback that returns `False`.

- [ ] **Step 1: Implement `_restore`**

  In `do_activate`, if `not _RESTORED`, set it to `True` and schedule `GLib.idle_add(self._restore)`. The idle callback runs after the Restore Tabs plugin has created its tabs, so ours come after.

  For each `(note_id, text)` from `list_notes()`, do the following:
  1. Reuse the startup tab if there is one: an active tab whose document is untitled, unmodified, empty (`get_char_count() == 0`), and not yet a restore target. Only the first note may reuse it. Otherwise call `self.window.create_tab(False)`.
  2. Untrack any id the reused tab got from `tab-added`, and `_STORE.discard` that id.
  3. Set the text inside `doc.begin_not_undoable_action()` / `end_not_undoable_action()` so the restored text can't be undone away.
  4. Call `doc.set_modified(True)`.
  5. Call `_track(doc, note_id)`, so the original id is kept and no duplicate is created.

  Leave the previously active tab active.

- [ ] **Step 2: Write M4 and run it**

  **M4:** Create two scratch tabs, "one" and "two", and open one named file. Quit (click "Close without saving" if any prompt appears). Start `xed` again. The tabs should be: the named file (restored by Restore Tabs), then "one", then "two". Both scratch tabs show the unsaved marker and the "Untitled Document N" title. There should be no extra empty tab, and `index.json` should hold exactly 2 ids. Then start `xed somefile.txt` from scratch. The scratch tabs should be restored there too.

- [ ] **Step 3: Commit**

```bash
git add scratch-tabs/scratch_tabs/__init__.py docs/manual-test.md
git commit -m "feat: restore scratch tabs once per process after Restore Tabs"
```

---

### Task 5: Close and quit behavior

**Files:**
- Modify: `scratch-tabs/scratch_tabs/__init__.py`
- Modify: `docs/manual-test.md` (add M5, M6, M9)

**Interfaces:**
- Consumes: `_save_all`, `_ids`, `_untrack`, `_closing`, and the hook list from the spike.
- Produces:
  - `_prepare_for_close() -> None`
  - `_on_tab_removed(window, tab) -> None`
  - `_discard_later(note_id: str) -> None`

- [ ] **Step 1: Implement `_prepare_for_close`**

  It's called from every path the spike marked "covered". It does the following:
  1. Sets `_closing = True`.
  2. Calls `_save_all()`.
  3. Calls `doc.set_modified(False)` on every tracked document, so xed's prompt only lists named files.
  4. Schedules `GLib.idle_add` to detect a cancelled close. If the window still has tabs after the idle, the close was cancelled, so set `_closing = False` and call `set_modified(True)` on every tracked document that has text.

- [ ] **Step 2: Implement `_on_tab_removed` and deferred discard**

  On `tab-removed`, if the document is tracked, call `_untrack` to get the id. If `_closing`, keep the note. Otherwise call `_discard_later(id)`, which does `GLib.timeout_add(500, ...)`. That callback discards the note only if `self.window` is still in `Xed.App.get_default().get_main_windows()` and `not self._closing`.

  This covers the spec's fallback: if an uncovered quit path shows the prompt and the user clicks "Close without saving", the app or window goes away before the timer fires, so the note survives. "Close All" and Ctrl+Shift+W leave the window open, so their notes are discarded, as the spec says.

- [ ] **Step 3: Write M5, M6, and M9, and run them, together with every path in `docs/spike-quit-hooks.md`**

  - **M5:** Open a scratch tab "keep" and a modified named file. Press Ctrl+Q. The prompt lists only the named file. Click Cancel. The scratch tab shows the unsaved marker again. Wait 3 seconds: `keep` is still on disk.
  - **M6:** In a scratch tab with "bye", click ×. The prompt appears. Click "Close without saving", and within about 1 second the `.txt` file is gone. An empty scratch tab closes with no prompt.
  - **M9:** With two windows open, each with a scratch tab, close window B. A's note stays open, and B's note is still on disk. Quit and restart: both notes come back in one window.

- [ ] **Step 4: Commit**

```bash
git add scratch-tabs/scratch_tabs/__init__.py docs/manual-test.md
git commit -m "feat: skip quit prompt for scratch tabs; × discards"
```

---

### Task 6: Explicit save turns a note into a normal file

**Files:**
- Modify: `scratch-tabs/scratch_tabs/__init__.py`
- Modify: `docs/manual-test.md` (add M7)

**Interfaces:**
- Consumes: `_track` (it connects one more handler), `_untrack`, and `_STORE.discard`.
- Produces: `_on_saved(doc, *args) -> None`

- [ ] **Step 1: Implement it**

  In `_track`, also connect the document's `saved` signal to `_on_saved`. If `not doc.is_untitled()` after the signal, call `_untrack(doc)` and then `_STORE.discard(id)` immediately (no delay). If it's still untitled, the save failed or was cancelled, so do nothing.

- [ ] **Step 2: Write M7 and run it**

  **M7:** In a scratch tab with "x", press Ctrl+S and cancel the dialog. The note is still on disk. Press Ctrl+S again and save as `/tmp/x.txt`. The `.txt` in the scratch dir is gone, and the tab title is `x.txt`. Quit and restart: Restore Tabs reopens `x.txt`, and no scratch duplicate appears.

- [ ] **Step 3: Commit**

```bash
git add scratch-tabs/scratch_tabs/__init__.py docs/manual-test.md
git commit -m "feat: drop scratch copy once a note is saved to a real file"
```

---

### Task 7: Full manual pass and README

**Files:**
- Create: `README.md` (install with `make install`, enable the plugin, where notes live, and the known limitations from the spike doc)
- Modify: `docs/manual-test.md` (add M8)

- [ ] **Step 1: Write M8 and run it**

  **M8:** Type "crash" into a scratch tab, wait 3 seconds, then run `pkill -9 xed`. Restart: "crash" is restored. Repeat, killing xed 0.5 seconds after typing. You may lose that last edit, but no older text is lost and nothing ends up corrupted.

- [ ] **Step 2: Run M1–M9 from a clean scratch dir (`rm -rf ~/.local/share/xed/scratch`) and record pass or fail next to each**

  Expected: all pass, or any failures are explained by "not covered" rows in the spike doc.

- [ ] **Step 3: Run `make test`**

  Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/manual-test.md
git commit -m "docs: README and completed manual test pass"
```
