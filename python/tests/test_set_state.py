"""A world's state and its start (spec/README.md): ``set_state`` on every family that keeps a
start. By default the state becomes the start ``reset()`` returns to; with ``keep_start``
the start stays, so a host showing a saved frame or an undo point leaves Reset alone."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from heaton_life.boids import Boids
from heaton_life.ca import Cyclic, Elementary, LargerThanLife, LifeLike, MergeLife, Wireworld
from heaton_life.lenia import AsymptoticLenia, ClassicLenia, FlowLenia
from heaton_life.rd import GrayScott

FAMILIES: dict[str, Callable[[], Any]] = {
    "lifelike": lambda: LifeLike(size=(16, 12), seed=3),
    "elementary": lambda: Elementary(30, size=(16, 8), init="soup", seed=5),
    "cyclic": lambda: Cyclic(5, size=(16, 12), seed=2),
    "wireworld": lambda: Wireworld(size=(16, 12)),
    "mergelife": lambda: MergeLife(size=(16, 12), seed=1),
    "grayscott": lambda: GrayScott(size=(16, 12), seed=4, spots=3),
    "lenia-classic": lambda: ClassicLenia(size=(32, 32), radius=8, blobs=3),
    "lenia-asymptotic": lambda: AsymptoticLenia(size=(32, 32), radius=8, blobs=3),
    "lenia-flow": lambda: FlowLenia(size=(32, 32), radius=8),
    "boids": lambda: Boids(8, size=(64, 64), seed=6),
    "ltl": lambda: LargerThanLife(size=(16, 12), seed=7),
}


@pytest.fixture(params=sorted(FAMILIES), name="make")
def _make(request: pytest.FixtureRequest) -> Callable[[], Any]:
    return FAMILIES[request.param]


def test_keep_start_moves_the_world_but_not_its_start(make: Callable[[], Any]) -> None:
    sim = make()
    born = sim.state.copy()
    sim.step(3)
    later = sim.state.copy()
    assert not np.array_equal(born, later)
    sim.reset()
    given = later.copy()
    sim.set_state(given, 9, keep_start=True)
    given[...] = 0  # the world keeps its own copy
    assert np.array_equal(sim.state, later)
    assert sim.generation == 9
    sim.reset()
    assert np.array_equal(sim.state, born)
    assert sim.generation == 0


def test_by_default_the_state_becomes_the_start(make: Callable[[], Any]) -> None:
    sim = make()
    born = sim.state.copy()
    sim.step(3)
    later = sim.state.copy()
    sim.set_state(later, 4)
    assert sim.generation == 4
    assert sim.params.init == "array"
    sim.set_state(born, 7, keep_start=True)  # moving it again keeps the new start
    sim.reset()
    assert np.array_equal(sim.state, later)
    assert sim.generation == 0


def test_the_wrong_shape_changes_nothing(make: Callable[[], Any]) -> None:
    sim = make()
    sim.step(2)
    before = sim.state.copy()
    wrong = np.zeros(tuple(n + 1 for n in before.shape), dtype=before.dtype)
    for keep_start in (False, True):
        with pytest.raises(ValueError, match="shape"):
            sim.set_state(wrong, 5, keep_start=keep_start)
        assert np.array_equal(sim.state, before)
        assert sim.generation == 2


def test_values_the_init_refuses_change_nothing() -> None:
    wire = Wireworld(size=(12, 12))
    before = wire.state.copy()
    bad = before.copy()
    bad[0, 0] = 4
    with pytest.raises(ValueError, match="> 3"):
        wire.set_state(bad, keep_start=True)
    assert np.array_equal(wire.state, before)
    cyclic = Cyclic(4, size=(8, 6), seed=1)
    before = cyclic.state.copy()
    bad = before.copy()
    bad[1, 1] = 4
    with pytest.raises(ValueError, match="states"):
        cyclic.set_state(bad)
    assert np.array_equal(cyclic.state, before)
    life = LifeLike(size=(8, 6))
    life.set_state(np.full((6, 8), 7, dtype=np.uint8), keep_start=True)
    assert set(np.unique(life.state)) == {1}  # nonzero is alive


def test_elementary_takes_its_diagram_or_restarts_it() -> None:
    sim = Elementary(90, size=(16, 8), init="single")
    sim.step(5)
    tape, diagram = sim.state.copy(), sim.frame() // 255
    sim.reset()
    sim.set_state(tape, 5, diagram=diagram, keep_start=True)
    assert np.array_equal(sim.frame() // 255, diagram)
    sim.set_state(tape, 5, keep_start=True)  # the tape alone: in row 5, the rest blank
    picture = sim.frame() // 255
    assert np.array_equal(picture[5], tape)
    assert picture.sum() == tape.sum()
    sim.set_state(tape, 40, keep_start=True)  # past the last row: in the last row
    assert np.array_equal(sim.frame()[-1] // 255, tape)
    sim.step()  # the picture goes on from the tape's row
    sim.reset()
    assert sim.generation == 0
    assert sim.state.sum() == 1  # the single cell it was born with
    with pytest.raises(ValueError, match="diagram"):
        sim.set_state(tape, 0, diagram=np.zeros((3, 16), np.uint8))
