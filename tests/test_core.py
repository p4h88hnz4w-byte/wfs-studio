import errno
import json
import os
import threading
import urllib.error
import zipfile
from pathlib import Path

import pytest

from wfs_studio.binaries import platform_key, safe_extract, sha256_file
from wfs_studio.copy_job import (
    copy_game_data,
    copy_titles,
    game_folder_name,
    relative_archive_members,
    tree_totals,
)
from wfs_studio.extract import (
    CatalogRequest,
    ExtractRequest,
    append_extract_chunk,
    build_args,
    build_catalog_args,
    catalog_binary,
    parse_extract_line,
    recovery_warning,
)
from wfs_studio.gametdb import (
    annotate,
    cover_paths,
    disc_urls,
    fetch_cover,
    fetch_png,
    index_cover_zip,
    load_cached,
    load_zip,
    lookup,
    parse_titles,
    read_zip_png,
    read_cover_cache,
    remember_cover,
    remember_cover_miss,
)
from wfs_studio.paths import PathIssue, validate_copy, validate_extract_paths
from wfs_studio.settings import load_settings, save_settings
from wfs_studio.titles import (
    directory_size,
    format_region,
    group_titles,
    load_meta_text,
    load_size_cache,
    meta_stamp,
    region_label,
    save_size_cache,
    scan_titles,
)
from wfs_studio.util import format_bytes, progress_permille

META = """<?xml version="1.0" encoding="utf-8"?>
<menu>
  <title_version type="unsignedInt" length="4">0</title_version>
  <product_code type="string" length="32">WUP-P-APKE</product_code>
  <title_id type="hexBinary" length="8">00050000101DF400</title_id>
  <region type="hexBinary" length="4">00000002</region>
  <longname_en type="string" length="256">POKKÉN TOURNAMENT
Deluxe</longname_en>
  <publisher_en type="string" length="256">Nintendo</publisher_en>
</menu>
"""

GAMETDB = """TITLES = https://www.gametdb.com (type: WiiU language: EN version: 20261007000000)
APKE01 = Pokken Tournament
APKJ2P = Pokken: Pokken Tournament
APKP01 = Pokken Tournament
PAKE = The Legend of Zelda: The Minish Cap
AAFE01 = Bayonetta
"""


def write_title(root: Path, high: str, low: str, meta: str | bytes, payload: bytes = b"game") -> Path:
    folder = root / "usr" / "title" / high / low
    (folder / "meta").mkdir(parents=True)
    (folder / "content").mkdir()
    meta_path = folder / "meta" / "meta.xml"
    if isinstance(meta, bytes):
        meta_path.write_bytes(meta)
    else:
        meta_path.write_text(meta, encoding="utf-8")
    (folder / "content" / "data.bin").write_bytes(payload)
    return folder


def test_scan_reads_names_regions_and_related_updates(tmp_path: Path):
    write_title(tmp_path, "00050000", "101df400", META, b"abc")
    write_title(tmp_path, "0005000e", "101df400", "<menu></menu>", b"upd")
    records = scan_titles(tmp_path)
    by_kind = {record.kind: record for record in records}
    assert by_kind["Game"].name == "POKKÉN TOURNAMENT Deluxe"
    assert by_kind["Game"].title_id == "00050000-101DF400"
    assert by_kind["Game"].region == "USA"
    assert by_kind["Game"].product_code == "WUP-P-APKE"
    assert by_kind["Game"].publisher == "Nintendo"
    assert by_kind["Update"].name == "Update for POKKÉN TOURNAMENT Deluxe"


