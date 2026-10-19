"""Scratch Tabs: keep untitled xed tabs across restarts, like Notepad++.

Every untitled tab's text is saved (debounced) to a hidden folder by
``store.ScratchStore``. Quitting or closing a window keeps the notes and skips
xed's "Save changes?" prompt for them; closing a single tab discards its note;
saving it to a real file drops the hidden copy. See
docs/superpowers/specs/2026-10-19-scratch-tabs-design.md.
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
DISCARD_DELAY_MS = 500
CLOSE_POLL_MS = 200

_STORE = ScratchStore(default_root())
_RESTORED = False
_INSTANCES = set()
_QUIT_HOOK_INSTALLED = False
# Note id of every scratch document, shared by all windows so a tab moved to
# another window keeps its note.
_NOTE_IDS = {}
# Documents the user asked to close (tab ×, Ctrl+W, Close All). Only these lose
# their note when their tab goes away; tabs closed any other way (another
# plugin, a window closing) keep it.
_USER_CLOSING = set()


def _warn(msg):
    print(f"scratch-tabs: {msg}", file=sys.stderr)


def _text(doc):
    return doc.get_text(doc.get_start_iter(), doc.get_end_iter(), True)


def _owner(action):
    """The plugin instance whose window this GtkAction belongs to."""
    for instance in _INSTANCES:
        for group in instance.window.get_ui_manager().get_action_groups():
            if group.get_action(action.get_name()) == action:
                return instance
    return None


def _on_action_activate(action):
    """Emission hook: runs before xed's own handler for every GtkAction."""
    name = action.get_name()
    if name not in ("FileQuit", "FileClose", "FileCloseAll"):
        return True
    instance = _owner(action)
    if instance is None:
        return True
    if name == "FileQuit":
        instance._on_closing()
    elif name == "FileClose":
        tab = instance.window.get_active_tab()
        if tab is not None:
            instance._mark_user_closing([tab.get_document()])
    else:
        instance._mark_user_closing(instance.window.get_documents())
    return True


def _on_tab_close_request(notebook, tab):
    """Emission hook for a tab's own × button."""
    for instance in _INSTANCES:
        if tab.get_document() in instance._handlers:
            instance._mark_user_closing([tab.get_document()])
    return True


