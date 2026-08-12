"""Behavior pins for the built-in pattern set (spec/patterns.md "Built-in
patterns"): the encodings must BE the objects they claim — stills stay,
oscillator periods hold, ships translate, the gun fires, the replicator
copies itself, the Wireworld clock keeps circulating, and the diode passes
electrons exactly one way."""

import numpy as np
import pytest
from numpy.typing import NDArray

from heaton_life.ca import LifeLike, Wireworld
from heaton_life.ca.wireworld import HEAD, TAIL
from heaton_life.init import BUILTIN_PATTERNS, BuiltinPattern, stamp


def builtin(name: str) -> BuiltinPattern:
    for pattern in BUILTIN_PATTERNS:
        if pattern.name == name:
            return pattern
    raise AssertionError(f"no built-in named {name}")


def stamped_life(rule: str, size: int, name: str, x: int, y: int) -> LifeLike:
    grid = np.zeros((size, size), dtype=np.uint8)
    stamp(grid, builtin(name).cells(), x, y, torus=True)
    return LifeLike(rule, size=(size, size), init=grid)


def stamped_wireworld(width: int, height: int, name: str, x: int, y: int) -> Wireworld:
    grid = np.zeros((height, width), dtype=np.uint8)
    stamp(grid, builtin(name).cells(), x, y, torus=False)
    return Wireworld(size=(width, height), init=grid, boundary="dead")


def translated_copy(before: NDArray[np.uint8], after: NDArray[np.uint8]) -> bool:
    """Is `after` exactly `before` translated by some nonzero toroidal offset?"""
    for dy in range(-4, 5):
        for dx in range(-4, 5):
            if (dy, dx) != (0, 0) and np.array_equal(np.roll(before, (dy, dx), (0, 1)), after):
                return True
    return False


def test_set_is_wellformed() -> None:
    names = [pattern.name for pattern in BUILTIN_PATTERNS]
    assert len(names) == len(set(names)), "duplicate built-in names"
    for pattern in BUILTIN_PATTERNS:
        cells = pattern.cells()
        assert cells.size > 0 and cells.max() > 0, f"{pattern.name} decodes empty"
        assert pattern.family in ("lifelike", "wireworld")


@pytest.mark.parametrize("name", ["Block", "Beehive", "Loaf"])
def test_stills_stay(name: str) -> None:
    world = stamped_life("B3/S23", 32, name, 12, 12)
    initial = world.state.copy()
    world.step(2)
    assert np.array_equal(world.state, initial), f"{name} is not a still life"


@pytest.mark.parametrize(
    ("name", "period"),
    [("Blinker", 2), ("Toad", 2), ("Beacon", 2), ("Pulsar", 3), ("Pentadecathlon", 15)],
)
def test_oscillator_periods_hold(name: str, period: int) -> None:
    world = stamped_life("B3/S23", 48, name, 18, 18)
    initial = world.state.copy()
    world.step(1)
    assert not np.array_equal(world.state, initial), f"{name} is static"
    world.step(period - 1)
    assert np.array_equal(world.state, initial), f"{name} period is not {period}"


@pytest.mark.parametrize(
    "name",
    ["Glider", "Lightweight spaceship", "Middleweight spaceship", "Heavyweight spaceship"],
)
def test_ships_translate(name: str) -> None:
    world = stamped_life("B3/S23", 48, name, 20, 20)
    initial = world.state.copy()
    world.step(4)
    assert translated_copy(initial, world.state), f"{name} did not travel"


def test_gosper_gun_fires() -> None:
    world = stamped_life("B3/S23", 80, "Gosper glider gun", 4, 4)
    before = int(np.count_nonzero(world.state))
    world.step(120)
    assert int(np.count_nonzero(world.state)) > before + 10, "gun did not fire"


def test_highlife_replicator_replicates() -> None:
    world = stamped_life("B36/S23", 48, "Replicator (HighLife)", 20, 20)
    before = int(np.count_nonzero(world.state))
    world.step(12)
    assert int(np.count_nonzero(world.state)) == 2 * before, "replicator did not replicate"


def test_wireworld_clock_keeps_ticking() -> None:
    wire = stamped_wireworld(14, 9, "Clock", 3, 3)
    wire.step(100)
    assert int((wire.state == HEAD).sum()) > 0, "clock died"


def test_wireworld_diode_is_one_way() -> None:
    # Electrons pass rightward…
    wire = stamped_wireworld(20, 9, "Diode (passes right)", 6, 3)
    grid = wire.state.copy()
    grid[4, 6] = TAIL
    grid[4, 7] = HEAD
    wire = Wireworld(size=(20, 9), init=grid, boundary="dead")
    passed = False
    for _ in range(10):
        wire.step(1)
        passed = passed or bool((wire.state[4, 11:14] == HEAD).any())
    assert passed, "diode blocked the forward electron"
    # …and die leftward.
    wire = stamped_wireworld(20, 9, "Diode (passes right)", 6, 3)
    grid = wire.state.copy()
    grid[4, 13] = TAIL
    grid[4, 12] = HEAD
    wire = Wireworld(size=(20, 9), init=grid, boundary="dead")
    wire.step(10)
    assert int((wire.state == HEAD).sum()) == 0, "diode passed a reverse electron"
