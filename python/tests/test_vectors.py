"""Conformance runner: replays every case in vectors/ and compares states.

Discrete CA families are bit-exact; float families compare within the case's
epsilon (same-language replay is exact anyway — the ε is headroom for the .NET
implementation's FFT/libm differences). Codecs live in heaton_life.conformance
and are part of the cross-language contract.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from heaton_life.conformance import CODECS, build_sim, bytes_to_state

VECTOR_ROOT = Path(__file__).resolve().parents[2] / "vectors"
CASES = sorted(
    p for p in VECTOR_ROOT.glob("*/*/params.json") if p.parent.parent.name in CODECS
)


def test_vectors_exist_for_every_family() -> None:
    families = {p.parent.parent.name for p in CASES}
    assert families == set(CODECS), f"families without vectors: {set(CODECS) - families}"


@pytest.mark.parametrize("case", CASES, ids=lambda p: f"{p.parent.parent.name}/{p.parent.name}")
def test_vector(case: Path) -> None:
    case_dir = case.parent
    meta = json.loads(case.read_text())
    family = meta["family"]

    initial = None
    first = meta["checkpoints"][0]
    if meta["params"].get("init") == "array":
        initial = bytes_to_state(family, (case_dir / first["file"]).read_bytes(), first.get("shape"))
    sim = build_sim(family, meta["params"], initial)

    current = 0
    for checkpoint in meta["checkpoints"]:
        step, file = checkpoint["step"], checkpoint["file"]
        sim.step(step - current)
        current = step
        expected = bytes_to_state(family, (case_dir / file).read_bytes(), checkpoint.get("shape"))
        state = np.asarray(sim.state)
        if meta["tier"] == "bit-exact":
            assert np.array_equal(state, expected), (
                f"{family}/{case_dir.name}: state mismatch at step {step}"
            )
        else:
            epsilon = float(meta["epsilon"])
            deviation = float(np.max(np.abs(state - expected)))
            assert deviation <= epsilon, (
                f"{family}/{case_dir.name}: max deviation {deviation:.3e} > {epsilon:.1e} "
                f"at step {step}"
            )
