import numpy as np

from heaton_life.ca import Wireworld, clock_loop, wireworld_from_text
from heaton_life.ca.wireworld import CONDUCTOR, EMPTY, HEAD, TAIL
from heaton_life.init import place


def test_from_text() -> None:
    grid = wireworld_from_text(".#H\nT..")
    assert grid.tolist() == [[EMPTY, CONDUCTOR, HEAD], [TAIL, EMPTY, EMPTY]]


def test_electron_moves_along_wire() -> None:
    # head at x=2 fires the conductor at x=3; head decays to tail.
    pattern = wireworld_from_text("TH##")
    grid = place(pattern, (8, 3), at=(1, 1))
    sim = Wireworld(size=(8, 3), init=grid)
    sim.step()
    row = sim.state[1]
    assert row[1] == CONDUCTOR  # tail -> conductor
    assert row[2] == TAIL  # head -> tail
    assert row[3] == HEAD  # conductor next to one head -> head
    assert row[4] == CONDUCTOR  # too far: stays conductor


def test_conductor_with_three_heads_does_not_fire() -> None:
    pattern = wireworld_from_text("H.\n" "H#\n" "H.")
    grid = place(pattern, (6, 5), at=(1, 1))
    sim = Wireworld(size=(6, 5), init=grid)
    sim.step()
    assert sim.state[2, 2] == CONDUCTOR  # 3 head neighbors: no fire


def test_empty_stays_empty() -> None:
    sim = Wireworld(size=(8, 8), init=np.zeros((8, 8), dtype=np.uint8))
    sim.step(3)
    assert not sim.state.any()


def test_clock_loop_is_periodic() -> None:
    # The electron cuts corners (Moore adjacency briefly doubles the head), so we
    # detect the period instead of predicting it from the perimeter.
    sim = Wireworld(size=(16, 16), init="clock")
    sim.step()  # the seeded configuration is a transient; step onto the attractor
    reference = sim.state.copy()
    period = None
    for t in range(1, 101):
        sim.step()
        assert 1 <= (sim.state == HEAD).sum() <= 2, "electron must neither die nor explode"
        if np.array_equal(sim.state, reference):
            period = t
            break
    assert period is not None, "clock loop must be periodic"
    assert period >= 20, f"suspiciously short period {period} for a 16x16 loop"


def test_clock_loop_helper_shape() -> None:
    grid = clock_loop((20, 12))
    assert grid.shape == (12, 20)
    assert (grid == HEAD).sum() == 1
    assert (grid == TAIL).sum() == 1
