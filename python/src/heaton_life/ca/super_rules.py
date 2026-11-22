"""Super rules (spec/super.md): any Life-like rule with 26 states.

States 0–6 are a History rule's (spec/history.md) and behave as they do there. States 7–25
add on cells that leave no trail (7 and the odd states 13–25), two more trails with
envelopes of their own (9 and 10, 11 and 12), and labels, the even states 14–24, that
vanish, wait to be cleared, cycle, or appear when something touches them. The on cells
(the odd states) run the base rule's table exactly as a two-state world's live cells do,
away from boundary cells (6). A newborn takes its state from its parents, the on cells
among its neighbors.

This module holds the cell function the multi-state HashLife runs (``SuperRule``) and the
vectorized grid step the Life-like family runs; the tests pin that the two agree.
"""

from __future__ import annotations

import functools
from collections.abc import Iterable, Sequence
from typing import Final

import numpy as np
from numpy.typing import NDArray

from heaton_life.ca.history import _NEIGHBOR_BITS, _NEIGHBORS
from heaton_life.ca.rulestring import LifeRule, compile_rule
from heaton_life.ca.state_rules import StateRule
from heaton_life.core.topology import Halo

STATES: Final = 26
"""A Super rule's states (spec/super.md "States")."""
NAMES: Final = (
    "off",
    "on",
    "envelope",
    "marked on",
    "marked off",
    "start on",
    "boundary",
    "marked on, no trail",
    "marked off, no trail",
    "second trail: on",
    "second trail: envelope",
    "third trail: on",
    "third trail: envelope",
    "no trail 1",
    "vanishing label",
    "no trail 2",
    "clearable label",
    "no trail 3",
    "cycling label 1",
    "no trail 4",
    "cycling label 2",
    "no trail 5",
    "cycling label 3",
    "no trail 6",
    "hidden label",
    "no trail 7",
)
BOUNDARY: Final = 6
MARKED_ON, MARKED_OFF, NO_TRAIL_MARKED_ON, NO_TRAIL_MARKED_OFF = 3, 4, 7, 8
NO_TRAIL: Final = (13, 15, 17, 19, 21, 23, 25)
"""The on states that leave no trail when they die."""
TRAILS: Final = (9, 11)
"""The second and third trails' on states; each dies into the state after it."""
LABELS: Final = (14, 16, 18, 20, 22, 24)
VANISHING, CLEARABLE, CYCLING_1, CYCLING_2, CYCLING_3, HIDDEN = LABELS

# An on cell's state when it turns off: 1 → 2, 3 and 5 → 4, 7 → 8, 9 → 10, 11 → 12, and a
# no-trail state → 0 (spec/super.md "Evolution"); an off state maps to itself.
_DEATH: Final = tuple(
    {1: 2, 3: 4, 5: 4, 7: 8, 9: 10, 11: 12}.get(s, 0 if s & 1 else s) for s in range(STATES)
)
# A cell's next state beside a boundary cell: 7, 8, the no-trail states and the labels → 0,
# the others as on turning off or staying off.
_WALLED: Final = tuple(0 if s in (7, 8) or s >= 13 else _DEATH[s] for s in range(STATES))
_DEATH_ARRAY: Final = np.array(_DEATH, dtype=np.uint8)
_WALLED_ARRAY: Final = np.array(_WALLED, dtype=np.uint8)
# The eight neighbors' bits in the neighborhood index, in block order NW N NE W E SW S SE.
_BITS: Final = (256, 128, 64, 32, 8, 4, 2, 1)


def _check(rule: LifeRule) -> LifeRule:
    if rule.variant != "Super":
        raise ValueError(f"{rule.canonical} is not a Super rule (spec/super.md)")
    return rule


def newborn(parents: Iterable[int]) -> int:
    """A newborn's state from its parents' states, the on cells among its neighbors (spec/
    super.md "The newborn's state"): the first of these that applies — one no-trail state s
    with any 3s gives s; one trail state t with any 7s gives t; 7s and no-trail states give
    13; anything else, a birth with no parents included, gives 1."""
    count = 0
    no_trail = trail = 0
    first = second = third = True
    for parent in parents:
        count += 1
        quiet = parent >= 13  # one of the no-trail states 13, 15, …, 25
        if parent != MARKED_ON:
            if quiet and no_trail in (0, parent):
                no_trail = parent
            else:
                first = False
        if parent != NO_TRAIL_MARKED_ON:
            if parent in TRAILS and trail in (0, parent):
                trail = parent
            else:
                second = False
            if not quiet:
                third = False
    if count == 0:
        return 1
    if first and no_trail:
        return no_trail
    if second and trail:
        return trail
    if third:
        return 13
    return 1


