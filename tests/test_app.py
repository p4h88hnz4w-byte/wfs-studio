import os
import struct
import threading
import time
import zipfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from wfs_studio import __version__
from wfs_studio.app import CoverWorker, MainWindow, SizeItem, SizeWorker, apply_theme
from wfs_studio.copy_job import CopyProgress
from wfs_studio.gametdb import parse_titles, remember_cover, remember_cover_miss
from wfs_studio.icon import rgba_png
from wfs_studio.titles import TitleRecord

META = """<?xml version="1.0" encoding="utf-8"?>
<menu>
  <product_code type="string" length="32">WUP-P-AAFE</product_code>
  <region type="hexBinary" length="4">00000002</region>
  <longname_en type="string" length="256">Bayonetta</longname_en>
  <title_version type="unsignedInt" length="4">16</title_version>
</menu>
"""


def test_window_lists_a_scanned_title(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("wfs_studio.app.fetch_png", lambda *_args, **_kwargs: ("missing", None))
    folder = tmp_path / "dump" / "usr" / "title" / "00050000" / "10112200"
    (folder / "meta").mkdir(parents=True)
    (folder / "content").mkdir()
    (folder / "meta" / "meta.xml").write_text(META, encoding="utf-8")
    (folder / "content" / "data.bin").write_bytes(b"1234")
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "wiiutdb.txt").write_text(
        "TITLES = test (version: 1)\nAAFE01 = Bayonetta\n",
        encoding="utf-8",
    )

    app = QApplication.instance() or QApplication([])
    window = MainWindow(root=tmp_path)
    window.show()
    app.processEvents()
    window.source_edit.setText(str(tmp_path / "dump"))
    window._scan()
    app.processEvents()
    for worker in list(window._workers):
        worker.wait(5000)
    app.processEvents()

    assert window.table.rowCount() == 1
    assert window.table.item(0, 2).text() == "Bayonetta"
    assert window.table.item(0, 5).text() == "USA (NTSC-U)"
    assert window.table.item(0, 7).text() == "Bayonetta"
    assert parse_titles((tmp_path / "cache" / "wiiutdb.txt").read_text()).by_id["AAFE01"] == "Bayonetta"
    window.table.setCurrentCell(0, 2)
    app.processEvents()
    for worker in list(window._workers):
        worker.wait(5000)
    app.processEvents()
    assert "Bayonetta" in window.detail_label.text()
    assert "USA (NTSC-U)" in window.detail_label.text()
    assert "00050000-10112200" in window.detail_label.text()
    assert (tmp_path / "cache" / "covers" / "AAFE01.missing").is_file()
    window.close()


