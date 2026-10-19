"""Test-only xed plugin: runs SCRATCH_DRIVER_SCRIPT's scenario(d) in the first window.

Each value the scenario yields is a delay in milliseconds before it resumes.
Results are written as JSON lines to SCRATCH_DRIVER_LOG.
"""

import json
import os
import traceback

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Xed", "1.0")
from gi.repository import GLib, GObject, Gtk, Xed  # noqa: E402

_STARTED = False


class Driver:
    def __init__(self, window):
        self.window = window
        self._log = open(os.environ["SCRATCH_DRIVER_LOG"], "a", encoding="utf-8")

    def log(self, **entry):
        self._log.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._log.flush()

    @staticmethod
    def text(doc):
        return doc.get_text(doc.get_start_iter(), doc.get_end_iter(), True)

    def tabs(self, window=None):
        window = window or self.window
        out = []
        for doc in window.get_documents():
            out.append({
                "title": doc.get_short_name_for_display(),
                "untitled": doc.is_untitled(),
                "modified": doc.get_modified(),
                "text": self.text(doc),
            })
        return out

    def new_tab(self, text="", window=None):
        tab = (window or self.window).create_tab(True)
        if text:
            tab.get_document().insert_at_cursor(text)
        return tab

    def type(self, tab, text):
        tab.get_document().insert_at_cursor(text)

    def tab(self, index, window=None):
        docs = (window or self.window).get_documents()
        return Xed.Tab.get_from_document(docs[index])

    def close_tab(self, index, window=None):
        """Same as clicking the tab's × (runs xed's FileClose command on it)."""
        window = window or self.window
        window.set_active_tab(self.tab(index, window))
        self.action("FileClose", window)

    def action(self, name, window=None):
        ui = (window or self.window).get_ui_manager()
        for group in ui.get_action_groups():
            act = group.get_action(name)
            if act is not None:
                act.activate()
                return
        raise KeyError(name)

    def close_window(self, window=None):
        """Same as clicking the window's × (synthesises a delete-event)."""
        (window or self.window).close()

    def dialog(self):
        for w in Gtk.Window.list_toplevels():
            if isinstance(w, Gtk.Dialog) and w.get_visible():
                return w
        return None

    def respond(self, response):
        dlg = self.dialog()
        if dlg is None:
            raise AssertionError("no dialog to respond to")
        dlg.response(response)

    def windows(self):
        return Xed.App.get_default().get_main_windows()


class ScratchDriverWindowActivatable(GObject.Object, Xed.WindowActivatable):
    window = GObject.Property(type=Xed.Window)

    def do_activate(self):
        global _STARTED
        if _STARTED:
            return
        _STARTED = True
        ns = {"Gtk": Gtk, "Xed": Xed, "GLib": GLib}
        with open(os.environ["SCRATCH_DRIVER_SCRIPT"], encoding="utf-8") as f:
            exec(compile(f.read(), "scenario", "exec"), ns)
        self._driver = Driver(self.window)
        self._gen = ns["scenario"](self._driver)
        GLib.timeout_add(500, self._step)

    def _step(self):
        try:
            delay = next(self._gen)
        except StopIteration:
            self._driver.log(done=True)
            return False
        except Exception:
            self._driver.log(error=traceback.format_exc())
            Xed.App.get_default().quit()
            return False
        GLib.timeout_add(int(delay), self._step)
        return False

    def do_deactivate(self):
        pass
