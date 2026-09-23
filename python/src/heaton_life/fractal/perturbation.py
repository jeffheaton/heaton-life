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
    for it in range(1, max_iter + 1):
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
                dz[keep], dc[keep], m[keep], last[keep], idx[keep], z[keep], zabs2[keep]
            )
            if idx.size == 0:
                break
        rebase = zabs2 < (dz.real * dz.real + dz.imag * dz.imag)
        if rebase.any():
            dz[rebase] = z[rebase]
            m[rebase] = rebase_start
            last[rebase] = rebase_last
    return counts, final


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
                dx[keep], dy[keep], dcx[keep], dcy[keep], m[keep],
                idx[keep], zx[keep], zy[keep], zabs2[keep],
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
