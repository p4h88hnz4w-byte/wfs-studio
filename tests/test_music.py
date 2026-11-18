"""Menu music: the shipped Opus file, the credit, and a quiet offscreen window."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from wfs_studio.app import MainWindow
from wfs_studio.music import menu_track
from wfs_studio.settings import load_settings


def test_menu_track_is_a_small_opus_file():
    path = menu_track()
    assert path is not None
    data = path.read_bytes()
    assert data.startswith(b"OggS")
    assert b"OpusHead" in data[:200]
    assert b"Joth" in data
    assert b"CC0" in data
    # The source MP3 is 160 kbps and about 1.2 MB. This encode is well under that.
    assert 200_000 < path.stat().st_size < 800_000


def test_window_credits_the_track_and_stays_quiet_offscreen(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(root=tmp_path, data=tmp_path)
    app.processEvents()
    assert window.menu_music_action.isChecked()
    assert window._player is None
    text = window._about_text()
    assert "Joth" in text
    assert "CC0" in text
    assert "opengameart.org/content/bossa-nova" in text
    window.menu_music_action.setChecked(False)
    window._persist()
    assert load_settings(tmp_path)["menu_music"] is False
    window.close()


def test_silence_clears_the_track_instead_of_calling_stop(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(root=tmp_path, data=tmp_path)

    class Player:
        def __init__(self):
            self.urls: list[QUrl] = []
            self.stopped = False

        def source(self) -> QUrl:
            return QUrl() if self.urls else QUrl.fromLocalFile("/tmp/menu.opus")

        def setSource(self, url: QUrl) -> None:
            self.urls.append(url)

        def stop(self) -> None:
            self.stopped = True

    player = Player()
    window._player = player
    window._stop_menu_music()
    assert player.urls and player.urls[0].isEmpty()
    assert player.stopped is False
    window._player = None
    window.close()
    app.processEvents()
