"""Playground adapter: a Life-like grid that can start from a pattern.

The library's ``LifeLike`` starts from a soup, a blob, a single cell, or an array handed
to it. Here ``init`` has one more choice, ``pattern``, and ``pattern`` names a built-in or
a ``.rle``, ``.mc``, or ``.mc.gz`` file, as HashLife's does. Its live cells are centered on
a dead grid, which grows to leave them room (twice their size, up to the largest grid the
form allows), and the rule the pattern names is adopted.

A grid holds every one of its cells, and a pattern file can describe more of them than
memory holds, so a file is measured before any grid is made of it (``measure``): RLE
through the library's ``rle_measure``, Macrocell through a HashLife universe. ``advise``
turns the size into advice:

- past the largest grid (``GRID_LIMIT`` a side): only HashLife can run it;
- within it, but more than half of it (``ROOMY``) or a Macrocell file: HashLife is the
  better place, and the user chooses;
- otherwise nothing to say: it loads.

The registry makes that advice a ``Redirect``, which the engine offers before it builds.
"""

from __future__ import annotations

import dataclasses
import functools
import zlib
from pathlib import Path
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray

from heaton_life.ca import LifeLike, LifeLikeParams
from heaton_life.ca.hashlife import DEFAULT_MEMORY_MB, HashLife, HashLifeMemoryError
from heaton_life.ca.rulestring import compile_rule
from heaton_life.core.params import Params
from heaton_life.core.topology import Axis, Boundary, Topology
from heaton_life.init import BUILTIN_PATTERNS, place, rle_decode, rle_encode, rle_measure
from heaton_life.playground.hashlife_sim import BUILTIN_NAMES, PATTERN_FILTER, PATTERN_SUFFIXES

_LIBRARY = {f.name: f for f in dataclasses.fields(LifeLikeParams)}

GRID_LIMIT = int(_LIBRARY["width"].metadata["max"])
"""The largest grid side the form allows (the library's own range for width and height)."""
ROOMY = GRID_LIMIT // 2
"""A pattern wider or taller than this can't have a grid twice its size: little room."""
HEAVY = 100_000_000
"""Cells from which a grid's memory is worth a sentence: 100 MB of them, before the copies
that stepping and drawing make."""
RLE_SIZE_LIMIT = 8 * 2**20
"""Bytes of RLE read at most: about twice what the fullest GRID_LIMIT² pattern takes (one
character a cell). A larger file can't fit, and reading it would only take time."""


def _library_field(name: str, **metadata: object) -> Any:
    """The library's own field (default, range, label), so the two can't drift apart."""
    source = _LIBRARY[name]
    return dataclasses.field(default=source.default, metadata={**source.metadata, **metadata})


@dataclasses.dataclass(frozen=True)
class LifeLikeSimParams(Params):
    rule: str = _library_field("rule")
    width: int = _library_field("width")
    height: int = _library_field("height")
    init: str = _library_field("init", choices=[*_LIBRARY["init"].metadata["choices"], "pattern"])
    pattern: str = dataclasses.field(
        default="Gosper glider gun",
        metadata={
            "role": "file",
            "filter": PATTERN_FILTER,
            "label": "Pattern",
            "selects": {"init": "pattern"},  # choosing one is choosing to start from it
        },
    )
    density: float = _library_field("density")
    seed: int = _library_field("seed")
    boundary: str = _library_field("boundary")
    shift: int = _library_field("shift")
    axis: str = _library_field("axis")


# -- measuring a pattern ------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, eq=False)
class Measured:
    """What a pattern holds, found without making a grid of it."""

    name: str
    """The built-in's name or the file's, for messages."""
    macrocell: bool
    width: int | None = None
    """The live cells' bounding box; None when the file was too large even to read."""
    height: int | None = None
    rule: str | None = None
    """The rule it names, if it names one."""
    cells: NDArray[np.uint8] | None = None
    """That box as a grid of 0/1, when it fits the largest grid."""
    unread: str = ""
    """Why it wasn't read, as the rest of "<name> …"."""


def measure(pattern: str) -> Measured:
    """A built-in by name, or a pattern file. Raises ValueError for neither, for a file
    that can't be read, and for one with no live cells."""
    builtin = next((p for p in BUILTIN_PATTERNS if p.name == pattern), None)
    if builtin is not None and builtin.family == "lifelike":
        cells = builtin.cells()
        height, width = cells.shape
        return Measured(pattern, False, width, height, builtin.rule, cells)
    path = Path(pattern).expanduser()
    try:
        stat = path.stat()
    except OSError:
        raise ValueError(f"no built-in pattern or file named {pattern!r}") from None
    # Keyed by what the file is now: one edited since is measured again.
    return _measure_file(str(path), stat.st_mtime_ns, stat.st_size)


