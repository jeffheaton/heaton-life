#!/usr/bin/env python3
"""Regenerate the golden conformance vectors in ../../vectors/.

Run only when a spec change justifies it; vectors are the cross-language contract.
Usage: .venv/bin/python tools/gen_vectors.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from heaton_life.ca import LifeLike, LifeLikeParams
from heaton_life.init import place, rle_decode

SPEC_VERSION = "0.1.0"
REPO_ROOT = Path(__file__).resolve().parents[2]
VECTOR_ROOT = REPO_ROOT / "vectors"

GLIDER_RLE = "x = 3, y = 3, rule = B3/S23\nbob$2bo$3o!"


def save_state(path: Path, state: np.ndarray) -> None:
    Image.fromarray(state * np.uint8(255), mode="L").save(path)


def write_case(family: str, name: str, sim: LifeLike, steps: list[int]) -> None:
    case_dir = VECTOR_ROOT / family / name
    case_dir.mkdir(parents=True, exist_ok=True)
    checkpoints = []
    current = 0
    for step in steps:
        sim.step(step - current)
        current = step
        file = f"state_{step:05d}.png"
        save_state(case_dir / file, sim.state)
        checkpoints.append({"step": step, "file": file})
    meta = {
        "spec_version": SPEC_VERSION,
        "family": family,
        "tier": "bit-exact",
        "params": sim.params.to_dict(),
        "checkpoints": checkpoints,
    }
    (case_dir / "params.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    print(f"wrote {case_dir.relative_to(REPO_ROOT)} (steps {steps})")


def main() -> None:
    # Glider on a 16x16 torus: returns to its exact starting position at step 64.
    pattern, _ = rle_decode(GLIDER_RLE)
    glider = LifeLike("B3/S23", size=(16, 16), init=place(pattern, (16, 16), at=(0, 0)))
    write_case("lifelike", "glider-16-torus", glider, [0, 32, 64])

    # Random soup, toroidal boundary.
    soup_torus = LifeLike.from_params(
        LifeLikeParams(rule="B3/S23", width=64, height=64, density=0.35, seed=42)
    )
    write_case("lifelike", "soup-64-torus", soup_torus, [0, 1, 10, 100])

    # Random soup, dead boundary — locks the boundary spec.
    soup_dead = LifeLike.from_params(
        LifeLikeParams(rule="B3/S23", width=64, height=64, density=0.35, seed=7, boundary="dead")
    )
    write_case("lifelike", "soup-64-dead", soup_dead, [0, 1, 10, 100])

    # HighLife soup — locks rulestring generality (replicators emerge from B36).
    highlife = LifeLike.from_params(
        LifeLikeParams(rule="B36/S23", width=64, height=64, density=0.4, seed=11)
    )
    write_case("lifelike", "highlife-64-torus", highlife, [0, 1, 10, 100])


if __name__ == "__main__":
    main()
