"""Small built-in colormaps (256x3 uint8 LUTs), no matplotlib dependency.

Two registries (spec/render.md): the anchor colormaps, built by interpolating a few
anchors and indexed by clipping, and the cyclic palettes, byte tables that wrap and are
meant for the phase lookup (apply_phase).
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray

from heaton_life.render._palette_tables import TABLES
from heaton_life.render.dither import tpdf_frame

_ANCHORS: dict[str, list[tuple[int, int, int]]] = {
    "gray": [(0, 0, 0), (255, 255, 255)],
    "phosphor": [(6, 10, 6), (10, 60, 25), (40, 200, 90), (170, 255, 190)],
    "fire": [(0, 0, 0), (120, 16, 0), (255, 140, 0), (255, 255, 220)],
    "ice": [(0, 0, 0), (0, 40, 110), (70, 160, 255), (230, 250, 255)],
    "violet": [(8, 4, 16), (90, 30, 140), (200, 100, 255), (255, 240, 255)],
    # Anchors land exactly on indices 0/85/170/255 -> Wireworld's 4 states get the
    # classic empty/head/tail/conductor colors when frames are encoded as state*85.
    "wireworld": [(0, 0, 0), (70, 130, 255), (255, 80, 60), (255, 210, 70)],
    # Closed hue wheel: index 255 matches index 0, which suits cyclic CA states.
    "rainbow": [
        (220, 40, 40),
        (230, 200, 40),
        (60, 200, 70),
        (50, 200, 220),
        (70, 70, 230),
        (200, 60, 220),
        (220, 40, 40),
    ],
}


def list_colormaps() -> list[str]:
    """Names of the anchor colormaps (the clipping lookup's)."""
    return sorted(_ANCHORS)


def list_cyclic_colormaps() -> list[str]:
    """Names of the cyclic palettes (spec/render.md "Cyclic palettes"), for apply_phase."""
    return list(TABLES)


def is_cyclic(name: str) -> bool:
    """True for a cyclic palette, False for an anchor colormap; unknown names raise."""
    if name in TABLES:
        return True
    if name in _ANCHORS:
        return False
    raise ValueError(f"unknown colormap {name!r}")


def get_colormap(name: str) -> NDArray[np.uint8]:
    """Return a (256, 3) uint8 LUT for a named colormap or cyclic palette."""
    if name in TABLES:
        return np.frombuffer(bytes.fromhex(TABLES[name]), dtype=np.uint8).reshape(256, 3).copy()
    try:
        anchors = _ANCHORS[name]
    except KeyError:
        known = sorted(_ANCHORS) + list(TABLES)
        raise ValueError(f"unknown colormap {name!r} (available: {known})") from None
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


def apply_phase(
    t: NDArray[np.float64],
    cmap: str | NDArray[np.uint8],
    *,
    wrap: str = "cyclic",
    interior: tuple[int, int, int] = (0, 0, 0),
    antialias: bool = True,
    dither: float = 1.0,
    frame_index: int = 0,
) -> NDArray[np.uint8]:
    """Color an unwrapped phase t (cycles; NaN where a pixel did not escape) through a
    palette that repeats (spec/render.md "Phase lookup"): linear interpolation between
    entries, an antialias blend toward the palette's mean where t moves more than about
    a third of a cycle per pixel, and a +-1-code triangular dither per channel.
    wrap "cyclic" (256 positions, for the cyclic palettes) or "mirror" (510: any
    colormap up and back down). Returns (height, width, 3) uint8."""
    if t.ndim != 2 or not np.issubdtype(t.dtype, np.floating):
        raise ValueError("t must be a 2-D float array")
    if wrap == "cyclic":
        period = 256
        entry = np.arange(256)
    elif wrap == "mirror":
        period = 510
        k = np.arange(510)
        entry = np.where(k <= 255, k, 510 - k)
    else:
        raise ValueError(f"wrap must be 'cyclic' or 'mirror', got {wrap!r}")
    if not (math.isfinite(dither) and dither >= 0.0):
        raise ValueError("dither must be finite and non-negative")
    if len(interior) != 3 or any(not 0 <= v <= 255 for v in interior):
        raise ValueError("interior must be three bytes")
    lut = get_colormap(cmap) if isinstance(cmap, str) else cmap
    if lut.shape != (256, 3) or lut.dtype != np.uint8:
        raise ValueError("a colormap is a (256, 3) uint8 array")
    height, width = t.shape
    t = t.astype(np.float64, copy=False)
    with np.errstate(over="ignore", invalid="ignore"):
        x = t * float(period)
    valid = np.isfinite(t) & np.isfinite(x)
    out = np.empty((height, width, 3), dtype=np.uint8)
    out[~valid] = interior
    xs = x[valid]
    fl = np.floor(xs)
    f = xs - fl
    k0 = fl - float(period) * np.floor(fl / float(period))
    k0 = np.where(k0 < 0.0, k0 + period, k0)
    k0 = np.where(k0 >= period, k0 - period, k0)
    i0 = k0.astype(np.int64)
    i1 = np.where(i0 + 1 == period, 0, i0 + 1)
    a = lut[entry[i0]].astype(np.float64)
    b = lut[entry[i1]].astype(np.float64)
    v = a + (b - a) * f[:, None]
    if antialias:
        mean = lut[entry].astype(np.int64).sum(axis=0) / float(period)
        need = _phase_need(t)[valid]
        alias = np.clip((need - 0.35) / (1.0 - 0.35), 0.0, 1.0)
        alias = (alias * alias) * (3.0 - 2.0 * alias)
        v = v + (mean[None, :] - v) * alias[:, None]
    if dither != 0.0:
        noise = tpdf_frame(width, height, frame_index)[valid].astype(np.float64) * 2.0**-32
        v = v + dither * noise
    out[valid] = np.clip(np.round(v), 0.0, 255.0).astype(np.uint8)
    return out


def _phase_need(t: NDArray[np.float64]) -> NDArray[np.float64]:
    """The largest |t - t_n| over each pixel's four neighbors whose t is finite; 0 if none."""
    need = np.zeros(t.shape, dtype=np.float64)
    finite = np.isfinite(t)
    with np.errstate(invalid="ignore", over="ignore"):
        across = np.abs(t[:, 1:] - t[:, :-1])
        down = np.abs(t[1:, :] - t[:-1, :])
    across = np.where(finite[:, 1:] & finite[:, :-1], across, 0.0)
    down = np.where(finite[1:, :] & finite[:-1, :], down, 0.0)
    need[:, 1:] = np.maximum(need[:, 1:], across)
    need[:, :-1] = np.maximum(need[:, :-1], across)
    need[1:, :] = np.maximum(need[1:, :], down)
    need[:-1, :] = np.maximum(need[:-1, :], down)
    return need
