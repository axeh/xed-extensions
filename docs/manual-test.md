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
