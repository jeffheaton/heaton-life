"""Generations (spec/generations.md): the rule's two spellings, canonical form and reasons;
the grid family against a cell-by-cell oracle on every topology and against Life at C = 2;
editing; RLE's two-letter tags; and the unbounded plane (multi-state HashLife), with the
two-state HashLife refusing Generations rules."""

from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import NDArray

from heaton_life.ca import Generations, GenerationsParams, LifeLike
from heaton_life.ca.generations import (
    GenerationsRule,
    compile_generations_rule,
    try_compile_generations_rule,
)
from heaton_life.ca.hashlife import HashLife, MultiStateHashLife
from heaton_life.ca.state_rules import state_rule
from heaton_life.core.topology import Halo, Topology
from heaton_life.init import read_pattern, rle_decode, rle_encode
from heaton_life.init.patterns import compatible


def _states(height: int, width: int, states: int, seed: int) -> NDArray[np.uint8]:
    """Incompressible test input from an integer hash (simulation randomness stays PCG32)."""
    v = (
        np.arange(height * width, dtype=np.uint64) * np.uint64(0x9E3779B1) + np.uint64(seed)
    ) & np.uint64(0xFFFFFFFF)
    v ^= v >> np.uint64(15)
    v = (v * np.uint64(0x85EBCA6B)) & np.uint64(0xFFFFFFFF)
    v ^= v >> np.uint64(13)
    return ((v >> np.uint64(5)) % np.uint64(states)).astype(np.uint8).reshape(height, width)


def _oracle_step(
    state: NDArray[np.uint8], rule: GenerationsRule, topology: Topology
) -> NDArray[np.uint8]:
    """One generation cell by cell through the rule's cell function, the halo giving the
    block past the edges: independent of the family's vectorized step."""
    height, width = state.shape
    padded = Halo(topology, width, height).fill(state)
    out = np.zeros_like(state)
    for y in range(height):
        for x in range(width):
            b = padded[y : y + 3, x : x + 3]
            out[y, x] = rule.next_state(
                b[0, 0], b[0, 1], b[0, 2], b[1, 0], b[1, 1], b[1, 2], b[2, 0], b[2, 1], b[2, 2]
            )
    return out


# -- rules ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "canonical", "states"),
    [
        ("345/2/4", "B2/S345/C4", 4),
        ("B2/S345/C4", "B2/S345/C4", 4),
        ("/2/3", "B2/S/C3", 3),
        (" b2/s/c3\t", "B2/S/C3", 3),
        ("B2/S/C003", "B2/S/C3", 3),
        ("23/3/2", "B3/S23/C2", 2),
        ("332/33/5", "B3/S23/C5", 5),
        ("B2a/S23/C5", "B2a/S23/C5", 5),
        ("B2/S34H/C5", "B2/S34H/C5", 5),
        ("B1/S1V/C256", "B1/S1V/C256", 256),
        ("B2/S345 / c4", "B2/S345/C4", 4),
    ],
)
def test_both_spellings_compile_to_one_canonical_form(
    text: str, canonical: str, states: int
) -> None:
    rule = compile_generations_rule(text)
    assert (rule.canonical, rule.states) == (canonical, states)
    assert compile_generations_rule(rule.canonical) == rule
    assert state_rule(text) == rule


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("B3/S23", "expected '/C' and the number of states at the end"),
        ("B3/S23/C1", "a Generations rule has 2 to 256 states"),
        ("B3/S23/C257", "a Generations rule has 2 to 256 states"),
        ("B3/S23/C0000000000000000000003000", "a Generations rule has 2 to 256 states"),
        ("B9/S/C3", "expected '/' after the birth counts"),
        ("life/C3", "expected B…/S… or MAP…"),
    ],
)
def test_refusals_carry_their_reason(text: str, reason: str) -> None:
    assert try_compile_generations_rule(text) == (None, reason)
    with pytest.raises(ValueError, match="invalid Generations rule") as raised:
        compile_generations_rule(text)
    assert reason in str(raised.value)
    with pytest.raises(TypeError):
        compile_generations_rule(3)  # type: ignore[arg-type]


