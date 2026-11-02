"""The HashLife universe (spec/hashlife.md): a Life-like rule on an unbounded plane.

Cells live in a hash-consed quadtree whose root is centered on the origin. Cell (x, y)
sits at tree position (x, y − 1) — Golly's placement, so Macrocell files land on the same
cells as in Golly — and every coordinate, generation, and population is a Python int.
"""

from __future__ import annotations

import dataclasses
import functools
import operator
import weakref
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from heaton_life.ca.hashlife.leaves import (
    array_blocks,
    columns,
    inner,
    leaf_cells,
    rect_mask,
    rule_table,
)
from heaton_life.ca.hashlife.render import TILE_CACHE_LIMIT, RenderMode
from heaton_life.ca.hashlife.render import render as render_frame
from heaton_life.ca.hashlife.store import Abort, NodeStore
from heaton_life.ca.hashlife.view import LifeView
from heaton_life.ca.rulestring import canonical_rule, parse_rule
from heaton_life.core.params import Params
from heaton_life.init.seeding import soup

EDIT_LIMIT = 1_000_000_000
"""Editing reaches cells with |x| ≤ EDIT_LIMIT and |y| ≤ EDIT_LIMIT."""
MAX_LEVEL = 512
"""The deepest tree (spec/hashlife.md "Depth"): every live cell lies within ±2^511, and
the walks below recurse at most once per level, well inside Python's recursion limit."""
DEFAULT_MEMORY_MB = 500
MIN_MEMORY_MB = 10
PasteMode = Literal["copy", "or", "xor"]
PASTE_MODES: tuple[PasteMode, ...] = ("copy", "or", "xor")
_MIN_LEVEL = 4  # the root is always an internal node
_MIN_STEP_LEVEL = 6  # sub-steps check containment on the root's great-grandchildren

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

    __slots__ = ("__weakref__", "_generation", "_level", "_owner", "_root")

    def __init__(self, owner: HashLife, root: int, level: int, generation: int) -> None:
        self._owner = weakref.ref(owner)
        self._root = root
        self._level = level
        self._generation = generation

    @property
    def generation(self) -> int:
        return self._generation


@functools.lru_cache(maxsize=16)
def _table(rule: str) -> tuple[int, ...]:
    birth, survive = parse_rule(rule)
    return rule_table(birth, survive)


def _hashlife_rule(rule: str) -> str:
    canonical = canonical_rule(rule)
    if 0 in parse_rule(canonical)[0]:
        raise ValueError(
            f"HashLife cannot run B0 rules ({canonical}): births with no live neighbors "
            "would fill the infinite background (spec/hashlife.md)"
        )
    return canonical


def _budget(max_memory_mb: int) -> int:
    mb = operator.index(max_memory_mb)
    if mb < MIN_MEMORY_MB:
        raise ValueError(f"max_memory_mb must be at least {MIN_MEMORY_MB}, got {mb}")
    return mb << 20


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


