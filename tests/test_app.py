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
from PySide6.QtWidgets import QApplication, QMessageBox

from wfs_studio.app import CoverWorker, MainWindow, SizeItem, SizeWorker
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
    assert window.table.item(0, 7).text() == "Bayonetta"
    assert parse_titles((tmp_path / "cache" / "wiiutdb.txt").read_text()).by_id["AAFE01"] == "Bayonetta"
    window.table.setCurrentCell(0, 2)
    app.processEvents()
    for worker in list(window._workers):
        worker.wait(5000)
    app.processEvents()
    assert "Bayonetta" in window.detail_label.text()
    assert "00050000-10112200" in window.detail_label.text()
    assert (tmp_path / "cache" / "covers" / "AAFE01.missing").is_file()
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
