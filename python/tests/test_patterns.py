"""Pattern operations (spec/patterns.md): transforms, extract/stamp, compatibility,
and the multi-state RLE dialect."""

import numpy as np
import pytest

from heaton_life.init import (
    compatible,
    extract,
    flip_h,
    flip_v,
    rle_decode,
    rle_encode,
    rotate90,
    stamp,
)

GLIDER = np.array([[0, 1, 0], [0, 0, 1], [1, 1, 1]], dtype=np.uint8)


def test_rotate90_is_clockwise() -> None:
    pattern = np.array([[1, 2], [3, 4]], dtype=np.uint8)
    assert rotate90(pattern).tolist() == [[3, 1], [4, 2]]
    # Four quarter turns are the identity.
    result = pattern
    for _ in range(4):
        result = rotate90(result)
    assert np.array_equal(result, pattern)


def test_flips_mirror_and_involute() -> None:
    assert flip_h(GLIDER).tolist() == [[0, 1, 0], [1, 0, 0], [1, 1, 1]]
    assert flip_v(GLIDER).tolist() == [[1, 1, 1], [0, 0, 1], [0, 1, 0]]
    assert np.array_equal(flip_h(flip_h(GLIDER)), GLIDER)
    assert np.array_equal(flip_v(flip_v(GLIDER)), GLIDER)


def test_transforms_move_trailing_channels_together() -> None:
    rgb = np.zeros((1, 2, 3), dtype=np.uint8)
    rgb[0, 0] = (10, 20, 30)
    rgb[0, 1] = (40, 50, 60)
    rotated = rotate90(rgb)
    assert rotated.shape == (2, 1, 3)
    assert rotated[0, 0].tolist() == [10, 20, 30]
    assert rotated[1, 0].tolist() == [40, 50, 60]


def test_extract_wraps_on_torus_and_zero_fills_dead() -> None:
    grid = np.arange(16, dtype=np.uint8).reshape(4, 4)
    wrapped = extract(grid, 3, 3, 2, 2, torus=True)
    assert wrapped.tolist() == [[15, 12], [3, 0]]
    clipped = extract(grid, 3, 3, 2, 2, torus=False)
    assert clipped.tolist() == [[15, 0], [0, 0]]


def test_stamp_wraps_clips_and_respects_transparency() -> None:
    grid = np.zeros((4, 4), dtype=np.uint8)
    stamp(grid, GLIDER, 2, 2, torus=True)
    assert grid[2, 3] == 1 and grid[3, 0] == 1 and grid[0, 2] == 1  # wrapped cells

    grid = np.zeros((4, 4), dtype=np.uint8)
    stamp(grid, GLIDER, 2, 2, torus=False)
    assert grid[3, 3] == 0  # glider's (1,1) is 0; nothing outside leaked back in
    assert grid.sum() == 1  # only the in-range live cell landed

    grid = np.full((3, 3), 7, dtype=np.uint8)
    stamp(grid, GLIDER, 0, 0, torus=True, transparent=True)
    assert grid[0, 0] == 7  # dead pattern cell skipped
    assert grid[0, 1] == 1

    grid = np.full((3, 3), 7, dtype=np.uint8)
    stamp(grid, GLIDER, 0, 0, torus=True, transparent=False)
    assert grid[0, 0] == 0  # opaque stamp overwrites with dead cells


def test_transparent_rejected_for_channel_payloads() -> None:
    rgb_grid = np.zeros((4, 4, 3), dtype=np.uint8)
    rgb_pattern = np.ones((2, 2, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        stamp(rgb_grid, rgb_pattern, 0, 0, torus=True, transparent=True)


def test_compatibility_is_family_bound() -> None:
    assert compatible("lifelike", "wireworld", GLIDER) is not None
    assert compatible("lifelike", "mergelife", GLIDER) is not None
    assert compatible("lifelike", "lifelike", GLIDER) is None
    high_state = np.array([[13]], dtype=np.uint8)
    assert compatible("cyclic", "cyclic", high_state, target_states=14) is None
    assert compatible("cyclic", "cyclic", high_state, target_states=6) is not None


def test_multistate_rle_round_trip() -> None:
    diode = np.array([[0, 3, 3, 0], [1, 3, 0, 3], [0, 3, 3, 2]], dtype=np.uint8)
    text = rle_encode(diode, rule="WireWorld")
    assert "." in text and "C" in text and "A" in text
    decoded, rule = rle_decode(text)
    assert rule == "WireWorld"
    assert np.array_equal(decoded, diode)


def test_two_state_rle_still_round_trips() -> None:
    text = rle_encode(GLIDER)
    assert "o" in text and "." not in text
    decoded, _ = rle_decode(text)
    assert np.array_equal(decoded, GLIDER)


def test_rle_rejects_unencodable_states() -> None:
    with pytest.raises(ValueError):
        rle_encode(np.array([[25]], dtype=np.uint8))
