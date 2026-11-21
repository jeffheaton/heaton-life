"""Pattern images: a pixel is a cell, dead when white and alive otherwise
(spec/formats.md "Images").

PNG pixels come from Pillow, as the library's other PNG reading does, but the header and
palette are read here so that what counts as white, and which files are refused, follow
the spec rather than one decoder's habits: 16-bit samples count by their high byte, an
index past the palette is an error, and transparency never matters. BMP is decoded here
outright: it is simple, and its variants are where decoders disagree.
"""

from __future__ import annotations

import dataclasses
import io
import struct
import zlib

import numpy as np
from numpy.typing import NDArray
from PIL import Image, UnidentifiedImageError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
BMP_HEADER_SIZES = (12, 40, 52, 56, 108, 124)

# PNG's allowed bit depths for each color type (ISO/IEC 15948, table 11.1).
_PNG_DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}

Cells = NDArray[np.uint8]


def is_bmp(data: bytes) -> bool:
    """``BM`` and one of the info header sizes this reader knows (spec/formats.md)."""
    return (
        len(data) >= 18
        and data[:2] == b"BM"
        and struct.unpack_from("<I", data, 14)[0] in BMP_HEADER_SIZES
    )


def _check_limit(width: int, height: int, max_cells: int | None) -> None:
    if max_cells is not None and width * height > max_cells:
        raise ValueError(
            f"the image is {width:,} × {height:,} pixels, past the limit of {max_cells:,} cells"
        )


# -- PNG ------------------------------------------------------------------------------------


def _png_chunks(data: bytes) -> tuple[tuple[int, int, int, int, int], bytes | None]:
    """IHDR's (width, height, depth, color type, interlace) and PLTE's bytes, checked."""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("not a PNG: bad signature")
    pos = len(PNG_SIGNATURE)
    header: tuple[int, int, int, int, int] | None = None
    palette: bytes | None = None
    saw_data = False
    while True:
        if pos + 8 > len(data):
            raise ValueError("not a PNG: it ends before IEND")
        length, kind = struct.unpack_from(">I4s", data, pos)
        body = pos + 8
        if length > 0x7FFFFFFF or body + length + 4 > len(data):
            raise ValueError("not a PNG: a chunk runs past the end of the file")
        if header is None and kind != b"IHDR":
            raise ValueError("not a PNG: the first chunk is not IHDR")
        if kind == b"IHDR":
            if header is not None or length != 13:
                raise ValueError("not a PNG: a broken IHDR")
            width, height, depth, color, compression, method, interlace = struct.unpack_from(
                ">IIBBBBB", data, body
            )
            if not (0 < width <= 0x7FFFFFFF and 0 < height <= 0x7FFFFFFF):
                raise ValueError(f"not a PNG: an image {width} × {height}")
            if depth not in _PNG_DEPTHS.get(color, ()):
                raise ValueError(f"not a PNG: bit depth {depth} with color type {color}")
            if compression != 0 or method != 0 or interlace not in (0, 1):
                raise ValueError("not a PNG: unknown compression, filter, or interlace method")
            header = (width, height, depth, color, interlace)
        elif kind == b"PLTE":
            if palette is not None or length == 0 or length % 3 or length > 768:
                raise ValueError("not a PNG: a broken PLTE")
            palette = data[body : body + length]
        elif kind == b"IDAT":
            saw_data = True
        elif kind == b"IEND":
            break
        pos = body + length + 4
    assert header is not None
    if not saw_data:
        raise ValueError("not a PNG: no IDAT")
    if header[3] == 3 and palette is None:
        raise ValueError("not a PNG: an indexed image without PLTE")
    return header, palette


def png_size(data: bytes) -> tuple[int, int]:
    """A PNG image's (width, height), its chunks checked as ``png_cells`` checks them but no
    pixel decoded (spec/formats.md "Measuring")."""
    (width, height, _depth, _color, _interlace), _palette = _png_chunks(data)
    return width, height


def png_cells(data: bytes, max_cells: int | None = None) -> Cells:
    """A PNG image's cells, 1 alive and 0 dead (white); refused past ``max_cells``."""
    (width, height, _depth, color, _interlace), palette = _png_chunks(data)
    _check_limit(width, height, max_cells)
    try:
        with Image.open(io.BytesIO(data), formats=["PNG"]) as image:
            image.load()
            mode = image.mode
            pixels = np.asarray(image)
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        OSError,
        SyntaxError,
        ValueError,
        zlib.error,
    ) as error:
        raise ValueError(f"not a PNG: {error}") from error
    if pixels.shape[:2] != (height, width):
        raise ValueError("not a PNG: the image is not the size its header says")
    if color == 3:
        if mode != "P" or palette is None:
            raise ValueError(f"unexpected PNG decode: mode {mode!r} for an indexed image")
        entries = len(palette) // 3
        if int(pixels.max(initial=0)) >= entries:
            raise ValueError(f"PNG pixel index past the palette's {entries} entries")
        rgb = np.frombuffer(palette, dtype=np.uint8).reshape(entries, 3)
        white = (rgb == 255).all(axis=1)
        live = ~white[pixels]
    elif mode == "1":
        live = ~pixels.astype(bool)
    elif mode == "L":
        live = pixels != 255
    elif mode in ("I", "I;16", "I;16B", "I;16L"):
        live = (pixels.astype(np.int64) >> 8) != 255  # a 16-bit sample by its high byte
    elif mode == "LA":
        live = pixels[:, :, 0] != 255
    elif mode in ("RGB", "RGBA"):
        live = ~(pixels[:, :, :3] == 255).all(axis=2)
    else:
        raise ValueError(f"unexpected PNG decode: mode {mode!r}")
    return np.ascontiguousarray(live, dtype=np.uint8)


