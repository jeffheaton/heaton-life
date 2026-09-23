"""High-precision reference orbits for deep zoom (spec/deep-zoom.md).

The only bignum computation in the whole fractal pipeline: one orbit of the
viewport center, in binary FIXED point on integers. That arithmetic is normative
(spec/deep-zoom.md "Reference orbit"): the C# port (HeatonLife.ReferenceOrbit)
runs the same integer operations, so the two produce the same orbit bit for bit
at any length. gmpy2's mpz speeds the integers up when installed; integer
arithmetic is exact, so the orbit is identical either way.

A real x is held as the integer round(x * 2^F) for F fractional bits. Every
rounding is spelled out below because the orbit is a cross-language contract:
decimal parsing and products round to nearest with ties away from zero, and each
sample becomes float64 by one correct rounding (ties to even, subnormals
included).
"""

from __future__ import annotations

import functools
import math
from collections.abc import Callable
from typing import Any

import numpy as np
from numpy.typing import NDArray

from heaton_life.core import decimal_text

GUARD_BITS = 64  # zoom-precision guard: precision_bits() = trunc(3.33 * zoom) + this
WORKING_GUARD_BITS = 64  # fixed-point headroom beyond the precision rule
# Center digits past 10^-340 sit below half the smallest float64 subnormal: they cannot
# reach a sample, so the digit term stops there and a long string cannot set F alone.
MAX_DIGIT_PLACES = 340
_ESCAPE_ABS2 = 1e100  # stop the reference once it is unambiguously escaping


def precision_bits(zoom_log10: float) -> int:
    """Bits needed to resolve a frame at 10^zoom magnification, plus guard.

    Truncating, not ceiling: the shipped vectors were produced this way.
    """
    return int(3.33 * max(zoom_log10, 0.0)) + GUARD_BITS


def decimal_places(text: str) -> int:
    """Fraction digits needed to write a decimal string exactly (0 for an integer)."""
    _, _, net_exponent = decimal_text.scan(text)
    return max(-net_exponent, 0)


def working_bits(center_re: str, center_im: str, zoom_log10: float) -> int:
    """Fractional bits F of the fixed-point orbit (spec/deep-zoom.md "Precision").

    The frame's need (precision_bits) or the center's own digits (at most
    MAX_DIGIT_PLACES of them), whichever is finer, plus WORKING_GUARD_BITS. The digit
    term keeps a long or tiny center intact: a component of 1e-310 at zoom 280 would
    otherwise keep ~30 bits.
    """
    places = min(max(decimal_places(center_re), decimal_places(center_im)), MAX_DIGIT_PLACES)
    power: int = 10**places
    digit_bits = power.bit_length()
    return max(precision_bits(zoom_log10), digit_bits) + WORKING_GUARD_BITS


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
    if max_iter < 1:
        raise ValueError("max_iter must be positive")
    bits = working_bits(center_re, center_im, zoom_log10)
    try:
        import gmpy2

        integer: Callable[[int], Any] = gmpy2.mpz
    except ImportError:
        integer = int
    return _orbit_fixed(kind, center_re, center_im, bits, max_iter, c_re, c_im, integer)


def _orbit_fixed(
    kind: str,
    center_re: str,
    center_im: str,
    bits: int,
    max_iter: int,
    c_re: float,
    c_im: float,
    integer: Callable[[int], Any] = int,
) -> NDArray[np.complex128]:
    """The orbit loop, operation for operation as ReferenceOrbit.Iterate in C#.

    ``integer`` wraps the starting values (int, or gmpy2.mpz for speed); every
    operation after that is exact integer arithmetic plus explicit rounding.
    """
    center_r = integer(parse_fixed(center_re, bits))
    center_i = integer(parse_fixed(center_im, bits))
    if kind == "julia":
        zr, zi = center_r, center_i
        cr, ci = integer(from_double(c_re, bits)), integer(from_double(c_im, bits))
    else:
        zr, zi = integer(0), integer(0)
        cr, ci = center_r, center_i

    half = integer(1 << (bits - 1))
    scale = 1 << bits

    def mul(a: Any, b: Any) -> Any:
        # round(a * b / 2^bits), ties away from zero: truncation would bias every
        # multiply toward zero and drift the orbit over thousands of iterations.
        product = a * b
        if product >= 0:
            return (product + half) >> bits
        return -((-product + half) >> bits)

    def to_double(value: Any) -> float:
        # Python's int true division rounds correctly (ties to even), subnormals
        # included -- the one rounding the spec asks for. Via int, because
        # mpz / int would return an mpfr. Past the float64 range IEEE rounding gives
        # an infinity, as the C# port does; CPython raises instead, so map it.
        exact = int(value)
        try:
            return exact / scale
        except OverflowError:
            return math.inf if exact > 0 else -math.inf

    orbit = [complex(to_double(zr), to_double(zi))]
    for _ in range(max_iter):
        next_r = mul(zr, zr) - mul(zi, zi) + cr
        if kind == "burning_ship":
            next_i = 2 * mul(abs(zr), abs(zi)) + ci
        else:
            next_i = 2 * mul(zr, zi) + ci
        zr, zi = next_r, next_i
        sr, si = to_double(zr), to_double(zi)
        orbit.append(complex(sr, si))
        # The escape test runs on the ROUNDED sample.
        if sr * sr + si * si > _ESCAPE_ABS2:
            break
    return np.array(orbit, dtype=np.complex128)


def parse_fixed(text: str, bits: int) -> int:
    """A decimal string (core.decimal_text grammar) as round(value * 2^bits), ties
    away from zero, never via float."""
    negative, digits, net_exponent = decimal_text.scan(text)
    scaled = digits << bits
    result: int
    if net_exponent >= 0:
        result = scaled * 10**net_exponent
    else:
        result = _round_div(scaled, 10**-net_exponent)
    return -result if negative else result


def from_double(value: float, bits: int) -> int:
    """A float64 as round(value * 2^bits), ties away from zero. Exact when it fits."""
    if not math.isfinite(value):
        raise ValueError("center components must be finite")
    numerator, denominator = value.as_integer_ratio()  # denominator is a power of 2
    magnitude = _round_div(abs(numerator) << bits, denominator)
    return -magnitude if numerator < 0 else magnitude


def _round_div(numerator: int, denominator: int) -> int:
    """Round-to-nearest quotient of non-negative ints, ties away from zero."""
    quotient, remainder = divmod(numerator, denominator)
    if 2 * remainder >= denominator:
        quotient += 1
    return quotient
