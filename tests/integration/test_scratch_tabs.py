"""End-to-end checks (M1–M9 of docs/manual-test.md) against a real, sandboxed xed."""

import json
import unittest

from xedsandbox import XedSandbox, last

QUIT = "    Xed.App.get_default().quit()\n    yield 200\n"


class SandboxTest(unittest.TestCase):
    def setUp(self):
        self.sb = XedSandbox()

    def tearDown(self):
        self.sb.cleanup()

    def run_xed(self, scenario, args=(), timeout=30):
        entries, out = self.sb.run(scenario, args=args, timeout=timeout)
        for e in entries:
            if "error" in e:
                self.fail(f"scenario error:\n{e['error']}")
        self.assertNotIn("Traceback", out, out)
        return entries

    def notes(self):
        """{id: text} of what is stored on disk, plus the index order."""
        d = self.sb.scratch_dir
        if not d.is_dir():
            return {}, []
        texts = {p.stem: p.read_text(encoding="utf-8") for p in d.glob("*.txt")}
        index = d / "index.json"
        order = json.loads(index.read_text())["order"] if index.exists() else []
        return texts, order


class TrackAndSaveTest(SandboxTest):
    def test_m1_untitled_tab_is_saved_after_typing(self):
        self.run_xed('def scenario(d):\n    d.new_tab("abc")\n    yield 3000\n' + QUIT)
        texts, order = self.notes()
        self.assertEqual(list(texts.values()), ["abc"])
        self.assertEqual(order, list(texts))

    def test_m2_save_is_debounced_until_typing_stops(self):
        entries = self.run_xed('''
import os
def scenario(d):
    tab = d.new_tab("a")
    for _ in range(8):
        yield 300
        d.type(tab, "a")
    d.log(while_typing=sorted(os.listdir(os.environ["XDG_DATA_HOME"] + "/xed")))
    yield 2600
''' + QUIT)
        self.assertNotIn("scratch", last(entries, "while_typing")["while_typing"])
        texts, _ = self.notes()
        self.assertEqual(list(texts.values()), ["a" * 9])

    def test_m3_named_files_are_not_tracked(self):
        named = self.sb.root / "named.txt"
        named.write_text("orig\n")
        self.run_xed('''
def scenario(d):
    doc = [x for x in d.window.get_documents() if not x.is_untitled()][0]
    doc.insert_at_cursor("edit ")
    yield 3000
''' + QUIT, args=[str(named)])
        texts, _ = self.notes()
        self.assertEqual(texts, {})


# Window × (Restore Tabs only records its file list on delete-event).
CLOSE_WINDOW = '''
    d.close_window()
    yield 800
    if d.dialog():
        d.log(quit_dialog=True)
        d.respond(Gtk.ResponseType.NO)
    yield 500
'''

LOG_TABS = '''
def scenario(d):
    yield 1500
    d.log(tabs=d.tabs(), windows=len(d.windows()))
''' + QUIT


class RestoreTest(SandboxTest):
    def first_session(self, named):
        self.run_xed('''
def scenario(d):
    d.new_tab("one")
    d.new_tab("two")
    yield 300
''' + CLOSE_WINDOW, args=[str(named)])

    def test_m4_scratch_tabs_restored_after_saved_files(self):
        named = self.sb.root / "named.txt"
        named.write_text("named\n")
        self.first_session(named)
        tabs = last(self.run_xed(LOG_TABS), "tabs")["tabs"]
        self.assertEqual([t["text"] for t in tabs], ["named", "one", "two"])
        for t in tabs[1:]:
            self.assertTrue(t["untitled"])
            self.assertTrue(t["modified"], "restored scratch tab must look unsaved")
        texts, order = self.notes()
        self.assertEqual(len(order), 2)

    def test_m4_no_extra_empty_tab_on_plain_start(self):
        # Without Restore Tabs, xed opens an empty "Unsaved Document 1" at startup.
        self.sb.cleanup()
        self.sb = XedSandbox(plugins=("scratch_tabs", "scratch_driver"))
        self.run_xed('def scenario(d):\n    d.window.get_documents()[0].insert_at_cursor("solo")\n    yield 2600\n' + QUIT)
        tabs = last(self.run_xed(LOG_TABS), "tabs")["tabs"]
        self.assertEqual([t["text"] for t in tabs], ["solo"])
        self.assertTrue(tabs[0]["modified"])

    def test_m4_restored_when_launched_with_a_file(self):
        self.run_xed('def scenario(d):\n    d.new_tab("keep")\n    yield 2600\n' + QUIT)
        other = self.sb.root / "other.txt"
        other.write_text("other\n")
        tabs = last(self.run_xed(LOG_TABS, args=[str(other)]), "tabs")["tabs"]
        self.assertEqual([t["text"] for t in tabs], ["other", "keep"])

    def test_m4_restored_text_is_not_undoable(self):
        self.run_xed('def scenario(d):\n    d.new_tab("keep")\n    yield 2600\n' + QUIT)
        entries = self.run_xed('''
def scenario(d):
    yield 1500
    doc = [x for x in d.window.get_documents() if d.text(x) == "keep"][0]
    d.log(can_undo=doc.can_undo())
''' + QUIT)
        self.assertFalse(last(entries, "can_undo")["can_undo"])


