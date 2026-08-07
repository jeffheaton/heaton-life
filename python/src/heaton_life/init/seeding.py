"""Seeded initial states.

Every strategy consumes exactly ``width * height`` PCG32 draws in row-major order
regardless of masks, so implementations in any language agree bit-for-bit.
A cell is alive when ``draw < floor(density * 2**32)``.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from heaton_life.core.rng import Pcg32


def _draws(size: tuple[int, int], seed: int) -> NDArray[np.uint32]:
    width, height = size
    return Pcg32(seed).fill_u32(width * height).reshape(height, width)


def _threshold(density: float) -> int:
    if not 0.0 <= density <= 1.0:
        raise ValueError(f"density must be in [0, 1], got {density}")
    return int(density * 4294967296.0)


def soup(size: tuple[int, int], *, density: float = 0.35, seed: int = 0) -> NDArray[np.uint8]:
    """Uniform random fill: alive with probability ``density``."""
    alive = _draws(size, seed) < _threshold(density)
    return alive.astype(np.uint8)


def blob(
    size: tuple[int, int], *, density: float = 0.5, radius: float = 0.25, seed: int = 0
) -> NDArray[np.uint8]:
    """Soup restricted to a centered disk; ``radius`` is a fraction of min(width, height)."""
    width, height = size
    alive = _draws(size, seed) < _threshold(density)
    yy, xx = np.mgrid[0:height, 0:width]
    r = radius * min(width, height)
    inside = np.asarray((xx - width // 2) ** 2 + (yy - height // 2) ** 2 <= r * r)
    result: NDArray[np.uint8] = (alive & inside).astype(np.uint8)
    return result


def single(size: tuple[int, int]) -> NDArray[np.uint8]:
    """A single live cell at (width // 2, height // 2). Consumes no RNG draws."""
    width, height = size
    grid = np.zeros((height, width), dtype=np.uint8)
    grid[height // 2, width // 2] = 1
    return grid
