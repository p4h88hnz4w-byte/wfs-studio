"""Build and interpret wfs-extract command lines.

The runner reads an image and writes a folder. It does not modify the input.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExtractRequest:
    binary: Path
    input_path: Path
    image_type: str
    output_path: Path
    dump_path: str = "/"
    otp: Path | None = None
    seeprom: Path | None = None
    dump_usr_dir: bool = False


def build_args(request: ExtractRequest) -> list[str]:
    dump_path = request.dump_path.strip() or "/"
    args = [
        str(request.binary),
        "--input",
        str(request.input_path),
        "--type",
        request.image_type,
        "--output",
        str(request.output_path),
        "--dump-path",
        dump_path,
        "--verbose",
    ]
    if request.image_type != "plain" and request.otp is not None:
        args.extend(["--otp", str(request.otp)])
    if request.image_type == "usb" and request.seeprom is not None:
        args.extend(["--seeprom", str(request.seeprom)])
    if request.dump_usr_dir:
        args.append("--dump-usr-dir")
    return args


def format_command(args: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in args)


def recovery_warning(dump_path: str, enabled: bool) -> str | None:
    if not enabled:
        return None
    trimmed = dump_path.strip().strip("/")
    if trimmed and trimmed != "usr" and not trimmed.startswith("usr/"):
        return "Recovery mode only dumps paths inside /usr."
    return None


_EXTRACT_BUFFER_LIMIT = 1_048_576


def append_extract_chunk(
    buffer: str,
    chunk: str,
    limit: int = _EXTRACT_BUFFER_LIMIT,
) -> tuple[str, list[str]]:
    """Append extractor output and return complete lines plus the leftover.

    The leftover stays within ``limit`` bytes. After a cut, bytes before the
    first newline are dropped so a split line is not parsed as a path.
    """
    combined = buffer + chunk
    if len(combined) > limit:
        combined = combined[-limit:]
        newline = combined.find("\n")
        if newline != -1:
            combined = combined[newline + 1 :]
    lines: list[str] = []
    while "\n" in combined:
        line, combined = combined.split("\n", 1)
        lines.append(line.rstrip("\r"))
    return combined, lines


def parse_extract_line(line: str) -> dict[str, str]:
    text = line.strip()
    if text.startswith("Dumping /"):
        return {"event": "file", "path": text.split(" ", 1)[1]}
    if text == "Dumping...":
        return {"event": "start", "path": ""}
    if text == "Done!":
        return {"event": "done", "path": ""}
    if text.startswith("Error:") or text.startswith("error:"):
        return {"event": "error", "path": text}
    if not text:
        return {"event": "blank", "path": ""}
    return {"event": "log", "path": text}