def _label(state: int, neighbors: Sequence[int]) -> int:
    """An off cell's next state when it stays off (spec/super.md "Evolution")."""
    if state == VANISHING:
        return 0
    if state == CLEARABLE:
        return VANISHING if any(v & 1 or v == VANISHING for v in neighbors) else state
    if state == CYCLING_1:
        return CYCLING_3 if CYCLING_3 in neighbors else state
    if state == CYCLING_2:
        return CYCLING_1 if CYCLING_1 in neighbors else state
    if state == CYCLING_3:
        return CYCLING_2 if CYCLING_2 in neighbors else state
    if state == HIDDEN:
        hit = any(v & 1 or v in (VANISHING, CYCLING_1) for v in neighbors)
        return CYCLING_1 if hit else state
    return state


def next_state(table: bytes, near: int, block: Sequence[int]) -> int:
    """A cell's next state from its 3 × 3 block, row-major (NW N NE / W C E / SW S SE): the
    base rule's ``table`` read at the index of the block's on cells, and ``near`` the
    neighbors the rule counts as bits of that index (spec/super.md "Evolution")."""
    c = block[4]
    if c == BOUNDARY:
        return BOUNDARY
    around = (*block[:4], *block[5:])
    neighbors = [v for v, bit in zip(around, _BITS, strict=True) if near & bit]
    if BOUNDARY in neighbors:
        return _WALLED[c]
    index = 0
    for v in block:
        index = index << 1 | (v & 1)
    if c & 1:
        return c if table[index] else _DEATH[c]
    if table[index]:
        if c == MARKED_OFF:
            return MARKED_ON
        if c == NO_TRAIL_MARKED_OFF:
            return NO_TRAIL_MARKED_ON
        return newborn(v for v in neighbors if v & 1)
    return _label(c, neighbors)


def step(cells: NDArray[np.uint8], halo: Halo, rule: LifeRule) -> NDArray[np.uint8]:
    """One generation of a Super grid (spec/super.md "Evolution"), its edges read through
    ``halo`` (radius 1, the grid's size; spec/topology.md). A new array."""
    _check(rule)
    height, width = cells.shape
    padded = halo.fill(cells)

    def window(dy: int, dx: int) -> NDArray[np.uint8]:
        return padded[1 + dy : 1 + dy + height, 1 + dx : 1 + dx + width]

    index = np.zeros((height, width), dtype=np.uint16)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            index |= (window(dy, dx) & 1).astype(np.uint16) << (4 - 3 * dy - dx)
    neighbors = [window(dy, dx) for dy, dx in _NEIGHBORS[rule.neighborhood]]
    walled = np.zeros((height, width), dtype=bool)
    for around in neighbors:
        walled |= around == BOUNDARY
    on = np.frombuffer(rule.table, dtype=np.uint8)[index].astype(bool) & ~walled
    odd = (cells & 1).astype(bool)
    free = ~walled & (cells != BOUNDARY)
    stepped = cells.copy()  # an on cell staying on, and an off one staying off, keep theirs
    beside = walled & (cells != BOUNDARY)
    stepped[beside] = _WALLED_ARRAY[cells[beside]]
    dies = free & odd & ~on
    stepped[dies] = _DEATH_ARRAY[cells[dies]]
    born = free & ~odd & on
    stepped[born & (cells == MARKED_OFF)] = MARKED_ON
    stepped[born & (cells == NO_TRAIL_MARKED_OFF)] = NO_TRAIL_MARKED_ON
    taken = born & (cells != MARKED_OFF) & (cells != NO_TRAIL_MARKED_OFF)
    if taken.any():
        stepped[taken] = _newborns(np.stack([around[taken] for around in neighbors]))
    stays = free & ~odd & ~on
    if stays.any():
        touched = np.zeros((height, width), dtype=bool)  # a neighbor is on
        has: dict[int, NDArray[np.bool_]] = {
            label: np.zeros((height, width), dtype=bool) for label in LABELS
        }
        for around in neighbors:
            touched |= (around & 1).astype(bool)
            for label in (VANISHING, CYCLING_1, CYCLING_2, CYCLING_3):
                has[label] |= around == label
        stepped[stays & (cells == VANISHING)] = 0
        stepped[stays & (cells == CLEARABLE) & (touched | has[VANISHING])] = VANISHING
        stepped[stays & (cells == CYCLING_1) & has[CYCLING_3]] = CYCLING_3
        stepped[stays & (cells == CYCLING_2) & has[CYCLING_1]] = CYCLING_1
        stepped[stays & (cells == CYCLING_3) & has[CYCLING_2]] = CYCLING_2
        hit = touched | has[VANISHING] | has[CYCLING_1]
        stepped[stays & (cells == HIDDEN) & hit] = CYCLING_1
    return stepped


