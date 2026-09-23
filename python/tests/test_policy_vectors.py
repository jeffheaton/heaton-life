"""Iteration-policy conformance (spec/fractals.md "Iteration policy", policy version 1)."""

import json
from pathlib import Path

import numpy as np

from heaton_life.fractal import auto_max_iter, need_from_counts, suggest_max_iter

CASE = (
    Path(__file__).resolve().parents[2] / "vectors" / "iteration-policy" / "table" / "params.json"
)


def test_iteration_policy_table() -> None:
    meta = json.loads(CASE.read_text())
    assert set(meta) == {"spec_version", "family", "tier", "policy_version", "ramp", "frames"}
    assert (meta["spec_version"], meta["policy_version"], meta["tier"]) == ("0.6.0", 1, "bit-exact")
    assert meta["family"] == "iteration-policy"
    for row in meta["ramp"]:
        assert set(row) == {"zoom_log10", "max_iter"}
        assert auto_max_iter(row["zoom_log10"]) == row["max_iter"], row
    for frame in meta["frames"]:
        assert set(frame) == {"zoom_log10", "counts", "need", "suggest"}
        counts = np.array(frame["counts"], dtype=np.int64)
        assert need_from_counts(counts) == frame["need"]
        assert suggest_max_iter(frame["zoom_log10"], counts) == frame["suggest"]
