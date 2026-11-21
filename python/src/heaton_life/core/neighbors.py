"""Moore-neighborhood sums and indices with the spec's boundary modes."""

from __future__ import annotations

from typing import Literal

import numpy as np
from numpy.typing import NDArray

Boundary = Literal["torus", "dead"]

_OFFSETS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


def moore_sum(grid: NDArray[np.uint8], boundary: Boundary = "torus") -> NDArray[np.uint8]:
    """Sum of the 8 Moore neighbors for every cell (values must be small: max sum 8*255... practically 0/1 grids)."""
    if boundary == "torus":
        acc = np.zeros_like(grid)
        for dy, dx in _OFFSETS:
            acc += np.roll(grid, (dy, dx), axis=(0, 1))
        return acc
    if boundary == "dead":
        h, w = grid.shape
        padded = np.zeros((h + 2, w + 2), dtype=grid.dtype)
        padded[1:-1, 1:-1] = grid
        acc = np.zeros_like(grid)
        for dy, dx in _OFFSETS:
            acc += padded[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]
        return acc
    raise ValueError(f"unknown boundary mode: {boundary!r} (expected 'torus' or 'dead')")


def moore_index(grid: NDArray[np.uint8], boundary: Boundary = "torus") -> NDArray[np.uint16]:
    """The neighborhood index of every cell of a 0/1 grid (spec/rules.md "The transition
    table"): the weights of the live cells in its 3×3 block, NW 256, N 128, NE 64, W 32,
    the cell itself 16, E 8, SW 4, S 2, SE 1. A rule's table maps it to the next state."""
    cells = grid.astype(np.uint16)
    acc = np.zeros(grid.shape, dtype=np.uint16)
    if boundary == "torus":
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                # np.roll by (-dy, -dx) puts the cell at offset (dx, dy) under each cell.
                acc |= np.roll(cells, (-dy, -dx), axis=(0, 1)) << (4 - 3 * dy - dx)
        return acc
    if boundary == "dead":
        h, w = grid.shape
        padded = np.zeros((h + 2, w + 2), dtype=np.uint16)
        padded[1:-1, 1:-1] = cells
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                acc |= padded[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w] << (4 - 3 * dy - dx)
        return acc
    raise ValueError(f"unknown boundary mode: {boundary!r} (expected 'torus' or 'dead')")
