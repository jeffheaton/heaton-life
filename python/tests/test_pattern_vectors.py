"""Pattern conformance: replay vectors/patterns/ — RLE dialects, transforms,
extract and stamp semantics. Bit-exact; the same files the .NET/Unity suites replay."""

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from heaton_life.init import extract, flip_h, flip_v, rle_decode, rle_encode, rotate90, stamp

VECTOR_ROOT = Path(__file__).resolve().parents[2] / "vectors" / "patterns"

CASES = sorted(VECTOR_ROOT.glob("*/params.json"))


def _png(path: Path) -> np.ndarray:
    with Image.open(path) as img:
        return np.asarray(img.convert("L"))


def test_pattern_vectors_exist() -> None:
    kinds = {json.loads(c.read_text())["kind"] for c in CASES}
    assert kinds == {"rle", "transform", "stamp", "extract"}


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.parent.name)
def test_pattern_vector(case: Path) -> None:
    meta = json.loads(case.read_text())
    assert meta["tier"] == "bit-exact"
    kind = meta["kind"]
    if kind == "rle":
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
            grid, pattern, meta["x"], meta["y"],
            torus=meta["torus"], transparent=meta["transparent"],
        )
        assert np.array_equal(grid, _png(case.parent / meta["expected"]["file"]))
    else:  # extract
        grid = _png(case.parent / meta["grid"]["file"])
        region = extract(
            grid, meta["x"], meta["y"], meta["width"], meta["height"], torus=meta["torus"]
        )
        assert np.array_equal(region, _png(case.parent / meta["expected"]["file"]))
