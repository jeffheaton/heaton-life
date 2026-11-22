"""Larger than Life (spec/ltl.md): the rule text, the neighborhoods, the counts and the
evolution checked against direct sums on every topology, the editing tools, files, and the
universes' refusals. The vectors in vectors/ltl/ and vectors/ltl-rules/ pin the same; these
tests check it independently."""

from __future__ import annotations

import itertools

import numpy as np
import pytest
from numpy.typing import NDArray

from heaton_life.ca import LargerThanLife, LifeLike, parse_ltl_rule, try_parse_ltl_rule
from heaton_life.ca.hashlife import HashLife, StepCanceled, read_universe
from heaton_life.ca.hashlife.multistate import MultiStateHashLife, read_multistate_universe
from heaton_life.ca.ltl import BOSCO, MAX_COUNT, LtlRule, counts, half_widths
from heaton_life.core import Halo, Topology
from heaton_life.init import compatible, read_pattern, rle_encode, soup

TOPOLOGIES = [
    Topology("dead"),
    Topology("torus"),
    Topology("torus", 3, "x"),
    Topology("klein", 0, "y"),
    Topology("klein", 1, "x"),
    Topology("cross"),
    Topology("sphere"),
]


def _mixed(width: int, height: int, states: int, seed: int) -> NDArray[np.uint8]:
    """A grid of every state, from PCG32 soups (alive state 1 the most common)."""
    cells = soup((width, height), density=0.5, seed=seed)
    if states > 2:
        aging = soup((width, height), density=0.4, seed=seed + 1)
        cells = np.where(
            aging == 1,
            (seed + np.arange(cells.size) % (states - 1)).reshape(cells.shape) % states,
            cells,
        )
    return cells.astype(np.uint8)


# -- the rule text ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "canonical"),
    [
        (BOSCO, BOSCO),
        ("5,34,45,34,58", BOSCO),
        ("r5,c2,m1,s34..58,b34..45", BOSCO),
        ("  R005,C00,M1,S034..58,B34..045,nm\t", BOSCO),
        ("R1,C3,M0,S2..3,B3..3,NC", "R1,C3,M0,S2..3,B3..3,NC"),
        ("R500,C256,M0,S0..1002001,B0..0,NN", "R500,C256,M0,S0..1002001,B0..0,NN"),
    ],
)
def test_a_rule_reads_and_writes_canonically(text: str, canonical: str) -> None:
    rule = parse_ltl_rule(text)
    assert rule.canonical == str(rule) == canonical
    assert parse_ltl_rule(canonical) == rule


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "expected R…,C…,M…,S…,B…,N… or five numbers r,bmin,bmax,smin,smax"),
        ("B3/S23", "expected R…,C…,M…,S…,B…,N… or five numbers r,bmin,bmax,smin,smax"),
        ("R5,C0,M1,S34..58", "expected the fields R, C, M, S, B and N, in that order"),
        ("R5,C0,M1,S1..2,B1..2,NM,X", "expected the fields R, C, M, S, B and N, in that order"),
        ("Rx,C0,M1,S1..2,B1..2", "expected R and the range, not 'Rx'"),
        ("R5,K0,M1,S1..2,B1..2", "expected C and the number of states, not 'K0'"),
        ("R5,C0,M2,S1..2,B1..2", "expected M0 or M1, not 'M2'"),
        ("R5,C0,M1,S1-2,B1..2", "expected S and a range of counts S<min>..<max>, not 'S1-2'"),
        ("R5,C0,M1,S1..2,B1", "expected B and a range of counts B<min>..<max>, not 'B1'"),
        ("R5,C0,M1,S1..2,B1..2,NX", "expected NM, NN or NC, not 'NX'"),
        ("R5, C0,M1,S1..2,B1..2", "expected C and the number of states, not ' C0'"),
        ("5,34,45,34", "expected five numbers r,bmin,bmax,smin,smax"),
        ("5,34,45,34,5x", "expected five numbers r,bmin,bmax,smin,smax"),
        ("R0,C0,M1,S1..2,B1..2", "the range is 1 to 500, not 0"),
        ("R501,C0,M1,S1..2,B1..2", "the range is 1 to 500, not 501"),
        ("R5,C1,M1,S1..2,B1..2", "C is 0 or 2 (two states) or 3 to 256, not 1"),
        ("R5,C257,M1,S1..2,B1..2", "C is 0 or 2 (two states) or 3 to 256, not 257"),
        ("R5,C0,M1,S1..1002002,B1..2", f"a count is at most {MAX_COUNT}"),
        ("R5,C0,M1,S9..2,B1..2", "S9..2 is empty"),
        ("R5,C0,M1,S1..2,B09..2", "B9..2 is empty"),
        ("R٥,C0,M1,S1..2,B1..2", "expected R and the range, not 'R٥'"),  # Arabic-Indic 5
    ],
)
def test_a_text_that_is_no_rule_says_why(text: str, reason: str) -> None:
    assert try_parse_ltl_rule(text) == (None, reason)
    with pytest.raises(ValueError) as error:
        parse_ltl_rule(text)
    assert str(error.value) == f"invalid Larger than Life rule '{text}': {reason} (spec/ltl.md)"


