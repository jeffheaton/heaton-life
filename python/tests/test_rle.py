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
