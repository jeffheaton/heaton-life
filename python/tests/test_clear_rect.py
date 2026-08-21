"""Clear is normative (spec/patterns.md "Extract and stamp"), and until 2026-08-21
the Python library had no implementation of it at all — only the C# port did, per
family as ``ClearRect``. These pin the family blanks, which the spec is explicit
about: they are family facts, not app choices, and Gray-Scott's is the substrate
rather than zero.
"""

import numpy as np
import pytest

from heaton_life.ca import Cyclic, LifeLike, MergeLife, Wireworld
from heaton_life.lenia import ClassicLenia
from heaton_life.rd import GrayScott


def test_lifelike_clears_to_dead() -> None:
    # density 1.0 = every cell alive, so anything blank afterwards was cleared.
    # Deliberately NOT stepped first: B3/S23 kills a saturated grid immediately,
    # which would leave nothing to prove "outside is untouched" with.
    sim = LifeLike("B3/S23", size=(8, 8), init="soup", density=1.0)
    assert sim.state.all()

    sim.clear_rect(1, 1, 3, 4)

    assert not sim.state[1:5, 1:4].any()          # inclusive corners
    assert sim.state[0, 0] == 1                    # outside untouched
    assert sim.state[5, 4] == 1


def test_clearing_does_not_reset_the_generation() -> None:
    """spec/patterns.md: clearing, like stamping, does not reset the generation."""
    sim = LifeLike("B3/S23", size=(8, 8), init="soup", density=0.4, seed=5)
    sim.step(3)
    assert sim.generation == 3
    sim.clear_rect(0, 0, 7, 7)
    assert sim.generation == 3


def test_cyclic_clears_to_zero() -> None:
    sim = Cyclic(states=6, size=(8, 8))
    sim.step()
    sim.clear_rect(0, 0, 2, 2)
    assert not sim.state[0:3, 0:3].any()


def test_wireworld_clears_to_empty() -> None:
    sim = Wireworld(size=(12, 12), init="clock")
    assert sim.state.any()
    sim.clear_rect(0, 0, 11, 11)
    assert not sim.state.any()


def test_mergelife_clears_to_black_across_rgb() -> None:
    sim = MergeLife(size=(8, 8), seed=3)
    sim.step()
    generation = sim.generation
    sim.clear_rect(2, 2, 5, 5)
    assert not sim.state[2:6, 2:6, :].any()        # all three channels
    assert sim.state.shape[2] == 3
    assert sim.generation == generation


def test_lenia_clears_to_zero() -> None:
    sim = ClassicLenia(size=(32, 32), radius=8)
    sim.clear_rect(4, 4, 20, 20)
    assert np.all(sim.state[4:21, 4:21] == 0.0)


def test_grayscott_clears_to_the_substrate_not_zero() -> None:
    """The spec calls this out by name: Gray-Scott's blank is U = 1, V = 0."""
    sim = GrayScott(size=(32, 32), init="spots", seed=1)
    sim.step(3)
    generation = sim.generation

    sim.clear_rect(5, 5, 15, 15)

    u, v = sim.state[0], sim.state[1]
    assert np.all(u[5:16, 5:16] == 1.0), "U must be restored to the substrate, not 0"
    assert np.all(v[5:16, 5:16] == 0.0)
    assert sim.generation == generation


@pytest.mark.parametrize(
    "rect",
    [(-1, 0, 2, 2), (0, -1, 2, 2), (0, 0, 8, 2), (0, 0, 2, 8), (3, 0, 1, 2), (0, 3, 2, 1)],
)
def test_out_of_bounds_and_inverted_rectangles_are_rejected(rect: tuple[int, int, int, int]) -> None:
    sim = LifeLike("B3/S23", size=(8, 8))
    with pytest.raises(ValueError):
        sim.clear_rect(*rect)


def test_a_single_cell_is_a_legal_rectangle() -> None:
    """Inclusive corners, so x0 == x1 clears exactly one column."""
    sim = LifeLike("B3/S23", size=(8, 8), init="soup", density=1.0)
    sim.clear_rect(3, 4, 3, 4)
    assert sim.state[4, 3] == 0
    assert sim.state[4, 2] == 1
    assert sim.state[3, 3] == 1
