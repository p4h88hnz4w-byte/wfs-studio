import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from wfs_studio.app import MainWindow
from wfs_studio.gametdb import parse_titles

META = """<?xml version="1.0" encoding="utf-8"?>
<menu>
  <product_code type="string" length="32">WUP-P-AAFE</product_code>
  <region type="hexBinary" length="4">00000002</region>
  <longname_en type="string" length="256">Bayonetta</longname_en>
  <title_version type="unsignedInt" length="4">16</title_version>
</menu>
"""


def test_window_lists_a_scanned_title(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("wfs_studio.app.download_bytes", lambda *_args, **_kwargs: None)
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
    assert "Bayonetta" in window.detail_label.text()
    assert "00050000-10112200" in window.detail_label.text()
    window.close()
