"""The decimal-string grammar of viewport centers (spec/deep-zoom.md "Viewport contract").

One grammar for every consumer: Viewport validation, the fixed-point orbit parse
(core.bignum), and the float64 projection T0 renders from. The C# port scans the
same way (HeatonLife.DecimalText), so a string one side accepts the other does too.

    [ws] [+|-] digits-with-at-most-one-point [ (e|E) [+|-] digits ] [ws]

At least one digit before the exponent (".5" and "5." are fine, "." is not); at most
10,000 digits before it; exponent magnitude at most 100,000; ASCII digits only;
surrounding ASCII spaces, tabs, CRs and LFs are ignored. No NaN, no infinities, no
"_" separators. The two bounds keep parsing and the orbit precision finite for any
string a caller can hand in.
"""

from __future__ import annotations

import math

MAX_DIGITS = 10_000
MAX_EXPONENT = 100_000
_WHITESPACE = " \t\r\n"


def scan(text: str) -> tuple[bool, int, int]:
    """(negative, digits, net_exponent) with value = digits * 10^net_exponent.

    Raises ValueError for anything outside the grammar.
    """
    s = text.strip(_WHITESPACE)
    if not s:
        raise ValueError("empty decimal string")
    i = 0
    negative = False
    if s[i] in "+-":
        negative = s[i] == "-"
        i += 1
    digits = 0
    digit_count = 0
    fraction_digits = 0
    saw_digit = saw_point = saw_exponent = False
    while i < len(s):
        c = s[i]
        if "0" <= c <= "9":
            digit_count += 1
            if digit_count > MAX_DIGITS:
                raise ValueError(f"more than {MAX_DIGITS} digits: {text[:40]!r}...")
            digits = digits * 10 + (ord(c) - 48)
            if saw_point:
                fraction_digits += 1
            saw_digit = True
        elif c == "." and not saw_point:
            saw_point = True
        elif c in "eE" and saw_digit:
            i += 1
            saw_exponent = True
            break
        else:
            raise ValueError(f"not a decimal number: {text!r}")
        i += 1
    if not saw_digit:
        raise ValueError(f"not a decimal number: {text!r}")

    exponent = 0
    if saw_exponent and i >= len(s):
        raise ValueError(f"truncated exponent: {text!r}")
    if i < len(s):
        exp_negative = False
        if s[i] in "+-":
            exp_negative = s[i] == "-"
            i += 1
        if i >= len(s):
            raise ValueError(f"truncated exponent: {text!r}")
        while i < len(s):
            c = s[i]
            if not "0" <= c <= "9":
                raise ValueError(f"not a decimal number: {text!r}")
            exponent = exponent * 10 + (ord(c) - 48)
            if exponent > MAX_EXPONENT:
                raise ValueError(f"exponent out of range: {text!r}")
            i += 1
        if exp_negative:
            exponent = -exponent
    return negative, digits, exponent - fraction_digits


def to_float(text: str) -> float:
    """The float64 nearest the decimal value: one rounding, ties to even.

    Subnormals round like everything else, magnitudes past the float64 range become
    infinities (IEEE-754 round-to-nearest), and "-0" is -0.0. CPython's float()
    rounds a decimal string correctly (David Gay's algorithm), so after the grammar
    check it IS the exact conversion; the C# port computes it from the digits.
    """
    scan(text)
    return float(text.strip(_WHITESPACE))


def difference(minuend: str, subtrahend: str) -> float:
    """The float64 nearest ``minuend - subtrahend``, computed exactly from the digits and
    rounded once (ties to even; infinities past the float64 range; an exact zero is
    +0.0). The off-center reference's offset (spec/deep-zoom.md "Off-center
    reference") -- never a difference of two already-rounded doubles.
    """
    neg_a, digits_a, exp_a = scan(minuend)
    neg_b, digits_b, exp_b = scan(subtrahend)
    common = min(exp_a, exp_b)
    a = digits_a * 10 ** (exp_a - common) * (-1 if neg_a else 1)
    b = digits_b * 10 ** (exp_b - common) * (-1 if neg_b else 1)
    diff: int = a - b
    if diff == 0:
        return 0.0
    try:
        if common >= 0:
            return float(diff * 10**common)
        denominator: int = 10**-common
        return diff / denominator
    except OverflowError:
        return float("inf") if diff > 0 else float("-inf")