def test_group_titles_joins_a_game_with_its_update_and_dlc(tmp_path: Path):
    write_title(tmp_path, "00050000", "101df400", META, b"abc")
    write_title(tmp_path, "0005000e", "101df400", "<menu></menu>", b"upd")
    write_title(tmp_path, "0005000c", "101DF400", "<menu></menu>", b"dlc")
    write_title(tmp_path, "00050002", "101df400", META.replace("POKKÉN TOURNAMENT\nDeluxe", "Pokken Demo"), b"demo")
    write_title(tmp_path, "0005000e", "10111100", "<menu></menu>", b"orphan-upd")
    write_title(tmp_path, "0005000c", "10111100", "<menu></menu>", b"orphan-dlc")
    groups = group_titles(scan_titles(tmp_path))
    family = next(group for group in groups if group.kind_label == "Game + Update + DLC")
    assert family.head.low_id == "101df400"
    assert [member.kind for member in family.members] == ["Game", "Update", "DLC"]
    assert family.head.name == "POKKÉN TOURNAMENT Deluxe"
    demo = next(group for group in groups if group.head.kind == "Demo")
    assert demo.kind_label == "Demo"
    assert demo.head.low_id == "101df400"
    orphan = next(group for group in groups if group.head.low_id == "10111100")
    assert orphan.kind_label == "Update + DLC"
    assert orphan.head.kind == "Update"


def test_pal_and_ntsc_j_titles_scan_and_match_gametdb(tmp_path: Path):
    pal = META.replace("WUP-P-APKE", "WUP-P-APKP").replace("00000002", "00000004")
    japan = META.replace("WUP-P-APKE", "WUP-P-APKJ").replace("00000002", "00000001")
    letter_only = META.replace("WUP-P-APKE", "WUP-P-APKX").replace(
        '<region type="hexBinary" length="4">00000002</region>',
        "<region></region>",
    )
    write_title(tmp_path, "00050000", "101df401", pal)
    write_title(tmp_path, "00050000", "101df402", japan)
    write_title(tmp_path, "00050000", "101df403", letter_only)
    by_low = {record.low_id: record for record in scan_titles(tmp_path)}
    assert by_low["101df401"].region == "EUR"
    assert by_low["101df402"].region == "JPN"
    assert by_low["101df403"].region == "EUR"
    assert format_region("00000001") == "JPN"
    assert format_region("00000002") == "USA"
    assert format_region("00000004") == "EUR"
    assert format_region("00000006") == "USA+EUR"
    assert format_region("00000007") == "JPN+USA+EUR"
    assert format_region("00000008") == "AUS"
    assert region_label("USA") == "USA (NTSC-U)"
    assert region_label("EUR") == "EUR (PAL)"
    assert region_label("JPN") == "JPN (NTSC-J)"
    assert region_label("AUS") == "AUS (PAL)"
    assert region_label("USA+EUR") == "USA+EUR (NTSC-U, PAL)"
    assert region_label("JPN+USA+EUR") == "JPN+USA+EUR (NTSC-J, NTSC-U, PAL)"
    assert region_label("ALL") == "ALL"

    database = parse_titles(GAMETDB + "APKJ01 = Pokken Tournament\n")
    assert lookup(database, "WUP-P-APKP", "EUR") == ("APKP01", "Pokken Tournament")
    assert lookup(database, "WUP-P-APKJ", "JPN") == ("APKJ01", "Pokken Tournament")
    assert lookup(database, "WUP-P-APKE", "USA+EUR") == ("APKE01", "Pokken Tournament")
    assert disc_urls("APKP01", "EUR")[0].endswith("/EN/APKP01.png")
    assert disc_urls("APKJ01", "JPN")[0].endswith("/JA/APKJ01.png")
    assert disc_urls("APKE01", "USA")[0].endswith("/US/APKE01.png")
    assert [url.rsplit("/", 2)[-2] for url in disc_urls("NAZE01", "USA+EUR")] == ["US", "EN", "JA"]
    assert [url.rsplit("/", 2)[-2] for url in disc_urls("AMKP01", "EUR+AUS")] == ["EN", "AU", "US", "JA"]


def test_utf16_meta_xml(tmp_path: Path):
    encoded = META.encode("utf-16")
    assert b"\x00" in encoded
    write_title(tmp_path, "00050000", "101df400", encoded)
    text = load_meta_text(tmp_path / "usr" / "title" / "00050000" / "101df400" / "meta" / "meta.xml")
    assert "POKKÉN TOURNAMENT" in text
    records = scan_titles(tmp_path)
    assert records[0].name == "POKKÉN TOURNAMENT Deluxe"


