# Spike: can the plugin act before xed's "Save changes?" prompt?

xed 3.8.9, tested headlessly with `tests/integration/xedsandbox.py` (real xed, Broadway backend,
isolated HOME/settings/D-Bus). Spike plugin did `doc.set_modified(False)` on untitled docs in
the hook, then checked whether xed showed its close-confirmation dialog.

## How xed closes (from source, `xed-app.c`, `xed-commands-file.c`)

- Window × → `delete-event` → xed's `window_delete_event` → `_xed_cmd_file_quit(window)` →
  `file_close_all(window, TRUE)`, which calls `xed_window_get_unsaved_documents()` and shows the
  dialog. xed's handler returns TRUE (stops emission).
- Ctrl+Q / File → Quit → `GtkAction` "FileQuit" → `_xed_cmd_file_quit` (no delete-event).
- Close All (Ctrl+Shift+W) → `GtkAction` "FileCloseAll" → `file_close_all(window, FALSE)`.
- Tab × / Ctrl+W → `GtkAction` "FileClose" / tab close button → per-tab prompt.
- Logout: each window with a modified tab holds a `GTK_APPLICATION_INHIBIT_LOGOUT` inhibitor
  ("There are unsaved documents"), driven by the tabs' modified state.

## Results

| Path | Covered | Mechanism | Notes |
|------|---------|-----------|-------|
| Window × | yes | `window.connect("delete-event", ...)` in `do_activate` | Plugin activates before xed-app connects its handler, so ours runs first. Prompt suppressed. |
| Ctrl+Q / File → Quit | yes | `GObject.add_emission_hook(Gtk.Action, "activate", cb)`, filter `action.get_name() == "FileQuit"` | Emission hooks run before handlers. Callback signature is `cb(action)` (no ihint), must return True to stay installed. Hook is process-wide: install once. Prompt suppressed. |
| Closing one of two windows | yes | same `delete-event` handler (cloned windows activate the plugin too) | Second window made via Documents → Move to New Window. |
| Close All / Ctrl+Shift+W | not hooked (by design) | — | Spec: counts as discard, xed's prompt applies. |
| Logout / session end | no | — | Not testable headlessly. Scratch tabs stay "modified", so xed inhibits logout like any unsaved doc. Spec fallback applies: the prompt may show; the note must survive (already on disk; deferred discard never fires once the app exits). |

## Other findings

- `active-plugins` holds libpeas **module** names: `scratch_tabs`, not `scratch-tabs`.
- A scratch tab can move between windows (Move to New Window / drag), firing `tab-removed` in the
  source window. Discard must check that the document is gone from `Xed.App.get_documents()`.
- `Xed.Window.create_tab()` logs harmless GTK criticals under Broadway; the tab works.

**Conclusion — Tasks 3 and 5 hook:** `delete-event` via `window.connect` (window × and closing one
window) and a once-per-process `Gtk.Action::activate` emission hook for `FileQuit` (Ctrl+Q, menu).
