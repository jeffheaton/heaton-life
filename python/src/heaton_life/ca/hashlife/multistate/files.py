"""Pattern files into the unbounded multi-state universe (spec/hashlife-multistate.md
"Pattern I/O"): Macrocell and RLE, gzip-compressed or not, recognized by their content.

Every file is built into a store first, the universe's state untouched, so one reading
serves both a new universe and one that exists. The other formats hold two states and are
refused.
"""

from __future__ import annotations

import dataclasses

from heaton_life.ca.hashlife.files import PatternSnapshot
from heaton_life.ca.hashlife.multistate.macrocell import (
    build_macrocell,
    fallback_rule,
    timeline_frames,
)
from heaton_life.ca.hashlife.multistate.rle import build_rle
from heaton_life.ca.hashlife.multistate.universe import MultiStateHashLife
from heaton_life.ca.hashlife.universe import DEFAULT_MEMORY_MB, Snapshot
from heaton_life.ca.state_rules import StateRule
from heaton_life.init.formats import PatternFormat, recognize
from heaton_life.init.metadata import PatternMetadata
from heaton_life.init.rle import rle_metadata


@dataclasses.dataclass(frozen=True)
class MultiStatePatternUniverse:
    """A pattern file read into a multi-state universe, with its format and metadata. A
    Macrocell timeline also gives its ``frames`` (snapshots of ``universe``, in order) and
    ``step``; any other file gives none."""

    format: PatternFormat
    universe: MultiStateHashLife
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
    rule: StateRule
    metadata: PatternMetadata
    step: int | None
    frames: list[tuple[int, int, int]]


def _read_into(
    universe: MultiStateHashLife,
    source: bytes | bytearray | memoryview | str,
    fallback: StateRule,
) -> _Read:
    """Read a Macrocell or RLE file into ``universe``'s store, without changing the
    universe's state or rule; ``fallback`` is the rule when the file names none."""
    found = recognize(source)
    fmt = found.format
    if fmt == "rle":
        root, level, generation, rule = build_rle(universe, found.text, fallback)
        return _Read(fmt, root, level, generation, rule, rle_metadata(found.text), None, [])
    if fmt == "macrocell":
        built = build_macrocell(universe, found.text, fallback)
        timeline = timeline_frames(universe, built)
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
    raise ValueError(
        f"a multi-state universe reads Macrocell and RLE files; {fmt} holds two states"
    )


def read_multistate_universe(
    source: bytes | bytearray | memoryview | str,
    *,
    rule: str | StateRule | None = None,
    max_memory_mb: int = DEFAULT_MEMORY_MB,
) -> MultiStatePatternUniverse:
    """A Macrocell or RLE file (gzip-compressed or not) as a new multi-state universe; the
    rule is the file's, or ``rule`` (default WireWorld) when it names none. A Macrocell
    timeline gives its frames too, and a malformed one is refused."""
    fallback = fallback_rule(rule)
    universe = MultiStateHashLife(fallback, max_memory_mb=max_memory_mb)
    read = _read_into(universe, source, fallback)
    universe.state_rule = read.rule
    universe._adopt(read.root, read.level, read.generation)
    states = read.rule.states
    frames = tuple(universe._snapshot_at(*frame, states) for frame in read.frames)
    return MultiStatePatternUniverse(read.format, universe, read.metadata, frames, read.step)


def read_multistate_snapshot(
    universe: MultiStateHashLife, source: bytes | bytearray | memoryview | str
) -> PatternSnapshot:
    """A Macrocell or RLE file read into ``universe``'s own store as a snapshot, with its
    format, rule, metadata and a timeline's frames; a file that names no rule takes the
    universe's. The universe's state, rule and earlier snapshots stay as they were."""
    read = _read_into(universe, source, universe.state_rule)
    states = read.rule.states
    snapshot = universe._snapshot_at(read.root, read.level, read.generation, states)
    frames = tuple(universe._snapshot_at(*frame, states) for frame in read.frames)
    return PatternSnapshot(
        read.format, snapshot, read.rule.canonical, read.metadata, frames, read.step
    )