def test_title_list_groups_update_and_dlc(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("wfs_studio.app.fetch_png", lambda *_args, **_kwargs: ("missing", None))
    game = tmp_path / "dump" / "usr" / "title" / "00050000" / "10112200"
    update = tmp_path / "dump" / "usr" / "title" / "0005000e" / "10112200"
    dlc = tmp_path / "dump" / "usr" / "title" / "0005000c" / "10112200"
    for folder, payload in ((game, b"game"), (update, b"up"), (dlc, b"dlc-data")):
        (folder / "meta").mkdir(parents=True)
        (folder / "content").mkdir()
        (folder / "meta" / "meta.xml").write_text(META, encoding="utf-8")
        (folder / "content" / "data.bin").write_bytes(payload)
    (tmp_path / "cache").mkdir()

    app = QApplication.instance() or QApplication([])
    window = MainWindow(root=tmp_path)
    window.show()
    app.processEvents()
    window.source_edit.setText(str(tmp_path / "dump"))
    window._scan()
    app.processEvents()
    for worker in list(window._workers):
        worker.wait(5000)
    app.processEvents()

    assert window.table.rowCount() == 1
    assert window.table.item(0, 1).text() == "Game + Update + DLC"
    assert window.table.item(0, 2).text() == "Bayonetta"
    assert window.table.item(0, 3).text() == "00050000-10112200"
    assert window._title_count_message() == "3 titles in 1 group"
    monkeypatch.setattr(
        "wfs_studio.app.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )
    window.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    chosen = window._checked_records()
    assert [record.kind for record in chosen] == ["Game", "Update", "DLC"]
    window.table.setCurrentCell(0, 2)
    app.processEvents()
    detail = window.detail_label.text()
    assert "Update 0005000E-10112200" in detail
    assert "DLC 0005000C-10112200" in detail
    window.search_edit.setText("0005000e-10112200")
    assert not window.table.isRowHidden(0)
    window.search_edit.setText("not-a-title")
    assert window.table.isRowHidden(0)
    window.close()


def test_size_worker_emits_byte_counts_past_2gib(tmp_path: Path, monkeypatch):
    size = 3 * 1024**3
    monkeypatch.setattr("wfs_studio.app.directory_size", lambda path, cancel=None: size)
    app = QApplication.instance() or QApplication([])
    record = TitleRecord(
        source_root=tmp_path,
        path=tmp_path,
        high_id="00050000",
        low_id="10112200",
        kind="Game",
        name="Big",
        product_code="",
        region="",
        version="",
        publisher="",
    )
    seen: list[object] = []
    worker = SizeWorker([record], threading.Event())
    worker.sized.connect(seen.append)
    worker.start()
    assert worker.wait(3000)
    app.processEvents()
    assert seen == [(str(tmp_path), size)]
    assert isinstance(seen[0][1], int)
    assert seen[0][1] > 2**31


def test_size_worker_reuses_a_cached_size(tmp_path: Path, monkeypatch):
    calls: list[Path] = []

    def fake(path, cancel=None):
        calls.append(path)
        return 10

    monkeypatch.setattr("wfs_studio.app.directory_size", fake)
    (tmp_path / "meta").mkdir()
    (tmp_path / "meta" / "meta.xml").write_text("<menu></menu>", encoding="utf-8")
    record = TitleRecord(
        source_root=tmp_path,
        path=tmp_path,
        high_id="00050000",
        low_id="10112200",
        kind="Game",
        name="Cached",
        product_code="",
        region="",
        version="",
        publisher="",
    )
    cache = tmp_path / "title-sizes.json"
    app = QApplication.instance() or QApplication([])

    def run_once(refresh: bool = False) -> list[object]:
        seen: list[object] = []
        worker = SizeWorker([record], threading.Event(), cache_path=cache, refresh=refresh)
        worker.sized.connect(seen.append)
        worker.start()
        assert worker.wait(3000)
        app.processEvents()
        return seen

    assert run_once() == [(str(tmp_path), 10)]
    assert calls == [tmp_path]
    calls.clear()
    assert run_once() == [(str(tmp_path), 10)]
    assert calls == []
    assert run_once(refresh=True) == [(str(tmp_path), 10)]
    assert calls == [tmp_path]


def test_size_cell_stores_a_large_byte_count():
    app = QApplication.instance() or QApplication([])
    del app
    item = SizeItem("…")
    size = 5 * 1024**3
    item.setData(Qt.ItemDataRole.UserRole, size)
    assert item.data(Qt.ItemDataRole.UserRole) == size


def test_copy_progress_bar_uses_permille_for_large_sizes(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(root=tmp_path)
    window._copy_progress(
        CopyProgress(
            copied_bytes=3 * 1024**3,
            total_bytes=6 * 1024**3,
            current_path="usr/title/00050000/10112200/content/data.bin",
            file_index=1,
            file_count=1,
        )
    )
    app.processEvents()
    assert window.copy_progress.value() == 500
    assert "3.0 GB of 6.0 GB" in window.copy_label.text()
    window.close()


def test_cover_worker_skips_network_after_a_miss(tmp_path: Path, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        "wfs_studio.app.fetch_png",
        lambda url, timeout=20, limit=2_000_000: calls.append(url),
    )
    remember_cover_miss(tmp_path, "GF7E01")
    app = QApplication.instance() or QApplication([])
    seen: list[tuple[int, object]] = []
    worker = CoverWorker(
        1,
        ["https://art.gametdb.com/wiiu/disc/US/GF7E01.png"],
        tmp_path,
        "GF7E01",
        threading.Event(),
    )
    worker.ready.connect(lambda generation, data: seen.append((generation, data)))
    worker.start()
    assert worker.wait(3000)
    app.processEvents()
    assert seen == [(1, None)]
    assert calls == []


def test_cover_worker_does_not_cache_a_network_error(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("wfs_studio.app.fetch_png", lambda *_args, **_kwargs: ("error", None))
    app = QApplication.instance() or QApplication([])
    worker = CoverWorker(
        1,
        ["https://art.gametdb.com/wiiu/disc/US/AAFE01.png"],
        tmp_path,
        "AAFE01",
        threading.Event(),
    )
    worker.ready.connect(lambda _generation, _data: None)
    worker.start()
    assert worker.wait(3000)
    app.processEvents()
    assert not (tmp_path / "covers" / "AAFE01.missing").exists()


def test_close_while_busy_can_stay_open(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "wfs_studio.app.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )
    app = QApplication.instance() or QApplication([])
    window = MainWindow(root=tmp_path)
    window.show()
    app.processEvents()
    window._busy = True
    window.close()
    app.processEvents()
    assert window.isVisible()
    assert window._closing is False
    window._busy = False
    window.close()


def test_close_while_busy_cancels_and_returns(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "wfs_studio.app.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    app = QApplication.instance() or QApplication([])
    window = MainWindow(root=tmp_path)
    window.show()
    app.processEvents()
    window._busy = True
    started = time.monotonic()
    window.close()
    assert window._closing is True
    assert window._cancel_copy.is_set()
    assert window._cancel_sizes.is_set()
    assert window._cancel_covers.is_set()
    assert time.monotonic() - started < 2


def _icon_tga(b: int, g: int, r: int) -> bytes:
    header = struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, 1, 1, 32, 0x28)
    return header + bytes((b, g, r, 255))


def _dump_with_icon(tmp_path: Path, tga: bytes) -> None:
    folder = tmp_path / "dump" / "usr" / "title" / "00050000" / "10112200"
    (folder / "meta").mkdir(parents=True)
    (folder / "content").mkdir()
    (folder / "meta" / "meta.xml").write_text(META, encoding="utf-8")
    (folder / "meta" / "iconTex.tga").write_bytes(tga)


def _select_scanned_title(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(root=tmp_path)
    window.show()
    app.processEvents()
    window.source_edit.setText(str(tmp_path / "dump"))
    window._scan()
    app.processEvents()
    for worker in list(window._workers):
        assert worker.wait(5000)
    app.processEvents()
    window.table.setCurrentCell(0, 2)
    app.processEvents()
    for worker in list(window._workers):
        assert worker.wait(5000)
    app.processEvents()
    return window


def _center_rgb(window: MainWindow) -> tuple[int, int, int]:
    image = window.cover_label.pixmap().toImage()
    color = image.pixelColor(image.width() // 2, image.height() // 2)
    return color.red(), color.green(), color.blue()


def test_title_list_shows_the_dump_icon(tmp_path: Path, monkeypatch):
    def fail_fetch(*_args, **_kwargs):
        raise AssertionError("disc fetch")

    monkeypatch.setattr("wfs_studio.app.fetch_png", fail_fetch)
    _dump_with_icon(tmp_path, _icon_tga(255, 0, 0))
    window = _select_scanned_title(tmp_path)
    assert not window.table.item(0, 2).icon().isNull()
    assert window.copy_button.text() == "Transfer"
    window.close()


def test_title_icon_shows_when_there_is_no_disc(tmp_path: Path, monkeypatch):
    def fail_fetch(*_args, **_kwargs):
        raise AssertionError("disc fetch")

    monkeypatch.setattr("wfs_studio.app.fetch_png", fail_fetch)
    _dump_with_icon(tmp_path, _icon_tga(255, 0, 0))
    window = _select_scanned_title(tmp_path)
    assert window.records[0].gametdb_id == ""
    assert _center_rgb(window) == (0, 0, 255)
    window.close()


def test_cached_disc_is_preferred_over_the_title_icon(tmp_path: Path, monkeypatch):
    def fail_fetch(*_args, **_kwargs):
        raise AssertionError("disc fetch")

    monkeypatch.setattr("wfs_studio.app.fetch_png", fail_fetch)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "wiiutdb.txt").write_text("TITLES = test (version: 1)\nAAFE01 = Bayonetta\n", encoding="utf-8")
    remember_cover(cache, "AAFE01", rgba_png(1, 1, bytes((255, 0, 0, 255))))
    _dump_with_icon(tmp_path, _icon_tga(255, 0, 0))
    window = _select_scanned_title(tmp_path)
    assert _center_rgb(window) == (255, 0, 0)
    window.close()


def test_banner_zip_is_preferred_over_the_title_icon(tmp_path: Path, monkeypatch):
    def fail_fetch(*_args, **_kwargs):
        raise AssertionError("disc fetch")

    monkeypatch.setattr("wfs_studio.app.fetch_png", fail_fetch)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "wiiutdb.txt").write_text("TITLES = test (version: 1)\nAAFE01 = Bayonetta\n", encoding="utf-8")
    archive = tmp_path / "banners.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("AAFE01.png", rgba_png(1, 1, bytes((0, 255, 0, 255))))
    _dump_with_icon(tmp_path, _icon_tga(255, 0, 0))
    app = QApplication.instance() or QApplication([])
    window = MainWindow(root=tmp_path)
    window.settings["cover_zip"] = str(archive)
    window._index_cover_zip()
    window.show()
    app.processEvents()
    window.source_edit.setText(str(tmp_path / "dump"))
    window._scan()
    app.processEvents()
    for worker in list(window._workers):
        worker.wait(5000)
    app.processEvents()
    window.table.setCurrentCell(0, 2)
    app.processEvents()
    assert _center_rgb(window) == (0, 255, 0)
    window.close()


def test_a_missed_disc_keeps_the_title_icon(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("wfs_studio.app.fetch_png", lambda *_args, **_kwargs: ("missing", None))
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "wiiutdb.txt").write_text("TITLES = test (version: 1)\nAAFE01 = Bayonetta\n", encoding="utf-8")
    _dump_with_icon(tmp_path, _icon_tga(255, 0, 0))
    window = _select_scanned_title(tmp_path)
    assert _center_rgb(window) == (0, 0, 255)
    assert (cache / "covers" / "AAFE01.missing").is_file()
    window.close()


def test_theme_uses_the_wii_u_menu_colors():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    sheet = app.styleSheet()
    assert "#009ac7" in sheet
    assert "#ffffff" in sheet
    assert "#e6ebed" in sheet
    assert "#1f7a6d" not in sheet
    assert "#1b1e22" not in sheet


def test_version_sits_in_the_top_right(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    window = MainWindow(root=tmp_path)
    window.show()
    app.processEvents()
    label = window.findChild(QLabel, "version")
    assert label is not None
    assert label.text() == f"v{__version__}"
    assert label.y() < 40
    assert label.x() > window.width() / 2
    window.close()


def test_checking_every_title_offers_an_archive(tmp_path: Path, monkeypatch):
    folder = tmp_path / "dump" / "usr" / "title" / "00050000" / "10112200"
    (folder / "meta").mkdir(parents=True)
    (folder / "content").mkdir()
    (folder / "meta" / "meta.xml").write_text(META, encoding="utf-8")
    (folder / "content" / "data.bin").write_bytes(b"1234")
    app = QApplication.instance() or QApplication([])
    window = MainWindow(root=tmp_path)
    window.show()
    app.processEvents()
    window.source_edit.setText(str(tmp_path / "dump"))
    window._scan()
    app.processEvents()
    for worker in list(window._workers):
        worker.wait(5000)
    app.processEvents()
    assert window.table.rowCount() == 1
    monkeypatch.setattr(
        "wfs_studio.app.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    target = tmp_path / "titles.zip"
    monkeypatch.setattr(
        "wfs_studio.app.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: (str(target), ""),
    )
    window._set_visible_checks(True)
    assert len(window._checked_records()) == 1
    assert window._title_archive == target
    window.close()


def _title(root: Path, name: str, low: str) -> TitleRecord:
    return TitleRecord(
        source_root=root,
        path=root / low,
        high_id="00050000",
        low_id=low,
        kind="Game",
        name=name,
        product_code="",
        region="USA",
        version="",
        publisher="",
    )


def test_ctrl_c_closes_without_the_quit_prompt(tmp_path: Path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(root=tmp_path)
    window.show()
    app.processEvents()
    window._busy = True
    app._interrupt = True

    def refuse(*_args, **_kwargs):
        raise AssertionError("Ctrl+C should close without asking")

    monkeypatch.setattr("wfs_studio.app.QMessageBox.question", refuse)
    window.close()
    app.processEvents()
    assert window._closing is True
    app._interrupt = False


def test_keyboard_interrupt_requests_one_clean_quit():
    from wfs_studio.app import request_interrupt

    class Fake:
        def __init__(self) -> None:
            self._interrupt = False
            self.quit_called = 0

        def quit(self) -> None:
            self.quit_called += 1

    app = Fake()
    request_interrupt(app)
    assert app._interrupt is True
    assert app.quit_called == 1


def test_notify_catches_ctrl_c():
    import subprocess
    import sys

    script = """
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QWidget
from wfs_studio.app import WfsApplication

app = WfsApplication([])

class Boom(QWidget):
    def event(self, event):
        raise KeyboardInterrupt()

assert app.notify(Boom(), QEvent(QEvent.Type.User)) is False
assert app._interrupt is True
print("ok")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
    assert "Error calling Python override" not in result.stderr


def test_edit_menu_select_all_follows_the_tab(tmp_path: Path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(root=tmp_path)
    window.show()
    app.processEvents()
    window.records = [_title(tmp_path, "Bayonetta", "10112200"), _title(tmp_path, "Other", "10113300")]
    window._fill_table()
    window.search_edit.setText("Bayonetta")
    app.processEvents()
    assert window.table.isRowHidden(1)
    monkeypatch.setattr(
        "wfs_studio.app.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.No,
    )
    window.tabs.setCurrentIndex(0)
    window.source_edit.setFocus()
    window.select_all_action.trigger()
    assert window.table.item(0, 0).checkState() == Qt.CheckState.Checked
    assert window.table.item(1, 0).checkState() == Qt.CheckState.Checked
    assert window._title_archive_declined is True

    profile = tmp_path / "dump" / "usr" / "save" / "00050000" / "10112200" / "user" / "80000001"
    profile.mkdir(parents=True)
    (profile / "save.dat").write_bytes(b"abc")
    window.source_edit.setText(str(tmp_path / "dump"))
    window._scan_saves()
    window.tabs.setCurrentIndex(1)
    window.select_all_action.trigger()
    assert len(window._checked_saves()) == 1
    assert window._save_archive_declined is True

    window.extract_log.setPlainText("alpha\nbeta")
    window.tabs.setCurrentIndex(2)
    window.input_edit.setFocus()
    window.select_all_action.trigger()
    cursor = window.extract_log.textCursor()
    assert cursor.selectionStart() == 0
    assert cursor.selectionEnd() == len("alpha\nbeta")
    window.close()


def test_copy_worker_archives_the_copied_title(tmp_path: Path):
    folder = tmp_path / "title"
    (folder / "meta").mkdir(parents=True)
    (folder / "content").mkdir()
    (folder / "meta" / "meta.xml").write_text("<menu></menu>", encoding="utf-8")
    (folder / "content" / "data.bin").write_bytes(b"1234")
    dest = tmp_path / "out"
    dest.mkdir()
    archive = tmp_path / "titles.zip"
    app = QApplication.instance() or QApplication([])
    assert app is not None
    from wfs_studio.app import CopyWorker

    worker = CopyWorker(
        [(folder, "Bayonetta [00050000-10112200]")],
        dest,
        True,
        threading.Event(),
        True,
        archive,
        ["Bayonetta [00050000-10112200]"],
    )
    worker.run()
    assert archive.is_file()
    assert worker.archive_note.startswith("Archive written to ")
    with zipfile.ZipFile(archive) as bundle:
        assert any(item.endswith("data.bin") for item in bundle.namelist())


def test_select_all_saves_offers_an_archive(tmp_path: Path, monkeypatch):
    profile = tmp_path / "dump" / "usr" / "save" / "00050000" / "10112200" / "user" / "80000001"
    profile.mkdir(parents=True)
    (profile / "save.dat").write_bytes(b"abc")
    app = QApplication.instance() or QApplication([])
    window = MainWindow(root=tmp_path)
    window.show()
    app.processEvents()
    window.source_edit.setText(str(tmp_path / "dump"))
    window._scan_saves()
    assert len(window.save_records) == 1
    monkeypatch.setattr(
        "wfs_studio.app.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    target = tmp_path / "packed.zip"
    monkeypatch.setattr(
        "wfs_studio.app.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: (str(target), ""),
    )
    window._select_all_saves()
    assert len(window._checked_saves()) == 1
    assert window._save_archive == target
    window.close()


def test_catalog_button_shows_the_metadata_command(tmp_path: Path, monkeypatch):
    binary = tmp_path / "wfs-catalog"
    binary.write_bytes(b"#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    monkeypatch.setenv("WFS_CATALOG", str(binary))
    app = QApplication.instance() or QApplication([])
    window = MainWindow(root=tmp_path)
    window.show()
    app.processEvents()
    assert window.catalog_button.text() == "Catalog titles"
    window.input_edit.setText(str(tmp_path / "image.bin"))
    window.output_edit.setText(str(tmp_path / "out"))
    window.plain_radio.setChecked(True)
    app.processEvents()
    catalog_lines = [
        line for line in window.command_preview.toPlainText().splitlines() if "wfs-catalog" in line
    ]
    assert len(catalog_lines) == 1
    assert "--dump-path" not in catalog_lines[0]
    assert "--type" in catalog_lines[0]
    assert "plain" in catalog_lines[0]
    monkeypatch.delenv("WFS_CATALOG")
    window._refresh_command()
    assert "build-catalog.sh" in window.command_preview.toPlainText()
    window.close()
