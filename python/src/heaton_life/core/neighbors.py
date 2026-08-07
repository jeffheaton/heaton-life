"""Moore-neighborhood sums with the spec's boundary modes."""

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
