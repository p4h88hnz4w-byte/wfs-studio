"""Menu music shipped with the window.

``assets/menu.opus`` is Joth's "8bit Bossa" (CC0,
https://opengameart.org/content/bossa-nova). The original MP3 is not in
this repo. This file is 48 kHz Opus encoded at 64 kbps. A two-second
crossfade joins the ending to the opening, so a player loop does not click.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

MENU_VOLUME = 0.35
MENU_CREDIT = (
    "Menu music is 8bit Bossa by Joth, CC0, from "
    "https://opengameart.org/content/bossa-nova."
)


def menu_track() -> Path | None:
    """Return the Opus file, from the package or from a frozen build."""
    bundled = Path(__file__).resolve().parent / "assets" / "menu.opus"
    if bundled.is_file():
        return bundled
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        frozen = Path(meipass) / "menu.opus"
        if frozen.is_file():
            return frozen
    return None


def quiet_ffmpeg_logs() -> None:
    """Hide Qt's own FFmpeg category. The player still reports a real open error.

    Do not call ``av_log_set_level`` here. On PipeWire, Qt is still starting
    its FFmpeg copy when the menu track opens, and that call never returns.
    The window stops answering and the track never starts.
    """
    try:
        from PySide6.QtCore import QLoggingCategory
    except ImportError:
        return
    rules = os.environ.get("QT_LOGGING_RULES", "")
    quiet = "qt.multimedia.ffmpeg=false"
    if quiet not in rules:
        rules = f"{rules}\n{quiet}" if rules else quiet
    QLoggingCategory.setFilterRules(rules)
