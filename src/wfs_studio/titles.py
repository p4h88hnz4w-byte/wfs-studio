"""Read Wii U title folders and their meta.xml names."""

from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

_HEX8 = re.compile(r"^[0-9a-fA-F]{8}$")
_HEX16 = re.compile(r"^[0-9a-fA-F]{16}$")

KIND_BY_HIGH = {
    "00050000": "Game",
    "00050002": "Demo",
    "0005000b": "Shared data",
    "0005000c": "DLC",
    "0005000e": "Update",
    "00050010": "System",
    "0005001b": "System data",
    "00050030": "Applet",
}

REGION_BITS = (
    (0x01, "JPN"),
    (0x02, "USA"),
    (0x04, "EUR"),
    (0x08, "AUS"),
    (0x10, "CHN"),
    (0x20, "KOR"),
    (0x40, "TWN"),
)

# GameTDB's fourth letter when a region name has to choose among ids.
# Product letter A means every region, so it is not Australia here.
REGION_LETTERS = (
    ("USA", "E"),
    ("JPN", "J"),
    ("EUR", "P"),
    ("KOR", "K"),
    ("CHN", "C"),
    ("TWN", "W"),
    ("AUS", "A"),
)

# Video standard for the consoles that share a region bit. Australia's
# retail consoles are the EUR region, which is PAL. China has no separate mark.
_VIDEO = {
    "JPN": "NTSC-J",
    "USA": "NTSC-U",
    "EUR": "PAL",
    "AUS": "PAL",
    "KOR": "NTSC",
    "TWN": "NTSC",
}

_NAME_LANGS = ("en", "ja", "fr", "de", "es", "it", "nl", "pt", "ru", "ko", "zhs", "zht", "zhtw", "zhcn")
# Fourth letter of the four-character id, used only when meta.xml has no region.
# A is every region. D, F, I, R, S, and X are European language or PAL SKUs.
# Y is another USA mark. Z is used for more than one combination, so it is left unset.
_PRODUCT_REGION = {
    "E": "USA",
    "Y": "USA",
    "J": "JPN",
    "P": "EUR",
    "D": "EUR",
    "F": "EUR",
    "I": "EUR",
    "R": "EUR",
    "S": "EUR",
    "X": "EUR",
    "K": "KOR",
    "C": "CHN",
    "W": "TWN",
    "A": "ALL",
}


@dataclass(frozen=True)
class TitleRecord:
    source_root: Path
    path: Path
    high_id: str
    low_id: str
    kind: str
    name: str
    product_code: str
    region: str
    version: str
    publisher: str
    gametdb_id: str = ""
    gametdb_name: str = ""

    @property
    def title_id(self) -> str:
        if self.high_id and self.low_id:
            return f"{self.high_id.upper()}-{self.low_id.upper()}"
        return self.low_id.upper()

    @property
    def relative_path(self) -> Path:
        return self.path.resolve().relative_to(self.source_root.resolve())


def load_meta_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    sample = raw[:8]
    if sample and sample.count(0) >= 2:
        return raw.decode("utf-16-le", errors="replace")
    return raw.decode("utf-8-sig", errors="replace")


