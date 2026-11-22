"""History rules (spec/history.md): any Life-like rule with seven states.

The on cells (odd states) run the base rule's table exactly as a two-state world's live
cells do; the other states record the envelope (cells once on) and marks, and boundary
cells (6) never change and keep every cell beside them off. This module holds the one
table of state changes, the vectorized grid step the Life-like family runs, and the cell
function the multi-state HashLife runs (``HistoryRule``).

Variants with more states (Super, 26) plug in the same way: a state count, a table of
state changes, and a cell function.
"""

from __future__ import annotations

import functools
from typing import Final

import numpy as np
from numpy.typing import NDArray

from heaton_life.ca.rulestring import LifeRule, Neighborhood, compile_rule
from heaton_life.ca.state_rules import StateRule, _b0_reason, _StateRuleError
from heaton_life.core.topology import Halo

STATES: Final = 7
"""A History rule's states: 0 off, 1 on, 2 envelope, 3 marked on, 4 marked off, 5 start
on, 6 boundary (spec/history.md "States")."""
OFF, ON, ENVELOPE, MARKED_ON, MARKED_OFF, START_ON, BOUNDARY = range(STATES)
NAMES: Final = ("off", "on", "envelope", "marked on", "marked off", "start on", "boundary")
LETTERS: Final = (".", "A", "B", "C", "D", "E", "F")
"""Each state's letter in the extended dialect of RLE (spec/patterns.md)."""

NEXT: Final = np.array([[0, 1], [2, 1], [2, 1], [4, 3], [4, 3], [4, 5], [6, 6]], dtype=np.uint8)
"""``NEXT[state][on]``: a cell's next state from its state and whether it is on next
(spec/history.md "Evolution")."""
_NEXT_FLAT: Final = tuple(int(v) for v in NEXT.reshape(-1))

# The neighbors whose boundary cells keep a cell off, by the rule's neighborhood
# (spec/rules.md "Neighborhoods"): offsets (dy, dx) of the 3 × 3 block, the cell excluded.
_ALL: Final = tuple((dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy, dx) != (0, 0))
_NEIGHBORS: Final[dict[Neighborhood, tuple[tuple[int, int], ...]]] = {
    "moore": _ALL,
    "hexagonal": tuple(o for o in _ALL if o not in ((-1, 1), (1, -1))),  # no NE, no SW
    "vonneumann": ((-1, 0), (0, -1), (0, 1), (1, 0)),
}
# The same as bits of the neighborhood index: NW 256, N 128, NE 64, W 32, E 8, SW 4, S 2,
# SE 1 (spec/rules.md "The transition table").
_NEIGHBOR_BITS: Final[dict[Neighborhood, int]] = {
    "moore": 0x1EF,
    "hexagonal": 0x1AB,
    "vonneumann": 0xAA,
}


def _check(rule: LifeRule) -> LifeRule:
    if rule.variant != "History":
        raise ValueError(f"{rule.canonical} is not a History rule (spec/history.md)")
    return rule


def step(cells: NDArray[np.uint8], halo: Halo, rule: LifeRule) -> NDArray[np.uint8]:
    """One generation of a History grid (spec/history.md "Evolution"), its edges read
    through ``halo`` (radius 1, the grid's size; spec/topology.md). A new array."""
    _check(rule)
    height, width = cells.shape
    padded = halo.fill(cells)
    table = np.frombuffer(rule.table, dtype=np.uint8)
    index = np.zeros((height, width), dtype=np.uint16)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            window = padded[1 + dy : 1 + dy + height, 1 + dx : 1 + dx + width]
            index |= (window & 1).astype(np.uint16) << (4 - 3 * dy - dx)
    beside = np.zeros((height, width), dtype=bool)
    for dy, dx in _NEIGHBORS[rule.neighborhood]:
        beside |= padded[1 + dy : 1 + dy + height, 1 + dx : 1 + dx + width] == BOUNDARY
    on = table[index] & ~beside
    stepped: NDArray[np.uint8] = NEXT[cells, on]
    return stepped


def check_cells(cells: NDArray[np.generic]) -> NDArray[np.uint8]:
    """``cells`` as History states (0–6), refusing any other value."""
    array = np.asarray(cells)
    if array.size and (array.dtype.kind not in "biu" or int(array.min()) < 0):
        raise ValueError("History cells are states 0 to 6")
    if array.size and int(array.max()) >= STATES:
        raise ValueError(f"state {int(array.max())} is not a History state (0 to {STATES - 1})")
    return array.astype(np.uint8)


class HistoryRule(StateRule):
    """A History rule as the multi-state HashLife runs it (spec/hashlife-multistate.md "State
    rules"): seven states, the rule's canonical name, and history.md's evolution as the
    cell function. A base rule with B0 is refused: the plane's background would change."""

    def __init__(self, rule: LifeRule) -> None:
        self.rule = _check(rule)
        if rule.has_b0:
            raise _StateRuleError(
                _b0_reason(rule.canonical), 'spec/history.md "On the unbounded plane"'
            )
        self.canonical = rule.canonical
        self.states = STATES
        self._table = rule.table
        self._near = _NEIGHBOR_BITS[rule.neighborhood]

    def next_state(
        self, nw: int, n: int, ne: int, w: int, c: int, e: int, sw: int, s: int, se: int
    ) -> int:
        if c == BOUNDARY:
            return BOUNDARY
        index = (
            (nw & 1) << 8
            | (n & 1) << 7
            | (ne & 1) << 6
            | (w & 1) << 5
            | (c & 1) << 4
            | (e & 1) << 3
            | (sw & 1) << 2
            | (s & 1) << 1
            | (se & 1)
        )
        boundary = (
            (nw == BOUNDARY) << 8
            | (n == BOUNDARY) << 7
            | (ne == BOUNDARY) << 6
            | (w == BOUNDARY) << 5
            | (e == BOUNDARY) << 3
            | (sw == BOUNDARY) << 2
            | (s == BOUNDARY) << 1
            | (se == BOUNDARY)
        )
        on = self._table[index] if boundary & self._near == 0 else 0
        return _NEXT_FLAT[2 * c + on]


def is_history(rule: StateRule) -> bool:
    """Whether a state rule is a History rule (the multi-state universe's random fill is
    for these alone)."""
    return isinstance(rule, HistoryRule)


def history_rule(text: str) -> HistoryRule | None:
    """The state rule a History rule's text names (``B3/S23History``, ``LifeHistory``, any
    notation of spec/rules.md), or None for text that is no History rule. Every spelling of
    a rule gives the same object. Raises ValueError for a History rule the multi-state
    universe can't run (a base with B0)."""
    try:
        rule = compile_rule(text, presets=False, variants=True)
    except ValueError:
        return None
    if rule.variant != "History":
        return None
    return _history_rule(rule)


@functools.lru_cache(maxsize=32)
def _history_rule(rule: LifeRule) -> HistoryRule:
    return HistoryRule(rule)
