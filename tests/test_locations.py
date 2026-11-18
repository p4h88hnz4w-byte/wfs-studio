from pathlib import Path

from wfs_studio.locations import data_dir, license_dir


def test_license_files_live_beside_the_source(tmp_path: Path):
    assert license_dir(tmp_path, frozen=False) == (tmp_path / "packaging" / "licenses").resolve()


def test_a_checkout_keeps_data_beside_the_project(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("WFS_STUDIO_DATA", raising=False)
    assert data_dir(tmp_path, frozen=False) == tmp_path.resolve()


def test_data_dir_honors_an_override(tmp_path: Path, monkeypatch):
    chosen = tmp_path / "elsewhere"
    monkeypatch.setenv("WFS_STUDIO_DATA", str(chosen))
    assert data_dir(tmp_path, frozen=True, system="Linux", home=tmp_path / "home") == chosen.resolve()


def test_frozen_data_dir_follows_the_platform(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("WFS_STUDIO_DATA", raising=False)
    home = tmp_path / "home"
    assert data_dir(tmp_path, frozen=True, system="Darwin", home=home) == (
        home / "Library" / "Application Support" / "WFS Studio"
    )
    assert data_dir(tmp_path, frozen=True, system="Linux", home=home) == (
        home / ".local" / "share" / "wfs-studio"
    )
    assert data_dir(tmp_path, frozen=True, system="Windows", home=home) == (
        home / "AppData" / "Roaming" / "WFS Studio"
    )
