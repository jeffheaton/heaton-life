"""Fractal conformance runner: rebuilds each field and compares int32 outputs exactly.

Fractal vectors are one-shot renders (no time axis): params + viewport + declared
outputs. Deep-zoom cases also pin the reference orbit — regeneration must match the
stored orbit bit-for-bit (gmpy2 and mpmath are tested identical, so this holds for
either backend).
"""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from heaton_life.core.bignum import reference_orbit
from heaton_life.core.viewport import Viewport
from heaton_life.fractal import BurningShip, Julia, Mandelbrot, Newton

VECTOR_ROOT = Path(__file__).resolve().parents[2] / "vectors"

FIELDS = {
    "mandelbrot": lambda p: Mandelbrot(max_iter=p["max_iter"], escape_radius=p["escape_radius"]),
    "julia": lambda p: Julia(
        c=complex(p["c_re"], p["c_im"]),
        max_iter=p["max_iter"],
        escape_radius=p["escape_radius"],
    ),
    "burning-ship": lambda p: BurningShip(
        max_iter=p["max_iter"], escape_radius=p["escape_radius"]
    ),
    "newton": lambda p: Newton(degree=p["degree"], max_iter=p["max_iter"]),
}

ORBIT_KINDS = {"mandelbrot": "mandelbrot", "julia": "julia", "burning-ship": "burning_ship"}

CASES = sorted(
    p for p in VECTOR_ROOT.glob("*/*/params.json") if p.parent.parent.name in FIELDS
)


def test_fractal_vectors_exist() -> None:
    families = {p.parent.parent.name for p in CASES}
    assert families == set(FIELDS), f"fractal families without vectors: {set(FIELDS) - families}"


@pytest.mark.parametrize("case", CASES, ids=lambda p: f"{p.parent.parent.name}/{p.parent.name}")
def test_fractal_vector(case: Path) -> None:
    case_dir = case.parent
    meta: dict[str, Any] = json.loads(case.read_text())
    family = meta["family"]
    field = FIELDS[family](meta["params"])
    viewport = Viewport.from_dict(meta["viewport"])
    size = (meta["size"][0], meta["size"][1])

    produced = field.outputs(size, viewport)
    for output in meta["outputs"]:
        expected = (
            np.frombuffer((case_dir / output["file"]).read_bytes(), dtype="<i4")
            .reshape(tuple(output["shape"]))
        )
        got = produced[output["kind"]]
        assert np.array_equal(got, expected), (
            f"{family}/{case_dir.name}: {output['kind']} mismatch"
        )

    if "reference_orbit" in meta:
        stored = np.frombuffer(
            (case_dir / meta["reference_orbit"]["file"]).read_bytes(), dtype="<c16"
        )
        regenerated = reference_orbit(
            ORBIT_KINDS[family],
            viewport.center_re,
            viewport.center_im,
            viewport.zoom_log10,
            meta["params"]["max_iter"],
            c_re=meta["params"].get("c_re", 0.0),
            c_im=meta["params"].get("c_im", 0.0),
        )
        assert np.array_equal(stored, regenerated), (
            "reference orbit regeneration diverged from the stored contract"
        )
