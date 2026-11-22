"""Pattern operations — spec/patterns.md.

Patterns are rectangular cell regions in a family's payload: 2-D grids for the
byte families and Lenia, trailing-channel 3-D for MergeLife (h, w, 3) and
Gray-Scott (h, w, 2). Transforms act on axes (0, 1), so every layout shares one
implementation. Extract/stamp take the target's boundary mode: torus wraps,
dead boundaries read 0 / clip.
"""

from __future__ import annotations

import operator
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from heaton_life.init.seeding import soup

CellArray = NDArray[Any]
StampMode = Literal["copy", "or", "xor", "and"]
STAMP_MODES: tuple[StampMode, ...] = ("copy", "or", "xor", "and")


def rotate90(pattern: CellArray) -> CellArray:
    """Clockwise quarter turn: result[y][x] = pattern[h-1-x][y]."""
    return np.ascontiguousarray(np.rot90(pattern, k=-1, axes=(0, 1)))


def rotate90_ccw(pattern: CellArray) -> CellArray:
    """Counter-clockwise quarter turn: result[y][x] = pattern[x][w-1-y]; undoes rotate90."""
    return np.ascontiguousarray(np.rot90(pattern, k=1, axes=(0, 1)))


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
    mode: StampMode = "copy",
) -> None:
    """Write the pattern into the grid at top-left (x, y), in place (spec/patterns.md
    "Extract and stamp").

    Torus targets wrap; dead-boundary targets clip out-of-range cells; cells land in
    row-major order. ``mode`` combines each pattern cell ``p`` with the target cell ``t``:
    ``copy`` writes ``p``; ``or`` skips cells equal to 0 (the transparent value), which is
    what ``transparent=True`` means; ``xor`` and ``and`` write ``t ^ p`` and ``t & p``.
    Every mode but ``copy`` needs a 2-D payload (the opaque-only families reject it), and
    ``xor`` and ``and`` need two-state cells: a pattern cell, or a target cell under the
    pattern, other than 0 or 1 is a ValueError raised before anything is written.
    """
    if transparent:
        if mode not in ("copy", "or"):
            raise ValueError(f"transparent stamping is mode 'or'; it cannot be {mode!r} too")
        mode = "or"
    if mode not in STAMP_MODES:
        raise ValueError(f"unknown stamp mode {mode!r}; expected one of {STAMP_MODES}")
    if mode != "copy" and pattern.ndim != 2:
        raise ValueError(f"stamp mode {mode!r} is defined for 2-D cell payloads only")
    grid_h, grid_w = grid.shape[0], grid.shape[1]
    pat_h, pat_w = pattern.shape[0], pattern.shape[1]
    targets: list[tuple[int, int, int, int]] = []  # (row, col, dst_y, dst_x) in landing order
    for row in range(pat_h):
        for col in range(pat_w):
            dst_y = y + row
            dst_x = x + col
            if torus:
                targets.append((row, col, dst_y % grid_h, dst_x % grid_w))
            elif 0 <= dst_y < grid_h and 0 <= dst_x < grid_w:
                targets.append((row, col, dst_y, dst_x))
    if mode in ("xor", "and"):
        if not np.isin(pattern, (0, 1)).all():
            raise ValueError(f"stamp mode {mode!r} needs a two-state pattern (cells 0 and 1)")
        for _, _, dst_y, dst_x in targets:
            if grid[dst_y, dst_x] not in (0, 1):
                raise ValueError(
                    f"stamp mode {mode!r} needs two-state cells; ({dst_x}, {dst_y}) holds "
                    f"{grid[dst_y, dst_x]}"
                )
    for row, col, dst_y, dst_x in targets:
        p = pattern[row, col]
        if mode == "copy":
            grid[dst_y, dst_x] = p
        elif mode == "or":
            if p != 0:
                grid[dst_y, dst_x] = p
        elif mode == "xor":
            grid[dst_y, dst_x] ^= p
        else:
            grid[dst_y, dst_x] &= p


