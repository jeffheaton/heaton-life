"""HashLife conformance: replay vectors/hashlife/ — evolution checkpoints, Macrocell and
RLE reading and canonical writing, edit sequences, and snapshot scripts (what snapshots
hold, releasing them, files read into a universe that exists). Every state is compared
through its canonical Macrocell text (spec/macrocell.md), bit-exact. The .NET suite replays
the same files."""

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
    Snapshot,
    cell_at,
    center_cell,
    centered,
    fit,
    frame_map,
    pan,
    resized,
    zoom_at,
)
from heaton_life.init import PatternMetadata

VECTOR_ROOT = Path(__file__).resolve().parents[2] / "vectors" / "hashlife"
CASES = sorted(VECTOR_ROOT.glob("*/params.json"))
SPEC_VERSIONS = {"0.14.0", "0.15.0", "0.16.0"}
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
    "snapshots": _COMMON | {"rule", "ops", "state", "state_sha256", "state_lines"} | _STATE,
}
# A snapshot script's own ops (spec 0.16.0); its other ops are the edit ops.
_SNAPSHOT_OPS = {
    "snapshot": {"op", "name"},
    "release": {"op", "name"},
    "restore": {"op", "name", "expect", "error"},
    "read": {"op", "input", "name", "frames", "expect", "error"},
    "measure": {"op", "names", "expect"},
}


def _expect_state(case_dir: Path, u: HashLife, entry: dict[str, Any]) -> None:
    assert str(u.generation) == entry["generation"]
    assert str(u.population) == entry["population"]
    box = u.bounding_box()
    assert (None if box is None else [str(v) for v in box]) == entry["bounding_box"]
    text = u.to_macrocell()
    if "state" in entry:
        assert text == (case_dir / entry["state"]).read_text(encoding="utf-8")
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
    elif kind == "clear_outside":  # spec 0.16.0 on
        u.clear_outside(op["x0"], op["y0"], op["x1"], op["y1"])
    elif kind == "rotate_rect":
        got = u.rotate_rect(op["x0"], op["y0"], op["x1"], op["y1"], clockwise=op["clockwise"])
        assert list(got) == op["expect"], op
    elif kind == "flip_rect":
        u.flip_rect(op["x0"], op["y0"], op["x1"], op["y1"], horizontal=op["horizontal"])
    elif kind in ("advance_selection", "advance_outside"):
        advance = u.advance_selection if kind == "advance_selection" else u.advance_outside
        advance(op["x0"], op["y0"], op["x1"], op["y1"], int(op["n"]))
    elif kind == "set_generation":
        u.set_generation(int(op["n"]))
    elif kind == "bounding_box_in":
        box = u.bounding_box_in(*(int(op[k]) for k in ("x0", "y0", "x1", "y1")))
        assert (None if box is None else [str(v) for v in box]) == op["expect"], op
    else:
        raise AssertionError(f"unknown op {kind!r}")


def _view(fields: list[Any]) -> LifeView:
    return LifeView(int(fields[0]), int(fields[1]), fields[2])


def _view_result(op: dict[str, Any]) -> tuple[Any, ...]:
    kind = op["op"]
    if kind == "pan":
        return tuple(vars(pan(_view(op["view"]), op["dx"], op["dy"])).values())
    if kind == "zoom_at":
        return tuple(vars(zoom_at(_view(op["view"]), op["i"], op["j"], op["steps"])).values())
    if kind == "cell_at":
        return cell_at(_view(op["view"]), op["i"], op["j"])
    if kind == "center_cell":
        return center_cell(_view(op["view"]), tuple(op["size"]))
    if kind == "centered":
        cx, cy = (int(c) for c in op["cell"])
        return tuple(vars(centered(cx, cy, op["mag"], tuple(op["size"]))).values())
    if kind == "fit":
        box = None if op["box"] is None else tuple(int(c) for c in op["box"])
        return tuple(vars(fit(box, tuple(op["size"]))).values())  # type: ignore[arg-type]
    if kind == "resized":
        return tuple(vars(resized(_view(op["view"]), tuple(op["old"]), tuple(op["new"]))).values())
    if kind == "frame_map":
        return frame_map(_view(op["frame"]), _view(op["view"]))
    raise AssertionError(f"unknown view op {kind!r}")


def _check_view_op(op: dict[str, Any]) -> None:
    if op.get("error"):
        with pytest.raises(ValueError):
            _view_result(op)
        return
    want = tuple(int(e) if isinstance(e, str) else e for e in op["expect"])
    assert _view_result(op) == want, op


def _snapshot_op(d: Path, u: HashLife, named: dict[str, Snapshot], op: dict[str, Any]) -> None:
    """One op of a snapshot script (spec/hashlife.md "Vector encoding", ``snapshots``)."""
    kind = op["op"]
    if kind not in _SNAPSHOT_OPS:
        _apply(u, op)
        return
    assert set(op) <= _SNAPSHOT_OPS[kind], set(op) - _SNAPSHOT_OPS[kind]
    if kind == "snapshot":
        named[op["name"]] = u.snapshot()
    elif kind == "release":
        named[op["name"]].release()
    elif kind == "restore":
        u.restore(named[op["name"]])
        _expect_state(d, u, op["expect"])
    elif kind == "read":
        before = (u.to_macrocell(), u.generation, u.rule)
        found = u.read_snapshot((d / op["input"]).read_bytes())
        assert (u.to_macrocell(), u.generation, u.rule) == before  # a read never moves it
        expect = op["expect"]
        assert found.format == expect["format"]
        assert found.rule == expect["rule"]
        notes = expect["metadata"]
        assert found.metadata == PatternMetadata(
            notes["name"], notes["author"], tuple(notes["comments"])
        )
        assert (None if found.step is None else str(found.step)) == expect["step"]
        named[op["name"]] = found.snapshot
        named.update(zip(op["frames"], found.frames, strict=True))
    else:  # measure
        footprint = u.measure_snapshots([named[n] for n in op["names"]])
        expect = op["expect"]
        assert footprint.universe_nodes == expect["universe_nodes"], op
        assert list(footprint.added) == expect["added"], op
        assert footprint.nodes == expect["nodes"], op


def test_hashlife_vectors_exist() -> None:
    kinds = {json.loads(c.read_text(encoding="utf-8"))["kind"] for c in CASES}
    assert kinds == set(_KEYS)


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.parent.name)
def test_hashlife_vector(case: Path) -> None:
    meta = json.loads(case.read_text(encoding="utf-8"))
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
        text = (d / meta["input"]).read_text(encoding="utf-8")
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
            assert u.to_rle() == (d / meta["rle"]).read_text(encoding="utf-8")
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
    elif kind == "snapshots":
        u = HashLife(meta["rule"])
        named: dict[str, Snapshot] = {}
        for op in meta["ops"]:
            if op.get("error"):
                before = (u.to_macrocell(), u.generation, u.rule)
                with pytest.raises(ValueError):
                    _snapshot_op(d, u, named, op)
                assert (u.to_macrocell(), u.generation, u.rule) == before
            else:
                _snapshot_op(d, u, named, op)
        _expect_state(d, u, meta)
    else:  # edit
        u = HashLife(meta["rule"])
        for op in meta["ops"]:
            if op.get("error"):
                before = (u.to_macrocell(), u.generation)
                with pytest.raises(ValueError):
                    _apply(u, op)
                assert (u.to_macrocell(), u.generation) == before
            else:
                _apply(u, op)
        _expect_state(d, u, meta)
