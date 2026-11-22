"""Pattern file conformance: replay vectors/formats/ — every format read into a grid, into a
new unbounded universe and into one that exists, measured without a grid, detection,
metadata read and written, Macrocell timelines, MCell files written and every MCell
refusal's reason (spec/formats.md, spec/macrocell.md). Bit-exact; the .NET suite replays
the same files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from heaton_life.ca.hashlife import HashLife, read_timeline, read_universe, write_timeline
from heaton_life.core import BoundedGrid, parse_bounded_grid
from heaton_life.init import (
    PatternMetadata,
    detect_format,
    mcell_encode,
    measure_pattern,
    read_pattern,
    rle_encode,
)

VECTOR_ROOT = Path(__file__).resolve().parents[2] / "vectors" / "formats"
CASES = sorted(VECTOR_ROOT.glob("*/params.json"))
SPEC_VERSIONS = {"0.16.0"}
_COMMON = {"spec_version", "family", "tier", "kind"}
_STATE = {"generation", "population", "bounding_box", "state", "state_sha256", "state_lines"}
_KEYS = {
    "read": _COMMON
    | {"input", "trim", "limit", "error", "format", "x", "y", "rule", "generation"}
    | {"metadata", "grid", "canonical", "bounded_grid", "mcell", "mcell_error"},
    "universe": _COMMON
    | {"input", "error", "format", "metadata", "with_metadata", "rle", "rle_error"}
    | {"frames", "step"}
    | _STATE,
    "detect": _COMMON | {"inputs"},
    "measure": _COMMON
    | {"input", "error", "format", "width", "height", "x", "y", "rule", "generation"}
    | {"metadata", "two_state", "bounded_grid"},
    "timeline-read": _COMMON
    | {"input", "error", "count", "first", "step", "metadata", "universe", "frames"},
    "timeline-write": _COMMON | {"input", "generations", "metadata", "timeline", "frames"},
    "mcell-reasons": _COMMON | {"cases"},
}


def _png(path: Path) -> np.ndarray:  # type: ignore[type-arg]
    with Image.open(path) as img:
        return np.asarray(img.convert("L"))


def _metadata(fields: dict[str, Any]) -> PatternMetadata:
    return PatternMetadata(fields["name"], fields["author"], tuple(fields["comments"]))


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


def test_format_vectors_exist() -> None:
    kinds = {json.loads(c.read_text(encoding="utf-8"))["kind"] for c in CASES}
    assert kinds == set(_KEYS)


def _bounded(meta: dict[str, Any]) -> BoundedGrid | None:
    """A case's bounded grid (spec/topology.md): its canonical suffix, or none if absent."""
    return parse_bounded_grid(meta["bounded_grid"]) if "bounded_grid" in meta else None


def _canonical_rule(text: str) -> str:
    """A rule's canonical form in the family that reads it, so that two spellings of one
    rule (``345/2/4`` and ``B2/S345/C4``) compare equal."""
    from heaton_life.ca.generations import try_compile_generations_rule
    from heaton_life.ca.ltl import try_parse_ltl_rule
    from heaton_life.ca.rulestring import compile_rule
    from heaton_life.init.rle import survival_birth_rule

    try:
        return compile_rule(survival_birth_rule(text), presets=False, variants=True).canonical
    except ValueError:
        pass
    generations, _ = try_compile_generations_rule(text)
    if generations is not None:
        return generations.canonical
    ltl, _ = try_parse_ltl_rule(text)
    return text if ltl is None else ltl.canonical