@functools.lru_cache(maxsize=4)
def _measure_file(name: str, _modified: int, size: int) -> Measured:
    path = Path(name)
    try:
        with path.open("rb") as file:
            head = file.read(64)
        # Recognized by content, as HashLife.from_file does: gzip, or the Macrocell header.
        if head[:2] == b"\x1f\x8b" or head.lstrip()[:4] == b"[M2]":
            return _measure_macrocell(path)
        if size > RLE_SIZE_LIMIT:
            return Measured(path.name, False, unread=f"is {size / 2**20:,.0f} MB of RLE")
        return _measure_rle(path.name, path.read_bytes().decode("latin-1"))
    except (OSError, EOFError, zlib.error) as exc:
        raise ValueError(f"cannot read {path.name}: {exc}") from exc


def _measure_macrocell(path: Path) -> Measured:
    try:
        universe = HashLife.from_file(path)
    except HashLifeMemoryError:
        unread = f"takes more than HashLife's default {DEFAULT_MEMORY_MB:,} MB just to read"
        return Measured(path.name, True, unread=unread)
    except ValueError as exc:
        raise ValueError(f"{path.name}: {exc}") from exc  # the reader's words, and whose
    box = universe.bounding_box()
    if box is None:
        raise ValueError(f"{path.name} has no live cells")
    x0, y0, x1, y1 = box
    width, height = x1 - x0 + 1, y1 - y0 + 1
    fits = width <= GRID_LIMIT and height <= GRID_LIMIT
    cells = universe.get_rect(x0, y0, x1, y1) if fits else None
    return Measured(path.name, True, width, height, universe.rule, cells)


def _measure_rle(name: str, text: str) -> Measured:
    """The live cells' box from the library's measure (spec/patterns.md "Extent"): a row
    of a billion dead cells, or a header that declares one, never becomes memory."""
    try:
        extent = rle_measure(text)
    except ValueError as exc:
        raise ValueError(f"{name}: {exc}") from exc  # the reader's words, and whose
    if extent.extended:
        raise ValueError(f"{name}: a multi-state RLE; a Life-like cell is dead or alive")
    if extent.live is None:
        raise ValueError(f"{name} has no live cells")
    x0, y0, x1, y1 = extent.live
    width, height = x1 - x0 + 1, y1 - y0 + 1
    cells: NDArray[np.uint8] | None = None
    if width <= GRID_LIMIT and height <= GRID_LIMIT:
        cells, _ = rle_decode(text, trim=True, max_cells=GRID_LIMIT * GRID_LIMIT)
    return Measured(name, False, width, height, extent.rule, cells)


# -- advice ---------------------------------------------------------------------------------


def _memory(cells: int) -> str:
    """A grid's size in memory, a byte a cell, in round figures."""
    value = float(cells)
    for unit in ("bytes", "KB", "MB", "GB", "TB", "PB"):
        if value < 1000:
            return (
                f"{value:.1f} {unit}" if value < 10 and unit != "bytes" else f"{value:.0f} {unit}"
            )
        value /= 1000
    return f"{value:,.0f} EB"


def _grid() -> str:
    return f"{GRID_LIMIT:,} × {GRID_LIMIT:,}"


def too_large(measured: Measured) -> str | None:
    """Why Life-like can't hold the pattern at all, or None if it can."""
    if measured.cells is not None:
        return None
    if measured.width is None or measured.height is None:
        return (
            f"{measured.name} {measured.unread}, more than any pattern that fits "
            f"Life-like's largest grid ({_grid()}) needs."
        )
    width, height = measured.width, measured.height
    reason = (
        f"{measured.name} is {width:,} × {height:,} cells, and Life-like's largest grid is "
        f"{_grid()}."
    )
    if width * height >= HEAVY:
        reason += (
            f" A grid keeps every cell in memory: one this size would take "
            f"{_memory(width * height)} for its cells alone, and several times that to step "
            f"and draw them."
        )
    return reason


def better_elsewhere(measured: Measured) -> str | None:
    """Why HashLife suits a pattern that Life-like can hold, or None if it doesn't."""
    width, height = measured.width, measured.height
    if measured.cells is None or width is None or height is None:
        return None
    size = f"{width:,} × {height:,} cells"
    if width > ROOMY or height > ROOMY:
        kind = "a Macrocell file, HashLife's format, and " if measured.macrocell else ""
        return (
            f"{measured.name} is {kind}{size}. It fits Life-like's largest grid ({_grid()}), "
            f"but takes more than half its width or height, which leaves it little room to "
            f"run before it meets the edges."
        )
    if measured.macrocell:
        return (
            f"{measured.name} is a Macrocell file, HashLife's format ({size}). Life-like "
            f"can take its cells, centered on a grid, but not their place on the plane or "
            f"their generation."
        )
    return None


@dataclasses.dataclass(frozen=True)
class Advice:
    """That a pattern belongs in HashLife."""

    required: bool
    """Life-like can't hold it at all (else: it can, and HashLife suits it better)."""
    reason: str


