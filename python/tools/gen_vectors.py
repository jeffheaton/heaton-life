#!/usr/bin/env python3
"""Regenerate the golden conformance vectors in ../../vectors/.

Run only when a spec change justifies it; vectors are the cross-language contract.
(vectors/mergelife-upstream/ is NOT generated here — it tracks the upstream repo.)
Usage: .venv/bin/python tools/gen_vectors.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from heaton_life.ca import LifeLike, Wireworld, wireworld_from_text
from heaton_life.conformance import build_sim, state_to_image
from heaton_life.core.protocols import Simulation
from heaton_life.init import place, rle_decode

SPEC_VERSION = "0.1.0"
REPO_ROOT = Path(__file__).resolve().parents[2]
VECTOR_ROOT = REPO_ROOT / "vectors"

GLIDER_RLE = "x = 3, y = 3, rule = B3/S23\nbob$2bo$3o!"


def write_case(family: str, name: str, sim: Simulation, steps: list[int]) -> None:
    case_dir = VECTOR_ROOT / family / name
    case_dir.mkdir(parents=True, exist_ok=True)
    checkpoints = []
    current = 0
    for step in steps:
        sim.step(step - current)
        current = step
        file = f"state_{step:05d}.png"
        state_to_image(family, np.asarray(sim.state)).save(case_dir / file)
        checkpoints.append({"step": step, "file": file})
    meta = {
        "spec_version": SPEC_VERSION,
        "family": family,
        "tier": "bit-exact",
        "params": sim.params.to_dict(),  # type: ignore[attr-defined]
        "checkpoints": checkpoints,
    }
    (case_dir / "params.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    print(f"wrote {case_dir.relative_to(REPO_ROOT)} (steps {steps})")


def main() -> None:
    # -- lifelike ------------------------------------------------------------------
    pattern, _ = rle_decode(GLIDER_RLE)
    glider = LifeLike("B3/S23", size=(16, 16), init=place(pattern, (16, 16), at=(0, 0)))
    write_case("lifelike", "glider-16-torus", glider, [0, 32, 64])

    lifelike_cases = [
        ("soup-64-torus", {"rule": "B3/S23", "density": 0.35, "seed": 42}),
        ("soup-64-dead", {"rule": "B3/S23", "density": 0.35, "seed": 7, "boundary": "dead"}),
        ("highlife-64-torus", {"rule": "B36/S23", "density": 0.4, "seed": 11}),
    ]
    for name, overrides in lifelike_cases:
        params = {"width": 64, "height": 64, **overrides}
        write_case("lifelike", name, build_sim("lifelike", params), [0, 1, 10, 100])

    # -- elementary ----------------------------------------------------------------
    write_case(
        "elementary",
        "rule30-single-128",
        build_sim("elementary", {"rule": 30, "width": 128, "height": 64, "init": "single"}),
        [0, 1, 64, 127],
    )
    write_case(
        "elementary",
        "rule110-soup-128",
        build_sim(
            "elementary",
            {"rule": 110, "width": 128, "height": 64, "init": "soup", "seed": 42},
        ),
        [0, 1, 64, 127],
    )
    write_case(
        "elementary",
        "rule90-dead-128",
        build_sim(
            "elementary",
            {"rule": 90, "width": 128, "height": 64, "init": "single", "boundary": "dead"},
        ),
        [0, 1, 64, 127],
    )

    # -- cyclic --------------------------------------------------------------------
    write_case(
        "cyclic",
        "demons-64",
        build_sim("cyclic", {"states": 14, "width": 64, "height": 64, "seed": 42}),
        [0, 1, 10, 50],
    )
    write_case(
        "cyclic",
        "r2t5-vonneumann-64",
        build_sim(
            "cyclic",
            {
                "states": 6,
                "threshold": 2,
                "reach": 2,
                "neighborhood": "vonneumann",
                "width": 64,
                "height": 64,
                "seed": 9,
            },
        ),
        [0, 1, 10, 50],
    )

    # -- wireworld -----------------------------------------------------------------
    write_case(
        "wireworld",
        "clock-16",
        build_sim("wireworld", {"width": 16, "height": 16, "init": "clock"}),
        [0, 1, 10, 40],
    )
    # Two parallel wires converging on one cell: exercises the 1-or-2-heads rule.
    junction = wireworld_from_text(
        "TH########.\n"
        "..........#\n"
        "TH########.\n"
    )
    grid = place(junction, (16, 8), at=(1, 2))
    write_case("wireworld", "junction-16", Wireworld(size=(16, 8), init=grid), [0, 1, 5, 20])

    # -- mergelife -----------------------------------------------------------------
    write_case(
        "mergelife",
        "redworld-48",
        build_sim(
            "mergelife",
            {
                "genome": "e542-5f79-9341-f31e-6c6b-7f08-8773-7068",
                "width": 48,
                "height": 48,
                "seed": 5,
            },
        ),
        [0, 1, 10, 50],
    )

    print("done")


if __name__ == "__main__":
    main()
