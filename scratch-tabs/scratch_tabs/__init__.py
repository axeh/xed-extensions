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
RESTORE_POLL_MS = 100
RESTORE_MAX_POLLS = 100

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
        global _RESTORED
        if not _RESTORED:
            _RESTORED = True
            self._restore_polls = 0
            GLib.timeout_add(RESTORE_POLL_MS, self._restore_when_ready)
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

    # --- restoring ------------------------------------------------------

    def _startup_tab(self):
        """xed's own empty "Unsaved Document 1", if it is still pristine."""
        tab = self.window.get_active_tab()
        # A tab still loading a file also looks untitled and empty; writing into it crashes xed.
        if tab is None or tab.get_state() != Xed.TabState.STATE_NORMAL:
            return None
        doc = tab.get_document()
        if doc.is_untitled() and not doc.get_modified() and doc.get_char_count() == 0:
            return tab
        return None

    def _restore_when_ready(self):
        """Restore once no tab is still loading a file.

        Creating a tab while another one loads at startup crashes xed 3.8.9, and
        waiting also puts our tabs after the files Restore Tabs reopens.
        """
        loading = any(
            Xed.Tab.get_from_document(doc).get_state() == Xed.TabState.STATE_LOADING
            for doc in self.window.get_documents()
        )
        self._restore_polls += 1
        if loading and self._restore_polls < RESTORE_MAX_POLLS:
            return True
        self._restore()
        return False

    def _new_tab(self):
        """Open a tab exactly like Ctrl+N does, and return it.

        Xed.Window.create_tab() is unsafe from Python in xed 3.8.9 (it crashes
        when called at startup). Restore Tabs closes the first untitled tab
        added after the window shows, so retry if ours was the one closed.
        """
        for _ in range(3):
            added = []
            handler = self.window.connect("tab-added", lambda window, tab: added.append(tab))
            try:
                self._activate_action("FileNew")
            finally:
                self.window.disconnect(handler)
            # Not get_active_tab(): early at startup GTK may not switch to the new tab.
            if added and added[0].get_document() in self.window.get_documents():
                return added[0]
        raise RuntimeError("could not open a new tab")

    def _activate_action(self, name):
        for group in self.window.get_ui_manager().get_action_groups():
            action = group.get_action(name)
            if action is not None:
                action.activate()
                return
        raise RuntimeError(f"xed has no {name} action")

    def _restore(self):
        try:
            notes = _STORE.list_notes()
        except OSError as e:
            _warn(f"could not read notes: {e}")
            return False
        if not notes:
            return False
        previous = self.window.get_active_tab()
        reuse = self._startup_tab()
        for note_id, text in notes:
            tab = reuse or self._new_tab()
            doc = tab.get_document()
            if reuse is not None:
                reuse = None
                previous = None
                stale = self._untrack(doc)
                if stale is not None:
                    _STORE.discard(stale)
            else:
                self._untrack(doc)
            doc.begin_not_undoable_action()
            doc.set_text(text, -1)
            doc.end_not_undoable_action()
            doc.place_cursor(doc.get_start_iter())
            doc.set_modified(True)
            self._track(doc, note_id)
        if previous is not None:
            self.window.set_active_tab(previous)
        return False

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