def difference_x(minuend: str, subtrahend: str) -> tuple[float, int]:
    """``minuend - subtrahend`` as floatexp (m, e): the exact difference of the digits
    rounded once to a 53-bit mantissa (ties to even), with no exponent range limit --
    difference() for T2, where the off-center offset lies far below float64
    (spec/deep-zoom.md "T2"). An exact zero is (0.0, 0)."""
    neg_a, digits_a, exp_a = scan(minuend)
    neg_b, digits_b, exp_b = scan(subtrahend)
    common = min(exp_a, exp_b)
    a = digits_a * 10 ** (exp_a - common) * (-1 if neg_a else 1)
    b = digits_b * 10 ** (exp_b - common) * (-1 if neg_b else 1)
    diff: int = a - b
    if diff == 0:
        return 0.0, 0
    numerator = abs(diff) * (10**common if common >= 0 else 1)
    denominator = 10**-common if common < 0 else 1
    # A 53-bit quotient: q = floor(value * 2^s) in [2^52, 2^53).
    s = 52 - (numerator.bit_length() - denominator.bit_length())
    while True:
        num, den = (numerator << s, denominator) if s >= 0 else (numerator, denominator << -s)
        q, r = divmod(num, den)
        if q >= 1 << 53:
            s -= 1
        elif q < 1 << 52:
            s += 1
        else:
            break
    if 2 * r > den or (2 * r == den and q & 1):
        q += 1
        if q == 1 << 53:
            q >>= 1
            s -= 1
    mantissa = math.ldexp(float(q), -52)  # exact: q has 53 bits
    return (-mantissa if diff < 0 else mantissa), 52 - s


def digits_of(value: int) -> str:
    """``str(value)`` for a non-negative int of any length. CPython refuses ``str()`` of
    an int past 4,300 digits by default, and the grammar allows 10,000: longer values
    are split at a power of ten and each half converted."""
    if value.bit_length() <= 13_000:  # under 3,914 digits
        return str(value)
    half = value.bit_length() * 30_103 // 200_000  # about half the digit count
    high, low = divmod(value, 10**half)
    return digits_of(high) + digits_of(low).rjust(half, "0")


def format_scaled(value: int, places: int) -> str:
    """``value * 10^-places`` written positionally with exactly ``places`` fraction digits
    (none, and no point, when ``places`` is 0): "-" only for a nonzero negative, no "+",
    one "0" before the point when the magnitude is below 1. Raises ValueError when the
    result would carry more than MAX_DIGITS digits -- it could not be read back.
    """
    if places < 0:
        raise ValueError(f"places must be non-negative, got {places}")
    # 10^MAX_DIGITS has 33,220 bits: refuse a longer value before converting it.
    if places >= MAX_DIGITS or abs(value).bit_length() > 33_220:
        raise ValueError(f"more than {MAX_DIGITS} digits in a positional decimal")
    magnitude = digits_of(abs(value)).rjust(places + 1, "0")
    if len(magnitude) > MAX_DIGITS:
        raise ValueError(f"more than {MAX_DIGITS} digits in a positional decimal")
    body = f"{magnitude[:-places]}.{magnitude[-places:]}" if places else magnitude
    return f"-{body}" if value < 0 else body


def positional(text: str) -> str:
    """The same value written positionally: no exponent, no "+", no sign on zero, no
    leading zeros beyond one -- and the same number of decimal places the precision
    rule counts (max(-net_exponent, 0), spec/deep-zoom.md), so an orbit's working bits
    do not change. "1e-5" -> "0.00001", "-1.2E-7" -> "-0.00000012", "2.5E1" -> "25",
    "0.10" -> "0.10". Raises ValueError outside the grammar, or when the positional
    form would exceed MAX_DIGITS digits ("1e-20000" has 20,000 places).
    """
    negative, digits, net_exponent = scan(text)
    signed = -digits if negative else digits
    if net_exponent >= 0:
        if len(digits_of(digits)) + net_exponent > MAX_DIGITS:
            raise ValueError(f"more than {MAX_DIGITS} digits in a positional decimal")
        return format_scaled(signed * 10**net_exponent, 0)
    return format_scaled(signed, -net_exponent)
