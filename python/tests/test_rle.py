import numpy as np
import pytest

from heaton_life.init import place, rle_decode, rle_encode, soup


def test_decode_glider() -> None:
    grid, rule = rle_decode("x = 3, y = 3, rule = B3/S23\nbob$2bo$3o!")
    assert rule == "B3/S23"
    expected = np.array([[0, 1, 0], [0, 0, 1], [1, 1, 1]], dtype=np.uint8)
    assert np.array_equal(grid, expected)


def test_decode_without_header_and_with_comments() -> None:
    grid, rule = rle_decode("#C a blinker\n3o!")
    assert rule is None
    assert np.array_equal(grid, np.array([[1, 1, 1]], dtype=np.uint8))


def test_decode_multi_dollar_and_trailing_dead() -> None:
    grid, _ = rle_decode("x = 2, y = 3\noo2$o!")
    expected = np.array([[1, 1], [0, 0], [1, 0]], dtype=np.uint8)
    assert np.array_equal(grid, expected)


def test_roundtrip_random() -> None:
    grid = soup((37, 23), density=0.4, seed=5)
    decoded, rule = rle_decode(rle_encode(grid))
    assert rule == "B3/S23"
    assert np.array_equal(decoded, grid)


def test_place_center_and_corner() -> None:
    pattern = np.ones((2, 3), dtype=np.uint8)
    grid = place(pattern, (10, 8))
    assert grid.shape == (8, 10)
    assert grid.sum() == 6
    assert grid[3, 3] == 1  # y=(8-2)//2=3, x=(10-3)//2=3
    corner = place(pattern, (10, 8), at=(0, 0))
    assert corner[0:2, 0:3].sum() == 6


def test_place_too_big_raises() -> None:
    with pytest.raises(ValueError):
        place(np.ones((5, 5), dtype=np.uint8), (4, 4))


def test_decode_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        rle_decode("x = 2, y = 2\nzz!")


# -- extent, the decode limit, trimmed decoding (spec/patterns.md) -------------------------


def test_measure_agrees_with_decode_on_random_grids() -> None:
    from heaton_life.core.rng import Pcg32
    from heaton_life.init import rle_measure

    rng = Pcg32(7)
    for _ in range(60):
        height, width = 1 + rng.next_u32() % 9, 1 + rng.next_u32() % 9
        grid = np.array(
            [[rng.next_u32() % 4 == 0 for _ in range(width)] for _ in range(height)],
            dtype=np.uint8,
        )
        text = rle_encode(grid)
        extent = rle_measure(text)
        decoded, _ = rle_decode(text)
        assert (extent.height, extent.width) == decoded.shape == grid.shape
        assert extent.population == int(grid.sum())
        if extent.live is None:
            assert not grid.any()
            continue
        x0, y0, x1, y1 = extent.live
        rows, columns = np.flatnonzero(grid.any(axis=1)), np.flatnonzero(grid.any(axis=0))
        assert (x0, y0, x1, y1) == (columns[0], rows[0], columns[-1], rows[-1])
        trimmed, _ = rle_decode(text, trim=True)
        assert np.array_equal(trimmed, grid[y0 : y1 + 1, x0 : x1 + 1])


def test_measure_never_makes_what_it_measures() -> None:
    from heaton_life.init import rle_measure

    extent = rle_measure("x = 1000000000, y = 1000000000, rule = B3/S23\n999999999bo$3o!")
    assert (extent.width, extent.height) == (10**9, 10**9)
    assert (extent.live, extent.population) == ((0, 0, 999_999_999, 1), 4)
    huge = rle_measure("9" * 40 + "$o!")
    assert huge.height == int("9" * 40) + 1 and huge.live == (0, int("9" * 40), 0, int("9" * 40))


def test_decode_refuses_past_the_limit_before_allocating() -> None:
    from heaton_life.init import DEFAULT_MAX_CELLS

    assert DEFAULT_MAX_CELLS == 2**26
    for text in ("x = 1000000000, y = 1000000000\no!", "o999999999b$o!", "o1000000000$o!"):
        with pytest.raises(ValueError, match="past the limit of 67,108,864"):
            rle_decode(text)
    with pytest.raises(ValueError, match="past the limit of 8"):
        rle_decode("bo$2bo$3o!", max_cells=8)
    grid, _ = rle_decode("bo$2bo$3o!", max_cells=9)
    assert grid.shape == (3, 3)
    lifted, _ = rle_decode("x = 9000, y = 9000\no!", max_cells=None)
    assert lifted.shape == (9000, 9000) and int(lifted.sum()) == 1


def test_trimmed_decode_is_the_live_cells_box() -> None:
    grid, rule = rle_decode(
        "x = 1000000000, y = 1000000000, rule = B36/S23\n5$7bo$8bo$6b3o9b!", trim=True
    )
    assert rule == "B36/S23"
    assert np.array_equal(grid, np.array([[0, 1, 0], [0, 0, 1], [1, 1, 1]], dtype=np.uint8))
    with pytest.raises(ValueError, match="no live cells"):
        rle_decode("x = 3, y = 3\n3b$3b!", trim=True)
    with pytest.raises(ValueError, match="past the limit"):
        rle_decode("bo$2bo$3o!", trim=True, max_cells=8)


def test_runs_come_one_at_a_time() -> None:
    """The scan used to tokenize the whole body first: a list as long as the file."""
    from heaton_life.init import rle_runs

    _, runs = rle_runs("o$" * 200_000 + "o!")
    assert next(runs) == (0, 0, 1, 1) and next(runs) == (0, 1, 1, 1)
    assert sum(1 for _ in runs) == 199_999
