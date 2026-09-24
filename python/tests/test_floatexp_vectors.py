"""Floatexp conformance runner (spec/floatexp.md): each operation at its boundaries, bit
for bit -- values as [mantissa bits, exponent], doubles as bits. Strict: an unknown key
or operation fails the case."""

import json
import struct
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from heaton_life.core import floatexp as fx
from heaton_life.core.pow10 import pow10x

ROOT = Path(__file__).resolve().parents[2] / "vectors" / "floatexp"
CASES = sorted(p.name for p in ROOT.iterdir() if p.is_dir())
KEYS = {
    "add": {"a", "b"},
    "mul": {"a", "b"},
    "compare": {"a", "b"},
    "div": {"a", "b"},
    "to_double": {"a"},
    "from_fixed": {"value", "bits"},
    "normalize": {"value", "exponent"},
}


def _double(bits: str) -> float:
    return float(struct.unpack("<d", struct.pack("<Q", int(bits, 16)))[0])


def _bits(value: float) -> str:
    return f"0x{struct.unpack('<Q', struct.pack('<d', value))[0]:016X}"


def _x(pair: list[Any]) -> fx.X:
    return _double(pair[0]), int(pair[1])


def test_every_operation_is_pinned() -> None:
    assert CASES == ["division", "operations"]
    ops = {case["op"] for name in CASES for case in _meta(name)["cases"]}
    assert ops == set(KEYS)


def _meta(name: str) -> dict[str, Any]:
    meta: dict[str, Any] = json.loads((ROOT / name / "params.json").read_text())
    assert set(meta) == {"spec_version", "family", "tier", "cases"}
    assert (meta["spec_version"], meta["family"], meta["tier"]) == (
        "0.10.0",
        "floatexp",
        "bit-exact",
    )
    return meta


@pytest.mark.parametrize("name", CASES)
def test_floatexp_operations(name: str) -> None:
    for case in _meta(name)["cases"]:
        op = case["op"]
        assert op in KEYS, f"unknown operation {op}"
        assert set(case) == KEYS[op] | {"op", "expected", "note"}, case
        if op == "add":
            got: Any = fx.add(_x(case["a"]), _x(case["b"]))
        elif op == "mul":
            got = fx.mul(_x(case["a"]), _x(case["b"]))
        elif op == "div":
            got = fx.div(_x(case["a"]), _x(case["b"]))
        elif op == "compare":
            got = fx.compare(_x(case["a"]), _x(case["b"]))
        elif op == "to_double":
            got = _bits(fx.to_double(_x(case["a"])))
        elif op == "from_fixed":
            got = fx.from_fixed(int(case["value"]), case["bits"])
        else:
            got = fx.normalize(_double(case["value"]), case["exponent"])
        if op not in ("to_double", "compare"):
            got = [_bits(got[0]), got[1]]
        assert got == case["expected"], case["note"]


def test_pow10x_known_answers() -> None:
    """spec/pow10.md "Floatexp"."""
    answers = {
        -300.5: ("0x3FFB1B75833790CA", -999),
        -320.0: ("0x3FFFA01712E8F047", -1064),
        -996.5: ("0x3FF9F7C393991048", -3311),
        -9000.0: ("0x3FF90E9C5BFAC594", -29898),
        10000.0: ("0x3FF3709D450AAD7E", 33219),
    }
    for x, (mantissa, exponent) in answers.items():
        m, n = pow10x(x)
        assert (_bits(m), n) == (mantissa, exponent), x


def test_numpy_meets_the_floating_point_contract() -> None:
    """spec/deep-zoom.md "Platform contract", the C# FloatingPointContract canaries on
    NumPy arrays: no contraction, gradual underflow, no extended range or precision."""
    v = np.array([1 + 2**-30, 1 + 2**-31, 1.0, 2.0**-1022, 0.5, 0.75, 2.0**-60, 2.0**60])
    a, b, one, tiny, half, three_quarters, down, up = (v[k : k + 1] for k in range(8))
    nxt = one + 2.0**-52
    assert ((a * a - b * b) + 2.0**-40)[0] == 2.0**-30 + 2.0**-40
    assert (a * a + -one)[0] == 2.0**-29
    assert (nxt * tiny * half)[0] == 2.0**-1023
    assert (tiny * three_quarters)[0] != 0.0
    assert ((tiny * half) * 2.0)[0] == tiny[0]
    assert (tiny * down * up)[0] == 0.0
    assert ((nxt + 2.0**-53) - one)[0] == 2.0**-51
