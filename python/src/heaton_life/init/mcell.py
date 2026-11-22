"""MCell files (``.mcl``) of the Life, Generations and Larger than Life families
(spec/formats.md "MCell").

An MCell file is keyword lines: ``#MCell`` and a version, then ``#GAME`` (the family),
``#RULE`` (the rule, possibly split over several lines), ``#BOARD`` and ``#WRAP`` (a world),
``#D`` (comments) and ``#L`` (cell data in extended RLE without a header). The reader here
gives the header and walks the cell data; ``heaton_life.init.formats`` builds grids and
extents on it, and both HashLife universes read through it. ``mcell_encode`` writes a grid.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

from heaton_life.core.decimal_text import int_of_digits
from heaton_life.core.topology import MAX_SIDE, BoundedGrid, Topology
from heaton_life.init.metadata import MetadataReader, PatternMetadata, metadata_lines
from heaton_life.init.rle import survival_birth_rule

MCELL_FAMILIES = ("Life", "Generations", "Larger than Life")
"""The MCell families this library reads and writes."""

MCELL_VERSION = "4.00"
"""The version the writer puts on its ``#MCell`` line: the one the format's description
documents."""

_LINE_WIDTH = 70  # characters of cell data on one #L line
_SURVIVAL_BIRTH_DIGITS = frozenset("012345678")


class MCellError(ValueError):
    """A file that breaks spec/formats.md "MCell": ``invalid MCell file: <reason>``."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"invalid MCell file: {reason}")
        self.reason = reason


@dataclasses.dataclass(frozen=True)
class MCellHeader:
    """An MCell file's lines, read and checked: everything but the cells."""

    family: str
    """One of MCELL_FAMILIES."""
    rule: str
    """The rule as the reader reports it: Life's as ``B…/S…``, Generations' as written, and
    Larger than Life's without its whitespace."""
    states: int
    """The rule's number of states: 2 for Life."""
    board: BoundedGrid | None
    metadata: PatternMetadata
    data: str
    """The ``#L`` lines' values joined, whitespace removed."""

    @property
    def two_state(self) -> bool:
        """Life files hold two states; the other families' files are multi-state."""
        return self.family == "Life"


def _ascii_lower(text: str) -> str:
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in text)


def _keyword(line: str) -> tuple[str, str]:
    """A stripped line's keyword (its text up to its first whitespace) and value."""
    for i, ch in enumerate(line):
        if ch.isspace():
            return line[:i], line[i:].strip()
    return line, ""


def _digits(text: str) -> bool:
    return text.isascii() and text.isdigit()


def _life_rule(text: str) -> str:
    survival, slash, birth = text.partition("/")
    if not slash or not set(survival + birth) <= _SURVIVAL_BIRTH_DIGITS or "/" in birth:
        raise MCellError(f"a Life rule is survival/birth digits, such as 23/3, not '{text}'")
    return survival_birth_rule(text)


def _family_rule(family: str, text: str) -> tuple[str, int]:
    """The rule a family reads from ``text``, as reported, and its number of states."""
    if family == "Life":
        return _life_rule(text), 2
    if family == "Generations":
        parts = text.split("/")
        if not (
            len(parts) == 3 and all(p == "" or _digits(p) for p in parts[:2]) and _digits(parts[2])
        ):
            raise MCellError(
                f"a Generations rule is survival/birth/states digits, such as 345/2/4, not '{text}'"
            )
        # Imported here: heaton_life.ca imports this package.
        from heaton_life.ca.generations import compile_generations_rule

        try:
            return text, compile_generations_rule(text).states
        except ValueError as error:
            raise MCellError(str(error)) from None
    from heaton_life.ca.ltl import parse_ltl_rule

    compact = "".join(ch for ch in text if not ch.isspace())
    try:
        return compact, parse_ltl_rule(compact).states
    except ValueError as error:
        raise MCellError(str(error)) from None


def _board(value: str) -> tuple[int, int]:
    at = next((i for i, ch in enumerate(value) if ch in "xX"), len(value))
    width, height = value[:at].strip(), value[at + 1 :].strip()
    if _digits(width) and _digits(height):
        w, h = int_of_digits(width), int_of_digits(height)
        if 0 < w <= MAX_SIDE and 0 < h <= MAX_SIDE:
            return w, h
    raise MCellError(f"#BOARD is <width>x<height>, not '{value}'")


