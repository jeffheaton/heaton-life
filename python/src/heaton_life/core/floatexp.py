"""Floatexp -- spec/floatexp.md: a float64 mantissa with an unbounded integer exponent.

A value is m * 2^e with |m| in [1, 2), or exactly zero as (0.0, 0). Every operation is
one IEEE-754 float64 operation on mantissas plus exact integer exponent arithmetic, and
every rescaling is a multiply by an exact normal power of two, so both ports compute the
same bits: add and mul are correctly rounded (ties to even) with no exponent range limit.
Scalar functions take and return (m, e) tuples; the ``v``-prefixed functions work on
NumPy arrays (mantissa float64, exponent int64) elementwise, bit for bit the same.

No libm call and no fused multiply-add anywhere: NumPy real-array ufuncs never contract.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from numpy.typing import NDArray

X = tuple[float, int]
FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]

ZERO: X = (0.0, 0)
ALIGN_LIMIT = 64  # add: an operand more than 64 binades below the other rounds away
MIN_NORMAL_EXP = -1022
MAX_EXP = 1023
EXP_FLOOR = -(2**31)  # a result whose exponent falls below this is zero (never overflows)

__all__ = [
    "ZERO",
    "X",
    "add",
    "binade",
    "compare",
    "from_double",
    "from_fixed",
    "mul",
    "neg",
    "normalize",
    "pow2",
    "scaled",
    "square",
    "sub",
    "to_double",
    "twice",
]


def pow2(k: int) -> float:
    """2^k as a double for k in [-1022, 1023]: exact, from the IEEE bits (no libm)."""
    if not MIN_NORMAL_EXP <= k <= MAX_EXP:
        raise ValueError(f"2^{k} is not a normal double")
    return math.ldexp(1.0, k)  # exact for normal results


def binade(value: float) -> int:
    """The k with |value| in [2^k, 2^(k+1)), for a finite nonzero double (subnormals too)."""
    return math.frexp(value)[1] - 1


def normalize(value: float, exponent: int) -> X:
    """value * 2^exponent as (m, e), |m| in [1, 2): exact."""
    if value == 0.0:
        return ZERO
    if not math.isfinite(value):
        raise ValueError("floatexp values are finite")
    mantissa, k = math.frexp(value)  # value = mantissa * 2^k, |mantissa| in [0.5, 1)
    if exponent + k - 1 < EXP_FLOOR:
        return ZERO  # past 2^-(2^31): an iterated square, e.g. at an exact zero of the orbit
    return mantissa * 2.0, exponent + k - 1


def from_double(value: float) -> X:
    return normalize(value, 0)


def from_fixed(value: int, bits: int) -> X:
    """value / 2^bits, the integer rounded to 53 significant bits (ties to even, sticky)."""
    if value == 0:
        return ZERO
    magnitude = abs(int(value))
    shift = max(magnitude.bit_length() - 53, 0)
    q = magnitude >> shift
    if shift:
        remainder = magnitude & ((1 << shift) - 1)
        half = 1 << (shift - 1)
        if remainder > half or (remainder == half and q & 1):
            q += 1
    top = q.bit_length() - 1  # 53, or 54 when rounding carried into a new binade
    mantissa = math.ldexp(float(q), -top)  # exact: q has at most 54 bits
    return (-mantissa if value < 0 else mantissa), shift + top - bits


def neg(a: X) -> X:
    return (-a[0], a[1]) if a[0] != 0.0 else ZERO


def twice(a: X) -> X:
    return (a[0], a[1] + 1) if a[0] != 0.0 else ZERO


def mul(a: X, b: X) -> X:
    if a[0] == 0.0 or b[0] == 0.0:
        return ZERO
    return normalize(a[0] * b[0], a[1] + b[1])


def square(a: X) -> X:
    return mul(a, a)


def add(a: X, b: X) -> X:
    """Correctly rounded a + b: aligned at the larger exponent (exact while the gap is at
    most 64), one IEEE add; an operand more than 64 binades down cannot move the result."""
    if a[0] == 0.0:
        return b
    if b[0] == 0.0:
        return a
    if a[1] < b[1]:
        a, b = b, a
    gap = a[1] - b[1]
    if gap > ALIGN_LIMIT:
        return a
    return normalize(a[0] + b[0] * pow2(-gap), a[1])


def sub(a: X, b: X) -> X:
    return add(a, neg(b))


def div(a: X, b: X) -> X:
    """a / b for a nonzero b: normalize(a.m / b.m, a.e - b.e), one IEEE division, so
    correctly rounded (the quotient of two mantissas lies in (1/2, 2))."""
    if b[0] == 0.0:
        raise ZeroDivisionError("floatexp division by zero")
    if a[0] == 0.0:
        return ZERO
    return normalize(a[0] / b[0], a[1] - b[1])


def compare(a: X, b: X) -> int:
    """-1, 0 or 1 as a <, =, > b (a total order on values; zero has no sign)."""
    sa = (a[0] > 0.0) - (a[0] < 0.0)
    sb = (b[0] > 0.0) - (b[0] < 0.0)
    if sa != sb:
        return -1 if sa < sb else 1
    if sa == 0:
        return 0
    key_a = (a[1], abs(a[0]))
    key_b = (b[1], abs(b[0]))
    if key_a == key_b:
        return 0
    bigger = key_a > key_b
    return (1 if bigger else -1) * sa


def to_double(a: X) -> float:
    """m * 2^e rounded once to a double: exact in the normal range, one correctly rounded
    step into the subnormals, signed zero below them, +-inf past the top."""
    m, e = a
    if m == 0.0:
        return 0.0
    if e > MAX_EXP:
        return math.inf if m > 0.0 else -math.inf
    if e >= MIN_NORMAL_EXP:
        return m * pow2(e)
    if e >= 2 * MIN_NORMAL_EXP:
        # m * 2^(e + 1022) is normal and exact; the second multiply rounds once.
        return (m * pow2(e - MIN_NORMAL_EXP)) * pow2(MIN_NORMAL_EXP)
    return -0.0 if m < 0.0 else 0.0


def scaled(a: X, exponent: int) -> float:
    """a / 2^exponent as a double (to_double's rounding)."""
    return to_double((a[0], a[1] - exponent)) if a[0] != 0.0 else 0.0


# --- vectorized (NumPy): mantissas float64, exponents int64 ----------------------------


def vnormalize(values: FloatArray, exponents: IntArray) -> tuple[FloatArray, IntArray]:
    """normalize elementwise (values finite)."""
    mantissa, k = np.frexp(values)
    e = exponents + k.astype(np.int64) - 1
    zero = (values == 0.0) | (e < EXP_FLOOR)
    m = np.where(zero, 0.0, mantissa * 2.0)
    e = np.where(zero, 0, e)
    return m, e.astype(np.int64)


def vpow2(k: NDArray[Any]) -> FloatArray:
    """2^k elementwise for k in [-1022, 1023] (exact)."""
    result: FloatArray = np.ldexp(1.0, k.astype(np.int32))
    return result


def vmul(am: FloatArray, ae: IntArray, bm: FloatArray, be: IntArray) -> tuple[FloatArray, IntArray]:
    return vnormalize(am * bm, ae + be)


def vadd(am: FloatArray, ae: IntArray, bm: FloatArray, be: IntArray) -> tuple[FloatArray, IntArray]:
    a_zero = am == 0.0
    b_zero = bm == 0.0
    swap = ae < be
    hm = np.where(swap, bm, am)
    he = np.where(swap, be, ae)
    lm = np.where(swap, am, bm)
    le = np.where(swap, ae, be)
    gap = he - le
    near = gap <= ALIGN_LIMIT
    shift = np.where(near, -gap, 0)
    total = np.where(near, hm + lm * vpow2(shift), hm)
    m, e = vnormalize(total, he)
    m = np.where(a_zero, bm, np.where(b_zero, am, m))
    e = np.where(a_zero, be, np.where(b_zero, ae, e))
    return m, e.astype(np.int64)


def vdiv(am: FloatArray, ae: IntArray, bm: FloatArray, be: IntArray) -> tuple[FloatArray, IntArray]:
    """div elementwise; every b must be nonzero."""
    return vnormalize(am / bm, ae - be)


def vto_double(m: FloatArray, e: IntArray) -> FloatArray:
    """to_double elementwise."""
    with np.errstate(over="ignore", under="ignore"):
        normal = (e >= MIN_NORMAL_EXP) & (e <= MAX_EXP)
        low = (e < MIN_NORMAL_EXP) & (e >= 2 * MIN_NORMAL_EXP)
        out = np.where(normal, m * vpow2(np.where(normal, e, 0)), 0.0)
        step = m * vpow2(np.where(low, e - MIN_NORMAL_EXP, 0))
        out = np.where(low, step * pow2(MIN_NORMAL_EXP), out)
        out = np.where(e > MAX_EXP, np.where(m > 0.0, np.inf, -np.inf), out)
        out = np.where(e < 2 * MIN_NORMAL_EXP, np.where(m < 0.0, -0.0, 0.0), out)
        out = np.where(m == 0.0, 0.0, out)
    result: FloatArray = out
    return result


def vcompare_magnitude2(
    am: FloatArray, ae: IntArray, bm: FloatArray, be: IntArray
) -> NDArray[np.int8]:
    """sign(a - b) for non-negative floatexp values a, b (squared magnitudes)."""
    a_zero = am == 0.0
    b_zero = bm == 0.0
    greater = (ae > be) | ((ae == be) & (am > bm))
    less = (ae < be) | ((ae == be) & (am < bm))
    out = np.where(greater, 1, np.where(less, -1, 0)).astype(np.int8)
    out = np.where(a_zero & b_zero, 0, np.where(a_zero, -1, np.where(b_zero, 1, out)))
    result: NDArray[np.int8] = out.astype(np.int8)
    return result
