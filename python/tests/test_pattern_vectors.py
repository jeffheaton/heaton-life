"""Pattern conformance: replay vectors/patterns/ — RLE dialects, transforms,
extract and stamp semantics. Bit-exact; the same files the .NET suite replays."""

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from heaton_life.ca import Cyclic, LargerThanLife, LifeLike, Wireworld
from heaton_life.ca.hashlife import EDIT_LIMIT, HashLife
from heaton_life.init import (
    extract,
    fill_random,
    flip_h,
    flip_v,
    rle_decode,
    rle_encode,
    rle_measure,
    rotate90,
    rotate90_ccw,
    stamp,
    turned_rect,
)

VECTOR_ROOT = Path(__file__).resolve().parents[2] / "vectors" / "patterns"

CASES = sorted(VECTOR_ROOT.glob("*/params.json"))


def _png(path: Path) -> np.ndarray:
    with Image.open(path) as img:
        return np.asarray(img.convert("L"))


def test_pattern_vectors_exist() -> None:
    kinds = {json.loads(c.read_text())["kind"] for c in CASES}
    assert kinds == {
        "rle",
        "transform",
        "stamp",
        "extract",
        "rle-extent",
        "rle-limit",
        "rle-trim",
        "fill-random",
        "advance",
        "turned-rect",
    }


def _decode(text: str, meta: dict, *, trim: bool = False):  # type: ignore[no-untyped-def, type-arg]
    """Decode under the case's limit: "default" (the spec's), a number, or null (lifted)."""
    if meta["limit"] == "default":
        return rle_decode(text, trim=trim)
    return rle_decode(text, trim=trim, max_cells=meta["limit"])


_TOPOLOGY = {"boundary", "shift", "axis"}