def read_mcell_header(text: str) -> MCellHeader:
    """An MCell file's lines, checked in spec/formats.md's order: the lines top to bottom,
    then the family, the rule, ``#BOARD``, ``#WRAP``. The cell data is checked when it is
    walked (``mcell_runs``)."""
    lines = text.splitlines()
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first is None or not lines[first].strip().startswith("#MCell"):
        raise MCellError("the first line does not start with '#MCell'")
    game = "Life"
    rules: list[str] = []
    board: str | None = None
    wrap: str | None = None
    notes = MetadataReader()
    data: list[str] = []
    for number, raw in enumerate(lines[first + 1 :], start=first + 2):
        stripped = raw.strip()
        if not stripped:
            continue
        if not stripped.startswith("#"):
            raise MCellError(f"line {number} does not start with '#'")
        keyword, value = _keyword(stripped)
        if keyword == "#GAME":
            game = value
        elif keyword == "#RULE":
            rules.append(value)
        elif keyword == "#BOARD":
            board = value
        elif keyword == "#WRAP":
            wrap = value
        elif keyword == "#D":
            notes.comment(value)
        elif keyword == "#L":
            data.append(value)
    family = next((f for f in MCELL_FAMILIES if _ascii_lower(f) == _ascii_lower(game)), None)
    if family is None:
        raise MCellError(
            f"the family '{game}' is not read here (Life, Generations and Larger than Life are)"
        )
    rule, states = _family_rule(family, "".join(rules) if rules else "23/3")
    size = None if board is None else _board(board)
    if wrap is not None and wrap not in ("0", "1"):
        raise MCellError(f"#WRAP is 0 or 1, not '{wrap}'")
    world = None
    if size is not None:
        topology = Topology("dead" if wrap == "0" else "torus")
        world = BoundedGrid(size[0], size[1], topology)
    cells = "".join(ch for ch in "".join(data) if not ch.isspace())
    return MCellHeader(family, rule, states, world, notes.result(), cells)


Emit = Callable[[int, int, int, int], None]
"""Receives each run of a non-zero state: (x, y, length, state)."""


@dataclasses.dataclass(frozen=True)
class MCellExtent:
    """The cell data's decoded size and the inclusive box of its non-zero cells."""

    width: int
    height: int
    live: tuple[int, int, int, int] | None


def mcell_runs(header: MCellHeader, emit: Emit | None = None) -> MCellExtent:
    """Walk the cell data (spec/formats.md "MCell", "Cell data"), handing each run of a
    non-zero state to ``emit`` (a Life file's states as 1), and give its extent. Every
    problem in the data is an MCellError, the first one met from the data's start."""
    data, states, life = header.data, header.states, header.family == "Life"
    n = len(data)
    x = y = width = 0
    items = False
    box: list[int] | None = None
    i = 0
    while i < n:
        j = i
        while j < n and "0" <= data[j] <= "9":
            j += 1
        if j == n:
            raise MCellError("a run count in the cell data has no state or '$' after it")
        count = int_of_digits(data[i:j]) if j > i else 1
        tag = data[j]
        items = True
        if tag == "$":
            if count:
                y += count
                x = 0
            i = j + 1
            continue
        if tag == ".":
            state = 0
            i = j + 1
        elif "A" <= tag <= "X":
            state = ord(tag) - 64
            i = j + 1
        elif "a" <= tag <= "j":
            if j + 1 == n or not "A" <= data[j + 1] <= "X":
                raise MCellError(f"'{tag}' in the cell data has no state letter A to X after it")
            state = 24 * (ord(tag) - 96) + ord(data[j + 1]) - 64
            if state > 255:
                raise MCellError(f"the cell data's state {state} is past 255")
            i = j + 2
        else:
            raise MCellError(f"'{tag}' in the cell data is no run count, state or '$'")
        if not life and state >= states:
            raise MCellError(f"the cell data's state {state} is past the rule's {states} states")
        if count == 0:
            continue
        if state:
            last = x + count - 1
            if box is None:
                box = [x, y, last, y]
            else:
                box = [min(box[0], x), box[1], max(box[2], last), y]
            if emit is not None:
                emit(x, y, count, 1 if life else state)
        x += count
        width = max(width, x)
    live = None if box is None else (box[0], box[1], box[2], box[3])
    return MCellExtent(width, y + 1 if items else 0, live)


