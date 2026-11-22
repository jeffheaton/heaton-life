"""The multi-state node store: hash-consed quadtree nodes whose leaves hold states,
memoized results, and garbage collection under a memory budget
(spec/hashlife-multistate.md "Quadtree", "Evolution"; spec/hashlife.md "Memory").

Node ids index ``data``. A leaf is a level-1 node, a 2 × 2 square of states packed in one
int (NW in bits 0–7, NE 8–15, SW 16–23, SE 24–31); an internal node's entry is its children
``(nw, ne, sw, se)``. Each entry is also the node's key in ``table`` — int and tuple keys
never collide — so equal content is one node. Levels are not stored: every walk knows the
level it stands on.

The rule enters in one place: a level-2 node's center one generation on, computed from the
cell function and cached with the node's other results. Nothing here is observable, so the
C# port lays its nodes out its own way.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from heaton_life.ca.hashlife.store import Abort
from heaton_life.ca.state_rules import StateRule

# Accounting estimates for CPython 3.12, fitted to tracemalloc on Wireworld soups and
# circuits: one node with its table entry and id, and one cached result or population.
NODE_BYTES = 145
ENTRY_BYTES = 45
_CHECK_EVERY = 4096  # allocations between cancel/budget checks


def pack(nw: int, ne: int, sw: int, se: int) -> int:
    """Four states into a leaf's int."""
    return nw | ne << 8 | sw << 16 | se << 24


def unpack(leaf: int) -> tuple[int, int, int, int]:
    """A leaf's int into its four states (NW, NE, SW, SE)."""
    return leaf & 0xFF, (leaf >> 8) & 0xFF, (leaf >> 16) & 0xFF, leaf >> 24


def leaf_population(leaf: int) -> int:
    """The leaf's non-zero states."""
    return (
        (leaf & 0xFF != 0)
        + (leaf & 0xFF00 != 0)
        + (leaf & 0xFF0000 != 0)
        + (leaf & 0xFF000000 != 0)
    )