def meta_fields(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        root = ET.fromstring(load_meta_text(path))
    except ET.ParseError:
        return {}
    fields: dict[str, str] = {}
    for element in root.iter():
        tag = element.tag.split("}")[-1].strip().lower()
        value = (element.text or "").strip()
        if value and tag not in fields:
            fields[tag] = value
    return fields


def _one_line(value: str) -> str:
    """Wii U long names put a newline between the two lines on the menu."""
    return " ".join(value.split())


def _localized(fields: dict[str, str], prefix: str) -> str:
    for lang in _NAME_LANGS:
        value = _one_line(fields.get(f"{prefix}_{lang}", ""))
        if value:
            return value
    for key, value in fields.items():
        if key.startswith(prefix + "_") and value:
            cleaned = _one_line(value)
            if cleaned:
                return cleaned
    return ""


def _parse_u32(value: str) -> int | None:
    text = value.strip().lower()
    if not text:
        return None
    try:
        if text.startswith("0x") or re.fullmatch(r"[0-9a-f]{8}", text):
            return int(text, 16)
        if re.fullmatch(r"[0-9]+", text):
            return int(text, 10)
        if re.fullmatch(r"[0-9a-f]+", text):
            return int(text, 16)
    except ValueError:
        return None
    return None


def format_region(value: str) -> str:
    number = _parse_u32(value)
    if number is None:
        return value.strip()
    if number in {0xFFFFFFFF, 0x7FFFFFFF}:
        return "ALL"
    names = [label for bit, label in REGION_BITS if number & bit]
    if names:
        return "+".join(names)
    if number == 0:
        return ""
    return f"0x{number:08X}"


def video_standard(region: str) -> str:
    """NTSC-U, PAL, or NTSC-J for a region name from ``format_region``."""
    labels: list[str] = []
    for part in region.split("+"):
        label = _VIDEO.get(part)
        if label and label not in labels:
            labels.append(label)
    return ", ".join(labels)


def region_label(region: str) -> str:
    """Region name plus its video standard, for the title list."""
    region = region.strip()
    if not region:
        return ""
    video = video_standard(region)
    if not video:
        return region
    return f"{region} ({video})"


def _region_from_product(product_code: str) -> str:
    token = product_code.strip().upper().split("-")[-1]
    if len(token) < 4:
        return ""
    return _PRODUCT_REGION.get(token[3], "")


def _ids(directory: Path, fields: dict[str, str]) -> tuple[str, str]:
    name = directory.name
    parent = directory.parent.name
    if _HEX8.fullmatch(name) and _HEX8.fullmatch(parent):
        return parent.lower(), name.lower()
    raw = fields.get("title_id", "").replace("-", "").strip()
    if _HEX16.fullmatch(raw):
        return raw[:8].lower(), raw[8:].lower()
    if _HEX8.fullmatch(name):
        return "", name.lower()
    return "", name.lower()


def _looks_like_title_root(path: Path) -> bool:
    try:
        children = list(path.iterdir())
    except OSError:
        return False
    return any(child.is_dir() and _HEX8.fullmatch(child.name) for child in children)


def iter_title_dirs(source: Path) -> list[Path]:
    """Find title folders without walking game content."""
    source = source.expanduser().resolve()
    if (source / "meta" / "meta.xml").is_file():
        return [source]
    root = None
    for candidate in (source / "usr" / "title", source / "title", source):
        if candidate.is_dir() and _looks_like_title_root(candidate):
            root = candidate
            break
    if root is None:
        return []
    found: list[Path] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir() or not _HEX8.fullmatch(child.name):
            continue
        if (child / "meta" / "meta.xml").is_file():
            found.append(child)
            continue
        lows = sorted(
            (
                low
                for low in child.iterdir()
                if low.is_dir() and _HEX8.fullmatch(low.name)
            ),
            key=lambda item: item.name.lower(),
        )
        if lows:
            found.extend(lows)
        else:
            found.append(child)
    return found


def meta_stamp(path: Path) -> str:
    """Return a stamp for ``meta/meta.xml``, or ``""`` when that file is absent.

    The size cache uses this so a replaced title is measured again. Editing a
    file inside ``content/`` does not change it. Recount sizes does that.
    """
    try:
        info = (path / "meta" / "meta.xml").stat()
    except OSError:
        return ""
    return f"{info.st_mtime_ns}:{info.st_size}"


def load_size_cache(path: Path) -> dict[str, dict[str, int | str]]:
    """Load ``{title path: {size, stamp}}``. A bad file is an empty cache."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict) or raw.get("version") != 1:
        return {}
    entries = raw.get("entries")
    if not isinstance(entries, dict):
        return {}
    clean: dict[str, dict[str, int | str]] = {}
    for key, value in entries.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        size = value.get("size")
        stamp = value.get("stamp")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            continue
        if not isinstance(stamp, str) or not stamp:
            continue
        clean[key] = {"size": size, "stamp": stamp}
    return clean


def save_size_cache(path: Path, entries: dict[str, dict[str, int | str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "entries": entries}
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(path)


def directory_size(path: Path, cancel=None) -> int | None:
    """Return the total size of regular files, or None if ``cancel`` is set.

    A cancelled walk does not return a partial total. Symlinks are not followed.
    The byte count is a Python int, so a title larger than 2 GiB stays positive.
    """
    total = 0
    seen = 0
    stack = [os.fspath(path)]
    while stack:
        if cancel is not None and cancel.is_set():
            return None
        current = stack.pop()
        try:
            iterator = os.scandir(current)
        except OSError:
            continue
        with iterator:
            for entry in iterator:
                seen += 1
                if seen % 200 == 0 and cancel is not None and cancel.is_set():
                    return None
                name = entry.name
                if name == ".DS_Store" or name.endswith(".wfs-studio-partial"):
                    continue
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                        continue
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
    if cancel is not None and cancel.is_set():
        return None
    return total


def scan_titles(source: Path) -> list[TitleRecord]:
    if not source.expanduser().exists():
        raise FileNotFoundError(f"Source folder does not exist: {source}")
    source_root = source.expanduser().resolve()
    records: list[TitleRecord] = []
    games: dict[str, str] = {}
    pending: list[TitleRecord] = []
    for directory in iter_title_dirs(source_root):
        fields = meta_fields(directory / "meta" / "meta.xml")
        high_id, low_id = _ids(directory, fields)
        kind = KIND_BY_HIGH.get(high_id, "Other" if high_id else "Folder")
        name = _localized(fields, "longname") or _localized(fields, "shortname")
        product = _one_line(fields.get("product_code", ""))
        region = format_region(fields.get("region", "")) or _region_from_product(product)
        version_number = _parse_u32(fields.get("title_version", ""))
        version = "" if version_number is None else str(version_number)
        publisher = _localized(fields, "publisher")
        if not name:
            name = "Unknown title"
        record = TitleRecord(
            source_root=source_root,
            path=directory,
            high_id=high_id,
            low_id=low_id,
            kind=kind,
            name=name,
            product_code=product,
            region=region,
            version=version,
            publisher=publisher,
        )
        if kind == "Game" and name != "Unknown title":
            games[low_id] = name
        pending.append(record)
    for record in pending:
        if record.kind in {"Update", "DLC", "Demo"} and record.name == "Unknown title":
            base = games.get(record.low_id)
            if base:
                record = TitleRecord(
                    source_root=record.source_root,
                    path=record.path,
                    high_id=record.high_id,
                    low_id=record.low_id,
                    kind=record.kind,
                    name=f"{record.kind} for {base}",
                    product_code=record.product_code,
                    region=record.region,
                    version=record.version,
                    publisher=record.publisher,
                )
        records.append(record)
    records.sort(key=lambda item: (item.name.lower(), item.kind, item.title_id))
    return records