def board_placement(world: BoundedGrid, extent: MCellExtent) -> tuple[int, int, int, int]:
    """Where a board's pattern and world sit (spec/formats.md "Bounded grids"): the pattern's
    top-left cell (its decoded size centered on the origin) and the world's (centered too).
    A live cell past the world is an MCellError."""
    left, top = -(world.width // 2), -(world.height // 2)
    x0, y0 = -(extent.width // 2), -(extent.height // 2)
    live = extent.live
    if live is not None and (
        x0 + live[0] < left
        or y0 + live[1] < top
        or x0 + live[2] >= left + world.width
        or y0 + live[3] >= top + world.height
    ):
        raise MCellError(f"the pattern reaches past its board ({world.suffix})")
    return x0, y0, left, top


def board_refusal(world: BoundedGrid) -> str:
    """Why an unbounded universe refuses a file with a board (spec/formats.md)."""
    return (
        f"the unbounded universe has no bounded grid (the MCell board '{world.suffix}'): "
        "open the file in a grid world (spec/topology.md)"
    )


# -- writing ---------------------------------------------------------------------------------


def _survival_birth(canonical: str) -> str | None:
    """``B<birth>/S<survival>`` with digits only as ``<survival>/<birth>``, else None."""
    birth, slash, survival = canonical.partition("/S")
    if not (slash and birth.startswith("B")):
        return None
    birth = birth[1:]
    if not set(birth + survival) <= _SURVIVAL_BIRTH_DIGITS:
        return None
    return f"{survival}/{birth}"


def _writer_rule(rule: str) -> tuple[str, str, int]:
    """The family, the ``#RULE`` text and the number of states MCell writes ``rule`` with."""
    from heaton_life.ca.generations import try_compile_generations_rule
    from heaton_life.ca.ltl import try_parse_ltl_rule
    from heaton_life.ca.rulestring import compile_rule

    rule = survival_birth_rule(rule)  # 23/3 is B3/S23, as the RLE encoder reads it
    try:
        life = compile_rule(rule, presets=False, variants=True)
    except ValueError:
        pass
    else:
        written = None if life.variant else _survival_birth(life.canonical)
        if written is not None:
            return "Life", written, 2
        raise ValueError(f"no MCell family holds the rule '{rule}'")
    generations, _ = try_compile_generations_rule(rule)
    if generations is not None:
        written = _survival_birth(generations.life.canonical)
        if written is not None:
            return "Generations", f"{written}/{generations.states}", generations.states
        raise ValueError(f"no MCell family holds the rule '{rule}'")
    ltl, _ = try_parse_ltl_rule(rule)
    if ltl is not None:
        return "Larger than Life", ltl.canonical, ltl.states
    raise ValueError(f"no MCell family holds the rule '{rule}'")


def _tag(state: int) -> str:
    if state == 0:
        return "."
    if state <= 24:
        return chr(64 + state)
    return chr(96 + (state - 1) // 24) + chr(65 + (state - 1) % 24)


def _run(length: int, tag: str) -> str:
    return tag if length == 1 else f"{length}{tag}"


def _data_items(grid: NDArray[np.uint8]) -> list[str]:
    """The cell data's items: each row's runs without its trailing dead cells, row ends as
    ``k$``, and the first row padded to the full width when no row reaches it."""
    height, width = grid.shape
    ends = [int(nz[-1]) + 1 if (nz := np.flatnonzero(row)).size else 0 for row in grid]
    pad = max(ends) < width
    items: list[str] = []
    rows_pending = 0
    for y in range(height):
        end = width if pad and y == 0 else ends[y]
        if y:
            rows_pending += 1
        if end == 0:
            continue
        if rows_pending:
            items.append(_run(rows_pending, "$"))
            rows_pending = 0
        row = grid[y]
        x = 0
        while x < end:
            state = int(row[x])
            run = 1
            while x + run < end and row[x + run] == state:
                run += 1
            items.append(_run(run, _tag(state)))
            x += run
    if rows_pending:
        items.append(_run(rows_pending, "$"))
    return items


def mcell_encode(
    cells: NDArray[np.generic],
    rule: str,
    *,
    topology: Topology | None = None,
    metadata: PatternMetadata | None = None,
) -> str:
    """A grid as an MCell file (spec/formats.md "MCell", "Writing"): the family ``rule``
    belongs to, the board and its wrap when ``topology`` is given (the torus or the plane),
    the metadata as ``#D`` lines (name, author, comments), and the cell data, read back as
    the same grid. A rule no MCell family holds, any other topology, a state past the rule's,
    or a grid without rows or columns is a ValueError."""
    grid = np.asarray(cells)
    if grid.ndim != 2 or grid.shape[0] == 0 or grid.shape[1] == 0:
        raise ValueError("an MCell pattern has at least one row and one column")
    if grid.min() < 0 or grid.max() > 255:
        raise ValueError("an MCell cell's state is 0 to 255")
    grid = grid.astype(np.uint8)
    family, written, states = _writer_rule(rule)
    top = int(grid.max())
    if top >= states:
        raise ValueError(f"the cells hold state {top}, past the rule's {states} states")
    height, width = grid.shape
    lines = [f"#MCell {MCELL_VERSION}", f"#GAME {family}", f"#RULE {written}"]
    if topology is not None:
        world = BoundedGrid(width, height, topology)
        if topology.shift or topology.boundary not in ("torus", "dead"):
            raise ValueError(f"an MCell board is a torus or the plane, not '{world.suffix}'")
        lines.append(f"#BOARD {width}x{height}")
        lines.append(f"#WRAP {1 if topology.boundary == 'torus' else 0}")
    lines.extend("#D" + line[2:] for line in metadata_lines(metadata))
    current = ""
    for item in _data_items(grid):
        if current and len(current) + len(item) > _LINE_WIDTH:
            lines.append(f"#L {current}")
            current = ""
        current += item
    lines.append(f"#L {current}")
    return "\n".join(lines) + "\n"
