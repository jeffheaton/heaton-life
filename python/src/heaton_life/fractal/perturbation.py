"""Perturbation + rebasing deep-zoom engine (spec/deep-zoom.md).

One high-precision reference orbit (core.bignum); every pixel iterates its small
deviation delta in plain float64. Rebasing (Zhuoran 2021): whenever the full value
|Z[m] + delta| drops below |delta|, restart against the beginning of an orbit whose
first sample is 0 (delta <- Z[m] + delta, m <- 0). For Mandelbrot and Burning Ship
that is the reference itself (Z0 = 0); a Julia reference starts at the viewport
center, so Julia rebases onto the critical orbit (W0 = 0, same c) instead. One
reference serves the whole frame; no glitch detection passes. The reference index
is clamped to the last sample of whichever orbit the pixel follows, which is only
reachable when that orbit escaped — those pixels escape immediately.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

ComplexArray = NDArray[np.complex128]
FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int32]


def perturb_z2(
    orbit: ComplexArray,
    delta0: ComplexArray,
    delta_c: ComplexArray,
    max_iter: int,
    escape_radius: float,
    rebase_orbit: ComplexArray | None = None,
) -> tuple[IntArray, ComplexArray]:
    """Perturbation for z^2 + c maps (Mandelbrot: delta0=0; Julia: delta_c=0).

    ``rebase_orbit`` is the orbit a rebased pixel restarts on; it must begin at 0.
    None means the reference itself (Mandelbrot, whose reference starts at 0).
    Julia passes its critical orbit. Same (counts, final_z) contract as
    engine.escape_time.
    """
    counts, final, _ = _perturb_z2(
        orbit, delta0, delta_c, max_iter, escape_radius, rebase_orbit, None
    )
    return counts, final


def perturb_z2_distance(
    orbit: ComplexArray,
    delta0: ComplexArray,
    delta_c: ComplexArray,
    max_iter: int,
    escape_radius: float,
    d0: tuple[float, float],
    add: float | None,
    rebase_orbit: ComplexArray | None = None,
) -> tuple[IntArray, ComplexArray, tuple[FloatArray, FloatArray]]:
    """perturb_z2 that also carries the derivative of the full z for a distance
    estimate (spec/fractals.md "Distance estimate"): updated from the z the previous
    iteration reconstructed -- fl(Z_0 + delta0) before the first -- and left alone by a
    rebase, which changes delta, m and the orbit but not z. ``d0`` and ``add`` as in
    engine.escape_time_distance. Counts and final z are exactly perturb_z2's."""
    counts, final, derivative = _perturb_z2(
        orbit, delta0, delta_c, max_iter, escape_radius, rebase_orbit, (d0, add)
    )
    assert derivative is not None
    return counts, final, derivative


