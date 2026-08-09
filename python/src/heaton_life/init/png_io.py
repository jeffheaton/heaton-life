"""PNG grid I/O for MergeLife worlds (spec/png-io.md).

Scale-aware: an export at scale k renders each cell as a solid k*k block; a
decode at scale k samples the top-left pixel of each block. PNG bytes are
per-encoder; only decoded grids are part of the cross-language contract.
"""

from __future__ import annotations

import io

import numpy as np
import numpy.typing as npt
from PIL import Image, UnidentifiedImageError

Rgb = npt.NDArray[np.uint8]


def mergelife_from_png(data: bytes, scale: int = 1) -> Rgb:
    """Decode PNG bytes into an (h, w, 3) uint8 grid; alpha, if present, is dropped."""
    if scale < 1:
        raise ValueError("scale must be >= 1")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if image.mode not in ("RGB", "RGBA"):
                raise ValueError(
                    f"unsupported PNG mode {image.mode!r}: need 8-bit RGB or RGBA"
                )
            rgb = np.asarray(image)[:, :, :3]
    except (UnidentifiedImageError, OSError, SyntaxError) as error:
        raise ValueError(f"not a PNG: {error}") from error
    height, width = rgb.shape[0], rgb.shape[1]
    if width % scale or height % scale:
        raise ValueError(f"image {width}x{height} is not a multiple of scale {scale}")
    return np.ascontiguousarray(rgb[::scale, ::scale, :]).astype(np.uint8)


def mergelife_to_png(grid: Rgb, scale: int = 1) -> bytes:
    """Encode an (h, w, 3) uint8 grid as PNG with each cell a scale*scale block."""
    if scale < 1:
        raise ValueError("scale must be >= 1")
    if grid.ndim != 3 or grid.shape[2] != 3 or grid.dtype != np.uint8:
        raise ValueError("grid must be an (h, w, 3) uint8 array")
    scaled = np.repeat(np.repeat(grid, scale, axis=0), scale, axis=1)
    buffer = io.BytesIO()
    Image.fromarray(scaled, mode="RGB").save(buffer, format="PNG")
    return buffer.getvalue()
