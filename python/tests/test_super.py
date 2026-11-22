"""Super rules (spec/super.md): 26 states over any Life-like rule. The on cells must run the
base rule exactly, on every neighborhood and topology; states 0–6 behave as History's; the
trails, the no-trail cells, the labels and a newborn's state follow super.md's tables; and
the rule reads, writes and runs on grids, in RLE and on the unbounded plane."""

from __future__ import annotations

import numpy as np
import pytest

from heaton_life.ca import LifeLike
from heaton_life.ca import super_rules as sup
from heaton_life.ca.hashlife import HashLife, read_universe
from heaton_life.ca.hashlife.multistate import MultiStateHashLife, read_multistate_universe
from heaton_life.ca.rulestring import compile_rule, try_compile_rule
from heaton_life.ca.state_rules import state_rule
from heaton_life.core.topology import Halo, Topology
from heaton_life.init import measure_pattern, read_pattern, rle_decode, rle_encode, soup

RULES = ["B3/S23Super", "B36/S23Super", "B2/S34HSuper", "B2/S013VSuper", "B3/S2-i34qSuper"]
RULES += [
    "MAPARYXfhZofugWaH7oaIDogBZofuhogOiA6IDogIAAgAAWaH7oaIDogGiA6ICAAIAAaIDogIAAgACAAIAAAAAAAASuper",
]
TOPOLOGIES = [("dead", 0, "x"), ("torus", 0, "x"), ("torus", 3, "y"), ("klein", 0, "x")]
TOPOLOGIES += [("cross", 0, "x"), ("sphere", 0, "x")]


def _states(height: int, width: int, seed: int, *, walls: bool = True) -> np.ndarray:
    """Random Super states (test input; simulation randomness stays PCG32), half the cells
    off; without ``walls`` no boundary cell."""
    rng = np.random.default_rng(seed)
    cells = rng.integers(0, 26, size=(height, width)).astype(np.uint8)
    cells[rng.random((height, width)) < 0.5] = 0
    if not walls:
        cells[cells == 6] = 0
    return cells


def _world(rule: str, cells: np.ndarray, boundary: str = "dead") -> LifeLike:
    height, width = cells.shape
    return LifeLike(rule, size=(width, height), init=cells, boundary=boundary)  # type: ignore[arg-type]


# -- the rule ----------------------------------------------------------------------------


def test_super_rules_compile_only_where_variants_are_asked_for() -> None:
    rule = compile_rule("b36 / s23super", variants=True)
    assert (rule.canonical, rule.variant, rule.states) == ("B36/S23Super", "Super", 26)
    assert rule.base == compile_rule("B36/S23") and rule.table == compile_rule("B36/S23").table
    assert compile_rule("LifeSuper", variants=True).canonical == "B3/S23Super"
    assert compile_rule(" lifesuper ", variants=True).canonical == "B3/S23Super"
    assert compile_rule("B2/S34hSUPER", variants=True).canonical == "B2/S34HSuper"
    for text in ("B3/S23Super", "LifeSuper", "MAP" + "A" * 86 + "Super"):
        assert try_compile_rule(text) == (None, "a Super rule has 26 states, not 2")
    assert try_compile_rule("B3/S23Supe", variants=True)[1] == (
        "unexpected 'Supe' after the survival counts"
    )
    # No MAP payload length less the word's 5 is another payload length, so a payload
    # that ends in "Super" is read one way only.
    plain = compile_rule("MAP" + "A" * 81 + "Super", variants=True)
    assert plain.variant == "" and plain.neighborhood == "moore"
    for stem in ("A" * 86, "A" * 22, "A" * 6):
        rule = compile_rule("MAP" + stem + "==super", variants=True)
        assert rule.variant == "Super" and rule.canonical.endswith("Super")