def test_single_title_folder(tmp_path: Path):
    folder = write_title(tmp_path, "00050000", "101df400", META)
    records = scan_titles(folder)
    assert len(records) == 1
    assert records[0].relative_path == Path(".")


def test_gametdb_lookup_uses_product_code():
    db = parse_titles(GAMETDB)
    assert db.version == "20261007000000"
    assert lookup(db, "WUP-P-APKE", "USA") == ("APKE01", "Pokken Tournament")
    assert lookup(db, "WUP-P-APKP", "EUR") == ("APKP01", "Pokken Tournament")
    assert lookup(db, "PAKE") == ("PAKE", "The Legend of Zelda: The Minish Cap")
    assert lookup(db, "WUP-P-ZZZZ") is None


WIIUTDB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<datafile>
  <WiiUTDB version="20261117000000" games="2"/>
  <game name="Bayonetta (Europe)">
    <id>AAFE01</id>
    <region>PAL</region>
    <locale lang="JA"><title>ベヨネッタ</title></locale>
    <locale lang="EN"><title>Bayonetta</title></locale>
    <developer>Platinum Games Inc.</developer>
    <publisher>Nintendo</publisher>
    <date year="2014" month="10" day="24"/>
    <genre>action</genre>
  </game>
  <game name="Only German">
    <id>ZZZZ01</id>
    <locale lang="DE"><title>Nur Deutsch</title></locale>
  </game>
