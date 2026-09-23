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
