"""Path checks for copy and extract jobs.

These checks refuse destinations that would write back into the source tree.
They do not delete anything.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path


class PathIssue(ValueError):
    """The chosen paths are not safe to use."""


def normalize_existing(path: Path) -> Path:
    """Resolve a path that already exists."""
    return path.expanduser().resolve()


def normalize_destination(path: Path) -> Path:
    """Resolve a destination that may not exist yet."""
    dest = path.expanduser()
    if dest.exists():
        return dest.resolve()
    parts: list[str] = []
    current = dest
    while not current.exists():
        parts.append(current.name)
        parent = current.parent
        if parent == current:
            raise PathIssue(f"Cannot resolve {path}.")
        current = parent
    resolved = current.resolve()
    for name in reversed(parts):
        resolved = resolved / name
    return resolved


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def validate_copy(source: Path, dest: Path) -> tuple[Path, Path]:
    """Return resolved source and destination, or raise PathIssue."""
    if not source.expanduser().exists():
        raise PathIssue("The source folder does not exist.")
    source_resolved = normalize_existing(source)
    if not source_resolved.is_dir():
        raise PathIssue("The source must be a folder.")
    dest_resolved = normalize_destination(dest)
    if dest_resolved.exists() and not dest_resolved.is_dir():
        raise PathIssue("The destination exists and is not a folder.")
    if source_resolved == dest_resolved:
        raise PathIssue("The destination is the same folder as the source.")
    if _inside(dest_resolved, source_resolved):
        raise PathIssue(
            "The destination is inside the source. Pick a folder outside the dump."
        )
    if _inside(source_resolved, dest_resolved):
        raise PathIssue("The source is inside the destination.")
    return source_resolved, dest_resolved


def is_file_or_device(path: Path) -> bool:
    """True for a regular file or a block/character device."""
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode) or stat.S_ISBLK(mode) or stat.S_ISCHR(mode)


def validate_key_file(path: Path, label: str) -> Path:
    """Require a small regular file. otp.bin and seeprom.bin are a few kilobytes."""
    if not path.expanduser().exists():
        raise PathIssue(f"The {label} file does not exist.")
    resolved = normalize_existing(path)
    if not resolved.is_file():
        raise PathIssue(f"The {label} path must be a file.")
    size = resolved.stat().st_size
    if size == 0 or size > 1_048_576:
        raise PathIssue(
            f"The {label} file is {size} bytes. otp.bin and seeprom.bin are small key files."
        )
    return resolved


def validate_extract_paths(
    input_path: Path,
    output_path: Path,
    otp: Path | None,
    seeprom: Path | None,
    image_type: str,
) -> None:
    """Check an extract job before any process is started."""
    if image_type not in {"usb", "mlc", "plain"}:
        raise PathIssue("Type must be usb, mlc, or plain.")
    if not input_path.expanduser().exists():
        raise PathIssue("The input image or device does not exist.")
    source = normalize_existing(input_path)
    if not is_file_or_device(source):
        raise PathIssue("The input must be an image file or a device path.")
    output = normalize_destination(output_path)
    if output.exists() and not output.is_dir():
        raise PathIssue("The output path exists and is not a folder.")
    if output == source:
        raise PathIssue("The output folder is the same path as the input.")
    if _inside(output, source):
        raise PathIssue("The output folder is inside the input.")
    if image_type != "plain":
        if otp is None:
            raise PathIssue("An otp.bin file is required for this image type.")
        validate_key_file(otp, "otp")
    if image_type == "usb":
        if seeprom is None:
            raise PathIssue("A seeprom.bin file is required for a USB image.")
        validate_key_file(seeprom, "seeprom")
    # A device node is not a directory, so this comparison matters for file images.
    try:
        if source.is_file() and _inside(source, output):
            raise PathIssue(
                "The output folder contains the input image. Pick a different output folder."
            )
    except OSError:
        pass
    if otp is not None and image_type != "plain":
        if normalize_existing(otp) == source:
            raise PathIssue("otp.bin is the same file as the input image.")
    if seeprom is not None and image_type == "usb":
        if normalize_existing(seeprom) == source:
            raise PathIssue("seeprom.bin is the same file as the input image.")


def output_is_nonempty(path: Path) -> bool:
    if not path.expanduser().exists():
        return False
    resolved = normalize_existing(path)
    if not resolved.is_dir():
        return False
    return any(resolved.iterdir())


def same_file(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False