class StateStore:
    """Nodes, results, populations, and the collector for one multi-state universe."""

    __slots__ = (
        "_tick",
        "budget",
        "cancel_requested",
        "collections",
        "data",
        "empties",
        "free",
        "guard",
        "next_state",
        "pops",
        "res",
        "slow",
        "slow_j",
        "table",
    )

    def __init__(self, rule: StateRule, budget: int) -> None:
        self.next_state = rule.next_state
        self.budget = budget
        self.data: list[Any] = []  # int leaf | (nw, ne, sw, se) | None (free slot)
        self.table: dict[Any, int] = {}
        self.free: list[int] = []
        self.res: dict[int, int] = {}  # full-speed results (the base case among them)
        self.slow: dict[int, int] = {}  # fixed-step results for slow_j
        self.slow_j = -1
        self.pops: dict[int, int] = {}
        self.guard = False  # True while a step may be abandoned
        self.cancel_requested = False
        self.collections = 0
        self._tick = 0
        self.empties: list[int] = [-1, self.leaf(0)]  # by level; 0 unused

    # -- nodes --------------------------------------------------------------------------

    def leaf(self, states: int) -> int:
        n = self.table.get(states)
        if n is None:
            n = self._alloc(states)
        return n

    def join(self, nw: int, ne: int, sw: int, se: int) -> int:
        key = (nw, ne, sw, se)
        n = self.table.get(key)
        if n is None:
            n = self._alloc(key)
        return n

    def empty(self, k: int) -> int:
        e = self.empties
        while len(e) <= k:
            z = e[-1]
            e.append(self.join(z, z, z, z))
        return e[k]

    def _alloc(self, key: Any) -> int:
        if self.free:
            n = self.free.pop()
            self.data[n] = key
        else:
            n = len(self.data)
            self.data.append(key)
        self.table[key] = n
        self._tick += 1
        if self._tick >= _CHECK_EVERY:
            self._check()
        return n

    def _check(self) -> None:
        self._tick = 0
        if self.guard:
            if self.cancel_requested:
                raise Abort(canceled=True)
            if self.memory_used() > self.budget:
                raise Abort(canceled=False)

    # -- results ------------------------------------------------------------------------

    def use_rule(self, rule: StateRule) -> None:
        """Switch rules: cells survive, every cached result goes."""
        self.next_state = rule.next_state
        self.res = {}
        self.slow = {}

    def use_step(self, j: int) -> None:
        """Fixed-step results hold for one j at a time."""
        if j != self.slow_j:
            self.slow = {}
            self.slow_j = j

    def _base(self, n: int) -> int:
        """Level-2 node n → its center 2 × 2 one generation on (the base case): each center
        cell is the cell function of its 3 × 3 block."""
        data = self.data
        a, b, c, d = data[n]
        la, lb, lc, ld = data[a], data[b], data[c], data[d]
        if not (la | lb | lc | ld):
            return self.empties[1]  # f(0, …, 0) = 0
        # The 4 × 4 square, row by row: a0 a1 b0 b1 / a2 a3 b2 b3 / c0 c1 d0 d1 / c2 c3 d2 d3.
        a0, a1, a2, a3 = la & 0xFF, (la >> 8) & 0xFF, (la >> 16) & 0xFF, la >> 24
        b0, b1, b2, b3 = lb & 0xFF, (lb >> 8) & 0xFF, (lb >> 16) & 0xFF, lb >> 24
        c0, c1, c2, c3 = lc & 0xFF, (lc >> 8) & 0xFF, (lc >> 16) & 0xFF, lc >> 24
        d0, d1, d2, d3 = ld & 0xFF, (ld >> 8) & 0xFF, (ld >> 16) & 0xFF, ld >> 24
        f = self.next_state
        return self.leaf(
            f(a0, a1, b0, a2, a3, b2, c0, c1, d0)
            | f(a1, b0, b1, a3, b2, b3, c1, d0, d1) << 8
            | f(a2, a3, b2, c0, c1, d0, c2, c3, d2) << 16
            | f(a3, b2, b3, c1, d0, d1, c3, d2, d3) << 24
        )

    def full(self, n: int, k: int) -> int:
        """Level-k node n (k ≥ 2) → the level-(k−1) node at its center 2^(k−2) generations on."""
        r = self.res.get(n)
        if r is not None:
            return r
        if k == 2:
            r = self._base(n)
        else:
            data = self.data
            a, b, c, d = data[n]
            _, a2, a3, a4 = data[a]
            b1, _, b3, b4 = data[b]
            c1, c2, _, c4 = data[c]
            d1, d2, d3, _ = data[d]
            join = self.join
            full = self.full
            k1 = k - 1
            r00 = full(a, k1)
            r01 = full(join(a2, b1, a4, b3), k1)
            r02 = full(b, k1)
            r10 = full(join(a3, a4, c1, c2), k1)
            r11 = full(join(a4, b3, c2, d1), k1)
            r12 = full(join(b3, b4, d1, d2), k1)
            r20 = full(c, k1)
            r21 = full(join(c2, d1, c4, d3), k1)
            r22 = full(d, k1)
            r = join(
                full(join(r00, r01, r10, r11), k1),
                full(join(r01, r02, r11, r12), k1),
                full(join(r10, r11, r20, r21), k1),
                full(join(r11, r12, r21, r22), k1),
            )
        self.res[n] = r
        return r

    def center(self, n: int, k: int) -> int:
        """The level-(k−1) node at the center of level-k node n (k ≥ 2), no time advance."""
        data = self.data
        a, b, c, d = data[n]
        if k == 2:
            return self.leaf(
                data[a] >> 24
                | (data[b] >> 16 & 0xFF) << 8
                | (data[c] >> 8 & 0xFF) << 16
                | (data[d] & 0xFF) << 24
            )
        return self.join(data[a][3], data[b][2], data[c][1], data[d][0])

    def stepped(self, n: int, k: int, j: int) -> int:
        """Level-k node n (k ≥ 3, j ≤ k − 3) → the level-(k−1) node at its center 2^j
        generations on: centers first (no time), then ``result_j`` of the four overlaps."""
        r = self.slow.get(n)
        if r is not None:
            return r
        data = self.data
        a, b, c, d = data[n]
        _, a2, a3, a4 = data[a]
        b1, _, b3, b4 = data[b]
        c1, c2, _, c4 = data[c]
        d1, d2, d3, _ = data[d]
        join = self.join
        k1 = k - 1
        center = self.center
        s00 = center(a, k1)
        s01 = center(join(a2, b1, a4, b3), k1)
        s02 = center(b, k1)
        s10 = center(join(a3, a4, c1, c2), k1)
        s11 = center(join(a4, b3, c2, d1), k1)
        s12 = center(join(b3, b4, d1, d2), k1)
        s20 = center(c, k1)
        s21 = center(join(c2, d1, c4, d3), k1)
        s22 = center(d, k1)
        q00 = join(s00, s01, s10, s11)
        q01 = join(s01, s02, s11, s12)
        q10 = join(s10, s11, s20, s21)
        q11 = join(s11, s12, s21, s22)
        if k1 == j + 2:
            full = self.full
            r = join(full(q00, k1), full(q01, k1), full(q10, k1), full(q11, k1))
        else:
            st = self.stepped
            r = join(st(q00, k1, j), st(q01, k1, j), st(q10, k1, j), st(q11, k1, j))
        self.slow[n] = r
        return r

    # -- populations and memory ---------------------------------------------------------

    def population(self, n: int, k: int) -> int:
        """The non-zero cells of level-k node n."""
        if k == 1:
            return leaf_population(self.data[n])
        p = self.pops.get(n)
        if p is None:
            a, b, c, d = self.data[n]
            k1 = k - 1
            pop = self.population
            p = pop(a, k1) + pop(b, k1) + pop(c, k1) + pop(d, k1)
            self.pops[n] = p
        return p

    def memory_used(self) -> int:
        return (
            len(self.table) * NODE_BYTES
            + (len(self.res) + len(self.slow) + len(self.pops)) * ENTRY_BYTES
        )

    def collect(self, roots: Iterable[tuple[int, int]]) -> None:
        """Mark from ``roots`` ((node, level) pairs) and the empty nodes; free the rest.

        Full-speed results survive only when both ends do; fixed-step results go (they are
        cheap to recompute and their memory is what the budget is for).
        """
        data = self.data
        marked = bytearray(len(data))
        stack = [(e, k) for k, e in enumerate(self.empties) if k >= 1]
        stack.extend(roots)
        while stack:
            n, k = stack.pop()
            if marked[n]:
                continue
            marked[n] = 1
            if k > 1:
                a, b, c, d = data[n]
                k -= 1
                stack += ((a, k), (b, k), (c, k), (d, k))
        table: dict[Any, int] = {}
        free: list[int] = []
        for n, key in enumerate(data):
            if marked[n]:
                table[key] = n
            else:
                data[n] = None
                free.append(n)
        self.table = table
        self.free = free
        self.res = {n: r for n, r in self.res.items() if marked[n] and marked[r]}
        self.pops = {n: p for n, p in self.pops.items() if marked[n]}
        self.slow = {}
        self.collections += 1