def _world(desc: dict, grid: np.ndarray):  # type: ignore[no-untyped-def, type-arg]
    """The world an ``advance`` case names: a family and its parameters, cells from ``grid``."""
    size = (grid.shape[1], grid.shape[0])
    family = desc["family"]
    # A topology's shift and axis appear only when they aren't 0 and "x" (spec/topology.md).
    topology = {k: desc[k] for k in ("boundary", "shift", "axis") if k in desc}
    if family == "lifelike":
        assert {"family", "rule", "boundary"} <= set(desc) <= {"family", "rule", *_TOPOLOGY}
        return LifeLike(desc["rule"], size=size, init=grid, **topology)
    if family == "wireworld":
        assert {"family", "boundary"} <= set(desc) <= {"family", *_TOPOLOGY}
        return Wireworld(size=size, init=grid, **topology)
    if family == "ltl":  # spec/ltl.md: every key of the topology written
        assert set(desc) == {"family", "rule", *_TOPOLOGY}
        return LargerThanLife(desc["rule"], size=size, init=grid, **topology)
    assert family == "cyclic"
    assert set(desc) == {"family", "states", "threshold", "reach", "neighborhood"}
    return Cyclic(
        desc["states"],
        size=size,
        threshold=desc["threshold"],
        reach=desc["reach"],
        neighborhood=desc["neighborhood"],
        init=grid,
    )


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.parent.name)
def test_pattern_vector(case: Path) -> None:
    meta = json.loads(case.read_text())
    assert meta["tier"] == "bit-exact"
    kind = meta["kind"]
    if kind == "rle-extent":
        extent, want = rle_measure((case.parent / meta["input"]).read_text()), meta["extent"]
        assert (extent.width, extent.height) == (int(want["width"]), int(want["height"]))
        live = None if want["live"] is None else tuple(int(v) for v in want["live"])
        assert (extent.live, extent.population) == (live, int(want["population"]))
        assert (extent.rule, extent.extended) == (want["rule"], want["extended"])
    elif kind == "rle-limit":
        text = (case.parent / meta["input"]).read_text()
        if meta.get("error"):
            with pytest.raises(ValueError):
                _decode(text, meta)
        else:
            grid, _ = _decode(text, meta)
            assert list(grid.shape) == meta["shape"]
            assert int(np.count_nonzero(grid)) == meta["population"]
    elif kind == "rle-trim":
        text = (case.parent / meta["input"]).read_text()
        if meta.get("error"):
            with pytest.raises(ValueError):
                _decode(text, meta, trim=True)
        else:
            grid, rule = _decode(text, meta, trim=True)
            assert rule == meta["rule"]
            assert np.array_equal(grid, _png(case.parent / meta["grid"]["file"]))
    elif kind == "rle":
        grid, rule = rle_decode((case.parent / meta["input"]).read_text())
        assert rule == meta["rule"]
        assert np.array_equal(grid, _png(case.parent / meta["grid"]["file"]))
        canonical = rle_encode(grid, rule=rule if rule is not None else "B3/S23")
        assert canonical == (case.parent / meta["canonical"]).read_text()
    elif kind == "transform":
        grid = _png(case.parent / meta["grid"]["file"])
        transforms = {
            "rotate90": rotate90,
            "rotate90_ccw": rotate90_ccw,
            "flip_h": flip_h,
            "flip_v": flip_v,
        }
        assert {"rotate90", "flip_h", "flip_v"} <= set(meta["outputs"]) <= set(transforms)
        for name, file in meta["outputs"].items():
            assert np.array_equal(transforms[name](grid), _png(case.parent / file)), name
    elif kind == "stamp":
        pattern = _png(case.parent / meta["pattern"]["file"])
        if "grid" in meta:  # spec 0.16.0: a background grid instead of one value
            grid = _png(case.parent / meta["grid"]["file"]).copy()
        else:
            grid = np.full(
                (meta["grid_height"], meta["grid_width"]), meta["background"], dtype=np.uint8
            )
        if "mode" in meta:
            mode = {"mode": meta["mode"]}
        else:
            mode = {"transparent": meta["transparent"]}
        if meta.get("error"):
            before = grid.copy()
            with pytest.raises(ValueError):
                stamp(grid, pattern, meta["x"], meta["y"], torus=meta["torus"], **mode)
            assert np.array_equal(grid, before)
            return
        stamp(grid, pattern, meta["x"], meta["y"], torus=meta["torus"], **mode)
        assert np.array_equal(grid, _png(case.parent / meta["expected"]["file"]))
    elif kind == "fill-random":
        grid = _png(case.parent / meta["grid"]["file"]).copy()
        before = grid.copy()
        region = meta["region"]
        if meta.get("error"):
            with pytest.raises(ValueError):
                fill_random(grid, *region, density=meta["density"], seed=meta["seed"])
            assert np.array_equal(grid, before)
            return
        fill_random(grid, *region, density=meta["density"], seed=meta["seed"])
        assert np.array_equal(grid, _png(case.parent / meta["expected"]["file"]))
    elif kind == "advance":
        grid = _png(case.parent / meta["grid"]["file"]).copy()
        world = _world(meta["world"], grid)
        advance = world.advance_outside if meta["outside"] else world.advance_selection
        if meta.get("error"):
            with pytest.raises(ValueError):
                advance(*meta["region"], meta["n"])
            assert np.array_equal(world.state, grid) and world.generation == 0
            return
        advance(*meta["region"], meta["n"])
        assert np.array_equal(world.state, _png(case.parent / meta["expected"]["file"]))
        assert world.generation == 0
    elif kind == "turned-rect":
        for entry in meta["cases"]:
            rect = tuple(int(v) for v in entry["rect"])
            clockwise = entry["clockwise"]
            if entry.get("error"):
                assert set(entry) == {"rect", "clockwise", "error"}
                with pytest.raises(ValueError):
                    turned_rect(*rect, clockwise=clockwise)
                continue
            assert set(entry) == {"rect", "clockwise", "expect"}
            expect = tuple(int(v) for v in entry["expect"])
            assert turned_rect(*rect, clockwise=clockwise) == expect, entry
            if all(abs(v) <= EDIT_LIMIT for v in rect + expect):  # the same as the universe's
                assert HashLife().rotate_rect(*rect, clockwise=clockwise) == expect, entry
    else:  # extract
        grid = _png(case.parent / meta["grid"]["file"])
        region = extract(
            grid, meta["x"], meta["y"], meta["width"], meta["height"], torus=meta["torus"]
        )
        assert np.array_equal(region, _png(case.parent / meta["expected"]["file"]))