def _read(meta: dict[str, Any], data: bytes | str) -> Any:
    if meta["limit"] == "default":
        return read_pattern(data, trim=meta["trim"])
    return read_pattern(data, trim=meta["trim"], max_cells=meta["limit"])


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.parent.name)
def test_format_vector(case: Path) -> None:
    meta = json.loads(case.read_text(encoding="utf-8"))
    d = case.parent
    kind = meta["kind"]
    assert meta["family"] == "formats" and meta["tier"] == "bit-exact"
    assert meta["spec_version"] in SPEC_VERSIONS
    assert set(meta) <= _KEYS[kind], set(meta) - _KEYS[kind]
    if kind == "read":
        data = (d / meta["input"]).read_bytes()
        if meta.get("error"):
            with pytest.raises(ValueError):
                _read(meta, data)
            return
        found = _read(meta, data)
        assert found.format == meta["format"]
        assert (found.x, found.y) == (int(meta["x"]), int(meta["y"]))
        assert found.rule == meta["rule"]
        assert found.generation == int(meta["generation"])
        assert found.metadata == _metadata(meta["metadata"])
        assert list(found.cells.shape) == meta["grid"]["shape"]
        assert np.array_equal(found.cells, _png(d / meta["grid"]["file"]))
        assert found.bounded_grid == _bounded(meta)
        # A bounded world writes its suffix; its trimmed cells are no world.
        world = None if found.bounded_grid is None or meta["trim"] else found.bounded_grid
        topology = None if world is None else world.topology
        canonical = (d / meta["canonical"]).read_text(encoding="utf-8")
        encoded = rle_encode(
            found.cells, found.rule or "B3/S23", metadata=found.metadata, topology=topology
        )
        assert encoded == canonical
        again = read_pattern(canonical)  # the round trip: same cells and metadata
        assert np.array_equal(again.cells, found.cells)
        assert again.metadata == found.metadata
        rule = found.rule or "B3/S23"
        if meta.get("mcell_error"):
            with pytest.raises(ValueError):
                mcell_encode(found.cells, rule, topology=topology, metadata=found.metadata)
        elif "mcell" in meta:
            text = mcell_encode(found.cells, rule, topology=topology, metadata=found.metadata)
            assert text == (d / meta["mcell"]).read_text(encoding="utf-8")
            back = read_pattern(text)  # the same grid, rule and world; the metadata comments
            assert np.array_equal(back.cells, found.cells)
            assert _canonical_rule(back.rule) == _canonical_rule(rule)
            assert back.bounded_grid == world
            notes = found.metadata
            flat = tuple(v for v in (notes.name, notes.author) if v is not None)
            assert back.metadata == PatternMetadata(None, None, flat + notes.comments)
    elif kind == "mcell-reasons":
        for entry in meta["cases"]:
            assert set(entry) == {"input", "message"}, entry
            with pytest.raises(ValueError) as error:
                read_pattern(entry["input"])
            assert str(error.value) == entry["message"]
    elif kind == "universe":
        data = (d / meta["input"]).read_bytes()
        if meta.get("error"):
            with pytest.raises(ValueError):
                read_universe(data)
            return
        found = read_universe(data)
        assert found.format == meta["format"]
        assert found.metadata == _metadata(meta["metadata"])
        _expect_state(d, found.universe, meta)
        with_metadata = found.universe.to_macrocell(found.metadata)
        assert with_metadata == (d / meta["with_metadata"]).read_text(encoding="utf-8")
        if meta.get("rle_error"):
            with pytest.raises(ValueError, match="Macrocell"):
                found.universe.to_rle(found.metadata)
        else:
            rle = found.universe.to_rle(found.metadata)
            assert rle == (d / meta["rle"]).read_text(encoding="utf-8")
        if "frames" in meta:  # a timeline: the universe at the file's root, and its frames
            assert found.step == int(meta["step"])
            for frame, entry in zip(found.frames, meta["frames"], strict=True):
                found.universe.restore(frame)
                _expect_state(d, found.universe, entry)
        else:
            assert found.frames == () and found.step is None
    elif kind == "measure":
        data = (d / meta["input"]).read_bytes()
        if meta.get("error"):
            with pytest.raises(ValueError):
                measure_pattern(data)
            return
        extent = measure_pattern(data)
        assert extent.format == meta["format"]
        assert (extent.width, extent.height) == (int(meta["width"]), int(meta["height"]))
        assert (extent.x, extent.y) == (int(meta["x"]), int(meta["y"]))
        assert extent.rule == meta["rule"]
        assert extent.generation == int(meta["generation"])
        assert extent.metadata == _metadata(meta["metadata"])
        assert extent.two_state is meta["two_state"]
        assert extent.bounded_grid == _bounded(meta)
        if data.isascii():  # a text file measures the same handed over as text
            assert measure_pattern(data.decode("ascii")) == extent
    elif kind == "detect":
        for entry in meta["inputs"]:
            data = bytes.fromhex(entry["input"])
            if entry.get("error"):
                with pytest.raises(ValueError):
                    detect_format(data)
            else:
                assert detect_format(data) == entry["format"], data
    elif kind == "timeline-read":
        text = (d / meta["input"]).read_text(encoding="utf-8")
        # A file with a #FRAMES line is a timeline to the reader by content too.
        framed = any(line.strip().startswith("#FRAMES") for line in text.splitlines())
        if meta.get("error"):
            with pytest.raises(ValueError):
                read_timeline(text)
            if framed:
                with pytest.raises(ValueError):
                    read_universe(text)
            return
        timeline = read_timeline(text)
        assert len(timeline.frames) == meta["count"]
        assert timeline.frames[0].generation == int(meta["first"])
        assert timeline.step == int(meta["step"])
        assert timeline.metadata == _metadata(meta["metadata"])
        _expect_state(d, timeline.universe, meta["universe"])
        for frame, entry in zip(timeline.frames, meta["frames"], strict=True):
            timeline.universe.restore(frame)
            _expect_state(d, timeline.universe, entry)
        found = read_universe(text)
        assert found.step == timeline.step
        _expect_state(d, found.universe, meta["universe"])
        for frame, entry in zip(found.frames, meta["frames"], strict=True):
            found.universe.restore(frame)
            _expect_state(d, found.universe, entry)
    else:  # timeline-write
        universe = read_universe((d / meta["input"]).read_bytes()).universe
        frames = []
        for generation in meta["generations"]:
            universe.step(int(generation) - universe.generation)
            frames.append(universe.snapshot())
        text = write_timeline(universe, frames, metadata=_metadata(meta["metadata"]))
        assert text == (d / meta["timeline"]).read_text(encoding="utf-8")
        timeline = read_timeline(text)
        assert timeline.metadata == _metadata(meta["metadata"])
        for frame, entry in zip(timeline.frames, meta["frames"], strict=True):
            timeline.universe.restore(frame)
            _expect_state(d, timeline.universe, entry)


