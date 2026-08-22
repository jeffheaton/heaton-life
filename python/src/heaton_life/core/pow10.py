"""pow10 — the spec-pinned deterministic power of ten (spec/pow10.md).

The fractal pixel scale is a bit-exact conformance output computed from
``10^-zoom_log10`` — and ``pow`` is a libm call, so platform libms legitimately
disagree in the last ulp (Windows UCRT rounds ``pow(10, 0.2)`` one ulp below
macOS libm; measured 2026-08-21 as 12 flipped escape counts in
vectors/burning-ship/home-64). Like Pcg32, this module replaces the platform
primitive with a fixed integer algorithm: every implementation computes the
same bits because the arithmetic is arbitrary-precision integers all the way
to the final ties-to-even rounding, never a platform float library.
"""

from __future__ import annotations

import math
import struct

_F = 128  # fixed-point fraction bits (Q128)

# round(log2(10) * 2**128) and round(ln(2) * 2**128) — spec/pow10.md appendix.
_LOG2_10_Q128 = 1130393554869435518674010122299176348979
_LN2_Q128 = 235865763225513294137944142764154484399


def pow10(x: float) -> float:
    """10**x as float64 via the spec/pow10.md integer algorithm (bit-portable).

    Domain: finite ``|x| <= 300`` (deep-zoom.md's tier ceiling is 290; results
    stay normal). Raises ``ValueError`` outside it.
    """
    if not math.isfinite(x) or abs(x) > 300.0:
        raise ValueError(f"pow10 domain is finite |x| <= 300, got {x!r}")
    if x == 0.0:
        return 1.0

    # 1. Exact decompose: x = m * 2**e, sign carried by m.
    bits = struct.unpack("<q", struct.pack("<d", x))[0]
    exp_field = (bits >> 52) & 0x7FF
    frac = bits & ((1 << 52) - 1)
    if exp_field == 0:
        m, e = frac, -1074  # subnormal (|x| <= 300 never is, but exactness is free)
    else:
        m, e = frac | (1 << 52), exp_field - 1075
    if bits < 0:
        m = -m

    # 2. Y ~= x * log2(10) in Q128. Right shift floors (toward -inf) by spec.
    y = (m * _LOG2_10_Q128) << e if e >= 0 else (m * _LOG2_10_Q128) >> -e

    # 3. Split into binary exponent and fraction in [0, 2**F).
    n = y >> _F
    f = y - (n << _F)

    # 4. t ~= frac * ln(2), in [0, ln 2).
    t = (f * _LN2_Q128) >> _F

    # 5. exp(t) * 2**F by Taylor; every operand non-negative, so // truncates
    #    identically to C# BigInteger division.
    acc = 1 << _F
    term = 1 << _F
    k = 1
    while True:
        term = ((term * t) >> _F) // k
        if term == 0:
            break
        acc += term
        k += 1

    # 6. Round to a 53-bit mantissa, ties-to-even. acc is in [2**F, 2**(F+1)).
    shift = _F + 1 - 53
    mant = acc >> shift
    rem = acc - (mant << shift)
    half = 1 << (shift - 1)
    if rem > half or (rem == half and mant & 1):
        mant += 1
    if mant == 1 << 53:
        mant = 1 << 52
        n += 1

    # 7. Assemble the IEEE-754 double directly — no ldexp, no libm.
    assembled = ((n + 1023) << 52) | (mant - (1 << 52))
    result: float = struct.unpack("<d", struct.pack("<q", assembled))[0]
    return result
