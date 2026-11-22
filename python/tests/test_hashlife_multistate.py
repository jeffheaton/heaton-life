"""Multi-state HashLife (spec/hashlife-multistate.md): state rules, the grid Wireworld and the
two-state HashLife as oracles, editing with states, snapshots, budgets, cancellation,
frames with the zoom order, and the multi-state Macrocell and RLE files."""

from __future__ import annotations

import gzip
import threading
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray

from heaton_life.ca.hashlife import (
    EDIT_LIMIT,
    MAX_LEVEL,
    HashLife,
    HashLifeMemoryError,
    LifeView,
    MultiStateHashLife,
    StepCanceled,
    measure_multistate_pattern,
    read_multistate_universe,
)
from heaton_life.ca.hashlife.multistate import read_timeline, write_timeline
from heaton_life.ca.rulefile import RuleTable, parse_rule_file
from heaton_life.ca.rulestring import compile_rule
from heaton_life.ca.state_rules import StateRule, check_state_rule, state_rule, try_state_rule
from heaton_life.ca.wireworld import WIREWORLD_RULE, Wireworld, clock_loop, wireworld_from_text
from heaton_life.init import BUILTIN_PATTERNS, PatternMetadata


class LifeStates(StateRule):
    """A two-state Life-like rule as a state rule: the multi-state engine must run it
    exactly as the two-state engine does."""

    def __init__(self, rule: str = "B3/S23") -> None:
        compiled = compile_rule(rule)
        self.table = compiled.table
        self.canonical = "Life-" + compiled.canonical.replace("/", "-")
        self.states = 2

    def next_state(
        self, nw: int, n: int, ne: int, w: int, c: int, e: int, sw: int, s: int, se: int
    ) -> int:
        index = nw << 8 | n << 7 | ne << 6 | w << 5 | c << 4 | e << 3 | sw << 2 | s << 1 | se
        return self.table[index]


class BriansBrain(StateRule):
    """Three states that move: 0 ready, 1 firing, 2 refractory; a ready cell fires with
    exactly two firing neighbors."""

    canonical = "Test-Brain"
    states = 3

    def next_state(
        self, nw: int, n: int, ne: int, w: int, c: int, e: int, sw: int, s: int, se: int
    ) -> int:
        if c == 1:
            return 2
        if c == 2:
            return 0
        firing = sum(1 for v in (nw, n, ne, w, e, sw, s, se) if v == 1)
        return 1 if firing == 2 else 0


class Cycle(StateRule):
    """S states that count up wherever any neighbor is non-zero (a test of many states)."""

    def __init__(self, states: int) -> None:
        self.states = states
        self.canonical = f"Test-Cycle-{states}"

    def next_state(
        self, nw: int, n: int, ne: int, w: int, c: int, e: int, sw: int, s: int, se: int
    ) -> int:
        if c == 0:
            return 1 if (nw or n or ne or w or e or sw or s or se) else 0
        return c + 1 if c + 1 < self.states else 1


def _noise(height: int, width: int, seed: int, states: int = 2) -> NDArray[np.uint8]:
    """Incompressible test input from an integer hash (simulation randomness stays PCG32)."""
    mask = np.uint64(0xFFFFFFFF)
    v = (
        np.arange(height * width, dtype=np.uint64) * np.uint64(0x9E3779B1) + np.uint64(seed)
    ) & mask
    v ^= v >> np.uint64(15)
    v = (v * np.uint64(0x85EBCA6B)) & mask
    v ^= v >> np.uint64(13)
    v = (v * np.uint64(0xC2B2AE35)) & mask
    v ^= v >> np.uint64(16)
    return ((v >> np.uint64(8)) % np.uint64(states)).astype(np.uint8).reshape(height, width)


def _wire_soup(height: int, width: int, seed: int) -> NDArray[np.uint8]:
    """Half conductor, a few heads and tails: chaotic for a while, then periodic."""
    roll = _noise(height, width, seed, 20)
    out = np.where(roll < 9, 3, 0).astype(np.uint8)
    out[roll == 18] = 1
    out[roll == 19] = 2
    return out


def _state(u: MultiStateHashLife | HashLife) -> tuple[tuple[int, int, int, int] | None, bytes]:
    box = u.bounding_box()
    if box is None:
        return None, b""
    return box, u.get_rect(*box).tobytes()


def _builtin(name: str) -> NDArray[np.uint8]:
    return next(p for p in BUILTIN_PATTERNS if p.name == name).cells()


# -- state rules ------------------------------------------------------------------------------


def test_names_ignore_ascii_case_and_end_whitespace() -> None:
    for text in ("WireWorld", "wireworld", " WIREWORLD\t", "\u3000WireWorld\u2028"):
        assert state_rule(text) is WIREWORLD_RULE
    for text in ("Wire World", "WireWorld!", "", "B3/S23", "\u212aireworld"):
        with pytest.raises(ValueError, match="not a state rule"):
            state_rule(text)
    assert MultiStateHashLife(" wireWORLD ").rule == "WireWorld"


_KNOWN = (
    "known: WireWorld, Langtons-Loops, Byl-Loop, Evoloop, Langtons-Ant, Ant-LLRR, Ant-RLR, "
    "History rules such as B3/S23History, Super rules such as B3/S23Super, and Generations "
    "rules such as B2/S345/C4"
)
_B0 = (
    " has B0: its first generation would turn the whole plane on, and the unbounded "
    "universe's background must stay 0; a grid runs it"
)


