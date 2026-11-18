"""Menu music shipped with the window.

``assets/menu.opus`` is Joth's "8bit Bossa" (CC0,
https://opengameart.org/content/bossa-nova). The original MP3 is not in
this repo. This file is 48 kHz Opus encoded at 64 kbps. A two-second
crossfade joins the ending to the opening, so a player loop does not click.
"""

from __future__ import annotations

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