# -- the neighborhoods -------------------------------------------------------------------------


@pytest.mark.parametrize("radius", [*range(1, 13), 20, 50, 137, 500])
def test_each_neighborhood_holds_the_cells_the_spec_names(radius: int) -> None:
    r = radius
    for hood, inside in (
        ("moore", lambda dx, dy: abs(dx) <= r and abs(dy) <= r),
        ("vonneumann", lambda dx, dy: abs(dx) + abs(dy) <= r),
        ("circular", lambda dx, dy: dx * dx + dy * dy <= r * r + r),
    ):
        widths = half_widths(r, hood)  # type: ignore[arg-type]
        for dy, w in zip(range(-r, r + 1), widths, strict=True):
            assert inside(w, dy) and not inside(w + 1, dy), (hood, r, dy)
    assert sum(2 * w + 1 for w in half_widths(r, "moore")) == (2 * r + 1) ** 2
    assert sum(2 * w + 1 for w in half_widths(r, "vonneumann")) == 2 * r * (r + 1) + 1
    assert half_widths(1, "circular") == (1, 1, 1)  # at r = 1 the circle is the 3 × 3 box


def _direct_counts(
    cells: NDArray[np.uint8], rule: LtlRule, topology: Topology
) -> NDArray[np.int32]:
    """Each cell's count summed cell by cell over its neighborhood (spec/ltl.md), every
    point past an edge located through the topology."""
    height, width = cells.shape
    r = rule.range
    found = np.zeros((height, width), dtype=np.int32)
    offsets = [
        (dx, dy)
        for dy, w in zip(range(-r, r + 1), rule.half_widths, strict=True)
        for dx in range(-w, w + 1)
        if rule.middle or (dx, dy) != (0, 0)
    ]
    for y, x in itertools.product(range(height), range(width)):
        total = 0
        for dx, dy in offsets:
            cell = topology.locate(x + dx, y + dy, width, height)
            if cell is not None and cells[cell[1], cell[0]] == 1:
                total += 1
        found[y, x] = total
    return found


@pytest.mark.parametrize("topology", TOPOLOGIES, ids=repr)
@pytest.mark.parametrize("hood", ["M", "N", "C"])
def test_counts_equal_a_direct_sum_on_every_topology(topology: Topology, hood: str) -> None:
    for radius, middle, states in ((1, 0, 2), (2, 1, 4), (3, 0, 3)):
        rule = parse_ltl_rule(f"R{radius},C{states},M{middle},S0..1,B0..1,N{hood}")
        size = 2 * radius + 3
        width, height = (
            (size, size) if topology.boundary == "sphere" else (size + 3, size)
        )  # even: a shifted Klein bottle's twisted side
        topology.check(width, height)
        cells = _mixed(width, height, rule.states, seed=radius * 10 + middle)
        padded = Halo(topology, width, height, radius).fill(cells)
        assert np.array_equal(counts(padded, rule), _direct_counts(cells, rule, topology))


