import numpy as np
import pytest

from heaton_life.ca import Cyclic


def test_successor_advance_with_threshold_one() -> None:
    grid = np.zeros((3, 3), dtype=np.uint8)
    grid[1, 2] = 1  # one neighbor of the center holds the successor state
    sim = Cyclic(4, size=(3, 3), threshold=1, init=grid)
    sim.step()
    assert sim.state[1, 1] == 1  # center advanced 0 -> 1


def test_threshold_blocks_advance() -> None:
    grid = np.zeros((3, 3), dtype=np.uint8)
    grid[1, 2] = 1
    sim = Cyclic(4, size=(3, 3), threshold=2, init=grid)
    sim.step()
    assert sim.state[1, 1] == 0  # one successor neighbor is not enough


def test_uniform_grid_is_fixed_point() -> None:
    grid = np.full((8, 8), 3, dtype=np.uint8)
    sim = Cyclic(5, size=(8, 8), init=grid)
    sim.step(10)
    assert np.array_equal(sim.state, grid)


def test_wraps_from_last_state_to_zero() -> None:
    grid = np.full((3, 3), 3, dtype=np.uint8)
    grid[1, 1] = 2  # center's successor (3) surrounds it
    sim = Cyclic(4, size=(3, 3), threshold=1, init=grid)
    sim.step()
    assert sim.state[1, 1] == 3
    # now the center is 3; its successor is 0, but no neighbor is 0
    sim.step()
    assert sim.state[1, 1] == 3


def test_vonneumann_excludes_diagonals() -> None:
    grid = np.zeros((3, 3), dtype=np.uint8)
    grid[0, 0] = 1  # diagonal neighbor of the center
    sim = Cyclic(4, size=(3, 3), threshold=1, neighborhood="vonneumann", init=grid)
    sim.step()
    assert sim.state[1, 1] == 0


def test_reach_two_counts_distant_cells() -> None:
    grid = np.zeros((5, 5), dtype=np.uint8)
    grid[2, 4] = 1  # two cells away from the center
    sim = Cyclic(4, size=(5, 5), threshold=1, reach=2, init=grid)
    sim.step()
    assert sim.state[2, 2] == 1


def test_soup_determinism_and_range() -> None:
    a = Cyclic(14, size=(32, 32), seed=7)
    b = Cyclic(14, size=(32, 32), seed=7)
    assert np.array_equal(a.state, b.state)
    assert a.state.max() < 14
    a.step(5)
    b.step(5)
    assert np.array_equal(a.state, b.state)


def test_rejects_bad_neighborhood_and_init_values() -> None:
    with pytest.raises(ValueError):
        Cyclic(4, size=(4, 4), neighborhood="hexagonal")
    with pytest.raises(ValueError):
        Cyclic(4, size=(2, 2), init=np.full((2, 2), 9, dtype=np.uint8))
