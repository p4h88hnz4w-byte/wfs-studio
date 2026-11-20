"""Local settings stored in the user data directory, under ``cache/``."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULTS = {
    "source": "",
    "dest": "",
    "skip_same_size": True,
    "input": "",
    "extract_type": "mlc",
    "otp": "",
    "seeprom": "",
    "output": "",
    "dump_path": "/",
    "dump_usr_dir": False,
    "gametdb_zip": "",
    "cover_zip": "",
    "game_data_copy": True,
    "save_dest": "",
    "save_usb": False,
    "menu_music": True,
    "linux_audio_backend": "PulseAudio",
}

# Qt's QT_AUDIO_BACKEND names. PulseAudio stays the default: on Ubuntu it is
# PipeWire's pulse layer, and it is the backend the window already ships with.
LINUX_AUDIO_BACKENDS = ("PulseAudio", "PipeWire")


def normalize_linux_audio_backend(value: object) -> str:
    if value in LINUX_AUDIO_BACKENDS:
        return str(value)
    return "PulseAudio"


def cache_dir(root: Path) -> Path:
    path = root / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path(root: Path) -> Path:
    return cache_dir(root) / "settings.json"


def load_settings(root: Path) -> dict:
    path = settings_path(root)
    if not path.is_file():
        return dict(DEFAULTS)
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)
    if not isinstance(stored, dict):
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update({key: stored[key] for key in DEFAULTS if key in stored})
    return merged


def save_settings(root: Path, values: dict) -> None:
    merged = dict(DEFAULTS)
    merged.update({key: values[key] for key in DEFAULTS if key in values})
    path = settings_path(root)
    path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
