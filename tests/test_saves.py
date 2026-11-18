import json
import threading
from pathlib import Path

import tarfile
import zipfile

import pytest

from wfs_studio.paths import PathIssue
from wfs_studio.saves import (
    archive_format,
    backup_saves,
    fat32_title,
    savemii_dir_name,
    scan_saves,
    write_save_archive,
)


def write_save(root: Path, high: str, low: str, profiles: dict[str, bytes], common: bytes | None = None) -> Path:
    folder = root / "usr" / "save" / high / low
    (folder / "meta").mkdir(parents=True)
    (folder / "meta" / "meta.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<menu>
  <product_code type="string" length="32">WUP-P-APKE</product_code>
  <longname_en type="string" length="256">Pokken: Deluxe</longname_en>
</menu>
""",
        encoding="utf-8",
    )
    (folder / "meta" / "saveinfo.xml").write_text("<saveinfo>ok</saveinfo>", encoding="utf-8")
    (folder / "meta" / "iconTex.tga").write_bytes(b"icon-bytes")
    user = folder / "user"
    user.mkdir()
    for name, payload in profiles.items():
        profile = user / name
        profile.mkdir()
        (profile / "save.dat").write_bytes(payload)
    if common is not None:
        shared = user / "common"
        shared.mkdir()
        (shared / "common.dat").write_bytes(common)
    return folder


def test_scan_accepts_the_high_id_folder_and_one_title(tmp_path: Path):
    write_save(tmp_path, "00050000", "101DF400", {"80000013": b"profile"}, b"shared")
    other = tmp_path / "usr" / "save" / "00050000" / "10111100" / "user" / "80000001"
    other.mkdir(parents=True)
    (other / "save.dat").write_bytes(b"second")
    high = tmp_path / "usr" / "save" / "00050000"
    from_high = scan_saves(high)
    from_dump = scan_saves(tmp_path)
    assert [record.title_id for record in from_high] == [record.title_id for record in from_dump]
    assert len(from_high) == 2
    one = scan_saves(high / "101DF400")
    assert [record.title_id for record in one] == ["00050000-101df400"]
    assert scan_saves(tmp_path / "usr" / "save") == from_dump
    assert scan_saves(tmp_path / "usr") == from_dump


def test_scan_lists_profiles_and_skips_system(tmp_path: Path):
    write_save(tmp_path, "00050000", "101DF400", {"80000013": b"profile"}, b"shared")
    system = tmp_path / "usr" / "save" / "system" / "barista"
    system.mkdir(parents=True)
    (system / "account.dat").write_bytes(b"nope")
    records = scan_saves(tmp_path)
    assert len(records) == 1
    assert records[0].title_id == "00050000-101df400"
    assert records[0].name == "Pokken: Deluxe"
    assert records[0].profiles == ("80000013",)
    assert records[0].has_common is True


def _backup_folder(root: Path) -> tuple[Path, str]:
    name = "Game [00050000-10112200]"
    slot = root / name / "0"
    slot.mkdir(parents=True)
    (slot / "save.dat").write_bytes(b"abc")
    return root, name


def test_archive_format_is_zip_on_mac_and_7z_or_bzip_on_linux(monkeypatch):
    assert archive_format("Darwin") == "zip"
    monkeypatch.setattr("wfs_studio.saves.shutil.which", lambda name: "/usr/bin/7z" if name == "7z" else None)
    assert archive_format("Linux") == "7z"
    monkeypatch.setattr("wfs_studio.saves.shutil.which", lambda _name: None)
    assert archive_format("Linux") == "bzip2"


def test_zip_and_bzip_archives_contain_the_backup(tmp_path: Path):
    root, name = _backup_folder(tmp_path / "backups")
    zip_path = write_save_archive(root, [name], tmp_path / "out.zip", fmt="zip")
    with zipfile.ZipFile(zip_path) as bundle:
        assert any(item.endswith("save.dat") for item in bundle.namelist())
    bz_path = write_save_archive(root, [name], tmp_path / "out.tar.bz2", fmt="bzip2")
    with tarfile.open(bz_path, "r:bz2") as bundle:
        assert any(item.endswith("save.dat") for item in bundle.getnames())


def test_archive_must_sit_outside_the_backup_folder(tmp_path: Path):
    root, name = _backup_folder(tmp_path / "backups")
    with pytest.raises(PathIssue):
        write_save_archive(root, [name], root / "inside.zip", fmt="zip")


def test_archive_accepts_a_nested_title_and_rejects_a_parent_path(tmp_path: Path):
    root = tmp_path / "copied"
    nested = root / "00050000" / "10112200" / "content"
    nested.mkdir(parents=True)
    (nested / "data.bin").write_bytes(b"title")
    zip_path = write_save_archive(root, ["00050000/10112200"], tmp_path / "titles.zip", fmt="zip")
    with zipfile.ZipFile(zip_path) as bundle:
        assert any(item.endswith("data.bin") for item in bundle.namelist())
    with pytest.raises(PathIssue):
        write_save_archive(root, ["00050000/../copied"], tmp_path / "escape.zip", fmt="zip")


def test_savemii_folder_name_replaces_forbidden_characters():
    assert fat32_title("Pokkén: Tournament") == "Pokk_n_ Tournament"
    name = savemii_dir_name("Pokkén: Tournament", "00050000", "101DF400")
    assert name == "Pokk_n_ Tournament [00050000-101df400]"
    assert "/" not in name
    assert ":" not in name


def test_backup_writes_a_savemii_slot_and_leaves_the_dump(tmp_path: Path):
    title = write_save(tmp_path / "dump", "00050000", "101df400", {"80000013": b"profile-bytes"}, b"shared")
    before = (title / "user" / "80000013" / "save.dat").read_bytes()
    records = scan_saves(tmp_path / "dump")
    dest = tmp_path / "backups"
    result = backup_saves(
        records,
        dest,
        storage="NAND",
        cancel=threading.Event(),
        on_progress=lambda _progress: None,
    )
    slot = dest / "Pokken_ Deluxe [00050000-101df400]" / "0"
    assert result.verified is True
    assert (slot / "80000013" / "save.dat").read_bytes() == b"profile-bytes"
    assert (slot / "common" / "common.dat").read_bytes() == b"shared"
    assert (slot / "savemii_saveinfo.xml").read_text(encoding="utf-8") == "<saveinfo>ok</saveinfo>"
    assert not (slot / "iconTex.tga").exists()
    meta = json.loads((slot / "savemiiMeta.json").read_text(encoding="utf-8"))
    assert meta["highID"] == "00050000"
    assert meta["lowID"] == "101df400"
    assert meta["storage"] == "NAND"
    assert meta["backupFormat"] == "FILES"
    assert meta["backupHealth"] == "0"
    assert meta["serialId"] == "_WIIU_"
    assert meta["shortName"] == "Pokken: Deluxe"
    assert (title / "user" / "80000013" / "save.dat").read_bytes() == before

    second = backup_saves(records, dest, cancel=threading.Event(), on_progress=lambda _progress: None)
    assert second.verified is True
    assert (dest / "Pokken_ Deluxe [00050000-101df400]" / "1" / "savemiiMeta.json").is_file()