def check_region(width: int, height: int, x0: int, y0: int, x1: int, y1: int) -> None:
    """Raise ValueError unless (x0, y0)..(x1, y1) is a region of a width × height grid:
    an inclusive rectangle with 0 ≤ x0 ≤ x1 < width and 0 ≤ y0 ≤ y1 < height
    (spec/patterns.md "Editing a region")."""
    if not (0 <= x0 <= x1 < width and 0 <= y0 <= y1 < height):
        raise ValueError(
            f"region ({x0}, {y0})..({x1}, {y1}) is not an inclusive rectangle inside the "
            f"{width}x{height} grid"
        )


def turn_center(x0: int, y0: int, x1: int, y1: int) -> tuple[int, int]:
    """(s, d) of a quarter turn of the inclusive rectangle (spec/hashlife.md "Rectangle
    transforms"): clockwise sends (x, y) to (s − y, x + d), counter-clockwise to
    (y − d, s − x). The center itself when it is a cell or a cell corner; otherwise the cell
    with an even x + y of the two it lies between, so turns never drift."""
    sx, sy = x0 + x1, y0 + y1  # twice the center
    if (sx - sy) % 2 == 0:
        return (sx + sy) // 2, (sy - sx) // 2
    s = (sx + sy + 1) // 2
    if s % 2:
        s -= 1
    return (s, sy - s) if sx % 2 else (s, s - sx)


def turned_rect(
    x0: int, y0: int, x1: int, y1: int, *, clockwise: bool = True
) -> tuple[int, int, int, int]:
    """The rectangle a quarter turn of the inclusive rectangle about its center lands on
    (spec/patterns.md "Editing a region"), for any integers and without turning anything:
    the rectangle HashLife's ``rotate_rect`` returns. A grid turns a region onto it by
    pasting ``rotate90`` (or ``rotate90_ccw``) of the region at its top-left. Raises
    ValueError for an empty rectangle (x1 < x0 or y1 < y0)."""
    x0, y0, x1, y1 = (operator.index(v) for v in (x0, y0, x1, y1))
    if x1 < x0 or y1 < y0:
        raise ValueError(f"empty rectangle ({x0}, {y0})..({x1}, {y1})")
    s, d = turn_center(x0, y0, x1, y1)
    if clockwise:
        return s - y1, x0 + d, s - y0, x1 + d
    return y0 - d, s - x1, y1 - d, s - x0


def fill_random(
    grid: NDArray[np.uint8], x0: int, y0: int, x1: int, y1: int, *, density: float, seed: int
) -> None:
    """spec/patterns.md "Random fill": the region becomes the soup of a world its size.

    PCG32 stream 0 seeded with ``seed``, one draw per cell of the region in row-major
    order, alive iff ``draw < floor(density * 2**32)`` — the draws of ``soup`` for the
    region's width and height, and of HashLife's ``fill_random`` for the same rectangle
    size. Two-state (life-like) grids only; the generation is the caller's and stays.
    """
    if grid.ndim != 2:
        raise ValueError("random fill is defined for two-state (2-D) grids only")
    height, width = grid.shape
    check_region(width, height, x0, y0, x1, y1)
    grid[y0 : y1 + 1, x0 : x1 + 1] = soup((x1 - x0 + 1, y1 - y0 + 1), density=density, seed=seed)


def clear(grid: NDArray[Any], x0: int, y0: int, x1: int, y1: int, blank: Any) -> None:
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
        raise ValueError(f"clear region ({x0}, {y0})..({x1}, {y1}) is outside {width}x{height}")
    grid[y0 : y1 + 1, x0 : x1 + 1] = blank


def compatible(
    pattern_family: str, target_family: str, pattern: CellArray, target_states: int | None = None
) -> str | None:
    """Spec compatibility check: the rejection reason, or None when stampable.

    Patterns are family-bound (a glider cannot enter Wireworld); cyclic and generations
    additionally require every cell below the target's state count.
    """
    if pattern_family != target_family:
        return f"{pattern_family!r} patterns cannot be stamped into {target_family!r}"
    if target_family in ("cyclic", "generations") and target_states is not None:
        top = int(pattern.max(initial=0))
        if top >= target_states:
            return f"pattern uses state {top}, target has only {target_states} states"
    return None
