"""Small shared helpers."""

from __future__ import annotations


def format_bytes(size: int) -> str:
    """Format a byte count using 1024-based units."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"