</datafile>
"""


def test_wiiutdb_zip_supplies_the_english_title_and_metadata(tmp_path: Path):
    archive = tmp_path / "wiiutdb.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("wiiutdb.xml", WIIUTDB_XML)
    database = load_zip(archive)
    assert database.version == "20261117000000"
    assert database.by_id["AAFE01"] == "Bayonetta"
    assert database.by_id["ZZZZ01"] == "Nur Deutsch"
    info = database.info["AAFE01"]
    assert info.developer == "Platinum Games Inc."
    assert info.publisher == "Nintendo"
    assert info.date == "2014-10-24"
    assert info.genre == "action"
    assert info.region == "PAL"
    assert lookup(database, "WUP-P-AAFE", "USA") == ("AAFE01", "Bayonetta")
    assert not (tmp_path / "wiiutdb.xml").exists()


def test_cached_zip_wins_over_the_text_list(tmp_path: Path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "wiiutdb.txt").write_text("AAFE01 = From Text\n", encoding="utf-8")
    with zipfile.ZipFile(cache / "wiiutdb.zip", "w") as bundle:
        bundle.writestr("wiiutdb.xml", WIIUTDB_XML)
    assert load_cached(cache).by_id["AAFE01"] == "Bayonetta"
    (cache / "wiiutdb.zip").write_bytes(b"not a zip")
    assert load_cached(cache).by_id["AAFE01"] == "From Text"


def test_banner_zip_returns_a_png_without_extracting(tmp_path: Path):
    png = b"\x89PNG\r\n\x1a\nart"
    archive = tmp_path / "covers.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("disc/US/AAFE01.png", png)
        bundle.writestr("AAFE01.png", png + b"short")
        bundle.writestr("notes/readme.txt", b"no")
    index = index_cover_zip(archive)
    assert index["AAFE01"] == "AAFE01.png"
    assert read_zip_png(archive, index["AAFE01"]) == png + b"short"
    assert read_zip_png(archive, "missing.png") is None
    assert list(tmp_path.glob("*.png")) == []


def test_annotate_adds_database_name(tmp_path: Path):
    write_title(tmp_path, "00050000", "101df400", META)
    records = annotate(scan_titles(tmp_path), parse_titles(GAMETDB))
    assert records[0].gametdb_id == "APKE01"
    assert records[0].gametdb_name == "Pokken Tournament"


def test_copy_writes_destination_and_skips_matches(tmp_path: Path):
    write_title(tmp_path / "src", "00050000", "101df400", META, b"payload-bytes")
    source = tmp_path / "src"
    dest = tmp_path / "dest"
    seen: list[str] = []

    def on_progress(progress):
        seen.append(progress.current_path)

    result = copy_titles(
        [(source, source / "usr" / "title" / "00050000" / "101df400")],
        dest,
        skip_same_size=True,
        cancel=threading.Event(),
        on_progress=on_progress,
    )
    copied = dest / "usr" / "title" / "00050000" / "101df400" / "content" / "data.bin"
    assert copied.read_bytes() == b"payload-bytes"
    assert (source / "usr" / "title" / "00050000" / "101df400" / "content" / "data.bin").read_bytes() == b"payload-bytes"
    assert result.files_written == 2
    assert result.cancelled is False
    assert any("data.bin" in path for path in seen)

    second = copy_titles(
        [(source, source / "usr" / "title" / "00050000" / "101df400")],
        dest,
        skip_same_size=True,
        cancel=threading.Event(),
        on_progress=lambda _progress: None,
    )
    assert second.files_written == 0
    assert second.files_skipped == 2


def test_relative_archive_members_follow_the_copy(tmp_path: Path):
    source = tmp_path / "dump"
    title = write_title(source, "00050000", "101df400", META, b"payload-bytes")
    record = scan_titles(source)[0]
    assert relative_archive_members([record]) == ["usr/title/00050000/101df400"]
    alone = scan_titles(title)[0]
    assert relative_archive_members([alone]) == ["content", "meta"]
    assert title.is_dir()


def test_game_data_copy_names_a_folder_and_leaves_saves(tmp_path: Path):
    source = tmp_path / "dump"
    title = write_title(source, "00050000", "101df400", META, b"payload-bytes")
    save = source / "usr" / "save" / "00050000" / "101df400" / "user"
    save.mkdir(parents=True)
    (save / "save.dat").write_bytes(b"secret-save")
    dest = tmp_path / "out"
    name = game_folder_name("Pokken/Tournament", "00050000-101DF400")
    assert "/" not in name
    assert name.endswith(" [00050000-101DF400]")

    result = copy_game_data(
        [(title, name)],
        dest,
        skip_same_size=True,
        cancel=threading.Event(),
        on_progress=lambda _progress: None,
    )
    copied = dest / name / "content" / "data.bin"
    assert copied.read_bytes() == b"payload-bytes"
    assert result.verified is True
    assert result.files_written == 2
    assert not (dest / name / "usr").exists()
    assert (save / "save.dat").read_bytes() == b"secret-save"
    assert tree_totals(title) == tree_totals(dest / name)


def test_game_data_copy_reports_a_short_destination(tmp_path: Path, monkeypatch):
    source = tmp_path / "dump"
    title = write_title(source, "00050000", "101df400", META, b"payload-bytes")
    real = tree_totals
    seen = {"n": 0}

    def short(path, cancel=None):
        seen["n"] += 1
        totals = real(path, cancel)
        if seen["n"] == 2 and totals is not None:
            return totals[0], totals[1] - 1
        return totals

    monkeypatch.setattr("wfs_studio.copy_job.tree_totals", short)
    result = copy_game_data(
        [(title, "Pokken [00050000-101DF400]")],
        tmp_path / "out",
        skip_same_size=True,
        cancel=threading.Event(),
        on_progress=lambda _progress: None,
    )
    assert result.verified is False
    assert result.errors
    assert "bytes" in result.errors[0]


def test_cancel_removes_partial_and_leaves_source(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("wfs_studio.copy_job.CHUNK", 4)
    write_title(tmp_path / "src", "00050000", "101df400", META, b"0123456789abcdef")
    source = tmp_path / "src"
    original = (source / "usr" / "title" / "00050000" / "101df400" / "content" / "data.bin").read_bytes()
    dest = tmp_path / "dest"
    cancel = threading.Event()

    def on_progress(progress):
        if progress.copied_bytes:
            cancel.set()

    result = copy_titles(
        [(source, source / "usr" / "title" / "00050000" / "101df400")],
        dest,
        skip_same_size=False,
        cancel=cancel,
        on_progress=on_progress,
    )
    assert result.cancelled is True
    assert list(dest.rglob("*.wfs-studio-partial")) == []
    assert original == (source / "usr" / "title" / "00050000" / "101df400" / "content" / "data.bin").read_bytes()


def test_copy_refuses_destination_inside_source(tmp_path: Path):
    source = tmp_path / "src"
    source.mkdir()
    with pytest.raises(PathIssue):
        validate_copy(source, source / "inside")
    with pytest.raises(PathIssue):
        validate_copy(source, source)


def test_extract_paths_reject_output_that_contains_the_image(tmp_path: Path):
    folder = tmp_path / "backup"
    folder.mkdir()
    image = folder / "mlc.bin"
    image.write_bytes(b"x" * 32)
    otp = tmp_path / "otp.bin"
    otp.write_bytes(b"k" * 1024)
    with pytest.raises(PathIssue):
        validate_extract_paths(image, folder, otp, None, "mlc")
    validate_extract_paths(image, tmp_path / "out", otp, None, "mlc")
    with pytest.raises(PathIssue):
        validate_extract_paths(image, tmp_path / "out", None, None, "mlc")
    with pytest.raises(PathIssue):
        validate_extract_paths(image, tmp_path / "usb-out", otp, None, "usb")


def test_extract_command_matches_image_type(tmp_path: Path):
    binary = tmp_path / "wfs-extract"
    request = ExtractRequest(
        binary=binary,
        input_path=Path("mlc.bin"),
        image_type="mlc",
        output_path=Path("out"),
        otp=Path("otp.bin"),
        seeprom=Path("seeprom.bin"),
    )
    args = build_args(request)
    assert args[0] == str(binary)
    assert "--type" in args and args[args.index("--type") + 1] == "mlc"
    assert "--verbose" in args
    assert "--seeprom" not in args
    assert "--otp" in args
    usb = build_args(
        ExtractRequest(
            binary=binary,
            input_path=Path("/dev/disk4"),
            image_type="usb",
            output_path=Path("out"),
            otp=Path("otp.bin"),
            seeprom=Path("seeprom.bin"),
            dump_path="/usr/title",
        )
    )
    assert "--seeprom" in usb
    assert usb[usb.index("--dump-path") + 1] == "/usr/title"
    plain = build_args(
        ExtractRequest(
            binary=binary,
            input_path=Path("plain.img"),
            image_type="plain",
            output_path=Path("out"),
            otp=Path("otp.bin"),
        )
    )
    assert "--otp" not in plain
    assert parse_extract_line("Dumping /usr/title/game")["path"] == "/usr/title/game"
    assert parse_extract_line("Done!")["event"] == "done"
    assert parse_extract_line("Titles: 4") == {"event": "titles", "path": "4"}
    assert parse_extract_line("Error: bad key")["event"] == "error"
    assert recovery_warning("/usr/save", True) is None
    assert recovery_warning("/sys", True) is not None


def test_catalog_command_reads_usr_title_metadata(tmp_path: Path, monkeypatch):
    binary = tmp_path / "wfs-catalog"
    binary.write_bytes(b"#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    args = build_catalog_args(
        CatalogRequest(
            binary=binary,
            input_path=Path("usb.img"),
            image_type="usb",
            output_path=Path("out"),
            otp=Path("otp.bin"),
            seeprom=Path("seeprom.bin"),
            dump_usr_dir=True,
        )
    )
    assert args[0] == str(binary)
    assert "--dump-path" not in args
    assert "--verbose" not in args
    assert "--dump-usr-dir" in args
    assert args[args.index("--type") + 1] == "usb"
    assert args[args.index("--seeprom") + 1] == "seeprom.bin"
    plain = build_catalog_args(
        CatalogRequest(
            binary=binary,
            input_path=Path("plain.img"),
            image_type="plain",
            output_path=Path("out"),
            otp=Path("otp.bin"),
            seeprom=Path("seeprom.bin"),
        )
    )
    assert "--otp" not in plain
    assert "--seeprom" not in plain
    monkeypatch.delenv("WFS_CATALOG", raising=False)
    assert catalog_binary(tmp_path) is None
    monkeypatch.setenv("WFS_CATALOG", str(binary))
    assert catalog_binary(tmp_path) == binary
    monkeypatch.setenv("WFS_CATALOG", str(tmp_path / "missing"))
    assert catalog_binary(tmp_path) is None


def test_catalog_layout_scans_without_code_or_content(tmp_path: Path):
    title = tmp_path / "usr" / "title" / "00050000" / "101df400" / "meta"
    title.mkdir(parents=True)
    (title / "meta.xml").write_text(META, encoding="utf-8")
    (title / "iconTex.tga").write_bytes(b"tga")
    records = scan_titles(tmp_path)
    assert len(records) == 1
    assert records[0].name == "POKKÉN TOURNAMENT Deluxe"
    assert records[0].kind == "Game"
    assert not (tmp_path / "usr" / "title" / "00050000" / "101df400" / "code").exists()
    assert not (tmp_path / "usr" / "title" / "00050000" / "101df400" / "content").exists()


def test_platform_key_and_zip_slip(tmp_path: Path):
    assert platform_key("Darwin", "arm64") == "macos-arm64"
    assert platform_key("Windows", "AMD64") == "windows-x64"
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../evil.txt", "nope")
    with pytest.raises(RuntimeError):
        safe_extract(archive, tmp_path / "out")
    good = tmp_path / "good.zip"
    with zipfile.ZipFile(good, "w") as bundle:
        info = zipfile.ZipInfo("wfs-extract")
        info.external_attr = 0o755 << 16
        bundle.writestr(info, b"#!/bin/sh\n")
    safe_extract(good, tmp_path / "bin")
    extracted = tmp_path / "bin" / "wfs-extract"
    assert extracted.read_bytes().startswith(b"#!")
    assert extracted.stat().st_mode & 0o111
    assert len(sha256_file(extracted)) == 64


def test_byte_math_stays_exact_past_32_bits():
    assert format_bytes(0) == "0 B"
    assert format_bytes(-4) == "0 B"
    assert format_bytes(1536) == "1.5 KB"
    assert format_bytes(3 * 1024**3) == "3.0 GB"
    assert format_bytes(1024**4) == "1.0 TB"
    assert progress_permille(0, 10) == 0
    assert progress_permille(10, 0) == 0
    assert progress_permille(3 * 1024**3, 6 * 1024**3) == 500
    assert progress_permille(2**62, 2**63) == 500
    assert progress_permille(2**63, 2**62) == 1000


def test_size_cache_keeps_a_measured_title_until_meta_changes(tmp_path: Path):
    title = tmp_path / "title"
    (title / "meta").mkdir(parents=True)
    meta = title / "meta" / "meta.xml"
    meta.write_text("<menu></menu>", encoding="utf-8")
    stamp = meta_stamp(title)
    assert stamp
    cache_path = tmp_path / "cache" / "title-sizes.json"
    save_size_cache(cache_path, {str(title): {"size": 3 * 1024**3, "stamp": stamp}})
    loaded = load_size_cache(cache_path)
    assert loaded[str(title)]["size"] == 3 * 1024**3
    assert loaded[str(title)]["stamp"] == stamp

    meta.write_text("<menu>changed</menu>", encoding="utf-8")
    assert meta_stamp(title) != stamp
    assert load_size_cache(tmp_path / "missing.json") == {}
    (cache_path).write_text("{", encoding="utf-8")
    assert load_size_cache(cache_path) == {}


def test_fetch_cover_requests_regions_together():
    release = threading.Event()
    ready = threading.Condition()
    calls: list[str] = []
    png = b"\x89PNG\r\n\x1a\n"

    def fetch(url: str, timeout: float = 20):
        with ready:
            calls.append(url)
            ready.notify_all()
        if url.endswith("slow.png"):
            assert release.wait(2)
            return "missing", None
        return "png", png

    holder: list[tuple[str, bytes | None]] = []

    def run() -> None:
        holder.append(
            fetch_cover(
                ["https://art.example/slow.png", "https://art.example/fast.png"],
                fetch,
                1,
            )
        )

    thread = threading.Thread(target=run)
    thread.start()
    with ready:
        while len(calls) < 2:
            assert ready.wait(2)
    release.set()
    thread.join(2)
    assert holder == [("png", png)]


def test_fetch_cover_keeps_a_failed_request_out_of_the_miss_cache():
    def fetch(url: str, timeout: float = 20):
        if url.endswith("bad.png"):
            return "error", None
        return "missing", None

    assert fetch_cover(["https://art.example/no.png", "https://art.example/bad.png"], fetch, 1) == (
        "error",
        None,
    )
    assert fetch_cover(["https://art.example/no.png"], fetch, 1) == ("missing", None)
    cancel = threading.Event()
    cancel.set()
    assert fetch_cover(["https://art.example/no.png"], fetch, 1, cancel) == ("cancelled", None)


def test_directory_size_keeps_counts_past_32_bits(tmp_path: Path):
    folder = tmp_path / "title"
    folder.mkdir()
    big = folder / "data.bin"
    big.touch()
    size = 3 * 1024**3 + 5
    os.truncate(big, size)
    info = big.stat()
    assert info.st_blocks * 512 < 1024 * 1024
    (folder / ".DS_Store").write_bytes(b"xx")
    (folder / "data.bin.wfs-studio-partial").write_bytes(b"yyyy")
    (folder / "link.bin").symlink_to(big)
    assert directory_size(folder) == size
    cancel = threading.Event()
    cancel.set()
    assert directory_size(folder, cancel) is None


def test_copy_skips_symlink_and_partial(tmp_path: Path):
    folder = write_title(tmp_path / "src", "00050000", "101df400", META, b"payload-bytes")
    (folder / ".DS_Store").write_bytes(b"store")
    (folder / "content" / "link.bin").symlink_to(folder / "content" / "data.bin")
    (folder / "content" / "data.bin.wfs-studio-partial").write_bytes(b"temp")
    source = tmp_path / "src"
    dest = tmp_path / "dest"
    result = copy_titles(
        [(source, folder)],
        dest,
        skip_same_size=True,
        cancel=threading.Event(),
        on_progress=lambda _progress: None,
    )
    copied_root = dest / "usr" / "title" / "00050000" / "101df400"
    assert (copied_root / "content" / "data.bin").read_bytes() == b"payload-bytes"
    assert not (copied_root / "content" / "link.bin").exists()
    assert not (copied_root / ".DS_Store").exists()
    assert list(copied_root.rglob("*.wfs-studio-partial")) == []
    assert result.files_written == 2
    assert result.halted == ""


@pytest.mark.parametrize("code", [errno.ENOSPC, errno.EDQUOT])
def test_copy_stops_when_the_disk_is_full(tmp_path: Path, monkeypatch, code: int):
    folder = write_title(tmp_path / "src", "00050000", "101df400", META, b"payload-bytes")
    calls: list[Path] = []

    def boom(*_args, **_kwargs):
        calls.append(Path("called"))
        raise OSError(code, "No space left on device")

    monkeypatch.setattr("wfs_studio.copy_job._copy_one", boom)
    result = copy_titles(
        [(tmp_path / "src", folder)],
        tmp_path / "dest",
        skip_same_size=True,
        cancel=threading.Event(),
        on_progress=lambda _progress: None,
    )
    assert len(calls) == 1
    assert result.files_written == 0
    assert result.cancelled is False
    assert result.halted.startswith("Stopped. The destination ran out of space")
    assert result.errors


def test_copy_stops_when_planning_runs_out_of_space(tmp_path: Path, monkeypatch):
    folder = write_title(tmp_path / "src", "00050000", "101df400", META, b"payload-bytes")

    def boom(*_args, **_kwargs):
        raise OSError(errno.ENOSPC, "No space left on device", "dest")

    monkeypatch.setattr(Path, "mkdir", boom)
    result = copy_titles(
        [(tmp_path / "src", folder)],
        tmp_path / "dest",
        skip_same_size=True,
        cancel=threading.Event(),
        on_progress=lambda _progress: None,
    )
    assert result.files_written == 0
    assert "ran out of space" in result.halted


def test_extract_buffer_drops_a_split_line_when_capped():
    buffer, lines = append_extract_chunk("", "Dumping /usr/a\nDumping /usr/b\n")
    assert lines == ["Dumping /usr/a", "Dumping /usr/b"]
    assert buffer == ""
    buffer, lines = append_extract_chunk("", "Dumping /usr/partial")
    assert lines == []
    assert buffer == "Dumping /usr/partial"
    chunk = ("a" * 100) + "\nDumping /kept\n"
    buffer, lines = append_extract_chunk("", chunk, limit=40)
    assert lines == ["Dumping /kept"]
    assert "a" not in buffer


def test_cover_cache_remembers_hits_and_misses(tmp_path: Path):
    assert cover_paths(tmp_path, "../x") is None
    assert cover_paths(tmp_path, "ab") is None
    remember_cover_miss(tmp_path, "../etc")
    remember_cover(tmp_path, "../etc", b"\x89PNG\r\n\x1a\n")
    assert list(tmp_path.rglob("*")) == []

    png = b"\x89PNG\r\n\x1a\nrest"
    remember_cover(tmp_path, "aafe01", png)
    status, data = read_cover_cache(tmp_path, "AAFE01")
    assert status == "hit"
    assert data == png
    assert not (tmp_path / "covers" / "AAFE01.missing").exists()

    remember_cover_miss(tmp_path, "GF7E01")
    assert read_cover_cache(tmp_path, "GF7E01") == ("miss", None)
    remember_cover(tmp_path, "GF7E01", b"hello")
    assert read_cover_cache(tmp_path, "GF7E01") == ("miss", None)

    oversized = tmp_path / "covers" / "ZZZZ01.png"
    oversized.write_bytes(b"\x89PNG" + b"x" * 2_000_000)
    assert read_cover_cache(tmp_path, "ZZZZ01") == ("absent", None)


def test_fetch_png_separates_a_missing_image_from_a_failed_request(monkeypatch):
    def missing(*_args, **_kwargs):
        raise urllib.error.HTTPError("https://art.example/a.png", 404, "missing", None, None)

    monkeypatch.setattr("wfs_studio.gametdb.urllib.request.urlopen", missing)
    assert fetch_png("https://art.example/a.png", timeout=1) == ("missing", None)

    def failed(*_args, **_kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr("wfs_studio.gametdb.urllib.request.urlopen", failed)
    assert fetch_png("https://art.example/a.png", timeout=1) == ("error", None)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return b"\x89PNG\r\n\x1a\n"

    monkeypatch.setattr("wfs_studio.gametdb.urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    kind, data = fetch_png("https://art.example/a.png", timeout=1)
    assert kind == "png"
    assert data is not None and data.startswith(b"\x89PNG")


def test_settings_roundtrip(tmp_path: Path):
    save_settings(tmp_path, {"source": "/tmp/dump", "extract_type": "usb", "extra": "ignored"})
    loaded = load_settings(tmp_path)
    assert loaded["source"] == "/tmp/dump"
    assert loaded["extract_type"] == "usb"
    assert loaded["dump_path"] == "/"
    assert "extra" not in loaded
    assert json.loads((tmp_path / "cache" / "settings.json").read_text())["extract_type"] == "usb"