def test_the_cell_function_follows_the_spec_table() -> None:
    rule = compile_generations_rule("B2/S23/C5")
    f = rule.next_state
    assert f(1, 1, 0, 0, 0, 0, 0, 0, 0) == 1  # born of two live neighbors
    assert f(2, 2, 0, 0, 0, 0, 0, 0, 0) == 0  # dying neighbors are dead ones
    assert f(1, 1, 0, 0, 1, 0, 0, 0, 0) == 1  # survives with two
    assert f(0, 0, 0, 0, 1, 0, 0, 0, 0) == 2  # starts dying
    assert [f(1, 1, 1, 1, s, 1, 1, 1, 1) for s in (2, 3, 4)] == [3, 4, 0]
    assert compile_generations_rule("B3/S23/C2").next_state(0, 0, 0, 0, 1, 0, 0, 0, 0) == 0


# -- the grid ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule", "topology"),
    [
        ("B2/S/C3", Topology("torus")),
        ("B2/S345/C4", Topology("dead")),
        ("B2/S34H/C5", Topology("klein", 0, "y")),
        ("B1/S1V/C4", Topology("cross")),
        ("B2-a/S12/C7", Topology("sphere")),
        ("B01/S1/C4", Topology("torus", 3, "x")),
    ],
)
def test_a_step_is_the_cell_function_everywhere(rule: str, topology: Topology) -> None:
    compiled = compile_generations_rule(rule)
    start = _states(14, 14, compiled.states, 7)
    g = Generations(
        rule,
        size=(14, 14),
        init=start,
        boundary=topology.boundary,
        shift=topology.shift,
        axis=topology.axis,  # type: ignore[arg-type]
    )
    expect = start
    for _ in range(6):
        expect = _oracle_step(expect, compiled, topology)
        g.step()
        assert np.array_equal(g.state, expect), (rule, g.generation)


def test_two_states_is_life() -> None:
    g = Generations("B36/S23/C2", size=(40, 30), density=0.4, seed=3)
    life = LifeLike("B36/S23", size=(40, 30), density=0.4, seed=3)
    for n in (1, 5, 30):
        g.step(n)
        life.step(n)
        assert np.array_equal(g.state, life.state)


def test_a_dying_cell_takes_its_count_to_die() -> None:
    g = Generations("B2/S/C6", size=(8, 8), init=np.zeros((8, 8), np.uint8), boundary="dead")
    cells = np.zeros((8, 8), np.uint8)
    cells[4, 4] = 3
    g.set_state(cells)
    for state in (4, 5):  # 3, then 4 and 5
        g.step()
        assert g.state[4, 4] == state and g.state.sum() == state
    g.step()
    assert g.state.sum() == 0


def test_params_frames_and_state_checks() -> None:
    g = Generations("345/2/4", size=(16, 12), density=0.5, seed=4, boundary="klein", axis="y")
    p = g.params
    assert p.rule == "B2/S345/C4" and g.states == 4 and g.topology == Topology("klein", 0, "y")
    again = Generations.from_params(GenerationsParams.from_dict(p.to_dict()))
    assert np.array_equal(again.state, g.state)
    cells = np.array([[0, 1, 2, 3]], np.uint8)
    small = Generations("B2/S345/C4", size=(4, 1), init=cells, boundary="dead")
    assert small.frame().tolist() == [[0, 255, 170, 85]]
    with pytest.raises(ValueError, match="0 to 3"):
        small.set_state(np.array([[0, 4, 0, 0]], np.uint8))
    small.step(2)
    small.set_state(np.array([[1, 0, 0, 0]], np.uint8), 9, keep_start=True)
    small.reset()
    assert small.state.tolist() == [[0, 1, 2, 3]] and small.generation == 0
    many = Generations("B3/S23/C256", size=(3, 1), init=np.array([[1, 128, 255]], np.uint8))
    assert many.frame().tolist() == [[255, 128, 1]]


