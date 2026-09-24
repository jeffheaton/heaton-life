"""Escape-time machinery shared by the fractal fields — spec/fractals.md.

Counts convention (spec): counts[i] = n where n is the 1-based iteration at which
|z| first exceeds the escape radius; -1 if it never does within max_iter.
Smooth value for escaped pixels: mu = n + 1 - log2(log|z| / log R).
"""

from __future__ import annotations

import math
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


# Per-pixel status (spec/fractals.md "Status"): how a pixel's count was decided.
ESCAPED = 0  # count > 0
EXHAUSTED = 1  # max_iter reached with nothing proved: more iterations might escape
CARDIOID_OR_BULB = 2  # Mandelbrot T0: inside the main cardioid or period-2 bulb
CYCLE = 3  # T0: the float64 state repeated exactly, so it never escapes

StatusArray = NDArray[np.int8]


def escape_time(
    z0: ComplexArray,
    c: ComplexArray,
    update: Callable[[ComplexArray, ComplexArray], ComplexArray],
    max_iter: int,
    escape_radius: float,
) -> tuple[IntArray, ComplexArray, StatusArray]:
    """Vectorized escape iteration with active-set compaction and exact cycle detection.

    Returns (counts, final_z, status); final_z is meaningful only where counts > 0.
    Cycle detection (spec/fractals.md "Interior shortcuts"): after the escape test at
    iteration n fails, a pixel whose z_n equals (IEEE ==, both parts) the state saved
    at the last power-of-two iteration is interior -- the iteration is deterministic,
    so a repeated state repeats forever and never escapes. Then z_n is saved when n is
    a power of two (Brent's schedule). Counts are unchanged: -1 either way.
    """
    counts, final, status, _ = _escape_loop(z0, c, update, max_iter, escape_radius, None)
    return counts, final, status


Derivative = tuple[FloatArray, FloatArray]


def escape_time_distance(
    z0: ComplexArray,
    c: ComplexArray,
    max_iter: int,
    escape_radius: float,
    d0: tuple[float, float],
    add: float | None,
) -> tuple[IntArray, ComplexArray, StatusArray, Derivative]:
    """escape_time for z^2 + c that also carries the derivative a distance estimate
    needs (spec/fractals.md "Distance estimate"): d starts at ``d0`` and each iteration,
    before z is updated, becomes (2(zr dr - zi di) + add, 2(zr di + zi dr)) from the
    pre-square z -- real arrays, so nothing is fma-contracted. ``add`` is the pixel
    scale for Mandelbrot and None for Julia (no addition at all). Counts, final z and
    statuses are exactly escape_time's; the derivative at escape comes back as
    (final_dr, final_di), meaningful where counts > 0."""
    counts, final, status, derivative = _escape_loop(
        z0, c, _z2_update, max_iter, escape_radius, (d0, add)
    )
    assert derivative is not None
    return counts, final, status, derivative


def _z2_update(z: ComplexArray, c: ComplexArray) -> ComplexArray:
    result: ComplexArray = z * z + c
    return result