def test_the_same_base_and_converting_cells() -> None:
    life = compile_rule("B3/S23")
    history = compile_rule("LifeHistory", variants=True)
    superb = compile_rule("LifeSuper", variants=True)
    assert superb.same_base(life) and superb.same_base(history)
    assert not superb.same_base(compile_rule("B36/S23Super", variants=True))
    cells = np.array([[0, 1, 2, 5, 6, 7, 8, 9, 10, 14, 24, 25]], np.uint8)
    # A Super pattern under a two-state rule keeps its on cells; under a History rule
    # states 0–6 stay and the rest become their parity; a History pattern is a Super one.
    assert life.convert_cells(cells).tolist() == [[0, 1, 0, 1, 0, 1, 0, 1, 0, 0, 0, 1]]
    assert history.convert_cells(cells).tolist() == [[0, 1, 2, 5, 6, 1, 0, 1, 0, 0, 0, 1]]
    assert superb.convert_cells(cells).tolist() == cells.tolist()
    marks = np.array([[2, 3, 4], [5, 6, 1]], np.uint8)
    assert np.array_equal(superb.convert_cells(marks), marks)


# -- the evolution -------------------------------------------------------------------------


@pytest.mark.parametrize("rule_text", RULES)
def test_the_grid_step_is_the_cell_function(rule_text: str) -> None:
    """The vectorized step and the multi-state universe's cell function agree on random
    blocks of every state, under every topology."""
    rule = compile_rule(rule_text, variants=True)
    cell = sup.SuperRule(rule)
    for seed, (boundary, shift, axis) in enumerate(TOPOLOGIES):
        cells = _states(10, 10, seed)
        halo = Halo(Topology(boundary, shift, axis), 10, 10)  # type: ignore[arg-type]
        for _ in range(3):
            got = sup.step(cells, halo, rule)
            padded = halo.fill(cells)
            for y in range(10):
                for x in range(10):
                    block = [int(v) for v in padded[y : y + 3, x : x + 3].reshape(-1)]
                    assert got[y, x] == cell.next_state(*block), (boundary, x, y)
            cells = got


@pytest.mark.parametrize("rule_text", RULES)
@pytest.mark.parametrize("topology", TOPOLOGIES)
def test_on_cells_run_the_base_rule(rule_text: str, topology: tuple[str, int, str]) -> None:
    """Without boundary cells, which cells are on is the base rule's run, whatever the
    other states: trails, labels and newborns' states never change it."""
    boundary, shift, axis = topology
    rule = compile_rule(rule_text, variants=True)
    kw = {"boundary": boundary, "shift": shift, "axis": axis}
    start = _states(24, 24, 9, walls=False)
    two = LifeLike(rule.base.canonical, size=(24, 24), init=start & 1, **kw)  # type: ignore[arg-type]
    many = LifeLike(rule.canonical, size=(24, 24), init=start, **kw)  # type: ignore[arg-type]
    for _ in range(20):
        two.step()
        many.step()
        assert np.array_equal(many.state & 1, two.state)


@pytest.mark.parametrize("base", ["B3/S23", "B36/S23", "B2/S34H", "B2/S013V"])
def test_a_history_pattern_runs_as_under_the_history_rule(base: str) -> None:
    cells = _states(30, 30, 4) % 7
    cells[cells == 6] = 0
    cells[3:27:6, 4] = 6  # a few boundary cells
    history = _world(base + "History", cells)
    superb = _world(base + "Super", cells)
    for n in (1, 2, 5, 20):
        history.step(n)
        superb.step(n)
        assert np.array_equal(history.state, superb.state), (base, superb.generation)


