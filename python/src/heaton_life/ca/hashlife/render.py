"""Frames of the unbounded plane (spec/hashlife.md "View and render").

A frame is one byte per pixel. Zoomed out, a pixel is an aligned level-s quadtree node
(s = −mag): ``any`` lights it 255 when the block holds a live cell, ``density`` gives
⌈255 · population / 4^s⌉. At ``mag ≥ 0`` each cell is a 2^mag-pixel square of 0 or 255.
The walk stops at level s + 3, where each node's 8×8 tile of pixels is cached, so a frame
costs O(pixels) whatever the population or the zoom.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import numpy as np
from numpy.typing import NDArray

from heaton_life.ca.hashlife.leaves import leaf_cells
from heaton_life.ca.hashlife.store import NodeStore
from heaton_life.ca.hashlife.view import LifeView

if TYPE_CHECKING:
    from heaton_life.ca.hashlife.universe import HashLife

RenderMode = Literal["any", "density"]
RENDER_MODES: tuple[RenderMode, ...] = ("any", "density")
TILE_CACHE_LIMIT = 50_000  # tiles kept per universe before the cache starts over


def render(
    universe: HashLife, view: LifeView, size: tuple[int, int], mode: RenderMode = "any"
) -> NDArray[np.uint8]:
    """The (height, width) uint8 frame of ``view``."""
    width, height = size
    if width <= 0 or height <= 0:
        raise ValueError(f"frame size must be positive, got {size}")
    if mode not in RENDER_MODES:
        raise ValueError(f"unknown render mode {mode!r}; expected one of {RENDER_MODES}")
    if view.mag <= 0:
        return _blocks(universe, view.x, view.y, width, height, -view.mag, mode)
    p = view.mag
    cx0, cy0 = view.x >> p, view.y >> p
    cx1, cy1 = (view.x + width - 1) >> p, (view.y + height - 1) >> p
    cells = _blocks(universe, cx0, cy0, cx1 - cx0 + 1, cy1 - cy0 + 1, 0, mode)
    big = cells.repeat(1 << p, axis=0).repeat(1 << p, axis=1)
    ox, oy = view.x - (cx0 << p), view.y - (cy0 << p)
    return np.ascontiguousarray(big[oy : oy + height, ox : ox + width])


def _blocks(
    universe: HashLife, bx0: int, by0: int, w: int, h: int, s: int, mode: RenderMode
) -> NDArray[np.uint8]:
    """Level-s block values for blocks bx0..bx0+w−1 × by0..by0+h−1 (block b covers tree
    cells [b·2^s, (b+1)·2^s))."""
    out = np.zeros((h, w), np.uint8)
    store = universe._store
    t = s + 3  # tile level: 8×8 blocks
    root, k = universe._root, universe._level
    if s >= k - 1:  # each of the root's quarters lies inside one block: no tree to build
        return _quarters(universe, out, bx0, by0, s, mode)
    while k <= t:  # tiles must be proper, aligned descendants of the (centered) root
        e = store.empty(k - 1)
        a, b, c, d = store.data[root]
        j = store.join
        root = j(j(e, e, e, a), j(e, e, b, e), j(e, c, e, e), j(d, e, e, e))
        k += 1
    tiles = universe._tile_cache(s, mode)
    x_lo, x_hi = bx0 << s, (bx0 + w) << s
    y_lo, y_hi = by0 << s, (by0 + h) << s
    origin = -(1 << (k - 1))
    stack = [(root, k, origin, origin)]
    while stack:
        n, lvl, nx, ny = stack.pop()
        span = 1 << lvl
        if nx >= x_hi or nx + span <= x_lo or ny >= y_hi or ny + span <= y_lo:
            continue
        if n == store.empty(lvl):
            continue
        if lvl == t:
            tile = tiles.get(n)
            if tile is None:
                tile = _tile(store, n, t, s, mode)
                tiles[n] = tile
            tbx, tby = nx >> s, ny >> s
            c0, c1 = max(tbx, bx0), min(tbx + 8, bx0 + w)
            r0, r1 = max(tby, by0), min(tby + 8, by0 + h)
            out[r0 - by0 : r1 - by0, c0 - bx0 : c1 - bx0] = tile[
                r0 - tby : r1 - tby, c0 - tbx : c1 - tbx
            ]
            continue
        half = span >> 1
        a, b, c, d = store.data[n]
        lvl -= 1
        stack += ((a, lvl, nx, ny), (b, lvl, nx + half, ny), (c, lvl, nx, ny + half))
        stack.append((d, lvl, nx + half, ny + half))
    return out


def _quarters(
    universe: HashLife, out: NDArray[np.uint8], bx0: int, by0: int, s: int, mode: RenderMode
) -> NDArray[np.uint8]:
    """Blocks of level s ≥ k − 1 around a level-k root: its NW, NE, SW, and SE quarters
    fill blocks (−1, −1), (0, −1), (−1, 0), and (0, 0), and every other block is empty.
    Frames this far out cost O(1) however distant, with no tree built past the root."""
    store = universe._store
    h, w = out.shape
    for q, child in enumerate(store.data[universe._root]):
        pop = store.population(child, universe._level - 1)
        col, row = (q & 1) - 1 - bx0, (q >> 1) - 1 - by0
        if pop and 0 <= col < w and 0 <= row < h:
            out[row, col] = 255 if mode == "any" else (255 * pop + (1 << 2 * s) - 1) >> (2 * s)
    return out


def _tile(store: NodeStore, n: int, t: int, s: int, mode: RenderMode) -> NDArray[np.uint8]:
    """The 8×8 pixels of a level-t node, each a level-s block (t = s + 3)."""
    if s < 3:  # blocks inside leaves: assemble the cells, then pool
        f = 1 << s
        pooled = _cells(store, n, t).reshape(8, f, 8, f)
        if mode == "any":
            return pooled.max(axis=(1, 3)) * np.uint8(255)
        counts = pooled.sum(axis=(1, 3), dtype=np.int64)
        return ((255 * counts + f * f - 1) // (f * f)).astype(np.uint8)
    grid = [[n]]
    for _ in range(3):
        grid = [
            [store.data[m][q] for m in row for q in (top, top + 1)]
            for row in grid
            for top in (0, 2)
        ]
    tile = np.zeros((8, 8), np.uint8)
    empty = store.empty(s)
    area_bits = 2 * s
    for r, row in enumerate(grid):
        for c, m in enumerate(row):
            if m == empty:
                continue
            if mode == "any":
                tile[r, c] = 255
            else:
                pop = store.population(m, s)
                tile[r, c] = (255 * pop + (1 << area_bits) - 1) >> area_bits
    return tile


def _cells(store: NodeStore, n: int, k: int) -> NDArray[np.uint8]:
    if k == 3:
        return leaf_cells(store.data[n])
    a, b, c, d = store.data[n]
    k -= 1
    return np.block(
        [[_cells(store, a, k), _cells(store, b, k)], [_cells(store, c, k), _cells(store, d, k)]]
    )
