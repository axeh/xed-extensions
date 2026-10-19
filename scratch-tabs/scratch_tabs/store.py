"""On-disk storage for scratch notes. Pure Python: no GTK, unit-testable.

Layout: ``<root>/<id>.txt`` holds each note's text (UTF-8), ``<root>/index.json``
holds their order. Every write is atomic (temp file, fsync, rename), and notes
whose id is missing from the index are still found, so a crash or a corrupt
index never hides a note.
"""

import json
import os
import uuid
from pathlib import Path


def default_root() -> Path:
    data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data) / "xed" / "scratch"


def _atomic_write(path: Path, data: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class ScratchStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    @property
    def _index_path(self) -> Path:
        return self.root / "index.json"

    def _note_path(self, note_id: str) -> Path:
        return self.root / f"{note_id}.txt"

    def _read_order(self) -> list:
        try:
            order = json.loads(self._index_path.read_text(encoding="utf-8"))["order"]
        except (OSError, ValueError, KeyError, TypeError):
            return []
        return [i for i in order if isinstance(i, str)]

    def _write_order(self, order: list) -> None:
        _atomic_write(self._index_path, json.dumps({"version": 1, "order": order}))

    def new_id(self) -> str:
        return uuid.uuid4().hex

    def write(self, note_id: str, text: str) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        _atomic_write(self._note_path(note_id), text)
        order = self._read_order()
        if note_id not in order:
            order.append(note_id)
            self._write_order(order)

    def discard(self, note_id: str) -> None:
        self._note_path(note_id).unlink(missing_ok=True)
        order = self._read_order()
        if note_id in order:
            order.remove(note_id)
            self._write_order(order)

    def list_notes(self) -> list:
        if not self.root.is_dir():
            return []
        order = self._read_order()
        orphans = sorted((p for p in self.root.glob("*.txt") if p.stem not in order),
                         key=lambda p: p.stat().st_mtime)
        notes, kept = [], []
        for note_id in order + [p.stem for p in orphans]:
            path = self._note_path(note_id)
            try:
                with open(path, encoding="utf-8", errors="replace", newline="") as f:
                    text = f.read()
            except FileNotFoundError:
                continue
            if text == "":
                path.unlink(missing_ok=True)
                continue
            notes.append((note_id, text))
            kept.append(note_id)
        if kept != order:
            self._write_order(kept)
        return notes
