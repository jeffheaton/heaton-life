"""Pattern operations — spec/patterns.md.

Patterns are rectangular cell regions in a family's payload: 2-D grids for the
byte families and Lenia, trailing-channel 3-D for MergeLife (h, w, 3) and
Gray-Scott (h, w, 2). Transforms act on axes (0, 1), so every layout shares one
implementation. Extract/stamp take the target's boundary mode: torus wraps,
dead boundaries read 0 / clip.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

CellArray = NDArray[Any]


def rotate90(pattern: CellArray) -> CellArray:
    """Clockwise quarter turn: result[y][x] = pattern[h-1-x][y]."""
    return np.ascontiguousarray(np.rot90(pattern, k=-1, axes=(0, 1)))


def flip_h(pattern: CellArray) -> CellArray:
    """Mirror left-right."""
    return np.ascontiguousarray(pattern[:, ::-1])


def flip_v(pattern: CellArray) -> CellArray:
    """Mirror top-bottom."""
    return np.ascontiguousarray(pattern[::-1, :])


def extract(grid: CellArray, x: int, y: int, width: int, height: int, *, torus: bool) -> CellArray:
    """Copy a (height, width) region with top-left (x, y) out of the grid.

    Torus targets wrap; dead-boundary targets read 0 outside the grid.
    """
    if width < 1 or height < 1:
        raise ValueError("extract region must be at least 1x1")
    grid_h, grid_w = grid.shape[0], grid.shape[1]
    shape = (height, width) + grid.shape[2:]
    out = np.zeros(shape, dtype=grid.dtype)
    for row in range(height):
        for col in range(width):
            src_y = y + row
            src_x = x + col
            if torus:
                out[row, col] = grid[src_y % grid_h, src_x % grid_w]
            elif 0 <= src_y < grid_h and 0 <= src_x < grid_w:
                out[row, col] = grid[src_y, src_x]
    return out


def stamp(
    grid: CellArray,
    pattern: CellArray,
    x: int,
    y: int,
    *,
    torus: bool,
    transparent: bool = False,
) -> None:
    """Write the pattern into the grid at top-left (x, y), in place.

    Torus targets wrap; dead-boundary targets clip out-of-range cells. With
    ``transparent``, cells equal to 0 are skipped (2-D payloads only — the
    opaque-only families reject the flag, per spec).
    """
    if transparent and pattern.ndim != 2:
        raise ValueError("transparent stamping is defined for 2-D cell payloads only")
    grid_h, grid_w = grid.shape[0], grid.shape[1]
    pat_h, pat_w = pattern.shape[0], pattern.shape[1]
    for row in range(pat_h):
        for col in range(pat_w):
            if transparent and pattern[row, col] == 0:
                continue
            dst_y = y + row
            dst_x = x + col
            if torus:
                grid[dst_y % grid_h, dst_x % grid_w] = pattern[row, col]
            elif 0 <= dst_y < grid_h and 0 <= dst_x < grid_w:
                grid[dst_y, dst_x] = pattern[row, col]


def clear(
    grid: NDArray[Any], x0: int, y0: int, x1: int, y1: int, blank: Any
) -> None:
    """spec/patterns.md "Clear": restore an inclusive rectangle to the family blank.

    ``grid`` is indexed ``[y, x]`` with any trailing channel axis, and ``blank`` is
    broadcast into the region, so it may be a scalar (0, 0.0) or a per-channel
    sequence. The blank is a family fact, not an app choice — Gray-Scott's is the
    substrate (U = 1, V = 0), not zero — so callers are the family classes'
    ``clear_rect`` methods rather than app code. Clearing does not touch the
    generation, exactly like stamping.
    """
    height, width = grid.shape[0], grid.shape[1]
    if x0 > x1 or y0 > y1:
        raise ValueError(f"clear region is empty: ({x0}, {y0})..({x1}, {y1})")
    if x0 < 0 or y0 < 0 or x1 >= width or y1 >= height:
        raise ValueError(
            f"clear region ({x0}, {y0})..({x1}, {y1}) is outside {width}x{height}"
        )
    grid[y0 : y1 + 1, x0 : x1 + 1] = blank


def compatible(pattern_family: str, target_family: str, pattern: CellArray,
               target_states: int | None = None) -> str | None:
    """Spec compatibility check: the rejection reason, or None when stampable.

    Patterns are family-bound (a glider cannot enter Wireworld); cyclic
    additionally requires every cell below the target's state count.
    """
    if pattern_family != target_family:
        return f"{pattern_family!r} patterns cannot be stamped into {target_family!r}"
    if target_family == "cyclic" and target_states is not None:
        top = int(pattern.max(initial=0))
        if top >= target_states:
            return f"pattern uses state {top}, target has only {target_states} states"
    return None
