"""cis_turns conformance runner (spec/turns.md): each (k, n) to the IEEE-754 bit patterns
of (cos 2 pi k/n, sin 2 pi k/n). Strict: an unknown key fails the case."""

import json
import struct
from pathlib import Path

from heaton_life.core.turns import HALF_PI, cis_turns

CASE = Path(__file__).resolve().parents[2] / "vectors" / "turns" / "known-answers" / "params.json"


def _bits(value: float) -> str:
    return f"0x{struct.unpack('<Q', struct.pack('<d', value))[0]:016X}"


def test_cis_turns_known_answers() -> None:
    meta = json.loads(CASE.read_text())
    assert set(meta) == {"spec_version", "family", "tier", "cases"}
    assert (meta["spec_version"], meta["family"], meta["tier"]) == ("0.12.0", "turns", "bit-exact")
    for case in meta["cases"]:
        assert set(case) == {"k", "n", "expected"}, case
        re, im = cis_turns(case["k"], case["n"])
        assert [_bits(re), _bits(im)] == case["expected"], case


def test_half_pi_is_pinned() -> None:
    """floor(pi/2 * 2^192): pi from its first 70 decimal places, which bound it."""
    from fractions import Fraction

    low = Fraction(3141592653589793238462643383279502884197169399375105820974944592307816, 10**69)
    high = low + Fraction(1, 10**69)
    assert (low / 2 * 2**192) // 1 == HALF_PI == (high / 2 * 2**192) // 1


def test_domain_and_integer_types() -> None:
    import numpy as np
    import pytest

    from heaton_life.fractal.newton import Newton

    assert cis_turns(1, np.int64(4)) == (0.0, 1.0)  # NumPy integers are integers
    assert Newton(degree=np.int64(4)).degree == 4
    assert cis_turns(-(2**70) - 1, 4) == cis_turns(-1, 4)  # any k reduces exactly
    for n in (0, -3, (1 << 61) + 1):
        with pytest.raises(ValueError):
            cis_turns(1, n)
    with pytest.raises(TypeError):
        cis_turns(1.0, 4)  # type: ignore[arg-type]
