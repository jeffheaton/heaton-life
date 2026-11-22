"""A Life-like world converted between the two engines (spec/hashlife-multistate.md
"Converting between the engines").

The cells never become a grid: each distinct node of the old tree is converted once, into
the new universe's store, and the tree keeps its root, its level and its place. A two-state
universe's live cells become state 1 of a History or Super rule; a History or Super
universe's on cells, its odd states, become a two-state universe's live cells; and a History
or Super universe under another of those rules keeps each state the rule has and turns any
other into its parity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from heaton_life.ca.hashlife.multistate.macrocell import _bits_node
from heaton_life.ca.hashlife.multistate.store import StateStore, pack, unpack
from heaton_life.ca.hashlife.multistate.universe import MultiStateHashLife
from heaton_life.ca.rulestring import compile_rule
from heaton_life.ca.state_rules import StateRule, resolve_rule

if TYPE_CHECKING:
    from heaton_life.ca.hashlife.universe import HashLife

_PAGE = 'spec/hashlife-multistate.md "Converting between the engines"'


def _life_like(rule: StateRule) -> bool:
    """Whether a state rule is a History or Super rule, a Life-like rule of many states."""
    # Imported here: the families import heaton_life.ca, which imports this package.
    from heaton_life.ca.history import is_history
    from heaton_life.ca.super_rules import is_super

    return is_history(rule) or is_super(rule)


def _require_life_like(rule: StateRule, whose: str) -> None:
    if not _life_like(rule):
        raise ValueError(
            f"{whose}{rule.canonical} is no History or Super rule: a world converts between "
            f"Life-like rules only, two states, History and Super ({_PAGE})"
        )


def _odd_bits(store: StateStore, n: int) -> int:
    """A level-3 node of states as a two-state 8 × 8 leaf (bit 8r + c is row r, column c):
    its odd cells live."""
    bits = 0
    data = store.data
    for quarter, (qx, qy) in zip(data[n], ((0, 0), (4, 0), (0, 4), (4, 4)), strict=True):
        for leaf, (lx, ly) in zip(data[quarter], ((0, 0), (2, 0), (0, 2), (2, 2)), strict=True):
            nw, ne, sw, se = unpack(data[leaf])
            x, y = qx + lx, qy + ly
            bits |= (
                (nw & 1) << (8 * y + x)
                | (ne & 1) << (8 * y + x + 1)
                | (sw & 1) << (8 * y + x + 8)
                | (se & 1) << (8 * y + x + 9)
            )
    return bits


def to_multistate_from_two_state(
    universe: HashLife, rule: str | StateRule, max_memory_mb: int | None
) -> MultiStateHashLife:
    """``HashLife.to_multistate``: a new universe of a History or Super rule, its cells the
    two-state universe's live cells as state 1, its generation the same."""
    target = resolve_rule(rule)
    _require_life_like(target, "")
    if universe.background:
        raise ValueError(
            f"the universe's background is alive at generation {universe.generation} (its rule "
            f"{universe.rule} has B0): a universe of many states has a background of 0 ({_PAGE})"
        )
    budget = universe.max_memory_mb if max_memory_mb is None else max_memory_mb
    out = MultiStateHashLife(target, max_memory_mb=budget)
    src, dst = universe._store, out._store
    memo: dict[int, int] = {}

    def convert(n: int, k: int) -> int:
        if n == src.empty(k):
            return dst.empty(k)
        hit = memo.get(n)
        if hit is not None:
            return hit
        if k == 3:
            r = _bits_node(dst, src.data[n])
        else:
            a, b, c, d = src.data[n]
            k1 = k - 1
            r = dst.join(convert(a, k1), convert(b, k1), convert(c, k1), convert(d, k1))
        memo[n] = r
        return r

    out._adopt(convert(universe._root, universe._level), universe._level, universe.generation)
    return out


def to_two_state(universe: MultiStateHashLife, rule: str, max_memory_mb: int | None) -> HashLife:
    """``MultiStateHashLife.to_two_state``: a new two-state universe of ``rule``, its live
    cells the odd states of a History or Super universe, its generation the same."""
    from heaton_life.ca.hashlife.universe import HashLife

    _require_life_like(universe.state_rule, "the universe's rule ")
    budget = universe.max_memory_mb if max_memory_mb is None else max_memory_mb
    out = HashLife(rule, max_memory_mb=budget)
    generation = universe.generation
    if compile_rule(out.rule, presets=False).background(generation):
        raise ValueError(
            f"{out.rule} has B0 and its background is alive at generation {generation}: the "
            f"world's cells, on a background of 0, can't be its cells ({_PAGE}; "
            'spec/hashlife.md "Rules with B0")'
        )
    src, dst = universe._store, out._store
    root, level = universe._root, universe._level
    while level < 4:  # the two-state tree's leaves are 8 × 8, its root at least level 4
        root, level = universe._grow(root, level), level + 1
    memo: dict[int, int] = {}

    def convert(n: int, k: int) -> int:
        if n == src.empty(k):
            return dst.empty(k)
        hit = memo.get(n)
        if hit is not None:
            return hit
        if k == 3:
            r = dst.leaf(_odd_bits(src, n))
        else:
            a, b, c, d = src.data[n]
            k1 = k - 1
            r = dst.join(convert(a, k1), convert(b, k1), convert(c, k1), convert(d, k1))
        memo[n] = r
        return r

    out._adopt(convert(root, level), level, generation)
    return out


def to_multistate(
    universe: MultiStateHashLife, rule: str | StateRule, max_memory_mb: int | None
) -> MultiStateHashLife:
    """``MultiStateHashLife.to_multistate``: a new universe of another History or Super
    rule, each state the rule has kept and every other state turned into its parity
    (``convert_cells``), its generation the same."""
    _require_life_like(universe.state_rule, "the universe's rule ")
    target = resolve_rule(rule)
    _require_life_like(target, "")
    budget = universe.max_memory_mb if max_memory_mb is None else max_memory_mb
    out = MultiStateHashLife(target, max_memory_mb=budget)
    states = target.states
    table = [s if s < states else s & 1 for s in range(256)]
    src, dst = universe._store, out._store
    memo: dict[int, int] = {}

    def convert(n: int, k: int) -> int:
        if n == src.empty(k):
            return dst.empty(k)
        hit = memo.get(n)
        if hit is not None:
            return hit
        if k == 1:
            nw, ne, sw, se = unpack(src.data[n])
            r = dst.leaf(pack(table[nw], table[ne], table[sw], table[se]))
        else:
            a, b, c, d = src.data[n]
            k1 = k - 1
            r = dst.join(convert(a, k1), convert(b, k1), convert(c, k1), convert(d, k1))
        memo[n] = r
        return r

    out._adopt(convert(universe._root, universe._level), universe._level, universe.generation)
    return out