def test_names_give_reasons() -> None:
    """spec/hashlife-multistate.md "Names", "Reasons": the reason without its page, and the
    error's message the reason and its page."""
    cases = {
        "B03/S23History": ("B03/S23History" + _B0, 'spec/history.md "On the unbounded plane"'),
        " b0/s8super ": ("B0/S8Super" + _B0, 'spec/super.md "On the unbounded plane"'),
        "B03/S23/C3": ("B03/S23/C3" + _B0, 'spec/generations.md "The unbounded plane"'),
        "23/03/3": ("B03/S23/C3" + _B0, 'spec/generations.md "The unbounded plane"'),
        "R2,C0,M1,S2..3,B3..3": (
            (
                "R2,C0,M1,S2..3,B3..3,NM is a Larger than Life rule: it runs on a bounded grid, "
                "never on the unbounded plane"
            ),
            "spec/ltl.md",
        ),
        "B3/S23": (
            f"'B3/S23' is not a state rule ({_KNOWN})",
            'spec/hashlife-multistate.md "Names"',
        ),
        " it's\t": (
            f"' it's\t' is not a state rule ({_KNOWN})",
            'spec/hashlife-multistate.md "Names"',
        ),
        "": (f"'' is not a state rule ({_KNOWN})", 'spec/hashlife-multistate.md "Names"'),
    }
    for text, (reason, page) in cases.items():
        assert try_state_rule(text) == (None, reason), text
        with pytest.raises(ValueError) as error:
            state_rule(text)
        assert str(error.value) == f"{reason} ({page})", text
    for text in ("WireWorld", "evoloop", "B3/S23History", "LifeSuper", "345/2/4", "B2/S/C3"):
        rule, reason = try_state_rule(text)
        assert reason is None and rule is state_rule(text), text
    with pytest.raises(TypeError):
        try_state_rule(None)  # type: ignore[arg-type]


def test_every_named_rule_runs() -> None:
    """A name gives only rules that check_state_rule passes: a Generations rule with B0 is
    refused at its name, as History and Super rules are (spec/hashlife-multistate.md "Names")."""
    for text in ("B0/S/C3", "B03/S23/C3", "B0/S8History", "B0/S8Super", "B0123478/S01234678/C5"):
        rule, reason = try_state_rule(text)
        assert rule is None and reason is not None and " has B0: " in reason, text
        with pytest.raises(ValueError, match="has B0"):
            MultiStateHashLife(text)
    for text in ("WireWorld", "Byl-Loop", "B2/S/C3", "B36/S23History", "B2/S34HSuper"):
        assert check_state_rule(state_rule(text)) is state_rule(text)


def test_rules_that_cannot_run_are_refused() -> None:
    class Lit(Cycle):
        def next_state(self, *block: int) -> int:  # type: ignore[override]
            return 1

    with pytest.raises(ValueError, match="background"):
        MultiStateHashLife(Lit(3))
    with pytest.raises(ValueError, match="2 to 256"):
        check_state_rule(Cycle(257))
    with pytest.raises(ValueError, match="2 to 256"):
        check_state_rule(Cycle(1))
    bad = Cycle(5)
    bad.canonical = "two words"
    with pytest.raises(ValueError, match="canonical name"):
        MultiStateHashLife(bad)
    with pytest.raises(TypeError):
        MultiStateHashLife(42)  # type: ignore[arg-type]
    assert MultiStateHashLife(Cycle(256)).states == 256


def test_the_wireworld_rule_is_the_spec_table() -> None:
    f = WIREWORLD_RULE.next_state
    assert f(0, 1, 1, 1, 0, 1, 1, 1, 1) == 0  # empty stays empty
    assert f(0, 0, 0, 0, 1, 0, 0, 0, 0) == 2 and f(3, 3, 3, 3, 2, 3, 3, 3, 3) == 3
    for heads in range(9):
        block = [1] * heads + [3] * (8 - heads)
        want = 1 if heads in (1, 2) else 3
        assert f(*block[:4], 3, *block[4:]) == want


# -- oracles ----------------------------------------------------------------------------------


@pytest.mark.parametrize("origin", [(0, 0), (-37, 5), (EDIT_LIMIT - 63, -EDIT_LIMIT)])
def test_wireworld_agrees_with_the_grid(origin: tuple[int, int]) -> None:
    grid = _wire_soup(64, 64, 11)
    grid[0, :] = 3  # conductor along the edge: the dead boundary never matters
    u = MultiStateHashLife()
    x, y = origin
    u.set_rect(x, y, grid)
    w = Wireworld(size=(64, 64), init=grid)
    for n in (1, 1, 2, 5, 17, 64, 200, 1024):
        u.step(n)
        w.step(n)
        assert np.array_equal(u.get_rect(x, y, x + 63, y + 63), w.state), u.generation
        assert u.population == int(np.count_nonzero(w.state))


def test_the_clock_lands_where_its_period_says() -> None:
    u = MultiStateHashLife()
    u.set_rect(10, -4, clock_loop((16, 16)))
    u.step(1)  # the electron settles onto its cycle
    start = _state(u)
    period = 40  # a 12 × 12 loop's 44 cells, less the four corners it cuts
    u.step(period)
    assert _state(u) == start
    big = 2**200 + 7
    u.step(big)
    reference = MultiStateHashLife()
    reference.set_rect(10, -4, clock_loop((16, 16)))
    reference.step(1 + (period + big) % period)
    assert _state(u) == _state(reference) and u.generation == 1 + period + big


@pytest.mark.parametrize(
    ("rule", "steps"),
    [
        ("B3/S23", (1, 3, 60, 500, 2**12)),
        ("B36/S23", (1, 3, 60, 500, 2**12)),
        ("B2/S", (1, 3, 20)),  # explodes: a few generations are enough
        ("B3/S12345", (1, 3, 20)),
    ],
)
def test_two_state_rules_run_as_the_two_state_engine_runs_them(
    rule: str, steps: tuple[int, ...]
) -> None:
    states = LifeStates(rule)
    a = _noise(48, 40, 3)
    u, h = MultiStateHashLife(states), HashLife(rule)
    u.set_rect(-20, 7, a)
    h.set_rect(-20, 7, a)
    for n in steps:
        u.step(n)
        h.step(n)
        assert _state(u) == _state(h), (rule, u.generation)
        assert u.population == h.population


def test_a_glider_crosses_past_64_bit_coordinates() -> None:
    u = MultiStateHashLife(LifeStates())
    u.set_rect(0, 0, _builtin("Glider"))
    m = 2**62
    u.step(4 * m)
    assert u.bounding_box() == (m, m, m + 2, m + 2) and u.population == 5


