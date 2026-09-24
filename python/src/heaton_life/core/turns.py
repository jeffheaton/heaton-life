"""Pinned cosine and sine of a rational number of turns -- spec/turns.md.

``cis_turns(k, n)`` is (cos 2*pi*k/n, sin 2*pi*k/n) as float64 from integer arithmetic
alone: the turn k/n reduced exactly to a quarter-turn quadrant, the angle in fixed point
with F = 192 fraction bits against a pinned pi/2, a Taylor series with floor divisions,
and one correct rounding (ties to even) of each result. No libm, so every platform and
both ports give the same bits (libm cos/sin differ in the last ulp between platforms).
Quarter turns are exact: (1, 0), (0, 1), (-1, 0), (0, -1).
"""

from __future__ import annotations

import operator

FRACTION_BITS = 192
# floor(pi/2 * 2^192), pinned (spec/turns.md)
HALF_PI = 0x1921FB54442D18469898CC51701B839A252049C1114CF98E8
_ONE = 1 << FRACTION_BITS


def _cos_sin(x: int) -> tuple[int, int]:
    """cos and sin of x / 2^F for 0 <= x < pi/2 * 2^F, in the same fixed point: Taylor
    series term by term, each term floor((prev * x^2 / 2^F) / (m (m + 1))), summed with
    alternating signs until a term is 0."""
    x2 = (x * x) >> FRACTION_BITS
    s = x
    term = x
    m = 2
    sign = -1
    while True:
        term = ((term * x2) >> FRACTION_BITS) // (m * (m + 1))
        if term == 0:
            break
        s += sign * term
        sign = -sign
        m += 2
    c = _ONE
    term = _ONE
    m = 1
    sign = -1
    while True:
        term = ((term * x2) >> FRACTION_BITS) // (m * (m + 1))
        if term == 0:
            break
        c += sign * term
        sign = -sign
        m += 2
    return c, s


def cis_turns(k: int, n: int) -> tuple[float, float]:
    """(cos, sin) of 2*pi*k/n, pinned (spec/turns.md): k taken mod n, 4k = q n + r with
    0 <= r < n, phi = floor(HALF_PI * r / n) in Q192, the quadrant q applied by symmetry,
    each component rounded once to float64 (ties to even; zero is +0.0). k is any
    integer; 1 <= n <= 2^61, else ValueError."""
    k, n = operator.index(k), operator.index(n)  # NumPy integers become Python ints
    if not 1 <= n <= 1 << 61:
        raise ValueError(f"n must lie in [1, 2^61], got {n}")
    k %= n
    q, r = divmod(4 * k, n)
    c, s = _cos_sin((HALF_PI * r) // n)
    re, im = ((c, s), (-s, c), (-c, -s), (s, -c))[q]
    return re / _ONE, im / _ONE