def _direct_step(cells: NDArray[np.uint8], rule: LtlRule, topology: Topology) -> NDArray[np.uint8]:
    found = _direct_counts(cells, rule, topology)
    (smin, smax), (bmin, bmax) = rule.survival, rule.birth
    out = np.zeros_like(cells)
    for (y, x), state in np.ndenumerate(cells):
        count = found[y, x]
        if state == 0:
            out[y, x] = 1 if bmin <= count <= bmax else 0
        elif state == 1:
            out[y, x] = 1 if smin <= count <= smax else (2 if rule.states > 2 else 0)
        else:
            out[y, x] = state + 1 if state + 1 < rule.states else 0
    return out


@pytest.mark.parametrize(
    "text",
    ["R2,C0,M1,S3..9,B4..6,NM", "R2,C5,M0,S2..7,B3..5,NN", "R3,C4,M1,S5..14,B6..9,NC"],
)
def test_a_generation_is_the_table_of_spec_ltl_md(text: str) -> None:
    rule = parse_ltl_rule(text)
    for topology in (Topology("torus"), Topology("dead"), Topology("klein", 1, "x")):
        world = LargerThanLife(
            rule, size=(14, 12), init=_mixed(14, 12, rule.states, 7), **_kw(topology)
        )
        for _ in range(4):
            expected = _direct_step(world.state, rule, topology)
            world.step()
            assert np.array_equal(world.state, expected), (text, topology)


def _kw(topology: Topology) -> dict[str, object]:
    return {"boundary": topology.boundary, "shift": topology.shift, "axis": topology.axis}


@pytest.mark.parametrize(
    "topology",
    [Topology("torus"), Topology("dead"), Topology("klein", 1, "x"), Topology("sphere")],
    ids=repr,
)
def test_range_1_with_the_middle_out_is_life(topology: Topology) -> None:
    ltl = LargerThanLife(
        "R1,C0,M0,S2..3,B3..3,NM", size=(40, 40), density=0.4, seed=9, **_kw(topology)
    )
    life = LifeLike("B3/S23", size=(40, 40), density=0.4, seed=9, **_kw(topology))
    for _ in range(25):
        ltl.step()
        life.step()
        assert np.array_equal(ltl.state, life.state)


def test_a_world_is_at_least_2r_plus_1_cells_on_a_side() -> None:
    with pytest.raises(ValueError, match="range 5 is at least 11 cells wide and high"):
        LargerThanLife(BOSCO, size=(10, 40))
    LargerThanLife(BOSCO, size=(11, 11), boundary="sphere")  # the sphere's halo reaches


# -- editing, frames ---------------------------------------------------------------------------


def test_editing_tools_and_frames() -> None:
    world = LargerThanLife("R2,C4,M1,S3..9,B4..6,NM", size=(30, 20), density=0.4, seed=2)
    start = world.state.copy()
    world.step(3)
    assert world.frame().max() <= 3 and world.frame().dtype == np.uint8  # the states themselves
    with pytest.raises(ValueError, match="past this rule's 4 states"):
        world.set_state(np.full((20, 30), 4, dtype=np.uint8))
    shown = world.state.copy()
    world.set_state(start, 5, keep_start=True)
    assert world.generation == 5
    world.reset()
    assert np.array_equal(world.state, start)  # the start stayed the soup
    world.set_state(shown, 3)
    world.clear_rect(0, 0, 9, 9)
    assert not world.state[0:10, 0:10].any()
    world.fill_random(0, 0, 9, 9, density=0.5, seed=4)
    assert np.array_equal(world.state[0:10, 0:10], soup((10, 10), density=0.5, seed=4))
    before = world.state.copy()
    world.cancel()  # forgotten: an advance starts by forgetting an earlier request
    world.advance_selection(2, 2, 25, 15, 4)
    assert world.generation == 3 and not np.array_equal(world.state, before)
    two = LargerThanLife(BOSCO, size=(32, 32), seed=1)
    assert set(np.unique(two.frame())) <= {0, 255}


def test_a_pattern_stamps_only_within_the_targets_states() -> None:
    cells = np.array([[0, 1, 4]], dtype=np.uint8)
    assert compatible("ltl", "ltl", cells, target_states=5) is None
    assert compatible("ltl", "ltl", cells, target_states=4) is not None
    assert compatible("lifelike", "ltl", cells[:, :2]) is not None


