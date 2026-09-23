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

import collections
import dataclasses
import math
import threading
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


# The orbit depends on (kind, center, F, c) and on max_iter only through where it stops,
# so the cache keys on the first four (spec/deep-zoom.md "Caching & interactivity"). A
# cached orbit answers a shorter request with a prefix and a longer one by resuming from
# the exact fixed-point state it kept -- both identical to computing afresh, since the
# recurrence is deterministic and max_iter only says when to stop. Least recently used
# first out, under an entry cap and a byte cap, as in the C# port -- always keeping the
# two most recent, since a Julia frame uses two orbits (its center's and the critical one).
CACHE_ENTRIES = 8
CACHE_BYTES = 64 << 20
_KEEP_RECENT = 2


@dataclasses.dataclass(frozen=True)
class _Entry:
    orbit: NDArray[np.complex128]  # read-only
    escaped: bool  # the last sample tripped the stopping rule
    zr: int  # the fixed-point Z at the last sample, and C, to resume from
    zi: int
    cr: int
    ci: int

    def covers(self, max_iter: int) -> bool:
        return self.escaped or len(self.orbit) - 1 >= max_iter

    def prefix(self, max_iter: int) -> NDArray[np.complex128]:
        return self.orbit[: min(len(self.orbit), max_iter + 1)]


_CACHE: collections.OrderedDict[tuple[object, ...], _Entry] = collections.OrderedDict()
_CACHE_LOCK = threading.Lock()


def clear_cache() -> None:
    """Drop every cached orbit."""
    with _CACHE_LOCK:
        _CACHE.clear()


def reference_orbit(
    kind: str,
    center_re: str,
    center_im: str,
    zoom_log10: float,
    max_iter: int,
    c_re: float = 0.0,
    c_im: float = 0.0,
) -> NDArray[np.complex128]:
    """Z_0..Z_K as read-only complex128; K = max_iter unless the reference escapes early.

    kinds: "mandelbrot" (Z0=0, Z^2+C), "julia" (Z0=center, Z^2+c),
    "burning_ship" (Z0=0, (|X|+i|Y|)^2+C).
    """
    if kind not in ("mandelbrot", "julia", "burning_ship"):
        raise ValueError(f"unknown reference orbit kind: {kind!r}")
    if max_iter < 1:
        raise ValueError("max_iter must be positive")
    bits = working_bits(center_re, center_im, zoom_log10)
    key = (kind, center_re, center_im, bits, c_re, c_im)
    with _CACHE_LOCK:
        start = _CACHE.get(key)
        if start is not None:
            _CACHE.move_to_end(key)
            if start.covers(max_iter):
                return start.prefix(max_iter)

    integer = _integer_type()
    if start is None:
        computed = _fresh(kind, center_re, center_im, bits, max_iter, c_re, c_im, integer)
    else:
        computed = _resume(kind, start, bits, max_iter, integer)

    with _CACHE_LOCK:
        existing = _CACHE.get(key)
        if existing is None or len(existing.orbit) < len(computed.orbit):
            _CACHE[key] = computed  # else another thread stored a longer one
        _CACHE.move_to_end(key)
        total = sum(entry.orbit.nbytes for entry in _CACHE.values())
        while len(_CACHE) > _KEEP_RECENT and (len(_CACHE) > CACHE_ENTRIES or total > CACHE_BYTES):
            _, oldest = _CACHE.popitem(last=False)
            total -= oldest.orbit.nbytes
    return computed.prefix(max_iter)


def _integer_type() -> Callable[[int], Any]:
    try:
        import gmpy2

        mpz: Callable[[int], Any] = gmpy2.mpz
        return mpz
    except ImportError:
        return int


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
    """One orbit computed afresh, bypassing the cache (tests compare integer types)."""
    return _fresh(kind, center_re, center_im, bits, max_iter, c_re, c_im, integer).orbit


def _fresh(
    kind: str,
    center_re: str,
    center_im: str,
    bits: int,
    max_iter: int,
    c_re: float,
    c_im: float,
    integer: Callable[[int], Any],
) -> _Entry:
    center_r = parse_fixed(center_re, bits)
    center_i = parse_fixed(center_im, bits)
    if kind == "julia":
        zr, zi = center_r, center_i
        cr, ci = from_double(c_re, bits), from_double(c_im, bits)
    else:
        zr, zi = 0, 0
        cr, ci = center_r, center_i
    # orbit[0] is Z0 itself, never escape-tested.
    first = complex(_to_double(zr, 1 << bits), _to_double(zi, 1 << bits))
    return _run(kind, bits, zr, zi, cr, ci, [first], max_iter, integer)


def _resume(
    kind: str, start: _Entry, bits: int, max_iter: int, integer: Callable[[int], Any]
) -> _Entry:
    steps = max_iter - (len(start.orbit) - 1)
    tail = _run(kind, bits, start.zr, start.zi, start.cr, start.ci, [], steps, integer)
    orbit = np.concatenate([start.orbit, tail.orbit])
    orbit.setflags(write=False)
    return dataclasses.replace(tail, orbit=orbit)


def _run(
    kind: str,
    bits: int,
    zr0: int,
    zi0: int,
    cr0: int,
    ci0: int,
    samples: list[complex],
    steps: int,
    integer: Callable[[int], Any],
) -> _Entry:
    """Up to ``steps`` steps from Z = (zr0, zi0), appending each rounded sample and stopping
    after the first that trips the stopping rule -- ReferenceOrbit.Run in C#, operation for
    operation. ``integer`` wraps the values (int, or gmpy2.mpz for speed); every operation
    after that is exact integer arithmetic plus explicit rounding."""
    zr, zi, cr, ci = integer(zr0), integer(zi0), integer(cr0), integer(ci0)
    half = integer(1 << (bits - 1))
    scale = 1 << bits

    def mul(a: Any, b: Any) -> Any:
        # round(a * b / 2^bits), ties away from zero: truncation would bias every
        # multiply toward zero and drift the orbit over thousands of iterations.
        product = a * b
        if product >= 0:
            return (product + half) >> bits
        return -((-product + half) >> bits)

    escaped = False
    for _ in range(steps):
        next_r = mul(zr, zr) - mul(zi, zi) + cr
        if kind == "burning_ship":
            next_i = 2 * mul(abs(zr), abs(zi)) + ci
        else:
            next_i = 2 * mul(zr, zi) + ci
        zr, zi = next_r, next_i
        sr, si = _to_double(zr, scale), _to_double(zi, scale)
        samples.append(complex(sr, si))
        # The escape test runs on the ROUNDED sample.
        if sr * sr + si * si > _ESCAPE_ABS2:
            escaped = True
            break
    orbit = np.array(samples, dtype=np.complex128)
    orbit.setflags(write=False)
    return _Entry(orbit, escaped, int(zr), int(zi), int(cr), int(ci))


def _to_double(value: Any, scale: int) -> float:
    """Fixed point (``scale`` = 2^F) to the nearest float64: one correct rounding, ties to even.

    Python's int true division rounds correctly, subnormals included -- the one
    rounding the spec asks for. Via int, because mpz / int would return an mpfr. Past
    the float64 range IEEE rounding gives an infinity, as the C# port does; CPython
    raises instead, so map it.
    """
    exact = int(value)
    try:
        return exact / scale
    except OverflowError:
        return math.inf if exact > 0 else -math.inf


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
