import numpy as np
import pytest

from heaton_life.ca import LifeLike, LifeLikeParams
from heaton_life.init import place, rle_decode

GLIDER_RLE = "x = 3, y = 3, rule = B3/S23\nbob$2bo$3o!"


def glider_sim(size: int = 16) -> LifeLike:
    pattern, _ = rle_decode(GLIDER_RLE)
    grid = place(pattern, (size, size), at=(0, 0))
    return LifeLike("B3/S23", size=(size, size), init=grid)


def test_block_is_still_life() -> None:
    grid = np.zeros((4, 4), dtype=np.uint8)
    grid[1:3, 1:3] = 1
    sim = LifeLike("B3/S23", size=(4, 4), init=grid, boundary="dead")
    sim.step(5)
    assert np.array_equal(sim.state, grid)


def test_blinker_oscillates() -> None:
    grid = np.zeros((5, 5), dtype=np.uint8)
    grid[2, 1:4] = 1
    sim = LifeLike("B3/S23", size=(5, 5), init=grid, boundary="dead")
    sim.step()
    vertical = np.zeros((5, 5), dtype=np.uint8)
    vertical[1:4, 2] = 1
    assert np.array_equal(sim.state, vertical)
    sim.step()
    assert np.array_equal(sim.state, grid)


def test_glider_translates_diagonally_every_4_steps() -> None:
    sim = glider_sim()
    initial = sim.state.copy()
    sim.step(4)
    shifts = [(dy, dx) for dy in (-1, 1) for dx in (-1, 1)]
    matches = [s for s in shifts if np.array_equal(sim.state, np.roll(initial, s, axis=(0, 1)))]
    assert len(matches) == 1, "glider must translate by exactly one diagonal cell per 4 steps"
    shift = matches[0]
    sim.step(4)
    twice = np.roll(initial, (2 * shift[0], 2 * shift[1]), axis=(0, 1))
    assert np.array_equal(sim.state, twice), "direction must be consistent"


def test_glider_returns_home_on_torus() -> None:
    sim = glider_sim(16)
    initial = sim.state.copy()
    sim.step(64)  # (1,1) per 4 steps -> 16 cells -> wraps to start on a 16x16 torus
    assert np.array_equal(sim.state, initial)
    assert sim.generation == 64


def test_soup_is_reproducible() -> None:
    a = LifeLike(size=(64, 64), seed=42)
    b = LifeLike(size=(64, 64), seed=42)
    c = LifeLike(size=(64, 64), seed=43)
    assert np.array_equal(a.state, b.state)
    assert not np.array_equal(a.state, c.state)
    a.step(10)
    b.step(10)
    assert np.array_equal(a.state, b.state)


def test_reset_replays() -> None:
    sim = LifeLike(size=(32, 32), seed=7)
    initial = sim.state.copy()
    sim.step(20)
    sim.reset()
    assert np.array_equal(sim.state, initial)
    assert sim.generation == 0
    sim.reset(seed=8)
    assert sim.params.seed == 8
    assert not np.array_equal(sim.state, initial)


def test_params_roundtrip_and_from_params() -> None:
    sim = LifeLike("highlife", size=(48, 32), density=0.5, seed=11, boundary="dead")
    assert sim.params.rule == "B36/S23"
    clone = LifeLike.from_params(LifeLikeParams.from_json(sim.params.to_json()))
    assert np.array_equal(clone.state, sim.state)


def test_from_params_rejects_array_init() -> None:
    sim = glider_sim()
    with pytest.raises(ValueError):
        LifeLike.from_params(sim.params)


def test_state_shape_and_frame() -> None:
    sim = LifeLike(size=(30, 20))  # width=30, height=20
    assert sim.state.shape == (20, 30)
    f = sim.frame()
    assert f.dtype == np.uint8
    assert set(np.unique(f)).issubset({0, 255})