def _escape_loop(
    z0: ComplexArray,
    c: ComplexArray,
    update: Callable[[ComplexArray, ComplexArray], ComplexArray],
    max_iter: int,
    escape_radius: float,
    derivative: tuple[tuple[float, float], float | None] | None,
) -> tuple[IntArray, ComplexArray, StatusArray, Derivative | None]:
    n = z0.size
    counts = np.full(n, -1, dtype=np.int32)
    final = np.zeros(n, dtype=np.complex128)
    status = np.full(n, EXHAUSTED, dtype=np.int8)
    z = z0.copy()
    cc = c.copy()
    idx = np.arange(n)
    saved: ComplexArray | None = None
    r2 = escape_radius * escape_radius
    dr: FloatArray | None = None
    di: FloatArray | None = None
    final_dr = final_di = np.zeros(0)
    add: float | None = None
    if derivative is not None:
        (d0r, d0i), add = derivative
        dr = np.full(n, d0r, dtype=np.float64)
        di = np.full(n, d0i, dtype=np.float64)
        final_dr = np.zeros(n, dtype=np.float64)
        final_di = np.zeros(n, dtype=np.float64)
    for it in range(1, max_iter + 1):
        if dr is not None and di is not None:
            zr = z.real
            zi = z.imag
            tr = 2.0 * (zr * dr - zi * di)
            if add is not None:
                tr = tr + add
            ti = 2.0 * (zr * di + zi * dr)
            dr, di = tr, ti
        z = update(z, cc)
        escaped = (z.real * z.real + z.imag * z.imag) > r2
        cycled = (z == saved) & ~escaped if saved is not None else None
        done = escaped if cycled is None else escaped | cycled
        if done.any():
            hits = idx[escaped]
            counts[hits] = it
            final[hits] = z[escaped]
            status[hits] = ESCAPED
            if cycled is not None:
                status[idx[cycled]] = CYCLE
            keep = ~done
            z, cc, idx = z[keep], cc[keep], idx[keep]
            if saved is not None:
                saved = saved[keep]
            if dr is not None and di is not None:
                final_dr[hits] = dr[escaped]
                final_di[hits] = di[escaped]
                dr, di = dr[keep], di[keep]
            if idx.size == 0:
                break
        if (it & (it - 1)) == 0:  # a power of two (C-family ports: == binds tighter than &)
            saved = z.copy()
    return counts, final, status, (final_dr, final_di) if derivative is not None else None


# Exact powers of two for the distance estimate's magnitude scaling (spec/fractals.md).
_TWO_400, _TWO_M400 = math.ldexp(1.0, 400), math.ldexp(1.0, -400)
_TWO_600, _TWO_M600 = math.ldexp(1.0, 600), math.ldexp(1.0, -600)


def distance_estimate(
    counts: IntArray, final: ComplexArray, final_dr: FloatArray, final_di: FloatArray
) -> FloatArray:
    """DE in pixels from the escaping z and derivative (spec/fractals.md "Distance
    estimate"): ((sqrt(m2) * (0.5 log m2)) / |d|) with |d| exponent-scaled by an exact
    power of two so its squares never go subnormal; +inf where d is exactly 0 (a
    critical point), 0 where d is not finite (overflowed: on the boundary), NaN where
    the pixel did not escape."""
    de = np.full(counts.shape, np.nan, dtype=np.float64)
    escaped = counts > 0
    if not escaped.any():
        return de
    zr = final.real[escaped]
    zi = final.imag[escaped]
    dr = final_dr[escaped]
    di = final_di[escaped]
    m2 = zr * zr + zi * zi
    a = np.maximum(np.abs(dr), np.abs(di))  # NaN if either part is NaN
    finite = np.isfinite(a)
    s = np.where(a < _TWO_M400, _TWO_600, np.where(a > _TWO_400, _TWO_M600, 1.0))
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        sr = dr * s
        si = di * s
        value = ((np.sqrt(m2) * (0.5 * np.log(m2))) / np.sqrt(sr * sr + si * si)) * s
    de[escaped] = np.where(a == 0.0, np.inf, np.where(finite, value, 0.0))
    return de


def cardioid_or_bulb(c: ComplexArray) -> NDArray[np.bool_]:
    """Pixels inside Mandelbrot's main cardioid or period-2 bulb by more than 1e-12 in
    the test's own measure -- interior, provably, so a T0 render with an escape radius
    of at least 2 need not iterate them (their orbits stay within |z| < 2; a smaller
    radius can be crossed, near 1.27 in the bulb). Plain float64, this operation order
    (spec/fractals.md "Interior shortcuts")."""
    x = c.real
    y = c.imag
    xq = x - 0.25
    q = xq * xq + y * y
    cardioid = q * (q + xq) < 0.25 * (y * y) - 1e-12
    bulb = (x + 1.0) * (x + 1.0) + y * y < 0.0625 - 1e-12
    inside: NDArray[np.bool_] = cardioid | bulb
    return inside


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
    output and are untouched). Exactly apply_stretch(mu, measure_stretch(mu))
    (spec/fractal-color.md "Stretch"); all zeros when nothing escaped.
    """
    from heaton_life.fractal.coloring import apply_stretch, measure_stretch

    stretch = measure_stretch(mu)
    if stretch is None:
        return np.zeros(mu.shape, dtype=np.float64)
    return apply_stretch(mu, stretch)
