"""Moore-neighborhood sums and indices, read through a grid's halo (spec/topology.md)."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from heaton_life.core.topology import Boundary, Halo, Topology

_OFFSETS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


def _halo(grid: NDArray[np.uint8], boundary: Boundary | Topology, halo: Halo | None) -> Halo:
    height, width = grid.shape
    if halo is None:
        topology = boundary if isinstance(boundary, Topology) else Topology(boundary)
        return Halo(topology, width, height)
    if (halo.width, halo.height, halo.radius) != (width, height, 1):
        raise ValueError(f"a halo of radius 1 around {width} x {height} cells is needed")
    return halo


def moore_sum(
    grid: NDArray[np.uint8], boundary: Boundary | Topology = "torus", *, halo: Halo | None = None
) -> NDArray[np.uint8]:
    """Sum of the 8 Moore neighbors of every cell (for 0/1 grids: a sum of bytes), the
    cells past the edges as the topology puts them, 0 past a dead edge. ``halo`` (radius 1,
    the grid's size) stands in for ``boundary`` and saves building one."""
    h, w = grid.shape
    padded = _halo(grid, boundary, halo).fill(grid)
    acc = np.zeros_like(grid)
    for dy, dx in _OFFSETS:
        acc += padded[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]
    return acc


def moore_index(
    grid: NDArray[np.uint8], boundary: Boundary | Topology = "torus", *, halo: Halo | None = None
) -> NDArray[np.uint16]:
    """The neighborhood index of every cell of a 0/1 grid (spec/rules.md "The transition
    table"): the weights of the live cells in its 3×3 block, NW 256, N 128, NE 64, W 32,
    the cell itself 16, E 8, SW 4, S 2, SE 1, the block read from the grid's halo
    (spec/topology.md). A rule's table maps it to the next state."""
    h, w = grid.shape
    padded = _halo(grid, boundary, halo).fill(grid, dtype=np.uint16)
    acc = np.zeros(grid.shape, dtype=np.uint16)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            acc |= padded[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w] << (4 - 3 * dy - dx)
    return acc
