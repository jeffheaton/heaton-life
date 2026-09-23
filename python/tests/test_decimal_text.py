"""The viewport-center grammar and its float64 projection (core/decimal_text.py).

The grammar lists mirror the .NET DecimalTextTests: a string one port accepts, the
other must too.
"""

import random
from fractions import Fraction

import pytest

from heaton_life.core import decimal_text
from heaton_life.core.viewport import Viewport

ACCEPTED = [
    "0",
    "-0",
    "+1",
    "5.",
    ".5",
    "-.5e-3",
    "1e5",
    "1E+5",
    "1e-005",
    "2.5E1",
    " 1 ",
    "\t-2.5e-3\n",
    "00012.3400",
    "1e100000",
]

REJECTED = [
    "",
    " ",
    ".",
    "e5",
    "1e",
    "1e+",
    "--1",
    "+-1",
    "1.2.3",
    "1e5.5",
    "1e100001",
    "NaN",
    "nan",
    "Infinity",
    "-Inf",
    "1_000",
    "1,000",
    "0x10",
    "\u0661\u0662",
    "1 2",
]


def test_grammar_accepts_and_rejects_exactly_the_shared_lists() -> None:
    for s in ACCEPTED:
        decimal_text.scan(s)
    for s in REJECTED:
        with pytest.raises(ValueError):
            decimal_text.scan(s)


def test_viewport_refuses_what_the_orbit_parser_cannot_read() -> None:
    # decimal.Decimal() accepted all of these before the shared grammar.
    for s in ("NaN", "Infinity", "1_000", "\u0661\u0662"):
        with pytest.raises(ValueError):
            Viewport(s, "0", 0.0)
        with pytest.raises(ValueError):
            Viewport("0", s, 0.0)


def _exact(text: str) -> float:
    negative, digits, exponent = decimal_text.scan(text)
    value = Fraction(digits) * Fraction(10) ** exponent
    try:
        result = float(value)  # Fraction -> float rounds correctly (int true division)
    except OverflowError:
        result = float("inf")
    return -result if negative else result


def test_projection_is_the_single_correct_rounding() -> None:
    rng = random.Random(11)
    for _ in range(5000):
        digits = "".join(rng.choice("0123456789") for _ in range(rng.randint(1, 40)))
        point = rng.randint(0, len(digits))
        mantissa = digits[:point] + "." + digits[point:]
        if mantissa == ".":
            continue
        text = f"{rng.choice(['', '-'])}{mantissa}e{rng.randint(-400, 400)}"
        assert decimal_text.to_float(text) == _exact(text), text


def test_overflow_underflow_and_signed_zero() -> None:
    assert decimal_text.to_float("1.7976931348623157e308") == 1.7976931348623157e308
    assert decimal_text.to_float("1e400") == float("inf")
    assert decimal_text.to_float("-1e100000") == float("-inf")
    assert decimal_text.to_float("1e-400") == 0.0
    assert decimal_text.to_float("4.9406564584124654e-324") == 5e-324
    assert str(decimal_text.to_float("-0.000")) == "-0.0"
    assert str(decimal_text.to_float("-1e-400")) == "-0.0"


def test_digit_count_is_bounded() -> None:
    decimal_text.scan("1" * decimal_text.MAX_DIGITS)
    decimal_text.scan("0." + "1" * (decimal_text.MAX_DIGITS - 1))
    with pytest.raises(ValueError):
        decimal_text.scan("1" * (decimal_text.MAX_DIGITS + 1))
    with pytest.raises(ValueError):
        decimal_text.scan("0." + "1" * decimal_text.MAX_DIGITS)
