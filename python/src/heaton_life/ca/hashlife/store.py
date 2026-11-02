"""The HashLife node store: hash-consed quadtree nodes, memoized results, and garbage
collection under a memory budget (spec/hashlife.md "Quadtree", "Evolution", "Memory").

Node ids index ``data``. A leaf's entry is its 8×8 bitmap (an int); an internal node's
entry is its children ``(nw, ne, sw, se)``. Each entry is also the node's key in
``table`` — int and tuple keys never collide — so equal content is one node. Levels are
not stored: every walk knows the level it stands on.

Nothing here is observable: the spec pins cells, never layout, so the C# port may store
nodes however it likes.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from heaton_life.ca.hashlife.leaves import (
    LEFT4,
    MASK64,
    RIGHT4,
    advance1,
    advance2,
    center,
    compose,
    inner,
)

# Accounting estimates for CPython 3.12, fitted to tracemalloc on a soup and a gun run
# (within 2% of both): one node with its table entry and id, one cached result or
# population, one cached leaf result.
NODE_BYTES = 130
ENTRY_BYTES = 45
LEAF_ENTRY_BYTES = 100
_CHECK_EVERY = 4096  # allocations between cancel/budget checks


class Abort(Exception):
    """A guarded computation stopped: the budget filled, or a cancel was requested."""

    def __init__(self, *, canceled: bool) -> None:
        super().__init__("canceled" if canceled else "memory budget exhausted")
        self.canceled = canceled


class NodeStore:
    """Nodes, results, populations, and the collector for one universe."""

    __slots__ = (
        "_tick",
        "budget",
        "cancel_requested",
        "collections",
        "data",
        "empties",
        "free",
        "guard",
        "leaf1",
        "leaf2",
        "pops",
        "res",
        "slow",
        "slow_j",
        "t",
        "table",
    )

    def __init__(self, t: Sequence[int], budget: int) -> None:
        self.t = t
        self.budget = budget
        self.data: list[Any] = []  # int bitmap | (nw, ne, sw, se) | None (free slot)
        self.table: dict[Any, int] = {}
        self.free: list[int] = []
        self.res: dict[int, int] = {}  # full-speed results
        self.slow: dict[int, int] = {}  # fixed-step results for slow_j
        self.slow_j = -1
        self.leaf1: dict[int, int] = {}  # leaf bitmap -> center 4x4 one generation on
        self.leaf2: dict[int, int] = {}  # leaf bitmap -> center 4x4 two generations on
        self.pops: dict[int, int] = {}
        self.guard = False  # True while a step may be abandoned
        self.cancel_requested = False
        self.collections = 0
        self._tick = 0
        self.empties: list[int] = [-1, -1, -1, self.leaf(0)]  # by level; 0-2 unused

    # -- nodes --------------------------------------------------------------------------

    def leaf(self, bits: int) -> int:
        n = self.table.get(bits)
        if n is None:
            n = self._alloc(bits)
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

    def use_rule(self, t: Sequence[int]) -> None:
        """Switch rules: cells survive, every cached result goes."""
        self.t = t
        self.res = {}
        self.slow = {}
        self.leaf1 = {}
        self.leaf2 = {}

    def use_step(self, j: int) -> None:
        """Fixed-step results hold for one j at a time."""
        if j != self.slow_j:
            self.slow = {}
            self.slow_j = j

    def one(self, b: int) -> int:
        r = self.leaf1.get(b)
        if r is None:
            r = advance1(b, self.t)
            self.leaf1[b] = r
            self._tick += 1
        return r

    def two(self, b: int) -> int:
        r = self.leaf2.get(b)
        if r is None:
            r = advance2(b, self.t)
            self.leaf2[b] = r
            self._tick += 1
        return r

    def full(self, n: int, k: int) -> int:
        """Level-k node n (k ≥ 4) → the level-(k−1) node at its center 2^(k−2) generations on."""
        r = self.res.get(n)
        if r is not None:
            return r
        data = self.data
        a, b, c, d = data[n]
        if k == 4:
            # Children are leaves: the nine overlapping squares are bit shuffles, their
            # two-generation centers come from the leaf cache, and so do the second
            # phase's four.
            na, nb, nc, nd = data[a], data[b], data[c], data[d]
            n01 = ((na >> 4) & LEFT4) | ((nb << 4) & RIGHT4)
            n21 = ((nc >> 4) & LEFT4) | ((nd << 4) & RIGHT4)
            n10 = (na >> 32) | ((nc << 32) & MASK64)
            n12 = (nb >> 32) | ((nd << 32) & MASK64)
            n11 = (n01 >> 32) | ((n21 << 32) & MASK64)
            two = self.two
            r00, r01, r02 = two(na), two(n01), two(nb)
            r10, r11, r12 = two(n10), two(n11), two(n12)
            r20, r21, r22 = two(nc), two(n21), two(nd)
            r = self.leaf(
                compose(
                    two(compose(r00, r01, r10, r11)),
                    two(compose(r01, r02, r11, r12)),
                    two(compose(r10, r11, r20, r21)),
                    two(compose(r11, r12, r21, r22)),
                )
            )
        else:
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

    def stepped(self, n: int, k: int, j: int) -> int:
        """Level-k node n (k ≥ 4, j ≤ k − 3) → the level-(k−1) node at its center 2^j
        generations on: centers first (no time), then ``result_j`` of the four overlaps."""
        r = self.slow.get(n)
        if r is not None:
            return r
        data = self.data
        a, b, c, d = data[n]
        if k == 4:  # j is 0 or 1; children are leaves
            na, nb, nc, nd = data[a], data[b], data[c], data[d]
            n01 = ((na >> 4) & LEFT4) | ((nb << 4) & RIGHT4)
            n21 = ((nc >> 4) & LEFT4) | ((nd << 4) & RIGHT4)
            n10 = (na >> 32) | ((nc << 32) & MASK64)
            n12 = (nb >> 32) | ((nd << 32) & MASK64)
            n11 = (n01 >> 32) | ((n21 << 32) & MASK64)
            c00, c01, c02 = center(na), center(n01), center(nb)
            c10, c11, c12 = center(n10), center(n11), center(n12)
            c20, c21, c22 = center(nc), center(n21), center(nd)
            adv = self.two if j == 1 else self.one
            r = self.leaf(
                compose(
                    adv(compose(c00, c01, c10, c11)),
                    adv(compose(c01, c02, c11, c12)),
                    adv(compose(c10, c11, c20, c21)),
                    adv(compose(c11, c12, c21, c22)),
                )
            )
        else:
            _, a2, a3, a4 = data[a]
            b1, _, b3, b4 = data[b]
            c1, c2, _, c4 = data[c]
            d1, d2, d3, _ = data[d]
            join = self.join
            squares = (
                a,
                join(a2, b1, a4, b3),
                b,
                join(a3, a4, c1, c2),
                join(a4, b3, c2, d1),
                join(b3, b4, d1, d2),
                c,
                join(c2, d1, c4, d3),
                d,
            )
            k1 = k - 1
            cs: list[int] = []
            for sq in squares:
                p, q, s, u = data[sq]
                if k1 == 4:
                    cs.append(self.leaf(inner(data[p], data[q], data[s], data[u])))
                else:
                    cs.append(join(data[p][3], data[q][2], data[s][1], data[u][0]))
            q00 = join(cs[0], cs[1], cs[3], cs[4])
            q01 = join(cs[1], cs[2], cs[4], cs[5])
            q10 = join(cs[3], cs[4], cs[6], cs[7])
            q11 = join(cs[4], cs[5], cs[7], cs[8])
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
        if k == 3:
            return self.data[n].bit_count()  # type: ignore[no-any-return]
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
            + (len(self.leaf1) + len(self.leaf2)) * LEAF_ENTRY_BYTES
        )

    def collect(self, roots: Iterable[tuple[int, int]]) -> None:
        """Mark from ``roots`` ((node, level) pairs) and the empty nodes; free the rest.

        Results survive only when both ends do; fixed-step and leaf results go (they are
        cheap to recompute and their memory is what the budget is for).
        """
        data = self.data
        marked = bytearray(len(data))
        stack = [(e, k) for k, e in enumerate(self.empties) if k >= 3]
        stack.extend(roots)
        while stack:
            n, k = stack.pop()
            if marked[n]:
                continue
            marked[n] = 1
            if k > 3:
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
        self.leaf1 = {}
        self.leaf2 = {}
        self.collections += 1
