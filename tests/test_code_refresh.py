"""code_refresh: after an in-place code update (a push on Streamlit Cloud), the new code is imported."""
import importlib
import os
import sys

import code_refresh


def test_changed_package_is_imported_again(tmp_path, monkeypatch):
    pkg = tmp_path / "refresh_demo_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "utils.py").write_text("OLD = 1\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    assert code_refresh.refresh(pkg) is False, "first call only remembers the files"
    old = importlib.import_module("refresh_demo_pkg.utils")
    assert not hasattr(old, "NEW")
    assert code_refresh.refresh(pkg) is False, "nothing changed"
    assert sys.modules["refresh_demo_pkg.utils"] is old

    (pkg / "utils.py").write_text("OLD = 1\nNEW = 2\n")  # the push
    stat = (pkg / "utils.py").stat()
    os.utime(pkg / "utils.py", ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    assert code_refresh.refresh(pkg) is True
    assert "refresh_demo_pkg.utils" not in sys.modules and "refresh_demo_pkg" not in sys.modules
    from refresh_demo_pkg.utils import NEW  # what failed on Cloud: a name added in the same push

    assert NEW == 2
    for name in ("refresh_demo_pkg", "refresh_demo_pkg.utils"):
        sys.modules.pop(name, None)


def test_the_real_package_is_watched():
    assert (code_refresh.PACKAGE_DIR / "utils.py").is_file()