def _perturb_z2(
    orbit: ComplexArray,
    delta0: ComplexArray,
    delta_c: ComplexArray,
    max_iter: int,
    escape_radius: float,
    rebase_orbit: ComplexArray | None,
    derivative: tuple[tuple[float, float], float | None] | None,
) -> tuple[IntArray, ComplexArray, tuple[FloatArray, FloatArray] | None]:
    # Both orbits live in one array so a pixel's reference sample stays a single
    # fancy-indexed gather: m is an absolute index, `last` the end of the orbit
    # that pixel currently follows. With no separate rebase orbit the values are
    # exactly the historical single-orbit loop's.
    if rebase_orbit is None:
        refs = orbit
        rebase_start = 0
    else:
        refs = np.concatenate([orbit, rebase_orbit])
        rebase_start = len(orbit)
    rebase_last = len(refs) - 1
    n = delta0.size
    counts = np.full(n, -1, dtype=np.int32)
    final = np.zeros(n, dtype=np.complex128)
    dz = delta0.copy()
    dc = delta_c.copy()
    m = np.zeros(n, dtype=np.int64)
    last = np.full(n, len(orbit) - 1, dtype=np.int64)
    idx = np.arange(n)
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
        z = refs[m] + dz  # the pre-square z of iteration 1: fl(Z_0 + delta0)
    for it in range(1, max_iter + 1):
        if dr is not None and di is not None:
            zr = z.real
            zi = z.imag
            tr = 2.0 * (zr * dr - zi * di)
            if add is not None:
                tr = tr + add
            ti = 2.0 * (zr * di + zi * dr)
            dr, di = tr, ti
        dz = (2.0 * refs[m] + dz) * dz + dc
        m = np.minimum(m + 1, last)
        z = refs[m] + dz
        zabs2 = z.real * z.real + z.imag * z.imag
        escaped = zabs2 > r2
        if escaped.any():
            hits = idx[escaped]
            counts[hits] = it
            final[hits] = z[escaped]
            keep = ~escaped
            dz, dc, m, last, idx, z, zabs2 = (
                dz[keep],
                dc[keep],
                m[keep],
                last[keep],
                idx[keep],
                z[keep],
                zabs2[keep],
            )
            if dr is not None and di is not None:
                final_dr[hits] = dr[escaped]
                final_di[hits] = di[escaped]
                dr, di = dr[keep], di[keep]
            if idx.size == 0:
                break
        rebase = zabs2 < (dz.real * dz.real + dz.imag * dz.imag)
        if rebase.any():
            # z, and so the derivative, are unchanged: only delta, m and the orbit move
            dz[rebase] = z[rebase]
            m[rebase] = rebase_start
            last[rebase] = rebase_last
    return counts, final, (final_dr, final_di) if derivative is not None else None


def perturb_burning_ship(
    orbit: ComplexArray,
    delta_c: ComplexArray,
    max_iter: int,
    escape_radius: float,
) -> tuple[IntArray, ComplexArray]:
    """Component-form perturbation for the Burning Ship, using stable diffabs."""
    ref_x = orbit.real.copy()
    ref_y = orbit.imag.copy()
    n = delta_c.size
    counts = np.full(n, -1, dtype=np.int32)
    final = np.zeros(n, dtype=np.complex128)
    dx = np.zeros(n, dtype=np.float64)
    dy = np.zeros(n, dtype=np.float64)
    dcx = delta_c.real.copy()
    dcy = delta_c.imag.copy()
    m = np.zeros(n, dtype=np.int64)
    idx = np.arange(n)
    last = len(orbit) - 1
    r2 = escape_radius * escape_radius
    for it in range(1, max_iter + 1):
        x_ref = ref_x[m]
        y_ref = ref_y[m]
        a = _diffabs(x_ref, dx)
        b = _diffabs(y_ref, dy)
        new_dx = (2.0 * x_ref + dx) * dx - (2.0 * y_ref + dy) * dy + dcx
        new_dy = 2.0 * (np.abs(x_ref) * b + np.abs(y_ref) * a + a * b) + dcy
        dx, dy = new_dx, new_dy
        m = np.minimum(m + 1, last)
        zx = ref_x[m] + dx
        zy = ref_y[m] + dy
        zabs2 = zx * zx + zy * zy
        escaped = zabs2 > r2
        if escaped.any():
            hits = idx[escaped]
            counts[hits] = it
            final[hits] = zx[escaped] + 1j * zy[escaped]
            keep = ~escaped
            dx, dy, dcx, dcy, m, idx, zx, zy, zabs2 = (
                dx[keep],
                dy[keep],
                dcx[keep],
                dcy[keep],
                m[keep],
                idx[keep],
                zx[keep],
                zy[keep],
                zabs2[keep],
            )
            if idx.size == 0:
                break
        rebase = zabs2 < (dx * dx + dy * dy)
        if rebase.any():
            dx[rebase] = zx[rebase]
            dy[rebase] = zy[rebase]
            m[rebase] = 0
    return counts, final


def _diffabs(ref: FloatArray, delta: FloatArray) -> FloatArray:
    """|ref + delta| - |ref|, computed without cancellation (case analysis)."""
    total = ref + delta
    result: FloatArray = np.where(
        ref >= 0.0,
        np.where(total >= 0.0, delta, -(2.0 * ref + delta)),
        np.where(total <= 0.0, -delta, 2.0 * ref + delta),
    )
    return result