def test_each_state_changes_as_the_table_says() -> None:
    """super.md "Evolution", by hand: deaths of every kind of on cell, a still block of
    mixed states, births into 4 and 8 and from mixed parents, and every label."""
    cells = np.zeros((12, 24), np.uint8)
    for x, state in zip((1, 4, 7, 10, 13, 16, 19, 22), (1, 3, 5, 7, 9, 11, 13, 25), strict=True):
        cells[1, x] = state  # lone on cells: each dies
    cells[4:6, 1:3] = [[7, 9], [13, 25]]  # a block: every cell survives as it is
    cells[5, 6:9] = 13  # a blinker of no-trail cells
    cells[4, 7], cells[6, 7] = 4, 8  # marked off cells above and below its middle
    cells[4, 12], cells[4, 15], cells[4, 18] = 14, 16, 24  # labels alone
    cells[7, 12:14] = [16, 1]  # a clearable label touched by an on cell
    cells[7, 16:18] = [24, 1]  # a hidden label touched by an on cell
    cells[7, 20:22] = [16, 14]  # a clearable label touched by a vanishing one
    cells[9, 12:15] = [18, 20, 22]  # the three cycling labels in a row
    w = _world("B3/S23Super", cells)
    w.step()
    s = w.state
    assert s[1, 1:23:3].tolist() == [2, 4, 4, 8, 10, 12, 0, 0]
    assert s[4:6, 1:3].tolist() == [[7, 9], [13, 25]]
    assert (s[4, 7], s[5, 7], s[6, 7]) == (3, 13, 7)  # born into 4 and 8: 3 and 7
    assert (s[5, 6], s[5, 8]) == (0, 0)  # the blinker's ends leave no trail
    assert (s[4, 12], s[4, 15], s[4, 18]) == (0, 16, 24)
    assert s[7, 12:14].tolist() == [14, 2]
    assert s[7, 16:18].tolist() == [18, 2]
    assert s[7, 20:22].tolist() == [14, 0]
    assert s[9, 12:15].tolist() == [18, 18, 20]  # 20 meets 18, 22 meets 20, 18 meets no 22
    w.step()
    s = w.state
    # The blinker turns back: its ends are born of parents 3, 13 and 7, which mix, so 1.
    assert (s[5, 6], s[5, 7], s[5, 8]) == (1, 13, 1)
    assert (s[4, 7], s[6, 7]) == (4, 8)  # the marked cells die marked
    assert s[9, 12:15].tolist() == [18, 18, 18]
    assert s[7, 12] == 0  # the vanishing label lasted one generation


def test_the_cycling_labels_chase_each_other() -> None:
    cells = np.zeros((3, 7), np.uint8)
    cells[1, 1:6] = [18, 22, 20, 18, 22]
    w = _world("B3/S23Super", cells)
    w.step()
    # 18 beside 22 becomes 22; 22 beside 20 becomes 20; 20 beside 18 becomes 18; the last
    # 22 has no 20 beside it and stays.
    assert w.state[1, 1:6].tolist() == [22, 20, 18, 22, 22]


@pytest.mark.parametrize(
    ("parents", "newborn"),
    [
        ((13, 13, 13), 13),
        ((15, 15, 3), 15),
        ((17, 3, 3), 17),
        ((9, 9, 9), 9),
        ((9, 9, 7), 9),
        ((11, 7, 7), 11),
        ((13, 15, 7), 13),
        ((15, 15, 7), 13),
        ((7, 7, 7), 13),
        ((11, 9, 7), 1),
        ((9, 9, 3), 1),
        ((13, 3, 7), 1),
        ((9, 9, 13), 1),
        ((3, 3, 3), 1),
        ((1, 1, 1), 1),
        ((5, 5, 5), 1),
        ((25, 25, 1), 1),
    ],
)
def test_a_newborn_takes_its_parents_state(parents: tuple[int, ...], newborn: int) -> None:
    """super.md "The newborn's state", for Life's three parents, into every off state the
    table above doesn't fix (0, the envelopes and the labels)."""
    rule = sup.SuperRule(compile_rule("B3/S23Super", variants=True))
    for target in (0, 2, 10, 12, 14, 16, 18, 20, 22, 24):
        block = [*parents, 0, target, 0, 0, 0, 0]  # the parents along the top row
        assert rule.next_state(*block) == newborn, (parents, target)
    assert sup.newborn(parents) == newborn


