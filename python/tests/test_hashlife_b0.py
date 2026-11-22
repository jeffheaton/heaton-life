"""Rules with B0 on the unbounded plane (spec/hashlife.md "Rules with B0", spec/rules.md
"B0 and the background"): the universe holds the cells that differ from the background,
B0 with Smax runs as its black/white reversal, and B0 without Smax alternates two phase
tables with every step of two or more generations at an even start. Checked against a
torus, which runs the rule on the plane's own cells, for every rule form."""

from __future__ import annotations

import gzip
import random
from pathlib import Path

import numpy as np
import pytest

from heaton_life.ca import LifeLike
from heaton_life.ca.hashlife import (
    HashLife,
    LifeView,
    read_timeline,
    read_universe,
    write_timeline,
)
from heaton_life.ca.rulestring import compile_rule
from heaton_life.init import measure_pattern, read_pattern, soup

_BASE64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def _map_rule(seed: int, *, smax: bool) -> str:
    """A MAP rule with a random table that has B0, with or without Smax."""
    rnd = random.Random(seed)
    bits = [rnd.random() < 0.3 for _ in range(512)]
    bits[0], bits[511] = True, smax
    bits += [False] * 4  # the last character's four unused bits
    chars = (int("".join("1" if b else "0" for b in bits[i : i + 6]), 2) for i in range(0, 516, 6))
    return "MAP" + "".join(_BASE64[c] for c in chars)


# B0 without Smax (the phases alternate), then B0 with Smax (the reversal), in every form.
STROBING = [
    "B0/S",
    "B03/S23",
    "B01/S1",
    "B02a/S12-a",
    "B0/S2H",
    "B0/S013V",
    _map_rule(7, smax=False),
]
REVERSED = ["B0123478/S01234678", "B0/S8", "B01c/S8", "B0/S6H", "B0/S4V", _map_rule(8, smax=True)]
GLIDER = np.array([[0, 1, 0], [0, 0, 1], [1, 1, 1]], dtype=np.uint8)


