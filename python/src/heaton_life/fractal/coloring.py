"""Fractal color -- spec/fractal-color.md: stretch, depth phase, frequency, distance shading.

How an escape-time frame's smooth values mu and distance estimates become colors that
hold still while a view moves. Presentation only: counts never depend on it. Every
function is bit-exact given its inputs -- plain float64 operations in the spec's order,
no libm beyond sqrt -- and the C# port (FractalColor) matches it byte for byte.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int32]
ByteArray = NDArray[np.uint8]

LOG2_10 = 3.321928094887362  # the double nearest log2(10): 0x400A934F0979A371
_DIAGONAL_1080P_SQUARED = 1920 * 1920 + 1080 * 1080  # 4852800

__all__ = [
    "LOG2_10",
    "Frequency",
    "PhaseParams",
    "ShadeParams",
    "Stretch",
    "apply_stretch",
    "color_scale",
    "depth_phase",
    "measure_frequency",
    "measure_stretch",
    "retune",
    "shade_distance",
    "smoothstep",
]


def color_scale(width: int, height: int) -> float:
    """sqrt(W^2 + H^2) / sqrt(1920^2 + 1080^2): pixel-sized parameters are given at 1080p
    and scaled to the frame. Integer squares, correctly rounded square roots -- never
    hypot, which is libm."""
    if width < 1 or height < 1:
        raise ValueError("frame dimensions must be positive")
    return math.sqrt(float(width * width + height * height)) / math.sqrt(
        float(_DIAGONAL_1080P_SQUARED)
    )


def smoothstep(e0: float, e1: float, x: FloatArray) -> FloatArray:
    """(t*t)*(3 - 2t) with t = clip((x - e0) / (e1 - e0), 0, 1)."""
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    result: FloatArray = (t * t) * (3.0 - 2.0 * t)
    return result


# --- stretch --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Stretch:
    """The 1st and 99th percentiles of a frame's escaped mu -- the bounds the per-frame
    stretch maps onto [0, 1]. Kept and reused, a frozen stretch."""

    lo: float
    hi: float


def measure_stretch(mu: FloatArray) -> Stretch | None:
    """The frame's own stretch: NumPy's linear percentiles 1 and 99 of the escaped
    (mu > 0) values; None when nothing escaped."""
    escaped = mu[mu > 0]
    if escaped.size == 0:
        return None
    lo, hi = np.percentile(escaped, [1.0, 99.0])
    return Stretch(float(lo), float(hi))


def apply_stretch(mu: FloatArray, stretch: Stretch) -> FloatArray:
    """Escaped pixels: 0.6 if hi <= lo (a featureless frame), else
    clip((mu - lo) / (hi - lo), 0.02, 1); the rest 0; then sqrt. normalize_render is
    apply_stretch(mu, measure_stretch(mu))."""
    values = np.zeros(mu.shape, dtype=np.float64)
    escaped = mu > 0
    if stretch.hi <= stretch.lo:
        values[escaped] = 0.6
    else:
        # the floor keeps escaped pixels distinguishable from the interior
        values[escaped] = np.clip((mu[escaped] - stretch.lo) / (stretch.hi - stretch.lo), 0.02, 1.0)
    result: FloatArray = np.sqrt(values)
    return result


# --- depth phase ----------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PhaseParams:
    """t = (phase_offset + cycles_per_octave * u) + cycles_per_iteration * (mu - anchor),
    u = zoom_log10 * LOG2_10. cycles_per_octave 0 (the default) gives a point the same
    color at every zoom; Heaton Fractal's video flow uses 0.25."""

    cycles_per_iteration: float = 0.01
    cycles_per_octave: float = 0.0
    phase_offset: float = 0.0
    anchor: float = 0.0

    def __post_init__(self) -> None:
        for name in ("cycles_per_iteration", "cycles_per_octave", "phase_offset", "anchor"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")


def depth_phase(mu: FloatArray, zoom_log10: float, params: PhaseParams | None = None) -> FloatArray:
    """The unwrapped palette phase t, in cycles, for every escaped (mu > 0) pixel; NaN
    elsewhere. Unwrapped so an epsilon difference in mu stays an epsilon difference in
    t -- the lookup (render.apply_phase) wraps it."""
    if not math.isfinite(zoom_log10):
        raise ValueError("zoom must be finite")
    params = params or PhaseParams()
    base = params.phase_offset + params.cycles_per_octave * (zoom_log10 * LOG2_10)
    t = np.full(mu.shape, np.nan, dtype=np.float64)
    escaped = mu > 0
    t[escaped] = base + params.cycles_per_iteration * (mu[escaped] - params.anchor)
    return t


# --- frequency ------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Frequency:
    """A fitted cycles_per_iteration and the anchor (an escape count) it pivots on."""

    cycles_per_iteration: float
    anchor: float


def measure_frequency(
    counts: IntArray,
    mu: FloatArray,
    *,
    target_cycles_per_step: float = 0.03,
    max_cycles_per_iteration: float = 0.01,
) -> Frequency | None:
    """Fit the phase frequency to one frame (Heaton Fractal's single-station fit): the
    upper median of neighbor steps |mu - mu_left| and |mu - mu_up| where both escaped
    with a finite mu,
    c = min(max, (target / color_scale) / max(step, 1)), anchor = the upper median of
    the positive counts. None with fewer than 64 steps."""
    if not (math.isfinite(target_cycles_per_step) and target_cycles_per_step > 0):
        raise ValueError("target_cycles_per_step must be finite and positive")
    if not (math.isfinite(max_cycles_per_iteration) and max_cycles_per_iteration > 0):
        raise ValueError("max_cycles_per_iteration must be finite and positive")
    if counts.shape != mu.shape or mu.ndim != 2:
        raise ValueError("counts and mu must be (height, width) arrays of one shape")
    height, width = mu.shape
    escaped = (mu > 0) & (mu < np.inf)  # a finite mu: an infinite pair would step by NaN
    with np.errstate(invalid="ignore"):  # inf - inf where a pixel is not counted anyway
        across = np.abs(mu[:, 1:] - mu[:, :-1])[escaped[:, 1:] & escaped[:, :-1]]
        down = np.abs(mu[1:, :] - mu[:-1, :])[escaped[1:, :] & escaped[:-1, :]]
    steps = np.concatenate([across, down])
    positive = counts[counts > 0]
    if steps.size < 64 or positive.size == 0:
        return None
    step = float(np.sort(steps)[steps.size // 2])
    anchor = float(np.sort(positive)[positive.size // 2])
    scaled = (target_cycles_per_step / color_scale(width, height)) / max(step, 1.0)
    return Frequency(min(max_cycles_per_iteration, scaled), anchor)


def retune(params: PhaseParams, frequency: Frequency, pivot: float) -> PhaseParams:
    """params with the new frequency and anchor, and the phase offset moved so t at
    mu = pivot is unchanged (up to rounding): phi' = (phi + c (pivot - A)) - c' (pivot - A')."""
    offset = (
        params.phase_offset + params.cycles_per_iteration * (pivot - params.anchor)
    ) - frequency.cycles_per_iteration * (pivot - frequency.anchor)
    return PhaseParams(
        cycles_per_iteration=frequency.cycles_per_iteration,
        cycles_per_octave=params.cycles_per_octave,
        phase_offset=offset,
        anchor=frequency.anchor,
    )


# --- distance shading -----------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ShadeParams:
    """Distance shading (Heaton Fractal's defaults): the stroke width in pixels at 1080p,
    how dark the boundary gets, and how much dense regions are released."""

    width: float = 1.6
    strength: float = 0.85
    dense_release: float = 1.0

    def __post_init__(self) -> None:
        if not (math.isfinite(self.width) and self.width > 0):
            raise ValueError("width must be finite and positive")
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError("strength must be in [0, 1]")
        if not 0.0 <= self.dense_release <= 1.0:
            raise ValueError("dense_release must be in [0, 1]")


def _window_max(values: FloatArray, r: int) -> FloatArray:
    """Max over the (2r+1)^2 window cut off at the edges, rows then columns (exact)."""
    rows = values.copy()
    for k in range(1, r + 1):
        rows[:, k:] = np.maximum(rows[:, k:], values[:, :-k])
        rows[:, :-k] = np.maximum(rows[:, :-k], values[:, k:])
    out = rows.copy()
    for k in range(1, r + 1):
        out[k:, :] = np.maximum(out[k:, :], rows[:-k, :])
        out[:-k, :] = np.maximum(out[:-k, :], rows[k:, :])
    return out


def shade_distance(
    rgb: ByteArray, distance: FloatArray, params: ShadeParams | None = None
) -> ByteArray:
    """Darken each escaped pixel by its distance estimate (spec/fractal-color.md
    "Distance shading"): a factor f in light, applied to the encoded bytes as sqrt(f).
    Pixels whose distance is NaN (did not escape) are left as they are. Returns a new
    (height, width, 3) array."""
    if distance.ndim != 2 or rgb.shape != (*distance.shape, 3) or rgb.dtype != np.uint8:
        raise ValueError("rgb must be a (height, width, 3) uint8 array over the distances")
    params = params or ShadeParams()
    height, width = distance.shape
    w = max(params.width * color_scale(width, height), 1e-4)
    if not math.isfinite(w):
        raise ValueError("width * color_scale(width, height) must be finite")
    r = int(min(math.ceil(w) + 1, max(width, height)))
    maxde = np.maximum(_window_max(np.where(np.isnan(distance), 0.0, distance), r), 0.0)
    shaded = ~np.isnan(distance)
    shade = smoothstep(0.0, w, distance[shaded])
    opened = smoothstep(0.25 * w, w, maxde[shaded])
    s = params.strength * (1.0 + (opened - 1.0) * params.dense_release)
    g = np.sqrt(1.0 + (shade - 1.0) * s)
    out = rgb.copy()
    values = out[shaded].astype(np.float64) * g[:, None]
    out[shaded] = np.clip(np.round(values), 0.0, 255.0).astype(np.uint8)
    return out
