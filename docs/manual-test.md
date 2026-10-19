# Scratch Tabs: test checklist

Each item is automated by `make itest` (real xed in a headless sandbox, see
`tests/integration/`). You can also run them by hand in a real xed. The scratch
folder is `~/.local/share/xed/scratch/`.

| # | Steps | Expected | Automated test |
|---|-------|----------|----------------|
| M1 | Ctrl+N, type `abc`, wait 3 s | Scratch folder has one `.txt` with `abc`; `index.json` lists its id | `test_m1_untitled_tab_is_saved_after_typing` |
| M2 | Type continuously for a few seconds | Nothing written while typing; file appears ~2 s after typing stops | `test_m2_save_is_debounced_until_typing_stops` |
| M3 | Open a named file and edit it | Nothing for it appears in the scratch folder | `test_m3_named_files_are_not_tracked` |
| M4 | Make scratch tabs `one`, `two` and open a named file; close the window; start xed again. Also start `xed somefile.txt` | Tabs: named file, `one`, `two`; scratch tabs show the unsaved marker; no extra empty tab; restored text can't be undone away; launching with a file restores them too | `RestoreTest.test_m4_*` |
| M5 | Scratch tab `keep` (+ optionally a modified named file); quit with window × or Ctrl+Q | No prompt for the scratch tab (only the named file is listed); Cancel leaves the scratch tab marked unsaved and its note on disk | `CloseAndQuitTest.test_m5_*` |
| M6 | Scratch tab `bye` → click its ×; also × on an empty new tab | Prompt appears; "Close without saving" deletes the note within ~1 s; empty tab closes silently | `CloseAndQuitTest.test_m6_*` |
| M6b | Close All (Ctrl+Shift+W) with scratch tabs, "Close without saving" | Notes deleted | `test_close_all_discards_scratch` |
| M9 | Two windows (Documents → Move to New Window), each with a note; close the second | No prompt; its note stays on disk; both come back after restart. Moving a tab between windows keeps a single note | `test_m9_closing_one_window_keeps_its_notes`, `test_moving_tab_to_new_window_keeps_note` |
| M7 | Scratch tab `x`: Ctrl+S then Cancel; then Ctrl+S and save as `x.txt` | Cancel keeps the note; after saving, the hidden copy is gone at once, the tab is `x.txt`, and after restart only `x.txt` comes back (no duplicate) | `SaveAsTest.test_m7_*` |
