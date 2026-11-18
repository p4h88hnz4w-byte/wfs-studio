"""GameTDB Wii U title list.

The text database maps a 6-character id such as APKE01 to a name.
Wii U product codes such as WUP-P-APKE use the first four of those characters.
"""

from __future__ import annotations

import io
import re
import threading
import urllib.error
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from pathlib import Path

from wfs_studio.titles import REGION_LETTERS, TitleRecord

TITLES_URL = "https://www.gametdb.com/wiiutdb.txt?LANG=EN"
ZIP_URL = "https://www.gametdb.com/wiiutdb.zip?LANG=EN"
USER_AGENT = "wfs-studio/0.2"
COVER_TIMEOUT = 5
APP_LANG = "EN"
MAX_XML_BYTES = 20_000_000
_COVER_ID = re.compile(r"^[A-Z0-9]{3,16}$")
DISC_FOLDERS = {
    "USA": "US",
    "JPN": "JA",
    "EUR": "EN",
    "AUS": "AU",
    "KOR": "KO",
    "CHN": "ZHCN",
    "TWN": "ZHTW",
}


@dataclass(frozen=True)
class GameInfo:
    name: str
    region: str = ""
    developer: str = ""
    publisher: str = ""
    date: str = ""
    genre: str = ""


@dataclass(frozen=True)
class GameTdb:
    by_id: dict[str, str]
    version: str = ""
    info: dict[str, GameInfo] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.by_id)


def parse_titles(text: str) -> GameTdb:
    by_id: dict[str, str] = {}
    version = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("TITLES"):
            marker = "version:"
            if marker in line:
                version = line.split(marker, 1)[1].strip().rstrip(")")
            continue
        if " = " not in line:
            continue
        ident, name = line.split(" = ", 1)
        ident = ident.strip().upper()
        name = name.strip()
        if ident and name:
            by_id[ident] = name
    return GameTdb(by_id=by_id, version=version)


def game_id_from_product(product_code: str) -> str:
    code = product_code.strip().upper().replace(" ", "")
    if not code:
        return ""
    token = code.split("-")[-1]
    if len(token) >= 4:
        return token[:4]
    return token


def lookup(db: GameTdb, product_code: str, region: str = "") -> tuple[str, str] | None:
    """Return (gametdb id, name) for a product code."""
    code = product_code.strip().upper().replace(" ", "")
    if code in db.by_id:
        return code, db.by_id[code]
    game = game_id_from_product(product_code)
    if len(game) < 4:
        return None
    matches = [ident for ident in db.by_id if ident.startswith(game)]
    if not matches:
        return None
    # A combined region such as USA+EUR keeps the first letter it names.
    letter = ""
    for part in region.split("+"):
        for name, candidate in REGION_LETTERS:
            if part == name:
                letter = candidate
                break
        if letter:
            break

    def rank(ident: str) -> tuple[int, int, int, str]:
        region_rank = 0 if letter and len(ident) >= 4 and ident[3] == letter else 1
        revision_rank = 0 if ident.endswith("01") else 1
        return (region_rank, revision_rank, len(ident), ident)

    best = sorted(matches, key=rank)[0]
    return best, db.by_id[best]


def annotate(records: list[TitleRecord], db: GameTdb | None) -> list[TitleRecord]:
    if db is None:
        return list(records)
    annotated: list[TitleRecord] = []
    for record in records:
        found = lookup(db, record.product_code, record.region)
        if found is None:
            annotated.append(record)
            continue
        ident, name = found
        annotated.append(replace(record, gametdb_id=ident, gametdb_name=name))
    return annotated


def disc_urls(gametdb_id: str, region: str) -> list[str]:
    if not gametdb_id:
        return []
    folders: list[str] = []
    for part in region.split("+"):
        folder = DISC_FOLDERS.get(part.strip())
        if folder and folder not in folders:
            folders.append(folder)
    for extra in ("US", "EN", "JA"):
        if extra not in folders:
            folders.append(extra)
    return [
        f"https://art.gametdb.com/wiiu/disc/{folder}/{gametdb_id}.png"
        for folder in folders
    ]


def _locale_title(game: ET.Element, language: str) -> str:
    fallback = ""
    english = ""
    for locale in game.findall("locale"):
        title = (locale.findtext("title") or "").strip()
        if not title:
            continue
        lang = (locale.get("lang") or "").strip().upper()
        if lang == language.upper():
            return title
        if lang == "EN" and not english:
            english = title
        if not fallback:
            fallback = title
    return english or fallback


