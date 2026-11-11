"""Load new code after a push on Streamlit Cloud, without a reboot.

Cloud updates the files in place and keeps the same Python process running. The pages
(views/*.py) are re-run from the new files, but modules already imported (grocery.*) stay
the old version, so a page that uses something added in the same push fails, e.g.
"ImportError: cannot import name 'person_label' from 'grocery.utils'", until the app is
rebooted. app.py calls refresh() before importing grocery: when any of the package's files
changed since the last run, the grocery modules are dropped from sys.modules and the
imports that follow load the new code.

This module tracks changes from the moment it is first imported. When it is itself
deployed for the first time, a reboot is still needed once.
"""
import sys
import threading
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent / "grocery"

_lock = threading.Lock()
_stamps = {}  # package dir -> stamp at the last refresh


def _stamp(package_dir):
    return tuple(sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in Path(package_dir).rglob("*.py")))


def refresh(package_dir=PACKAGE_DIR):
    """Forget the package's modules if any of its files changed since the last call. True if it did."""
    package_dir = Path(package_dir).resolve()
    name = package_dir.name
    with _lock:
        stamp = _stamp(package_dir)
        changed = package_dir in _stamps and _stamps[package_dir] != stamp
        _stamps[package_dir] = stamp
        if changed:
            for module in [m for m in sys.modules if m == name or m.startswith(name + ".")]:
                del sys.modules[module]
        return changed
