"""Frames of the unbounded multi-state plane (spec/hashlife-multistate.md "View and render").

A frame is one byte per pixel. In ``state`` mode a pixel is a state: at ``mag ≥ 0`` the
cell's own, repeated over its 2^mag square; zoomed out, an aligned level-s node's shown
state (s = −mag), its non-zero state that comes first in the universe's zoom order. In
``density`` mode a pixel is ⌈255 · p / 4^s⌉ for a block of p non-zero cells, as in the
two-state frames. The walk stops at level s + 3, where each node's 8 × 8 tile of pixels is
cached, so a frame costs O(pixels) whatever the population or the zoom.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

from heaton_life.ca.hashlife.multistate.store import unpack
from heaton_life.ca.hashlife.view import LifeView

if TYPE_CHECKING:
    from heaton_life.ca.hashlife.multistate.universe import MultiStateHashLife, StateRenderMode


def render(
    universe: MultiStateHashLife, view: LifeView, size: tuple[int, int], mode: StateRenderMode
) -> NDArray[np.uint8]:
    """The (height, width) uint8 frame of ``view``."""
    from heaton_life.ca.hashlife.multistate.universe import STATE_RENDER_MODES

    width, height = size
    if width <= 0 or height <= 0:
        raise ValueError(f"frame size must be positive, got {size}")
    if mode not in STATE_RENDER_MODES:
        raise ValueError(f"unknown render mode {mode!r}; expected one of {STATE_RENDER_MODES}")
    if view.mag <= 0:
        return _blocks(universe, view.x, view.y, width, height, -view.mag, mode)
    p = view.mag
    cx0, cy0 = view.x >> p, view.y >> p
    cx1, cy1 = (view.x + width - 1) >> p, (view.y + height - 1) >> p
    cells = _blocks(universe, cx0, cy0, cx1 - cx0 + 1, cy1 - cy0 + 1, 0, mode)
    big = cells.repeat(1 << p, axis=0).repeat(1 << p, axis=1)
    ox, oy = view.x - (cx0 << p), view.y - (cy0 << p)
    return np.ascontiguousarray(big[oy : oy + height, ox : ox + width])


def _value(universe: MultiStateHashLife, n: int, s: int, mode: StateRenderMode) -> int:
    """One pixel: level-s node n's shown state, or its density."""
    if mode == "state":
        return universe._shown_state(n, s)
    pop = universe._store.population(n, s)
    return (255 * pop + (1 << 2 * s) - 1) >> (2 * s)


def _blocks(
    universe: MultiStateHashLife, bx0: int, by0: int, w: int, h: int, s: int, mode: StateRenderMode
) -> NDArray[np.uint8]:
    """Level-s block values for blocks bx0..bx0+w−1 × by0..by0+h−1 (block b covers tree
    cells [b·2^s, (b+1)·2^s)); level 0 is a cell."""
    out = np.zeros((h, w), np.uint8)
    store = universe._store
    t = s + 3  # tile level: 8×8 blocks
    root, k = universe._root, universe._level
    if s >= k - 1:  # each of the root's quarters lies inside one block: no tree to build
        return _quarters(universe, out, bx0, by0, s, mode)
    while k <= t:  # tiles must be proper, aligned descendants of the (centered) root
        root = universe._grow(root, k)
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
                tile = _tile(universe, n, t, s, mode)
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
    universe: MultiStateHashLife,
    out: NDArray[np.uint8],
    bx0: int,
    by0: int,
    s: int,
    mode: StateRenderMode,
) -> NDArray[np.uint8]:
    """Blocks of level s ≥ k − 1 around a level-k root: its NW, NE, SW, and SE quarters
    fill blocks (−1, −1), (0, −1), (−1, 0), and (0, 0), and every other block is empty."""
    store = universe._store
    h, w = out.shape
    k = universe._level
    for q, child in enumerate(store.data[universe._root]):
        col, row = (q & 1) - 1 - bx0, (q >> 1) - 1 - by0
        if 0 <= col < w and 0 <= row < h and child != store.empty(k - 1):
            if mode == "state":
                out[row, col] = universe._shown_state(child, k - 1)
            else:
                pop = store.population(child, k - 1)
                out[row, col] = (255 * pop + (1 << 2 * s) - 1) >> (2 * s)
    return out


def _tile(
    universe: MultiStateHashLife, n: int, t: int, s: int, mode: StateRenderMode
) -> NDArray[np.uint8]:
    """The 8×8 pixels of a level-t node, each a level-s block (t = s + 3)."""
    store = universe._store
    if s == 0:
        cells = _cells(universe, n, t)
        return cells if mode == "state" else (cells != 0).astype(np.uint8) * np.uint8(255)
    grid = [[n]]
    for _ in range(3):
        grid = [
            [store.data[m][q] for m in row for q in (top, top + 1)]
            for row in grid
            for top in (0, 2)
        ]
    tile = np.zeros((8, 8), np.uint8)
    empty = store.empty(s)
    for r, row in enumerate(grid):
        for c, m in enumerate(row):
            if m != empty:
                tile[r, c] = _value(universe, m, s, mode)
    return tile


def _cells(universe: MultiStateHashLife, n: int, k: int) -> NDArray[np.uint8]:
    """A level-k node's states as a 2^k × 2^k array."""
    store = universe._store
    if k == 1:
        nw, ne, sw, se = unpack(store.data[n])
        return np.array([[nw, ne], [sw, se]], np.uint8)
    if n == store.empty(k):
        return np.zeros((1 << k, 1 << k), np.uint8)
    a, b, c, d = store.data[n]
    k -= 1
    return np.block(
        [
            [_cells(universe, a, k), _cells(universe, b, k)],
            [_cells(universe, c, k), _cells(universe, d, k)],
        ]
    )
