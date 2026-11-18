import struct
from pathlib import Path

import pytest

from wfs_studio.icon import rgba_png, tga_to_png, title_icon_png


def _tga(
    pixels: bytes,
    width: int,
    height: int,
    *,
    depth: int = 32,
    top: bool = False,
    right: bool = False,
    image_id: bytes = b"",
    footer: bytes = b"",
) -> bytes:
    descriptor = 0
    if depth == 32:
        descriptor |= 8
    if top:
        descriptor |= 0x20
    if right:
        descriptor |= 0x10
    header = struct.pack(
        "<BBBHHBHHHHBB",
        len(image_id),
        0,
        2,
        0,
        0,
        0,
        0,
        0,
        width,
        height,
        depth,
        descriptor,
    )
    return header + image_id + pixels + footer


def _png_rgba(data: bytes) -> tuple[int, int, bytes]:
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    pos = 8
    width = height = 0
    idat = b""
    while pos + 8 <= len(data):
        length = struct.unpack_from(">I", data, pos)[0]
        tag = data[pos + 4 : pos + 8]
        payload = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height = struct.unpack_from(">II", payload)
        elif tag == b"IDAT":
            idat += payload
        elif tag == b"IEND":
            break
    import zlib

    raw = zlib.decompress(idat)
    rows = bytearray()
    stride = width * 4
    cursor = 0
    for _ in range(height):
        assert raw[cursor] == 0
        cursor += 1
        rows.extend(raw[cursor : cursor + stride])
        cursor += stride
    return width, height, bytes(rows)


def test_bottom_up_tga_becomes_top_down_png():
    # File order is bottom row first: blue, green, then red, white.
    pixels = bytes(
        [
            255, 0, 0, 255,
            0, 255, 0, 255,
            0, 0, 255, 255,
            255, 255, 255, 128,
        ]
    )
    png = tga_to_png(_tga(pixels, 2, 2, footer=b"\x00" * 26))
    width, height, rgba = _png_rgba(png)
    assert (width, height) == (2, 2)
    assert rgba == bytes(
        [
            255, 0, 0, 255,
            255, 255, 255, 128,
            0, 0, 255, 255,
            0, 255, 0, 255,
        ]
    )


def test_top_origin_and_24_bit_keep_row_order_and_opaque_alpha():
    pixels = bytes([0, 0, 255, 255, 255, 255])
    png = tga_to_png(_tga(pixels, 2, 1, depth=24, top=True, image_id=b"skip-me"))
    _width, _height, rgba = _png_rgba(png)
    assert rgba == bytes([255, 0, 0, 255, 255, 255, 255, 255])


def test_right_to_left_rows_are_reversed():
    pixels = bytes([0, 0, 255, 255, 255, 0, 0, 255])
    png = tga_to_png(_tga(pixels, 2, 1, top=True, right=True))
    _width, _height, rgba = _png_rgba(png)
    assert rgba[:4] == bytes([0, 0, 255, 255])
    assert rgba[4:] == bytes([255, 0, 0, 255])


@pytest.mark.parametrize(
    "blob",
    [
        b"",
        _tga(b"\x00" * 16, 2, 2)[:10],
        bytes([0, 0, 10]) + b"\x00" * 15 + b"\x00" * 16,
        _tga(b"\x00", 1, 1),
    ],
)
def test_other_tga_kinds_are_refused(blob: bytes):
    with pytest.raises(ValueError):
        tga_to_png(blob)


def test_title_icon_png_reads_a_file_and_ignores_a_bad_one(tmp_path: Path):
    good = tmp_path / "iconTex.tga"
    good.write_bytes(_tga(bytes([0, 0, 255, 255]), 1, 1, top=True))
    png = title_icon_png(good)
    assert png is not None and png.startswith(b"\x89PNG")
    bad = tmp_path / "broken.tga"
    bad.write_bytes(b"not-a-tga")
    assert title_icon_png(bad) is None
    assert title_icon_png(tmp_path / "missing.tga") is None


def test_rgba_png_rejects_a_short_buffer():
    with pytest.raises(ValueError):
        rgba_png(2, 2, b"\x00" * 4)