class CloseAndQuitTest(SandboxTest):
    def assert_exited_without_prompt(self, entries):
        self.assertNotIn("quit_dialog", [k for e in entries for k in e])

    def test_m5_window_close_does_not_prompt_for_scratch(self):
        entries = self.run_xed('def scenario(d):\n    d.new_tab("keep")\n    yield 300\n' + CLOSE_WINDOW)
        self.assert_exited_without_prompt(entries)
        self.assertEqual(list(self.notes()[0].values()), ["keep"])

    def test_m5_ctrl_q_does_not_prompt_for_scratch(self):
        entries = self.run_xed('''
def scenario(d):
    d.new_tab("keep")
    yield 300
    d.action("FileQuit")
    yield 800
    if d.dialog():
        d.log(quit_dialog=True)
        d.respond(Gtk.ResponseType.NO)
    yield 500
''')
        self.assert_exited_without_prompt(entries)
        self.assertEqual(list(self.notes()[0].values()), ["keep"])

    def test_m5_cancelled_quit_keeps_scratch_looking_unsaved(self):
        named = self.sb.root / "named.txt"
        named.write_text("named\n")
        entries = self.run_xed('''
def scenario(d):
    yield 500
    [x for x in d.window.get_documents() if not x.is_untitled()][0].insert_at_cursor("edit ")
    d.new_tab("")  # Restore Tabs closes the first new tab after launching with a file
    d.new_tab("keep")
    yield 300
    d.action("FileQuit")
    yield 800
    d.log(prompted=[x.get_short_name_for_display() for x in d.window.get_unsaved_documents()],
          dialog=d.dialog() is not None)
    d.respond(Gtk.ResponseType.CANCEL)
    yield 3000
    d.log(tabs=d.tabs())
''' + QUIT, args=[str(named)])
        prompted = last(entries, "prompted")
        self.assertTrue(prompted["dialog"])
        self.assertEqual(prompted["prompted"], ["named.txt"])
        scratch = [t for t in last(entries, "tabs")["tabs"] if t["untitled"]]
        self.assertEqual([(t["text"], t["modified"]) for t in scratch], [("keep", True)])
        self.assertEqual(list(self.notes()[0].values()), ["keep"])

    def test_m6_closing_tab_with_text_prompts_then_discards(self):
        entries = self.run_xed('''
def scenario(d):
    d.new_tab("bye")
    yield 2600
    d.close_tab(len(d.window.get_documents()) - 1)
    yield 500
    d.log(dialog=d.dialog() is not None)
    d.respond(Gtk.ResponseType.NO)
    yield 1500
''' + QUIT)
        self.assertTrue(last(entries, "dialog")["dialog"])
        self.assertEqual(self.notes(), ({}, []))

    def test_m6_closing_empty_tab_does_not_prompt(self):
        entries = self.run_xed('''
def scenario(d):
    d.new_tab("")
    yield 300
    d.close_tab(len(d.window.get_documents()) - 1)
    yield 500
    d.log(dialog=d.dialog() is not None)
''' + QUIT)
        self.assertFalse(last(entries, "dialog")["dialog"])

    def test_close_all_discards_scratch(self):
        self.run_xed('''
def scenario(d):
    d.new_tab("a")
    d.new_tab("b")
    yield 2600
    d.action("FileCloseAll")
    yield 500
    d.respond(Gtk.ResponseType.NO)
    yield 1500
''' + QUIT)
        self.assertEqual(self.notes(), ({}, []))

    def test_m9_closing_one_window_keeps_its_notes(self):
        entries = self.run_xed('''
def scenario(d):
    d.new_tab("in-w1")
    d.new_tab("in-w2")
    yield 300
    d.action("DocumentsMoveToNewWindow")
    yield 2600
    w2 = [w for w in d.windows() if w != d.window][0]
    d.close_window(w2)
    yield 1500
    d.log(dialog=d.dialog() is not None, windows=len(d.windows()), w1=[t["text"] for t in d.tabs()])
''' + CLOSE_WINDOW)
        state = last(entries, "windows")
        self.assertFalse(state["dialog"])
        self.assertEqual(state["windows"], 1)
        self.assertEqual(state["w1"], ["in-w1"])
        self.assertEqual(sorted(self.notes()[0].values()), ["in-w1", "in-w2"])
        tabs = last(self.run_xed(LOG_TABS), "tabs")["tabs"]
        self.assertEqual(sorted(t["text"] for t in tabs), ["in-w1", "in-w2"])

    def test_moving_tab_to_new_window_keeps_note(self):
        entries = self.run_xed('''
def scenario(d):
    d.new_tab("stay")
    d.new_tab("moved")
    yield 2600
    d.action("DocumentsMoveToNewWindow")
    yield 1500
    w2 = [w for w in d.windows() if w != d.window][0]
    d.tab(0, w2).get_document().insert_at_cursor("!")
    yield 2600
''' + QUIT)
        self.assertEqual(sorted(self.notes()[0].values()), ["moved!", "stay"])


if __name__ == "__main__":
    unittest.main()
