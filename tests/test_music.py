"""Menu music: the shipped Opus file, the credit, and a quiet offscreen window."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from wfs_studio.app import MainWindow, apply_linux_audio_backend
from wfs_studio.music import menu_track
from wfs_studio.settings import load_settings, save_settings


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


def test_audio_backend_menu_is_linux_only(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("wfs_studio.app._audio_backend_from_environment", False)
    app = QApplication.instance() or QApplication([])
    window = MainWindow(root=tmp_path, data=tmp_path)
    assert window.audio_backend_actions == {}
    window.close()
    app.processEvents()


def test_linux_audio_backend_is_remembered(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("wfs_studio.app._audio_backend_from_environment", False)
    monkeypatch.delenv("QT_AUDIO_BACKEND", raising=False)
    save_settings(tmp_path, {"linux_audio_backend": "PipeWire"})
    app = QApplication.instance() or QApplication([])
    window = MainWindow(root=tmp_path, data=tmp_path)
    app.processEvents()
    assert window.audio_backend_actions["PipeWire"].isChecked()
    assert window.audio_backend_actions["PulseAudio"].isChecked() is False
    window.audio_backend_actions["PulseAudio"].setChecked(True)
    assert load_settings(tmp_path)["linux_audio_backend"] == "PulseAudio"
    assert "PulseAudio" in window.statusBar().currentMessage()
    window.close()
    app.processEvents()


def test_environment_backend_is_shown_and_not_saved(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("wfs_studio.app._audio_backend_from_environment", True)
    monkeypatch.setenv("QT_AUDIO_BACKEND", "PipeWire")
    save_settings(tmp_path, {"linux_audio_backend": "PulseAudio"})
    app = QApplication.instance() or QApplication([])
    window = MainWindow(root=tmp_path, data=tmp_path)
    assert window.audio_backend_actions["PipeWire"].isChecked()
    assert window.audio_backend_actions["PipeWire"].isEnabled() is False
    window._persist()
    assert load_settings(tmp_path)["linux_audio_backend"] == "PulseAudio"
    window.close()
    app.processEvents()


def test_saved_pipewire_is_applied_when_the_environment_is_empty(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("QT_AUDIO_BACKEND", raising=False)
    apply_linux_audio_backend("PipeWire")
    assert os.environ["QT_AUDIO_BACKEND"] == "PipeWire"


def test_existing_audio_backend_variable_is_left_alone(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("QT_AUDIO_BACKEND", "PulseAudio")
    apply_linux_audio_backend("PipeWire")
    assert os.environ["QT_AUDIO_BACKEND"] == "PulseAudio"


def test_unknown_backend_falls_back_to_pulseaudio(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("QT_AUDIO_BACKEND", raising=False)
    apply_linux_audio_backend("alsa")
    assert os.environ["QT_AUDIO_BACKEND"] == "PulseAudio"


def test_mac_does_not_set_an_audio_backend(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("QT_AUDIO_BACKEND", raising=False)
    apply_linux_audio_backend("PipeWire")
    assert "QT_AUDIO_BACKEND" not in os.environ
