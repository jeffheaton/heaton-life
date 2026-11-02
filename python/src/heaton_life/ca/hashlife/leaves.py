"""Leaf-level bit machinery for HashLife (spec/hashlife.md "Quadtree").

A leaf is an 8×8 bitmap in one Python int: cell (x, y) of the leaf is bit ``y * 8 + x``
(row-major, origin top-left, y down). Smaller squares keep the same 8-wide row stride
("spread" form): a 4×4 square occupies bits ``y * 8 + x`` for x, y < 4, so four of them
compose into a leaf with three shifts. The rule enters only through the 65,536-entry base
case, a 4×4 square to its center 2×2 one generation later.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

MASK64 = (1 << 64) - 1
LEFT4 = 0x0F0F0F0F0F0F0F0F  # columns 0-3 of every row
RIGHT4 = 0xF0F0F0F0F0F0F0F0  # columns 4-7 of every row
SQUARE4 = 0x0F0F0F0F  # a 4×4 square in spread form
_REPEAT_ROWS = 0x0101010101010101


def rule_table(birth: frozenset[int], survive: frozenset[int]) -> tuple[int, ...]:
    """The base case: a 4×4 square indexed compactly (bit ``y * 4 + x``) to its center
    2×2 one generation later, in spread form (bits 0, 1, 8, 9)."""
    index = np.arange(1 << 16, dtype=np.uint32)
    born = np.zeros(9, dtype=np.uint32)
    born[sorted(birth)] = 1
    stays = np.zeros(9, dtype=np.uint32)
    stays[sorted(survive)] = 1
    out = np.zeros(1 << 16, dtype=np.uint32)
    for cx, cy, bit in ((1, 1, 0), (2, 1, 1), (1, 2, 8), (2, 2, 9)):
        count = np.zeros(1 << 16, dtype=np.uint32)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx or dy:
                    count += (index >> ((cy + dy) * 4 + cx + dx)) & 1
        alive = (index >> (cy * 4 + cx)) & 1
        out |= np.where(alive == 1, stays[count], born[count]) << bit
    return tuple(out.tolist())


def _window(b: int) -> int:
    """The 4×4 square at bit 0 of a spread bitmap, as a compact 16-bit table index."""
    return (b & 0xF) | ((b >> 4) & 0xF0) | ((b >> 8) & 0xF00) | ((b >> 12) & 0xF000)


def advance1(b: int, t: Sequence[int]) -> int:
    """A leaf's center 4×4 one generation on (spread form)."""
    return (
        t[_window(b >> 9)]
        | t[_window(b >> 11)] << 2
        | t[_window(b >> 25)] << 16
        | t[_window(b >> 27)] << 18
    )


def advance2(b: int, t: Sequence[int]) -> int:
    """A leaf's center 4×4 two generations on (spread form).

    Nine windows at even offsets give the 6×6 at cells 1..6 after one generation (each
    window's 2×2 lands at its own offset + 9); four windows of that give the center.
    """
    g = (
        t[_window(b)] << 9
        | t[_window(b >> 2)] << 11
        | t[_window(b >> 4)] << 13
        | t[_window(b >> 16)] << 25
        | t[_window(b >> 18)] << 27
        | t[_window(b >> 20)] << 29
        | t[_window(b >> 32)] << 41
        | t[_window(b >> 34)] << 43
        | t[_window(b >> 36)] << 45
    )
    return (
        t[_window(g >> 9)]
        | t[_window(g >> 11)] << 2
        | t[_window(g >> 25)] << 16
        | t[_window(g >> 27)] << 18
    )


def center(b: int) -> int:
    """A leaf's center 4×4 with no time advance (spread form)."""
    return (b >> 18) & SQUARE4


def compose(nw: int, ne: int, sw: int, se: int) -> int:
    """Four 4×4 squares (spread form) into one leaf."""
    return nw | ne << 4 | sw << 32 | se << 36


def beside(w: int, e: int) -> int:
    """The leaf straddling two side-by-side leaves: w's right half, then e's left half."""
    return ((w >> 4) & LEFT4) | ((e << 4) & RIGHT4)


def above(n: int, s: int) -> int:
    """The leaf straddling two stacked leaves: n's bottom half over s's top half."""
    return (n >> 32) | ((s << 32) & MASK64)


def inner(nw: int, ne: int, sw: int, se: int) -> int:
    """The leaf at the center of four leaves (a level-4 node's center, no time)."""
    return compose((nw >> 36) & SQUARE4, (ne >> 32) & SQUARE4, (sw >> 4) & SQUARE4, se & SQUARE4)


def rect_mask(c0: int, c1: int, r0: int, r1: int) -> int:
    """Columns c0..c1 and rows r0..r1 of a leaf, inclusive, all within 0..7."""
    row = ((1 << (c1 - c0 + 1)) - 1) << c0
    return (row * _REPEAT_ROWS) & (((1 << ((r1 - r0 + 1) * 8)) - 1) << (8 * r0))


def columns(b: int) -> int:
    """The 8-bit OR of a leaf's rows: bit x is set when column x holds a live cell."""
    b |= b >> 32
    b |= b >> 16
    b |= b >> 8
    return b & 0xFF


def leaf_cells(b: int) -> NDArray[np.uint8]:
    """A leaf as an 8×8 uint8 array of 0/1."""
    raw = np.frombuffer(b.to_bytes(8, "little"), dtype=np.uint8)
    return np.unpackbits(raw, bitorder="little").reshape(8, 8)


def array_blocks(cells: NDArray[np.generic], tx: int, ty: int) -> dict[tuple[int, int], int]:
    """The non-empty leaves of an array placed with its top-left cell at tree position
    (tx, ty): ``{(bx, by): bitmap}``, where leaf (bx, by) covers tree positions
    [8·bx, 8·bx + 8) × [8·by, 8·by + 8)."""
    height, width = cells.shape
    bx0, by0 = tx >> 3, ty >> 3
    ox, oy = tx - (bx0 << 3), ty - (by0 << 3)
    grid = np.zeros((((oy + height + 7) >> 3) << 3, ((ox + width + 7) >> 3) << 3), np.uint8)
    grid[oy : oy + height, ox : ox + width] = np.asarray(cells) != 0
    rows, cols = grid.shape[0] >> 3, grid.shape[1] >> 3
    tiles = grid.reshape(rows, 8, cols, 8).transpose(0, 2, 1, 3)
    words = np.packbits(tiles, axis=-1, bitorder="little").reshape(rows, cols, 8)
    bitmaps = np.ascontiguousarray(words).view("<u8").reshape(rows, cols)
    return {
        (bx0 + int(c), by0 + int(r)): int(bitmaps[r, c])
        for r, c in zip(*np.nonzero(bitmaps), strict=True)
    }
