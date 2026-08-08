import numpy as np

from heaton_life.ca import Elementary
from heaton_life.init import soup


def test_rule_110_first_step_from_single() -> None:
    sim = Elementary(110, size=(11, 8), init="single")
    c = 5
    sim.step()
    expected = np.zeros(11, dtype=np.uint8)
    expected[c - 1] = 1  # (0,0,1) -> bit 1 of 110 -> 1
    expected[c] = 1  # (0,1,0) -> bit 2 of 110 -> 1
    # (1,0,0) -> bit 4 of 110 -> 0
    assert np.array_equal(sim.state, expected)


def test_rule_90_is_xor_of_neighbors() -> None:
    sim = Elementary(90, size=(64, 8), init="soup", density=0.5, seed=3)
    tape = sim.state.copy()
    sim.step()
    expected = np.roll(tape, 1) ^ np.roll(tape, -1)
    assert np.array_equal(sim.state, expected)


def test_rule_254_fills_with_dead_boundary() -> None:
    sim = Elementary(254, size=(9, 8), init="single", boundary="dead")
    sim.step(4)  # spreads one cell per side per step
    assert sim.state.tolist() == [1] * 9


def test_torus_wraps() -> None:
    tape = np.zeros(8, dtype=np.uint8)
    tape[0] = 1
    sim = Elementary(254, size=(8, 8), init=tape)  # 254: any live neighbor -> alive
    sim.step()
    assert sim.state[7] == 1  # wrapped around the left edge


def test_diagram_records_history_then_scrolls() -> None:
    sim = Elementary(30, size=(16, 4), init="single")
    sim.step(2)
    frame = sim.frame()
    assert frame.shape == (4, 16)
    assert frame[0].any() and frame[2].any()
    assert not frame[3].any()  # not yet reached
    row2 = frame[2].copy()
    sim.step(1)  # fills last row
    sim.step(1)  # forces scroll
    frame = sim.frame()
    assert np.array_equal(frame[1], row2)  # scrolled up by one


def test_reset_and_determinism() -> None:
    a = Elementary(110, size=(64, 16), init="soup", seed=9)
    b = Elementary(110, size=(64, 16), init="soup", seed=9)
    a.step(20)
    b.step(20)
    assert np.array_equal(a.state, b.state)
    a.reset()
    assert a.generation == 0
    assert np.array_equal(a.state, soup((64, 1), density=0.5, seed=9)[0])
