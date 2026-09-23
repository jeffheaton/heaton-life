"""Escape-time machinery shared by the fractal fields — spec/fractals.md.

Counts convention (spec): counts[i] = n where n is the 1-based iteration at which
|z| first exceeds the escape radius; -1 if it never does within max_iter.
Smooth value for escaped pixels: mu = n + 1 - log2(log|z| / log R).
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

from heaton_life.core import decimal_text
from heaton_life.core.pow10 import pow10
from heaton_life.core.viewport import Viewport

T0_MAX_ZOOM = 12.0  # beyond this, float64 pixel spacing collapses -> perturbation
T1_MAX_ZOOM = 290.0  # beyond this, float64 pixel *deltas* underflow -> future floatexp
BASE_SPAN = 4.0

ComplexArray = NDArray[np.complex128]
FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int32]


def tier_of(zoom_log10: float) -> str:
    """The tier a zoom selects (spec/fractals.md "Tiering"): "T0" through 1e12, "T1"
    through 1e290, "T2" beyond -- reserved for floatexp, so rendering there raises today.
    What a family can render is its own ``max_zoom_log10`` (Newton stops at T0)."""
    if zoom_log10 <= T0_MAX_ZOOM:
        return "T0"
    return "T1" if zoom_log10 <= T1_MAX_ZOOM else "T2"


def pixel_scale(size: tuple[int, int], viewport: Viewport) -> float:
    """Complex-plane distance between adjacent pixel centers (float64).

    spec/fractals.md "Pixel mapping": one float64 division, one deterministic
    power (spec/pow10.md), one float64 multiply. Never the historical
    ``10**(log10(4/width) - zoom)`` — its two libm/numpy transcendentals made
    the bit-exact tier platform-dependent at fractional zooms.
    """
    width, _ = size
    return scale_at(width, viewport.zoom_log10)


def scale_at(width: int, zoom_log10: float) -> float:
    """pixel_scale for a frame ``width`` pixels wide at ``zoom_log10`` -- the one
    expression every consumer shares, so a navigation step and a render agree."""
    return (BASE_SPAN / width) * pow10(-zoom_log10)


def pixel_offsets(size: tuple[int, int], viewport: Viewport) -> ComplexArray:
    """Per-pixel offsets from the viewport center, row-major, im decreasing downward."""
    width, height = size
    ps = pixel_scale(size, viewport)
    xs = (np.arange(width, dtype=np.float64) + 0.5 - width / 2.0) * ps
    ys = -(np.arange(height, dtype=np.float64) + 0.5 - height / 2.0) * ps
    grid: ComplexArray = (xs[None, :] + 1j * ys[:, None]).astype(np.complex128)
    return grid.ravel()


def reference_offset(viewport: Viewport) -> complex:
    """round64(center - reference), per component, exactly from the decimal strings;
    0 when the viewport has no reference (spec/deep-zoom.md "Off-center reference")."""
    if viewport.reference_re is None or viewport.reference_im is None:
        return 0j
    return complex(
        decimal_text.difference(viewport.center_re, viewport.reference_re),
        decimal_text.difference(viewport.center_im, viewport.reference_im),
    )


def pixel_deltas(size: tuple[int, int], viewport: Viewport) -> ComplexArray:
    """Each pixel's offset from the point a T1 frame iterates (``viewport.orbit_center``).

    Without a reference these are exactly ``pixel_offsets``. With one, each component is
    fl(d + offset), d = round64(center - reference): one float64 add after the exact
    difference, the operation order the C# port runs. The components are stored, not
    combined as ``xs + 1j * ys``: that is a complex multiply, whose real part is
    0 * inf = NaN when d's imaginary part overflows.
    """
    if not viewport.has_reference:
        return pixel_offsets(size, viewport)
    width, height = size
    ps = pixel_scale(size, viewport)
    d = reference_offset(viewport)
    xs = d.real + (np.arange(width, dtype=np.float64) + 0.5 - width / 2.0) * ps
    ys = d.imag + -(np.arange(height, dtype=np.float64) + 0.5 - height / 2.0) * ps
    grid: ComplexArray = np.empty((height, width), dtype=np.complex128)
    grid.real = xs[None, :]
    grid.imag = ys[:, None]
    return grid.ravel()


def reference_on_screen(size: tuple[int, int], viewport: Viewport) -> bool:
    """Whether the viewport's reference lies within its frame -- the suggested rule for
    keeping a reference while panning (True when there is none). Advisory: output is
    defined for any reference."""
    width, height = size
    ps = pixel_scale(size, viewport)
    d = reference_offset(viewport)
    return abs(d.real) <= width / 2.0 * ps and abs(d.imag) <= height / 2.0 * ps


def pixel_grid(size: tuple[int, int], viewport: Viewport) -> ComplexArray:
    """Absolute pixel coordinates in float64 (T0 only — collapses past zoom ~1e13)."""
    center = complex(
        decimal_text.to_float(viewport.center_re), decimal_text.to_float(viewport.center_im)
    )
    return pixel_offsets(size, viewport) + center


def escape_time(
    z0: ComplexArray,
    c: ComplexArray,
    update: Callable[[ComplexArray, ComplexArray], ComplexArray],
    max_iter: int,
    escape_radius: float,
) -> tuple[IntArray, ComplexArray]:
    """Vectorized escape iteration with active-set compaction.

    Returns (counts, final_z); final_z is meaningful only where counts > 0.
    """
    n = z0.size
    counts = np.full(n, -1, dtype=np.int32)
    final = np.zeros(n, dtype=np.complex128)
    z = z0.copy()
    cc = c.copy()
    idx = np.arange(n)
    r2 = escape_radius * escape_radius
    for it in range(1, max_iter + 1):
        z = update(z, cc)
        escaped = (z.real * z.real + z.imag * z.imag) > r2
        if escaped.any():
            hits = idx[escaped]
            counts[hits] = it
            final[hits] = z[escaped]
            keep = ~escaped
            z, cc, idx = z[keep], cc[keep], idx[keep]
            if idx.size == 0:
                break
    return counts, final


def smooth_iterations(counts: IntArray, final: ComplexArray, escape_radius: float) -> FloatArray:
    """mu = n + 1 - log2(log|z| / log R) for escaped pixels; 0 for interior."""
    mu = np.zeros(counts.shape, dtype=np.float64)
    escaped = counts > 0
    if escaped.any():
        abs_z = np.abs(final[escaped])
        mu[escaped] = counts[escaped] + 1.0 - np.log2(np.log(abs_z) / np.log(escape_radius))
    return mu


def normalize_render(mu: FloatArray) -> FloatArray:
    """Map smooth iterations to [0,1] for colormapping; interior stays 0 (black).

    Per-frame percentile contrast stretch: deep zooms cluster all escape counts in
    a narrow band near max_iter, so an absolute mu/max_iter mapping goes monochrome.
    Stretching between the frame's 1st and 99th escaped percentiles keeps the full
    palette in play at any depth (presentation only — counts are the conformance
    output and are untouched).
    """
    values = np.zeros(mu.shape, dtype=np.float64)
    escaped = mu > 0
    if escaped.any():
        lo, hi = np.percentile(mu[escaped], [1.0, 99.0])
        if hi <= lo:
            values[escaped] = 0.6  # featureless frame: one mid tone
        else:
            # floor keeps escaped pixels distinguishable from the black interior
            values[escaped] = np.clip((mu[escaped] - lo) / (hi - lo), 0.02, 1.0)
    result: FloatArray = np.sqrt(values)
    return result
