"""Copy title folders with byte progress.

The source is opened only for reading. Each file is written to a temporary
name in the destination and renamed into place when the copy finishes.
Cancelling removes that temporary file. An existing destination file is left
alone when its size already matches.
"""

from __future__ import annotations

import errno
import os
import shutil
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from wfs_studio.paths import validate_copy

CHUNK = 8 * 1024 * 1024
PARTIAL_SUFFIX = ".wfs-studio-partial"
_FULL_ERRNOS = {errno.ENOSPC}
if hasattr(errno, "EDQUOT"):
    _FULL_ERRNOS.add(errno.EDQUOT)


def _disk_full(exc: OSError) -> bool:
    return exc.errno in _FULL_ERRNOS


class Cancelled(Exception):
    """The user stopped the copy."""


@dataclass
class CopyProgress:
    copied_bytes: int
    total_bytes: int
    current_path: str
    file_index: int
    file_count: int
    files_written: int = 0
    files_skipped: int = 0
    error_count: int = 0


@dataclass
class CopyResult:
    copied_bytes: int
    total_bytes: int
    files_written: int
    files_skipped: int
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False
    halted: str = ""


def _ignored(name: str) -> bool:
    return name == ".DS_Store" or name.endswith(PARTIAL_SUFFIX)


def _collect_files(
    title: Path,
    source_root: Path,
    dest_root: Path,
    cancel: threading.Event,
) -> tuple[list[tuple[Path, Path, int]], list[str]]:
    """List regular files to copy. Raises ``Cancelled`` or ``OSError`` for a full disk."""
    planned: list[tuple[Path, Path, int]] = []
    errors: list[str] = []
    seen = 0
    stack = [title]
    while stack:
        if cancel.is_set():
            raise Cancelled()
        current = stack.pop()
        try:
            relative_dir = current.relative_to(source_root)
        except ValueError:
            try:
                relative_dir = current.resolve().relative_to(source_root)
            except (ValueError, OSError):
                errors.append(f"{current} is outside the source")
                continue
        try:
            (dest_root / relative_dir).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            if _disk_full(exc):
                raise
            errors.append(f"{relative_dir}: {exc}")
            continue
        try:
            iterator = os.scandir(current)
        except OSError as exc:
            errors.append(f"{relative_dir}: {exc}")
            continue
        with iterator:
            for entry in iterator:
                seen += 1
                if seen % 200 == 0 and cancel.is_set():
                    raise Cancelled()
                if _ignored(entry.name):
                    continue
                relative = relative_dir / entry.name
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError as exc:
                    errors.append(f"{relative}: {exc}")
                    continue
                planned.append((Path(entry.path), dest_root / relative, size))
    return planned, errors


def _emit(on_progress, progress: CopyProgress, last: list[float], force: bool) -> None:
    now = time.monotonic()
    if not force and now - last[0] < 0.1:
        return
    last[0] = now
    on_progress(replace(progress))


def _copy_one(
    src: Path,
    dest: Path,
    size: int,
    cancel: threading.Event,
    on_bytes,
    skip_same_size: bool,
) -> str:
    """Copy one file. Returns ``written`` or ``skipped``."""
    if skip_same_size and dest.is_file():
        try:
            if dest.stat().st_size == size:
                on_bytes(size)
                return "skipped"
        except OSError:
            pass
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + PARTIAL_SUFFIX)
    try:
        with src.open("rb") as source_file, partial.open("wb") as dest_file:
            while True:
                if cancel.is_set():
                    raise Cancelled()
                block = source_file.read(CHUNK)
                if not block:
                    break
                dest_file.write(block)
                on_bytes(len(block))
        if cancel.is_set():
            raise Cancelled()
        os.replace(partial, dest)
        try:
            shutil.copystat(src, dest, follow_symlinks=True)
        except OSError:
            pass
        return "written"
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def copy_titles(
    jobs: list[tuple[Path, Path]],
    dest_root: Path,
    *,
    skip_same_size: bool,
    cancel: threading.Event,
    on_progress,
) -> CopyResult:
    """Copy title folders into ``dest_root``.

    ``jobs`` is a list of ``(source_root, title_path)``. Paths inside the
    destination match each title's path relative to its source root.
    """
    if not jobs:
        raise ValueError("No titles were selected.")
    source_root = jobs[0][0].expanduser().resolve()
    for root, _title in jobs[1:]:
        if root.expanduser().resolve() != source_root:
            raise ValueError("All titles in one copy must share the same source folder.")
    source_root, dest_root = validate_copy(source_root, dest_root)

    progress = CopyProgress(0, 0, "Counting files", 0, 0)
    last_emit = [0.0]
    _emit(on_progress, progress, last_emit, True)

    planned: list[tuple[Path, Path, int]] = []
    errors: list[str] = []
    for _root, title in jobs:
        if cancel.is_set():
            return CopyResult(0, 0, 0, 0, cancelled=True)
        title = title.expanduser().resolve()
        try:
            found, walk_errors = _collect_files(title, source_root, dest_root, cancel)
        except Cancelled:
            return CopyResult(0, 0, 0, 0, cancelled=True)
        except OSError as exc:
            if _disk_full(exc):
                return CopyResult(
                    0,
                    0,
                    0,
                    0,
                    [str(exc)],
                    halted="Stopped. The destination ran out of space.",
                )
            raise
        planned.extend(found)
        errors.extend(walk_errors)

    total = sum(size for _src, _dest, size in planned)
    copied = 0
    written = 0
    skipped = 0

    def snapshot(current: str, index: int, force: bool = False) -> None:
        progress.copied_bytes = copied
        progress.total_bytes = total
        progress.current_path = current
        progress.file_index = index
        progress.file_count = len(planned)
        progress.files_written = written
        progress.files_skipped = skipped
        progress.error_count = len(errors)
        _emit(on_progress, progress, last_emit, force)

    for index, (src, dest, size) in enumerate(planned, start=1):
        if cancel.is_set():
            snapshot(str(dest.relative_to(dest_root)), index, True)
            return CopyResult(copied, total, written, skipped, errors, cancelled=True)
        display = str(dest.relative_to(dest_root))
        snapshot(display, index, True)
        start = copied

        def on_bytes(amount: int, display: str = display, index: int = index) -> None:
            nonlocal copied
            copied += amount
            snapshot(display, index)

        try:
            outcome = _copy_one(src, dest, size, cancel, on_bytes, skip_same_size)
        except Cancelled:
            snapshot(display, index, True)
            return CopyResult(copied, total, written, skipped, errors, cancelled=True)
        except OSError as exc:
            copied = start
            errors.append(f"{display}: {exc}")
            snapshot(display, index, True)
            if _disk_full(exc):
                return CopyResult(
                    copied,
                    total,
                    written,
                    skipped,
                    errors,
                    halted="Stopped. The destination ran out of space. Completed files were left in place.",
                )
            continue
        if outcome == "written":
            written += 1
        else:
            skipped += 1
    snapshot("Done", len(planned), True)
    return CopyResult(copied, total, written, skipped, errors, cancelled=False)