# -- BMP ------------------------------------------------------------------------------------

_WHOLE_BYTES = (0xFF, 0xFF00, 0xFF0000, 0xFF000000)
_MASKS_16 = ((0xF800, 0x07E0, 0x001F), (0x7C00, 0x03E0, 0x001F))


@dataclasses.dataclass(frozen=True)
class _BmpLayout:
    """A BMP image as far as its pixels: size, row layout, and what counts as white."""

    width: int
    height: int
    bits: int
    rows: NDArray[np.uint8]
    """(height, stride) stored rows, top to bottom."""
    masks: tuple[int, int, int] | None
    white: NDArray[np.bool_] | None
    """Which palette entries are white, for 1, 4 and 8 bits."""


def _bmp_layout(data: bytes, max_cells: int | None) -> _BmpLayout:
    """Everything ``bmp_cells`` checks before it reads a pixel (spec/formats.md "Images")."""
    if not is_bmp(data):
        raise ValueError("not a BMP: bad signature or header size")
    offset, header_size = (
        struct.unpack_from("<I", data, 10)[0],
        struct.unpack_from("<I", data, 14)[0],
    )
    if len(data) < 14 + header_size:
        raise ValueError("not a BMP: the info header runs past the end of the file")
    if header_size == 12:
        width, height, _planes, bits = struct.unpack_from("<HHHH", data, 18)
        compression, colors, entry, top_down = 0, 0, 3, False
        if width == 0 or height == 0:
            raise ValueError(f"not a BMP: an image {width} × {height}")
        if bits not in (1, 4, 8, 24):
            raise ValueError(f"unsupported BMP: {bits} bits a pixel in a core header")
    else:
        width, height = struct.unpack_from("<ii", data, 18)
        bits, compression = struct.unpack_from("<HI", data, 28)
        colors = struct.unpack_from("<I", data, 46)[0]
        entry, top_down = 4, height < 0
        if width < 1 or height == 0:
            raise ValueError(f"not a BMP: an image {width} × {height}")
        height = abs(height)
    _check_limit(width, height, max_cells)

    masks: tuple[int, int, int] | None = None
    if compression == 0:
        if bits not in (1, 4, 8, 16, 24, 32):
            raise ValueError(f"unsupported BMP: {bits} bits a pixel")
    elif compression == 3:
        if bits not in (16, 32):
            raise ValueError(f"unsupported BMP: bit fields with {bits} bits a pixel")
        if len(data) < 66:
            raise ValueError("not a BMP: the bit field masks run past the end of the file")
        masks = struct.unpack_from("<III", data, 54)
        if bits == 16 and masks not in _MASKS_16:
            raise ValueError(f"unsupported BMP: 16-bit masks {[hex(m) for m in masks]}")
        if bits == 32 and (len(set(masks)) != 3 or not all(m in _WHOLE_BYTES for m in masks)):
            raise ValueError(f"unsupported BMP: 32-bit masks {[hex(m) for m in masks]}")
    else:
        raise ValueError(f"unsupported BMP compression {compression}")

    stride = (width * bits + 31) // 32 * 4
    if offset + stride * height > len(data):
        raise ValueError("not a BMP: the pixel data ends before the last row")

    white: NDArray[np.bool_] | None = None
    if bits <= 8:
        usable = min(colors or 1 << bits, 1 << bits)
        start = 14 + header_size
        if start + usable * entry > len(data):
            raise ValueError("not a BMP: the palette runs past the end of the file")
        table = np.frombuffer(data, dtype=np.uint8, count=usable * entry, offset=start)
        white = (table.reshape(usable, entry)[:, :3] == 255).all(axis=1)
    stored = np.frombuffer(data, dtype=np.uint8, count=stride * height, offset=offset)
    rows = stored.reshape(height, stride)  # a view: nothing is copied until a pixel is read
    return _BmpLayout(width, height, bits, rows if top_down else rows[::-1], masks, white)


def bmp_size(data: bytes) -> tuple[int, int]:
    """A BMP image's (width, height), its headers, masks, palette and the length of its
    pixel data checked as ``bmp_cells`` checks them but no pixel read (spec/formats.md
    "Measuring")."""
    layout = _bmp_layout(data, None)
    return layout.width, layout.height


def bmp_cells(data: bytes, max_cells: int | None = None) -> Cells:
    """A BMP image's cells, 1 alive and 0 dead (white); refused past ``max_cells``."""
    layout = _bmp_layout(data, max_cells)
    width, height, bits, rows, masks = (
        layout.width,
        layout.height,
        layout.bits,
        layout.rows,
        layout.masks,
    )
    stride = rows.shape[1]
    if layout.white is not None:
        white = layout.white
        usable = len(white)
        if bits == 1:
            index = np.unpackbits(rows, axis=1)[:, :width]
        elif bits == 4:
            index = np.empty((height, stride * 2), dtype=np.uint8)
            index[:, 0::2] = rows >> 4
            index[:, 1::2] = rows & 0x0F
            index = index[:, :width]
        else:
            index = rows[:, :width]
        if int(index.max(initial=0)) >= usable:
            raise ValueError(f"BMP pixel index past the palette's {usable} entries")
        live = ~white[index]
    elif bits == 24:
        live = ~(rows[:, : width * 3].reshape(height, width, 3) == 255).all(axis=2)
    else:
        size = bits // 8
        words = np.ascontiguousarray(rows[:, : width * size]).view("<u2" if size == 2 else "<u4")
        if masks is None:
            need = 0x7FFF if bits == 16 else 0x00FFFFFF  # 5-5-5, or blue, green, red bytes
        else:
            need = masks[0] | masks[1] | masks[2]
        live = (words.astype(np.uint64) & need) != need
    return np.ascontiguousarray(live, dtype=np.uint8)