def test_a_canceled_advance_leaves_the_world_as_it_was() -> None:
    import threading

    world = LargerThanLife(BOSCO, size=(96, 96), seed=3)
    before = world.state.copy()
    started = threading.Event()
    step = world.step

    def watched(n: int = 1) -> None:
        started.set()
        step(n)

    world.step = watched  # type: ignore[method-assign]
    raised: list[BaseException] = []

    def run() -> None:
        try:
            world.advance_outside(10, 10, 60, 60, 10**9)
        except BaseException as error:  # noqa: BLE001 - handed back to the test
            raised.append(error)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert started.wait(60)
    world.cancel()
    thread.join(60)
    assert raised and isinstance(raised[0], StepCanceled)
    assert np.array_equal(world.state, before) and world.generation == 0


# -- files and the universes ------------------------------------------------------------------


@pytest.mark.parametrize("text", [BOSCO, "R2,C5,M0,S2..7,B3..5,NN"])
def test_a_world_round_trips_through_rle_with_its_topology(text: str) -> None:
    world = LargerThanLife(text, size=(40, 30), density=0.45, seed=6, boundary="klein", axis="y")
    world.step(5)
    saved = rle_encode(world.state, world.rule.canonical, topology=world.topology)
    found = read_pattern(saved)
    assert found.rule == world.rule.canonical
    assert found.bounded_grid is not None and found.bounded_grid.topology == world.topology
    assert np.array_equal(found.cells, world.state)
    again = LargerThanLife(found.rule, size=(40, 30), init=found.cells, boundary="klein", axis="y")
    again.step(3)
    world.step(3)
    assert np.array_equal(again.state, world.state)


def test_a_world_past_24_states_writes_two_letter_tags() -> None:
    """RLE's two-letter tags (spec/patterns.md) carry the dying states past 24, so a world of
    up to 256 states saves and reads back as itself. The .NET suite pins the same text."""
    cells = np.zeros((3, 5), dtype=np.uint8)
    cells[0] = [24, 25, 48, 49, 255]
    world = LargerThanLife("R1,C256,M1,S2..3,B3..3,NM", size=(5, 3), init=cells)
    text = rle_encode(world.state, world.rule.canonical, topology=world.topology)
    assert text == "x = 5, y = 3, rule = R1,C256,M1,S2..3,B3..3,NM:T5,3\nXpApXqAyO2$!\n"
    found = read_pattern(text)
    assert found.rule == world.rule.canonical
    assert found.bounded_grid is not None and found.bounded_grid.topology == world.topology
    assert np.array_equal(found.cells, world.state)
    many = LargerThanLife("R2,C48,M0,S3..8,B4..6,NM", size=(30, 24), density=0.5, seed=8)
    many.step(60)
    assert many.state.max() > 24  # dying states past 24, reached by the run itself
    again = read_pattern(rle_encode(many.state, many.rule.canonical, topology=many.topology))
    assert np.array_equal(again.cells, many.state)


def test_neither_universe_runs_larger_than_life() -> None:
    reason = f"{BOSCO} is a Larger than Life rule: it runs on a bounded grid"
    with pytest.raises(ValueError, match=reason):
        HashLife(BOSCO)
    with pytest.raises(ValueError, match=reason):
        HashLife().rule = "5,34,45,34,58"
    with pytest.raises(ValueError, match=reason):
        read_universe(f"x = 3, y = 1, rule = {BOSCO}\n3o!\n")
    with pytest.raises(ValueError, match=reason):
        read_universe(f"[M2]\n#R {BOSCO}\n$$$$$$$$.***$\n")
    with pytest.raises(ValueError, match=reason):
        MultiStateHashLife(BOSCO)
    with pytest.raises(ValueError, match=reason):
        read_multistate_universe(f"x = 3, y = 1, rule = {BOSCO}\n3A!\n")
    # A file's bounded grid is refused first, as for any rule (spec/patterns.md).
    bounded = "the unbounded universe has no bounded grid"
    with pytest.raises(ValueError, match=bounded):
        read_universe(f"x = 3, y = 1, rule = {BOSCO}:T40,30\n3o!\n")
    with pytest.raises(ValueError, match=bounded):
        read_multistate_universe(f"x = 3, y = 1, rule = {BOSCO}:T40,30\n3A!\n")
