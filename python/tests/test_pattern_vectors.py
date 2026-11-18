"""Pattern conformance: replay vectors/patterns/ — RLE dialects, transforms,
extract and stamp semantics. Bit-exact; the same files the .NET suite replays."""

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from heaton_life.init import (
    extract,
    flip_h,
    flip_v,
    rle_decode,
    rle_encode,
    rle_measure,
    rotate90,
    stamp,
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
    }


def _decode(text: str, meta: dict, *, trim: bool = False):  # type: ignore[no-untyped-def, type-arg]
    """Decode under the case's limit: "default" (the spec's), a number, or null (lifted)."""
    if meta["limit"] == "default":
        return rle_decode(text, trim=trim)
    return rle_decode(text, trim=trim, max_cells=meta["limit"])


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
        assert np.array_equal(rotate90(grid), _png(case.parent / meta["outputs"]["rotate90"]))
        assert np.array_equal(flip_h(grid), _png(case.parent / meta["outputs"]["flip_h"]))
        assert np.array_equal(flip_v(grid), _png(case.parent / meta["outputs"]["flip_v"]))
    elif kind == "stamp":
        pattern = _png(case.parent / meta["pattern"]["file"])
        grid = np.full(
            (meta["grid_height"], meta["grid_width"]), meta["background"], dtype=np.uint8
        )
        stamp(
            grid,
            pattern,
            meta["x"],
            meta["y"],
            torus=meta["torus"],
            transparent=meta["transparent"],
        )
        assert np.array_equal(grid, _png(case.parent / meta["expected"]["file"]))
    else:  # extract
        grid = _png(case.parent / meta["grid"]["file"])
        region = extract(
            grid, meta["x"], meta["y"], meta["width"], meta["height"], torus=meta["torus"]
        )
        assert np.array_equal(region, _png(case.parent / meta["expected"]["file"]))
