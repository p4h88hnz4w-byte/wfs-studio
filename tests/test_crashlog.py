import sys
import threading
from pathlib import Path

import pytest

from wfs_studio.crashlog import LOG_LIMIT, install, log_path, shutdown
from wfs_studio.locations import data_dir


@pytest.fixture
def crash_log(tmp_path: Path):
    previous = sys.excepthook
    previous_thread = threading.excepthook
    path = install(tmp_path)
    yield path
    sys.excepthook = previous
    threading.excepthook = previous_thread
    shutdown()


def test_crash_log_follows_the_platform_data_dir(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("WFS_STUDIO_DATA", raising=False)
    home = tmp_path / "home"
    checkout = data_dir(tmp_path, frozen=False)
    mac = data_dir(tmp_path, frozen=True, system="Darwin", home=home)
    linux = data_dir(tmp_path, frozen=True, system="Linux", home=home)
    windows = data_dir(tmp_path, frozen=True, system="Windows", home=home)
    assert log_path(checkout) == checkout / "cache" / "wfs-studio.log"
    assert log_path(mac) == home / "Library" / "Application Support" / "WFS Studio" / "cache" / "wfs-studio.log"
    assert log_path(linux) == home / ".local" / "share" / "wfs-studio" / "cache" / "wfs-studio.log"
    assert log_path(windows) == home / "AppData" / "Roaming" / "WFS Studio" / "cache" / "wfs-studio.log"


def test_startup_and_uncaught_exception_are_written(crash_log: Path):
    try:
        raise RuntimeError("boom-marker")
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    shutdown()
    text = crash_log.read_text(encoding="utf-8")
    assert "WFS Studio" in text
    assert "boom-marker" in text
    assert "RuntimeError" in text
    assert "Unhandled exception" in text


def test_system_exit_is_not_recorded_as_a_crash(crash_log: Path):
    sys.excepthook(SystemExit, SystemExit(0), None)
    shutdown()
    text = crash_log.read_text(encoding="utf-8")
    assert "SystemExit" not in text


def test_a_large_log_is_rotated(tmp_path: Path):
    path = log_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x" * (LOG_LIMIT + 10))
    installed = install(tmp_path)
    try:
        assert installed == path
        assert path.stat().st_size < LOG_LIMIT
        assert (path.parent / "wfs-studio.log.1").is_file()
        assert "WFS Studio" in path.read_text(encoding="utf-8")
    finally:
        shutdown()
