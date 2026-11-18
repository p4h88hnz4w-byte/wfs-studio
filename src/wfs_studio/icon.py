"""Turn a Wii U title icon into PNG bytes.

``meta/iconTex.tga`` on a dumped title is an uncompressed 32-bit TGA.
Qt does not reliably load that file, so the window is given a PNG instead.
The decoder uses only the standard library.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

_HEADER = 18
_MAX_EDGE = 1024
_MAX_FILE = 8 * 1024 * 1024


def title_icon_png(path: Path) -> bytes | None:
    """Return a PNG for ``path``, or None when the file is missing or not a plain TGA."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) > _MAX_FILE:
        return None
    try:
        return tga_to_png(data)
    except ValueError:
        return None


def tga_to_png(data: bytes) -> bytes:
    """Decode an uncompressed truecolor TGA into an 8-bit RGBA PNG.

    Raises ``ValueError`` for any other TGA. Bytes after the pixel block,
    including a TGA 2.0 footer, are ignored.
    """
    if len(data) < _HEADER:
        raise ValueError("TGA header is short")
    id_len = data[0]
    colormap = data[1]
    image_type = data[2]
    width, height = struct.unpack_from("<HH", data, 12)
    depth = data[16]
    descriptor = data[17]
    if colormap != 0 or image_type != 2:
        raise ValueError("Only uncompressed truecolor TGA is supported")
    if depth not in (24, 32):
        raise ValueError("TGA pixel depth must be 24 or 32")
    if width == 0 or height == 0 or width > _MAX_EDGE or height > _MAX_EDGE:
        raise ValueError("TGA size is out of range")
    pixel_bytes = depth // 8
    start = _HEADER + id_len
    need = width * height * pixel_bytes
    if start + need > len(data):
        raise ValueError("TGA pixel data is short")
    pixels = data[start : start + need]
    use_alpha = depth == 32 and (descriptor & 0x0F) != 0
    top_down = bool(descriptor & 0x20)
    right_to_left = bool(descriptor & 0x10)
    rgba = bytearray(width * height * 4)
    source_rows = range(height) if top_down else range(height - 1, -1, -1)
    out = 0
    for src_y in source_rows:
        row = pixels[src_y * width * pixel_bytes : (src_y + 1) * width * pixel_bytes]
        xs = range(width - 1, -1, -1) if right_to_left else range(width)
        for x in xs:
            offset = x * pixel_bytes
            rgba[out] = row[offset + 2]
            rgba[out + 1] = row[offset + 1]
            rgba[out + 2] = row[offset]
            rgba[out + 3] = row[offset + 3] if use_alpha else 255
            out += 4
    return rgba_png(width, height, bytes(rgba))


def rgba_png(width: int, height: int, rgba: bytes) -> bytes:
    """Encode tightly packed 8-bit RGBA rows as a PNG."""
    if width <= 0 or height <= 0 or len(rgba) != width * height * 4:
        raise ValueError("RGBA buffer does not match the image size")

    def chunk(tag: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)

    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        raw.extend(rgba[y * stride : (y + 1) * stride])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