def test_newborns_of_other_parent_counts() -> None:
    two = sup.SuperRule(compile_rule("B2/SSuper", variants=True))
    for parents, newborn in [((13, 13), 13), ((13, 3), 13), ((9, 7), 9), ((13, 15), 13)]:
        assert two.next_state(*parents, 0, 0, 0, 0, 0, 0, 0) == newborn, parents
    for parents in [(13, 1), (3, 3), (9, 11)]:
        assert two.next_state(*parents, 0, 0, 0, 0, 0, 0, 0) == 1, parents
    assert two.next_state(7, 7, 0, 0, 0, 0, 0, 0, 0) == 13
    six = sup.SuperRule(compile_rule("B36/S23Super", variants=True))
    assert six.next_state(15, 15, 15, 15, 0, 15, 3, 0, 0) == 15
    assert six.next_state(9, 9, 7, 9, 0, 7, 9, 0, 0) == 9
    # A birth with no parents (B0) gives 1, as History's does.
    b0 = _world("B0/S8Super", np.zeros((5, 5), np.uint8))
    b0.step()
    assert int(b0.state.min()) == 1 and int(b0.state.max()) == 1


def test_boundary_cells_take_their_neighbors_away() -> None:
    cells = np.zeros((9, 16), np.uint8)
    cells[2, 2] = 6
    cells[1, 1:4] = [7, 9, 16]
    cells[2, 1], cells[2, 3] = 8, 25
    cells[3, 1:4] = [14, 11, 18]
    cells[1, 10] = 6  # a wall cell above where a blinker would give birth
    cells[3, 9:12] = 1
    w = _world("B3/S23Super", cells)
    w.step()
    s = w.state
    assert s[2, 2] == 6
    # Beside a boundary: 7, 8, no-trail cells and labels vanish; trails leave envelopes.
    assert s[1, 1:4].tolist() == [0, 10, 0] and (s[2, 1], s[2, 3]) == (0, 0)
    assert s[3, 1:4].tolist() == [0, 12, 0]
    # The blinker's cell beside the wall is never born; the one below it is.
    assert (s[2, 10], s[3, 10], s[4, 10]) == (0, 1, 1)
    hex_world = _world("B3/S23HSuper", np.zeros((5, 5), np.uint8))
    block = np.zeros((5, 5), np.uint8)
    block[2, 2], block[1, 3] = 16, 14  # NE of the label: no hexagonal neighbor of it
    hex_world.set_state(block)
    hex_world.step()
    assert hex_world.state[2, 2] == 16  # untouched, so still clearable


def test_super_cells_are_checked_and_framed_as_themselves() -> None:
    cells = (np.arange(26 * 2, dtype=np.uint8) % 26).reshape(4, 13)
    w = _world("B3/S23Super", cells)
    assert w.states == 26 and w.rule.variant == "Super"
    assert w.frame().tolist() == cells.tolist()
    with pytest.raises(ValueError, match="Super"):
        w.set_state(np.full((4, 13), 26, np.uint8))
    assert w.state.tolist() == cells.tolist()  # a refused state changes nothing
    w.fill_random(0, 0, 12, 3, density=0.5, seed=4)
    assert set(np.unique(w.state)) <= {0, 1}  # the two-state rule's soup


def test_advance_selection_keeps_states() -> None:
    w = _world("B3/S23Super", _states(12, 20, 2, walls=False), boundary="klein")
    w.step(3)
    outside = w.state.copy()
    w.advance_selection(4, 3, 12, 8, 5)
    assert np.array_equal(w.state[:3], outside[:3]) and w.generation == 3


# -- files -------------------------------------------------------------------------------


def test_rle_reads_and_writes_super() -> None:
    text = "x = 5, y = 2, rule = LifeSuper\nMpAH2.$oDbX!\n"
    cells, rule = rle_decode(text)
    assert rule == "LifeSuper"
    assert cells.tolist() == [[13, 25, 8, 0, 0], [1, 4, 0, 24, 0]]
    written = rle_encode(cells, rule)
    assert written == "x = 5, y = 2, rule = B3/S23Super\nMpAH$AD.X!\n"
    assert rle_decode(written)[0].tolist() == cells.tolist()
    assert rle_decode("x = 3, y = 1, rule = B3/S23Super\nBOB!\n")[0].tolist() == [[2, 15, 2]]
    bounded = "#CXRLE Pos=-1,0 Gen=4\nx = 3, y = 1, rule = B3/S23Super:T10,6\nFpAB!\n"
    found = read_pattern(bounded)
    assert found.bounded_grid is not None and found.rule == "B3/S23Super"
    assert int(found.cells.max()) == 25 and found.generation == 4
    assert not measure_pattern(bounded).two_state