def _soup_universe(rule: str, seed: int = 1, size: int = 16) -> HashLife:
    u = HashLife(rule)
    u.set_rect(-size // 2, -size // 2, soup((size, size), density=0.4, seed=seed))
    return u


def test_the_background_of_each_kind_of_rule() -> None:
    life = compile_rule("B3/S23")
    strobe = compile_rule("B03/S23")
    reversed_ = compile_rule("B0123478/S01234678")
    assert (life.has_b0, life.has_smax) == (False, False)
    assert (strobe.has_b0, strobe.has_smax) == (True, False)
    assert (reversed_.has_b0, reversed_.has_smax) == (True, True)
    assert compile_rule("B3/S238").has_smax and not compile_rule("B3/S238").has_b0
    for g in (0, 1, 2, 3, 2**64 + 1, 10**40):
        assert life.background(g) == 0
        assert reversed_.background(g) == 1  # alive from generation 0 on
        assert strobe.background(g) == g % 2
    assert strobe.background(np.int64(5)) == 1  # any integer type
    with pytest.raises(ValueError, match="negative"):
        strobe.background(-1)
    with pytest.raises(TypeError):
        strobe.background(1.0)  # type: ignore[arg-type]
    # Smax is the all-alive block's entry in every neighborhood: S6 hexagonal, S4 von Neumann.
    assert compile_rule("B0/S6H").has_smax and not compile_rule("B0/S5H").has_smax
    assert compile_rule("B0/S4V").has_smax and not compile_rule("B0/S3V").has_smax


@pytest.mark.parametrize("rule", STROBING + REVERSED)
def test_a_torus_runs_the_plane_the_universe_stands_for(rule: str) -> None:
    """spec/hashlife.md "Oracles": a torus big enough that nothing meets itself holds the
    plane's own cells, which are the universe's XOR the background."""
    compiled = compile_rule(rule)
    size, patch = 80, 12
    cells = soup((patch, patch), density=0.4, seed=3)
    u = HashLife(rule)
    u.set_rect(0, 0, cells)
    plane = np.zeros((size, size), np.uint8)
    off = (size - patch) // 2
    plane[off : off + patch, off : off + patch] = cells
    plane ^= np.uint8(compiled.background(0))  # with Smax, the plane is alive from the start
    torus = LifeLike(rule, size=(size, size), init=plane, boundary="torus")
    for _ in range(18):
        assert u.background == compiled.background(u.generation)
        view = u.get_rect(-off, -off, size - off - 1, size - off - 1)
        assert np.array_equal(view ^ np.uint8(u.background), np.asarray(torus.state))
        u.step(1)
        torus.step(1)


# The reversals of B2/S34H and B2/S013V: rules whose reversals are tame enough to jump.
@pytest.mark.parametrize("rule", ["B0123478/S01234678", "B01456/S012356H", "B02/S0134V"])
def test_b0_with_smax_runs_as_its_reversal(rule: str) -> None:
    table = compile_rule(rule).table
    reversal = bytes(1 - table[511 - i] for i in range(512))
    a = _soup_universe(rule, seed=5, size=20)
    b = HashLife(_map_of(reversal))
    b.set_rect(-10, -10, soup((20, 20), density=0.4, seed=5))
    for n in (1, 2, 7, 100, 2**40 + 3):
        a.step(n)
        b.step(n)
        assert a.background == 1
        assert a.population == b.population and a.bounding_box() == b.bounding_box()
        assert _nodes(a) == _nodes(b)


def _map_of(table: bytes) -> str:
    """A Moore MAP string writing ``table`` (every neighborhood's table is a Moore table)."""
    bits = [*table, 0, 0, 0, 0]
    chars = (int("".join(str(b) for b in bits[i : i + 6]), 2) for i in range(0, 516, 6))
    return "MAP" + "".join(_BASE64[c] for c in chars)


def _nodes(u: HashLife) -> list[str]:
    """The node lines of the universe's canonical Macrocell text: its cells alone."""
    return [line for line in u.to_macrocell().splitlines() if line[0] not in "[#"]


def test_life_and_its_reversal_agree_cell_for_cell() -> None:
    anti, life = HashLife("B0123478/S01234678"), HashLife("B3/S23")
    for u in (anti, life):
        u.set_rect(-1, -1, np.array([[0, 1, 1], [1, 1, 0], [0, 1, 0]], np.uint8))  # R-pentomino
    anti.step(1103)
    life.step(1103)
    assert anti.population == life.population == 116
    assert _nodes(anti) == _nodes(life)


@pytest.mark.parametrize("rule", ["B03/S23", "B0/S", "B01/S1", "B0/S2H", "B0123478/S01234678"])
def test_a_jump_is_its_single_generations(rule: str) -> None:
    for start in (0, 1, 2, 3):
        for n in (1, 2, 3, 5, 8, 13, 32, 37):
            jumped = _soup_universe(rule, seed=start + 7)
            stepped = _soup_universe(rule, seed=start + 7)
            jumped.step(start)
            stepped.step(start)
            jumped.step(n)
            for _ in range(n):
                stepped.step(1)
            assert jumped.generation == stepped.generation == start + n
            assert jumped.to_macrocell() == stepped.to_macrocell(), (rule, start, n)


def test_sub_steps_of_alternating_phases_start_at_even_generations() -> None:
    u = HashLife("B03/S23")
    for start in range(4):
        for n in range(70):
            u.set_generation(start)
            g = start
            for j in u._sub_steps(n):
                assert j == 0 or g % 2 == 0, (start, n)
                g += 1 << j
            assert g == start + n
    life = HashLife()
    life.set_generation(1)
    assert life._sub_steps(0b1011) == [0, 1, 3]  # every other rule: the bits of n
    anti = HashLife("B0123478/S01234678")
    anti.set_generation(1)
    assert anti._sub_steps(0b1011) == [0, 1, 3]  # the reversal never alternates


def test_a_tight_budget_changes_nothing() -> None:
    """spec/hashlife.md "Memory": sub-steps split under a small budget keep the parities."""
    roomy = HashLife("B03/S23")
    tight = HashLife("B03/S23")
    tight._store.budget = 1 << 20  # below the 10 MiB floor, so the store must collect and split
    for u in (roomy, tight):
        u.set_rect(-20, -20, soup((40, 40), density=0.45, seed=21))
        u.step(1)
        u.step(2**7 + 1)
    assert tight.collections > 0
    assert tight.to_macrocell() == roomy.to_macrocell()


def test_the_generation_and_the_rule_say_what_the_cells_stand_for() -> None:
    u = HashLife("B03/S23")
    u.set_rect(0, 0, GLIDER)
    u.step(3)
    assert (u.generation, u.background) == (3, 1)
    cells = _nodes(u)
    u.set_generation(4)  # the other parity: no cell of the universe changes
    assert (u.background, _nodes(u)) == (0, cells)
    u.set_generation(3)
    u.rule = "B0123478/S01234678"  # keeps the cells; the background is alive throughout
    assert (u.background, _nodes(u)) == (1, cells)
    u.rule = "B3/S23"
    assert (u.background, _nodes(u)) == (0, cells)


def test_editing_writes_the_universes_cells() -> None:
    """Where the background is alive a live cell of the universe is a dead cell of the
    plane: to give the plane's cell a state, set the universe's to that XOR background."""
    u = HashLife("B0/S")  # births on an empty block only: the background flips each generation
    u.step(1)
    assert (u.population, u.background) == (0, 1)
    u.set_cell(5, 5, 1)  # the plane's cell (5, 5) dies
    assert u.get_cell(5, 5) ^ u.background == 0
    u.step(1)
    # On the plane every live cell dies (B0/S keeps none), and (5, 5) stays dead: its eight
    # neighbors were alive, and only a cell whose block is empty is born.
    assert (u.population, u.background) == (0, 0)


def test_dilation_and_erosion() -> None:
    """B0/S runs as P₀ = "any live cell in the block" from a dead background and P₁ = "the
    whole block alive" from a live one: a single cell grows to its block and back."""
    u = HashLife("B0/S")
    u.set_cell(0, 0, 1)
    u.step(1)
    assert u.population == 9 and u.bounding_box() == (-1, -1, 1, 1)
    u.step(1)
    assert u.population == 1 and u.bounding_box() == (0, 0, 0, 0)
    u.step(2**64 + 1)
    assert u.population == 9 and u.background == 1


def test_advancing_part_of_the_universe_works_on_its_cells() -> None:
    """spec/hashlife.md "Rules with B0": the selection's cells after n generations are put
    back as they are; over a selection that holds everything, that is what step gives."""
    for rule in ("B03/S23", "B0123478/S01234678"):
        u = _soup_universe(rule, seed=9, size=12)
        u.step(1)
        stepped = HashLife.from_macrocell(u.to_macrocell())
        stepped.step(5)
        u.advance_selection(-200, -200, 200, 200, 5)
        assert u.generation == 1
        assert _nodes(u) == _nodes(stepped)
        u.advance_outside(-200, -200, 200, 200, 3)  # the outside holds no cell to evolve
        assert _nodes(u) == _nodes(stepped)


@pytest.mark.parametrize("rule", ["B03/S23", "B0123478/S01234678", "B0/S2H", "B01c/S8"])
def test_files_round_trip(rule: str, tmp_path: Path) -> None:
    for generation in (0, 1, 2, 5):
        u = _soup_universe(rule, seed=13, size=10)
        u.step(generation)
        mc, rle = u.to_macrocell(), u.to_rle()
        assert f"#R {u.rule}\n" in mc
        for again in (
            HashLife.from_macrocell(mc),
            HashLife.from_rle(rle),
            read_universe(mc.encode()).universe,
            read_universe(gzip.compress(rle.encode())).universe,
        ):
            assert again.rule == u.rule and again.generation == generation
            assert again.background == u.background
            assert again.to_macrocell() == mc
        for name in ("a.mc", "a.mc.gz", "a.rle"):
            u.save(tmp_path / name)
            assert HashLife.from_file(tmp_path / name).to_macrocell() == mc
        host = HashLife()
        found = host.read_snapshot(mc)
        assert found.rule == u.rule
        host.rule = found.rule
        host.restore(found.snapshot)
        assert host.to_macrocell() == mc


def test_a_timeline_of_alternating_phases_round_trips() -> None:
    u = _soup_universe("B03/S23", seed=17, size=8)
    frames = []
    for _ in range(4):
        frames.append(u.snapshot())
        u.step(3)  # frames at generations 0, 3, 6, 9: both parities
    text = write_timeline(u, frames)
    timeline = read_timeline(text)
    assert [f.generation for f in timeline.frames] == [0, 3, 6, 9]
    for frame, original in zip(timeline.frames, frames, strict=True):
        timeline.universe.restore(frame)
        u.restore(original)
        assert timeline.universe.to_macrocell() == u.to_macrocell()
        assert timeline.universe.background == frame.generation % 2


def test_a_b0_macrocell_file_measures_and_reads_into_a_grid() -> None:
    u = HashLife("B0123478/S01234678")
    u.set_rect(3, -4, GLIDER)
    mc = u.to_macrocell()
    extent = measure_pattern(mc)
    assert (extent.x, extent.y, extent.width, extent.height) == (3, -4, 3, 3)
    assert extent.rule == "B0123478/S01234678" and extent.two_state
    grid = read_pattern(mc)
    assert np.array_equal(grid.cells, GLIDER)  # the cells as written
    assert grid.rule == "B0123478/S01234678"


def test_frames_show_the_universes_cells() -> None:
    u = HashLife("B0/S")
    u.set_cell(0, 0, 1)
    u.step(1)  # the background is alive; the universe holds the dead block's nine cells
    frame = u.render(LifeView(-2, -3, 0), (5, 5))
    assert frame.sum() == 9 * 255 and frame[1:4, 1:4].min() == 255
