"""Multi-state HashLife conformance: replay vectors/hashlife-multistate/ — Wireworld, History
and Generations grids run on the plane beside their grid families, evolution from files,
Macrocell and RLE reading and canonical writing, edits with states, frames under a zoom
order, snapshot scripts, and timelines. Every state is compared through its canonical
Macrocell text (spec/hashlife-multistate.md), bit-exact. The .NET suite replays the same
files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from heaton_life.ca import LifeLike
from heaton_life.ca.generations import Generations
from heaton_life.ca.hashlife import HashLife, LifeView, MultiStateHashLife, Snapshot, read_universe
from heaton_life.ca.hashlife.multistate import (
    measure_multistate_pattern,
    read_multistate_universe,
    read_timeline,
    write_timeline,
)
from heaton_life.ca.rulestring import try_compile_rule
from heaton_life.ca.ruletable import RuleTableCA, starter_rule_or_none
from heaton_life.ca.state_rules import check_state_rule, state_rule, try_state_rule
from heaton_life.ca.wireworld import Wireworld
from heaton_life.init import PatternMetadata

VECTOR_ROOT = Path(__file__).resolve().parents[2] / "vectors" / "hashlife-multistate"
CASES = sorted(VECTOR_ROOT.glob("*/params.json"))
SPEC_VERSIONS = {"0.16.0"}
_COMMON = {"spec_version", "family", "tier", "kind"}
_STATE = {"generation", "population", "bounding_box", "state", "state_sha256", "state_lines"}
_KEYS = {
    "evolve": _COMMON | {"input", "checkpoints"},
    "grid": _COMMON | {"rule", "grid", "origin", "checkpoints"},
    "macrocell": _COMMON | {"input", "rule", "error", "rle", "rle_error"} | _STATE,
    "rle": _COMMON | {"input", "rule", "error", "rle", "rle_error"} | _STATE,
    "edit": _COMMON | {"rule", "ops"} | _STATE,
    "render": _COMMON | {"input", "generation", "frames"},
    "snapshots": _COMMON | {"rule", "ops"} | _STATE,
    "timeline": _COMMON | {"input", "generations", "metadata", "timeline", "frames"},
    "names": _COMMON | {"cases"},
    "measure": _COMMON | {"input", "rule", "error", "extent", "rule_named"},
    "convert": _COMMON | {"input", "from", "rule", "error"} | _STATE,
}
_EXTENT = {"format", "width", "height", "x", "y", "rule", "generation", "metadata", "two_state"}
_EDIT_OPS = {
    "set_cell": {"x", "y", "state"},
    "set_rect": {"x", "y", "mode", "cells"},
    "clear_rect": {"x0", "y0", "x1", "y1"},
    "clear_outside": {"x0", "y0", "x1", "y1"},
    "rotate_rect": {"x0", "y0", "x1", "y1", "clockwise", "expect"},
    "flip_rect": {"x0", "y0", "x1", "y1", "horizontal"},
    "advance_selection": {"x0", "y0", "x1", "y1", "n"},
    "advance_outside": {"x0", "y0", "x1", "y1", "n"},
    "set_generation": {"n"},
    "step": {"n"},
    "clear": set(),
    "set_rule": {"rule"},
    "fill_random": {"x0", "y0", "x1", "y1", "density", "seed"},
    "live_population": {"expect"},
    "live_population_in": {"x0", "y0", "x1", "y1", "expect"},
    "get_rect": {"x0", "y0", "x1", "y1", "expect"},
    "bounding_box_in": {"x0", "y0", "x1", "y1", "expect"},
}
_SNAPSHOT_OPS = {
    "snapshot": {"name"},
    "release": {"name"},
    "restore": {"name", "expect"},
    "read": {"input", "name", "frames", "expect"},
    "measure": {"names", "expect"},
}
_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def _expect_state(case_dir: Path, u: MultiStateHashLife | HashLife, entry: dict[str, Any]) -> None:
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


def _states_png(path: Path, scale: int = 85) -> np.ndarray[Any, np.dtype[np.uint8]]:
    """A grid stored as its family's vectors store one: Wireworld's states × 85, or, with
    ``scale`` 1, a History, Super or Generations rule's: the states themselves."""
    with Image.open(path) as img:
        return (np.asarray(img.convert("L")) // scale).astype(np.uint8)


def _is_variant(rule: str) -> bool:
    """Whether a case's rule is a History or Super rule (spec/history.md, spec/super.md),
    whose grid is Life-like."""
    compiled, _ = try_compile_rule(rule, presets=False, variants=True)
    return compiled is not None and compiled.variant != ""


def _cells(rows: list[str]) -> np.ndarray[Any, np.dtype[np.uint8]]:
    return np.array([[_DIGITS.index(c) for c in row] for row in rows], np.uint8)


def _apply(u: MultiStateHashLife, op: dict[str, Any]) -> None:
    kind = op["op"]
    assert set(op) - {"op", "error"} <= _EDIT_OPS[kind], op
    box = tuple(op[k] for k in ("x0", "y0", "x1", "y1") if k in op)
    if kind == "set_cell":
        u.set_cell(op["x"], op["y"], op["state"])
    elif kind == "set_rect":
        u.set_rect(op["x"], op["y"], _cells(op["cells"]), op["mode"])
    elif kind == "clear_rect":
        u.clear_rect(*box)
    elif kind == "clear_outside":
        u.clear_outside(*box)
    elif kind == "rotate_rect":
        got = u.rotate_rect(*box, clockwise=op["clockwise"])
        assert list(got) == op["expect"], op
    elif kind == "flip_rect":
        u.flip_rect(*box, horizontal=op["horizontal"])
    elif kind == "advance_selection":
        u.advance_selection(*box, int(op["n"]))
    elif kind == "advance_outside":
        u.advance_outside(*box, int(op["n"]))
    elif kind == "set_generation":
        u.set_generation(int(op["n"]))
    elif kind == "step":
        u.step(int(op["n"]))
    elif kind == "clear":
        u.clear()
    elif kind == "set_rule":
        u.rule = op["rule"]
    elif kind == "fill_random":  # History, Super and Generations rules (hashlife-multistate.md)
        u.fill_random(*box, op["density"], op["seed"])
    elif kind == "get_rect":
        rows = ["".join(_DIGITS[v] for v in row) for row in u.get_rect(*box)]
        assert rows == op["expect"], op
    elif kind == "live_population":  # spec/hashlife-multistate.md "Observables"
        assert str(u.live_population) == op["expect"], op
    elif kind == "live_population_in":
        assert str(u.live_population_in(*(int(v) for v in box))) == op["expect"], op
    else:  # bounding_box_in
        found = u.bounding_box_in(*(int(v) for v in box))
        assert (None if found is None else [str(v) for v in found]) == op["expect"], op


def _snapshot_op(
    d: Path, u: MultiStateHashLife, named: dict[str, Snapshot], op: dict[str, Any]
) -> None:
    kind = op["op"]
    if kind not in _SNAPSHOT_OPS:
        _apply(u, op)
        return
    assert set(op) - {"op", "error"} <= _SNAPSHOT_OPS[kind], op
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


def _scripted(d: Path, meta: dict[str, Any], run: Any) -> MultiStateHashLife:
    u = MultiStateHashLife(meta["rule"])
    for op in meta["ops"]:
        if op.get("error"):
            before = (u.to_macrocell(), u.generation, u.rule)
            with pytest.raises(ValueError):
                run(u, op)
            assert (u.to_macrocell(), u.generation, u.rule) == before, op
        else:
            run(u, op)
    return u


def test_multistate_vectors_exist() -> None:
    kinds = {json.loads(c.read_text(encoding="utf-8"))["kind"] for c in CASES}
    assert kinds == set(_KEYS)


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.parent.name)
def test_multistate_vector(case: Path) -> None:
    meta = json.loads(case.read_text(encoding="utf-8"))
    d = case.parent
    kind = meta["kind"]
    assert meta["family"] == "hashlife-multistate" and meta["tier"] == "bit-exact"
    assert meta["spec_version"] in SPEC_VERSIONS
    assert set(meta) <= _KEYS[kind], set(meta) - _KEYS[kind]
    if kind == "evolve":
        u = read_multistate_universe((d / meta["input"]).read_bytes()).universe
        for entry in meta["checkpoints"]:
            assert set(entry) <= _STATE, entry
            u.step(int(entry["generation"]) - u.generation)
            _expect_state(d, u, entry)
    elif kind == "grid":
        # Wireworld's grid PNGs are states × 85. A History or Super rule's grid is Life-like
        # (spec/history.md, spec/super.md), and a Generations rule's (spec/generations.md) and
        # a rule table's (spec/ruletable.md) are their own families, their PNGs the states
        # themselves.
        wire = meta["rule"] == "WireWorld"
        life_like = _is_variant(meta["rule"])
        table = starter_rule_or_none(meta["rule"])  # a rule table (spec/ruletable.md)
        scale = 85 if wire else 1
        grid = _states_png(d / meta["grid"], scale)
        height, width = grid.shape
        x, y = (int(v) for v in meta["origin"])
        u = MultiStateHashLife(meta["rule"])
        u.set_rect(x, y, grid)
        w: Wireworld | LifeLike | Generations | RuleTableCA
        if wire:
            w = Wireworld(size=(width, height), init=grid)
        elif life_like:
            w = LifeLike(meta["rule"], size=(width, height), init=grid, boundary="dead")
        elif table is not None:
            w = RuleTableCA(table, size=(width, height), init=grid)
        else:
            w = Generations(meta["rule"], size=(width, height), init=grid, boundary="dead")
        for entry in meta["checkpoints"]:
            assert set(entry) <= _STATE | {"cells"}, entry
            gen = int(entry["generation"])
            u.step(gen - u.generation)
            w.step(gen - w.generation)
            _expect_state(d, u, entry)
            cells = _states_png(d / entry["cells"], scale)
            assert np.array_equal(w.state, cells), gen  # the grid family's own run
            assert np.array_equal(u.get_rect(x, y, x + width - 1, y + height - 1), cells), gen
            assert u.population == int(np.count_nonzero(cells)), gen  # nothing outside it
    elif kind in ("macrocell", "rle"):
        text = (d / meta["input"]).read_text(encoding="utf-8")
        read = (
            MultiStateHashLife.from_macrocell
            if kind == "macrocell"
            else MultiStateHashLife.from_rle
        )
        if meta.get("error"):
            with pytest.raises(ValueError):
                read(text, rule=meta.get("rule"))
            return
        u = read(text, rule=meta.get("rule"))
        _expect_state(d, u, meta)
        if meta.get("rle_error"):
            with pytest.raises(ValueError, match="Macrocell"):
                u.to_rle()
        else:
            assert u.to_rle() == (d / meta["rle"]).read_text(encoding="utf-8")
    elif kind == "render":
        u = read_multistate_universe((d / meta["input"]).read_bytes()).universe
        u.step(int(meta["generation"]) - u.generation)
        for frame in meta["frames"]:
            assert set(frame) == {"view", "size", "mode", "order", "file"}, frame
            u.zoom_order = frame["order"]
            view = LifeView(int(frame["view"][0]), int(frame["view"][1]), frame["view"][2])
            got = u.render(view, tuple(frame["size"]), frame["mode"])
            with Image.open(d / frame["file"]) as img:
                assert np.array_equal(got, np.asarray(img.convert("L"))), frame
    elif kind == "snapshots":
        named: dict[str, Snapshot] = {}
        u = _scripted(d, meta, lambda v, op: _snapshot_op(d, v, named, op))
        _expect_state(d, u, meta)
    elif kind == "timeline":
        u = read_multistate_universe((d / meta["input"]).read_bytes()).universe
        frames = []
        for generation in meta["generations"]:
            u.step(int(generation) - u.generation)
            frames.append(u.snapshot())
        notes = meta["metadata"]
        metadata = PatternMetadata(notes["name"], notes["author"], tuple(notes["comments"]))
        text = write_timeline(u, frames, metadata=metadata)
        assert text == (d / meta["timeline"]).read_text(encoding="utf-8")
        back = read_timeline(text)
        assert back.metadata == metadata
        for frame, entry in zip(back.frames, meta["frames"], strict=True):
            back.universe.restore(frame)
            _expect_state(d, back.universe, entry)
    elif kind == "convert":
        # A Life-like world converted between the engines (spec/hashlife-multistate.md
        # "Converting between the engines"), its state pinned as its new engine pins one.
        data = (d / meta["input"]).read_bytes()
        assert meta["from"] in ("two-state", "multistate"), meta["from"]
        source: HashLife | MultiStateHashLife = (
            read_universe(data).universe
            if meta["from"] == "two-state"
            else read_multistate_universe(data).universe
        )
        rule = meta["rule"]
        two_state, _ = try_compile_rule(rule, presets=False)

        def convert() -> HashLife | MultiStateHashLife:
            if isinstance(source, HashLife) or two_state is None:
                return source.to_multistate(rule)
            return source.to_two_state(rule)

        before = source.to_macrocell()
        if meta.get("error"):
            with pytest.raises(ValueError):
                convert()
        else:
            out = convert()
            assert out.generation == source.generation
            _expect_state(d, out, meta)
        assert source.to_macrocell() == before  # the old universe is unchanged
    elif kind == "measure":
        # Measured without a universe, then loaded: the extent is the loaded universe's box
        # (spec/hashlife-multistate.md "Measuring"), and loading says whether the file named
        # its rule.
        data = (d / meta["input"]).read_bytes()
        rule = meta.get("rule")
        if meta.get("error"):
            with pytest.raises(ValueError):
                measure_multistate_pattern(data, rule=rule)
            with pytest.raises(ValueError):
                read_multistate_universe(data, rule=rule)
            return
        want = meta["extent"]
        assert set(want) == _EXTENT, want
        extent = measure_multistate_pattern(data, rule=rule)
        assert extent.format == want["format"]
        assert (extent.width, extent.height) == (int(want["width"]), int(want["height"]))
        assert (extent.x, extent.y) == (int(want["x"]), int(want["y"]))
        assert extent.rule == want["rule"]
        assert extent.generation == int(want["generation"])
        notes = want["metadata"]
        assert extent.metadata == PatternMetadata(
            notes["name"], notes["author"], tuple(notes["comments"])
        )
        assert extent.two_state is want["two_state"]
        assert extent.bounded_grid is None
        read = read_multistate_universe(data, rule=rule)
        assert read.rule_named is meta["rule_named"]
        box = read.universe.bounding_box()
        if box is None:
            assert extent.width == extent.height == 0
        else:
            x0, y0, x1, y1 = box
            assert (x0, y0, x1 - x0 + 1, y1 - y0 + 1) == (
                extent.x,
                extent.y,
                extent.width,
                extent.height,
            )
    elif kind == "names":
        # Each text names a rule the universe runs, or gives its reason (spec/hashlife-multistate.md
        # "Names"); the error's message is the reason and the page that says why.
        for entry in meta["cases"]:
            text = entry["input"]
            rule, reason = try_state_rule(text)
            if entry.get("error"):
                assert set(entry) == {"input", "error", "reason"}, entry
                assert (rule, reason) == (None, entry["reason"]), text
                with pytest.raises(ValueError) as error:
                    state_rule(text)
                message = str(error.value)
                assert message.startswith(f"{reason} (spec/") and message.endswith(")"), text
            else:
                assert set(entry) == {"input", "canonical", "states"}, entry
                assert reason is None and rule is not None, text
                assert (rule.canonical, rule.states) == (entry["canonical"], entry["states"]), text
                assert check_state_rule(rule) is rule
    else:  # edit
        u = _scripted(d, meta, _apply)
        _expect_state(d, u, meta)
