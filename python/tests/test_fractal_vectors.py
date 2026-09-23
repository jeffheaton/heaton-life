"""Fractal conformance runner: rebuilds each field and compares int32 outputs exactly.

Fractal vectors are one-shot renders (no time axis): params + viewport + declared
outputs. Deep-zoom cases also pin the reference orbit (of the viewport's reference
point when it names one, else of its center) — regeneration must match the stored
orbit bit-for-bit (the orbit is fixed-point integer arithmetic; plain ints and gmpy2
mpz are tested identical, so this holds with or without gmpy2).
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
    "burning-ship": lambda p: BurningShip(max_iter=p["max_iter"], escape_radius=p["escape_radius"]),
    "newton": lambda p: Newton(degree=p["degree"], max_iter=p["max_iter"]),
}

ORBIT_KINDS = {"mandelbrot": "mandelbrot", "julia": "julia", "burning-ship": "burning_ship"}

# Everything this runner understands. A key outside these sets fails the case rather
# than being skipped: a runner that ignored, say, "critical_orbit" would replay a deep
# Julia case the old way and either fail confusingly or pass for the wrong reason.
SPEC_VERSIONS = {"0.2.0", "0.3.0", "0.4.0", "0.6.0"}
TOP_KEYS = {
    "spec_version",
    "family",
    "tier",
    "params",
    "viewport",
    "size",
    "outputs",
    "reference_orbit",
    "critical_orbit",
    "source",
}
PARAM_KEYS = {
    "mandelbrot": {"max_iter", "escape_radius"},
    "julia": {"c_re", "c_im", "max_iter", "escape_radius"},
    "burning-ship": {"max_iter", "escape_radius"},
    "newton": {"degree", "max_iter"},
}
OUTPUT_KINDS = {"iterations", "roots", "status"}

CASES = sorted(p for p in VECTOR_ROOT.glob("*/*/params.json") if p.parent.parent.name in FIELDS)


def test_fractal_vectors_exist() -> None:
    families = {p.parent.parent.name for p in CASES}
    assert families == set(FIELDS), f"fractal families without vectors: {set(FIELDS) - families}"


@pytest.mark.parametrize("case", CASES, ids=lambda p: f"{p.parent.parent.name}/{p.parent.name}")
def test_fractal_vector(case: Path) -> None:
    case_dir = case.parent
    meta: dict[str, Any] = json.loads(case.read_text())
    family = meta["family"]
    unknown = set(meta) - TOP_KEYS
    assert not unknown, f"{case}: runner does not understand {sorted(unknown)}; teach it first"
    assert meta["spec_version"] in SPEC_VERSIONS, f"{case}: unknown spec_version"
    assert meta["tier"] == "bit-exact"
    assert set(meta["params"]) == PARAM_KEYS[family], f"{case}: unexpected params"
    assert "critical_orbit" not in meta or family == "julia"
    viewport_keys = {"center_re", "center_im", "zoom_log10"}
    if "reference_re" in meta["viewport"] or "reference_im" in meta["viewport"]:
        # An off-center reference (spec/deep-zoom.md) arrived in 0.4.0; an older runner
        # would iterate the center instead and replay the case wrongly.
        assert meta["spec_version"] == "0.4.0", f"{case}: reference in a pre-0.4.0 case"
        viewport_keys |= {"reference_re", "reference_im"}
    assert set(meta["viewport"]) == viewport_keys, f"{case}: unexpected viewport keys"
    for key in ("reference_orbit", "critical_orbit"):
        if key in meta:
            assert set(meta[key]) == {"file", "length"} and meta[key]["file"].endswith(".c128")
    for output in meta["outputs"]:
        assert set(output) == {"kind", "file", "shape"}, f"{case}: unexpected output keys"
        assert output["kind"] in OUTPUT_KINDS and output["file"].endswith(".i32"), (
            f"{case}: runner does not understand output {output}"
        )
        assert output["shape"] == [meta["size"][1], meta["size"][0]], "size is [w, h]"
    field = FIELDS[family](meta["params"])
    viewport = Viewport.from_dict(meta["viewport"])
    size = (meta["size"][0], meta["size"][1])

    produced = dict(field.outputs(size, viewport))
    if any(output["kind"] == "status" for output in meta["outputs"]):
        # spec/fractals.md "Status" (0.6.0): how each count was decided.
        assert meta["spec_version"] == "0.6.0", f"{case}: status in a pre-0.6.0 case"
        produced["status"] = field.counts_and_status(size, viewport)[1]  # type: ignore[attr-defined]
    for output in meta["outputs"]:
        expected = np.frombuffer((case_dir / output["file"]).read_bytes(), dtype="<i4").reshape(
            tuple(output["shape"])
        )
        got = produced[output["kind"]]
        assert np.array_equal(got, expected), f"{family}/{case_dir.name}: {output['kind']} mismatch"

    if "reference_orbit" in meta:
        stored = np.frombuffer(
            (case_dir / meta["reference_orbit"]["file"]).read_bytes(), dtype="<c16"
        )
        assert len(stored) == meta["reference_orbit"]["length"]
        # The orbit belongs to the reference point, which is the center unless the
        # viewport names another.
        regenerated = reference_orbit(
            ORBIT_KINDS[family],
            *viewport.orbit_center,
            viewport.zoom_log10,
            meta["params"]["max_iter"],
            c_re=meta["params"].get("c_re", 0.0),
            c_im=meta["params"].get("c_im", 0.0),
        )
        assert np.array_equal(stored, regenerated), (
            "reference orbit regeneration diverged from the stored contract"
        )

    if "critical_orbit" in meta:
        # Julia's rebase target: the critical orbit (z0 = 0), same c and precision.
        stored = np.frombuffer(
            (case_dir / meta["critical_orbit"]["file"]).read_bytes(), dtype="<c16"
        )
        assert len(stored) == meta["critical_orbit"]["length"]
        regenerated = reference_orbit(
            "julia",
            "0",
            "0",
            viewport.zoom_log10,
            meta["params"]["max_iter"],
            c_re=meta["params"]["c_re"],
            c_im=meta["params"]["c_im"],
        )
        assert np.array_equal(stored, regenerated), (
            "critical orbit regeneration diverged from the stored contract"
        )
