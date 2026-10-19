"""Run a real xed headlessly in a throwaway sandbox and drive it with a scenario.

Each sandbox has its own HOME, XDG dirs, GSettings keyfile backend, D-Bus
session and Broadway display, so it never touches the user's running xed,
their settings or their files. A scenario is a Python file defining
``scenario(d)``, a generator run inside xed by the ``scratch_driver`` plugin.
"""

import json
import os
import random
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLUGIN_SRC = REPO / "scratch-tabs"
DRIVER_SRC = Path(__file__).resolve().parent / "driver"


class XedSandbox:
    def __init__(self, plugins=("restore-tabs", "scratch_tabs", "scratch_driver")):
        self.root = Path(tempfile.mkdtemp(prefix="xed-sandbox-"))
        self.home = self.root / "home"
        self.data = self.home / ".local" / "share"
        self.config = self.home / ".config"
        plugdir = self.data / "xed" / "plugins"
        plugdir.mkdir(parents=True)
        self.config.mkdir(parents=True)
        for src in (PLUGIN_SRC, DRIVER_SRC):
            for item in src.iterdir():
                if item.name != "__pycache__":
                    (plugdir / item.name).symlink_to(item)
        keyfile = self.config / "glib-2.0" / "settings" / "keyfile"
        keyfile.parent.mkdir(parents=True)
        active = ", ".join(f"'{p}'" for p in plugins)
        # Restore Tabs' schema default is [''], which opens the cwd as a tab.
        keyfile.write_text(f"[org/x/editor/plugins]\nactive-plugins=[{active}]\n\n"
                           "[com/github/tudo75/xed-restore-tabs-plugin]\nuris=@as []\n")

    @property
    def scratch_dir(self) -> Path:
        return self.data / "xed" / "scratch"

    def run(self, scenario: str, args=(), timeout=30, extra_env=None):
        """Launch xed with ``scenario`` (source text). Returns (log entries, stderr)."""
        scen_file = self.root / "scenario.py"
        scen_file.write_text(scenario)
        log_file = self.root / "driver.log"
        log_file.write_text("")
        display = random.randint(30, 90)
        runtime = self.root / "run"
        runtime.mkdir(mode=0o700, exist_ok=True)
        # broadwayd puts its socket in XDG_RUNTIME_DIR, so it must share xed's.
        broadway = subprocess.Popen(["broadwayd", "--port", str(9000 + display), f":{display}"],
                                    env={**os.environ, "XDG_RUNTIME_DIR": str(runtime)},
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.home),
            "XDG_DATA_HOME": str(self.data),
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_CACHE_HOME": str(self.root / "cache"),
            "XDG_RUNTIME_DIR": str(runtime),
            "GSETTINGS_BACKEND": "keyfile",
            "GDK_BACKEND": "broadway",
            "BROADWAY_DISPLAY": f":{display}",
            "NO_AT_BRIDGE": "1",
            "SCRATCH_DRIVER_SCRIPT": str(scen_file),
            "SCRATCH_DRIVER_LOG": str(log_file),
            "LANG": "C.UTF-8",
            **(extra_env or {}),
        }
        time.sleep(0.3)
        proc = subprocess.Popen(["dbus-run-session", "--", "xed", *args], env=env, cwd=self.root,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                start_new_session=True)
        try:
            out, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            out, _ = proc.communicate()
            out += "\n[sandbox] TIMEOUT: xed killed\n"
        else:
            out += f"\n[sandbox] exit {proc.returncode}\n"
        finally:
            broadway.terminate()
            broadway.wait()
        entries = [json.loads(line) for line in log_file.read_text().splitlines() if line.strip()]
        return entries, out

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


def last(entries, key):
    """The last logged entry containing ``key``."""
    for e in reversed(entries):
        if key in e:
            return e
    raise AssertionError(f"no log entry with {key!r} in {entries!r}")