def test_moving_states_spread_and_stop_at_the_deepest_tree() -> None:
    u = MultiStateHashLife(BriansBrain())
    u.set_rect(0, 0, np.array([[1, 1]], np.uint8))  # a pair of firing cells
    u.step(1)
    assert u.population > 2
    far = MultiStateHashLife(BriansBrain())
    chain = "[M2]\n#R Test-Brain\n1 0 0 1 1\n" + "".join(
        f"{k} 0 0 0 {k - 1}\n" for k in range(2, MAX_LEVEL + 1)
    )
    far = MultiStateHashLife.from_macrocell(chain, rule=BriansBrain())
    corner = 2 ** (MAX_LEVEL - 1) - 2
    assert far.bounding_box() == (corner, corner + 2, corner + 1, corner + 2)
    state = far.to_macrocell()
    with pytest.raises(ValueError, match="spread too far"):
        far.step(1)
    assert far.to_macrocell() == state and far.generation == 0
    for n in (2 ** (MAX_LEVEL - 2), 2**600):
        with pytest.raises(ValueError, match="deeper"):
            u.step(n)


def test_results_do_not_depend_on_the_budget() -> None:
    a = _wire_soup(150, 150, 4)
    roomy = MultiStateHashLife()
    roomy.set_rect(0, 0, a)
    roomy.step(300)
    tight = MultiStateHashLife(max_memory_mb=10)
    tight.set_rect(0, 0, a)
    for n in (1, 1, 200, 98):  # a mix of sub-step sizes under constant pressure
        tight.step(n)
    assert tight.collections > 0
    assert _state(tight) == _state(roomy)


def test_a_universe_too_big_for_its_budget_refuses_to_step_unchanged() -> None:
    u = MultiStateHashLife(Cycle(7), max_memory_mb=10)
    u.set_rect(0, 0, _noise(700, 700, 9, 7))  # loading never fails for budget
    before = (u.generation, _state(u))
    with pytest.raises(HashLifeMemoryError, match="max_memory_mb=10"):
        u.step(1)
    assert (u.generation, _state(u)) == before
    u.max_memory_mb = 4000
    u.step(1)
    assert u.generation == 1


def test_cancel_stops_at_a_completed_sub_step() -> None:
    u = MultiStateHashLife(BriansBrain())  # chaotic and growing: 2^20 takes far longer
    u.set_rect(0, 0, _noise(96, 96, 2, 3))
    outcome: list[BaseException | None] = []

    def run() -> None:
        try:
            u.step(2**20 + 1)  # one generation, then 2^20 in a single sub-step
        except StepCanceled as exc:
            outcome.append(exc)
        else:
            outcome.append(None)

    worker = threading.Thread(target=run)
    worker.start()
    time.sleep(1.0)
    u.cancel()
    worker.join(timeout=60)
    assert len(outcome) == 1 and isinstance(outcome[0], StepCanceled)
    assert u.generation == 1
    u.step(1)
    assert u.generation == 2


def test_a_rule_object_runs_as_its_name() -> None:
    a = _wire_soup(40, 40, 8)
    by_name, by_object = MultiStateHashLife("WireWorld"), MultiStateHashLife(WIREWORLD_RULE)
    for u in (by_name, by_object):
        u.set_rect(3, 3, a)
        u.step(77)
    assert by_name.to_macrocell() == by_object.to_macrocell()


# -- editing ----------------------------------------------------------------------------------


def test_cells_and_rectangles_hold_states() -> None:
    u = MultiStateHashLife(Cycle(9))
    a = _noise(29, 31, 1, 9)
    for x, y in ((-13, 7), (EDIT_LIMIT - 30, -EDIT_LIMIT), (-EDIT_LIMIT, EDIT_LIMIT - 28)):
        u.set_rect(x, y, a)
        assert np.array_equal(u.get_rect(x, y, x + 30, y + 28), a)
    assert u.population == 3 * int(np.count_nonzero(a))
    u.set_cell(5, -9, 8)
    assert u.get_cell(5, -9) == 8 and u.get_cell(6, -9) == 0
    with pytest.raises(ValueError, match="outside the rule's states"):
        u.set_cell(0, 0, 9)
    with pytest.raises(ValueError, match="outside the rule's states"):
        u.set_rect(0, 0, np.full((2, 2), 9, np.uint8))
    with pytest.raises(ValueError, match="editing box"):
        u.set_cell(EDIT_LIMIT + 1, 0, 1)
    u.clear()
    assert u.population == 0 and u.bounding_box() is None


def test_paste_modes_match_the_grid_stamp() -> None:
    from heaton_life.init.patterns import stamp

    u = MultiStateHashLife(Cycle(6))
    mirror = np.zeros((40, 50), np.uint8)
    for i, mode in enumerate(("copy", "or", "copy", "or", "copy")):
        piece = _noise(11 + i, 17 - i, 10 + i, 6)
        px, py = 3 * i + 1, 4 * i + 2
        stamp(mirror, piece, px, py, torus=False, mode=mode)  # type: ignore[arg-type]
        u.set_rect(-20 + px, -9 + py, piece, mode)  # type: ignore[arg-type]
        assert np.array_equal(u.get_rect(-20, -9, 29, 30), mirror), mode
    two = MultiStateHashLife(Cycle(6))
    grid = _noise(20, 20, 3)  # states 0 and 1 only
    two.set_rect(0, 0, grid)
    for mode in ("xor", "and"):
        piece = _noise(7, 9, 4)
        expect = grid.copy()
        stamp(expect, piece, 2, 3, torus=False, mode=mode)  # type: ignore[arg-type]
        two.set_rect(2, 3, piece, mode)  # type: ignore[arg-type]
        assert np.array_equal(two.get_rect(0, 0, 19, 19), expect)
        grid = expect
    before = two.to_macrocell()
    with pytest.raises(ValueError, match="states 0 and 1"):
        two.set_rect(0, 0, np.full((2, 2), 2, np.uint8), "xor")
    two.set_cell(30, 30, 4)
    with pytest.raises(ValueError, match="states 0 and 1"):
        two.set_rect(29, 29, np.ones((3, 3), np.uint8), "and")
    two.set_cell(30, 30, 0)
    assert two.to_macrocell() == before


