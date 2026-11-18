"""Back up extracted Wii U saves in SaveMii's folder layout.

This copies ``usr/save/<high>/<low>/user`` into a PC folder SaveMii can
restore. It does not edit save contents, and it does not write into the dump.
"""

from __future__ import annotations

import json
import re
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from wfs_studio.copy_job import CopyResult, copy_titles, tree_totals
from wfs_studio.gametdb import GameTdb, lookup
from wfs_studio.paths import PathIssue, validate_copy
from wfs_studio.titles import meta_fields

_HEX8 = re.compile(r"^[0-9a-fA-F]{8}$")
_PROFILE = re.compile(r"^[0-9a-fA-F]{8}$")
_FORBIDDEN = set('\\/:*?"<>|')
_NAME_LANGS = ("en", "ja", "fr", "de", "es", "it", "nl", "pt", "ru", "ko", "zhtw", "zhcn")
_META_NAME = "savemiiMeta.json"
_SAVEINFO_NAME = "savemii_saveinfo.xml"


@dataclass(frozen=True)
class SaveRecord:
    source_root: Path
    path: Path
    high_id: str
    low_id: str
    name: str
    product_code: str
    profiles: tuple[str, ...]
    has_common: bool
    gametdb_name: str = ""

    @property
    def title_id(self) -> str:
        return f"{self.high_id.lower()}-{self.low_id.lower()}"

    @property
    def user_path(self) -> Path:
        return self.path / "user"

    @property
    def display_name(self) -> str:
        return self.gametdb_name or self.name or self.title_id


def save_root(source: Path) -> Path:
    """Return the ``usr/save`` directory for a dump, or the folder itself."""
    nested = source / "usr" / "save"
    if nested.is_dir():
        return nested
    direct = source / "save"
    if source.name == "usr" and direct.is_dir():
        return direct
    return source


def _localized_name(fields: dict[str, str]) -> str:
    for lang in _NAME_LANGS:
        value = " ".join(fields.get(f"longname_{lang}", "").split())
        if value:
            return value
    for key, value in fields.items():
        if key.startswith("longname_") and value.strip():
            return " ".join(value.split())
    return ""


def fat32_title(name: str) -> str:
    """Match SaveMii's folder-name cleanup: forbidden and non-ASCII become ``_``."""
    parts: list[str] = []
    for char in name:
        if ord(char) > 127 or char in _FORBIDDEN:
            parts.append("_")
        else:
            parts.append(char)
    return "".join(parts).lstrip(" ")


def savemii_dir_name(name: str, high_id: str, low_id: str) -> str:
    """``Title Name [00050000-10174700]``, truncated so the id still fits."""
    ident = f" [{high_id.lower()}-{low_id.lower()}]"
    cleaned = fat32_title(name).rstrip(" .")
    if cleaned in {"", ".", ".."}:
        cleaned = "Untitled"
    room = 255 - len(ident)
    if len(cleaned) > room:
        cleaned = cleaned[:room].rstrip(" .") or "Untitled"
    return f"{cleaned}{ident}"


def _record_from_title(
    high_id: str,
    low: Path,
    database: GameTdb | None,
    source_root: Path,
) -> SaveRecord | None:
    if not low.is_dir() or low.is_symlink() or not _HEX8.fullmatch(low.name):
        return None
    user = low / "user"
    if not user.is_dir():
        return None
    profiles: list[str] = []
    has_common = False
    try:
        children = list(user.iterdir())
    except OSError:
        return None
    for child in children:
        if child.is_symlink() or not child.is_dir():
            continue
        if child.name == "common":
            has_common = True
        elif _PROFILE.fullmatch(child.name):
            profiles.append(child.name)
    if not profiles and not has_common:
        return None
    fields = meta_fields(low / "meta" / "meta.xml")
    name = _localized_name(fields) or f"{high_id}{low.name.lower()}"
    product = fields.get("product_code", "")
    gametdb_name = ""
    if database is not None and product:
        found = lookup(database, product)
        if found is not None:
            gametdb_name = found[1]
    return SaveRecord(
        source_root=source_root,
        path=low,
        high_id=high_id.lower(),
        low_id=low.name.lower(),
        name=name,
        product_code=product,
        profiles=tuple(sorted(profiles, key=str.lower)),
        has_common=has_common,
        gametdb_name=gametdb_name,
    )


def _scan_high(high: Path, high_id: str, database: GameTdb | None, source_root: Path) -> list[SaveRecord]:
    try:
        children = list(high.iterdir())
    except OSError:
        return []
    records: list[SaveRecord] = []
    for low in children:
        record = _record_from_title(high_id, low, database, source_root)
        if record is not None:
            records.append(record)
    return records


def _children_are_titles(path: Path) -> bool:
    try:
        children = list(path.iterdir())
    except OSError:
        return False
    return any(
        child.is_dir() and not child.is_symlink() and _HEX8.fullmatch(child.name) and (child / "user").is_dir()
        for child in children
    )


