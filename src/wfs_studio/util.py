"""Small shared helpers.

Byte counts stay Python integers. Qt's ``int`` signal is only 32 bits, so
sizes and progress that cross that boundary must not be passed through it.
"""

from __future__ import annotations

_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def format_bytes(size: int) -> str:
    """Format a byte count using 1024-based units and integer tenths."""
    if size < 0:
        size = 0
    if size < 1024:
        return f"{size} B"
    unit_index = 0
    value = size
    while value >= 1024 and unit_index < len(_UNITS) - 1:
        value //= 1024
        unit_index += 1
    divisor = 1024**unit_index
    whole, frac = divmod((size * 10) // divisor, 10)
    return f"{whole}.{frac} {_UNITS[unit_index]}"


def progress_permille(copied: int, total: int) -> int:
    """Return 0..1000 without using floating point."""
    if total <= 0 or copied <= 0:
        return 0
    if copied >= total:
        return 1000
    return int((copied * 1000) // total)
