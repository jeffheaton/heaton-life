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
    "mandelbrot": lambda p: Mandelbrot(
        max_iter=p["max_iter"], escape_radius=p["escape_radius"], bla=p.get("bla", False)
    ),
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
SPEC_VERSIONS = {"0.2.0", "0.3.0", "0.4.0", "0.6.0", "0.7.0", "0.8.0"}
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
OUTPUT_KINDS = {"iterations", "roots", "status", "distance", "bla_applications"}
BLA_FAMILIES = {"mandelbrot"}
DISTANCE_FAMILIES = {"mandelbrot", "julia"}


def _version(text: str) -> tuple[int, ...]:
    """spec_version as integers, so "0.10.0" sorts after "0.4.0"."""
    return tuple(int(part) for part in text.split("."))


def assert_relative(got: np.ndarray, want: np.ndarray, epsilon: float, what: str) -> None:
    """spec/fractals.md "Distance estimate": NaN, 0 and +-inf positions match exactly;
    elsewhere |got - want| <= epsilon * |want|."""
    special_want = ~np.isfinite(want) | (want == 0)
    special_got = ~np.isfinite(got) | (got == 0)
    assert np.array_equal(special_want, special_got), f"{what}: NaN/0/inf positions differ"
    assert np.array_equal(got[special_want], want[special_want], equal_nan=True), what
    finite = ~special_want
    assert np.all(np.abs(got[finite] - want[finite]) <= epsilon * np.abs(want[finite])), what


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
    params = set(meta["params"])
    bla = bool(meta["params"].get("bla", False))
    if "bla" in params:
        # spec/deep-zoom.md "BLA" (0.8.0): an algorithm parameter, Mandelbrot only.
        assert family in BLA_FAMILIES, f"{case}: {family} has no BLA"
        assert isinstance(meta["params"]["bla"], bool), f"{case}: bla must be a bool"
        assert _version(meta["spec_version"]) >= (0, 8, 0), f"{case}: bla before 0.8.0"
        params.discard("bla")
    assert params == PARAM_KEYS[family], f"{case}: unexpected params"
    assert "critical_orbit" not in meta or family == "julia"
    viewport_keys = {"center_re", "center_im", "zoom_log10"}
    if "reference_re" in meta["viewport"] or "reference_im" in meta["viewport"]:
        # An off-center reference (spec/deep-zoom.md) arrived in 0.4.0; an older runner
        # would iterate the center instead and replay the case wrongly.
        assert _version(meta["spec_version"]) >= (0, 4, 0), f"{case}: reference before 0.4.0"
        viewport_keys |= {"reference_re", "reference_im"}
    assert set(meta["viewport"]) == viewport_keys, f"{case}: unexpected viewport keys"
    for key in ("reference_orbit", "critical_orbit"):
        if key in meta:
            assert set(meta[key]) == {"file", "length"} and meta[key]["file"].endswith(".c128")
    for output in meta["outputs"]:
        if output["kind"] == "distance":
            # spec/fractals.md "Distance estimate" (0.7.0): float64, relative epsilon.
            assert set(output) == {"kind", "file", "shape", "relative_epsilon"}, case
            assert output["file"].endswith(".f64"), case
            assert _version(meta["spec_version"]) >= (0, 7, 0), f"{case}: distance before 0.7.0"
            assert family in DISTANCE_FAMILIES, f"{case}: {family} has no distance estimate"
        else:
            assert set(output) == {"kind", "file", "shape"}, f"{case}: unexpected output keys"
            assert output["kind"] in OUTPUT_KINDS and output["file"].endswith(".i32"), (
                f"{case}: runner does not understand output {output}"
            )
        assert output["shape"] == [meta["size"][1], meta["size"][0]], "size is [w, h]"
    field = FIELDS[family](meta["params"])
    viewport = Viewport.from_dict(meta["viewport"])
    size = (meta["size"][0], meta["size"][1])

    produced = dict(field.outputs(size, viewport))
    kinds = {output["kind"] for output in meta["outputs"]}
    if "status" in kinds:
        # spec/fractals.md "Status" (0.6.0): how each count was decided.
        assert _version(meta["spec_version"]) >= (0, 6, 0), f"{case}: status before 0.6.0"
        produced["status"] = field.counts_and_status(size, viewport)[1]  # type: ignore[attr-defined]
    if "distance" in kinds or "bla_applications" in kinds:
        # The distance loop is its own code path: its counts and statuses must be the
        # other paths' exactly, so they are checked against the same files.
        fields = field.fields(  # type: ignore[attr-defined]
            size,
            viewport,
            status="status" in kinds,
            distance="distance" in kinds,
            bla_applications="bla_applications" in kinds,
        )
        assert np.array_equal(fields.counts, produced["iterations"]), f"{case}: fields counts"
        if fields.status is not None:
            assert np.array_equal(fields.status, produced["status"]), f"{case}: fields status"
        produced["distance"] = fields.distance
        produced["bla_applications"] = fields.bla_applications
    if "bla_applications" in kinds:
        # spec/deep-zoom.md "BLA": a BLA case must engage, or it pins nothing.
        assert bla and _version(meta["spec_version"]) >= (0, 8, 0), (
            f"{case}: applications without bla"
        )
        assert int(np.sum(produced["bla_applications"])) > 0, f"{case}: BLA never engaged"
    assert not bla or "bla_applications" in kinds, f"{case}: a BLA case records its applications"
    for output in meta["outputs"]:
        what = f"{family}/{case_dir.name}: {output['kind']}"
        if output["kind"] == "distance":
            expected_de = np.frombuffer((case_dir / output["file"]).read_bytes(), dtype="<f8")
            got_de = produced["distance"]
            assert_relative(got_de.ravel(), expected_de, output["relative_epsilon"], what)
            continue
        expected = np.frombuffer((case_dir / output["file"]).read_bytes(), dtype="<i4").reshape(
            tuple(output["shape"])
        )
        got = produced[output["kind"]]
        assert np.array_equal(got, expected), f"{what} mismatch"

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
