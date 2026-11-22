"""Pattern files in every format, recognized by content (spec/formats.md).

RLE, Macrocell, plaintext (``.cells``), Life 1.05, Life 1.06, and PNG and BMP images,
any of them gzip-compressed. ``detect_format`` names a file's format; ``read_pattern``
gives its cells as a dense grid with their position, rule, generation, and metadata, and
``measure_pattern`` gives all of that but the cells without making the grid. The HashLife
universe's reader, ``heaton_life.ca.hashlife.read_universe``, builds on the same
recognition and the same text readers.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from heaton_life.core.decimal_text import int_of_digits
from heaton_life.core.topology import BoundedGrid
from heaton_life.init.images import (
    PNG_SIGNATURE,
    bmp_cells,
    bmp_size,
    is_bmp,
    png_cells,
    png_size,
)
from heaton_life.init.metadata import (
    MetadataReader,
    PatternMetadata,
    first_text_line,
    inflate,
    text_from_bytes,
)
from heaton_life.init.rle import (
    DEFAULT_MAX_CELLS,
    RleExtent,
    RleInfo,
    _place_rle,
    is_rle_header,
    rle_decode,
    rle_measure,
    rle_metadata,
    rle_runs,
    survival_birth_rule,
)

PatternFormat = Literal["rle", "macrocell", "plaintext", "life-1.05", "life-1.06", "png", "bmp"]
PATTERN_FORMATS: tuple[PatternFormat, ...] = (
    "rle",
    "macrocell",
    "plaintext",
    "life-1.05",
    "life-1.06",
    "png",
    "bmp",
)

_PLAINTEXT_CELLS = frozenset(".O*")

Run = tuple[int, int, int]
"""A run of live cells: (x, y, length), x and y in the file's own coordinates."""


@dataclasses.dataclass(frozen=True, eq=False)
class PatternFile:
    """A pattern file read into a grid (spec/formats.md "Reading into a grid")."""

    format: PatternFormat
    cells: NDArray[np.uint8]
    """(height, width) row-major cell values: 0/1, or RLE's states up to 24."""
    x: int
    """Where ``cells[0, 0]`` sits in the file's own coordinates (y grows downward)."""
    y: int
    rule: str | None
    generation: int
    metadata: PatternMetadata
    bounded_grid: BoundedGrid | None = None
    """The world a bounded file names (spec/formats.md "Bounded grids"); the cells are that
    whole world unless trimmed."""


@dataclasses.dataclass(frozen=True)
class PatternExtent:
    """What ``read_pattern`` without ``trim`` gives, except the cells, found without making
    the grid (spec/formats.md "Measuring"). Every number is exact, of any size."""

    format: PatternFormat
    width: int
    """The grid's size; 0 × 0 for a pattern that reading refuses as empty."""
    height: int
    x: int
    """Where the grid's top-left cell sits in the file's own coordinates (y grows downward)."""
    y: int
    rule: str | None
    generation: int
    metadata: PatternMetadata
    two_state: bool
    """False for extended RLE, whatever states it uses: the universe reader refuses it."""
    bounded_grid: BoundedGrid | None = None
    """The world a bounded file names; the universe reader refuses such a file too."""


@dataclasses.dataclass(frozen=True)
class Recognized:
    """A file whose format is known (spec/formats.md "Detection"): an image's bytes, or
    the text of any other format."""

    format: PatternFormat
    data: bytes = b""
    text: str = ""


@dataclasses.dataclass(frozen=True)
class LiveRuns:
    """A plaintext or Life 1.0x file's live cells as runs, with what else it says."""

    runs: tuple[Run, ...]
    width: int
    """Plaintext's grid size (the longest row and the row count); 0 for Life 1.0x."""
    height: int
    rule: str | None
    metadata: PatternMetadata


def recognize(source: bytes | bytearray | memoryview | str) -> Recognized:
    """The format of a file's bytes, or of text (spec/formats.md "Detection"). Raises
    ValueError for empty text and for binary data that is no image."""
    if isinstance(source, str):
        text = source
    else:
        data = inflate(bytes(source))
        if data.startswith(PNG_SIGNATURE):
            return Recognized("png", data=data)
        if is_bmp(data):
            return Recognized("bmp", data=data)
        if b"\x00" in data:
            raise ValueError("not a pattern file: the data is binary and no known image")
        text = text_from_bytes(data)
    lines = text.splitlines()
    first = first_text_line(lines)
    if not first:
        raise ValueError("the pattern file is empty")
    fmt: PatternFormat
    if first.startswith("[M2]"):
        fmt = "macrocell"
    elif first.startswith("#Life 1.05"):
        fmt = "life-1.05"
    elif first.startswith("#Life 1.06"):
        fmt = "life-1.06"
    elif first.startswith("!"):
        fmt = "plaintext"
    else:
        content = [stripped for line in lines if (stripped := line.strip())]
        top = next((line for line in content if not line.startswith("#")), None)
        if top is not None and is_rle_header(top):
            fmt = "rle"
        elif all(set(line) <= _PLAINTEXT_CELLS for line in content):
            fmt = "plaintext"
        else:
            fmt = "rle"
    return Recognized(fmt, text=text)


