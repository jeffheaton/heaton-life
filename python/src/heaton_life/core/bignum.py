"""High-precision reference orbits for deep zoom (spec/deep-zoom.md).

The only bignum computation in the whole fractal pipeline: one orbit of the
viewport center, computed with gmpy2 (GMP) when installed, mpmath otherwise.
Both paths use real-pair arithmetic with round-to-nearest at the same precision,
so they produce identical float64 orbit samples (tested).

Orbit samples are O(1) magnitude until escape, so they are stored as complex128.
"""

from __future__ import annotations

import functools
from typing import Any

import numpy as np
from numpy.typing import NDArray

GUARD_BITS = 64
_ESCAPE_ABS2 = 1e100  # stop the reference once it is unambiguously escaping


def precision_bits(zoom_log10: float) -> int:
    """Mantissa bits needed for a center at 10^zoom magnification, plus guard."""
    return int(3.33 * max(zoom_log10, 0.0)) + GUARD_BITS


@functools.lru_cache(maxsize=8)
def reference_orbit(
    kind: str,
    center_re: str,
    center_im: str,
    zoom_log10: float,
    max_iter: int,
    c_re: float = 0.0,
    c_im: float = 0.0,
) -> NDArray[np.complex128]:
    """Z_0..Z_K as complex128; K = max_iter unless the reference escapes early.

    kinds: "mandelbrot" (Z0=0, Z^2+C), "julia" (Z0=center, Z^2+c),
    "burning_ship" (Z0=0, (|X|+i|Y|)^2+C).
    """
    if kind not in ("mandelbrot", "julia", "burning_ship"):
        raise ValueError(f"unknown reference orbit kind: {kind!r}")
    bits = precision_bits(zoom_log10)
    try:
        return _orbit_gmpy2(kind, center_re, center_im, bits, max_iter, c_re, c_im)
    except ImportError:
        return _orbit_mpmath(kind, center_re, center_im, bits, max_iter, c_re, c_im)


def _iterate(
    kind: str,
    zr: Any,
    zi: Any,
    cr: Any,
    ci: Any,
    max_iter: int,
    abs_fn: Any,
) -> list[complex]:
    """Backend-agnostic orbit loop; zr/zi/cr/ci are bignum reals of one backend."""
    orbit = [complex(float(zr), float(zi))]
    for _ in range(max_iter):
        if kind == "burning_ship":
            zr, zi = zr * zr - zi * zi + cr, 2 * abs_fn(zr) * abs_fn(zi) + ci
        else:
            zr, zi = zr * zr - zi * zi + cr, 2 * zr * zi + ci
        sample = complex(float(zr), float(zi))
        orbit.append(sample)
        if sample.real * sample.real + sample.imag * sample.imag > _ESCAPE_ABS2:
            break
    return orbit


def _orbit_gmpy2(
    kind: str, center_re: str, center_im: str, bits: int, max_iter: int, c_re: float, c_im: float
) -> NDArray[np.complex128]:
    import gmpy2

    with gmpy2.context(precision=bits):
        center_r = gmpy2.mpfr(center_re)
        center_i = gmpy2.mpfr(center_im)
        if kind == "julia":
            zr, zi = center_r, center_i
            cr, ci = gmpy2.mpfr(c_re), gmpy2.mpfr(c_im)
        else:
            zr, zi = gmpy2.mpfr(0), gmpy2.mpfr(0)
            cr, ci = center_r, center_i
        orbit = _iterate(kind, zr, zi, cr, ci, max_iter, abs)
    return np.array(orbit, dtype=np.complex128)


def _orbit_mpmath(
    kind: str, center_re: str, center_im: str, bits: int, max_iter: int, c_re: float, c_im: float
) -> NDArray[np.complex128]:
    from mpmath import mp, mpf

    old_prec = mp.prec
    try:
        mp.prec = bits
        center_r = mpf(center_re)
        center_i = mpf(center_im)
        if kind == "julia":
            zr, zi = center_r, center_i
            cr, ci = mpf(c_re), mpf(c_im)
        else:
            zr, zi = mpf(0), mpf(0)
            cr, ci = center_r, center_i
        orbit = _iterate(kind, zr, zi, cr, ci, max_iter, abs)
    finally:
        mp.prec = old_prec
    return np.array(orbit, dtype=np.complex128)
