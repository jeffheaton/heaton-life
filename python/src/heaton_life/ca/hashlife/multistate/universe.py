"""The multi-state HashLife universe (spec/hashlife-multistate.md): a state rule on an
unbounded plane.

Cells hold states from 0 to S − 1 in a hash-consed quadtree whose leaves are 2 × 2 squares
of states and whose root is centered on the origin. Cell (x, y) sits at tree position
(x, y − 1), the placement of the two-state universe and of Macrocell files, and every
coordinate, generation, and population is a Python int. Everything but the leaves and the
base case of the evolution is the two-state universe's algorithm (spec/hashlife.md).
"""

from __future__ import annotations

import operator
import weakref
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import numpy as np
from numpy.typing import NDArray

from heaton_life.ca.hashlife.multistate.store import (
    NODE_BYTES,
    StateStore,
    pack,
    unpack,
)
from heaton_life.ca.hashlife.store import Abort
from heaton_life.ca.hashlife.universe import (
    DEFAULT_MEMORY_MB,
    MAX_LEVEL,
    PASTE_MODES,
    HashLifeMemoryError,
    PasteMode,
    Snapshot,
    SnapshotFootprint,
    StepCanceled,
    _budget,
    _check_count,
    _covers,
    _disjoint,
    _ints,
    check_box,
)
from heaton_life.ca.hashlife.view import LifeView
from heaton_life.ca.state_rules import StateRule, resolve_rule
from heaton_life.init.metadata import PatternMetadata
from heaton_life.init.patterns import turn_center, turned_rect

if TYPE_CHECKING:
    from heaton_life.ca.hashlife.files import PatternSnapshot

StateRenderMode = Literal["state", "density"]
STATE_RENDER_MODES: tuple[StateRenderMode, ...] = ("state", "density")
_MIN_LEVEL = 2  # the root is always an internal node
_MIN_STEP_LEVEL = 4  # sub-steps check containment on the root's great-grandchildren
_TURN_LEVEL = 33  # a centered root this tall holds the editing box with room for any shift

# A node turned or mirrored about its own center: which old quarter lands in each new one
# (NW, NE, SW, SE). A leaf's four states move the same way.
_ORDERS = {
    "cw": (2, 0, 3, 1),
    "ccw": (1, 3, 0, 2),
    "h": (1, 0, 3, 2),
    "v": (2, 3, 0, 1),
}

# Extremes for the bounding box: (near children, far children, use min) per edge; the far
# pair sits half a node further along the axis.
_EDGES = {
    "min_x": ((0, 2), (1, 3), True),
    "max_x": ((1, 3), (0, 2), False),
    "min_y": ((0, 1), (2, 3), True),
    "max_y": ((2, 3), (0, 1), False),
}


class _StateSnapshot(Snapshot):
    """A multi-state universe's snapshot: also the most states its cells can need, so a
    restore under a rule of fewer states knows whether to look."""

    __slots__ = ("_states",)

    def __init__(
        self, owner: MultiStateHashLife, root: int, level: int, generation: int, states: int
    ) -> None:
        super().__init__(owner, root, level, generation)
        self._states = states


def _leaf_inside(nx: int, ny: int, rect: tuple[int, int, int, int]) -> tuple[bool, ...]:
    """Which of a leaf's four cells (NW, NE, SW, SE) at tree (nx, ny) lie in ``rect``."""
    x0, y0, x1, y1 = rect
    xs = (x0 <= nx <= x1, x0 <= nx + 1 <= x1)
    ys = (y0 <= ny <= y1, y0 <= ny + 1 <= y1)
    return xs[0] and ys[0], xs[1] and ys[0], xs[0] and ys[1], xs[1] and ys[1]


def _leaf_edge(states: tuple[int, int, int, int], which: str) -> int | None:
    """One extreme of a leaf's non-zero cells, as a column or row 0..1, or None."""
    lowest = _EDGES[which][2]
    found = [
        (i & 1) if which in ("min_x", "max_x") else (i >> 1)
        for i, state in enumerate(states)
        if state
    ]
    if not found:
        return None
    return min(found) if lowest else max(found)


def _state_blocks(cells: NDArray[np.generic], tx: int, ty: int) -> dict[tuple[int, int], int]:
    """The non-empty leaves of an array of states placed with its top-left cell at tree
    position (tx, ty): ``{(bx, by): packed states}``, where leaf (bx, by) covers tree
    positions [2·bx, 2·bx + 2) × [2·by, 2·by + 2)."""
    height, width = cells.shape
    bx0, by0 = tx >> 1, ty >> 1
    ox, oy = tx - (bx0 << 1), ty - (by0 << 1)
    grid = np.zeros((((oy + height + 1) >> 1) << 1, ((ox + width + 1) >> 1) << 1), np.uint32)
    grid[oy : oy + height, ox : ox + width] = cells
    rows, cols = grid.shape[0] >> 1, grid.shape[1] >> 1
    g = grid.reshape(rows, 2, cols, 2)
    packed = g[:, 0, :, 0] | (g[:, 0, :, 1] << 8) | (g[:, 1, :, 0] << 16) | (g[:, 1, :, 1] << 24)
    return {
        (bx0 + int(c), by0 + int(r)): int(packed[r, c])
        for r, c in zip(*np.nonzero(packed), strict=True)
    }


