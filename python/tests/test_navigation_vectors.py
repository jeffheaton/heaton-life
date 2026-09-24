"""Navigation conformance runner (spec/navigation.md): exact viewport arithmetic.

Each case names an operation, its inputs, and the expected strings -- or, for
pixel_delta, the doubles as IEEE-754 bit patterns. Strict, like the fractal runner: a
key or operation this runner does not know fails the case instead of being skipped.
"""

import json
import struct
from pathlib import Path
from typing import Any

import pytest

from heaton_life.core import decimal_text
from heaton_life.core.bignum import working_bits
from heaton_life.core.viewport import Viewport
from heaton_life.fractal import pan, pixel_delta, zoom_at

ROOT = Path(__file__).resolve().parents[2] / "vectors" / "navigation"
CASES = sorted(ROOT.glob("*/params.json"))
BASE_KEYS = {"spec_version", "family", "tier", "operation", "expected"}
OPERATION_KEYS = {
    "pan": {"viewport", "size", "dx", "dy"},
    "zoom_at": {"viewport", "size", "dx", "dy", "zoom_log10"},
    "pixel_delta": {"from", "to", "size"},
    "positional": {"inputs"},
    "sequence": {"viewport", "size", "steps"},
}


def _bits(value: float) -> str:
    return f"0x{struct.unpack('<Q', struct.pack('<d', value))[0]:016X}"


def test_navigation_vectors_exist() -> None:
    operations = {json.loads(case.read_text())["operation"] for case in CASES}
    assert operations == set(OPERATION_KEYS)


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.parent.name)
def test_navigation_vector(case: Path) -> None:
    meta: dict[str, Any] = json.loads(case.read_text())
    assert meta["family"] == "navigation" and meta["tier"] == "bit-exact"
    # 0.10.0 added T2 navigation (spec/navigation.md): zooms past 290, floatexp offsets.
    assert meta["spec_version"] in ("0.5.0", "0.10.0")
    operation = meta["operation"]
    allowed = BASE_KEYS | OPERATION_KEYS[operation]
    if operation == "pan":
        allowed |= {"zoom_log10"}  # optional: pan and zoom in one step
    assert set(meta) <= allowed and set(meta) >= BASE_KEYS | OPERATION_KEYS[operation], (
        f"{case}: unexpected keys {sorted(set(meta) ^ allowed)}"
    )
    expected = meta["expected"]
    if operation == "positional":
        assert [decimal_text.positional(text) for text in meta["inputs"]] == expected
        return
    size = (meta["size"][0], meta["size"][1])
    if operation == "pixel_delta":
        dx, dy = pixel_delta(Viewport.from_dict(meta["from"]), Viewport.from_dict(meta["to"]), size)
        assert (_bits(dx), _bits(dy)) == (expected["dx_bits"], expected["dy_bits"])
        return
    viewport = Viewport.from_dict(meta["viewport"])
    if operation == "sequence":
        assert len(meta["steps"]) == len(expected)
        for step, want in zip(meta["steps"], expected, strict=True):
            assert set(step) == {"operation", "dx", "dy"} and step["operation"] == "pan"
            viewport = pan(viewport, step["dx"], step["dy"], size)
            assert viewport.to_dict() == {k: v for k, v in want.items() if k != "working_bits"}
            bits = working_bits(viewport.center_re, viewport.center_im, viewport.zoom_log10)
            assert bits == want["working_bits"]
        return
    if operation == "pan":
        got = pan(viewport, meta["dx"], meta["dy"], size, meta.get("zoom_log10"))
    else:
        got = zoom_at(viewport, meta["dx"], meta["dy"], size, meta["zoom_log10"])
    assert got.to_dict() == expected
