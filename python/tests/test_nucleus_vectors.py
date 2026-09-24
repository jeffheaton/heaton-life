"""Discovery conformance runner (spec/nucleus.md): the box period, Newton's nucleus, snap.

Each case names an operation, its inputs, and every field of the result: exact, but the
size and the framing's half-height, which are compared within the case's relative
epsilon. Strict, like the other runners: a key this runner does not know fails the case.
"""

import json
import math
import struct
from pathlib import Path
from typing import Any

import pytest

from heaton_life.fractal.nucleus import BoxResult, Nucleus, box_period, find_nucleus

ROOT = Path(__file__).resolve().parents[2] / "vectors" / "nucleus"
CASES = sorted(ROOT.glob("*/params.json"))
BASE_KEYS = {"spec_version", "family", "tier", "relative_epsilon", "operation", "input", "expected"}
COMMON_INPUT = {"center_re", "center_im", "zoom_log10", "radius"}
INPUT_KEYS = {
    "box": COMMON_INPUT | {"max_period"},
    "snap": COMMON_INPUT | {"max_period"},
    "find": COMMON_INPUT | {"period", "max_steps", "max_evaluations", "max_escalations"},
}
EXPECTED_KEYS = {
    "box": {"box"},
    "snap": {"box", "nucleus", "location"},
    "find": {"nucleus", "location"},
}
BOX_KEYS = {"period", "reason", "halvings", "radius"}
NUCLEUS_KEYS = {field.name for field in Nucleus.__dataclass_fields__.values()}
STOPS = {
    "floor",
    "no-improvement",
    "left-view",
    "stagnated",
    "max-evaluations",
    "max-steps",
    "zero-derivative",
    "start-escaped",
}


def _double(bits: str) -> float:
    return float(struct.unpack("<d", struct.pack("<Q", int(bits, 16)))[0])


def _close(got: float, want: float, epsilon: float) -> bool:
    if math.isnan(want):
        return math.isnan(got)
    return abs(got - want) <= epsilon * abs(want)


def _check_box(got: BoxResult, want: dict[str, Any]) -> None:
    assert set(want) == BOX_KEYS
    assert (got.period, got.reason, got.halvings) == (
        want["period"],
        want["reason"],
        want["halvings"],
    )
    assert got.radius == _double(want["radius"])


def _check_nucleus(
    got: Nucleus, want: dict[str, Any], location: dict[str, Any] | None, epsilon: float
) -> None:
    assert set(want) == NUCLEUS_KEYS
    exact = {k: v for k, v in want.items() if k != "size_log10"}
    assert {k: getattr(got, k) for k in exact} == exact
    assert _close(got.size_log10, _double(want["size_log10"]), epsilon)
    if location is None:
        assert not got.found
        return
    assert set(location) == {"half_height_log10", "max_iter"}
    loc = got.location()
    assert loc.format == "nucleus" and loc.max_iter == location["max_iter"]
    assert loc.half_height_log10 is not None
    assert _close(loc.half_height_log10, _double(location["half_height_log10"]), epsilon)


def test_nucleus_vectors_cover_every_outcome() -> None:
    metas = [json.loads(case.read_text()) for case in CASES]
    assert {meta["operation"] for meta in metas} == set(INPUT_KEYS)
    stops = {m["expected"]["nucleus"]["stop"] for m in metas if m["expected"].get("nucleus")}
    assert stops == STOPS
    reasons = {m["expected"]["box"]["reason"] for m in metas if "box" in m["expected"]}
    assert reasons == {"surrounded", "budget", "escaped"}


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.parent.name)
def test_nucleus_vector(case: Path) -> None:
    meta: dict[str, Any] = json.loads(case.read_text())
    assert set(meta) == BASE_KEYS, f"{case}: keys {sorted(set(meta) ^ BASE_KEYS)}"
    assert meta["family"] == "nucleus" and meta["tier"] == "bit-exact"
    assert meta["spec_version"] == "0.9.0"
    operation = meta["operation"]
    inputs, expected = meta["input"], meta["expected"]
    assert set(inputs) == INPUT_KEYS[operation]
    assert set(expected) == EXPECTED_KEYS[operation]
    epsilon = meta["relative_epsilon"]
    center_re, center_im, zoom = inputs["center_re"], inputs["center_im"], inputs["zoom_log10"]
    radius = None if inputs["radius"] is None else _double(inputs["radius"])
    if operation == "find":
        got = find_nucleus(
            center_re,
            center_im,
            inputs["period"],
            zoom,
            radius,
            max_steps=inputs["max_steps"],
            max_evaluations=inputs["max_evaluations"],
            max_escalations=inputs["max_escalations"],
        )
        _check_nucleus(got, expected["nucleus"], expected["location"], epsilon)
        return
    box = box_period(center_re, center_im, zoom, inputs["max_period"], radius)
    _check_box(box, expected["box"])
    if operation == "box":
        return
    if box.period is None:
        assert expected["nucleus"] is None and expected["location"] is None
        return
    got = find_nucleus(center_re, center_im, box.period, zoom, box.radius)
    _check_nucleus(got, expected["nucleus"], expected["location"], epsilon)
