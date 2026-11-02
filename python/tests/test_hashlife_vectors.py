"""HashLife conformance: replay vectors/hashlife/ — evolution checkpoints, Macrocell and
RLE reading and canonical writing, and edit sequences. Every state is compared through its
canonical Macrocell text (spec/macrocell.md), bit-exact. The .NET suite replays the same
files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from heaton_life.ca.hashlife import (
    HashLife,
    LifeView,
    cell_at,
    center_cell,
    centered,
    fit,
    pan,
    zoom_at,
)

VECTOR_ROOT = Path(__file__).resolve().parents[2] / "vectors" / "hashlife"
CASES = sorted(VECTOR_ROOT.glob("*/params.json"))
SPEC_VERSIONS = {"0.14.0"}
_COMMON = {"spec_version", "family", "tier", "kind"}
_STATE = {"generation", "population", "bounding_box"}
_KEYS = {
    "evolve": _COMMON | {"input", "checkpoints"},
    "macrocell": _COMMON
    | {"input", "error", "rle", "rle_error", "state", "state_sha256", "state_lines"}
    | _STATE,
    "rle": _COMMON | {"input", "error", "rle", "state", "state_sha256", "state_lines"} | _STATE,
    "edit": _COMMON | {"rule", "ops", "state", "state_sha256", "state_lines"} | _STATE,
    "view": _COMMON | {"operations"},
    "render": _COMMON | {"input", "generation", "frames"},
}


def _expect_state(case_dir: Path, u: HashLife, entry: dict[str, Any]) -> None:
    assert str(u.generation) == entry["generation"]
    assert str(u.population) == entry["population"]
    box = u.bounding_box()
    assert (None if box is None else [str(v) for v in box]) == entry["bounding_box"]
    text = u.to_macrocell()
    if "state" in entry:
        assert text == (case_dir / entry["state"]).read_text()
    else:
        assert text.count("\n") == entry["state_lines"]
        assert hashlib.sha256(text.encode("ascii")).hexdigest() == entry["state_sha256"]


def _apply(u: HashLife, op: dict[str, Any]) -> None:
    kind = op["op"]
    if kind == "set_cell":
        u.set_cell(op["x"], op["y"], op["alive"])
    elif kind == "set_rect":
        cells = np.array([[c == "*" for c in row] for row in op["cells"]], np.uint8)
        u.set_rect(op["x"], op["y"], cells, op["mode"])
    elif kind == "clear_rect":
        u.clear_rect(op["x0"], op["y0"], op["x1"], op["y1"])
    elif kind == "fill_random":
        u.fill_random(op["x0"], op["y0"], op["x1"], op["y1"], op["density"], op["seed"])
    elif kind == "step":
        u.step(int(op["n"]))
    elif kind == "clear":
        u.clear()
    else:
        raise AssertionError(f"unknown op {kind!r}")


def _view(fields: list[Any]) -> LifeView:
    return LifeView(int(fields[0]), int(fields[1]), fields[2])


def _check_view_op(op: dict[str, Any]) -> None:
    kind = op["op"]
    if kind == "pan":
        got: tuple[Any, ...] = tuple(vars(pan(_view(op["view"]), op["dx"], op["dy"])).values())
    elif kind == "zoom_at":
        got = tuple(vars(zoom_at(_view(op["view"]), op["i"], op["j"], op["steps"])).values())
    elif kind == "cell_at":
        got = cell_at(_view(op["view"]), op["i"], op["j"])
    elif kind == "center_cell":
        got = center_cell(_view(op["view"]), tuple(op["size"]))
    elif kind == "centered":
        cx, cy = (int(c) for c in op["cell"])
        got = tuple(vars(centered(cx, cy, op["mag"], tuple(op["size"]))).values())
    elif kind == "fit":
        box = None if op["box"] is None else tuple(int(c) for c in op["box"])
        got = tuple(vars(fit(box, tuple(op["size"]))).values())  # type: ignore[arg-type]
    else:
        raise AssertionError(f"unknown view op {kind!r}")
    want = tuple(int(e) if isinstance(e, str) else e for e in op["expect"])
    assert got == want, op


def test_hashlife_vectors_exist() -> None:
    kinds = {json.loads(c.read_text())["kind"] for c in CASES}
    assert kinds == set(_KEYS)


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.parent.name)
def test_hashlife_vector(case: Path) -> None:
    meta = json.loads(case.read_text())
    d = case.parent
    kind = meta["kind"]
    assert meta["family"] == "hashlife" and meta["tier"] == "bit-exact"
    assert meta["spec_version"] in SPEC_VERSIONS
    assert set(meta) <= _KEYS[kind], set(meta) - _KEYS[kind]
    if kind == "evolve":
        u = HashLife.from_file(d / meta["input"])
        for entry in meta["checkpoints"]:
            u.step(int(entry["generation"]) - u.generation)
            _expect_state(d, u, entry)
    elif kind in ("macrocell", "rle"):
        text = (d / meta["input"]).read_text()
        read = HashLife.from_macrocell if kind == "macrocell" else HashLife.from_rle
        if meta.get("error"):
            with pytest.raises(ValueError):
                read(text)
            return
        u = read(text)
        _expect_state(d, u, meta)
        if meta.get("rle_error"):
            with pytest.raises(ValueError, match="Macrocell"):
                u.to_rle()
        else:
            assert u.to_rle() == (d / meta["rle"]).read_text()
    elif kind == "view":
        for op in meta["operations"]:
            _check_view_op(op)
    elif kind == "render":
        u = HashLife.from_file(d / meta["input"])
        u.step(int(meta["generation"]) - u.generation)
        for frame in meta["frames"]:
            got = u.render(_view(frame["view"]), tuple(frame["size"]), frame["mode"])
            with Image.open(d / frame["file"]) as img:
                assert np.array_equal(got, np.asarray(img.convert("L"))), frame
    else:  # edit
        u = HashLife(meta["rule"])
        for op in meta["ops"]:
            if op.get("error"):
                before = u.to_macrocell()
                with pytest.raises(ValueError, match="editing box"):
                    _apply(u, op)
                assert u.to_macrocell() == before
            else:
                _apply(u, op)
        _expect_state(d, u, meta)
