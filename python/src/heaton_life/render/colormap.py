"""Small built-in colormaps (256x3 uint8 LUTs), no matplotlib dependency."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

_ANCHORS: dict[str, list[tuple[int, int, int]]] = {
    "gray": [(0, 0, 0), (255, 255, 255)],
    "phosphor": [(6, 10, 6), (10, 60, 25), (40, 200, 90), (170, 255, 190)],
    "fire": [(0, 0, 0), (120, 16, 0), (255, 140, 0), (255, 255, 220)],
    "ice": [(0, 0, 0), (0, 40, 110), (70, 160, 255), (230, 250, 255)],
    "violet": [(8, 4, 16), (90, 30, 140), (200, 100, 255), (255, 240, 255)],
}


def list_colormaps() -> list[str]:
    """Names of the built-in colormaps."""
    return sorted(_ANCHORS)


def get_colormap(name: str) -> NDArray[np.uint8]:
    """Return a (256, 3) uint8 LUT for a named colormap."""
    try:
        anchors = _ANCHORS[name]
    except KeyError:
        raise ValueError(f"unknown colormap {name!r} (available: {sorted(_ANCHORS)})") from None
    positions = np.linspace(0.0, 1.0, len(anchors))
    xs = np.linspace(0.0, 1.0, 256)
    channels = [np.interp(xs, positions, [a[c] for a in anchors]) for c in range(3)]
    return np.stack(channels, axis=1).round().astype(np.uint8)


def apply_colormap(
    frame: NDArray[np.generic], cmap: str | NDArray[np.uint8] = "gray"
) -> NDArray[np.uint8]:
    """Turn any frame (2-D uint8 / 2-D float in [0,1] / HxWx3 uint8) into HxWx3 RGB."""
    if frame.ndim == 3:
        if frame.shape[2] != 3 or frame.dtype != np.uint8:
            raise ValueError(f"3-D frames must be HxWx3 uint8, got {frame.shape} {frame.dtype}")
        return frame.astype(np.uint8, copy=False)
    if frame.ndim != 2:
        raise ValueError(f"frames must be 2-D or HxWx3, got shape {frame.shape}")
    if np.issubdtype(frame.dtype, np.floating):
        index = (np.clip(frame, 0.0, 1.0) * 255.0).round().astype(np.uint8)
    elif frame.dtype == np.uint8:
        index = frame
    else:
        raise ValueError(f"2-D frames must be uint8 or float, got dtype {frame.dtype}")
    lut = get_colormap(cmap) if isinstance(cmap, str) else cmap
    result: NDArray[np.uint8] = lut[index]
    return result