def detect_format(source: bytes | bytearray | memoryview | str) -> PatternFormat:
    """A pattern file's format, from its content alone (spec/formats.md "Detection")."""
    return recognize(source).format


# -- the text formats ------------------------------------------------------------------------


def _row_runs(row: str, x: int, y: int, number: int, alive: str) -> list[Run]:
    """The live runs of a row of ``.`` (dead) and ``alive`` characters starting at x."""
    runs: list[Run] = []
    start = -1
    for i, ch in enumerate(row):
        if ch in alive:
            if start < 0:
                start = i
            continue
        if ch != ".":
            raise ValueError(f"line {number}: {ch!r} is not a cell ('.' dead, '{alive}' alive)")
        if start >= 0:
            runs.append((x + start, y, i - start))
            start = -1
    if start >= 0:
        runs.append((x + start, y, len(row) - start))
    return runs


def _plaintext(text: str, add: Callable[[Run], None]) -> tuple[int, int, PatternMetadata]:
    """Plaintext's live runs, each handed to ``add`` as its row is read; returns the grid's
    width and height (blank lines at the end are not rows) and the metadata."""
    notes = MetadataReader()
    width = height = rows = 0
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if stripped.startswith("!"):
            body = stripped[1:]
            if body.startswith("Name:"):
                notes.name(body[5:])
            elif body.startswith("Author:"):
                notes.author(body[7:])
            else:
                notes.comment(body)
            continue
        row = raw.rstrip()
        for run in _row_runs(row, 0, rows, number, "O*"):
            add(run)
        rows += 1
        if row:
            width, height = max(width, len(row)), rows
    return width, height, notes.result()


def _signed(text: str) -> int | None:
    """An optional ``-`` and ASCII digits, any size; None for anything else."""
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not (digits and digits.isascii() and digits.isdigit()):
        return None
    value = int_of_digits(digits)
    return -value if negative else value


def _cell(text: str, number: int, what: str) -> tuple[int, int]:
    fields = text.split()
    if len(fields) == 2:
        x, y = _signed(fields[0]), _signed(fields[1])
        if x is not None and y is not None:
            return x, y
    raise ValueError(f"line {number}: {what} needs two integers 'x y', got {text!r}")


def _life(
    text: str, *, blocks: bool, add: Callable[[Run], None]
) -> tuple[str | None, PatternMetadata]:
    """Life 1.05 (``blocks``: ``#P`` blocks of rows) or Life 1.06 (a cell a line): each live
    run handed to ``add`` as it is read; returns the rule and the metadata."""
    lines = text.splitlines()
    header = next(i for i, line in enumerate(lines) if line.strip())
    notes = MetadataReader()
    rule: str | None = None
    bx = by = row = 0
    for number, raw in enumerate(lines[header + 1 :], start=header + 2):
        stripped = raw.strip()
        if stripped.startswith("#"):
            tag, value = stripped[:2], stripped[2:].strip()
            if tag in ("#D", "#C"):
                notes.comment(value)
            elif tag == "#N":
                rule = "B3/S23"
            elif tag == "#R":
                rule = survival_birth_rule(value) if value else rule
            elif tag == "#P" and blocks:
                bx, by = _cell(value, number, "#P")
                row = 0
        elif blocks:
            for run in _row_runs(raw.rstrip(), bx, by + row, number, "*O"):
                add(run)
            row += 1
        elif stripped:
            x, y = _cell(stripped, number, "a cell")
            add((x, y, 1))
    return rule, notes.result()


def live_runs(found: Recognized) -> LiveRuns:
    """The live cells of a plaintext, Life 1.05 or Life 1.06 file."""
    runs: list[Run] = []
    if found.format == "plaintext":
        width, height, metadata = _plaintext(found.text, runs.append)
        return LiveRuns(tuple(runs), width, height, None, metadata)
    if found.format in ("life-1.05", "life-1.06"):
        rule, metadata = _life(found.text, blocks=found.format == "life-1.05", add=runs.append)
        return LiveRuns(tuple(runs), 0, 0, rule, metadata)
    raise ValueError(f"{found.format} is not read as runs")


class _Box:
    """The bounding box of live runs, widened as each one arrives: a measure keeps no cell."""

    def __init__(self) -> None:
        self.box: tuple[int, int, int, int] | None = None

    def add(self, run: Run) -> None:
        x, y, length = run
        last = x + length - 1
        if self.box is None:
            self.box = (x, y, last, y)
        else:
            x0, y0, x1, y1 = self.box
            self.box = (min(x0, x), min(y0, y), max(x1, last), max(y1, y))


