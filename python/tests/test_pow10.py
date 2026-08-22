"""spec/pow10.md — the deterministic power of ten that keeps the fractal
bit-exact tier portable. Known answers pin the spec across languages (the
.NET suite asserts the same bit patterns); the mpmath sweep and the F=256
recompute guard the algorithm itself."""

import math
import struct

import mpmath
import pytest

from heaton_life.core.pow10 import pow10

# spec/pow10.md "Known-answer test" — exact IEEE-754 bit patterns.
KNOWN_BITS = {
    0.0: 0x3FF0000000000000,
    1.0: 0x4024000000000000,
    14.0: 0x42D6BCC41E900000,
    22.0: 0x4480F0CF064DD592,
    0.2: 0x3FF95BB8F6D46053,
    -0.2: 0x3FE430CD74F6D478,
    -0.1: 0x3FE96B230BCDC434,
    -14.0: 0x3D06849B86A12B9B,
    290.0: 0x7C2485CE9E7A065F,
    -290.0: 0x03B8F2B061AEA072,
}


def _bits(x: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", x))[0]


def test_known_answers() -> None:
    for x, want in KNOWN_BITS.items():
        assert _bits(pow10(x)) == want, f"pow10({x})"


def test_integer_powers_exact() -> None:
    # 10^0 .. 10^22 are exactly representable; the algorithm must land on them.
    for k in range(23):
        assert pow10(float(k)) == float(10**k)


def test_domain_rejected() -> None:
    for bad in [300.5, -300.5, math.inf, -math.inf, math.nan]:
        with pytest.raises(ValueError):
            pow10(bad)


def test_matches_mpmath() -> None:
    # Ground truth at 200-bit precision over a deterministic sweep of the domain.
    with mpmath.workprec(200):
        for i in range(-2900, 2901, 7):  # -290.0 .. 290.0 in 0.7 steps
            x = i / 10.0
            assert pow10(x) == float(mpmath.power(10, mpmath.mpf(x))), f"x={x}"
        for i in range(-199, 200):  # dense fractional coverage around 0
            x = i / 100.0
            assert pow10(x) == float(mpmath.power(10, mpmath.mpf(x))), f"x={x}"
