"""Scratch Tabs: keep untitled xed tabs across restarts, like Notepad++.

Every untitled tab's text is saved (debounced) to a hidden folder by
``store.ScratchStore``. See docs/superpowers/specs/2026-10-19-scratch-tabs-design.md.
"""

import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Xed", "1.0")
from gi.repository import GLib, GObject, Gtk, Xed  # noqa: E402

from .store import ScratchStore, default_root  # noqa: E402

SAVE_DELAY_MS = 2000

_STORE = ScratchStore(default_root())
_RESTORED = False
_INSTANCES = set()
_QUIT_HOOK_INSTALLED = False


def _warn(msg):
    print(f"scratch-tabs: {msg}", file=sys.stderr)


def _on_action_activate(action):
    """Emission hook: runs before xed's own handler for every GtkAction."""
    if action.get_name() == "FileQuit":
        for instance in list(_INSTANCES):
            instance._on_closing()
    return True


class ScratchTabsWindowActivatable(GObject.Object, Xed.WindowActivatable):
    window = GObject.Property(type=Xed.Window)

    def do_activate(self):
        global _QUIT_HOOK_INSTALLED
        self._ids = {}
        self._handlers = {}
        self._timers = {}
        self._closing = False
        self._window_handlers = [
            self.window.connect("tab-added", self._on_tab_added),
            self.window.connect("delete-event", self._on_delete_event),
        ]
        for doc in self.window.get_documents():
            if doc.is_untitled():
                self._track(doc)
        _INSTANCES.add(self)
        if not _QUIT_HOOK_INSTALLED:
            GObject.add_emission_hook(Gtk.Action, "activate", _on_action_activate)
            _QUIT_HOOK_INSTALLED = True

    def do_deactivate(self):
        self._save_all()
        for doc in list(self._ids):
            self._untrack(doc)
        for handler in self._window_handlers:
            self.window.disconnect(handler)
        _INSTANCES.discard(self)

    # --- tracking -------------------------------------------------------

    def _track(self, doc, note_id=None):
        if note_id is None:
            note_id = _STORE.new_id()
        self._ids[doc] = note_id
        self._handlers[doc] = [
            doc.connect("changed", self._schedule_save),
            doc.connect("loaded", self._on_loaded),
        ]
        return note_id

    def _untrack(self, doc):
        timer = self._timers.pop(doc, None)
        if timer is not None:
            GLib.source_remove(timer)
        for handler in self._handlers.pop(doc, []):
            doc.disconnect(handler)
        return self._ids.pop(doc, None)

    def _on_tab_added(self, window, tab):
        doc = tab.get_document()
        if doc.is_untitled() and doc not in self._ids:
            self._track(doc)

    def _on_loaded(self, doc, *args):
        # A tab created to open a file starts out untitled until it loads.
        if not doc.is_untitled():
            note_id = self._untrack(doc)
            if note_id is not None:
                _STORE.discard(note_id)

    # --- saving ---------------------------------------------------------

    def _schedule_save(self, doc):
        timer = self._timers.pop(doc, None)
        if timer is not None:
            GLib.source_remove(timer)
        self._timers[doc] = GLib.timeout_add(SAVE_DELAY_MS, self._on_save_timer, doc)

    def _on_save_timer(self, doc):
        self._timers.pop(doc, None)
        self._save_now(doc)
        return False

    def _save_now(self, doc):
        note_id = self._ids.get(doc)
        if note_id is None:
            return
        if not doc.is_untitled():
            self._untrack(doc)
            _STORE.discard(note_id)
            return
        text = doc.get_text(doc.get_start_iter(), doc.get_end_iter(), True)
        try:
            if text:
                _STORE.write(note_id, text)
            else:
                _STORE.discard(note_id)
        except OSError as e:
            _warn(f"could not save note {note_id}: {e}")

    def _save_all(self):
        for doc in list(self._ids):
            timer = self._timers.pop(doc, None)
            if timer is not None:
                GLib.source_remove(timer)
            self._save_now(doc)

    # --- closing --------------------------------------------------------

    def _on_delete_event(self, window, event):
        self._on_closing()
        return False

    def _on_closing(self):
        self._save_all()
