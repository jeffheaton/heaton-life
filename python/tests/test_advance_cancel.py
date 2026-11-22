"""Canceling grid Advance Selection and Advance Outside (spec/patterns.md "Canceling"): a
``cancel()`` from another thread stops the advance with HashLife's ``StepCanceled`` and leaves
the world exactly as it was; an advance nobody cancels gives the same cells as ever. The .NET
suite checks the same with a CancellationToken (GridAdvanceCancelTests.cs)."""

from __future__ import annotations

import threading
from collections.abc import Callable

import numpy as np
import pytest
from numpy.typing import NDArray

from heaton_life.ca import Cyclic, Generations, LifeLike, Wireworld
from heaton_life.ca._advance import AdvanceRegion
from heaton_life.ca.hashlife import StepCanceled
from heaton_life.init import soup

SIZE = 160
REGION = (20, 30, 120, 110)


def _life() -> LifeLike:
    return LifeLike("B3/S23", size=(SIZE, SIZE), init="soup", density=0.35, seed=11)


def _wire() -> Wireworld:
    states = soup((SIZE, SIZE), density=0.5, seed=12) + 2 * soup((SIZE, SIZE), density=0.5, seed=13)
    return Wireworld(size=(SIZE, SIZE), init=states, boundary="torus")


def _cyclic() -> Cyclic:
    return Cyclic(8, size=(SIZE, SIZE), threshold=2, reach=2, seed=14)


def _generations() -> Generations:
    # Star Wars: births and survival among live cells, dying states between.
    return Generations("B2/S345/C4", size=(SIZE, SIZE), init="soup", density=0.35, seed=15)


WORLDS: dict[str, Callable[[], AdvanceRegion]] = {
    "lifelike": _life,
    "wireworld": _wire,
    "cyclic": _cyclic,
    "generations": _generations,
}


def _state(world: AdvanceRegion) -> NDArray[np.uint8]:
    return world._state.copy()


def _advance(world: AdvanceRegion, n: int, *, outside: bool) -> None:
    (world.advance_outside if outside else world.advance_selection)(*REGION, n)


def _canceled_midway(world: AdvanceRegion, *, outside: bool) -> BaseException | None:
    """Start an advance far too long to finish on another thread, cancel it once a generation
    has run, and return what it raised."""
    started = threading.Event()
    step = world.step

    def watched(n: int = 1) -> None:
        started.set()
        step(n)

    world.step = watched  # type: ignore[method-assign]
    raised: list[BaseException] = []

    def run() -> None:
        try:
            _advance(world, 10**9, outside=outside)
        except BaseException as error:  # noqa: BLE001 - handed back to the test
            raised.append(error)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert started.wait(60), "the advance never began a generation"
    world.cancel()
    thread.join(60)
    assert not thread.is_alive(), "a canceled advance kept running"
    world.step = step  # type: ignore[method-assign]
    return raised[0] if raised else None


@pytest.mark.parametrize("outside", [False, True], ids=["selection", "outside"])
@pytest.mark.parametrize("family", WORLDS)
def test_a_cancel_from_another_thread_leaves_the_world_as_it_was(
    family: str, outside: bool
) -> None:
    world = WORLDS[family]()
    start = _state(world)
    world.step(3)
    before, generation = _state(world), world._generation
    error = _canceled_midway(world, outside=outside)
    assert isinstance(error, StepCanceled), error  # HashLife's: one except catches both
    assert np.array_equal(world._state, before)
    assert world._generation == generation
    world.reset()  # the start is untouched too
    assert np.array_equal(world._state, start)


@pytest.mark.parametrize("family", WORLDS)
def test_after_a_cancel_the_next_advance_runs_as_ever(family: str) -> None:
    canceled, fresh = WORLDS[family](), WORLDS[family]()
    assert isinstance(_canceled_midway(canceled, outside=False), StepCanceled)
    _advance(canceled, 4, outside=False)
    _advance(fresh, 4, outside=False)
    assert np.array_equal(canceled._state, fresh._state)
    assert canceled._generation == fresh._generation == 0


@pytest.mark.parametrize("family", WORLDS)
def test_a_cancel_before_an_advance_is_forgotten(family: str) -> None:
    """As with HashLife's step, an advance starts by forgetting an earlier request."""
    asked, fresh = WORLDS[family](), WORLDS[family]()
    asked.cancel()
    _advance(asked, 3, outside=True)
    _advance(fresh, 3, outside=True)
    assert np.array_equal(asked._state, fresh._state)


@pytest.mark.parametrize("outside", [False, True], ids=["selection", "outside"])
@pytest.mark.parametrize("family", WORLDS)
def test_an_uncanceled_advance_is_unchanged(family: str, outside: bool) -> None:
    """Spelled out from spec/patterns.md: isolate a copy, run it, take back what advanced."""
    world, copy = WORLDS[family](), WORLDS[family]()
    before = _state(world)
    x0, y0, x1, y1 = REGION
    region = (slice(y0, y1 + 1), slice(x0, x1 + 1))
    isolated = before.copy()
    if outside:
        isolated[region] = 0
    else:
        isolated[:] = 0
        isolated[region] = before[region]
    copy.set_state(isolated)  # type: ignore[attr-defined]
    copy.step(6)
    expected = copy._state.copy() if outside else before.copy()
    if outside:
        expected[region] = before[region]
    else:
        expected[region] = copy._state[region]
    _advance(world, 6, outside=outside)
    assert np.array_equal(world._state, expected)
    assert world._generation == 0
