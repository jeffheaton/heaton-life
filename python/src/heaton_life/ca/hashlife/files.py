"""Any two-state pattern file into the unbounded universe (spec/formats.md "Reading into
the unbounded universe").

RLE and Macrocell keep their own readers; plaintext, Life 1.05, Life 1.06, and images
land as runs of leaves, so cells that are far apart never become a grid between them.
"""

from __future__ import annotations

import dataclasses

from heaton_life.ca.hashlife.macrocell import read_macrocell_with_metadata
from heaton_life.ca.hashlife.rle import add_run, read_rle
from heaton_life.ca.hashlife.universe import (
    DEFAULT_MEMORY_MB,
    HashLife,
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
    """A pattern file read into a HashLife universe, with its format and metadata."""

    format: PatternFormat
    universe: HashLife
    metadata: PatternMetadata


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


def read_universe(
    source: bytes | bytearray | memoryview | str, *, max_memory_mb: int = DEFAULT_MEMORY_MB
) -> PatternUniverse:
    """A two-state pattern file of any format (spec/formats.md), recognized by content and
    placed as each format says; the rule is the file's, or ``B3/S23`` without one."""
    found = recognize(source)
    fmt = found.format
    if fmt == "rle":
        universe = read_rle(found.text, max_memory_mb=max_memory_mb)
        return PatternUniverse(fmt, universe, rle_metadata(found.text))
    if fmt == "macrocell":
        universe, metadata = read_macrocell_with_metadata(found.text, max_memory_mb=max_memory_mb)
        return PatternUniverse(fmt, universe, metadata)
    if fmt in ("png", "bmp"):
        cells = (png_cells if fmt == "png" else bmp_cells)(found.data)
        universe = HashLife(max_memory_mb=max_memory_mb)
        universe.set_rect(0, 0, cells, "or")
        return PatternUniverse(fmt, universe, PatternMetadata())
    live = live_runs(found)
    # A file names its rule, never a preset (spec/formats.md "Reading into the unbounded
    # universe"), so the rule is compiled with presets off before the universe takes it.
    rule = "B3/S23" if live.rule is None else _hashlife_rule(live.rule, presets=False)
    universe = HashLife(rule, max_memory_mb=max_memory_mb)
    _place(universe, live.runs)
    return PatternUniverse(fmt, universe, live.metadata)
