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


if __name__ == "__main__":
    unittest.main()
