"""Append crashes to the user data folder.

The file is ``cache/wfs-studio.log`` under :func:`wfs_studio.locations.data_dir`.
A checkout keeps that next to the project. A frozen app uses Application Support
on macOS, ``~/.local/share/wfs-studio`` on Linux, and ``%APPDATA%`` on Windows.
``WFS_STUDIO_DATA`` overrides the folder. The process working directory is not
used: a Dock or Start Menu launch does not have a useful one, and an app bundle
cannot store the log inside itself.
"""

from __future__ import annotations

import faulthandler
import logging
import platform
import sys
import threading
from pathlib import Path

from wfs_studio import __version__

LOG_NAME = "wfs-studio.log"
LOG_LIMIT = 512 * 1024

_fault_file: object | None = None
_previous_thread_hook = threading.excepthook
_repeat_key = ""
_repeat_count = 0


def log_path(data: Path) -> Path:
    """Return the crash log path for a data directory."""
    return data / "cache" / LOG_NAME


def install(data: Path) -> Path:
    """Open the crash log and send uncaught errors there."""
    global _fault_file
    path = log_path(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    _rotate(path)
    logger = logging.getLogger("wfs_studio")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s")
    )
    logger.addHandler(handler)
    logger.info(
        "WFS Studio %s  python %s  %s %s  frozen=%s  data=%s",
        __version__,
        platform.python_version(),
        sys.platform,
        platform.machine(),
        bool(getattr(sys, "frozen", False)),
        data,
    )
    handler.flush()
    if _fault_file is not None:
        faulthandler.disable()
        _fault_file.close()
    _fault_file = path.open("ab", buffering=0)
    faulthandler.enable(file=_fault_file, all_threads=True)
    sys.excepthook = _excepthook
    threading.excepthook = _thread_hook
    return path


def shutdown() -> None:
    """Close the crash log. Tests use this so the file can be read."""
    global _fault_file
    if _fault_file is not None:
        faulthandler.disable()
        _fault_file.close()
        _fault_file = None
        faulthandler.enable(all_threads=True)
    logger = logging.getLogger("wfs_studio")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def log_failure(where: str) -> None:
    """Write the active exception. Call this from an ``except`` block."""
    global _repeat_key, _repeat_count
    exc_type, exc, _tb = sys.exc_info()
    key = f"{where}:{getattr(exc_type, '__name__', '')}:{exc}"
    if key == _repeat_key:
        _repeat_count += 1
        if _repeat_count > 5:
            return
    else:
        _repeat_key = key
        _repeat_count = 1
    logger = logging.getLogger("wfs_studio")
    logger.exception("%s", where)
    for handler in logger.handlers:
        handler.flush()


def _rotate(path: Path) -> None:
    if not path.is_file() or path.stat().st_size <= LOG_LIMIT:
        return
    backup = path.with_name(path.name + ".1")
    if backup.exists():
        backup.unlink()
    path.replace(backup)


def _excepthook(exc_type, exc, tb) -> None:
    if exc_type is not None and issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        sys.__excepthook__(exc_type, exc, tb)
        return
    logging.getLogger("wfs_studio").critical(
        "Unhandled exception",
        exc_info=(exc_type, exc, tb),
    )
    for handler in logging.getLogger("wfs_studio").handlers:
        handler.flush()
    sys.__excepthook__(exc_type, exc, tb)


def _thread_hook(args: threading.ExceptHookArgs) -> None:
    if args.exc_type is not None and issubclass(args.exc_type, (KeyboardInterrupt, SystemExit)):
        _previous_thread_hook(args)
        return
    logging.getLogger("wfs_studio").critical(
        "Unhandled exception in thread %s",
        getattr(args.thread, "name", "?"),
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )
    for handler in logging.getLogger("wfs_studio").handlers:
        handler.flush()
    _previous_thread_hook(args)
