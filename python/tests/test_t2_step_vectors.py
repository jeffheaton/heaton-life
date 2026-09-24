"""T2 step conformance runner (spec/deep-zoom.md "T2"): the per-pixel loop on crafted
orbits and pixels, every output bit for bit -- the rare paths no natural frame reaches.
Strict: an unknown key fails the case, and every path a case names must run."""

import json
import struct
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from heaton_life.core import floatexp as fx
from heaton_life.core.bignum import OrbitX, SmallSamples
from heaton_life.fractal.bla import build_table_t2, table_words_x
from heaton_life.fractal.perturbation_t2 import XPair, perturb_t2

ROOT = Path(__file__).resolve().parents[2] / "vectors" / "t2-steps"
CASES = sorted(p.name for p in ROOT.iterdir() if p.is_dir())
KEYS = {
    "spec_version",
    "family",
    "tier",
    "orbit",
    "rebase_orbit",
    "delta0",
    "delta_c",
    "derivative",
    "max_iter",
    "escape_radius",
    "paths",
    "expected",
}


def _double(bits: str) -> float:
    return float(struct.unpack("<d", struct.pack("<Q", int(bits, 16)))[0])


def _bits(value: float) -> str:
    return f"0x{struct.unpack('<Q', struct.pack('<d', value))[0]:016X}"


def _x(pair: list[Any]) -> fx.X:
    return _double(pair[0]), int(pair[1])


def _orbit(data: dict[str, Any]) -> OrbitX:
    assert set(data) == {"samples", "small"}
    rows = data["small"]
    return OrbitX(
        np.array([complex(_double(r), _double(i)) for r, i in data["samples"]]),
        SmallSamples(
            np.array([row[0] for row in rows], dtype=np.int64),
            np.array([_double(row[1]) for row in rows], dtype=np.float64),
            np.array([row[2] for row in rows], dtype=np.int64),
            np.array([_double(row[3]) for row in rows], dtype=np.float64),
            np.array([row[4] for row in rows], dtype=np.int64),
        ),
    )


def _pair(data: list[Any] | None) -> XPair | None:
    if data is None:
        return None
    (rm, re), (im, ie) = _x(data[0]), _x(data[1])
    return XPair(
        np.array([rm]),
        np.array([re], dtype=np.int64),
        np.array([im]),
        np.array([ie], dtype=np.int64),
    )


def test_every_case_is_listed() -> None:
    assert CASES == [
        "bla-branch-order",
        "bla-complex-skip",
        "bla-dc-bad",
        "bla-dc-left-child",
        "bla-dead-before-merge",
        "bla-dead-rules",
        "bla-deep-radius",
        "bla-loop-end",
        "bla-radius-tie",
        "delta-gap",
        "derivative-gap",
        "final-inf-imaginary",
        "final-inf-real",
        "huge-sample",
        "loop-end",
    ]


@pytest.mark.parametrize("name", CASES)
def test_t2_step(name: str) -> None:
    meta = json.loads((ROOT / name / "params.json").read_text())
    assert set(meta) - {"bla"} == KEYS
    assert (meta["spec_version"], meta["family"], meta["tier"]) == (
        "0.10.0",
        "t2-steps",
        "bit-exact",
    )
    orbit = _orbit(meta["orbit"])
    rebase = None if meta["rebase_orbit"] is None else _orbit(meta["rebase_orbit"])
    derivative = None
    if meta["derivative"] is not None:
        assert set(meta["derivative"]) == {"d0", "add"}
        add = meta["derivative"]["add"]
        derivative = (_pair(meta["derivative"]["d0"]), None if add is None else _x(add))
    table = None
    if "bla" in meta:
        # BLA at T2 (spec/deep-zoom.md "BLA at T2"): the table from the crafted orbit.
        assert set(meta["bla"]) == {"dc_exponent"} and meta["rebase_orbit"] is None
        samples = orbit.samples[: meta["max_iter"] + 1]
        small = np.zeros(samples.size, dtype=bool)
        small[orbit.small.index[orbit.small.index < samples.size]] = True
        table = build_table_t2(samples, small, meta["escape_radius"], meta["bla"]["dc_exponent"])
    stats: dict[str, int] = {}
    result = perturb_t2(
        orbit,
        _pair(meta["delta0"]),
        _pair(meta["delta_c"]),
        meta["max_iter"],
        meta["escape_radius"],
        rebase_orbit=rebase,
        derivative=derivative,  # type: ignore[arg-type]
        stats=stats,
        table=table,
    )
    for path in meta["paths"]:
        assert stats.get(path, 0) > 0, f"{path} never ran"
    expected = meta["expected"]
    extra = {"applications", "table"} if table is not None else set()
    assert set(expected) == {"count", "final", "derivative"} | extra
    assert int(result.counts[0]) == expected["count"]
    assert [_bits(result.final[0].real), _bits(result.final[0].imag)] == expected["final"]
    got = [_bits(float(result.dr[0])), _bits(float(result.di[0])), int(result.d_exponent[0])]
    assert got == expected["derivative"]
    if table is not None:
        assert int(result.applications[0]) == expected["applications"]
        # Every NaN equals every NaN (spec/fractals.md, tables): a dead entry's overflowed
        # coefficient is NaN, and the sign of a default NaN depends on the platform.
        want = np.array([_double(w) for w in expected["table"]])
        assert np.array_equal(table_words_x(table), want, equal_nan=True)
        got_bits = [_bits(float(w)) for w in table_words_x(table)]
        numbers = ~np.isnan(want)  # and every other word bit for bit (-0.0 included)
        assert [g for g, keep in zip(got_bits, numbers, strict=True) if keep] == [
            b for b, keep in zip(expected["table"], numbers, strict=True) if keep
        ]


RARE_PATHS = {
    "slow_small",
    "slow_gap",
    "renormalize",
    "floor",
    "escape_small",
    "rebase_small",
    "rebase_normal",
    "d_slow_small",
    "d_slow_gap",
    "bla_skip",
    "bla_skip_escape",  # a skip that lands on an escape
    "bla_skip_small",  # a skip that lands on a small index
}


def test_every_rare_path_runs_in_some_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each branch a port must get bit for bit is exercised by some 0.10.0 vector: the
    T2 render frames (replayed with the distance estimate, so the derivative's branches
    run too) and the crafted step cases together."""
    from heaton_life.core.viewport import Viewport
    from heaton_life.fractal import Julia, Mandelbrot, escape_fields

    stats: dict[str, int] = {}

    def counted(*args: Any, **kwargs: Any) -> Any:
        return perturb_t2(*args, **{**kwargs, "stats": stats})

    monkeypatch.setattr(escape_fields, "perturb_t2", counted)
    vectors = Path(__file__).resolve().parents[2] / "vectors"
    for case in sorted(vectors.glob("*/t2-*/params.json")):
        meta = json.loads(case.read_text())
        p, v = meta["params"], meta["viewport"]
        viewport = Viewport.from_dict(v)
        field = (
            Julia(c=complex(p["c_re"], p["c_im"]), max_iter=p["max_iter"])
            if meta["family"] == "julia"
            else Mandelbrot(max_iter=p["max_iter"], bla=bool(p.get("bla", False)))
        )
        field.fields(tuple(meta["outputs"][0]["shape"][::-1]), viewport, distance=True)
    for name in CASES:
        test_t2_step(name)
        meta = json.loads((ROOT / name / "params.json").read_text())
        for path in meta["paths"]:
            stats[path] = stats.get(path, 0) + 1
    assert {path for path in RARE_PATHS if stats.get(path, 0) == 0} == set()
    assert set(stats) <= RARE_PATHS
