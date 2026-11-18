"""Where the program reads its install, and where it writes user data.

A source checkout keeps ``cache/`` and ``vendor/`` next to the project, which
is the layout this repository already uses. A frozen app cannot write inside
its own bundle, so those folders move to a per-user directory. ``WFS_STUDIO_DATA``
overrides either choice.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from wfs_studio.binaries import repo_root


def license_dir(install: Path | None = None, *, frozen: bool | None = None) -> Path:
    """Directory of the license files that ship with this program.

    A checkout keeps them in ``packaging/licenses``. A frozen macOS app
    copies that folder to ``Contents/Resources/licenses``.
    """
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        executable = Path(sys.executable).resolve()
        bundled = executable.parent.parent / "Resources" / "licenses"
        beside = executable.parent / "licenses"
        if bundled.is_dir():
            return bundled
        if beside.is_dir():
            return beside
        return bundled
    root = (install or repo_root()).resolve()
    return root / "packaging" / "licenses"


def data_dir(
    install: Path | None = None,
    *,
    frozen: bool | None = None,
    system: str | None = None,
    home: Path | None = None,
) -> Path:
    """Return the directory that contains ``cache/`` and ``vendor/``."""
    override = os.environ.get("WFS_STUDIO_DATA")
    if override:
        return Path(override).expanduser().resolve()
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    checkout = (install or repo_root()).resolve()
    if not frozen:
        return checkout
    home_dir = (home or Path.home()).expanduser()
    system_name = (system if system is not None else sys.platform).lower()
    if system_name in {"darwin", "macos"}:
        return home_dir / "Library" / "Application Support" / "WFS Studio"
    if system_name.startswith("win"):
        if home is None and os.environ.get("APPDATA"):
            return Path(os.environ["APPDATA"]) / "WFS Studio"
        return home_dir / "AppData" / "Roaming" / "WFS Studio"
    if home is None and os.environ.get("XDG_DATA_HOME"):
        return Path(os.environ["XDG_DATA_HOME"]).expanduser() / "wfs-studio"
    return home_dir / ".local" / "share" / "wfs-studio"