def runs_box(runs: tuple[Run, ...]) -> tuple[int, int, int, int] | None:
    """The live cells' inclusive bounding box (x0, y0, x1, y1), or None without any."""
    if not runs:
        return None
    return (
        min(x for x, _, _ in runs),
        min(y for _, y, _ in runs),
        max(x + length - 1 for x, _, length in runs),
        max(y for _, y, _ in runs),
    )


# -- reading into a grid ---------------------------------------------------------------------


def _check(width: int, height: int, max_cells: int | None) -> None:
    if max_cells is not None and width * height > max_cells:
        raise ValueError(
            f"the pattern is {width:,} × {height:,} cells, past the limit of {max_cells:,}"
        )


def _grid(runs: tuple[Run, ...], x0: int, y0: int, width: int, height: int) -> NDArray[np.uint8]:
    grid = np.zeros((height, width), dtype=np.uint8)
    for x, y, length in runs:
        grid[y - y0, x - x0 : x - x0 + length] = 1
    return grid


def _trimmed(cells: NDArray[np.uint8]) -> tuple[NDArray[np.uint8], int, int]:
    rows = np.flatnonzero(cells.any(axis=1))
    columns = np.flatnonzero(cells.any(axis=0))
    if rows.size == 0:
        raise ValueError("the pattern has no live cells")
    top, left = int(rows[0]), int(columns[0])
    box = cells[top : int(rows[-1]) + 1, left : int(columns[-1]) + 1]
    return np.ascontiguousarray(box), left, top


