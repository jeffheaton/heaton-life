"""Conformance runner: replays every case in vectors/ and compares states exactly.

The same vectors are (will be) consumed by the .NET implementation; discrete CA
families are bit-exact by spec.
"""

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from heaton_life.ca import LifeLike, LifeLikeParams

VECTOR_ROOT = Path(__file__).resolve().parents[2] / "vectors"
CASES = sorted(VECTOR_ROOT.glob("*/*/params.json"))


def load_state_png(path: Path) -> np.ndarray:
    with Image.open(path) as img:
        arr = np.asarray(img.convert("L"))
    return (arr > 0).astype(np.uint8)


def build_lifelike(meta: dict, case_dir: Path) -> LifeLike:
    params = LifeLikeParams.from_dict(meta["params"])
    if params.init == "array":
        first = case_dir / meta["checkpoints"][0]["file"]
        return LifeLike(
            params.rule,
            size=(params.width, params.height),
            init=load_state_png(first),
            boundary=params.boundary,  # type: ignore[arg-type]
        )
    return LifeLike.from_params(params)


BUILDERS = {"lifelike": build_lifelike}


def test_vectors_exist() -> None:
    assert CASES, f"no conformance vectors found under {VECTOR_ROOT}"


@pytest.mark.parametrize("case", CASES, ids=lambda p: f"{p.parent.parent.name}/{p.parent.name}")
def test_vector(case: Path) -> None:
    case_dir = case.parent
    meta = json.loads(case.read_text())
    family = meta["family"]
    assert family in BUILDERS, f"no builder registered for family {family!r}"
    sim = BUILDERS[family](meta, case_dir)

    current = 0
    for checkpoint in meta["checkpoints"]:
        step, file = checkpoint["step"], checkpoint["file"]
        sim.step(step - current)
        current = step
        expected = load_state_png(case_dir / file)
        assert np.array_equal(sim.state, expected), (
            f"{case_dir.name}: state mismatch at step {step}"
        )
