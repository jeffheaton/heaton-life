"""Conformance runner: replays every case in vectors/ and compares states exactly.

The same vectors are (will be) consumed by the .NET implementation; discrete CA
families are bit-exact by spec. Family-specific PNG codecs live in
heaton_life.conformance and are part of the cross-language contract.
"""

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from heaton_life.conformance import CODECS, build_sim, image_to_state

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
    if meta["params"].get("init") == "array":
        with Image.open(case_dir / meta["checkpoints"][0]["file"]) as img:
            initial = image_to_state(family, img)
    sim = build_sim(family, meta["params"], initial)

    current = 0
    for checkpoint in meta["checkpoints"]:
        step, file = checkpoint["step"], checkpoint["file"]
        sim.step(step - current)
        current = step
        with Image.open(case_dir / file) as img:
            expected = image_to_state(family, img)
        assert np.array_equal(sim.state, expected), (
            f"{family}/{case_dir.name}: state mismatch at step {step}"
        )