UNIVERSE_CASES = [
    c for c in CASES if json.loads(c.read_text(encoding="utf-8"))["kind"] == "universe"
]


@pytest.mark.parametrize("case", UNIVERSE_CASES, ids=lambda p: p.parent.name)
def test_read_snapshot_reads_as_the_universe_case(case: Path) -> None:
    """spec/formats.md "Reading into a universe that exists": every universe case's file,
    read into a universe that already holds a state and a snapshot, is accepted or refused
    as the case says, restores to the case's states, and leaves that universe as it was."""
    meta = json.loads(case.read_text(encoding="utf-8"))
    d = case.parent
    data = (d / meta["input"]).read_bytes()
    host = HashLife("B36/S23")
    host.set_rect(3, -2, np.array([[0, 1, 0], [0, 0, 1], [1, 1, 1]], np.uint8))
    host.step(7)
    kept = host.snapshot()
    host.step(5)
    before = (host.to_macrocell(), host.generation, host.rule)
    if meta.get("error"):
        with pytest.raises(ValueError):
            host.read_snapshot(data)
        assert (host.to_macrocell(), host.generation, host.rule) == before
        return
    found = host.read_snapshot(data)
    assert (host.to_macrocell(), host.generation, host.rule) == before
    assert found.format == meta["format"]
    assert found.metadata == _metadata(meta["metadata"])
    assert found.step == (int(meta["step"]) if "step" in meta else None)
    host.rule = found.rule  # the case's states carry the file's rule
    host.restore(found.snapshot)
    _expect_state(d, host, meta)
    for frame, entry in zip(found.frames, meta.get("frames", []), strict=True):
        host.restore(frame)
        _expect_state(d, host, entry)
    host.restore(kept)  # a snapshot taken before the read still restores
    assert host.generation == 7
