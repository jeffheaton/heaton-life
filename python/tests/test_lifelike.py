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


# -- every rule runs through its table (spec/lifelike.md, spec/rules.md) ------------------------

_WEIGHT = {
    (-1, -1): 256,
    (0, -1): 128,
    (1, -1): 64,
    (-1, 0): 32,
    (0, 0): 16,
    (1, 0): 8,
    (-1, 1): 4,
    (0, 1): 2,
    (1, 1): 1,
}


def _noise_map(seed: int) -> str:
    from heaton_life.core.rng import Pcg32

    rng = Pcg32(seed, 0)
    bits = "".join(str(rng.next_u32() >> 31) for _ in range(512)) + "0000"
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    return "MAP" + "".join(alphabet[int(bits[i : i + 6], 2)] for i in range(0, 516, 6))


@pytest.mark.parametrize("boundary", ["torus", "dead"])
def test_each_cell_takes_the_table_entry_at_its_index(boundary: str) -> None:
    """Against a direct evaluation of an arbitrary table: a mirrored or rotated weight
    order would pass an isotropic rule but not this one."""
    from heaton_life.ca.rulestring import compile_rule

    rule = _noise_map(11)
    table = compile_rule(rule).table
    sim = LifeLike(rule, size=(13, 9), density=0.5, seed=3, boundary=boundary)  # type: ignore[arg-type]
    state = sim.state.copy()
    sim.step()
    h, w = state.shape
    expected = np.zeros_like(state)
    for y in range(h):
        for x in range(w):
            index = 0
            for (dx, dy), weight in _WEIGHT.items():
                yy, xx = y + dy, x + dx
                if boundary == "torus":
                    yy, xx = yy % h, xx % w
                elif not (0 <= yy < h and 0 <= xx < w):
                    continue
                index += weight * int(state[yy, xx])
            expected[y, x] = table[index]
    assert np.array_equal(sim.state, expected)


def test_rules_are_carried_canonical_in_any_notation() -> None:
    assert LifeLike("b2cekin/s12", size=(8, 8)).params.rule == "B2-a/S12"
    assert LifeLike("b2/s34h", size=(8, 8)).params.rule == "B2/S34H"
    assert LifeLike(_noise_map(2) + "==", size=(8, 8)).params.rule == _noise_map(2)


def test_b0_rules_run_as_written() -> None:
    """B0 on a torus: every dead cell without live neighbors is born at once."""
    sim = LifeLike("B0/S", size=(8, 8), init=np.zeros((8, 8), np.uint8))
    sim.step()
    assert sim.state.all()
    sim.step()  # B0/S has no survival: everything dies
    assert not sim.state.any()
