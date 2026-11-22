"""Sampling a window of a grid (spec/render.md "Sampling a window of a grid").

A grid world too big to show whole is shown a window at a time, with fewer pixels than
cells. ``sample_window`` reads a window of a byte grid (a world's states, or a frame) and
gives each output pixel the value of its nearest cell, the state its cells show first by
a zoom order (so a lone live cell never vanishes), or their density.
"""

from __future__ import annotations

import operator
from collections.abc import Iterable
from typing import Literal, get_args

import numpy as np
from numpy.typing import NDArray

WindowMode = Literal["nearest", "state", "density"]
WINDOW_MODES: tuple[str, ...] = get_args(WindowMode)


def zoom_ranks(order: Iterable[int]) -> NDArray[np.uint8]:
    """Each byte value's place in a zoom order, lower shown first: the listed values in the
    list's order, then every other value from 1 to 255 in increasing order, and 0 last of
    all (255). A zoom order lists distinct values from 1 to 255."""
    listed = tuple(operator.index(v) for v in order)
    if any(not 1 <= v <= 255 for v in listed) or len(set(listed)) != len(listed):
        raise ValueError(f"a zoom order lists distinct states from 1 to 255, not {listed}")
    ranks = np.full(256, 255, dtype=np.uint8)
    place = 0
    for value in listed:
        ranks[value] = place
        place += 1
    seen = set(listed)
    for value in range(1, 256):
        if value not in seen:
            ranks[value] = place
            place += 1
    return ranks


def _bounds(cells: int, out: int) -> NDArray[np.int64]:
    """Where each pixel's cells start along one axis, and the window's end last: the cells
    whose centers lie in the pixel's share, ⌊(2iN + n − 1) / (2n)⌋."""
    i = np.arange(out + 1, dtype=np.int64)
    return (2 * i * cells + out - 1) // (2 * out)


def _nearest(cells: int, out: int) -> NDArray[np.int64]:
    """The cell under each pixel's center along one axis, ⌊(2i + 1) · N / (2n)⌋."""
    i = np.arange(out, dtype=np.int64)
    return ((2 * i + 1) * cells) // (2 * out)


def sample_window(
    cells: NDArray[np.uint8],
    x0: int,
    y0: int,
    width: int,
    height: int,
    out_width: int,
    out_height: int,
    *,
    mode: WindowMode = "state",
    order: Iterable[int] = (),
) -> NDArray[np.uint8]:
    """The window of ``width`` × ``height`` cells whose top-left cell is (x0, y0), sampled
    to ``out_height`` × ``out_width`` bytes (spec/render.md "Sampling a window of a grid").

    A pixel covers the cells whose centers lie in its share of the window, and its nearest
    cell is the one under its center (always one it covers). ``mode``:

    - ``"nearest"``: the nearest cell's value;
    - ``"state"``: of the non-zero values among its cells, the first in the zoom order
      ``order`` (listed values first, the rest increasing), else 0. In a two-state grid a
      pixel is live when any of its cells is;
    - ``"density"``: ⌈255 · p / n⌉ for n cells, p of them non-zero.

    The window lies inside the grid, with 1 <= out_width <= width and
    1 <= out_height <= height.
    """
    grid = np.asarray(cells)
    if grid.ndim != 2 or grid.dtype != np.uint8:
        raise ValueError(f"cells are a 2-D uint8 grid, not {grid.shape} {grid.dtype}")
    x0, y0 = operator.index(x0), operator.index(y0)
    width, height = operator.index(width), operator.index(height)
    out_width, out_height = operator.index(out_width), operator.index(out_height)
    grid_height, grid_width = grid.shape
    if not (0 <= x0 and 0 <= y0 and 1 <= width and 1 <= height):
        raise ValueError(f"a window is at least one cell, inside the grid: {width}x{height}")
    if x0 + width > grid_width or y0 + height > grid_height:
        raise ValueError(
            f"the window {width}x{height} at ({x0}, {y0}) leaves the "
            f"{grid_width}x{grid_height} grid"
        )
    if not (1 <= out_width <= width and 1 <= out_height <= height):
        raise ValueError(
            f"a {width}x{height} window samples to 1x1 up to {width}x{height} pixels, "
            f"not {out_width}x{out_height}"
        )
    if mode not in WINDOW_MODES:
        raise ValueError(f"mode must be one of {WINDOW_MODES}, not {mode!r}")
    ranks = zoom_ranks(order)
    if mode == "nearest":
        rows = y0 + _nearest(height, out_height)
        columns = x0 + _nearest(width, out_width)
        return np.ascontiguousarray(grid[np.ix_(rows, columns)])

    columns = _bounds(width, out_width)
    rows = _bounds(height, out_height)
    starts = columns[:-1]
    out = np.empty((out_height, out_width), dtype=np.uint8)
    if mode == "state":
        by_rank = np.zeros(256, dtype=np.uint8)
        by_rank[ranks[1:]] = np.arange(1, 256, dtype=np.uint8)
        by_rank[255] = 0
        for j in range(out_height):
            band = grid[y0 + rows[j] : y0 + rows[j + 1], x0 : x0 + width]
            least = np.minimum.reduceat(ranks[band], starts, axis=1).min(axis=0)
            out[j] = by_rank[least]
        return out
    across = (columns[1:] - columns[:-1]).astype(np.int64)
    for j in range(out_height):
        band = grid[y0 + rows[j] : y0 + rows[j + 1], x0 : x0 + width]
        live = np.add.reduceat((band != 0).astype(np.int64), starts, axis=1).sum(axis=0)
        n = across * int(rows[j + 1] - rows[j])
        out[j] = (255 * live + n - 1) // n
    return out
