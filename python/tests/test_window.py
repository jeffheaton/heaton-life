"""Sampling a window of a grid (spec/render.md "Sampling a window of a grid"): what each
pixel covers, its nearest cell, and the three modes, against a direct reading of the spec."""

import numpy as np
import pytest

from heaton_life.ca import LifeLike
from heaton_life.render import (
    HISTORY_ZOOM_ORDER,
    default_zoom_order,
    sample_window,
    zoom_ranks,
)


def _covered(start: int, cells: int, out: int, i: int) -> range:
    """The cells pixel i covers along one axis, straight from the spec's formula."""
    first = (2 * i * cells + out - 1) // (2 * out)
    end = (2 * (i + 1) * cells + out - 1) // (2 * out)
    return range(start + first, start + end)


def _reference(
    grid: np.ndarray,
    x0: int,
    y0: int,
    width: int,
    height: int,
    out_w: int,
    out_h: int,
    mode: str,
    order: tuple[int, ...],
) -> np.ndarray:
    ranking = list(order) + [v for v in range(1, 256) if v not in order]
    out = np.zeros((out_h, out_w), dtype=np.uint8)
    for j in range(out_h):
        rows = _covered(y0, height, out_h, j)
        for i in range(out_w):
            columns = _covered(x0, width, out_w, i)
            values = [int(grid[r, c]) for r in rows for c in columns]
            if mode == "nearest":
                r = y0 + (2 * j + 1) * height // (2 * out_h)
                c = x0 + (2 * i + 1) * width // (2 * out_w)
                assert r in rows and c in columns, "the nearest cell is one the pixel covers"
                out[j, i] = grid[r, c]
            elif mode == "state":
                present = {v for v in values if v}
                out[j, i] = next((v for v in ranking if v in present), 0)
            else:
                live = sum(1 for v in values if v)
                out[j, i] = (255 * live + len(values) - 1) // len(values)
    return out


def test_the_pixels_share_out_the_window() -> None:
    for cells in range(1, 40):
        for out in range(1, cells + 1):
            spans = [_covered(0, cells, out, i) for i in range(out)]
            assert all(len(s) >= 1 for s in spans)
            assert [c for s in spans for c in s] == list(range(cells))
            for i, span in enumerate(spans):  # the cells whose centers lie in the share
                assert all(i * cells <= (c + 0.5) * out < (i + 1) * cells for c in span)


@pytest.mark.parametrize("seed", range(12))
def test_every_mode_matches_the_spec_read_directly(seed: int) -> None:
    rng = np.random.default_rng(seed)
    grid_h, grid_w = rng.integers(1, 40, 2)
    grid = rng.choice([0, 0, 0, 1, 2, 3, 6, 200, 255], size=(grid_h, grid_w)).astype(np.uint8)
    for _ in range(6):
        width = int(rng.integers(1, grid_w + 1))
        height = int(rng.integers(1, grid_h + 1))
        x0 = int(rng.integers(0, grid_w - width + 1))
        y0 = int(rng.integers(0, grid_h - height + 1))
        out_w = int(rng.integers(1, width + 1))
        out_h = int(rng.integers(1, height + 1))
        order = tuple(int(v) for v in rng.permutation([1, 2, 3, 6, 200, 255])[: rng.integers(0, 4)])
        for mode in ("nearest", "state", "density"):
            got = sample_window(grid, x0, y0, width, height, out_w, out_h, mode=mode, order=order)  # type: ignore[arg-type]
            want = _reference(grid, x0, y0, width, height, out_w, out_h, mode, order)
            assert got.dtype == np.uint8 and got.shape == (out_h, out_w)
            assert np.array_equal(got, want), (mode, x0, y0, width, height, out_w, out_h, order)


def test_a_lone_live_cell_never_vanishes() -> None:
    misses = 0
    for y in range(0, 61, 7):
        for x in range(0, 97, 5):
            grid = np.zeros((61, 97), dtype=np.uint8)
            grid[y, x] = 1
            for out_w, out_h in ((13, 7), (40, 30), (1, 1), (96, 60)):
                assert sample_window(grid, 0, 0, 97, 61, out_w, out_h).sum() == 1
                dense = sample_window(grid, 0, 0, 97, 61, out_w, out_h, mode="density")
                assert np.count_nonzero(dense) == 1
                misses += int(
                    sample_window(grid, 0, 0, 97, 61, out_w, out_h, mode="nearest").sum() == 0
                )
    assert misses > 0, "nearest sampling does lose lone cells, which is the point"


def test_a_pixel_live_under_nearest_is_live_under_state() -> None:
    rng = np.random.default_rng(3)
    grid = (rng.random((120, 150)) < 0.02).astype(np.uint8)
    for out_w, out_h in ((150, 120), (77, 51), (20, 9), (3, 2)):
        nearest = sample_window(grid, 0, 0, 150, 120, out_w, out_h, mode="nearest")
        state = sample_window(grid, 0, 0, 150, 120, out_w, out_h)
        assert np.all(state >= nearest)