def _newborns(parents: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """``newborn`` for many cells at once: ``parents`` holds each cell's neighbors' states,
    one row per neighbor and one column per cell (only the odd states are parents)."""
    count = (parents & 1).sum(axis=0, dtype=np.int64)
    marked_on = (parents == MARKED_ON).sum(axis=0, dtype=np.int64)
    no_trail_marked_on = (parents == NO_TRAIL_MARKED_ON).sum(axis=0, dtype=np.int64)
    conditions: list[NDArray[np.bool_]] = []
    choices: list[int] = []
    quiet = np.zeros(count.shape, dtype=np.int64)
    for state in NO_TRAIL:
        same = (parents == state).sum(axis=0, dtype=np.int64)
        quiet += same
        conditions.append((same > 0) & (same + marked_on == count))
        choices.append(state)
    for state in TRAILS:
        same = (parents == state).sum(axis=0, dtype=np.int64)
        conditions.append((same > 0) & (same + no_trail_marked_on == count))
        choices.append(state)
    conditions.append((count > 0) & (quiet + no_trail_marked_on == count))
    choices.append(13)
    chosen: NDArray[np.uint8] = np.select(conditions, choices, default=1).astype(np.uint8)
    return chosen


def check_cells(cells: NDArray[np.generic]) -> NDArray[np.uint8]:
    """``cells`` as Super states (0–25), refusing any other value."""
    array = np.asarray(cells)
    if array.size and (array.dtype.kind not in "biu" or int(array.min()) < 0):
        raise ValueError("Super cells are states 0 to 25")
    if array.size and int(array.max()) >= STATES:
        raise ValueError(f"state {int(array.max())} is not a Super state (0 to {STATES - 1})")
    return array.astype(np.uint8)


class SuperRule(StateRule):
    """A Super rule as the multi-state HashLife runs it (spec/hashlife-multistate.md "State
    rules"): 26 states, the rule's canonical name, and super.md's evolution as the cell
    function. A base rule with B0 is refused: the plane's background would change."""

    def __init__(self, rule: LifeRule) -> None:
        self.rule = _check(rule)
        if rule.has_b0:
            raise ValueError(
                f"{rule.canonical} has B0: its first generation would turn the whole "
                "plane on, and the unbounded universe's background must stay 0 "
                '(spec/super.md "On the unbounded plane"); a grid runs it'
            )
        self.canonical = rule.canonical
        self.states = STATES
        self._table = rule.table
        self._near = _NEIGHBOR_BITS[rule.neighborhood]

    def next_state(
        self, nw: int, n: int, ne: int, w: int, c: int, e: int, sw: int, s: int, se: int
    ) -> int:
        return next_state(self._table, self._near, (nw, n, ne, w, c, e, sw, s, se))


def is_super(rule: StateRule) -> bool:
    """Whether a state rule is a Super rule."""
    return isinstance(rule, SuperRule)


def super_rule(text: str) -> SuperRule | None:
    """The state rule a Super rule's text names (``B3/S23Super``, ``LifeSuper``, any
    notation of spec/rules.md), or None for text that is no Super rule. Every spelling of a
    rule gives the same object. Raises ValueError for a Super rule the multi-state universe
    can't run (a base with B0)."""
    try:
        rule = compile_rule(text, presets=False, variants=True)
    except ValueError:
        return None
    if rule.variant != "Super":
        return None
    return _super_rule(rule)


@functools.lru_cache(maxsize=32)
def _super_rule(rule: LifeRule) -> SuperRule:
    return SuperRule(rule)
