"""Any two-state pattern file into the unbounded universe (spec/formats.md "Reading into
the unbounded universe", "Reading into a universe that exists").

RLE and Macrocell keep their own readers; plaintext, Life 1.05, Life 1.06, and images
land as runs of leaves, so cells that are far apart never become a grid between them.
Every format is built into a store first, the universe's state untouched, so one reading
serves both a new universe and one that exists.
"""

from __future__ import annotations

import dataclasses

from heaton_life.ca.hashlife.macrocell import build_macrocell, timeline_frames
from heaton_life.ca.hashlife.rle import add_run, build_rle
from heaton_life.ca.hashlife.universe import (
    DEFAULT_MEMORY_MB,
    HashLife,
    Snapshot,
    _hashlife_rule,
    check_box,
)
from heaton_life.init.formats import (
    PatternFormat,
    Run,
    live_runs,
    recognize,
    runs_box,
)
from heaton_life.init.images import bmp_cells, png_cells
from heaton_life.init.metadata import PatternMetadata
from heaton_life.init.rle import rle_metadata


@dataclasses.dataclass(frozen=True)
class PatternUniverse:
    """A pattern file read into a HashLife universe, with its format and metadata. A
    Macrocell timeline also gives its ``frames`` (snapshots of ``universe``, in order) and
    ``step``; any other file gives none."""

    format: PatternFormat
    universe: HashLife
    metadata: PatternMetadata
    frames: tuple[Snapshot, ...] = ()
    step: int | None = None


@dataclasses.dataclass(frozen=True)
class PatternSnapshot:
    """A pattern file read into a universe that exists (spec/formats.md "Reading into a
    universe that exists"): its format, a snapshot of its cells and generation in that
    universe, its rule in canonical form, its metadata, and a timeline's ``frames`` and
    ``step`` (none for any other file). The universe itself is unchanged."""

    format: PatternFormat
    snapshot: Snapshot
    rule: str
    metadata: PatternMetadata
    frames: tuple[Snapshot, ...] = ()
    step: int | None = None


@dataclasses.dataclass(frozen=True)
class _Read:
    """A file read into a store: its tree, generation, rule, metadata, and a timeline's step
    and frames as (node, level, generation), the universe not yet any of them."""

    format: PatternFormat
    root: int
    level: int
    generation: int
    rule: str
    metadata: PatternMetadata
    step: int | None
    frames: list[tuple[int, int, int]]


def _place(universe: HashLife, runs: tuple[Run, ...]) -> None:
    """Paste live runs, refusing any cell outside the editing box (spec/hashlife.md)."""
    box = runs_box(runs)
    if box is None:
        return
    check_box(*box)
    blocks: dict[tuple[int, int], int] = {}
    for x, y, length in runs:
        add_run(blocks, x, y - 1, length)  # tree row: one above the cell's y
    x0, y0, x1, y1 = box
    universe._paste_blocks(blocks, (x0, y0 - 1, x1, y1 - 1), "or")


def _read_into(universe: HashLife, source: bytes | bytearray | memoryview | str) -> _Read:
    """Read a two-state pattern file of any format into ``universe``'s store, placed as its
    format says, without changing the universe's state or rule."""
    found = recognize(source)
    fmt = found.format
    if fmt == "rle":
        root, level, generation, rule = build_rle(universe, found.text)
        return _Read(fmt, root, level, generation, rule, rle_metadata(found.text), None, [])
    if fmt == "macrocell":
        built = build_macrocell(universe, found.text)
        timeline = timeline_frames(
            universe._store, built.nodes, built.frames_lines, built.frame_lines
        )
        step, frames = (None, []) if timeline is None else timeline
        return _Read(
            fmt,
            built.root,
            built.level,
            built.generation,
            built.rule,
            built.metadata,
            step,
            frames,
        )
    if fmt in ("png", "bmp"):
        cells = (png_cells if fmt == "png" else bmp_cells)(found.data)
        root, level = universe._build(lambda: universe.set_rect(0, 0, cells, "or"))
        return _Read(fmt, root, level, 0, "B3/S23", PatternMetadata(), None, [])
    live = live_runs(found)
    # A file names its rule, never a preset (spec/formats.md "Reading into the unbounded
    # universe"), so the rule is compiled with presets off.
    rule = "B3/S23" if live.rule is None else _hashlife_rule(live.rule, presets=False)
    root, level = universe._build(lambda: _place(universe, live.runs))
    return _Read(fmt, root, level, 0, rule, live.metadata, None, [])


def read_universe(
    source: bytes | bytearray | memoryview | str, *, max_memory_mb: int = DEFAULT_MEMORY_MB
) -> PatternUniverse:
    """A two-state pattern file of any format (spec/formats.md), recognized by content and
    placed as each format says; the rule is the file's, or ``B3/S23`` without one. A
    Macrocell timeline gives its frames too, and a malformed one is refused."""
    universe = HashLife(max_memory_mb=max_memory_mb)
    read = _read_into(universe, source)
    universe.rule = read.rule
    universe._adopt(read.root, read.level, read.generation)
    frames = tuple(universe._snapshot_at(*frame) for frame in read.frames)
    return PatternUniverse(read.format, universe, read.metadata, frames, read.step)


def read_snapshot(
    universe: HashLife, source: bytes | bytearray | memoryview | str
) -> PatternSnapshot:
    """A two-state pattern file read into ``universe``'s own store as a snapshot, with its
    format, rule, metadata and a timeline's frames (spec/formats.md "Reading into a universe
    that exists"). The file is read as ``read_universe`` reads it; the universe's state,
    rule and earlier snapshots stay as they were."""
    read = _read_into(universe, source)
    snapshot = universe._snapshot_at(read.root, read.level, read.generation)
    frames = tuple(universe._snapshot_at(*frame) for frame in read.frames)
    return PatternSnapshot(read.format, snapshot, read.rule, read.metadata, frames, read.step)