@pytest.mark.parametrize("clockwise", [True, False])
def test_turns_and_flips_match_numpy(clockwise: bool) -> None:
    u = MultiStateHashLife(Cycle(7))
    a = _noise(9, 14, 5, 7)
    u.set_rect(-3, 2, a)
    new = u.rotate_rect(-3, 2, 10, 10, clockwise=clockwise)
    assert np.array_equal(u.get_rect(*new), np.rot90(a, -1 if clockwise else 1))
    assert u.population == int(np.count_nonzero(a))
    u.rotate_rect(*new, clockwise=not clockwise)
    assert np.array_equal(u.get_rect(-3, 2, 10, 10), a)
    u.flip_rect(-3, 2, 10, 10, horizontal=True)
    assert np.array_equal(u.get_rect(-3, 2, 10, 10), a[:, ::-1])
    u.flip_rect(-3, 2, 10, 10, horizontal=False)
    assert np.array_equal(u.get_rect(-3, 2, 10, 10), a[::-1, ::-1])


@pytest.mark.parametrize("outside", [False, True])
def test_advancing_part_matches_the_grid(outside: bool) -> None:
    grid = _wire_soup(40, 40, 6)
    u = MultiStateHashLife()
    u.set_rect(0, 0, grid)
    region = (8, 5, 30, 33)
    w = Wireworld(size=(40, 40), init=grid)
    (w.advance_outside if outside else w.advance_selection)(*region, 13)
    (u.advance_outside if outside else u.advance_selection)(*region, 13)
    assert np.array_equal(u.get_rect(0, 0, 39, 39), w.state) and u.generation == 0


def test_every_edit_matches_the_two_state_engine() -> None:
    states = LifeStates("B36/S23")
    u, h = MultiStateHashLife(states), HashLife("B36/S23")
    for v in (u, h):
        v.set_rect(-30, -20, _noise(50, 60, 7))
        v.clear_rect(-10, -10, 5, 3)
        v.clear_outside(-28, -19, 25, 28)
        v.rotate_rect(-25, -15, 0, 3, clockwise=True)
        v.flip_rect(-5, -5, 20, 20, horizontal=False)
        v.advance_selection(-20, -20, 10, 10, 37)
        v.advance_outside(-10, -10, 0, 0, 9)
        v.step(100)
    assert _state(u) == _state(h)
    for rect in ((-50, -50, 50, 50), (-3, -7, 4, 9), (100, 100, 200, 200)):
        assert u.bounding_box_in(*rect) == h.bounding_box_in(*rect)
        assert u.population_in(*rect) == h.population_in(*rect)


def test_a_rule_change_keeps_cells_and_refuses_missing_states() -> None:
    u = MultiStateHashLife(Cycle(9))
    u.set_rect(0, 0, _noise(10, 10, 2, 5))  # states up to 4
    snap = u.snapshot()
    with pytest.raises(ValueError, match="holds state 4"):
        u.rule = "WireWorld"  # 4 states: the universe holds a 4
    assert u.rule == "Test-Cycle-9"
    u.clear_rect(0, 0, 9, 9)
    u.set_rect(0, 0, _noise(10, 10, 2, 4))
    u.rule = "WireWorld"
    assert u.rule == "WireWorld" and u.states == 4
    with pytest.raises(ValueError, match="doesn't have"):
        u.restore(snap)  # it holds a 4 that WireWorld lacks
    u.state_rule = Cycle(9)
    u.restore(snap)
    assert u.get_rect(0, 0, 9, 9).max() == 4


# -- snapshots --------------------------------------------------------------------------------


def test_snapshots_survive_collection_and_belong_to_one_universe() -> None:
    u = MultiStateHashLife()
    u.set_rect(0, 0, _wire_soup(50, 50, 3))
    start = u.snapshot()
    first = _state(u)
    u.step(90)
    mid = u.snapshot()
    middle = _state(u)
    u.step(300)
    u.collect_garbage()
    u.restore(start)
    assert (u.generation, _state(u)) == (0, first)
    u.restore(mid)
    assert (u.generation, _state(u)) == (90, middle)
    for other in (MultiStateHashLife(), HashLife()):
        with pytest.raises(ValueError, match="another universe"):
            other.restore(mid)
    with pytest.raises(ValueError, match="another universe"):
        u.restore(HashLife().snapshot())
    mid.release()
    with pytest.raises(ValueError, match="released"):
        u.restore(mid)


def test_measured_nodes_are_the_macrocell_lines() -> None:
    u = MultiStateHashLife()
    u.set_rect(0, 0, clock_loop((16, 16)))
    one = u.snapshot()
    u.step(5)
    two = u.snapshot()
    u.set_cell(40, 40, 3)
    lines = sum(1 for line in u.to_macrocell().splitlines() if line[0].isdigit())
    footprint = u.measure_snapshots([two, one, two])
    assert footprint.universe_nodes == lines
    assert footprint.added[2] == 0 and footprint.nodes == sum(footprint.added)
    assert MultiStateHashLife().measure_snapshots([]).universe_nodes == 0
    one.release()
    assert u.measure_snapshots([one]).added == (0,)


# -- frames -----------------------------------------------------------------------------------


def _shown(block: NDArray[np.uint8], order: tuple[int, ...]) -> int:
    present = {int(v) for v in np.unique(block) if v}
    ranked = [s for s in order if s in present] + sorted(present - set(order))
    return ranked[0] if ranked else 0