def _date_text(game: ET.Element) -> str:
    node = game.find("date")
    if node is None:
        return ""
    parts: list[str] = []
    year = (node.get("year") or "").strip()
    month = (node.get("month") or "").strip()
    day = (node.get("day") or "").strip()
    if year:
        parts.append(year)
    if month:
        parts.append(month.zfill(2))
    if day and month and year:
        parts.append(day.zfill(2))
    return "-".join(parts)


def parse_wiiutdb_xml(data: bytes, language: str = APP_LANG) -> GameTdb:
    """Parse a ``wiiutdb.xml`` document already read from a zip."""
    if len(data) > MAX_XML_BYTES:
        raise RuntimeError("wiiutdb.xml is larger than 20 MB")
    root = ET.fromstring(data)
    header = root.find("WiiUTDB")
    version = header.get("version", "").strip() if header is not None else ""
    by_id: dict[str, str] = {}
    info: dict[str, GameInfo] = {}
    for game in root.iter("game"):
        ident = (game.findtext("id") or "").strip().upper()
        if not ident:
            continue
        name = _locale_title(game, language) or (game.get("name") or "").strip()
        if not name:
            continue
        by_id[ident] = name
        info[ident] = GameInfo(
            name=name,
            region=(game.findtext("region") or "").strip(),
            developer=(game.findtext("developer") or "").strip(),
            publisher=(game.findtext("publisher") or "").strip(),
            date=_date_text(game),
            genre=(game.findtext("genre") or "").strip(),
        )
    return GameTdb(by_id=by_id, version=version, info=info)


def xml_member_name(bundle: zipfile.ZipFile) -> str:
    names = [info.filename for info in bundle.infolist() if not info.is_dir()]
    for name in names:
        if Path(name).name == "wiiutdb.xml":
            return name
    xml_names = [name for name in names if name.lower().endswith(".xml")]
    if len(xml_names) == 1:
        return xml_names[0]
    raise RuntimeError("The zip has no wiiutdb.xml")


def load_zip_bytes(data: bytes, language: str = APP_LANG) -> GameTdb:
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        name = xml_member_name(bundle)
        info = bundle.getinfo(name)
        if info.file_size > MAX_XML_BYTES:
            raise RuntimeError("wiiutdb.xml is larger than 20 MB")
        return parse_wiiutdb_xml(bundle.read(name), language)


def load_zip(path: Path, language: str = APP_LANG) -> GameTdb:
    """Read ``wiiutdb.xml`` from a zip without writing the member to disk."""
    with zipfile.ZipFile(path) as bundle:
        name = xml_member_name(bundle)
        info = bundle.getinfo(name)
        if info.file_size > MAX_XML_BYTES:
            raise RuntimeError("wiiutdb.xml is larger than 20 MB")
        return parse_wiiutdb_xml(bundle.read(name), language)


def load_cached(cache: Path) -> GameTdb | None:
    zip_path = cache / "wiiutdb.zip"
    if zip_path.is_file():
        try:
            return load_zip(zip_path)
        except (OSError, zipfile.BadZipFile, ET.ParseError, RuntimeError):
            pass
    path = cache / "wiiutdb.txt"
    if not path.is_file():
        return None
    return parse_titles(path.read_text(encoding="utf-8-sig"))


def load_database(cache: Path, zip_path: str | Path | None = None) -> GameTdb | None:
    """Prefer a chosen zip, then ``cache/wiiutdb.zip``, then the text list."""
    if zip_path:
        path = Path(zip_path)
        if path.is_file():
            try:
                return load_zip(path)
            except (OSError, zipfile.BadZipFile, ET.ParseError, RuntimeError):
                pass
    return load_cached(cache)