class HashLife:
    """An unbounded Life-like universe. See spec/hashlife.md for the full contract."""

    def __init__(self, rule: str = "B3/S23", *, max_memory_mb: int = DEFAULT_MEMORY_MB) -> None:
        self._rule = _hashlife_rule(rule)
        self._max_memory_mb = operator.index(max_memory_mb)
        self._store = NodeStore(_table(self._rule), _budget(max_memory_mb))
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
        """Change rules in place: the cells stay, cached results go."""
        canonical = _hashlife_rule(rule)
        if canonical != self._rule:
            self._rule = canonical
            self._store.use_rule(_table(canonical))

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
        return self._store.population(self._root, self._level)

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
        if x1 < x0 or y1 < y0:
            return 0
        origin = -(1 << (self._level - 1))
        return self._count(self._root, self._level, origin, origin, (x0, y0 - 1, x1, y1 - 1))

    def get_cell(self, x: int, y: int) -> int:
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
        check_box(x0, y0, x1, y1)
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
        if n < 0:
            raise ValueError(f"cannot step backward ({n} generations)")
        if n.bit_length() > MAX_LEVEL - 2:
            raise ValueError(
                f"a step of 2^{n.bit_length() - 1} generations or more needs a tree deeper "
                f"than level {MAX_LEVEL}; step(n) takes n < 2^{MAX_LEVEL - 2} "
                '(spec/hashlife.md "Depth")'
            )
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
        cells = np.asarray(cells)
        if cells.ndim != 2 or 0 in cells.shape:
            raise ValueError(f"cells must be a non-empty 2-D array, got shape {cells.shape}")
        height, width = cells.shape
        check_box(x, y, x + width - 1, y + height - 1)
        rect = (x, y - 1, x + width - 1, y + height - 2)
        self._paste_blocks(array_blocks(cells, x, y - 1), rect, mode)

    def clear_rect(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """Every cell of the inclusive rectangle dies."""
        check_box(x0, y0, x1, y1)
        if x1 < x0 or y1 < y0:
            return
        origin = -(1 << (self._level - 1))
        rect = (x0, y0 - 1, x1, y1 - 1)
        self._root = self._clear(self._root, self._level, origin, origin, rect)

    def fill_random(self, x0: int, y0: int, x1: int, y1: int, density: float, seed: int) -> None:
        """Replace the inclusive rectangle with lifelike's PCG32 soup of the same size."""
        check_box(x0, y0, x1, y1)
        if x1 < x0 or y1 < y0:
            raise ValueError(f"empty rectangle ({x0}, {y0})..({x1}, {y1})")
        cells = soup((x1 - x0 + 1, y1 - y0 + 1), density=density, seed=seed)
        self.set_rect(x0, y0, cells, "copy")

    def clear(self) -> None:
        self._level = _MIN_LEVEL
        self._root = self._store.empty(_MIN_LEVEL)

    # -- snapshots ----------------------------------------------------------------------

    def snapshot(self) -> Snapshot:
        snap = Snapshot(self, self._root, self._level, self._generation)
        self._snapshots.add(snap)
        return snap

    def restore(self, snapshot: Snapshot) -> None:
        if snapshot._owner() is not self:
            raise ValueError("snapshot belongs to another universe")
        self._root = snapshot._root
        self._level = snapshot._level
        self._generation = snapshot._generation

    # -- frames -----------------------------------------------------------------------------

    def render(
        self, view: LifeView, size: tuple[int, int], mode: RenderMode = "any"
    ) -> NDArray[np.uint8]:
        """The (height, width) uint8 frame of ``view``: 0/255, or block density zoomed out."""
        return render_frame(self, view, size, mode)

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
        """Macrocell text or bytes (gzip-compressed bytes too), placed as Golly places it."""
        from heaton_life.ca.hashlife.macrocell import read_macrocell

        return read_macrocell(source, max_memory_mb=max_memory_mb)

    @classmethod
    def from_file(cls, path: str | Path, *, max_memory_mb: int = DEFAULT_MEMORY_MB) -> HashLife:
        """A ``.rle``, ``.mc``, or ``.mc.gz`` file, recognized by its content."""
        raw = Path(path).read_bytes()
        if raw[:2] == b"\x1f\x8b" or raw.lstrip()[:4] == b"[M2]":
            return cls.from_macrocell(raw, max_memory_mb=max_memory_mb)
        return cls.from_rle(raw.decode("latin-1"), max_memory_mb=max_memory_mb)

    def to_rle(self) -> str:
        """RLE of the bounding box behind a ``#CXRLE`` line; inside the editing box only."""
        from heaton_life.ca.hashlife.rle import write_rle

        return write_rle(self)

    def to_macrocell(self) -> str:
        """The canonical Macrocell text: the whole state, any size, in one string."""
        from heaton_life.ca.hashlife.macrocell import write_macrocell

        return write_macrocell(self)

    def save(self, path: str | Path) -> None:
        """Write by extension: ``.rle``, ``.mc``, or ``.mc.gz``."""
        target = Path(path)
        name = target.name.lower()
        if name.endswith(".mc.gz"):
            import gzip

            target.write_bytes(gzip.compress(self.to_macrocell().encode("ascii"), mtime=0))
        elif name.endswith(".mc"):
            target.write_text(self.to_macrocell(), encoding="ascii", newline="\n")
        elif name.endswith(".rle"):
            target.write_text(self.to_rle(), encoding="ascii", newline="\n")
        else:
            raise ValueError(f"unknown pattern extension for {target.name!r} (.rle, .mc, .mc.gz)")

    # -- tree walks (tree coordinates: y one less than the cell's) -------------------------

    def _adopt(self, root: int, level: int, generation: int) -> None:
        self._root, self._level, self._generation = root, level, generation

    def _minimal(self) -> tuple[int, int]:
        """The smallest centered root (level ≥ 3) that holds every live cell."""
        store = self._store
        data = store.data
        n, k = self._root, self._level
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
            else:
                new = old ^ src
            return store.leaf(new)
        tier = tiers.get(k)  # None at the root, which is centered, not aligned
        if tier is not None and (nx >> k, ny >> k) not in tier:  # no source cells below
            return self._clear(n, k, nx, ny, rect) if mode == "copy" else n
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
        near, far, lowest = _EDGES[which]
        store = self._store
        data = store.data
        memo: dict[int, int] = {}

        def walk(n: int, k: int) -> int:
            # Plain loops, not comprehensions: one frame per level (spec/hashlife.md "Depth").
            hit = memo.get(n)
            if hit is not None:
                return hit
            if k == 3:
                b = data[n]
                if which in ("min_x", "max_x"):
                    cols = columns(b)
                    r = (cols & -cols).bit_length() - 1 if lowest else cols.bit_length() - 1
                else:
                    r = ((b & -b).bit_length() - 1 if lowest else b.bit_length() - 1) >> 3
                memo[n] = r
                return r
            kids = data[n]
            e = store.empty(k - 1)
            half = 1 << (k - 1)
            side, offset = near, 0 if lowest else half
            if all(kids[i] == e for i in near):
                side, offset = far, half if lowest else 0
            found = []
            for i in side:
                if kids[i] != e:
                    found.append(walk(kids[i], k - 1))
            r = (min(found) if lowest else max(found)) + offset
            memo[n] = r
            return r

        return walk(self._root, self._level)