@pytest.mark.parametrize("order", [(), (3,), (2, 1), (5, 4, 3, 2, 1)])
def test_frames_match_the_cells_at_every_scale(order: tuple[int, ...]) -> None:
    u = MultiStateHashLife(Cycle(6))
    u.set_rect(-30, -20, _noise(48, 64, 2, 6))
    u.zoom_order = order
    cells = u.get_rect(-40, -31, 55, 48)  # tree rows -32..47: aligned to 2, 4 and 8
    assert np.array_equal(u.render(LifeView(-40, -32, 0), (96, 80)), cells)
    up = u.render(LifeView(-160, -128, 2), (384, 320))
    assert np.array_equal(up, cells.repeat(4, 0).repeat(4, 1))
    assert np.array_equal(u.render(LifeView(-40, -32, 0), (96, 80), "density"), (cells > 0) * 255)
    for s in (1, 2, 3):
        f = 1 << s
        pooled = cells.reshape(80 // f, f, 96 // f, f).transpose(0, 2, 1, 3)
        view = LifeView(-40 >> s, -32 >> s, -s)
        size = (96 // f, 80 // f)
        want = np.array([[_shown(b, order) for b in row] for row in pooled], np.uint8)
        assert np.array_equal(u.render(view, size), want), (order, s)
        counts = (pooled > 0).sum(axis=(2, 3))
        assert np.array_equal(
            u.render(view, size, "density"), (255 * counts + f * f - 1) // (f * f)
        )


def test_frames_far_out_show_the_quarters() -> None:
    u = MultiStateHashLife(Cycle(6))
    u.set_rect(-1, 0, np.array([[5, 4], [3, 2]], np.uint8))  # one cell in each quarter
    u.zoom_order = (4, 2)
    for s in (2, 9, 600):
        frame = u.render(LifeView(-2, -2, -s), (4, 4))
        assert frame[1, 1] == 5 and frame[1, 2] == 4 and frame[2, 1] == 3 and frame[2, 2] == 2
        assert frame.sum() == 14
    assert u.render(LifeView(-1, -1, -40), (2, 2), "density").max() == 1


def test_the_zoom_order_is_checked() -> None:
    u = MultiStateHashLife()
    for bad in ((0,), (1, 1), (256,)):
        with pytest.raises(ValueError, match="zoom order"):
            u.zoom_order = bad
    with pytest.raises(ValueError, match="render mode"):
        u.render(LifeView(0, 0, 0), (2, 2), "any")  # type: ignore[arg-type]


# -- files ------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["clock.rle", "clock.mc", "clock.mc.gz"])
def test_files_round_trip(tmp_path: Path, name: str) -> None:
    u = MultiStateHashLife()
    u.set_rect(-7, 3, clock_loop((16, 16)))
    u.step(9)
    notes = PatternMetadata("Clock", "nobody", ("a loop",))
    u.save(tmp_path / name, notes)
    found = read_multistate_universe((tmp_path / name).read_bytes())
    assert found.universe.to_macrocell() == u.to_macrocell()
    assert found.metadata == notes and found.format == (
        "rle" if name.endswith("rle") else "macrocell"
    )


def test_macrocell_reads_both_leaf_syntaxes_and_writes_level_one_leaves() -> None:
    two = HashLife()
    two.set_rect(-3, -2, _noise(19, 23, 5))
    text = two.to_macrocell().replace("#R B3/S23", "#R life-b3-s23")  # names the object
    as_states = MultiStateHashLife.from_macrocell(text, rule=LifeStates())
    assert _state(as_states) == _state(two)
    assert all(
        not line.startswith((".", "*", "$")) for line in as_states.to_macrocell().splitlines()
    )
    empty = MultiStateHashLife()
    assert empty.to_macrocell() == "[M2] (heaton-life)\n#R WireWorld\n1 0 0 0 0\n"
    one = MultiStateHashLife()
    one.set_cell(0, 0, 3)  # tree (0, -1): the NE cell of a level-1 root
    assert one.to_macrocell().splitlines()[-1] == "1 0 3 0 0"


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("[M2]\n#R WireWorld\n1 0 4 0 0\n", "doesn't have"),
        ("[M2]\n1 0 256 0 0\n", "at most 255"),
        ("[M2]\n#R Langton\n1 0 1 0 0\n", "not a state rule"),
        ("[M2]\n1 0 1 0 0\n3 1 0 0 0\n", "level 1, not 2"),
        ("[M2]\n2 1 0 0 0\n", "not defined yet"),
        ("[M2]\n0 0 0 0 0\n", "at least 1"),
        ("[M2]\n#G -1\n1 0 1 0 0\n", "digits"),
        ("[M2]\n", "no nodes"),
        ("x = 1, y = 1\n1 0 1 0 0\n", "first line"),
    ],
)
def test_macrocell_refusals(text: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        MultiStateHashLife.from_macrocell(text)


def test_rle_reads_either_dialect_and_writes_canonically() -> None:
    u = MultiStateHashLife.from_rle(
        "#CXRLE Pos=-4,7 Gen=12\nx = 3, y = 2, rule = WireWorld\nCBA$.2C!"
    )
    assert u.generation == 12 and u.get_rect(-4, 7, -2, 8).tolist() == [[3, 2, 1], [0, 3, 3]]
    assert u.to_rle() == "#CXRLE Pos=-4,7 Gen=12\nx = 3, y = 2, rule = WireWorld\nCBA$.2C!\n"
    heads = MultiStateHashLife.from_rle("x = 3, y = 1\nobo!")  # two-state dialect: states 0 and 1
    assert heads.rule == "WireWorld" and heads.population == 2
    assert heads.to_rle() == "#CXRLE Pos=0,0\nx = 3, y = 1, rule = WireWorld\nobo!\n"
    with pytest.raises(ValueError, match="doesn't have"):
        MultiStateHashLife.from_rle("x = 1, y = 1, rule = WireWorld\nD!")
    with pytest.raises(ValueError, match="editing box"):
        MultiStateHashLife.from_rle(f"#CXRLE Pos={EDIT_LIMIT},0\nx = 2, y = 1\n2C!")
    with pytest.raises(ValueError, match="editing box"):  # refused before it is spelled out
        MultiStateHashLife.from_rle("x = 1, y = 1, rule = WireWorld\n999999999999C!")
    many = MultiStateHashLife(Cycle(256))
    many.set_cell(0, 0, 25)
    many.set_cell(3, 0, 255)
    assert many.to_rle().splitlines()[-1] == "pA2.yO!"  # every state writes (spec/patterns.md)
    with pytest.raises(ValueError, match="bounded grid"):
        MultiStateHashLife.from_rle("x = 3, y = 1, rule = WireWorld:T30,20\nCBA!")


def test_loading_by_content_refuses_two_state_formats() -> None:
    with pytest.raises(ValueError, match="two states"):
        read_multistate_universe(b"!Name: x\n.O.\n")
    gz = gzip.compress(b"x = 2, y = 1, rule = WireWorld\nAC!", mtime=0)
    assert read_multistate_universe(gz).universe.population == 2


def test_read_snapshot_leaves_the_universe_alone() -> None:
    u = MultiStateHashLife()
    u.set_rect(0, 0, clock_loop((16, 16)))
    before = u.snapshot()
    state = (u.to_macrocell(), u.generation, u.rule)
    other = MultiStateHashLife()
    other.set_rect(100, 100, _wire_soup(12, 12, 1))
    other.step(3)
    found = u.read_snapshot(other.to_macrocell().encode())
    assert (u.to_macrocell(), u.generation, u.rule) == state
    assert found.rule == "WireWorld" and found.format == "macrocell" and found.frames == ()
    u.restore(found.snapshot)
    assert u.to_macrocell() == other.to_macrocell()
    u.restore(before)
    assert u.to_macrocell() == state[0]
    plain = u.read_snapshot("x = 1, y = 1\no!")  # names no rule: the universe's
    assert plain.rule == "WireWorld"
    with pytest.raises(ValueError):
        u.read_snapshot("[M2]\n#R Nothing\n1 0 1 0 0\n")
    assert (u.to_macrocell(), u.generation, u.rule) == state


def test_timelines_round_trip() -> None:
    u = MultiStateHashLife()
    u.set_rect(0, 0, wireworld_from_text("TH#####\n#.....#\n#######"))
    frames = []
    for _ in range(4):
        frames.append(u.snapshot())
        u.step(3)
    text = write_timeline(u, frames, metadata=PatternMetadata(name="Loop"))
    assert "#FRAMES 4 0 3^1" in text
    timeline = read_timeline(text)
    assert timeline.step == 3 and timeline.metadata.name == "Loop"
    for mine, theirs in zip(frames, timeline.frames, strict=True):
        u.restore(mine)
        timeline.universe.restore(theirs)
        assert timeline.universe.to_macrocell() == u.to_macrocell()
    found = read_multistate_universe(text)
    assert len(found.frames) == 4 and found.step == 3
    with pytest.raises(ValueError, match="evenly spaced"):
        write_timeline(u, [frames[0], frames[1], frames[3]])


# -- live cells (spec/hashlife-multistate.md "Observables") ------------------------------------


def _live_by_hand(u: MultiStateHashLife, rect: tuple[int, int, int, int], odd: bool) -> int:
    cells = u.get_rect(*rect)
    return int(np.count_nonzero(cells & 1 if odd else cells))


@pytest.mark.parametrize("rule", ["B3/S23History", "B36/S23Super", "B2/S345/C4", "WireWorld"])
def test_live_cells_are_the_on_cells_under_history_and_super(rule: str) -> None:
    """Under History and Super the live cells are the odd states, an envelope and the marks
    that are off left out; under every other rule they are the non-zero cells."""
    odd = rule.endswith(("History", "Super"))
    u = MultiStateHashLife(rule)
    states = 26 if rule.endswith("Super") else 7 if odd else u.states
    rng = np.random.default_rng(5)
    soup = (rng.random((40, 50)) < 0.4) * rng.integers(1, states, (40, 50))
    u.set_rect(-20, -9, soup.astype(np.uint8))
    for n in (0, 1, 7, 30):
        u.step(n)
        box = u.bounding_box()
        assert box is not None
        x0, y0, x1, y1 = box
        whole = (x0 - 3, y0 - 3, x1 + 3, y1 + 3)
        assert u.live_population == _live_by_hand(u, whole, odd)
        assert u.live_population_in(*whole) == u.live_population
        for rect in ((x0, y0, x0 + 9, y0 + 7), (-5, -5, 4, 6), (x1 - 3, y0, x1 + 40, y1 - 2)):
            assert u.live_population_in(*rect) == _live_by_hand(u, rect, odd), (n, rect)
        if odd:
            assert u.live_population < u.population  # the envelope is off
        else:
            assert (u.live_population, u.live_population_in(*whole)) == (
                u.population,
                u.population_in(*whole),
            )
    assert u.live_population_in(10**30, 10**30, 10**30 + 5, 10**30 + 5) == 0
    assert u.live_population_in(5, 5, 4, 4) == 0  # an empty rectangle


def test_live_cells_follow_the_rule_and_survive_collection() -> None:
    u = MultiStateHashLife("B3/S23History", max_memory_mb=10)
    u.set_rect(0, 0, np.array([[0, 1, 0], [0, 0, 1], [1, 1, 1]], np.uint8))  # a glider
    u.step(64)
    assert (u.live_population, u.population > 5) == (5, True)  # its trail is the envelope
    u.rule = "B3/S23Super"  # states 0-6 mean the same
    assert u.live_population == 5
    u.rule = "B3/S23/C7"  # a Generations rule of seven states: every non-zero cell lives
    assert u.live_population == u.population
    u.rule = "B3/S23History"
    u._store.collect([(u._root, u._level)])
    assert u.live_population == 5
    u.set_cell(1000, 1000, 4)  # marked off
    u.set_cell(1001, 1000, 3)  # marked on
    assert u.live_population == 6 and u.live_population_in(1000, 1000, 1001, 1000) == 1
    u.clear()
    assert (u.live_population, u.live_population_in(-9, -9, 9, 9)) == (0, 0)


# -- measuring and naming the rule (spec/hashlife-multistate.md "Pattern I/O") ----------------


def _measure_agrees_with_reading(source: bytes | str, rule: str | None = None) -> None:
    extent = measure_multistate_pattern(source, rule=rule)
    read = read_multistate_universe(source, rule=rule)
    u = read.universe
    assert extent.format == read.format
    box = u.bounding_box()
    if box is None:
        assert (extent.width, extent.height, extent.x, extent.y) == (0, 0, 0, 0)
    else:
        x0, y0, x1, y1 = box
        assert (extent.x, extent.y, extent.width, extent.height) == (
            x0,
            y0,
            x1 - x0 + 1,
            y1 - y0 + 1,
        )
    assert extent.rule == (u.rule if read.rule_named else None)
    assert (extent.generation, extent.metadata) == (u.generation, read.metadata)
    assert extent.bounded_grid is None


def test_measuring_gives_what_reading_gives() -> None:
    files: list[str | bytes] = [
        "[M2]\n#R WireWorld\n#G 12\n#N Name\n1 0 3 0 0\n",  # a lone leaf: tree (0, -1)
        "[M2]\n1 0 0 1 0\n",  # names no rule
        "[M2]\n#R LifeSuper\n1 0 25 0 0\n1 7 0 0 13\n2 1 0 0 2\n3 0 0 0 3\n",
        "[M2]\n#R B3/S23History\n1 0 0 0 0\n2 0 0 0 0\n",  # every cell 0
        "[M2]\n#R B2/S345/C4\n$$...*$\n4 0 1 0 1\n",  # a two-state leaf
        "#CXRLE Pos=-4,7 Gen=12\nx = 9, y = 3, rule = WireWorld\n3.CBA$$.2C!",
        "x = 2, y = 2\n$bo!",  # names no rule
        "x = 3, y = 1, rule = B2/S345/C4\n0C2.A!",
        "#MCell 4.20\n#GAME Generations\n#RULE 345/2/4\n#L 3.A$.BC\n",
    ]
    two = HashLife()
    two.set_rect(-3, -2, _noise(19, 23, 5))
    files.append(two.to_macrocell().replace("#R B3/S23\n", ""))
    wire = MultiStateHashLife()
    wire.set_rect(-1000, 77, clock_loop((16, 16)))
    wire.step(5)
    files += [wire.to_macrocell(), gzip.compress(wire.to_rle().encode(), mtime=0)]
    for source in files:
        _measure_agrees_with_reading(source)
    _measure_agrees_with_reading("x = 1, y = 1\nE!", rule="B3/S23History")  # its states, 0-6


def test_the_measure_says_how_the_file_writes_its_cells() -> None:
    assert not measure_multistate_pattern("[M2]\n#R WireWorld\n1 0 3 0 0\n").two_state
    assert measure_multistate_pattern("[M2]\n#R WireWorld\n$$...*$\n").two_state
    assert measure_multistate_pattern("x = 2, y = 1, rule = WireWorld\n2o!").two_state is False
    assert measure_multistate_pattern("x = 2, y = 1\n2o!").two_state
    mcell = "#MCell 4.20\n#GAME Generations\n#RULE 345/2/4\n#L A\n"
    assert not measure_multistate_pattern(mcell).two_state
    empty = measure_multistate_pattern("[M2]\n1 0 0 0 0\n")
    assert (empty.width, empty.height, empty.x, empty.y, empty.rule) == (0, 0, 0, 0, None)


@pytest.mark.parametrize(
    ("source", "match"),
    [
        ("!Name: x\n.O.\n", "two states"),  # plaintext
        ("[M2]\n#R Nothing\n1 0 1 0 0\n", "not a state rule"),
        ("[M2]\n#R B3/S23\n1 0 1 0 0\n", "not a state rule"),
        ("[M2]\n#R WireWorld\n1 0 4 0 0\n", "doesn't have"),
        ("[M2]\n1 0 5 0 0\n", "doesn't have"),  # no rule: the reader's, WireWorld
        ("[M2]\n#R B03/S23History\n1 0 1 0 0\n", "has B0"),
        ("[M2]\n2 1 0 0 0\n", "not defined yet"),
        ("x = 3, y = 1, rule = WireWorld:T30,20\nCBA!", "bounded grid"),
        (f"#CXRLE Pos={EDIT_LIMIT},0\nx = 2, y = 1\n2C!", "editing box"),
        ("x = 1, y = 1, rule = WireWorld\n999999999999C!", "editing box"),
        ("x = 1, y = 1, rule = R2,C0,M1,S2..3,B3..3\no!", "Larger than Life"),
        ("#MCell 4.20\n#GAME Generations\n#RULE 345/2/4\n#BOARD 20x20\n#L A\n", "board"),
        ("#MCell 4.20\n#GAME Life\n#RULE 23/3\n#L A\n", "not a state rule"),
    ],
)
def test_measuring_refuses_what_reading_refuses(source: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        measure_multistate_pattern(source)
    with pytest.raises(ValueError):
        read_multistate_universe(source)


def test_the_reader_says_whether_a_file_named_its_rule() -> None:
    named = {
        "[M2]\n#R WireWorld\n1 0 3 0 0\n": True,
        "[M2]\n1 0 1 0 0\n": False,
        "x = 1, y = 1, rule = WireWorld\nC!": True,
        "x = 1, y = 1\no!": False,
        "#MCell 4.20\n#GAME Generations\n#RULE 345/2/4\n#L A\n": True,
    }
    for text, expected in named.items():
        read = read_multistate_universe(text, rule="B3/S23History")
        assert read.rule_named is expected, text
        assert (read.universe.rule == "B3/S23History") is not expected


# -- a Macrocell file carrying its rule (spec/ruletable.md "Files") -----------------------------


def _my_byl() -> RuleTable:
    from heaton_life.ca.ruletable import starter_rule

    return parse_rule_file(
        starter_rule("Byl-Loop").text.replace("@RULE Byl-Loop", "@RULE My-Byl", 1)
    )


def test_a_macrocell_file_carries_its_rule_table() -> None:
    from heaton_life.ca.ruletable import append_rule, embedded_rule, starter_pattern

    mine = _my_byl()
    u = MultiStateHashLife(mine)
    u.set_rect(-3, 2, starter_pattern("Byl-Loop"))
    u.step(9)
    plain = u.to_macrocell()
    assert "@RULE" not in plain  # the canonical text is the cells'
    text = append_rule(plain, mine)
    found = read_multistate_universe(text)
    assert (found.universe.rule, found.rule_named) == ("My-Byl", True)
    assert found.universe.to_macrocell() == plain and found.universe.generation == 9
    carried = embedded_rule(text)
    assert carried is not None and (carried.canonical, carried.text) == ("My-Byl", mine.text)
    assert embedded_rule(plain) is None
    extent = measure_multistate_pattern(text)
    assert extent.rule == "My-Byl"
    box = found.universe.bounding_box()
    assert box is not None and (extent.x, extent.y) == box[:2]
    with pytest.raises(ValueError, match="not a state rule"):  # without its rule file
        read_multistate_universe(plain)
    same = u.read_snapshot(text)  # into a universe that exists
    assert same.rule == "My-Byl"
    # A rule object of the name wins, as for RLE; an appended rule #R doesn't name is skipped.
    assert read_multistate_universe(text, rule=mine).universe.state_rule is mine
    wire = MultiStateHashLife()
    wire.set_rect(0, 0, clock_loop((12, 12)))
    other = read_multistate_universe(append_rule(wire.to_macrocell(), mine))
    assert other.universe.rule == "WireWorld"


def test_an_appended_text_must_be_a_rule_file() -> None:
    broken = "[M2]\n#R My-Byl\n1 0 1 0 0\n@RULE My-Byl\n@TABLE\nn_states:2\nnonsense\n"
    with pytest.raises(ValueError, match="rule file"):
        read_multistate_universe(broken)
    with pytest.raises(ValueError, match="rule file"):
        measure_multistate_pattern(broken)
    # Node lines after @RULE belong to the rule file, not the tree.
    mine = _my_byl()
    text = "[M2]\n#R My-Byl\n1 0 1 0 0\n" + mine.text
    assert read_multistate_universe(text).universe.population == 1


def test_a_timeline_carries_its_rule_after_its_frame_lines() -> None:
    from heaton_life.ca.ruletable import append_rule, starter_pattern

    mine = _my_byl()
    u = MultiStateHashLife(mine)
    u.set_rect(0, 0, starter_pattern("Byl-Loop"))
    frames = []
    for _ in range(3):
        frames.append(u.snapshot())
        u.step(4)
    text = append_rule(write_timeline(u, frames), mine)
    timeline = read_timeline(text)
    assert timeline.universe.rule == "My-Byl" and len(timeline.frames) == 3


# -- converting between the engines (spec/hashlife-multistate.md) ------------------------------


def _soup(seed: int, height: int = 50, width: int = 60, states: int = 2) -> NDArray[np.uint8]:
    rng = np.random.default_rng(seed)
    cells = (rng.random((height, width)) < 0.35) * rng.integers(1, states, (height, width))
    return cells.astype(np.uint8)


def test_a_two_state_world_converts_to_history_and_super() -> None:
    two = HashLife("B36/S23", max_memory_mb=64)
    two.set_rect(-30, -20, _soup(3))
    two.step(17)
    before = two.to_macrocell()
    for rule in ("B36/S23History", "b36/s23super"):
        many = two.to_multistate(rule)
        assert (many.generation, many.population, many.max_memory_mb) == (17, two.population, 64)
        box = two.bounding_box()
        assert box is not None and many.bounding_box() == box
        assert np.array_equal(many.get_rect(*box), two.get_rect(*box))
        assert many.zoom_order == ()
    assert two.to_macrocell() == before  # the old universe is unchanged
    assert two.to_multistate("B36/S23History", max_memory_mb=20).max_memory_mb == 20


def test_on_cells_convert_back_and_run_the_base_rule() -> None:
    two = HashLife()
    two.set_rect(-30, -20, _soup(4))
    history = two.to_multistate("B3/S23History")
    two.step(40)
    history.step(40)
    back = history.to_two_state("B3/S23")
    assert back.generation == 40 and back.to_macrocell() == two.to_macrocell()
    assert history.population > back.population  # the envelope was dead cells there


def test_super_converts_to_history_by_parity() -> None:
    sup = MultiStateHashLife("B3/S23Super")
    cells = np.arange(26, dtype=np.uint8).reshape(2, 13)
    sup.set_rect(0, 0, cells)
    history = sup.to_multistate("B3/S23History")
    expect = np.where(cells < 7, cells, cells & 1)
    assert np.array_equal(history.get_rect(0, 0, 12, 1), expect)
    assert sup.to_multistate("B3/S23Super").to_macrocell() == sup.to_macrocell()
    with pytest.raises(ValueError, match="holds state"):  # the rule alone can't take them
        sup.rule = "B3/S23History"


def test_small_and_far_worlds_convert() -> None:
    tiny = MultiStateHashLife("B3/S23History")
    tiny.set_cell(0, 1, 5)  # a level-2 root
    two = tiny.to_two_state("B36/S23")
    assert (two.get_cell(0, 1), two.population, two.rule) == (1, 1, "B36/S23")
    far = MultiStateHashLife.from_macrocell(
        "\n".join(
            ["[M2]", "#R LifeSuper", "#G 99", "1 0 25 3 0"]
            + [f"{k} {k - 1} 0 0 0" for k in range(2, 90)]
        )
    )
    converted = far.to_two_state("B3/S23")
    assert converted.bounding_box() == far.bounding_box() and converted.generation == 99
    assert converted.population == 2
    assert converted.to_multistate("B3/S23History").population == 2


@pytest.mark.parametrize(
    ("make", "match"),
    [
        (lambda: HashLife().to_multistate("B2/S/C3"), "no History or Super rule"),
        (lambda: HashLife().to_multistate("WireWorld"), "no History or Super rule"),
        (lambda: MultiStateHashLife("B2/S/C3").to_two_state("B3/S23"), "no History or Super"),
        (lambda: MultiStateHashLife("WireWorld").to_multistate("LifeHistory"), "no History"),
        (lambda: MultiStateHashLife("LifeHistory").to_multistate("B2/S/C3"), "no History"),
        (lambda: MultiStateHashLife("LifeHistory").to_two_state("LifeHistory"), "7 states"),
        (lambda: HashLife("B0123478/S01234678").to_multistate("LifeHistory"), "background"),
        (lambda: MultiStateHashLife("LifeHistory").to_two_state("B0/S8"), "background"),
    ],
)
def test_conversions_that_have_no_meaning_are_refused(
    make: Callable[[], object], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        make()


def test_a_b0_world_converts_where_its_background_is_dead() -> None:
    two = HashLife("B0/S")  # B0 without Smax: dead at even generations
    two.set_rect(0, 0, np.array([[1, 1]], np.uint8))
    two.step(2)
    assert two.background == 0
    many = two.to_multistate("B3/S23History")
    assert many.population == two.population
    two.step(1)
    with pytest.raises(ValueError, match="background"):
        two.to_multistate("B3/S23History")
    history = MultiStateHashLife("LifeHistory")
    history.set_cell(0, 0, 1)
    history.set_generation(4)
    assert history.to_two_state("B0/S").population == 1  # dead at generation 4
    history.set_generation(5)
    with pytest.raises(ValueError, match="background"):
        history.to_two_state("B0/S")
