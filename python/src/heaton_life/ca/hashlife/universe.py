"""The HashLife universe (spec/hashlife.md): a Life-like rule on an unbounded plane.

Cells live in a hash-consed quadtree whose root is centered on the origin. Cell (x, y)
sits at tree position (x, y − 1) — the placement Macrocell files use, so they land on the
same cells here as in other readers — and every coordinate, generation, and population is
a Python int. Under a rule with B0 the cells are those that differ from the background
(spec/hashlife.md "Rules with B0").
"""

from __future__ import annotations

import dataclasses
import functools
import operator
import weakref
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import numpy as np
from numpy.typing import NDArray

from heaton_life.ca.hashlife.leaves import (
    array_blocks,
    base_case,
    columns,
    crop,
    inner,
    leaf_cells,
    mirror_columns,
    mirror_rows,
    phase_tables,
    rect_mask,
    turn_ccw,
    turn_cw,
)
from heaton_life.ca.hashlife.render import TILE_CACHE_LIMIT, RenderMode
from heaton_life.ca.hashlife.render import render as render_frame
from heaton_life.ca.hashlife.store import NODE_BYTES, Abort, NodeStore, Tables
from heaton_life.ca.hashlife.view import LifeView
from heaton_life.ca.rulestring import compile_rule
from heaton_life.core.params import Params
from heaton_life.init.metadata import PatternMetadata
from heaton_life.init.patterns import turn_center, turned_rect
from heaton_life.init.seeding import soup

if TYPE_CHECKING:
    from heaton_life.ca.hashlife.files import PatternSnapshot

EDIT_LIMIT = 1_000_000_000
"""Editing reaches cells with |x| ≤ EDIT_LIMIT and |y| ≤ EDIT_LIMIT."""
MAX_LEVEL = 512
"""The deepest tree (spec/hashlife.md "Depth"): every live cell lies within ±2^511, and
the walks below recurse at most once per level, well inside Python's recursion limit."""
DEFAULT_MEMORY_MB = 500
MIN_MEMORY_MB = 10
PasteMode = Literal["copy", "or", "xor", "and"]
PASTE_MODES: tuple[PasteMode, ...] = ("copy", "or", "xor", "and")
_MIN_LEVEL = 4  # the root is always an internal node
_MIN_STEP_LEVEL = 6  # sub-steps check containment on the root's great-grandchildren
_TURN_LEVEL = 33  # a centered root this tall holds the editing box with room for any shift

# A node turned or mirrored about its own center: the leaf transform, and which old child
# lands in each new quadrant (NW, NE, SW, SE).
_TRANSFORMS = {
    "cw": (turn_cw, (2, 0, 3, 1)),
    "ccw": (turn_ccw, (1, 3, 0, 2)),
    "h": (mirror_columns, (1, 0, 3, 2)),
    "v": (mirror_rows, (2, 3, 0, 1)),
}

# Extremes for the bounding box: (near children, far children, use min) per edge; the far
# pair sits half a node further along the axis.
_EDGES = {
    "min_x": ((0, 2), (1, 3), True),
    "max_x": ((1, 3), (0, 2), False),
    "min_y": ((0, 1), (2, 3), True),
    "max_y": ((2, 3), (0, 1), False),
}


class HashLifeMemoryError(MemoryError):
    """A step could not fit even one generation into ``max_memory_mb``."""


class StepCanceled(Exception):
    """``cancel()`` stopped a step; the universe holds the last completed sub-step."""


@dataclasses.dataclass(frozen=True)
class HashLifeParams(Params):
    rule: str = dataclasses.field(default="B3/S23", metadata={"label": "Rule (B/S)"})
    max_memory_mb: int = dataclasses.field(
        default=DEFAULT_MEMORY_MB,
        metadata={"min": MIN_MEMORY_MB, "max": 100_000_000, "label": "Max memory (MB)"},
    )


class Snapshot:
    """A universe's cells and generation at one moment (spec/hashlife.md "Snapshots")."""

    __slots__ = ("__weakref__", "_generation", "_level", "_owner", "_released", "_root")

    def __init__(self, owner: HashLife, root: int, level: int, generation: int) -> None:
        self._owner = weakref.ref(owner)
        self._root = root
        self._level = level
        self._generation = generation
        self._released = False

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def released(self) -> bool:
        """True once ``release()`` has let go of the snapshot's nodes."""
        return self._released

    def release(self) -> None:
        """Let go of this snapshot's nodes now (spec/hashlife.md "Snapshots"): the next
        collection may free whatever nothing else holds. A released snapshot holds no cells,
        so restoring it is an error; releasing it again does nothing."""
        if self._released:
            return
        self._released = True
        owner = self._owner()
        if owner is not None:
            owner._snapshots.discard(self)


@dataclasses.dataclass(frozen=True)
class SnapshotFootprint:
    """What a list of snapshots holds in a universe's store beyond its current state
    (spec/hashlife.md "What snapshots hold"). The counts are nodes, exact and the same in
    every port; ``estimated_bytes`` is this port's estimate of ``nodes`` in memory."""

    universe_nodes: int
    """The nodes of the universe's current state."""
    added: tuple[int, ...]
    """For each snapshot in order, the nodes it holds that neither the current state nor an
    earlier snapshot in the list holds (0 for a released snapshot)."""
    nodes: int
    """``sum(added)``: the nodes the list holds beyond the current state."""
    estimated_bytes: int
    """``nodes`` at this store's size of a node (``NODE_BYTES``)."""


@functools.lru_cache(maxsize=16)
def _tables(rule: str) -> Tables:
    """The base cases a universe of the canonical ``rule`` steps by, for the generations
    that start at an even generation and at an odd one (spec/hashlife.md "Rules with B0"):
    the rule's own table without B0; its black/white reversal (phase table P₁) at every
    generation with B0 and Smax; and P₀ then P₁, alternating, with B0 but without Smax.
    The pair holds one table twice unless the phases alternate."""
    compiled = compile_rule(rule)
    if not compiled.has_b0:
        own = base_case(compiled.table)
        return own, own
    p0, p1 = phase_tables(compiled.table)
    odd = base_case(p1)
    if compiled.has_smax:
        return odd, odd
    return base_case(p0), odd


