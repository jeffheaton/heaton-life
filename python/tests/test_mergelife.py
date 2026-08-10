"""MergeLife tests, including replay of the upstream cross-engine conformance vectors
(vectors/mergelife-upstream/, from github.com/jeffheaton/mergelife). Passing them means
this port is byte-identical with the reference Python/JS/Java/C engines.

Per the upstream contract, the LCG and FNV-1a helpers are implemented independently
here in the test harness; only the engine under test is shared code.
"""

import dataclasses
import json
from pathlib import Path

import numpy as np
import pytest

from heaton_life.ca.mergelife import (
    MergeLife,
    canonical_rule,
    compile_rule,
    decode_rule,
    parse_rule_error,
    random_rule,
)

UPSTREAM = Path(__file__).resolve().parents[2] / "vectors" / "mergelife-upstream" / "vectors.txt"


def lcg_lattice(seed: int, rows: int, cols: int) -> np.ndarray:
    """Upstream spec PRNG: 32-bit LCG, one byte (state >> 24) per advance, row-major RGB."""
    state = seed & 0xFFFFFFFF
    flat = np.empty(rows * cols * 3, dtype=np.uint8)
    for i in range(flat.size):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        flat[i] = state >> 24
    return flat.reshape(rows, cols, 3)


def fnv1a64(data: bytes) -> str:
    h = 0xCBF29CE484222325
    for b in data:
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


def upstream_cases() -> list[tuple[str, int, int, int, int, str]]:
    cases = []
    for line in UPSTREAM.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rule, rows, cols, seed, steps, digest = line.split()
        cases.append((rule, int(rows), int(cols), int(seed), int(steps), digest))
    return cases


@pytest.mark.parametrize("rule,rows,cols,seed,steps,digest", upstream_cases())
def test_upstream_conformance(
    rule: str, rows: int, cols: int, seed: int, steps: int, digest: str
) -> None:
    sim = MergeLife(rule, size=(cols, rows), init=lcg_lattice(seed, rows, cols))
    sim.step(steps)
    assert fnv1a64(sim.state.tobytes()) == digest


def test_rule_canonicalization() -> None:
    mixed = "E542-5F79-9341-F31E-6C6B-7F08-8773-7068"
    assert canonical_rule(mixed) == "e542-5f79-9341-f31e-6c6b-7f08-8773-7068"
    assert canonical_rule(mixed.replace("-", "")) == canonical_rule(mixed)


@pytest.mark.parametrize("bad", ["", "e542", "zz42-" * 8, "e542-5f79-9341-f31e-6c6b-7f08-8773"])
def test_invalid_rule(bad: str) -> None:
    assert parse_rule_error(bad) is not None
    with pytest.raises(ValueError):
        MergeLife(bad, size=(8, 8))


def test_rule_compilation_details() -> None:
    # 0xff * 8 = 2040 is promoted to 2048 so the top sub-rule catches every count;
    # negative percents index the *next* key color at |pct|/128.
    rule = compile_rule("ff7f-0080-0000-0000-0000-0000-0000-0000")
    limits = [entry[0] for entry in rule]
    assert max(limits) == 2048
    assert min(limits) == 0
    first = rule[0]
    assert first[0] == 0  # 0x00 * 8, stable sort keeps rule order among ties
    top = next(e for e in rule if e[0] == 2048)
    assert top[1] == pytest.approx(127 / 127.0)


def test_soup_determinism_and_shapes() -> None:
    a = MergeLife(size=(32, 24), seed=11)
    b = MergeLife(size=(32, 24), seed=11)
    assert a.state.shape == (24, 32, 3)
    assert np.array_equal(a.state, b.state)
    a.step(5)
    b.step(5)
    assert np.array_equal(a.state, b.state)
    assert a.frame().shape == (24, 32, 3)


def test_step_changes_grid() -> None:
    sim = MergeLife(size=(32, 32), seed=1)
    before = sim.state.copy()
    sim.step()
    assert not np.array_equal(sim.state, before)


def test_decode_rule_red_world() -> None:
    rows = decode_rule("e542-5f79-9341-f31e-6c6b-7f08-8773-7068")
    assert len(rows) == 8
    first = rows[0]  # the HeatonCA Rule-tab top row
    assert (first.limit, first.range_low, first.range_high) == (760, 0, 759)
    assert (first.color_index, first.color_name) == (1, "Red")
    assert (first.target_index, first.target_name) == (1, "Red")
    assert first.target_rgb == (255, 0, 0)
    assert (first.range_byte, first.percent_byte) == (0x5F, 0x79)
    assert int(first.percent * 100) == 95
    last = rows[-1]
    assert (last.limit, last.color_name) == (1944, "Yellow")
    assert int(last.percent * 100) == 23  # truncation, not rounding


def test_decode_rule_negative_swaps_target_and_keeps_raw_octets() -> None:
    rows = decode_rule("ff40-00c0-8020-407f-2081-6001-a0ff-e080")
    by_index = {r.color_index: r for r in rows}
    promoted = by_index[0]
    assert promoted.limit == 2048
    assert promoted.range_byte == 0xFF  # raw, not limit/8
    neg = by_index[1]
    assert neg.percent == -0.5
    assert (neg.color_name, neg.target_name) == ("Red", "Green")
    assert neg.percent_byte == -64
    wrap = by_index[7]
    assert wrap.percent == -1.0
    assert (wrap.target_index, wrap.target_name) == (0, "Black")


def test_decode_vectors_replay() -> None:
    root = Path(__file__).resolve().parents[2] / "vectors" / "mergelife-decode"
    cases = sorted(root.iterdir())
    assert cases, "mergelife-decode vectors missing"
    for case_dir in cases:
        meta = json.loads((case_dir / "params.json").read_text())
        rows = decode_rule(meta["rule"])
        assert len(rows) == len(meta["expected_rows"])
        for row, expected in zip(rows, meta["expected_rows"]):
            got = dataclasses.asdict(row)
            got["target_rgb"] = list(got["target_rgb"])
            assert got == expected, f"{case_dir.name}: row {expected['color_index']}"


def test_random_rule_is_valid_and_deterministic() -> None:
    g1 = random_rule(42)
    g2 = random_rule(42)
    assert g1 == g2
    assert parse_rule_error(g1) is None
    assert random_rule(43) != g1