def test_editing_tools() -> None:
    g = Generations("B2/S/C3", size=(20, 16), density=0.0, seed=0, boundary="dead")
    g.fill_random(2, 3, 13, 10, 0.4, 11)
    assert set(np.unique(g.state)) <= {0, 1} and g.state[3:11, 2:14].sum() > 0
    life = LifeLike("B3/S23", size=(20, 16), density=0.0)
    life.fill_random(2, 3, 13, 10, 0.4, 11)
    assert np.array_equal(g.state, life.state)
    start = _states(16, 20, 3, 5)
    g.set_state(start)
    whole = Generations("B2/S/C3", size=(20, 16), init=start, boundary="dead")
    g.advance_selection(0, 0, 19, 15, 4)
    whole.step(4)
    assert np.array_equal(g.state, whole.state) and g.generation == 0
    g.clear_rect(0, 0, 4, 4)
    assert g.state[:5, :5].sum() == 0
    assert compatible("generations", "generations", np.array([[3]], np.uint8), 3) is not None
    assert compatible("generations", "generations", np.array([[2]], np.uint8), 3) is None


# -- RLE ----------------------------------------------------------------------------------------


def test_every_state_round_trips_through_rle() -> None:
    grid = np.arange(256, dtype=np.uint8).reshape(16, 16)
    text = rle_encode(grid, "/2/256")
    assert "rule = B2/S/C256" in text and "yO" in text and "pA" in text
    cells, rule = rle_decode(text)
    assert rule == "B2/S/C256" and np.array_equal(cells, grid)
    file = read_pattern(text.encode())
    g = Generations(file.rule or "", size=(16, 16), init=file.cells, boundary="dead")
    assert g.states == 256


@pytest.mark.parametrize("body", ["pZ!", "yP!", "p!", "p3A!", "zA!"])
def test_a_broken_two_letter_tag_is_refused(body: str) -> None:
    with pytest.raises(ValueError, match="unsupported RLE tag"):
        rle_decode(f"x = 1, y = 1, rule = B2/S/C256\n{body}")


@pytest.mark.parametrize("body", ["2p A!", "2p\nA!"])
def test_whitespace_inside_a_two_letter_tag_is_ignored(body: str) -> None:
    text = f"x = 2, y = 1, rule = B2/S/C256\n{body}"
    assert rle_decode(text)[0].tolist() == [[25, 25]]
    assert MultiStateHashLife.from_rle(text).get_rect(0, 0, 1, 0).tolist() == [[25, 25]]


# -- the unbounded plane -------------------------------------------------------------------------


@pytest.mark.parametrize("rule", ["B2/S345/C4", "/2/3", "B3/S23/C9", "B2/S34H/C5"])
def test_the_plane_agrees_with_the_grid_while_the_pattern_stays_inside(rule: str) -> None:
    compiled = compile_generations_rule(rule)
    grid = np.zeros((60, 60), np.uint8)
    grid[22:38, 22:38] = _states(16, 16, compiled.states, 9)
    g = Generations(rule, size=(60, 60), init=grid, boundary="dead")
    u = MultiStateHashLife(rule)
    u.set_rect(-17, 40, grid)
    for n in (1, 2, 4, 8, 6):  # to generation 21: the pattern can't reach the edge
        g.step(n)
        u.step(n)
        assert np.array_equal(u.get_rect(-17, 40, 42, 99), g.state), (rule, u.generation)
        assert u.population == int(np.count_nonzero(g.state))


def test_the_two_state_universe_refuses_generations_rules() -> None:
    for text in ("B2/S345/C4", "345/2/4", "B3/S23/C2"):
        with pytest.raises(ValueError, match="Generations rule"):
            HashLife(text)
    u = HashLife()
    with pytest.raises(ValueError, match="MultiStateHashLife"):
        u.rule = "/2/3"
    with pytest.raises(ValueError, match="background would change"):
        MultiStateHashLife("B0/S/C3")
    assert MultiStateHashLife("345/2/4").rule == "B2/S345/C4"
