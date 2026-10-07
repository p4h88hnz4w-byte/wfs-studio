import json
import threading
import zipfile
from pathlib import Path

import pytest

from wfs_studio.binaries import platform_key, safe_extract, sha256_file
from wfs_studio.copy_job import copy_titles
from wfs_studio.extract import ExtractRequest, build_args, parse_extract_line, recovery_warning
from wfs_studio.gametdb import annotate, lookup, parse_titles
from wfs_studio.paths import PathIssue, validate_copy, validate_extract_paths
from wfs_studio.settings import load_settings, save_settings
from wfs_studio.titles import load_meta_text, scan_titles

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
    assert parse_extract_line("Error: bad key")["event"] == "error"
    assert recovery_warning("/usr/save", True) is None
    assert recovery_warning("/sys", True) is not None


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


def test_settings_roundtrip(tmp_path: Path):
    save_settings(tmp_path, {"source": "/tmp/dump", "extract_type": "usb", "extra": "ignored"})
    loaded = load_settings(tmp_path)
    assert loaded["source"] == "/tmp/dump"
    assert loaded["extract_type"] == "usb"
    assert loaded["dump_path"] == "/"
    assert "extra" not in loaded
    assert json.loads((tmp_path / "cache" / "settings.json").read_text())["extract_type"] == "usb"