def scan_saves(source: Path, database: GameTdb | None = None) -> list[SaveRecord]:
    """Find title save folders. ``usr/save/system`` is not a game save.

    ``source`` may be the dump, ``usr``, ``usr/save``, one high id such as
    ``usr/save/00050000``, or a single title folder.
    """
    root = save_root(source)
    if not root.is_dir():
        return []
    if (root / "user").is_dir() and _HEX8.fullmatch(root.name):
        parent = root.parent
        high_id = parent.name if _HEX8.fullmatch(parent.name) else "00050000"
        found = _record_from_title(high_id, root, database, root.parent)
        records = [found] if found is not None else []
    elif _children_are_titles(root):
        high_id = root.name if _HEX8.fullmatch(root.name) else "00050000"
        records = _scan_high(root, high_id, database, root)
    else:
        records = []
        try:
            highs = list(root.iterdir())
        except OSError:
            return []
        for high in highs:
            if not high.is_dir() or high.is_symlink() or not _HEX8.fullmatch(high.name):
                continue
            records.extend(_scan_high(high, high.name, database, root))
    records.sort(key=lambda item: (item.display_name.lower(), item.title_id))
    return records


def _metadata(record: SaveRecord, storage: str, when: datetime) -> dict[str, str]:
    return {
        "Date": when.strftime("%d/%m/%Y %H:%M"),
        "serialId": "_WIIU_",
        "storage": storage,
        "tag": "WFS Studio",
        "highID": record.high_id.lower(),
        "lowID": record.low_id.lower(),
        "vWiiHighID": "00000000",
        "vWiiLowID": "00000000",
        "shortName": record.display_name,
        "backupFormat": "FILES",
        "backupHealth": "0",
    }


def _next_slot(title_dir: Path) -> int:
    for number in range(256):
        slot = title_dir / str(number)
        if not slot.exists():
            return number
    raise PathIssue("All 256 SaveMii slots already exist for this title.")


def backup_saves(
    records: list[SaveRecord],
    dest_root: Path,
    *,
    storage: str = "NAND",
    cancel: threading.Event | None = None,
    on_progress=None,
    when: datetime | None = None,
) -> CopyResult:
    """Copy each save into ``dest/Title [high-low]/<slot>/``.

    The slot holds the profile folders, ``common`` when present,
    ``savemii_saveinfo.xml``, and ``savemiiMeta.json``.
    """
    if storage not in {"NAND", "USB"}:
        raise PathIssue("Save storage must be NAND or USB.")
    if not records:
        raise PathIssue("No saves were selected.")
    if cancel is None:
        cancel = threading.Event()
    stamp = when or datetime.now()
    copied = 0
    total = 0
    written = 0
    skipped = 0
    errors: list[str] = []

    for record in records:
        if cancel.is_set():
            return CopyResult(copied, total, written, skipped, errors, cancelled=True)
        folder_name = savemii_dir_name(record.display_name, record.high_id, record.low_id)
        title_dir = dest_root / folder_name
        try:
            slot_number = _next_slot(title_dir)
            slot_dir = title_dir / str(slot_number)
            validate_copy(record.user_path, slot_dir)
        except PathIssue as exc:
            errors.append(f"{record.display_name}: {exc}")
            continue

        def wrapped(progress, copied=copied, total=total, written=written, skipped=skipped) -> None:
            if on_progress is None:
                return
            on_progress(
                progress.__class__(
                    copied_bytes=copied + progress.copied_bytes,
                    total_bytes=total + progress.total_bytes,
                    current_path=progress.current_path,
                    file_index=progress.file_index,
                    file_count=progress.file_count,
                    files_written=written + progress.files_written,
                    files_skipped=skipped + progress.files_skipped,
                    error_count=len(errors) + progress.error_count,
                )
            )

        result = copy_titles(
            [(record.user_path, record.user_path)],
            slot_dir,
            skip_same_size=True,
            cancel=cancel,
            on_progress=wrapped,
        )
        copied += result.copied_bytes
        total += result.total_bytes
        written += result.files_written
        skipped += result.files_skipped
        errors.extend(result.errors)
        if result.halted:
            return CopyResult(copied, total, written, skipped, errors, halted=result.halted)
        if result.cancelled or cancel.is_set():
            return CopyResult(copied, total, written, skipped, errors, cancelled=True)

        saveinfo = record.path / "meta" / "saveinfo.xml"
        extra_files = 1
        extra_bytes = 0
        if saveinfo.is_file() and not saveinfo.is_symlink():
            target = slot_dir / _SAVEINFO_NAME
            shutil.copyfile(saveinfo, target)
            extra_files += 1
            extra_bytes += target.stat().st_size
            written += 1
        payload = _metadata(record, storage, stamp)
        meta_path = slot_dir / _META_NAME
        meta_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        extra_bytes += meta_path.stat().st_size
        written += 1

        source_totals = tree_totals(record.user_path, cancel)
        dest_totals = tree_totals(slot_dir, cancel)
        if source_totals is None or dest_totals is None:
            return CopyResult(copied, total, written, skipped, errors, cancelled=True)
        expected = (source_totals[0] + extra_files, source_totals[1] + extra_bytes)
        if dest_totals != expected:
            errors.append(
                f"{record.display_name}: backup has {dest_totals[0]} files and {dest_totals[1]} bytes; "
                f"expected {expected[0]} files and {expected[1]} bytes."
            )
    return CopyResult(copied, total, written, skipped, errors, verified=not errors)
