"""History rules (spec/history.md): seven states over any Life-like rule. The on cells must
run the base rule exactly, on every neighborhood and topology; the other states follow
history.md's table; boundary cells keep their neighbors off; and the rule reads, writes
and runs on grids, in RLE and on the unbounded plane (the multi-state universe)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from heaton_life.ca import LifeLike
from heaton_life.ca import history as hist
from heaton_life.ca.hashlife import HashLife, read_universe
from heaton_life.ca.hashlife.multistate import MultiStateHashLife, read_multistate_universe
from heaton_life.ca.rulestring import compile_rule, try_compile_rule
from heaton_life.ca.state_rules import state_rule
from heaton_life.core.topology import Halo, Topology
from heaton_life.init import measure_pattern, read_pattern, rle_decode, rle_encode, soup

RULES = ["B3/S23History", "B36/S23History", "B2/S34HHistory", "B2/S013VHistory"]
RULES += [
    "B3/S2-i34qHistory",
    "MAPARYXfhZofugWaH7oaIDogBZofuhogOiA6IDogIAAgAAWaH7oaIDogGiA6ICAAIAAaIDogIAAgACAAIAAAAAAAAHistory",
]
TOPOLOGIES = [("dead", 0, "x"), ("torus", 0, "x"), ("torus", 3, "y"), ("klein", 0, "x")]
TOPOLOGIES += [("cross", 0, "x"), ("sphere", 0, "x")]


# -- the rule ----------------------------------------------------------------------------


def test_the_states_are_named_as_the_spec_names_them() -> None:
    """spec/history.md "States": the names are the table's (the .NET port's History.Names
    pins the same table)."""
    assert hist.NAMES == _spec_state_names("history.md")
    assert len(hist.NAMES) == hist.STATES


def test_history_rules_compile_only_where_variants_are_asked_for() -> None:
    rule = compile_rule("b36 / s23history", variants=True)
    assert (rule.canonical, rule.variant, rule.states) == ("B36/S23History", "History", 7)
    assert rule.base == compile_rule("B36/S23")
    assert rule.table == compile_rule("B36/S23").table
    assert compile_rule("LifeHistory", variants=True).canonical == "B3/S23History"
    assert compile_rule(" LIFEHISTORY ", variants=True).canonical == "B3/S23History"
    assert compile_rule("B2/S34hhistory", variants=True).canonical == "B2/S34HHistory"
    assert compile_rule("B3/S23", variants=True).variant == ""  # a two-state rule is its base
    for text in ("B3/S23History", "LifeHistory", "MAP" + "A" * 86 + "History"):
        assert try_compile_rule(text) == (None, "a History rule has 7 states, not 2")
    assert try_compile_rule("B3/S23Histor", variants=True)[1] == (
        "unexpected 'Histor' after the survival counts"
    )
    # No MAP payload length less the word's 7 is another payload length, so a payload that
    # ends in "History" is read one way only.
    plain = compile_rule("MAP" + "A" * 79 + "History", variants=True)
    assert plain.variant == "" and plain.neighborhood == "moore"
    for stem in ("A" * 86, "A" * 22, "A" * 6):
        rule = compile_rule("MAP" + stem + "==History", variants=True)
        assert rule.variant == "History" and rule.canonical.endswith("History")


def test_the_same_base_and_converting_cells() -> None:
    history = compile_rule("B3/S23History", variants=True)
    life = compile_rule("B3/S23")
    assert history.same_base(life) and life.same_base(history)
    assert history.same_base(compile_rule("MAP" + _map_of(life.table), variants=True))
    assert not history.same_base(compile_rule("B36/S23"))
    cells = np.array([[0, 1, 2, 3, 4, 5, 6, 9, 12]])
    assert history.convert_cells(cells).tolist() == [[0, 1, 2, 3, 4, 5, 6, 1, 0]]
    assert life.convert_cells(cells).tolist() == [[0, 1, 0, 1, 0, 1, 0, 1, 0]]
    with pytest.raises(ValueError):
        life.convert_cells(np.array([[-1]]))


def _map_of(table: bytes) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    bits = [*table, 0, 0, 0, 0]
    return "".join(alphabet[int("".join(map(str, bits[i : i + 6])), 2)] for i in range(0, 516, 6))


# -- the evolution -------------------------------------------------------------------------


@pytest.mark.parametrize("rule_text", RULES)
def test_the_grid_step_is_the_cell_function(rule_text: str) -> None:
    """The vectorized step and the multi-state universe's cell function agree on random
    blocks of every state, under every topology."""
    rule = compile_rule(rule_text, variants=True)
    cell = hist.HistoryRule(rule)
    rng = np.random.default_rng(7)
    for boundary, shift, axis in TOPOLOGIES:
        cells = rng.integers(0, 7, size=(10, 10)).astype(np.uint8)
        halo = Halo(Topology(boundary, shift, axis), 10, 10)  # type: ignore[arg-type]
        got = hist.step(cells, halo, rule)
        padded = halo.fill(cells)
        for y in range(10):
            for x in range(10):
                block = [int(v) for v in padded[y : y + 3, x : x + 3].reshape(-1)]
                assert got[y, x] == cell.next_state(*block), (boundary, x, y)


@pytest.mark.parametrize("rule_text", RULES)
@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_on_cells_run_the_base_rule(rule_text: str, topology: tuple[str, int, str]) -> None:
    boundary, shift, axis = topology
    size = (24, 24)
    rule = compile_rule(rule_text, variants=True)
    kw = {"boundary": boundary, "shift": shift, "axis": axis}
    two = LifeLike(rule.base.canonical, size=size, seed=5, **kw)  # type: ignore[arg-type]
    seven = LifeLike(rule.canonical, size=size, seed=5, **kw)  # type: ignore[arg-type]
    assert np.array_equal(two.state, seven.state)  # the base rule's soup: states 0 and 1
    for _ in range(30):
        two.step()
        seven.step()
        assert np.array_equal(seven.state & 1, two.state)
        assert int(seven.state.max()) <= 2  # no marks appear by themselves


def test_each_state_changes_as_the_table_says() -> None:
    """history.md "Evolution": a still block of marked and start-on cells, a dying cell of
    each on state, and a birth into each off state."""
    w = LifeLike("B3/S23History", size=(16, 8), init=np.zeros((8, 16), np.uint8), boundary="dead")
    cells = np.zeros((8, 16), np.uint8)
    cells[1:3, 1:3] = [[3, 5], [1, 3]]  # a block: every cell survives as it is
    cells[5, 1], cells[5, 4], cells[5, 7] = 1, 3, 5  # lone on cells die: 2, 4, 4
    cells[1, 10], cells[1, 11], cells[1, 12] = 1, 1, 1  # a blinker over envelope and marks
    cells[0, 11], cells[2, 11] = 2, 4
    w.set_state(cells)
    w.step()
    s = w.state
    assert s[1:3, 1:3].tolist() == [[3, 5], [1, 3]]
    assert (s[5, 1], s[5, 4], s[5, 7]) == (2, 4, 4)
    assert (s[0, 11], s[1, 11], s[2, 11]) == (1, 1, 3)  # born into 2 and 4: 1 and 3
    assert (s[1, 10], s[1, 12]) == (2, 2)
    w.step()
    s = w.state
    assert (s[0, 11], s[2, 11]) == (2, 4)  # dying again: envelope, and marked off
    assert s[1, 10] == 1 and s[1, 12] == 1  # born again from the envelope


def test_a_start_on_cell_never_comes_back() -> None:
    w = LifeLike("B3/S23History", size=(8, 8), init=np.zeros((8, 8), np.uint8), boundary="dead")
    cells = np.zeros((8, 8), np.uint8)
    cells[3, 2:5] = [5, 5, 5]  # a blinker of start-on cells
    w.set_state(cells)
    w.step()
    assert w.state[2:5, 3].tolist() == [1, 5, 1] and w.state[3, 2] == 4 and w.state[3, 4] == 4
    w.step()
    # The ends died (4) and are born again marked (3), never start-on; the middle, alive
    # throughout, stays 5; the cell above, born from off, dies into the envelope.
    assert w.state[3, 2:5].tolist() == [3, 5, 3] and w.state[2, 3] == 2


def test_boundary_cells_keep_their_neighbors_off() -> None:
    """A boundary cell never changes, never counts, and every cell among its neighbors is off
    next generation: an on cell beside one dies, and an off cell is never born there."""
    w = LifeLike("B3/S23History", size=(9, 9), init=np.zeros((9, 9), np.uint8), boundary="dead")
    cells = np.zeros((9, 9), np.uint8)
    cells[4, 4] = 6
    cells[2, 2:4] = 1  # with (3, 3)… a block next to the boundary's corner
    cells[3, 2:4] = 1
    cells[6, 6:9] = 1  # a blinker whose middle cell's block holds no boundary cell
    w.set_state(cells)
    w.step()
    assert w.state[4, 4] == 6
    assert w.state[3, 3] == 2  # beside the boundary: dies though it has 3 neighbors
    assert w.state[2, 2] == 1  # out of the boundary's reach: the block's corner survives
    hex_world = LifeLike("B3/S23HHistory", size=(5, 5), init=np.zeros((5, 5), np.uint8))
    block = np.zeros((5, 5), np.uint8)
    block[2, 2] = 6
    block[1, 3] = 1  # NE of the boundary: no hexagonal neighbor of it
    block[0, 3], block[1, 4], block[0, 4] = 1, 1, 1
    hex_world.set_state(block)
    hex_world.step()
    assert hex_world.state[1, 3] == 1  # the boundary is no neighbor here, so it survives


def test_b0_history_runs_as_written_on_a_grid() -> None:
    w = LifeLike("B0/S8History", size=(6, 6), init=np.zeros((6, 6), np.uint8))
    cells = np.zeros((6, 6), np.uint8)
    cells[0, 0] = 6
    w.set_state(cells)
    w.step()
    assert w.state[0, 0] == 6
    assert int((w.state == 1).sum()) == 36 - 1 - 8  # all born but the boundary's ring
    with pytest.raises(ValueError, match="B0"):
        MultiStateHashLife("B0/S8History")


def test_history_cells_are_checked_and_framed_as_themselves() -> None:
    w = LifeLike("B3/S23History", size=(4, 3), init=np.arange(12, dtype=np.uint8).reshape(3, 4) % 7)
    assert w.states == 7 and w.rule.variant == "History"
    assert w.frame().tolist() == (np.arange(12).reshape(3, 4) % 7).tolist()
    with pytest.raises(ValueError, match="History"):
        w.set_state(np.full((3, 4), 7, np.uint8))
    plain = LifeLike("B3/S23", size=(4, 3), init=np.full((3, 4), 6, np.uint8))
    assert plain.states == 2 and plain.state.max() == 1  # nonzero is alive, as before
    w.fill_random(0, 0, 3, 2, density=0.5, seed=4)
    assert set(np.unique(w.state)) <= {0, 1}  # the two-state rule's soup


def test_advance_selection_keeps_states() -> None:
    w = LifeLike("B3/S23History", size=(20, 12), seed=2, boundary="klein")
    w.step(3)
    outside = w.state.copy()
    w.advance_selection(4, 3, 12, 8, 5)
    assert np.array_equal(w.state[:3], outside[:3])
    assert int(w.state.max()) <= 2 and w.generation == 3


# -- files -------------------------------------------------------------------------------


def test_rle_reads_and_writes_history() -> None:
    text = "x = 5, y = 3, rule = LifeHistory\n.ABA$CDEF.$2B!\n"
    cells, rule = rle_decode(text)
    assert rule == "LifeHistory"
    assert cells.tolist() == [[0, 1, 2, 1, 0], [3, 4, 5, 6, 0], [2, 2, 0, 0, 0]]
    written = rle_encode(cells, rule)
    assert written == "x = 5, y = 3, rule = B3/S23History\n.ABA$CDEF$2B!\n"
    assert rle_decode(written)[0].tolist() == cells.tolist()
    # Two-state letters under a History header: the file is extended, b and o still 0 and 1.
    assert rle_decode("x = 3, y = 1, rule = B3/S23History\nbob!\n")[0].tolist() == [[0, 1, 0]]
    assert rle_decode("x = 3, y = 1, rule = B3/S23History\nBOB!\n")[0].tolist() == [[2, 15, 2]]
    # A History world with only off and on cells writes two-state letters, as content says.
    life = rle_encode(np.array([[0, 1, 1]], np.uint8), "B36/S23History")
    assert life == "x = 3, y = 1, rule = B36/S23History\nb2o!\n"
    bounded = "#CXRLE Pos=-1,0 Gen=4\nx = 3, y = 1, rule = B3/S23History:T10,6\nFAB!\n"
    found = read_pattern(bounded)
    assert found.bounded_grid is not None and found.rule == "B3/S23History"
    assert int(found.cells.max()) == 6 and found.generation == 4
    extent = measure_pattern(bounded)
    assert not extent.two_state


def test_history_files_go_to_the_multi_state_universe() -> None:
    text = "#CXRLE Pos=-2,3 Gen=7\nx = 4, y = 2, rule = LifeHistory\nFFFF$.AB!\n"
    with pytest.raises(ValueError, match="extended"):
        read_universe(text)
    with pytest.raises(ValueError, match="History rule of 7 states"):
        HashLife("B3/S23History")
    with pytest.raises(ValueError, match="History"):
        read_universe(b"#Life 1.05\n#R B3/S23History\n*\n")
    u = read_multistate_universe(text.encode()).universe
    assert (u.rule, u.states, u.generation) == ("B3/S23History", 7, 7)
    assert u.get_rect(-2, 3, 1, 4).tolist() == [[6, 6, 6, 6], [0, 1, 2, 0]]
    again = MultiStateHashLife.from_macrocell(u.to_macrocell())
    assert again.to_macrocell() == u.to_macrocell() and again.rule == "B3/S23History"
    assert MultiStateHashLife.from_rle(u.to_rle()).to_macrocell() == u.to_macrocell()
    # Every spelling names the one rule.
    assert state_rule("lifehistory") is state_rule("B3/S23History")
    assert state_rule(" b3/s23HISTORY ").canonical == "B3/S23History"


def test_the_plane_agrees_with_a_grid_inside_a_wall() -> None:
    """A wall of boundary cells keeps everything inside it, so a dead-edged grid and the
    plane hold the same cells forever (spec/history.md "Evolution")."""
    for rule in ("B3/S23History", "B2/S34HHistory", "B2/S013VHistory"):
        grid = np.full((18, 22), 6, np.uint8)
        grid[1:-1, 1:-1] = soup((20, 16), density=0.4, seed=11)
        grid[4, 5], grid[9, 9], grid[12, 15] = 3, 4, 5
        u = MultiStateHashLife(rule)
        u.set_rect(-5, 7, grid)
        g = LifeLike(rule, size=(22, 18), init=grid, boundary="dead")
        for gen in (1, 2, 3, 10, 64, 200):
            u.step(gen - u.generation)
            g.step(gen - g.generation)
            assert np.array_equal(u.get_rect(-5, 7, 16, 24), g.state), (rule, gen)
            assert u.population == int(np.count_nonzero(g.state))


def test_random_fill_on_the_plane_is_the_two_state_universes() -> None:
    u = MultiStateHashLife("B3/S23History")
    u.fill_random(-7, 2, 12, 9, density=0.4, seed=5)
    two = HashLife()
    two.fill_random(-7, 2, 12, 9, density=0.4, seed=5)
    assert np.array_equal(u.get_rect(-7, 2, 12, 9), two.get_rect(-7, 2, 12, 9))
    with pytest.raises(ValueError, match="Life-like tool"):
        MultiStateHashLife("WireWorld").fill_random(0, 0, 1, 1, density=0.5, seed=1)


def test_a_life_pattern_pastes_into_history_and_back() -> None:
    life = compile_rule("B3/S23")
    history = compile_rule("LifeHistory", variants=True)
    glider = np.array([[0, 1, 0], [0, 0, 1], [1, 1, 1]], np.uint8)
    assert np.array_equal(history.convert_cells(glider), glider)  # unchanged
    marked = np.array([[2, 3, 4], [5, 6, 1]], np.uint8)
    assert life.convert_cells(marked).tolist() == [[0, 1, 0], [1, 0, 1]]


def _spec_state_names(page: str) -> tuple[str, ...]:
    """The Name column of a spec page's "## States" table, state n the n-th row."""
    text = (Path(__file__).resolve().parents[2] / "spec" / page).read_text(encoding="utf-8")
    table = text.split("## States", 1)[1].split("\n\n", 2)[1]
    rows = [line.split("|") for line in table.splitlines() if line.startswith("| ")]
    states = [row for row in rows if row[1].strip().isdigit()]
    assert [int(row[1]) for row in states] == list(range(len(states)))
    return tuple(row[2].strip() for row in states)
