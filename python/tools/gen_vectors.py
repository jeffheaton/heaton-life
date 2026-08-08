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
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from heaton_life.ca import LifeLike, Wireworld, wireworld_from_text
from heaton_life.conformance import CODECS, TIERS, build_sim
from heaton_life.core.bignum import reference_orbit
from heaton_life.core.protocols import Simulation
from heaton_life.core.viewport import Viewport
from heaton_life.fractal import BurningShip, Julia, Mandelbrot, Newton
from heaton_life.init import place, rle_decode

SPEC_VERSION = "0.2.0"
REPO_ROOT = Path(__file__).resolve().parents[2]
VECTOR_ROOT = REPO_ROOT / "vectors"

GLIDER_RLE = "x = 3, y = 3, rule = B3/S23\nbob$2bo$3o!"


def write_case(family: str, name: str, sim: Simulation, steps: list[int]) -> None:
    codec = CODECS[family]
    tier, epsilon = TIERS[family]
    case_dir = VECTOR_ROOT / family / name
    case_dir.mkdir(parents=True, exist_ok=True)
    checkpoints: list[dict[str, Any]] = []
    current = 0
    for step in steps:
        sim.step(step - current)
        current = step
        state = np.asarray(sim.state)
        file = f"state_{step:05d}.{codec.ext}"
        (case_dir / file).write_bytes(codec.encode(state))
        entry: dict[str, Any] = {"step": step, "file": file}
        if codec.ext == "f64":
            entry["shape"] = list(state.shape)
        checkpoints.append(entry)
    meta: dict[str, Any] = {
        "spec_version": SPEC_VERSION,
        "family": family,
        "tier": tier,
        "params": sim.params.to_dict(),  # type: ignore[attr-defined]
        "checkpoints": checkpoints,
    }
    if epsilon is not None:
        meta["epsilon"] = epsilon
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

    # -- grayscott -----------------------------------------------------------------
    write_case(
        "grayscott",
        "mitosis-center-64",
        build_sim(
            "grayscott",
            {"feed": 0.0367, "kill": 0.0649, "width": 64, "height": 64, "init": "center"},
        ),
        [0, 1, 100, 500],
    )
    write_case(
        "grayscott",
        "coral-spots-64",
        build_sim(
            "grayscott",
            {"feed": 0.0545, "kill": 0.062, "width": 64, "height": 64, "seed": 3},
        ),
        [0, 1, 100, 500],
    )

    # -- lenia ---------------------------------------------------------------------
    write_case(
        "lenia-classic",
        "blobs-64",
        build_sim("lenia-classic", {"width": 64, "height": 64, "seed": 7}),
        [0, 1, 10, 50],
    )
    write_case(
        "lenia-asymptotic",
        "blobs-64",
        build_sim("lenia-asymptotic", {"width": 64, "height": 64, "seed": 7}),
        [0, 1, 10, 50],
    )
    write_case(
        "lenia-flow",
        "soup-64",
        build_sim("lenia-flow", {"width": 64, "height": 64, "seed": 7}),
        [0, 1, 10, 50],
    )

    # -- fractals (one-shot renders: params + viewport + int32 outputs) --------------
    write_fractal_case(
        "mandelbrot", "home-64",
        Mandelbrot(max_iter=500),
        {"max_iter": 500, "escape_radius": 1000.0},
        Viewport("-0.5", "0.0", 0.0), (64, 64),
    )
    write_fractal_case(
        "mandelbrot", "deep-zoom14-48",
        Mandelbrot(max_iter=5000),
        {"max_iter": 5000, "escape_radius": 1000.0},
        Viewport(
            "-0.743643887037158704752191506114774",
            "0.131825904205311970493132056385139",
            14.0,
        ),
        (48, 48),
        orbit_kind="mandelbrot",
    )
    write_fractal_case(
        "julia", "classic-64",
        Julia(max_iter=500),
        {"c_re": -0.7269, "c_im": 0.1889, "max_iter": 500, "escape_radius": 1000.0},
        Viewport("0.0", "0.0", 0.0), (64, 64),
    )
    write_fractal_case(
        "burning-ship", "home-64",
        BurningShip(max_iter=500),
        {"max_iter": 500, "escape_radius": 1000.0},
        Viewport("-0.5", "-0.5", -0.2), (64, 64),
    )
    write_fractal_case(
        "newton", "z3-64",
        Newton(degree=3, max_iter=60),
        {"degree": 3, "max_iter": 60},
        Viewport("0.0", "0.0", -0.1), (64, 64),
    )

    print("done")


def write_fractal_case(
    family: str,
    name: str,
    field: Any,
    params: dict[str, Any],
    viewport: Viewport,
    size: tuple[int, int],
    orbit_kind: str | None = None,
) -> None:
    case_dir = VECTOR_ROOT / family / name
    case_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for kind, grid in field.outputs(size, viewport).items():
        file = f"{kind}.i32"
        (case_dir / file).write_bytes(np.ascontiguousarray(grid, dtype="<i4").tobytes())
        outputs.append({"kind": kind, "file": file, "shape": list(grid.shape)})
    meta: dict[str, Any] = {
        "spec_version": SPEC_VERSION,
        "family": family,
        "tier": "bit-exact",
        "params": params,
        "viewport": viewport.to_dict(),
        "size": list(size),
        "outputs": outputs,
    }
    if orbit_kind is not None:
        orbit = reference_orbit(
            orbit_kind, viewport.center_re, viewport.center_im,
            viewport.zoom_log10, params["max_iter"],
        )
        (case_dir / "orbit.c128").write_bytes(
            np.ascontiguousarray(orbit, dtype="<c16").tobytes()
        )
        meta["reference_orbit"] = {"file": "orbit.c128", "length": len(orbit)}
    (case_dir / "params.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    print(f"wrote {case_dir.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