def test_as_many_pixels_as_cells_is_the_window_itself() -> None:
    rng = np.random.default_rng(5)
    grid = rng.integers(0, 256, (30, 41)).astype(np.uint8)
    window = grid[4:24, 7:40]
    for mode in ("nearest", "state"):
        assert np.array_equal(sample_window(grid, 7, 4, 33, 20, 33, 20, mode=mode), window)  # type: ignore[arg-type]
    dense = sample_window(grid, 7, 4, 33, 20, 33, 20, mode="density")
    assert np.array_equal(dense, np.where(window != 0, 255, 0))


def test_nearest_is_the_cell_under_each_pixels_center() -> None:
    grid = np.arange(64 * 64, dtype=np.int64).reshape(64, 64) % 251
    grid = grid.astype(np.uint8)
    got = sample_window(grid, 3, 5, 50, 40, 21, 17, mode="nearest")
    rows = [5 + (2 * j + 1) * 40 // 34 for j in range(17)]
    columns = [3 + (2 * i + 1) * 50 // 42 for i in range(21)]
    assert np.array_equal(got, grid[np.ix_(rows, columns)])


def test_the_zoom_order_picks_among_the_states_a_pixel_covers() -> None:
    grid = np.array([[2, 1, 0, 0], [0, 5, 4, 0], [3, 0, 0, 6]], dtype=np.uint8)
    assert sample_window(grid, 0, 0, 4, 3, 1, 1).tolist() == [[1]]
    assert sample_window(grid, 0, 0, 4, 3, 1, 1, order=(6,)).tolist() == [[6]]
    assert sample_window(grid, 0, 0, 4, 3, 1, 1, order=HISTORY_ZOOM_ORDER).tolist() == [[3]]
    history = np.array([[2, 2, 2], [2, 1, 2], [2, 2, 2]], dtype=np.uint8)
    assert sample_window(history, 0, 0, 3, 3, 1, 1).tolist() == [[1]]
    marked = np.array([[2, 2, 5], [2, 2, 2], [4, 2, 2]], dtype=np.uint8)
    assert sample_window(marked, 0, 0, 3, 3, 1, 1).tolist() == [[2]]  # lowest first hides it
    order = default_zoom_order(LifeLike("B3/S23History", size=(8, 8)))
    assert sample_window(marked, 0, 0, 3, 3, 1, 1, order=order).tolist() == [[5]]
    assert sample_window(np.zeros((5, 5), np.uint8), 0, 0, 5, 5, 2, 2).tolist() == [[0, 0], [0, 0]]


def test_density_counts_the_non_zero_cells_rounding_up() -> None:
    grid = np.zeros((3, 4), dtype=np.uint8)
    grid[0, 0] = 9
    assert sample_window(grid, 0, 0, 4, 3, 1, 1, mode="density").tolist() == [[22]]  # ⌈255/12⌉
    grid[:] = 7
    assert sample_window(grid, 0, 0, 4, 3, 1, 1, mode="density").tolist() == [[255]]


def test_zoom_ranks() -> None:
    ranks = zoom_ranks((3, 5, 1))
    assert ranks[3] == 0 and ranks[5] == 1 and ranks[1] == 2 and ranks[2] == 3 and ranks[4] == 4
    assert ranks[0] == 255 and sorted(ranks[1:].tolist()) == list(range(255))
    assert zoom_ranks(())[1:].tolist() == list(range(255))


@pytest.mark.parametrize(
    "args",
    [
        (-1, 0, 4, 4, 2, 2),
        (0, 0, 11, 4, 2, 2),
        (0, 7, 4, 4, 2, 2),
        (0, 0, 0, 4, 1, 1),
        (0, 0, 4, 4, 5, 2),
        (0, 0, 4, 4, 2, 0),
        (8, 0, 3, 4, 2, 2),
    ],
)
def test_a_window_inside_the_grid_and_sizes_in_range(args: tuple[int, ...]) -> None:
    with pytest.raises(ValueError):
        sample_window(np.zeros((10, 10), np.uint8), *args)


def test_bad_modes_orders_and_grids_are_refused() -> None:
    grid = np.zeros((4, 4), np.uint8)
    with pytest.raises(ValueError, match="mode"):
        sample_window(grid, 0, 0, 4, 4, 2, 2, mode="max")  # type: ignore[arg-type]
    for order in ((0,), (256,), (3, 3), (-1,)):
        with pytest.raises(ValueError, match="zoom order"):
            sample_window(grid, 0, 0, 4, 4, 2, 2, order=order)
    with pytest.raises(ValueError, match="uint8"):
        sample_window(grid.astype(np.int32), 0, 0, 4, 4, 2, 2)
    with pytest.raises(ValueError, match="uint8"):
        sample_window(np.zeros(16, np.uint8), 0, 0, 4, 4, 2, 2)