def _states_array(cells: NDArray[np.generic], states: int) -> NDArray[np.uint8]:
    """``cells`` as a non-empty 2-D array of states below ``states``, or ValueError."""
    array = np.asarray(cells)
    if array.ndim != 2 or 0 in array.shape:
        raise ValueError(f"cells must be a non-empty 2-D array, got shape {array.shape}")
    if array.dtype == np.bool_:
        array = array.astype(np.uint8)
    if not np.issubdtype(array.dtype, np.integer):
        raise ValueError(f"cells are states (integers), not {array.dtype}")
    low, high = int(array.min()), int(array.max())
    if low < 0 or high >= states:
        bad = low if low < 0 else high
        raise ValueError(f"state {bad} is outside the rule's states 0..{states - 1}")
    return array.astype(np.uint8)


class MultiStateHashLife:
    """An unbounded universe of a state rule. See spec/hashlife-multistate.md for the full
    contract; everything it shares with the two-state ``HashLife`` behaves as there."""

    def __init__(
        self, rule: str | StateRule = "WireWorld", *, max_memory_mb: int = DEFAULT_MEMORY_MB
    ) -> None:
        self._rule = resolve_rule(rule)
        self._max_memory_mb = operator.index(max_memory_mb)
        self._store = StateStore(self._rule, _budget(max_memory_mb))
        self._level = _MIN_LEVEL
        self._root = self._store.empty(_MIN_LEVEL)
        self._generation = 0
        self._snapshots: weakref.WeakSet[Snapshot] = weakref.WeakSet()
        self._zoom_order: tuple[int, ...] = ()
        self._ranks = self._rank_table(())
        self._shown: dict[int, int] = {}  # node -> its shown state, under _ranks
        self._tiles: dict[tuple[int, str], dict[int, NDArray[np.uint8]]] = {}
        self._tiles_epoch = 0

    def __repr__(self) -> str:
        return (
            f"MultiStateHashLife(rule={self.rule!r}, generation={self._generation}, "
            f"population={self.population})"
        )

    # -- configuration ------------------------------------------------------------------

    @property
    def rule(self) -> str:
        """The rule's canonical name."""
        return self._rule.canonical

    @rule.setter
    def rule(self, rule: str | StateRule) -> None:
        self.state_rule = resolve_rule(rule)

    @property
    def state_rule(self) -> StateRule:
        """The rule itself. Setting it (or ``rule``) keeps the cells and drops cached
        results; a rule with fewer states than the largest state present is an error."""
        return self._rule

    @state_rule.setter
    def state_rule(self, rule: StateRule) -> None:
        rule = resolve_rule(rule)
        if rule is self._rule:
            return
        if rule.states < self._rule.states:
            top = self._max_state(self._root, self._level, {})
            if top >= rule.states:
                raise ValueError(
                    f"{rule.canonical} has {rule.states} states and the universe holds state {top}"
                )
        self._rule = rule
        self._store.use_rule(rule)

    @property
    def states(self) -> int:
        """The rule's number of states, S."""
        return self._rule.states

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

    @property
    def zoom_order(self) -> tuple[int, ...]:
        """How a zoomed-out pixel chooses among the states it covers
        (spec/hashlife-multistate.md "View and render"): these states first, in this order,
        then every other non-zero state in increasing order. Default ``()``."""
        return self._zoom_order

    @zoom_order.setter
    def zoom_order(self, order: Iterable[int]) -> None:
        ranked = tuple(operator.index(s) for s in order)
        if any(not 1 <= s <= 255 for s in ranked) or len(set(ranked)) != len(ranked):
            raise ValueError(f"a zoom order lists distinct states from 1 to 255, not {ranked}")
        if ranked != self._zoom_order:
            self._zoom_order = ranked
            self._ranks = self._rank_table(ranked)
            self._shown = {}
            self._tiles = {}

    @staticmethod
    def _rank_table(order: tuple[int, ...]) -> tuple[int, ...]:
        """Each state's place in the zoom order (lower shows first); state 0 last of all."""
        ranks = [0] * 256
        listed = set(order)
        for place, state in enumerate(order):
            ranks[state] = place
        place = len(order)
        for state in range(1, 256):
            if state not in listed:
                ranks[state] = place
                place += 1
        ranks[0] = 256
        return tuple(ranks)

    # -- observables --------------------------------------------------------------------

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def population(self) -> int:
        """The cells whose state is not 0."""
        return self._store.population(self._root, self._level)

    def bounding_box(self) -> tuple[int, int, int, int] | None:
        """(x0, y0, x1, y1): the inclusive extremes of the non-zero cells, or None."""
        if self.population == 0:
            return None
        origin = -(1 << (self._level - 1))
        x0 = origin + self._edge("min_x")
        x1 = origin + self._edge("max_x")
        y0 = origin + self._edge("min_y") + 1
        y1 = origin + self._edge("max_y") + 1
        return x0, y0, x1, y1

    def population_in(self, x0: int, y0: int, x1: int, y1: int) -> int:
        """Non-zero cells in the inclusive rectangle; any coordinates."""
        x0, y0, x1, y1 = _ints(x0, y0, x1, y1)
        if x1 < x0 or y1 < y0:
            return 0
        origin = -(1 << (self._level - 1))
        return self._count(self._root, self._level, origin, origin, (x0, y0 - 1, x1, y1 - 1))

    @property
    def live_population(self) -> int:
        """The live cells (spec/hashlife-multistate.md "Observables"): under a History or
        Super rule the on cells, the odd states; under any other rule the non-zero cells,
        ``population``."""
        if not self._odd_live():
            return self.population
        return self._store.odd_population(self._root, self._level)

    def live_population_in(self, x0: int, y0: int, x1: int, y1: int) -> int:
        """Live cells in the inclusive rectangle, as ``live_population`` counts them; any
        coordinates."""
        x0, y0, x1, y1 = _ints(x0, y0, x1, y1)
        if x1 < x0 or y1 < y0:
            return 0
        origin = -(1 << (self._level - 1))
        rect = (x0, y0 - 1, x1, y1 - 1)
        return self._count(self._root, self._level, origin, origin, rect, self._odd_live())

    def _odd_live(self) -> bool:
        """Whether the rule's live states are its odd ones (History and Super), not every
        non-zero one."""
        # Imported here: the families import heaton_life.ca, which imports this module.
        from heaton_life.ca.history import is_history
        from heaton_life.ca.super_rules import is_super

        return is_history(self._rule) or is_super(self._rule)

    def bounding_box_in(
        self, x0: int, y0: int, x1: int, y1: int
    ) -> tuple[int, int, int, int] | None:
        """(x0, y0, x1, y1): the inclusive extremes of the non-zero cells inside the
        inclusive rectangle, or None when it holds none. Any coordinates."""
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
        """The state of cell (x, y)."""
        x, y = _ints(x, y)
        check_box(x, y, x, y)
        k = self._level
        half = 1 << (k - 1)
        tx, ty = x + half, y - 1 + half
        if not (0 <= tx < 2 * half and 0 <= ty < 2 * half):
            return 0
        data = self._store.data
        n = self._root
        while k > 1:
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
        return (data[n] >> (8 * (ty * 2 + tx))) & 0xFF  # type: ignore[no-any-return]

    def get_rect(self, x0: int, y0: int, x1: int, y1: int) -> NDArray[np.uint8]:
        """The inclusive rectangle's states as a (y1 − y0 + 1) × (x1 − x0 + 1) array."""
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
        j = 0
        while n:
            if n & 1:
                self._advance(j)
            n >>= 1
            j += 1

    def cancel(self) -> None:
        """Ask a running ``step`` (on another thread) to stop at a sub-step boundary."""
        self._store.cancel_requested = True

    def _advance(self, j: int) -> None:
        """Advance 2^j generations: collect when three-quarters full, try twice, then split
        into two halves (spec/hashlife.md "Memory"). Halves wait on a list rather than the
        call stack, so splitting never adds to the recursion of a deep step."""
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
        store.use_step(j)
        store.guard = True
        try:
            root = store.stepped(self._root, self._level, j)
        finally:
            store.guard = False
        self._root = root
        self._level -= 1
        self._generation += 1 << j

    def _centered(self) -> bool:
        """Every non-zero cell lies in the centered square of side 2^(k−2)."""
        store = self._store
        data = store.data
        k = self._level
        a, b, c, d = data[self._root]
        inner = (data[data[a][3]][3], data[data[b][2]][2], data[data[c][1]][1], data[data[d][0]][0])
        held = sum(store.population(x, k - 3) for x in inner)
        return held == store.population(self._root, k)

    def _expand(self) -> None:
        """Wrap the root in a node twice its size, centered, with empty margins."""
        self._root = self._grow(self._root, self._level)
        self._level += 1

    def _collect(self) -> None:
        roots = [(self._root, self._level)]
        roots += [(s._root, s._level) for s in self._snapshots]
        self._store.collect(roots)
        self._shown = {}

    def collect_garbage(self) -> None:
        """Free every node unreachable from the current state and live snapshots."""
        self._collect()

    # -- editing ------------------------------------------------------------------------

    def set_cell(self, x: int, y: int, state: int) -> None:
        """Set cell (x, y) to ``state``, 0 ≤ state < S (``True`` is state 1)."""
        x, y, state = _ints(x, y, state)
        if not 0 <= state < self._rule.states:
            raise ValueError(f"state {state} is outside the rule's states 0..{self.states - 1}")
        check_box(x, y, x, y)
        self._contain(x, y - 1, x, y - 1)
        half = 1 << (self._level - 1)
        self._root = self._set(self._root, self._level, x + half, y - 1 + half, state)

    def set_rect(
        self, x: int, y: int, cells: NDArray[np.generic], mode: PasteMode = "copy"
    ) -> None:
        """Land ``cells`` (h × w states) with its top-left cell at (x, y). ``copy`` writes
        every cell, ``or`` the non-zero ones; ``xor`` and ``and`` need every cell of
        ``cells`` and of the rectangle it lands on to be 0 or 1."""
        if mode not in PASTE_MODES:
            raise ValueError(f"unknown paste mode {mode!r}; expected one of {PASTE_MODES}")
        x, y = _ints(x, y)
        array = _states_array(cells, self._rule.states)
        height, width = array.shape
        check_box(x, y, x + width - 1, y + height - 1)
        rect = (x, y - 1, x + width - 1, y + height - 2)
        if mode in ("xor", "and"):
            if int(array.max()) > 1:
                raise ValueError(f"paste mode {mode!r} needs cells of states 0 and 1")
            origin = -(1 << (self._level - 1))
            if self._max_state_in(self._root, self._level, origin, origin, rect, {}) > 1:
                raise ValueError(
                    f"paste mode {mode!r} needs the rectangle it lands on to hold states 0 "
                    "and 1 only"
                )
        self._paste_blocks(_state_blocks(array, x, y - 1), rect, mode)

    def fill_random(self, x0: int, y0: int, x1: int, y1: int, density: float, seed: int) -> None:
        """Replace the inclusive rectangle with lifelike's PCG32 soup of the same size, its
        live cells state 1 and its dead ones 0: the cells the two-state universe's
        ``fill_random`` gives (spec/hashlife-multistate.md "Editing"). Random fill is a
        Life-like tool, so only the universe of a History, Super or Generations rule has
        it; under any other rule it is an error that changes nothing."""
        from heaton_life.ca.generations import GenerationsRule
        from heaton_life.ca.history import is_history
        from heaton_life.ca.super_rules import is_super
        from heaton_life.init.seeding import soup

        rule = self._rule
        if not (is_history(rule) or is_super(rule) or isinstance(rule, GenerationsRule)):
            raise ValueError(
                f"random fill is a Life-like tool; {self.rule} is no History, Super or "
                'Generations rule (spec/hashlife-multistate.md "Editing")'
            )
        x0, y0, x1, y1, seed = _ints(x0, y0, x1, y1, seed)
        check_box(x0, y0, x1, y1)
        if x1 < x0 or y1 < y0:
            raise ValueError(f"empty rectangle ({x0}, {y0})..({x1}, {y1})")
        cells = soup((x1 - x0 + 1, y1 - y0 + 1), density=density, seed=seed)
        self.set_rect(x0, y0, cells, "copy")

    def clear_rect(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """Every cell of the inclusive rectangle becomes 0."""
        x0, y0, x1, y1 = _ints(x0, y0, x1, y1)
        check_box(x0, y0, x1, y1)
        if x1 < x0 or y1 < y0:
            return
        origin = -(1 << (self._level - 1))
        rect = (x0, y0 - 1, x1, y1 - 1)
        self._root = self._clear(self._root, self._level, origin, origin, rect)

    def clear_outside(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """Every cell outside the inclusive rectangle becomes 0, wherever it lies."""
        rect = self._edit_rect(x0, y0, x1, y1)
        origin = -(1 << (self._level - 1))
        self._root = self._keep(self._root, self._level, origin, origin, rect)

    def rotate_rect(
        self, x0: int, y0: int, x1: int, y1: int, *, clockwise: bool = True
    ) -> tuple[int, int, int, int]:
        """Turn the inclusive rectangle and its cells a quarter about its center, in place,
        and return the rectangle they land on (spec/hashlife.md "Rectangle transforms")."""
        self._edit_rect(x0, y0, x1, y1)
        x0, y0, x1, y1 = _ints(x0, y0, x1, y1)
        s, d = turn_center(x0, y0, x1, y1)
        new = turned_rect(x0, y0, x1, y1, clockwise=clockwise)
        shift = (s, d - 1) if clockwise else (1 - d, s)
        check_box(*new)
        self._move_rect((x0, y0, x1, y1), new, "cw" if clockwise else "ccw", shift)
        return new

    def flip_rect(self, x0: int, y0: int, x1: int, y1: int, *, horizontal: bool = True) -> None:
        """Mirror the inclusive rectangle's cells in place: left-right or, with
        ``horizontal=False``, top-bottom."""
        self._edit_rect(x0, y0, x1, y1)
        x0, y0, x1, y1 = _ints(x0, y0, x1, y1)
        rect = (x0, y0, x1, y1)
        if horizontal:
            self._move_rect(rect, rect, "h", (x0 + x1 + 1, 0))
        else:
            self._move_rect(rect, rect, "v", (0, y0 + y1 - 1))

    def advance_selection(self, x0: int, y0: int, x1: int, y1: int, n: int) -> None:
        """Evolve the inclusive rectangle ``n`` generations as an isolated plane and clip
        the result to it; the outside and the generation are untouched."""
        self._advance_region(x0, y0, x1, y1, n, outside=False)

    def advance_outside(self, x0: int, y0: int, x1: int, y1: int, n: int) -> None:
        """Evolve everything outside the inclusive rectangle ``n`` generations as if the
        rectangle held only 0 cells; the rectangle keeps its cells."""
        self._advance_region(x0, y0, x1, y1, n, outside=True)

    def set_generation(self, generation: int) -> None:
        """Set the generation counter to any integer ≥ 0; no cell changes."""
        generation = operator.index(generation)
        if generation < 0:
            raise ValueError(f"a generation is never negative, got {generation}")
        self._generation = generation

    def clear(self) -> None:
        self._level = _MIN_LEVEL
        self._root = self._store.empty(_MIN_LEVEL)

    # -- snapshots ----------------------------------------------------------------------

    def snapshot(self) -> Snapshot:
        return self._snapshot_at(self._root, self._level, self._generation, self.states)

    def _snapshot_at(self, root: int, level: int, generation: int, states: int) -> Snapshot:
        """A snapshot of any tree in this store whose states are all below ``states``."""
        snap = _StateSnapshot(self, root, level, generation, states)
        self._snapshots.add(snap)
        return snap

    def restore(self, snapshot: Snapshot) -> None:
        """Return to ``snapshot``'s cells and generation. A snapshot of another universe, a
        released one, or one holding a state the rule lacks is an error."""
        if snapshot._owner() is not self:
            raise ValueError("snapshot belongs to another universe")
        if snapshot._released:
            raise ValueError("the snapshot was released and holds no cells")
        self._check_states(snapshot)
        self._root = snapshot._root
        self._level = snapshot._level
        self._generation = snapshot._generation

    def _check_states(self, snapshot: Snapshot) -> None:
        """Raise ValueError when one of this universe's snapshots holds a state its rule
        lacks: only possible after a change to a rule of fewer states, so only then is the
        tree looked at."""
        assert isinstance(snapshot, _StateSnapshot)
        if snapshot._states > self.states:
            top = self._max_state(snapshot._root, snapshot._level, {})
            if top >= self.states:
                raise ValueError(
                    f"the snapshot holds state {top}, which {self.rule} doesn't have "
                    f"({self.states} states)"
                )

    def measure_snapshots(self, snapshots: Iterable[Snapshot]) -> SnapshotFootprint:
        """What ``snapshots`` hold beyond the current state, in nodes
        (spec/hashlife-multistate.md "Snapshots")."""
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
            if k > 1:
                a, b, c, d = data[n]
                k -= 1
                stack += ((a, k), (b, k), (c, k), (d, k))
        return count

    # -- frames -------------------------------------------------------------------------

    def render(
        self, view: LifeView, size: tuple[int, int], mode: StateRenderMode = "state"
    ) -> NDArray[np.uint8]:
        """The (height, width) uint8 frame of ``view``: states (zoomed out, each block's
        shown state under the zoom order), or ``density`` as the two-state universe gives
        it, counting non-zero cells."""
        from heaton_life.ca.hashlife.multistate.render import render as render_frame

        width, height = _ints(*size)
        return render_frame(self, view, (width, height), mode)

    def _tile_cache(self, s: int, mode: str) -> dict[int, NDArray[np.uint8]]:
        """Rendered tiles by node id; collection reuses ids, so it empties the cache."""
        from heaton_life.ca.hashlife.render import TILE_CACHE_LIMIT

        stale = self._tiles_epoch != self._store.collections
        if stale or sum(len(v) for v in self._tiles.values()) > TILE_CACHE_LIMIT:
            self._tiles = {}
            self._tiles_epoch = self._store.collections
        return self._tiles.setdefault((s, mode), {})

    def _shown_state(self, n: int, k: int) -> int:
        """The state level-k node n shows zoomed out: its non-zero state first in the zoom
        order, or 0 when it has none."""
        if self._shown and self._tiles_epoch != self._store.collections:
            self._shown = {}
        return self._shown_of(n, k)

    def _shown_of(self, n: int, k: int) -> int:
        store = self._store
        if k == 1:
            ranks = self._ranks
            best = 0
            for state in unpack(store.data[n]):
                if state and ranks[state] < ranks[best]:
                    best = state
            return best
        hit = self._shown.get(n)
        if hit is not None:
            return hit
        ranks = self._ranks
        best = 0
        if n != store.empty(k):
            for child in store.data[n]:  # a plain loop: one frame per level
                state = self._shown_of(child, k - 1)
                if ranks[state] < ranks[best]:
                    best = state
        self._shown[n] = best
        return best

    # -- files --------------------------------------------------------------------------

    @classmethod
    def from_macrocell(
        cls,
        source: str | bytes,
        *,
        rule: str | StateRule | None = None,
        max_memory_mb: int = DEFAULT_MEMORY_MB,
    ) -> MultiStateHashLife:
        """Macrocell text or bytes (gzip too), placed by tree coordinates; ``rule`` is the
        rule when the file names none (default WireWorld)."""
        from heaton_life.ca.hashlife.multistate.macrocell import read_macrocell

        return read_macrocell(source, rule=rule, max_memory_mb=max_memory_mb)

    @classmethod
    def from_rle(
        cls,
        text: str,
        *,
        rule: str | StateRule | None = None,
        max_memory_mb: int = DEFAULT_MEMORY_MB,
    ) -> MultiStateHashLife:
        """RLE of either dialect; ``#CXRLE Pos=x,y Gen=n`` places it and sets the
        generation; ``rule`` is the rule when the header names none (default WireWorld)."""
        from heaton_life.ca.hashlife.multistate.rle import read_rle

        return read_rle(text, rule=rule, max_memory_mb=max_memory_mb)

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        rule: str | StateRule | None = None,
        max_memory_mb: int = DEFAULT_MEMORY_MB,
    ) -> MultiStateHashLife:
        """A Macrocell or RLE file, gzip-compressed or not, recognized by its content."""
        from heaton_life.ca.hashlife.multistate.files import read_multistate_universe

        data = Path(path).read_bytes()
        return read_multistate_universe(data, rule=rule, max_memory_mb=max_memory_mb).universe

    def read_snapshot(self, source: bytes | bytearray | memoryview | str) -> PatternSnapshot:
        """Read a Macrocell or RLE file into this universe's own store: a snapshot of its
        cells and generation, with its format, rule, metadata and a timeline's frames. The
        universe's state, rule and earlier snapshots stay as they were."""
        from heaton_life.ca.hashlife.multistate.files import read_multistate_snapshot

        return read_multistate_snapshot(self, source)

    def to_macrocell(self, metadata: PatternMetadata | None = None) -> str:
        """The canonical Macrocell text: the whole state, any size, in one string."""
        from heaton_life.ca.hashlife.multistate.macrocell import write_macrocell

        return write_macrocell(self, metadata)

    def to_rle(self, metadata: PatternMetadata | None = None) -> str:
        """RLE of the bounding box behind a ``#CXRLE`` line; inside the editing box only."""
        from heaton_life.ca.hashlife.multistate.rle import write_rle

        return write_rle(self, metadata)

    def save(self, path: str | Path, metadata: PatternMetadata | None = None) -> None:
        """Write by extension: ``.rle``, ``.mc``, or ``.mc.gz``, with ``metadata`` if given."""
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
        as (root, level), leaving the universe's own root, level and generation as they
        were: how a file is read into the store without becoming the state."""
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
        center (``kind`` in ``_ORDERS``), move them by ``shift`` (tree coordinates) onto
        ``new``, and paste them there by copy; the rest of ``old`` becomes 0."""
        while self._level < _TURN_LEVEL:
            self._expand()
        k = self._level
        origin = -(1 << (k - 1))
        told = (old[0], old[1] - 1, old[2], old[3] - 1)
        tnew = (new[0], new[1] - 1, new[2], new[3] - 1)
        lifted = self._keep(self._root, k, origin, origin, told)
        turned = self._transform(lifted, k, _ORDERS[kind], {})
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
        """The smallest centered root (level ≥ 1) that holds every non-zero cell."""
        return self._minimal_of(self._root, self._level)

    def _minimal_of(self, n: int, k: int) -> tuple[int, int]:
        """The smallest centered root (level ≥ 1) holding every non-zero cell of (n, k)."""
        store = self._store
        while k > 1:
            middle = store.center(n, k)
            if store.population(middle, k - 1) != store.population(n, k):
                break
            n, k = middle, k - 1
        return n, k

    def _leaves(self) -> Iterator[tuple[int, int, int]]:
        """Every non-empty leaf as (tree x, tree y, packed states), in no particular order."""
        store = self._store
        data = store.data
        origin = -(1 << (self._level - 1))
        stack = [(self._root, self._level, origin, origin)]
        while stack:
            n, k, nx, ny = stack.pop()
            if n == store.empty(k):
                continue
            if k == 1:
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
        """Land leaves ``{(bx, by): packed states}`` over the tree rectangle ``rect``."""
        self._contain(*rect)
        k = self._level
        # Which aligned nodes hold source cells, per level below the (centered) root.
        tiers: dict[int, set[tuple[int, int]]] = {}
        for level in range(2, k):
            shift = level - 1
            tiers[level] = {(bx >> shift, by >> shift) for bx, by in blocks}
        origin = -(1 << (k - 1))
        self._root = self._paste(self._root, k, origin, origin, rect, blocks, tiers, mode)

    def _contain(self, x0: int, y0: int, x1: int, y1: int) -> None:
        while True:
            half = 1 << (self._level - 1)
            if -half <= x0 and x1 < half and -half <= y0 and y1 < half:
                return
            self._expand()

    def _grow(self, n: int, k: int) -> int:
        """Centered level-k node n (k ≥ 1) inside a centered node twice its size."""
        store = self._store
        if k == 1:
            nw, ne, sw, se = unpack(store.data[n])
            leaf = store.leaf
            return store.join(
                leaf(pack(0, 0, 0, nw)), leaf(pack(0, 0, ne, 0)), leaf(pack(0, sw, 0, 0)),
                leaf(pack(se, 0, 0, 0)),
            )  # fmt: skip
        e = store.empty(k - 1)
        join = store.join
        a, b, c, d = store.data[n]
        return join(join(e, e, e, a), join(e, e, b, e), join(e, c, e, e), join(d, e, e, e))

    def _set(self, n: int, k: int, x: int, y: int, state: int) -> int:
        store = self._store
        if k == 1:
            shift = 8 * (y * 2 + x)
            return store.leaf((store.data[n] & ~(0xFF << shift)) | (state << shift))
        half = 1 << (k - 1)
        a, b, c, d = store.data[n]
        if y < half:
            if x < half:
                a = self._set(a, k - 1, x, y, state)
            else:
                b = self._set(b, k - 1, x - half, y, state)
        elif x < half:
            c = self._set(c, k - 1, x, y - half, state)
        else:
            d = self._set(d, k - 1, x - half, y - half, state)
        return store.join(a, b, c, d)

    def _clear(self, n: int, k: int, nx: int, ny: int, rect: tuple[int, int, int, int]) -> int:
        size = 1 << k
        store = self._store
        e = store.empty(k)
        if n == e or _disjoint(nx, ny, size, rect):
            return n
        if _covers(nx, ny, size, rect):
            return e
        if k == 1:
            cells = unpack(store.data[n])
            inside = _leaf_inside(nx, ny, rect)
            return store.leaf(pack(*(0 if inside[i] else cells[i] for i in range(4))))
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
        """Node n with every cell outside the tree rectangle made 0."""
        size = 1 << k
        store = self._store
        e = store.empty(k)
        if n == e or _disjoint(nx, ny, size, rect):
            return e
        if _covers(nx, ny, size, rect):
            return n
        if k == 1:
            cells = unpack(store.data[n])
            inside = _leaf_inside(nx, ny, rect)
            return store.leaf(pack(*(cells[i] if inside[i] else 0 for i in range(4))))
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
        if k == 1:
            ins, outs = unpack(data[inside]), unpack(data[outside])
            mask = _leaf_inside(nx, ny, rect)
            return store.leaf(pack(*(ins[i] if mask[i] else outs[i] for i in range(4))))
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

    def _transform(self, n: int, k: int, order: tuple[int, ...], memo: dict[int, int]) -> int:
        """Level-k node n turned or mirrored about its own center (``_ORDERS``)."""
        hit = memo.get(n)
        if hit is not None:
            return hit
        store = self._store
        if k == 1:
            cells = unpack(store.data[n])
            r = store.leaf(pack(*(cells[i] for i in order)))
        elif n == store.empty(k):
            r = n
        else:
            kids = store.data[n]
            k1 = k - 1
            turned = []
            for i in order:  # a plain loop: one frame per level (spec/hashlife.md "Depth")
                turned.append(self._transform(kids[i], k1, order, memo))
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
        if k == 1:
            ca, cb, cc, cd = unpack(data[a]), unpack(data[b]), unpack(data[c]), unpack(data[d])
            square = (
                (ca[0], ca[1], cb[0], cb[1]),
                (ca[2], ca[3], cb[2], cb[3]),
                (cc[0], cc[1], cd[0], cd[1]),
                (cc[2], cc[3], cd[2], cd[3]),
            )
            r = store.leaf(
                pack(square[oy][ox], square[oy][ox + 1], square[oy + 1][ox], square[oy + 1][ox + 1])
            )
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
        if k == 1:
            old = unpack(store.data[n])
            src = unpack(blocks.get((nx >> 1, ny >> 1), 0))
            inside = _leaf_inside(nx, ny, rect)
            new = []
            for i in range(4):
                if not inside[i]:
                    new.append(old[i])
                elif mode == "copy":
                    new.append(src[i])
                elif mode == "or":
                    new.append(src[i] or old[i])
                elif mode == "xor":
                    new.append(old[i] ^ src[i])
                else:  # and
                    new.append(old[i] & src[i])
            return store.leaf(pack(*new))
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

    def _count(
        self, n: int, k: int, nx: int, ny: int, rect: tuple[int, int, int, int], odd: bool = False
    ) -> int:
        """The non-zero cells of level-k node n (or with ``odd`` its odd ones) inside
        ``rect``, the node's top-left at tree position (nx, ny)."""
        size = 1 << k
        store = self._store
        if n == store.empty(k) or _disjoint(nx, ny, size, rect):
            return 0
        if _covers(nx, ny, size, rect):
            return store.odd_population(n, k) if odd else store.population(n, k)
        if k == 1:
            cells = unpack(store.data[n])
            inside = _leaf_inside(nx, ny, rect)
            mask = 1 if odd else 0xFF
            return sum(1 for i in range(4) if inside[i] and cells[i] & mask)
        half = size >> 1
        a, b, c, d = store.data[n]
        k1 = k - 1
        return (
            self._count(a, k1, nx, ny, rect, odd)
            + self._count(b, k1, nx + half, ny, rect, odd)
            + self._count(c, k1, nx, ny + half, rect, odd)
            + self._count(d, k1, nx + half, ny + half, rect, odd)
        )

    def _max_state(self, n: int, k: int, memo: dict[int, int]) -> int:
        """The largest state in level-k node n."""
        store = self._store
        if k == 1:
            return max(unpack(store.data[n]))
        if n == store.empty(k):
            return 0
        hit = memo.get(n)
        if hit is not None:
            return hit
        top = 0
        for child in store.data[n]:  # a plain loop: one frame per level
            top = max(top, self._max_state(child, k - 1, memo))
        memo[n] = top
        return top

    def _max_state_in(
        self,
        n: int,
        k: int,
        nx: int,
        ny: int,
        rect: tuple[int, int, int, int],
        memo: dict[int, int],
    ) -> int:
        """The largest state of node n's cells inside the tree rectangle (0 when none)."""
        size = 1 << k
        store = self._store
        if n == store.empty(k) or _disjoint(nx, ny, size, rect):
            return 0
        if _covers(nx, ny, size, rect):
            return self._max_state(n, k, memo)
        if k == 1:
            cells = unpack(store.data[n])
            inside = _leaf_inside(nx, ny, rect)
            return max(cells[i] if inside[i] else 0 for i in range(4))
        half = size >> 1
        kids = store.data[n]
        top = 0
        corners = ((nx, ny), (nx + half, ny), (nx, ny + half), (nx + half, ny + half))
        for i in range(4):
            top = max(top, self._max_state_in(kids[i], k - 1, *corners[i], rect, memo))
        return top

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
        if k == 1:
            x0, y0, _, _ = rect
            cells = unpack(store.data[n])
            inside = _leaf_inside(nx, ny, rect)
            for i in range(4):
                if inside[i] and cells[i]:
                    out[ny + (i >> 1) - y0, nx + (i & 1) - x0] = cells[i]
            return
        half = size >> 1
        a, b, c, d = store.data[n]
        k1 = k - 1
        self._extract(a, k1, nx, ny, rect, out)
        self._extract(b, k1, nx + half, ny, rect, out)
        self._extract(c, k1, nx, ny + half, rect, out)
        self._extract(d, k1, nx + half, ny + half, rect, out)

    def _edge(self, which: str) -> int:
        """One extreme of the non-zero cells, as an offset from the root's origin."""
        return self._node_edge(self._root, self._level, which, {})

    def _node_edge(self, n: int, k: int, which: str, memo: dict[int, int]) -> int:
        """One extreme of the non-zero cells of non-empty level-k node n, as an offset from
        its origin; ``memo`` holds this edge's answers by node."""
        hit = memo.get(n)
        if hit is not None:
            return hit
        store = self._store
        if k == 1:
            edge = _leaf_edge(unpack(store.data[n]), which)
            assert edge is not None  # the node is non-empty
            r = edge
        else:
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
        """One extreme of node n's non-zero cells inside the tree rectangle, as a tree
        coordinate, or None when it holds none. The near half is searched first."""
        size = 1 << k
        store = self._store
        if n == store.empty(k) or _disjoint(nx, ny, size, rect):
            return None
        base = nx if which in ("min_x", "max_x") else ny
        if _covers(nx, ny, size, rect):
            return base + self._node_edge(n, k, which, memo)
        if k == 1:
            cells = unpack(store.data[n])
            inside = _leaf_inside(nx, ny, rect)
            masked = tuple(cells[i] if inside[i] else 0 for i in range(4))
            edge = _leaf_edge(masked, which)  # type: ignore[arg-type]
            return None if edge is None else base + edge
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