def test_super_files_go_to_the_multi_state_universe() -> None:
    text = "#CXRLE Pos=-2,3 Gen=7\nx = 4, y = 2, rule = LifeSuper\nFFFF$.MpAX!\n"
    with pytest.raises(ValueError, match="extended"):
        read_universe(text)
    with pytest.raises(ValueError, match="Super rule of 26 states"):
        HashLife("B3/S23Super")
    with pytest.raises(ValueError, match="Super"):
        read_universe(b"#Life 1.05\n#R B3/S23Super\n*\n")
    u = read_multistate_universe(text.encode()).universe
    assert (u.rule, u.states, u.generation) == ("B3/S23Super", 26, 7)
    assert u.get_rect(-2, 3, 1, 4).tolist() == [[6, 6, 6, 6], [0, 13, 25, 24]]
    again = MultiStateHashLife.from_macrocell(u.to_macrocell())
    assert again.to_macrocell() == u.to_macrocell() and again.rule == "B3/S23Super"
    assert MultiStateHashLife.from_rle(u.to_rle()).to_macrocell() == u.to_macrocell()
    assert state_rule("lifesuper") is state_rule("B3/S23Super")
    with pytest.raises(ValueError, match="B0"):
        MultiStateHashLife("B0/S8Super")


def test_the_plane_agrees_with_a_grid_inside_a_wall() -> None:
    """A wall of boundary cells keeps everything inside it, so a dead-edged grid and the
    plane hold the same cells forever (spec/super.md "Evolution")."""
    for rule in ("B3/S23Super", "B2/S34HSuper", "B2/S013VSuper"):
        grid = np.full((18, 22), 6, np.uint8)
        grid[1:-1, 1:-1] = _states(16, 20, 11, walls=False)
        u = MultiStateHashLife(rule)
        u.set_rect(-5, 7, grid)
        g = LifeLike(rule, size=(22, 18), init=grid, boundary="dead")
        for gen in (1, 2, 3, 10, 64, 200):
            u.step(gen - u.generation)
            g.step(gen - g.generation)
            assert np.array_equal(u.get_rect(-5, 7, 16, 24), g.state), (rule, gen)
            assert u.population == int(np.count_nonzero(g.state))


@pytest.mark.parametrize("rule", ["B3/S23Super", "B2/S/C3", "B3/S23History"])
def test_random_fill_on_the_plane_is_the_two_state_universes(rule: str) -> None:
    u = MultiStateHashLife(rule)
    u.fill_random(-7, 2, 12, 9, density=0.4, seed=5)
    two = HashLife()
    two.fill_random(-7, 2, 12, 9, density=0.4, seed=5)
    assert np.array_equal(u.get_rect(-7, 2, 12, 9), two.get_rect(-7, 2, 12, 9))
    with pytest.raises(ValueError, match="Life-like tool"):
        MultiStateHashLife("WireWorld").fill_random(0, 0, 1, 1, density=0.5, seed=1)


def test_a_soup_runs_the_same_on_the_plane() -> None:
    cells = soup((24, 24), density=0.4, seed=3)
    u = MultiStateHashLife("LifeSuper")
    u.set_rect(0, 0, cells)
    two = HashLife()
    two.set_rect(0, 0, cells)
    u.step(37)
    two.step(37)
    box = two.bounding_box()
    assert box is not None
    x0, y0, x1, y1 = box
    assert np.array_equal(u.get_rect(x0, y0, x1, y1) & 1, two.get_rect(x0, y0, x1, y1))