def _hashlife_rule(rule: str, *, presets: bool = True) -> str:
    """The canonical form of a rule the universe can run: any Life-like rule, B0 included
    (spec/hashlife.md "Rules with B0"). ``presets`` lets a preset name (``life``) stand
    for its rule, as where a person types one; a rule read from a file passes
    ``presets=False``, since a file names its rule, never a preset (spec/formats.md
    "Reading into the unbounded universe")."""
    return compile_rule(rule, presets=presets).canonical


def _budget(max_memory_mb: int) -> int:
    mb = operator.index(max_memory_mb)
    if mb < MIN_MEMORY_MB:
        raise ValueError(f"max_memory_mb must be at least {MIN_MEMORY_MB}, got {mb}")
    return mb << 20


def _ints(*values: int) -> tuple[int, ...]:
    """Coordinates as Python ints. NumPy integers (any ``__index__`` type) then behave like
    ints in the unbounded bit arithmetic below instead of overflowing at 64 bits; floats
    and other non-integers raise TypeError."""
    return tuple(operator.index(v) for v in values)


def check_box(x0: int, y0: int, x1: int, y1: int) -> None:
    """Raise ValueError unless every corner lies in the editing box."""
    for v in (x0, y0, x1, y1):
        if not -EDIT_LIMIT <= v <= EDIT_LIMIT:
            raise ValueError(
                f"({x0}, {y0})..({x1}, {y1}) reaches outside the editing box "
                f'|x|, |y| <= {EDIT_LIMIT:,} (spec/hashlife.md "Editing")'
            )


def _disjoint(nx: int, ny: int, size: int, rect: tuple[int, int, int, int]) -> bool:
    x0, y0, x1, y1 = rect
    return nx > x1 or nx + size <= x0 or ny > y1 or ny + size <= y0


def _covers(nx: int, ny: int, size: int, rect: tuple[int, int, int, int]) -> bool:
    x0, y0, x1, y1 = rect
    return x0 <= nx and nx + size - 1 <= x1 and y0 <= ny and ny + size - 1 <= y1


def _leaf_mask(nx: int, ny: int, rect: tuple[int, int, int, int]) -> int:
    x0, y0, x1, y1 = rect
    return rect_mask(max(x0 - nx, 0), min(x1 - nx, 7), max(y0 - ny, 0), min(y1 - ny, 7))


def _leaf_edge(b: int, which: str) -> int:
    """One extreme of a non-empty leaf's live cells, as a column or row 0..7."""
    lowest = _EDGES[which][2]
    if which in ("min_x", "max_x"):
        cols = columns(b)
        return (cols & -cols).bit_length() - 1 if lowest else cols.bit_length() - 1
    return ((b & -b).bit_length() - 1 if lowest else b.bit_length() - 1) >> 3


def _check_count(n: int) -> None:
    """Raise ValueError unless ``step`` can take ``n`` generations (0 ≤ n < 2^510)."""
    if n < 0:
        raise ValueError(f"cannot step backward ({n} generations)")
    if n.bit_length() > MAX_LEVEL - 2:
        raise ValueError(
            f"a step of 2^{n.bit_length() - 1} generations or more needs a tree deeper "
            f"than level {MAX_LEVEL}; step(n) takes n < 2^{MAX_LEVEL - 2} "
            '(spec/hashlife.md "Depth")'
        )


