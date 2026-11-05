"""The board: a 6×6 grid of OTCA metapixels running Life inside Life, written as Macrocell.

The inner world holds a NW glider with its first phase in columns/rows 2..4. It stays exact
Life through inner generation 8 (when it reaches row/column 0), and the one-cell margin on
the SE side catches every signal its live metapixels send their neighbors.

Usage: python board.py [--tiles out/tiles.npz] [--out out/board.mc]
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from heaton_life.ca.hashlife import HashLife

OUT = Path(__file__).resolve().parent / "out"
PITCH = 2048  # cells from one metapixel to the next
SIZE = 6  # the inner world is SIZE × SIZE metapixels
PERIOD = 35328  # outer generations per inner generation
TILE = 2058  # a tile's cells span −5..2052 on each axis, overlapping its neighbors
GLIDER_NW = ("ooo", "o..", ".o.")
GLIDER_AT = (2, 2)  # top-left inner cell of the glider's 3×3 box


def inner_cells() -> NDArray[np.uint8]:
    """The inner world at generation 0: rows are y, columns x."""
    grid = np.zeros((SIZE, SIZE), dtype=np.uint8)
    gx, gy = GLIDER_AT
    for r, row in enumerate(GLIDER_NW):
        for c, ch in enumerate(row):
            if ch == "o":
                grid[gy + r, gx + c] = 1
    return grid


def life_step(grid: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """One generation of B3/S23 on a finite grid whose outside is dead."""
    h, w = grid.shape
    p = np.pad(grid, 1).astype(np.int16)
    n = np.zeros((h, w), dtype=np.int16)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                n += p[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]
    out: NDArray[np.uint8] = ((n == 3) | ((grid == 1) & (n == 2))).astype(np.uint8)
    return out


def tile_array(cells: NDArray[np.int32]) -> NDArray[np.uint8]:
    """Tile cells (x, y from −5) as a TILE × TILE array whose [0, 0] is cell (−5, −5)."""
    a = np.zeros((TILE, TILE), dtype=np.uint8)
    a[cells[:, 1] + 5, cells[:, 0] + 5] = 1
    return a


def build(tiles: Path) -> HashLife:
    """Metapixel (i, j) has its own origin at cell (2048 i, 2048 j)."""
    with np.load(tiles) as t:
        off, on = tile_array(t["off"]), tile_array(t["on"])
    inner = inner_cells()
    u = HashLife("B3/S23", max_memory_mb=8000)
    for j in range(SIZE):
        for i in range(SIZE):
            u.set_rect(PITCH * i - 5, PITCH * j - 5, on if inner[j, i] else off, mode="or")
    return u


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tiles", type=Path, default=OUT / "tiles.npz")
    ap.add_argument("--out", type=Path, default=OUT / "board.mc")
    args = ap.parse_args()
    t0 = time.perf_counter()
    u = build(args.tiles)
    args.out.write_text(u.to_macrocell())
    print(
        f"board: {u.population:,} cells in {u.bounding_box()}, "
        f"{time.perf_counter() - t0:.1f} s → {args.out}"
    )


if __name__ == "__main__":
    main()