def advise(params: Params) -> Advice | None:
    """Whether the params' pattern belongs in HashLife: None for a grid that doesn't start
    from a file, and for a file that Life-like suits. Raises ValueError where ``measure``
    does."""
    assert isinstance(params, LifeLikeSimParams)
    if params.init != "pattern" or params.pattern in BUILTIN_NAMES:
        return None
    measured = measure(params.pattern)
    reason = too_large(measured)
    if reason is not None:
        return Advice(True, reason)
    reason = better_elsewhere(measured)
    return Advice(False, reason) if reason is not None else None


# -- the sim ----------------------------------------------------------------------------------


def _topology(params: LifeLikeSimParams) -> dict[str, Any]:
    """The form's topology as LifeLike's keyword arguments (spec/topology.md)."""
    boundary = cast(Boundary, params.boundary)
    return {"boundary": boundary, "shift": params.shift, "axis": cast(Axis, params.axis)}


def _with_room(side: int, cells: int) -> int:
    """The grid side for a pattern ``cells`` across: twice it, if the grid isn't already."""
    return max(side, min(GRID_LIMIT, 2 * cells))


def validate(params: Params) -> tuple[str, str] | None:
    """The first field the engine would reject, as (field, message), or None."""
    assert isinstance(params, LifeLikeSimParams)
    try:
        compile_rule(params.rule)
    except ValueError as exc:
        return ("rule", str(exc))
    try:
        topology = Topology(cast(Boundary, params.boundary), params.shift, cast(Axis, params.axis))
        topology.check(params.width, params.height)
    except ValueError as exc:
        return ("boundary", str(exc))
    pattern = params.pattern
    named = pattern in BUILTIN_NAMES or Path(pattern).expanduser().is_file()
    if params.init == "pattern" and not named:
        return ("pattern", f"no built-in pattern or file named {pattern!r}")
    return None


class LifeLikeSim:
    """A Life-like grid, and the params that describe it to the form."""

    def __init__(self, life: LifeLike, params: LifeLikeSimParams) -> None:
        self._life = life
        self.params = params

    @classmethod
    def build(cls, params: Params) -> LifeLikeSim:
        """A fresh grid. From a pattern: its cells centered, the grid grown to give them
        room, and its rule adopted."""
        assert isinstance(params, LifeLikeSimParams)
        size = (params.width, params.height)
        if params.init != "pattern":
            life = LifeLike(
                params.rule,
                size=size,
                init=params.init,
                density=params.density,
                seed=params.seed,
                **_topology(params),
            )
            return cls(life, params)
        measured = measure(params.pattern)
        if measured.cells is None:
            raise ValueError(too_large(measured))  # the engine asks advise() first
        pattern_height, pattern_width = measured.cells.shape
        size = (_with_room(params.width, pattern_width), _with_room(params.height, pattern_height))
        rule = measured.rule or params.rule
        life = LifeLike(rule, size=size, init=place(measured.cells, size), **_topology(params))
        return cls(life, params.replace(rule=rule, width=size[0], height=size[1]))

    def apply(self, params: LifeLikeSimParams) -> None:
        """Rule and topology in place: the cells stay."""
        state = np.asarray(self._life.state, dtype=np.uint8)
        height, width = state.shape
        self._life = LifeLike(params.rule, size=(width, height), init=state, **_topology(params))
        self.params = params

    # -- Simulation protocol ------------------------------------------------------------

    def step(self, n: int = 1) -> None:
        self._life.step(n)

    def reset(self, seed: int | None = None) -> None:
        self._life.reset(seed)

    @property
    def generation(self) -> int:
        return self._life.generation

    @property
    def state(self) -> NDArray[np.uint8]:
        return self._life.state

    def frame(self) -> NDArray[np.uint8]:
        return self._life.frame()

    # -- pattern files ------------------------------------------------------------------

    def pattern_file_name(self) -> str:
        """A suggested name for Save pattern: the pattern's name (or the rule's, for a
        grid that didn't start from one) and the generation."""
        p = self.params
        stem = Path(p.pattern).name if p.init == "pattern" else "life-" + p.rule.replace("/", "")
        for suffix in PATTERN_SUFFIXES[::-1]:  # .mc.gz before .mc
            if stem.lower().endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        stem = "-".join(stem.split()) or "pattern"
        return f"{stem}-gen{self.generation}.rle"

    def save_pattern(self, path: str | Path) -> Path:
        """Write the live cells' bounding box as RLE; a name without ``.rle`` gets it."""
        state = self._life.state
        rows, columns = np.flatnonzero(state.any(axis=1)), np.flatnonzero(state.any(axis=0))
        if rows.size == 0:
            raise ValueError("no live cells to save")
        box = state[rows[0] : rows[-1] + 1, columns[0] : columns[-1] + 1]
        target = Path(path)
        if not target.name.lower().endswith(".rle"):
            target = target.with_name(target.name + ".rle")
        target.write_text(rle_encode(box, self._life.params.rule), encoding="ascii", newline="\n")
        return target