class HashLife:
    """An unbounded Life-like universe. See spec/hashlife.md for the full contract. Every
    Life-like rule runs, B0 included: its universe holds the cells that differ from the
    background (``background``; spec/hashlife.md "Rules with B0")."""

    def __init__(self, rule: str = "B3/S23", *, max_memory_mb: int = DEFAULT_MEMORY_MB) -> None:
        self._rule = _hashlife_rule(rule)
        self._max_memory_mb = operator.index(max_memory_mb)
        self._store = NodeStore(_tables(self._rule), _budget(max_memory_mb))
        self._level = _MIN_LEVEL
        self._root = self._store.empty(_MIN_LEVEL)
        self._generation = 0
        self._snapshots: weakref.WeakSet[Snapshot] = weakref.WeakSet()
        self._tiles: dict[tuple[int, str], dict[int, NDArray[np.uint8]]] = {}
        self._tiles_epoch = 0

    @classmethod
    def from_params(cls, params: HashLifeParams) -> HashLife:
        return cls(params.rule, max_memory_mb=params.max_memory_mb)

    @property
    def params(self) -> HashLifeParams:
        return HashLifeParams(rule=self._rule, max_memory_mb=self._max_memory_mb)

    def __repr__(self) -> str:
        return (
            f"HashLife(rule={self._rule!r}, generation={self._generation}, "
            f"population={self.population})"
        )

    # -- configuration ------------------------------------------------------------------

    @property
    def rule(self) -> str:
        return self._rule

    @rule.setter
    def rule(self, rule: str) -> None:
        """Change rules in place: the cells stay, cached results go. Under a rule with B0
        the cells stand for the plane the new rule's background says (spec/hashlife.md
        "Rules with B0")."""
        canonical = _hashlife_rule(rule)
        if canonical != self._rule:
            self._rule = canonical
            self._store.use_rule(_tables(canonical))

    @property
    def max_memory_mb(self) -> int:
        return self._max_memory_mb

    @max_memory_mb.setter
    def max_memory_mb(self, max_memory_mb: int) -> None:
        self._store.budget = _budget(max_memory_mb)
        self._max_memory_mb = operator.index(max_memory_mb)

    @property
    def memory_used(self) -> int:
        """The node store's estimated size in bytes (the budget's measure, not the RSS)."""
        return self._store.memory_used()

    @property
    def node_count(self) -> int:
        return len(self._store.table)

    @property
    def collections(self) -> int:
        """Garbage collections run so far."""
        return self._store.collections

    # -- observables --------------------------------------------------------------------

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def population(self) -> int:
        """The universe's live cells: under a rule with B0, the cells that differ from the
        background, the plane's dead cells where the background is alive."""
        return self._store.population(self._root, self._level)

    @property
    def background(self) -> int:
        """The background at the current generation, 0 or 1 (spec/hashlife.md "Rules with
        B0"): what the plane is outside the universe's cells, always 0 for a rule without
        B0. The plane's cell (x, y) is ``get_cell(x, y) ^ background``."""
        return compile_rule(self._rule).background(self._generation)

    def bounding_box(self) -> tuple[int, int, int, int] | None:
        """(x0, y0, x1, y1): the inclusive extremes of the live cells, or None if empty."""
        if self.population == 0:
            return None
        origin = -(1 << (self._level - 1))
        x0 = origin + self._edge("min_x")
        x1 = origin + self._edge("max_x")
        y0 = origin + self._edge("min_y") + 1
        y1 = origin + self._edge("max_y") + 1
        return x0, y0, x1, y1

    def population_in(self, x0: int, y0: int, x1: int, y1: int) -> int:
        """Live cells in the inclusive rectangle; any coordinates."""
        x0, y0, x1, y1 = _ints(x0, y0, x1, y1)
        if x1 < x0 or y1 < y0:
            return 0
        origin = -(1 << (self._level - 1))
        return self._count(self._root, self._level, origin, origin, (x0, y0 - 1, x1, y1 - 1))

    def bounding_box_in(
        self, x0: int, y0: int, x1: int, y1: int
    ) -> tuple[int, int, int, int] | None:
        """(x0, y0, x1, y1): the inclusive extremes of the live cells inside the inclusive
        rectangle, or None when it holds none — where Shrink Selection moves a selection.
        Any coordinates."""
        x0, y0, x1, y1 = _ints(x0, y0, x1, y1)
        if x1 < x0 or y1 < y0:
            return None
        origin = -(1 << (self._level - 1))
        rect = (x0, y0 - 1, x1, y1 - 1)
        found = []
        for which in ("min_x", "max_x", "min_y", "max_y"):
            edge = self._extreme_in(self._root, self._level, origin, origin, rect, which, {})
            if edge is None:
                return None
            found.append(edge)
        return found[0], found[2] + 1, found[1], found[3] + 1

    def get_cell(self, x: int, y: int) -> int:
        x, y = _ints(x, y)
        check_box(x, y, x, y)
        k = self._level
        half = 1 << (k - 1)
        tx, ty = x + half, y - 1 + half
        if not (0 <= tx < 2 * half and 0 <= ty < 2 * half):
            return 0
        data = self._store.data
        n = self._root
        while k > 3:
            k -= 1
            half = 1 << k
            i = 0
            if tx >= half:
                tx -= half
                i = 1
            if ty >= half:
                ty -= half
                i += 2
            n = data[n][i]
        return (data[n] >> (ty * 8 + tx)) & 1  # type: ignore[no-any-return]

    def get_rect(self, x0: int, y0: int, x1: int, y1: int) -> NDArray[np.uint8]:
        """The inclusive rectangle as a (y1 − y0 + 1) × (x1 − x0 + 1) array of 0/1."""
        x0, y0, x1, y1 = _ints(x0, y0, x1, y1)
        check_box(x0, y0, x1, y1)
        return self._cells(x0, y0, x1, y1)

    def _cells(self, x0: int, y0: int, x1: int, y1: int) -> NDArray[np.uint8]:
        """``get_rect`` anywhere on the plane, for readers that measured the rectangle."""
        if x1 < x0 or y1 < y0:
            raise ValueError(f"empty rectangle ({x0}, {y0})..({x1}, {y1})")
        out = np.zeros((y1 - y0 + 1, x1 - x0 + 1), dtype=np.uint8)
        origin = -(1 << (self._level - 1))
        rect = (x0, y0 - 1, x1, y1 - 1)
        self._extract(self._root, self._level, origin, origin, rect, out)
        return out

    # -- evolution ----------------------------------------------------------------------

    def step(self, n: int = 1) -> None:
        """Advance exactly ``n`` generations (0 ≤ n < 2^510). Raises ``StepCanceled`` if
        ``cancel()`` stops it, ``HashLifeMemoryError`` if one generation can't fit, and
        ValueError if a sub-step needs a tree deeper than ``MAX_LEVEL``."""
        n = operator.index(n)
        _check_count(n)
        self._store.cancel_requested = False
        for j in self._sub_steps(n):
            self._advance(j)

    def _sub_steps(self, n: int) -> list[int]:
        """The sub-steps of ``step(n)`` as exponents j, in order (spec/hashlife.md
        "Sub-steps"): each set bit of n. When a rule with B0 alternates its phases, every
        sub-step of two or more generations starts at an even generation instead ("Rules
        with B0"): one generation first from an odd generation, then each set bit j ≥ 1 of
        what remains, then the last single generation, if one remains."""
        steps: list[int] = []
        if self._store.alternates:
            if n and self._generation & 1:
                steps.append(0)
                n -= 1
            last = n & 1
            n -= last
        else:
            last = 0
        j = 0
        while n:
            if n & 1:
                steps.append(j)
            n >>= 1
            j += 1
        if last:
            steps.append(0)
        return steps

    def cancel(self) -> None:
        """Ask a running ``step`` (on another thread) to stop at a sub-step boundary."""
        self._store.cancel_requested = True

    def _advance(self, j: int) -> None:
        """Advance 2^j generations: collect when three-quarters full, try twice, then
        split into two halves (spec/hashlife.md "Memory"). Halves wait on a list rather
        than the call stack, so splitting never adds to the recursion of a deep step."""
        store = self._store
        pending = [j]
        while pending:
            j = pending.pop()
            for _ in range(2):
                if store.memory_used() > store.budget * 3 // 4:
                    self._collect()
                try:
                    self._sub_step(j)
                except Abort as abort:
                    if abort.canceled:
                        raise StepCanceled(
                            f"canceled; the universe is at generation {self._generation}"
                        ) from None
                else:
                    break
            else:
                if j == 0:
                    self._collect()  # the abandoned attempts are garbage; the cells are unchanged
                    raise HashLifeMemoryError(
                        f"one generation does not fit in max_memory_mb={self._max_memory_mb} "
                        f"(the pattern itself takes about {store.memory_used() >> 20} MB of "
                        "it); raise the budget"
                    )
                pending += (j - 1, j - 1)

    def _sub_step(self, j: int) -> None:
        store = self._store
        need = max(j + 3, _MIN_STEP_LEVEL)
        while self._level < need or not self._centered():
            if self._level == MAX_LEVEL:
                raise ValueError(
                    f"the pattern has spread too far to step 2^{j} generations within a "
                    f'level-{MAX_LEVEL} tree (spec/hashlife.md "Depth"); the universe is at '
                    f"generation {self._generation}"
                )
            self._expand()
        store.use_step(j, self._generation & 1)
        store.guard = True
        try:
            root = store.stepped(self._root, self._level, j)
        finally:
            store.guard = False
        self._root = root
        self._level -= 1
        self._generation += 1 << j

    def _centered(self) -> bool:
        """Every live cell lies in the centered square of side 2^(k−2)."""
        store = self._store
        data = store.data
        k = self._level
        a, b, c, d = data[self._root]
        inner = (data[data[a][3]][3], data[data[b][2]][2], data[data[c][1]][1], data[data[d][0]][0])
        held = sum(store.population(x, k - 3) for x in inner)
        return held == store.population(self._root, k)

    def _expand(self) -> None:
        """Wrap the root in a node twice its size, centered, with empty margins."""
        store = self._store
        k = self._level
        e = store.empty(k - 1)
        join = store.join
        a, b, c, d = store.data[self._root]
        self._root = join(join(e, e, e, a), join(e, e, b, e), join(e, c, e, e), join(d, e, e, e))
        self._level = k + 1

    def _collect(self) -> None:
        roots = [(self._root, self._level)]
        roots += [(s._root, s._level) for s in self._snapshots]
        self._store.collect(roots)

    def collect_garbage(self) -> None:
        """Free every node unreachable from the current state and live snapshots."""
        self._collect()

    # -- editing ------------------------------------------------------------------------

    def set_cell(self, x: int, y: int, alive: bool | int) -> None:
        x, y = _ints(x, y)
        check_box(x, y, x, y)
        self._contain(x, y - 1, x, y - 1)
        half = 1 << (self._level - 1)
        bit = 1 if alive else 0
        self._root = self._set(self._root, self._level, x + half, y - 1 + half, bit)

    def set_rect(
        self, x: int, y: int, cells: NDArray[np.generic], mode: PasteMode = "copy"
    ) -> None:
        """Land ``cells`` (h × w, nonzero = alive) with its top-left cell at (x, y)."""
        if mode not in PASTE_MODES:
            raise ValueError(f"unknown paste mode {mode!r}; expected one of {PASTE_MODES}")
        x, y = _ints(x, y)
        cells = np.asarray(cells)
        if cells.ndim != 2 or 0 in cells.shape:
            raise ValueError(f"cells must be a non-empty 2-D array, got shape {cells.shape}")
        height, width = cells.shape
        check_box(x, y, x + width - 1, y + height - 1)
        rect = (x, y - 1, x + width - 1, y + height - 2)
        self._paste_blocks(array_blocks(cells, x, y - 1), rect, mode)

    def clear_rect(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """Every cell of the inclusive rectangle dies."""
        x0, y0, x1, y1 = _ints(x0, y0, x1, y1)
        check_box(x0, y0, x1, y1)
        if x1 < x0 or y1 < y0:
            return
        origin = -(1 << (self._level - 1))
        rect = (x0, y0 - 1, x1, y1 - 1)
        self._root = self._clear(self._root, self._level, origin, origin, rect)

    def fill_random(self, x0: int, y0: int, x1: int, y1: int, density: float, seed: int) -> None:
        """Replace the inclusive rectangle with lifelike's PCG32 soup of the same size."""
        x0, y0, x1, y1, seed = _ints(x0, y0, x1, y1, seed)
        check_box(x0, y0, x1, y1)
        if x1 < x0 or y1 < y0:
            raise ValueError(f"empty rectangle ({x0}, {y0})..({x1}, {y1})")
        cells = soup((x1 - x0 + 1, y1 - y0 + 1), density=density, seed=seed)
        self.set_rect(x0, y0, cells, "copy")

    def clear_outside(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """Every cell outside the inclusive rectangle dies, wherever it lies."""
        rect = self._edit_rect(x0, y0, x1, y1)
        origin = -(1 << (self._level - 1))
        self._root = self._keep(self._root, self._level, origin, origin, rect)

    def rotate_rect(
        self, x0: int, y0: int, x1: int, y1: int, *, clockwise: bool = True
    ) -> tuple[int, int, int, int]:
        """Turn the inclusive rectangle and its cells a quarter about its center, in place,
        and return the rectangle they land on (spec/hashlife.md "Rectangle transforms").
        The new rectangle takes the turned cells, live or dead; the rest of the old one
        dies. Works on the tree: no dense copy, whatever the area or population."""
        self._edit_rect(x0, y0, x1, y1)
        x0, y0, x1, y1 = _ints(x0, y0, x1, y1)
        s, d = turn_center(x0, y0, x1, y1)
        new = turned_rect(x0, y0, x1, y1, clockwise=clockwise)  # what a grid's turn lands on
        # The shift in tree coordinates, after turning about the root's center.
        shift = (s, d - 1) if clockwise else (1 - d, s)
        check_box(*new)
        self._move_rect((x0, y0, x1, y1), new, "cw" if clockwise else "ccw", shift)
        return new

    def flip_rect(self, x0: int, y0: int, x1: int, y1: int, *, horizontal: bool = True) -> None:
        """Mirror the inclusive rectangle's cells in place: left-right (x → x0 + x1 − x) or,
        with ``horizontal=False``, top-bottom (y → y0 + y1 − y). No dense copy is made."""
        self._edit_rect(x0, y0, x1, y1)
        x0, y0, x1, y1 = _ints(x0, y0, x1, y1)
        rect = (x0, y0, x1, y1)
        if horizontal:
            self._move_rect(rect, rect, "h", (x0 + x1 + 1, 0))
        else:
            self._move_rect(rect, rect, "v", (0, y0 + y1 - 1))

    def advance_selection(self, x0: int, y0: int, x1: int, y1: int, n: int) -> None:
        """Evolve the inclusive rectangle ``n`` generations as an isolated plane (cells
        outside it dead at the start) and clip the result to it; the outside and the
        generation are untouched. Raises what ``step`` raises, leaving the universe as it
        was (spec/hashlife.md "Advancing part of the universe"). Under a rule with B0 the
        cells evolved and put back are the universe's, as ``step`` gives them."""
        self._advance_region(x0, y0, x1, y1, n, outside=False)

    def advance_outside(self, x0: int, y0: int, x1: int, y1: int, n: int) -> None:
        """Evolve everything outside the inclusive rectangle ``n`` generations as if the
        rectangle were empty; the rectangle keeps its cells and the generation stays. Raises
        what ``step`` raises, leaving the universe as it was."""
        self._advance_region(x0, y0, x1, y1, n, outside=True)

    def set_generation(self, generation: int) -> None:
        """Set the generation counter to any integer ≥ 0; no cell changes. When a rule with
        B0 alternates its phases, the other parity swaps live and dead across the plane the
        cells stand for (spec/hashlife.md "Rules with B0")."""
        generation = operator.index(generation)
        if generation < 0:
            raise ValueError(f"a generation is never negative, got {generation}")
        self._generation = generation

    def clear(self) -> None:
        self._level = _MIN_LEVEL
        self._root = self._store.empty(_MIN_LEVEL)

    # -- snapshots ----------------------------------------------------------------------

    def snapshot(self) -> Snapshot:
        return self._snapshot_at(self._root, self._level, self._generation)

    def _snapshot_at(self, root: int, level: int, generation: int) -> Snapshot:
        """A snapshot of any tree in this universe's store, kept alive like any other."""
        snap = Snapshot(self, root, level, generation)
        self._snapshots.add(snap)
        return snap

    def restore(self, snapshot: Snapshot) -> None:
        if snapshot._owner() is not self:
            raise ValueError("snapshot belongs to another universe")
        if snapshot._released:
            raise ValueError("the snapshot was released and holds no cells")
        self._root = snapshot._root
        self._level = snapshot._level
        self._generation = snapshot._generation

    def measure_snapshots(self, snapshots: Iterable[Snapshot]) -> SnapshotFootprint:
        """What ``snapshots`` hold beyond the current state, in nodes (spec/hashlife.md "What
        snapshots hold"): the current state's own nodes, each snapshot's addition to the
        state's and the earlier snapshots' nodes, and their sum. The last k snapshots' counts
        add up to what releasing them frees, so a history listed newest first says what
        letting go of its oldest points would free."""
        listed = list(snapshots)
        for snapshot in listed:
            if snapshot._owner() is not self:
                raise ValueError("snapshot belongs to another universe")
        seen: set[int] = set()
        universe_nodes = self._count_new(*self._minimal(), seen)
        added = tuple(
            0 if s._released else self._count_new(*self._minimal_of(s._root, s._level), seen)
            for s in listed
        )
        nodes = sum(added)
        return SnapshotFootprint(universe_nodes, added, nodes, nodes * NODE_BYTES)

    def _count_new(self, root: int, level: int, seen: set[int]) -> int:
        """The non-empty nodes of tree (root, level) that ``seen`` lacks, added to it."""
        store = self._store
        data = store.data
        count = 0
        stack = [(root, level)]
        while stack:
            n, k = stack.pop()
            if n in seen or n == store.empty(k):
                continue
            seen.add(n)
            count += 1
            if k > 3:
                a, b, c, d = data[n]
                k -= 1
                stack += ((a, k), (b, k), (c, k), (d, k))
        return count

    # -- frames -----------------------------------------------------------------------------

    def render(
        self, view: LifeView, size: tuple[int, int], mode: RenderMode = "any"
    ) -> NDArray[np.uint8]:
        """The (height, width) uint8 frame of ``view``: 0/255, or block density zoomed out."""
        width, height = _ints(*size)
        return render_frame(self, view, (width, height), mode)

    def _tile_cache(self, s: int, mode: str) -> dict[int, NDArray[np.uint8]]:
        """Rendered tiles by node id; collection reuses ids, so it empties the cache."""
        stale = self._tiles_epoch != self._store.collections
        if stale or sum(len(v) for v in self._tiles.values()) > TILE_CACHE_LIMIT:
            self._tiles = {}
            self._tiles_epoch = self._store.collections
        return self._tiles.setdefault((s, mode), {})

    # -- files ------------------------------------------------------------------------------

    @classmethod
    def from_rle(cls, text: str, *, max_memory_mb: int = DEFAULT_MEMORY_MB) -> HashLife:
        """Two-state RLE; ``#CXRLE Pos=x,y Gen=n`` places it and sets the generation."""
        from heaton_life.ca.hashlife.rle import read_rle

        return read_rle(text, max_memory_mb=max_memory_mb)

    @classmethod
    def from_macrocell(
        cls, source: str | bytes, *, max_memory_mb: int = DEFAULT_MEMORY_MB
    ) -> HashLife:
        """Macrocell text or bytes (gzip-compressed bytes too), placed by tree coordinates."""
        from heaton_life.ca.hashlife.macrocell import read_macrocell

        return read_macrocell(source, max_memory_mb=max_memory_mb)

    @classmethod
    def from_file(cls, path: str | Path, *, max_memory_mb: int = DEFAULT_MEMORY_MB) -> HashLife:
        """A pattern file in any two-state format, gzip-compressed or not, recognized by its
        content (spec/formats.md); ``read_universe`` gives its metadata too."""
        from heaton_life.ca.hashlife.files import read_universe

        return read_universe(Path(path).read_bytes(), max_memory_mb=max_memory_mb).universe

    def read_snapshot(self, source: bytes | bytearray | memoryview | str) -> PatternSnapshot:
        """Read a pattern file of any two-state format into this universe's own store
        (spec/formats.md "Reading into a universe that exists"): a snapshot of its cells and
        generation, with its format, rule, metadata and a timeline's frames. The file is read
        as ``read_universe`` reads it, but the universe's state, rule and earlier snapshots
        stay as they were; restoring the snapshot is the caller's to do."""
        from heaton_life.ca.hashlife.files import read_snapshot

        return read_snapshot(self, source)

    def to_rle(self, metadata: PatternMetadata | None = None) -> str:
        """RLE of the bounding box behind a ``#CXRLE`` line (and ``metadata``'s lines);
        inside the editing box only."""
        from heaton_life.ca.hashlife.rle import write_rle

        return write_rle(self, metadata)

    def to_macrocell(self, metadata: PatternMetadata | None = None) -> str:
        """The canonical Macrocell text: the whole state, any size, in one string, with
        ``metadata``'s lines when given."""
        from heaton_life.ca.hashlife.macrocell import write_macrocell

        return write_macrocell(self, metadata)

    def save(self, path: str | Path, metadata: PatternMetadata | None = None) -> None:
        """Write by extension: ``.rle``, ``.mc``, or ``.mc.gz``, with ``metadata`` if given.
        The text is UTF-8 (ASCII unless the metadata isn't)."""
        target = Path(path)
        name = target.name.lower()
        if name.endswith(".mc.gz"):
            import gzip

            text = self.to_macrocell(metadata).encode("utf-8")
            target.write_bytes(gzip.compress(text, mtime=0))
        elif name.endswith(".mc"):
            target.write_text(self.to_macrocell(metadata), encoding="utf-8", newline="\n")
        elif name.endswith(".rle"):
            target.write_text(self.to_rle(metadata), encoding="utf-8", newline="\n")
        else:
            raise ValueError(f"unknown pattern extension for {target.name!r} (.rle, .mc, .mc.gz)")

    # -- tree walks (tree coordinates: y one less than the cell's) -------------------------

    def _adopt(self, root: int, level: int, generation: int) -> None:
        self._root, self._level, self._generation = root, level, generation

    def _build(self, fill: Callable[[], None]) -> tuple[int, int]:
        """Run ``fill`` on an empty tree in this universe's store and give the tree it built
        as (root, level), leaving the universe's own root, level and generation as they were:
        how a file is read into the store without becoming the state."""
        saved = self._root, self._level, self._generation
        self._root, self._level = self._store.empty(_MIN_LEVEL), _MIN_LEVEL
        try:
            fill()
            return self._root, self._level
        finally:
            self._root, self._level, self._generation = saved

    def _edit_rect(self, x0: int, y0: int, x1: int, y1: int) -> tuple[int, int, int, int]:
        """The tree rectangle of a non-empty inclusive rectangle in the editing box."""
        x0, y0, x1, y1 = _ints(x0, y0, x1, y1)
        check_box(x0, y0, x1, y1)
        if x1 < x0 or y1 < y0:
            raise ValueError(f"empty rectangle ({x0}, {y0})..({x1}, {y1})")
        return x0, y0 - 1, x1, y1 - 1

    def _move_rect(
        self,
        old: tuple[int, int, int, int],
        new: tuple[int, int, int, int],
        kind: str,
        shift: tuple[int, int],
    ) -> None:
        """Lift the cells of ``old`` (cell coordinates), turn or mirror them about the root's
        center (``kind`` in ``_TRANSFORMS``), move them by ``shift`` (tree coordinates) onto
        ``new``, and paste them there by copy; the rest of ``old`` dies."""
        while self._level < _TURN_LEVEL:
            self._expand()
        k = self._level
        origin = -(1 << (k - 1))
        told = (old[0], old[1] - 1, old[2], old[3] - 1)
        tnew = (new[0], new[1] - 1, new[2], new[3] - 1)
        lifted = self._keep(self._root, k, origin, origin, told)
        turned = self._transform(lifted, k, kind, {})
        moved = self._shifted(turned, k, *shift)
        rest = self._clear(self._root, k, origin, origin, told)
        self._root = self._splice(moved, rest, k, origin, origin, tnew)

    def _advance_region(self, x0: int, y0: int, x1: int, y1: int, n: int, *, outside: bool) -> None:
        rect = self._edit_rect(x0, y0, x1, y1)
        n = operator.index(n)
        _check_count(n)
        saved = self.snapshot()  # a collection inside the step keeps the original's nodes
        try:
            origin = -(1 << (self._level - 1))
            if outside:
                self._root = self._clear(self._root, self._level, origin, origin, rect)
            else:
                self._root = self._keep(self._root, self._level, origin, origin, rect)
            try:
                self.step(n)
            except BaseException:
                self.restore(saved)
                raise
            grown, grown_level = self._root, self._level
            self.restore(saved)
        finally:
            saved.release()  # the universe holds its nodes again; nothing else needs it
        while self._level < grown_level:
            self._expand()
        while grown_level < self._level:
            grown = self._grow(grown, grown_level)
            grown_level += 1
        k = self._level
        origin = -(1 << (k - 1))
        if outside:
            self._root = self._splice(self._root, grown, k, origin, origin, rect)
        else:
            self._root = self._splice(grown, self._root, k, origin, origin, rect)

    def _minimal(self) -> tuple[int, int]:
        """The smallest centered root (level ≥ 3) that holds every live cell."""
        return self._minimal_of(self._root, self._level)

    def _minimal_of(self, n: int, k: int) -> tuple[int, int]:
        """The smallest centered root (level ≥ 3) holding every live cell of tree (n, k)."""
        store = self._store
        data = store.data
        while k > 3:
            a, b, c, d = data[n]
            if k == 4:
                middle = store.leaf(inner(data[a], data[b], data[c], data[d]))
            else:
                middle = store.join(data[a][3], data[b][2], data[c][1], data[d][0])
            if store.population(middle, k - 1) != store.population(n, k):
                break
            n, k = middle, k - 1
        return n, k

    def _leaves(self) -> Iterator[tuple[int, int, int]]:
        """Every non-empty leaf as (tree x, tree y, bitmap), in no particular order."""
        store = self._store
        data = store.data
        origin = -(1 << (self._level - 1))
        stack = [(self._root, self._level, origin, origin)]
        while stack:
            n, k, nx, ny = stack.pop()
            if n == store.empty(k):
                continue
            if k == 3:
                yield nx, ny, data[n]
                continue
            half = 1 << (k - 1)
            a, b, c, d = data[n]
            k -= 1
            stack += ((a, k, nx, ny), (b, k, nx + half, ny), (c, k, nx, ny + half))
            stack.append((d, k, nx + half, ny + half))

    def _paste_blocks(
        self,
        blocks: dict[tuple[int, int], int],
        rect: tuple[int, int, int, int],
        mode: PasteMode,
    ) -> None:
        """Land leaf bitmaps ``{(bx, by): bits}`` over the tree rectangle ``rect``."""
        self._contain(*rect)
        k = self._level
        # Which aligned nodes hold source cells, per level below the (centered) root.
        tiers: dict[int, set[tuple[int, int]]] = {}
        for level in range(4, k):
            shift = level - 3
            tiers[level] = {(bx >> shift, by >> shift) for bx, by in blocks}
        origin = -(1 << (k - 1))
        self._root = self._paste(self._root, k, origin, origin, rect, blocks, tiers, mode)

    def _contain(self, x0: int, y0: int, x1: int, y1: int) -> None:
        while True:
            half = 1 << (self._level - 1)
            if -half <= x0 and x1 < half and -half <= y0 and y1 < half:
                return
            self._expand()

    def _set(self, n: int, k: int, x: int, y: int, bit: int) -> int:
        store = self._store
        if k == 3:
            mask = 1 << (y * 8 + x)
            bits = store.data[n]
            return store.leaf(bits | mask if bit else bits & ~mask)
        half = 1 << (k - 1)
        a, b, c, d = store.data[n]
        if y < half:
            if x < half:
                a = self._set(a, k - 1, x, y, bit)
            else:
                b = self._set(b, k - 1, x - half, y, bit)
        elif x < half:
            c = self._set(c, k - 1, x, y - half, bit)
        else:
            d = self._set(d, k - 1, x - half, y - half, bit)
        return store.join(a, b, c, d)

    def _clear(self, n: int, k: int, nx: int, ny: int, rect: tuple[int, int, int, int]) -> int:
        size = 1 << k
        store = self._store
        e = store.empty(k)
        if n == e or _disjoint(nx, ny, size, rect):
            return n
        if _covers(nx, ny, size, rect):
            return e
        if k == 3:
            return store.leaf(store.data[n] & ~_leaf_mask(nx, ny, rect))
        half = size >> 1
        a, b, c, d = store.data[n]
        k1 = k - 1
        return store.join(
            self._clear(a, k1, nx, ny, rect),
            self._clear(b, k1, nx + half, ny, rect),
            self._clear(c, k1, nx, ny + half, rect),
            self._clear(d, k1, nx + half, ny + half, rect),
        )

    def _keep(self, n: int, k: int, nx: int, ny: int, rect: tuple[int, int, int, int]) -> int:
        """Node n with every cell outside the tree rectangle cleared."""
        size = 1 << k
        store = self._store
        e = store.empty(k)
        if n == e or _disjoint(nx, ny, size, rect):
            return e
        if _covers(nx, ny, size, rect):
            return n
        if k == 3:
            return store.leaf(store.data[n] & _leaf_mask(nx, ny, rect))
        half = size >> 1
        a, b, c, d = store.data[n]
        k1 = k - 1
        return store.join(
            self._keep(a, k1, nx, ny, rect),
            self._keep(b, k1, nx + half, ny, rect),
            self._keep(c, k1, nx, ny + half, rect),
            self._keep(d, k1, nx + half, ny + half, rect),
        )

    def _splice(
        self, inside: int, outside: int, k: int, nx: int, ny: int, rect: tuple[int, int, int, int]
    ) -> int:
        """Two aligned level-k nodes made one: ``inside``'s cells in the tree rectangle,
        ``outside``'s everywhere else."""
        if inside == outside:
            return inside
        size = 1 << k
        if _disjoint(nx, ny, size, rect):
            return outside
        if _covers(nx, ny, size, rect):
            return inside
        store = self._store
        data = store.data
        if k == 3:
            mask = _leaf_mask(nx, ny, rect)
            return store.leaf((data[inside] & mask) | (data[outside] & ~mask))
        half = size >> 1
        ia, ib, ic, id_ = data[inside]
        oa, ob, oc, od = data[outside]
        k1 = k - 1
        return store.join(
            self._splice(ia, oa, k1, nx, ny, rect),
            self._splice(ib, ob, k1, nx + half, ny, rect),
            self._splice(ic, oc, k1, nx, ny + half, rect),
            self._splice(id_, od, k1, nx + half, ny + half, rect),
        )

    def _grow(self, n: int, k: int) -> int:
        """Centered level-k node n (k ≥ 4) inside a centered node twice its size."""
        store = self._store
        e = store.empty(k - 1)
        join = store.join
        a, b, c, d = store.data[n]
        return join(join(e, e, e, a), join(e, e, b, e), join(e, c, e, e), join(d, e, e, e))

    def _transform(self, n: int, k: int, kind: str, memo: dict[int, int]) -> int:
        """Level-k node n turned or mirrored about its own center (``_TRANSFORMS``)."""
        hit = memo.get(n)
        if hit is not None:
            return hit
        store = self._store
        leaf, order = _TRANSFORMS[kind]
        if k == 3:
            r = store.leaf(leaf(store.data[n]))
        elif n == store.empty(k):
            r = n
        else:
            kids = store.data[n]
            k1 = k - 1
            turned = []
            for i in order:  # a plain loop: one frame per level (spec/hashlife.md "Depth")
                turned.append(self._transform(kids[i], k1, kind, memo))
            r = store.join(*turned)
        memo[n] = r
        return r

    def _shifted(self, n: int, k: int, dx: int, dy: int) -> int:
        """Centered level-k node n with every cell moved by (dx, dy), |dx|, |dy| ≤ 2^(k−1).
        A cell moved past the node's edge is lost; callers leave room."""
        big = self._store.data[self._grow(n, k)]
        half = 1 << (k - 1)
        return self._crop(k, big[0], big[1], big[2], big[3], half - dx, half - dy, {})

    def _crop(
        self,
        k: int,
        a: int,
        b: int,
        c: int,
        d: int,
        ox: int,
        oy: int,
        memo: dict[tuple[int, ...], int],
    ) -> int:
        """The level-k node at offset (ox, oy), 0 ≤ ox, oy ≤ 2^k, in the square of the four
        aligned level-k nodes a b over c d."""
        size = 1 << k
        if ox in (0, size) and oy in (0, size):
            return (a, b, c, d)[(ox != 0) + 2 * (oy != 0)]
        store = self._store
        e = store.empty(k)
        if a == e and b == e and c == e and d == e:
            return e
        key = (k, a, b, c, d, ox, oy)
        hit = memo.get(key)
        if hit is not None:
            return hit
        data = store.data
        if k == 3:
            r = store.leaf(crop(data[a], data[b], data[c], data[d], ox, oy))
        else:
            na, nb, nc, nd = data[a], data[b], data[c], data[d]
            grid = (
                (na[0], na[1], nb[0], nb[1]),
                (na[2], na[3], nb[2], nb[3]),
                (nc[0], nc[1], nd[0], nd[1]),
                (nc[2], nc[3], nd[2], nd[3]),
            )
            half = size >> 1
            kids = []
            for j in (0, 1):
                gy, ry = divmod(oy + j * half, half)
                if gy == 3:
                    gy, ry = 2, half
                for i in (0, 1):
                    gx, rx = divmod(ox + i * half, half)
                    if gx == 3:
                        gx, rx = 2, half
                    top, below = grid[gy], grid[gy + 1]
                    kids.append(
                        self._crop(
                            k - 1, top[gx], top[gx + 1], below[gx], below[gx + 1], rx, ry, memo
                        )
                    )
            r = store.join(*kids)
        memo[key] = r
        return r

    def _paste(
        self,
        n: int,
        k: int,
        nx: int,
        ny: int,
        rect: tuple[int, int, int, int],
        blocks: dict[tuple[int, int], int],
        tiers: dict[int, set[tuple[int, int]]],
        mode: PasteMode,
    ) -> int:
        size = 1 << k
        if _disjoint(nx, ny, size, rect):
            return n
        store = self._store
        if k == 3:
            old = store.data[n]
            src = blocks.get((nx >> 3, ny >> 3), 0)
            if mode == "copy":
                new = (old & ~_leaf_mask(nx, ny, rect)) | src
            elif mode == "or":
                new = old | src
            elif mode == "xor":
                new = old ^ src
            else:  # and: inside the rectangle only the source's live cells may stay
                new = old & (src | ~_leaf_mask(nx, ny, rect))
            return store.leaf(new)
        tier = tiers.get(k)  # None at the root, which is centered, not aligned
        if tier is not None and (nx >> k, ny >> k) not in tier:  # no source cells below
            return self._clear(n, k, nx, ny, rect) if mode in ("copy", "and") else n
        half = size >> 1
        a, b, c, d = store.data[n]
        k1 = k - 1
        return store.join(
            self._paste(a, k1, nx, ny, rect, blocks, tiers, mode),
            self._paste(b, k1, nx + half, ny, rect, blocks, tiers, mode),
            self._paste(c, k1, nx, ny + half, rect, blocks, tiers, mode),
            self._paste(d, k1, nx + half, ny + half, rect, blocks, tiers, mode),
        )

    def _count(self, n: int, k: int, nx: int, ny: int, rect: tuple[int, int, int, int]) -> int:
        size = 1 << k
        store = self._store
        if n == store.empty(k) or _disjoint(nx, ny, size, rect):
            return 0
        if _covers(nx, ny, size, rect):
            return store.population(n, k)
        if k == 3:
            return int(store.data[n] & _leaf_mask(nx, ny, rect)).bit_count()
        half = size >> 1
        a, b, c, d = store.data[n]
        k1 = k - 1
        return (
            self._count(a, k1, nx, ny, rect)
            + self._count(b, k1, nx + half, ny, rect)
            + self._count(c, k1, nx, ny + half, rect)
            + self._count(d, k1, nx + half, ny + half, rect)
        )

    def _extract(
        self,
        n: int,
        k: int,
        nx: int,
        ny: int,
        rect: tuple[int, int, int, int],
        out: NDArray[np.uint8],
    ) -> None:
        size = 1 << k
        store = self._store
        if n == store.empty(k) or _disjoint(nx, ny, size, rect):
            return
        if k == 3:
            x0, y0, x1, y1 = rect
            ix0, iy0 = max(nx, x0), max(ny, y0)
            ix1, iy1 = min(nx + 7, x1), min(ny + 7, y1)
            cells = leaf_cells(store.data[n])
            out[iy0 - y0 : iy1 - y0 + 1, ix0 - x0 : ix1 - x0 + 1] = cells[
                iy0 - ny : iy1 - ny + 1, ix0 - nx : ix1 - nx + 1
            ]
            return
        half = size >> 1
        a, b, c, d = store.data[n]
        k1 = k - 1
        self._extract(a, k1, nx, ny, rect, out)
        self._extract(b, k1, nx + half, ny, rect, out)
        self._extract(c, k1, nx, ny + half, rect, out)
        self._extract(d, k1, nx + half, ny + half, rect, out)

    def _edge(self, which: str) -> int:
        """One extreme of the live cells, as an offset from the root's origin."""
        return self._node_edge(self._root, self._level, which, {})

    def _node_edge(self, n: int, k: int, which: str, memo: dict[int, int]) -> int:
        """One extreme of the live cells of non-empty level-k node n, as an offset from its
        origin; ``memo`` holds this edge's answers by node."""
        hit = memo.get(n)
        if hit is not None:
            return hit
        store = self._store
        if k == 3:
            r = _leaf_edge(store.data[n], which)
        else:
            # Plain loops, not comprehensions: one frame per level (spec/hashlife.md "Depth").
            near, far, lowest = _EDGES[which]
            kids = store.data[n]
            e = store.empty(k - 1)
            half = 1 << (k - 1)
            side, offset = near, 0 if lowest else half
            if all(kids[i] == e for i in near):
                side, offset = far, half if lowest else 0
            found = []
            for i in side:
                if kids[i] != e:
                    found.append(self._node_edge(kids[i], k - 1, which, memo))
            r = (min(found) if lowest else max(found)) + offset
        memo[n] = r
        return r

    def _extreme_in(
        self,
        n: int,
        k: int,
        nx: int,
        ny: int,
        rect: tuple[int, int, int, int],
        which: str,
        memo: dict[int, int],
    ) -> int | None:
        """One extreme of node n's live cells inside the tree rectangle, as a tree
        coordinate, or None when it holds none. The near half is searched first: anything
        found there beats everything in the far half."""
        size = 1 << k
        store = self._store
        if n == store.empty(k) or _disjoint(nx, ny, size, rect):
            return None
        base = nx if which in ("min_x", "max_x") else ny
        if _covers(nx, ny, size, rect):
            return base + self._node_edge(n, k, which, memo)
        if k == 3:
            bits = store.data[n] & _leaf_mask(nx, ny, rect)
            return None if bits == 0 else base + _leaf_edge(bits, which)
        near, far, lowest = _EDGES[which]
        half = size >> 1
        kids = store.data[n]
        corners = ((nx, ny), (nx + half, ny), (nx, ny + half), (nx + half, ny + half))
        for side in (near, far):
            found = []
            for i in side:
                got = self._extreme_in(kids[i], k - 1, *corners[i], rect, which, memo)
                if got is not None:
                    found.append(got)
            if found:
                return min(found) if lowest else max(found)
        return None