def read_pattern(
    source: bytes | bytearray | memoryview | str,
    *,
    max_cells: int | None = DEFAULT_MAX_CELLS,
    trim: bool = False,
) -> PatternFile:
    """A pattern file of any format as a dense grid (spec/formats.md "Reading into a grid").

    The grid past ``max_cells`` (width × height; ``None`` lifts the limit) is refused before
    memory is asked for, and so is an image past it, trimmed or not. With ``trim`` the grid
    is cut to its live cells' bounding box and (x, y) moves with it. Macrocell and Life
    1.0x always give that box. A pattern without a live cell is an error where a box is
    asked for.
    """
    found = recognize(source)
    fmt = found.format
    metadata = PatternMetadata()
    if fmt in ("png", "bmp"):
        cells = (png_cells if fmt == "png" else bmp_cells)(found.data, max_cells)
        x = y = 0
        if trim:
            cells, x, y = _trimmed(cells)
        return PatternFile(fmt, cells, x, y, None, 0, metadata)
    if fmt == "rle":
        return _read_rle(found.text, max_cells, trim)
    if fmt == "macrocell":
        return _read_macrocell(found.text, max_cells)
    live = live_runs(found)
    box = runs_box(live.runs)
    if fmt == "plaintext" and not trim:
        if live.width == 0 or live.height == 0:
            raise ValueError("the plaintext pattern has no cells")
        _check(live.width, live.height, max_cells)
        cells = _grid(live.runs, 0, 0, live.width, live.height)
        return PatternFile(fmt, cells, 0, 0, live.rule, 0, live.metadata)
    if box is None:
        raise ValueError("the pattern has no live cells")
    x0, y0, x1, y1 = box
    _check(x1 - x0 + 1, y1 - y0 + 1, max_cells)
    cells = _grid(live.runs, x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    return PatternFile(fmt, cells, x0, y0, live.rule, 0, live.metadata)


def _read_rle(text: str, max_cells: int | None, trim: bool) -> PatternFile:
    info, _ = rle_runs(text)  # the #CXRLE line: position and generation
    metadata = rle_metadata(text)
    world = info.bounded_grid
    if world is None:
        cells, rule = rle_decode(text, max_cells=max_cells, trim=trim)
        x, y = info.position or (0, 0)
        if trim:
            live = rle_measure(text).live
            assert live is not None  # a trimmed decode has a live cell
            x, y = x + live[0], y + live[1]
        return PatternFile("rle", cells, x, y, rule, info.generation, metadata)
    extent = rle_measure(text)
    x0, y0, left, top = _bounded(info, extent)
    if trim:
        cells, rule = rle_decode(text, max_cells=max_cells, trim=True)
        assert extent.live is not None  # a trimmed decode has a live cell
        x, y = x0 + extent.live[0], y0 + extent.live[1]
        return PatternFile("rle", cells, x, y, rule, info.generation, metadata, world)
    _check(world.width, world.height, max_cells)
    cells = np.zeros((world.height, world.width), dtype=np.uint8)
    _place_rle(text, cells, x0 - left, y0 - top)
    return PatternFile("rle", cells, left, top, info.rule, info.generation, metadata, world)


def _bounded(info: RleInfo, extent: RleExtent) -> tuple[int, int, int, int]:
    """A bounded file's pattern and world (spec/formats.md "Bounded grids"): where the
    pattern's top-left cell sits (``#CXRLE Pos``, or its decoded size's half up and left of
    the origin) and where the world's does (centered on the origin). A pattern with a live
    cell past its world is refused."""
    world = info.bounded_grid
    assert world is not None
    left, top = -(world.width // 2), -(world.height // 2)
    if info.position is not None:
        x0, y0 = info.position
    else:
        x0, y0 = -(extent.width // 2), -(extent.height // 2)
    live = extent.live
    if live is not None and (
        x0 + live[0] < left
        or y0 + live[1] < top
        or x0 + live[2] >= left + world.width
        or y0 + live[3] >= top + world.height
    ):
        raise ValueError(f"the pattern reaches past its bounded grid ({world.suffix})")
    return x0, y0, left, top


def _read_macrocell(text: str, max_cells: int | None) -> PatternFile:
    from heaton_life.ca.hashlife.macrocell import read_macrocell_with_metadata

    universe, metadata = read_macrocell_with_metadata(text)
    box = universe.bounding_box()
    if box is None:
        raise ValueError("the Macrocell pattern has no live cells")
    x0, y0, x1, y1 = box
    _check(x1 - x0 + 1, y1 - y0 + 1, max_cells)
    cells = universe._cells(x0, y0, x1, y1)
    return PatternFile("macrocell", cells, x0, y0, universe.rule, universe.generation, metadata)


# -- measuring -------------------------------------------------------------------------------


def measure_pattern(source: bytes | bytearray | memoryview | str) -> PatternExtent:
    """What ``read_pattern`` without ``trim`` would give, except the cells, found without
    making the grid (spec/formats.md "Measuring"): the format, the grid's size and position,
    the rule, the generation, the metadata, and whether the cells have two states.

    No cell is kept, so a pattern too large for any grid measures as easily as a glider:
    RLE by its counted extent, plaintext by its rows, Life 1.0x by its cells' coordinates,
    Macrocell from its tree without a universe, and an image from its header (a picture's
    extent is the picture: its pixels are not decoded). Text is checked as the readers check
    it; an image only as far as its pixel data. A pattern that reading refuses as empty
    measures 0 × 0 at (0, 0).
    """
    found = recognize(source)
    fmt = found.format
    if fmt in ("png", "bmp"):
        width, height = (png_size if fmt == "png" else bmp_size)(found.data)
        return PatternExtent(fmt, width, height, 0, 0, None, 0, PatternMetadata(), True)
    if fmt == "rle":
        return _measure_rle(found.text)
    box: tuple[int, int, int, int] | None
    if fmt == "macrocell":
        from heaton_life.ca.hashlife.macrocell import measure_macrocell

        box, mc_rule, generation, metadata = measure_macrocell(found.text)
        return _boxed(fmt, box, mc_rule, generation, metadata)
    if fmt == "plaintext":
        width, height, metadata = _plaintext(found.text, lambda run: None)
        if width == 0 or height == 0:
            width = height = 0
        return PatternExtent(fmt, width, height, 0, 0, None, 0, metadata, True)
    found_box = _Box()
    rule, metadata = _life(found.text, blocks=fmt == "life-1.05", add=found_box.add)
    return _boxed(fmt, found_box.box, rule, 0, metadata)


def _boxed(
    fmt: PatternFormat,
    box: tuple[int, int, int, int] | None,
    rule: str | None,
    generation: int,
    metadata: PatternMetadata,
) -> PatternExtent:
    """The extent of a format whose grid is its live cells' bounding box."""
    if box is None:
        return PatternExtent(fmt, 0, 0, 0, 0, rule, generation, metadata, True)
    x0, y0, x1, y1 = box
    return PatternExtent(fmt, x1 - x0 + 1, y1 - y0 + 1, x0, y0, rule, generation, metadata, True)


def _measure_rle(text: str) -> PatternExtent:
    info, _ = rle_runs(text)  # the #CXRLE line: position and generation, checked as read checks
    extent = rle_measure(text)
    width, height = extent.width, extent.height
    x, y = info.position or (0, 0)
    if info.bounded_grid is not None:  # the world, whatever the pattern's own size
        _, _, x, y = _bounded(info, extent)
        width, height = info.bounded_grid.width, info.bounded_grid.height
    elif width == 0 or height == 0:
        width = height = x = y = 0
    return PatternExtent(
        "rle",
        width,
        height,
        x,
        y,
        extent.rule,
        info.generation,
        rle_metadata(text),
        not extent.extended,
        info.bounded_grid,
    )