class ScratchTabsWindowActivatable(GObject.Object, Xed.WindowActivatable):
    window = GObject.Property(type=Xed.Window)

    def do_activate(self):
        global _QUIT_HOOK_INSTALLED, _RESTORED
        self._handlers = {}
        self._timers = {}
        self._closing = False
        self._window_handlers = [
            self.window.connect("tab-added", self._on_tab_added),
            self.window.connect("tab-removed", self._on_tab_removed),
            self.window.connect("delete-event", self._on_delete_event),
        ]
        for doc in self.window.get_documents():
            if doc.is_untitled():
                self._track(doc)
        _INSTANCES.add(self)
        if not _RESTORED:
            _RESTORED = True
            self._restore_polls = 0
            GLib.timeout_add(RESTORE_POLL_MS, self._restore_when_ready)
        if not _QUIT_HOOK_INSTALLED:
            GObject.add_emission_hook(Gtk.Action, "activate", _on_action_activate)
            GObject.add_emission_hook(Xed.Notebook, "tab-close-request", _on_tab_close_request)
            _QUIT_HOOK_INSTALLED = True

    def do_deactivate(self):
        self._save_all()
        for doc in list(self._handlers):
            self._untrack(doc)
        for handler in self._window_handlers:
            self.window.disconnect(handler)
        _INSTANCES.discard(self)

    # --- tracking -------------------------------------------------------

    def _track(self, doc, note_id=None):
        """Watch ``doc`` in this window; keeps its existing note id if it has one."""
        if note_id is None:
            note_id = _NOTE_IDS.get(doc) or _STORE.new_id()
        _NOTE_IDS[doc] = note_id
        if doc not in self._handlers:
            self._handlers[doc] = [
                doc.connect("changed", self._schedule_save),
                doc.connect("loaded", self._on_loaded),
                doc.connect("saved", self._on_saved),
            ]
        return note_id

    def _untrack(self, doc):
        """Stop watching ``doc`` in this window. The note itself is kept."""
        timer = self._timers.pop(doc, None)
        if timer is not None:
            GLib.source_remove(timer)
        for handler in self._handlers.pop(doc, []):
            doc.disconnect(handler)
        return _NOTE_IDS.get(doc)

    def _forget(self, doc):
        """Untrack ``doc`` and delete its note for good."""
        self._untrack(doc)
        note_id = _NOTE_IDS.pop(doc, None)
        if note_id is not None:
            _STORE.discard(note_id)

    def _on_tab_added(self, window, tab):
        doc = tab.get_document()
        if doc.is_untitled():
            self._track(doc)

    def _on_loaded(self, doc, *args):
        # A tab created to open a file starts out untitled until it loads. If a
        # file was loaded into a scratch tab, keep its stored note: it comes back
        # next start rather than being lost.
        if not doc.is_untitled():
            self._untrack(doc)
            _NOTE_IDS.pop(doc, None)

    def _on_saved(self, doc, *args):
        # Save As succeeded: it is a real file now. A cancelled or failed save leaves it untitled.
        if not doc.is_untitled():
            self._forget(doc)

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
            # Drop the throwaway id tab-added gave this blank tab; never stored.
            self._untrack(doc)
            _NOTE_IDS.pop(doc, None)
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
        note_id = _NOTE_IDS.get(doc)
        if note_id is None:
            return
        if not doc.is_untitled():
            self._forget(doc)
            return
        text = _text(doc)
        try:
            if text:
                _STORE.write(note_id, text)
            else:
                _STORE.discard(note_id)
        except OSError as e:
            _warn(f"could not save note {note_id}: {e}")

    def _save_all(self):
        for doc in list(self._handlers):
            timer = self._timers.pop(doc, None)
            if timer is not None:
                GLib.source_remove(timer)
            self._save_now(doc)

    # --- closing --------------------------------------------------------

    def _on_delete_event(self, window, event):
        self._on_closing()
        return False

    def _on_closing(self):
        """The window is about to close (window ×, Ctrl+Q): keep every note.

        Runs before xed builds its "Save changes?" list. Marking scratch tabs
        unmodified keeps them out of that list; if the close is cancelled they
        are marked modified again.
        """
        if self._closing:
            return
        self._closing = True
        self._save_all()
        for doc in self._handlers:
            doc.set_modified(False)
        GLib.timeout_add(CLOSE_POLL_MS, self._check_close_cancelled)

    def _close_dialog_open(self):
        """xed's own "Save changes?" dialog is showing for this window."""
        return any(w.__gtype__.name == "XedCloseConfirmationDialog" and w.get_visible()
                   and w.get_transient_for() == self.window
                   for w in Gtk.Window.list_toplevels())

    def _mark_user_closing(self, docs):
        marked = [doc for doc in docs if doc in self._handlers]
        _USER_CLOSING.update(marked)
        if marked:
            GLib.timeout_add(CLOSE_POLL_MS, self._clear_user_closing, marked)

    def _clear_user_closing(self, docs):
        """Once xed's prompt is gone, forget marks on tabs that were not closed (Cancel)."""
        if self not in _INSTANCES:
            _USER_CLOSING.difference_update(docs)
            return False
        if self._close_dialog_open():
            return True
        open_docs = self.window.get_documents()
        _USER_CLOSING.difference_update(doc for doc in docs if doc in open_docs)
        return False

    def _check_close_cancelled(self):
        if self not in _INSTANCES:
            return False
        if self._close_dialog_open():
            return True
        # Dialog gone (or never shown) and the window is still here: close was cancelled.
        self._closing = False
        for doc in self._handlers:
            if doc.get_char_count() > 0:
                doc.set_modified(True)
        return False

    def _on_tab_removed(self, window, tab):
        doc = tab.get_document()
        if doc not in self._handlers:
            return
        self._untrack(doc)
        if doc in _USER_CLOSING:
            _USER_CLOSING.discard(doc)
            if not self._closing:
                GLib.timeout_add(DISCARD_DELAY_MS, self._discard_if_closed, doc)

    def _discard_if_closed(self, doc):
        """Delete the note of a tab the user closed, unless it went elsewhere after all.

        Delayed so that a tab moved to another window, a window being closed,
        or the whole app quitting (even through a prompt we could not skip)
        never loses its note.
        """
        app = Xed.App.get_default()
        if (self._closing
                or self not in _INSTANCES
                or self.window not in app.get_main_windows()
                or doc in app.get_documents()):
            return False
        note_id = _NOTE_IDS.pop(doc, None)
        if note_id is not None:
            _STORE.discard(note_id)
        return False
