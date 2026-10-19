import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import store
from store import ScratchStore, default_root


class ScratchStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "scratch"
        self.store = ScratchStore(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def ids(self):
        return [note_id for note_id, _ in self.store.list_notes()]

    def test_write_then_list_returns_note(self):
        a = self.store.new_id()
        self.store.write(a, "hello")
        self.assertEqual(self.store.list_notes(), [(a, "hello")])

    def test_order_is_preserved(self):
        a, b, c = (self.store.new_id() for _ in range(3))
        for note_id in (a, b, c):
            self.store.write(note_id, note_id)
        self.store.write(a, "rewritten")
        self.assertEqual(self.ids(), [a, b, c])

    def test_discard_removes_note_and_is_idempotent(self):
        a = self.store.new_id()
        self.store.write(a, "x")
        self.store.discard(a)
        self.store.discard(a)
        self.assertEqual(self.ids(), [])
        self.assertFalse((self.root / f"{a}.txt").exists())

    def test_empty_note_is_dropped(self):
        a = self.store.new_id()
        self.store.write(a, "")
        self.assertEqual(self.store.list_notes(), [])
        self.assertFalse((self.root / f"{a}.txt").exists())

    def test_unicode_roundtrip(self):
        a = self.store.new_id()
        text = "čćšžđ ČĆŠŽĐ 🙂\r\nline2\n"
        self.store.write(a, text)
        self.assertEqual(ScratchStore(self.root).list_notes(), [(a, text)])

    def test_corrupt_index_recovers_orphans(self):
        a, b = self.store.new_id(), self.store.new_id()
        self.store.write(a, "A")
        self.store.write(b, "B")
        (self.root / "index.json").write_text("{not json")
        self.assertEqual(sorted(ScratchStore(self.root).list_notes()), sorted([(a, "A"), (b, "B")]))

    def test_missing_index_recovers_orphans(self):
        a = self.store.new_id()
        self.store.write(a, "A")
        (self.root / "index.json").unlink()
        self.assertEqual(ScratchStore(self.root).list_notes(), [(a, "A")])

    def test_tmp_files_ignored(self):
        a = self.store.new_id()
        self.store.write(a, "A")
        (self.root / "x.txt.tmp").write_text("half-written")
        self.assertEqual(self.ids(), [a])

    def test_default_root_uses_xdg(self):
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/tmp/q"}):
            self.assertEqual(default_root(), Path("/tmp/q/xed/scratch"))

    def test_default_root_falls_back_to_home(self):
        env = {k: v for k, v in os.environ.items() if k != "XDG_DATA_HOME"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(default_root(), Path.home() / ".local/share/xed/scratch")

    def test_root_is_private(self):
        self.store.write(self.store.new_id(), "secret")
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)


if __name__ == "__main__":
    unittest.main()
