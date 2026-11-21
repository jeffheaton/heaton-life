"""Pattern file conformance: replay vectors/formats/ — every format read into a grid and into
the unbounded universe, measured without a grid, detection, metadata read and written, and
Macrocell timelines (spec/formats.md, spec/macrocell.md). Bit-exact; the .NET suite replays
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
from heaton_life.init import (
    PatternMetadata,
    detect_format,
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
    | {"metadata", "grid", "canonical"},
    "universe": _COMMON
    | {"input", "error", "format", "metadata", "with_metadata", "rle", "rle_error"}
    | _STATE,
    "detect": _COMMON | {"inputs"},
    "measure": _COMMON
    | {"input", "error", "format", "width", "height", "x", "y", "rule", "generation"}
    | {"metadata", "two_state"},
    "timeline-read": _COMMON
    | {"input", "error", "count", "first", "step", "metadata", "universe", "frames"},
    "timeline-write": _COMMON | {"input", "generations", "metadata", "timeline", "frames"},
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
        assert text == (case_dir / entry["state"]).read_text()
    else:
        assert text.count("\n") == entry["state_lines"]
        assert hashlib.sha256(text.encode("ascii")).hexdigest() == entry["state_sha256"]


def test_format_vectors_exist() -> None:
    kinds = {json.loads(c.read_text(encoding="utf-8"))["kind"] for c in CASES}
    assert kinds == set(_KEYS)


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
        canonical = (d / meta["canonical"]).read_text(encoding="utf-8")
        assert rle_encode(found.cells, found.rule or "B3/S23", metadata=found.metadata) == canonical
        again = read_pattern(canonical)  # the round trip: same cells and metadata
        assert np.array_equal(again.cells, found.cells)
        assert again.metadata == found.metadata
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
        if meta.get("error"):
            with pytest.raises(ValueError):
                read_timeline(text)
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