def download_titles(cache: Path, timeout: float = 60) -> GameTdb:
    """Download ``wiiutdb.zip`` and keep it compressed in the cache."""
    cache.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(ZIP_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
    database = load_zip_bytes(data)
    (cache / "wiiutdb.zip").write_bytes(data)
    return database


def index_cover_zip(path: Path) -> dict[str, str]:
    """Map a GameTDB id to the zip member for its PNG. The archive is not extracted."""
    index: dict[str, str] = {}
    with zipfile.ZipFile(path) as bundle:
        for info in bundle.infolist():
            if info.is_dir():
                continue
            base = Path(info.filename).name
            if not base.upper().endswith(".PNG"):
                continue
            ident = base[:-4].upper()
            if not _COVER_ID.fullmatch(ident):
                continue
            current = index.get(ident)
            if current is None or len(info.filename) < len(current):
                index[ident] = info.filename
    return index


def read_zip_png(path: Path, member: str, limit: int = 2_000_000) -> bytes | None:
    try:
        with zipfile.ZipFile(path) as bundle:
            info = bundle.getinfo(member)
            if info.file_size > limit:
                return None
            data = bundle.read(info)
    except (OSError, zipfile.BadZipFile, KeyError):
        return None
    if len(data) > limit or not data.startswith(b"\x89PNG"):
        return None
    return data


def cover_paths(cache: Path, gametdb_id: str) -> tuple[Path, Path] | None:
    """Return ``(png, miss marker)`` for a safe GameTDB id."""
    ident = gametdb_id.strip().upper()
    if not _COVER_ID.fullmatch(ident):
        return None
    folder = cache / "covers"
    return folder / f"{ident}.png", folder / f"{ident}.missing"


def read_cover_cache(cache: Path, gametdb_id: str) -> tuple[str, bytes | None]:
    """Return ``('hit', png)``, ``('miss', None)``, or ``('absent', None)``."""
    paths = cover_paths(cache, gametdb_id)
    if paths is None:
        return "miss", None
    png, missing = paths
    if png.is_file():
        try:
            data = png.read_bytes() if png.stat().st_size <= 2_000_000 else b""
        except OSError:
            data = b""
        if data.startswith(b"\x89PNG"):
            return "hit", data
    if missing.is_file():
        return "miss", None
    return "absent", None


def remember_cover(cache: Path, gametdb_id: str, data: bytes) -> None:
    paths = cover_paths(cache, gametdb_id)
    if paths is None or len(data) > 2_000_000 or not data.startswith(b"\x89PNG"):
        return
    png, missing = paths
    png.parent.mkdir(parents=True, exist_ok=True)
    png.write_bytes(data)
    missing.unlink(missing_ok=True)


def remember_cover_miss(cache: Path, gametdb_id: str) -> None:
    paths = cover_paths(cache, gametdb_id)
    if paths is None:
        return
    _png, missing = paths
    missing.parent.mkdir(parents=True, exist_ok=True)
    missing.write_text("no-disc-image\n", encoding="utf-8")


def fetch_cover(urls: list[str], fetch, timeout: float, cancel=None) -> tuple[str, bytes | None]:
    """Fetch disc URLs together.

    Returns ``('png', data)`` for the earliest URL that is a PNG,
    ``('missing', None)`` when every URL is a not-found or non-PNG,
    ``('error', None)`` when none is a PNG and any request failed, or
    ``('cancelled', None)``. A cancel is not a miss.
    """
    if cancel is not None and cancel.is_set():
        return "cancelled", None
    if not urls:
        return "missing", None

    results: list[tuple[str, bytes | None] | None] = [None] * len(urls)
    lock = threading.Lock()
    pending = len(urls)
    finished = threading.Condition(lock)

    def run_one(index: int, url: str) -> None:
        nonlocal pending
        if cancel is not None and cancel.is_set():
            outcome: tuple[str, bytes | None] = ("cancelled", None)
        else:
            outcome = fetch(url, timeout=timeout)
        with finished:
            results[index] = outcome
            pending -= 1
            finished.notify_all()

    for index, url in enumerate(urls):
        threading.Thread(target=run_one, args=(index, url), daemon=True).start()

    with finished:
        while pending:
            if cancel is not None and cancel.is_set():
                return "cancelled", None
            if any(item is not None and item[0] == "png" and item[1] for item in results):
                break
            finished.wait(timeout=0.05)
        for item in results:
            if item is not None and item[0] == "png" and item[1]:
                return "png", item[1]
        if pending:
            return "cancelled", None
    kinds = [item[0] for item in results if item is not None]
    if kinds and all(kind == "missing" for kind in kinds):
        return "missing", None
    return "error", None


def fetch_png(url: str, timeout: float = 20, limit: int = 2_000_000) -> tuple[str, bytes | None]:
    """Download one PNG.

    Returns ``('png', data)``, ``('missing', None)`` for a not-found or
    non-PNG response, or ``('error', None)`` for a timeout or other failure.
    A later retry should skip the network only after ``missing``.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        try:
            if exc.code in {403, 404, 410}:
                return "missing", None
            return "error", None
        finally:
            exc.close()
    except Exception:
        return "error", None
    if len(data) > limit or not data.startswith(b"\x89PNG"):
        return "missing", None
    return "png", data


def download_bytes(url: str, timeout: float = 20, limit: int = 2_000_000) -> bytes | None:
    kind, data = fetch_png(url, timeout=timeout, limit=limit)
    if kind != "png":
        return None
    return data
