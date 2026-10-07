"""GameTDB Wii U title list.

The text database maps a 6-character id such as APKE01 to a name.
Wii U product codes such as WUP-P-APKE use the first four of those characters.
"""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path

from wfs_studio.titles import TitleRecord

TITLES_URL = "https://www.gametdb.com/wiiutdb.txt?LANG=EN"
USER_AGENT = "wfs-studio/0.1"
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
class GameTdb:
    by_id: dict[str, str]
    version: str = ""

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
    letter = ""
    for name, candidate in (
        ("USA", "E"),
        ("JPN", "J"),
        ("EUR", "P"),
        ("KOR", "K"),
        ("CHN", "C"),
        ("TWN", "W"),
        ("AUS", "A"),
    ):
        if region == name:
            letter = candidate
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
    primary = DISC_FOLDERS.get(region.split("+", 1)[0])
    if primary:
        folders.append(primary)
    for extra in ("US", "EN", "JA"):
        if extra not in folders:
            folders.append(extra)
    return [
        f"https://art.gametdb.com/wiiu/disc/{folder}/{gametdb_id}.png"
        for folder in folders
    ]


def load_cached(cache: Path) -> GameTdb | None:
    path = cache / "wiiutdb.txt"
    if not path.is_file():
        return None
    return parse_titles(path.read_text(encoding="utf-8-sig"))


def download_titles(cache: Path, timeout: float = 60) -> GameTdb:
    cache.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(TITLES_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
    (cache / "wiiutdb.txt").write_bytes(data)
    return parse_titles(data.decode("utf-8-sig"))


def download_bytes(url: str, timeout: float = 20, limit: int = 2_000_000) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(limit + 1)
    except Exception:
        return None
    if len(data) > limit or not data.startswith(b"\x89PNG"):
        return None
    return data
