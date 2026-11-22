"""The rule-table family (spec/ruletable.md): the starter set against its publications' figures
and definitions, the grid family's inits, edits and topologies, and rule tables on the
unbounded plane and in files."""

from __future__ import annotations

import numpy as np
import pytest

from heaton_life.ca.hashlife import MultiStateHashLife
from heaton_life.ca.hashlife.universe import StepCanceled
from heaton_life.ca.rulefile import RuleFileError, parse_rule_file
from heaton_life.ca.ruletable import (
    STARTER_RULES,
    RuleTableCA,
    RuleTableParams,
    append_rule,
    embedded_rule,
    rule_table_soup,
    starter_pattern,
    starter_rule,
)
from heaton_life.ca.state_rules import state_rule
from heaton_life.core.rng import Pcg32
from heaton_life.init import rle_encode
from heaton_life.init.patterns import compatible

# Fig. 6 and Fig. 9 of Langton (1984): the loop at time 0, and the loop and its offspring at
# time 151, as printed (0 is blank).
LANGTON_FIG6 = [
    " 22222222",
    "2170140142",
    "2022222202",
    "272    212",
    "212    212",
    "202    212",
    "272    212",
    "21222222122222",
    "207107107111112",
    " 2222222222222",
]
LANGTON_FIG9 = [
    "        2",
    "       212",
    "       272",
    "       202",
    "       212",
    " 222222272  22222222",
    "2111701702 2170140142",
    "2122222212 2022222202",
    "212    272 272    212",
    "202    202 212    212",
    "242    212 202    212",
    "212    272 272    212",
    "2022222202 21222222122222",
    "2410710712 207107107111112",
    " 22222222   2222222222222",
]
# Fig. 3 of Byl (1989), every time step as printed (its second "time = 11" is time 12).
BYL_FIG3 = [
    [" 22", "2312", "2342", " 25"],
    [" 22", "2142", "2332", " 225"],
    [" 22", "2432", "2133", " 225"],
    [" 22", "2332", "24131", " 225"],
    [" 22", "2312", "23413", " 2252"],
    [" 22", "2142", "233311", " 2242"],
    [" 22", "2432", "21333", " 22422"],
    [" 22", "2332", "241333", " 22422"],
    [" 22", "2312 1", "2341331", " 22422"],
    [" 22", "2142 3", "2334133", " 224222"],
    [" 22  1", "2432", "21334131", " 224222"],
    [" 22", "2332  1", "24133413", " 2242222"],
    [" 22", "2312   1", "234133411", " 2242222"],
    [" 22", "2142 1", "23341334", " 22422222"],
    [" 22", "2432 31", "213341332", " 22422222"],
    [" 22  1", "2332   1", "241334132", " 2242222"],
    [" 22", "2312   32", "234133412", " 2242222"],
    [" 22    1", "2142 1 12", "233413342", " 2242222"],
    [" 22     2", "2432 3 42", "213341332", " 2242222"],
    [" 22  1 22", "2332   32", "241334132", " 2242222"],
    [" 22    2", "2312  132", "234133412", " 2242222"],
    [" 22   22", "2142 5112", "233413342", " 2242222"],
    [" 22   22", "2432 2142", "213345332", " 2242222"],
    [" 22   22", "2332 2432", "241352132", " 2242522"],
    [" 22   22", "2312 2332", "2345 2412", " 2242 52"],
    [" 22   22", "2145 2312", "2332 2342", " 22 2 25"],
    [" 225  22", "2432 2142", "2132 2332", " 22   225"],
    [" 235  22", "2332 2432", "2412 2133", " 22   225"],
]


def _grid(rows: list[str]) -> np.ndarray:
    width = max(len(row) for row in rows)
    grid = np.zeros((len(rows), width), np.uint8)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            grid[y, x] = 0 if ch == " " else int(ch)
    return grid


def _trimmed(cells: np.ndarray) -> np.ndarray:
    ys, xs = np.nonzero(cells)
    return cells[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


def _text(cells: np.ndarray) -> list[str]:
    return ["".join(" " if v == 0 else str(v) for v in row).rstrip() for row in cells]


def _placed(pattern: np.ndarray, size: tuple[int, int], at: tuple[int, int]) -> np.ndarray:
    grid = np.zeros((size[1], size[0]), np.uint8)
    grid[at[1] : at[1] + pattern.shape[0], at[0] : at[0] + pattern.shape[1]] = pattern
    return grid


def _components(cells: np.ndarray) -> int:
    seen = np.zeros(cells.shape, bool)
    count = 0
    for y, x in zip(*np.nonzero(cells), strict=True):
        if seen[y, x]:
            continue
        count += 1
        stack = [(y, x)]
        seen[y, x] = True
        while stack:
            cy, cx = stack.pop()
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if (
                    0 <= ny < cells.shape[0]
                    and 0 <= nx < cells.shape[1]
                    and cells[ny, nx]
                    and not seen[ny, nx]
                ):
                    seen[ny, nx] = True
                    stack.append((ny, nx))
    return count


# -- the starter set ---------------------------------------------------------------------


def test_the_starter_set() -> None:
    assert STARTER_RULES == (
        "Langtons-Loops", "Byl-Loop", "Evoloop", "Langtons-Ant", "Ant-LLRR", "Ant-RLR",
    )  # fmt: skip
    expected = {
        "Langtons-Loops": (8, "vonNeumann", "rotate4"),
        "Byl-Loop": (6, "vonNeumann", "rotate4"),
        "Evoloop": (9, "vonNeumann", "rotate4"),
        "Langtons-Ant": (10, "vonNeumann", "none"),
        "Ant-LLRR": (20, "vonNeumann", "none"),
        "Ant-RLR": (15, "vonNeumann", "none"),
    }
    for name, (states, neighborhood, symmetries) in expected.items():
        rule = starter_rule(name)
        assert rule.name == name and rule.source == "table" and rule.neighbors == 4
        assert (rule.states, rule.neighborhood, rule.symmetries) == (
            states,
            neighborhood,
            symmetries,
        )
        assert rule.next_state(0, 0, 0, 0, 0, 0, 0, 0, 0) == 0
        assert starter_rule(name.upper()) is rule and state_rule(f" {name.lower()} ") is rule
        assert len(rule.names) == states
        pattern = starter_pattern(name)
        assert pattern.max() < states and pattern is not starter_pattern(name)
    assert np.array_equal(starter_pattern("Langtons-Loops"), _grid(LANGTON_FIG6))
    assert np.array_equal(starter_pattern("Evoloop"), _grid(LANGTON_FIG6))
    assert np.array_equal(starter_pattern("Byl-Loop"), _grid(BYL_FIG3[0])[:, ::-1])
    for name, ant in (("Langtons-Ant", 2), ("Ant-LLRR", 4), ("Ant-RLR", 3)):
        assert starter_pattern(name).tolist() == [[ant]]
    with pytest.raises(ValueError, match="not in the starter set"):
        starter_rule("Codd")


def test_langtons_loop_reproduces_as_figure_9_shows() -> None:
    world = RuleTableCA(
        "Langtons-Loops", size=(48, 40), init=_placed(_grid(LANGTON_FIG6), (48, 40), (8, 14))
    )
    world.step(151)
    assert np.array_equal(_trimmed(world.state), _grid(LANGTON_FIG9))


def test_byls_loop_runs_as_figure_3_shows_mirrored() -> None:
    world = RuleTableCA(
        "Byl-Loop", size=(30, 30), init=_placed(starter_pattern("Byl-Loop"), (30, 30), (13, 13))
    )
    for t, rows in enumerate(BYL_FIG3):
        assert _text(_trimmed(world.state[:, ::-1])) == rows, t
        world.step()


def _sayama(rows: list[str]) -> dict[tuple[int, ...], int]:
    """Table 2 of Sayama (2004) with its rotations, read from the rule file's six-digit lines."""
    table: dict[tuple[int, ...], int] = {}
    for line in rows:
        c, t, r, b, left, out = (int(ch) for ch in line)
        for key in ((c, t, r, b, left), (c, left, t, r, b), (c, b, left, t, r), (c, r, b, left, t)):
            table.setdefault(key, out)
    return table


def test_the_evoloop_runs_as_sayamas_appendix_says() -> None:
    text = starter_rule("Evoloop").text
    lines = [ln for ln in text.split("\n") if len(ln) == 6 and ln.isdigit()]
    assert len(lines) == 258
    table = _sayama(lines)

    def next_state(c: int, t: int, r: int, b: int, left: int) -> int:
        if (c, t, r, b, left) in table:
            return table[(c, t, r, b, left)]
        if c == 8:
            return 0
        around = (t, r, b, left)
        if 8 in around:
            if c in (0, 1):
                return 8 if any(2 <= v <= 7 for v in around) else c
            return 0 if c in (2, 3, 5) else 1
        return 0 if c == 0 else 8

    cells = _placed(starter_pattern("Evoloop"), (72, 72), (20, 30))
    world = RuleTableCA("Evoloop", size=(72, 72), init=cells)
    padded = np.zeros((74, 74), np.uint8)
    for generation in range(1, 211):
        padded[1:-1, 1:-1] = cells
        cells = np.array(
            [
                [
                    next_state(
                        int(padded[y, x]),
                        int(padded[y - 1, x]),
                        int(padded[y, x + 1]),
                        int(padded[y + 1, x]),
                        int(padded[y, x - 1]),
                    )
                    for x in range(1, 73)
                ]
                for y in range(1, 73)
            ],
            np.uint8,
        )
        world.step()
        assert np.array_equal(world.state, cells), generation
        if generation in (127, 128):
            # The first offspring separates at generation 128 (spec/ruletable.md).
            assert _components(world.state) == (1 if generation == 127 else 2)


def _ant(turns: str, steps: int, size: tuple[int, int]) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """A direct simulation of the ant (spec/ruletable.md "The ants") from the cell where the
    starter init puts it, facing north: its cells, and where it was after each step."""
    k = len(turns)
    width, height = size
    colors = np.zeros((height, width), np.int64)
    x, y, d = (width - 1) // 2, (height - 1) // 2, 0
    path = [(x, y)]
    for _ in range(steps):
        color = colors[y, x]
        d = (d + (1 if turns[color] == "R" else 3)) % 4
        colors[y, x] = (color + 1) % k
        x += (0, 1, 0, -1)[d]
        y += (-1, 0, 1, 0)[d]
        path.append((x, y))
    cells = colors.copy()
    cells[y, x] = k + 4 * colors[y, x] + d
    return cells.astype(np.uint8), path


@pytest.mark.parametrize(
    ("name", "turns", "steps", "size"),
    [
        ("Langtons-Ant", "RL", 2500, (60, 50)),
        ("Ant-LLRR", "LLRR", 4000, (32, 32)),
        ("Ant-RLR", "RLR", 3000, (40, 40)),
    ],
)
def test_the_ants_run_as_their_definitions_say(
    name: str, turns: str, steps: int, size: tuple[int, int]
) -> None:
    world = RuleTableCA(name, size=size, init="starter")
    world.step(steps)
    cells, _ = _ant(turns, steps, size)
    assert np.array_equal(world.state, cells)


def test_langtons_ant_builds_its_highway() -> None:
    _, path = _ant("RL", 11000, (80, 56))
    moved = [(path[t + 104][0] - path[t][0], path[t + 104][1] - path[t][1]) for t in range(10896)]
    assert all(m == (-2, 2) for m in moved[9976:])  # every 104 steps, two cells diagonally
    assert moved[9975] != (-2, 2)  # and not before step 9,976 (the published 9,977)


def test_llrr_grows_symmetrically() -> None:
    world = RuleTableCA("Ant-LLRR", size=(32, 32), init="starter")
    world.step(4000)
    colors = np.where(world.state >= 4, (world.state - 4) // 4, world.state)
    box = _trimmed(colors)
    assert np.array_equal(box, box[:, ::-1]) or np.array_equal(box, box[::-1, :])


# -- the grid family ---------------------------------------------------------------------


def test_inits() -> None:
    world = RuleTableCA("Byl-Loop", size=(10, 9), init="starter")
    assert np.array_equal(world.state, _placed(starter_pattern("Byl-Loop"), (10, 9), (3, 2)))
    assert RuleTableCA("Evoloop", size=(9, 9), init="blank").state.sum() == 0
    soup = RuleTableCA("Evoloop", size=(20, 10), init="soup", density=0.4, seed=5).state
    draws = Pcg32(5).fill_u32(200).reshape(10, 20).astype(np.int64)
    expected = np.where(draws < int(0.4 * 2**32), 1 + draws % 8, 0)
    assert np.array_equal(soup, expected) and soup.max() == 8
    assert np.array_equal(rule_table_soup((20, 10), 9, density=0.4, seed=5), soup)
    with pytest.raises(ValueError, match="bigger than"):
        RuleTableCA("Langtons-Loops", size=(14, 20), init="starter")
    with pytest.raises(ValueError, match="no starter pattern"):
        RuleTableCA(parse_rule_file(starter_rule("Byl-Loop").text.replace("Byl-Loop", "B", 1)))
    with pytest.raises(ValueError, match="unknown init"):
        RuleTableCA("Byl-Loop", init="clock")
    with pytest.raises(ValueError, match="states 0 to 5"):
        RuleTableCA("Byl-Loop", size=(4, 4), init=np.full((4, 4), 6, np.uint8))
    copy = parse_rule_file(starter_rule("Byl-Loop").text)  # the same rule, read again
    assert RuleTableCA(copy, size=(8, 8)).state.any()


def test_reset_set_state_and_params() -> None:
    world = RuleTableCA("Evoloop", size=(16, 16), init="soup", seed=3)
    start = world.state.copy()
    world.step(5)
    assert world.generation == 5
    world.reset()
    assert np.array_equal(world.state, start) and world.generation == 0
    world.reset(seed=4)
    assert world.params.seed == 4 and not np.array_equal(world.state, start)
    cells = np.full((16, 16), 2, np.uint8)
    world.set_state(cells, generation=7)
    assert world.generation == 7 and world.params.init == "array"
    world.set_state(np.zeros((16, 16), np.uint8), keep_start=True)
    world.reset()
    assert np.array_equal(world.state, cells)
    with pytest.raises(ValueError):
        world.set_state(np.full((16, 16), 9, np.uint8))
    with pytest.raises(ValueError):
        world.set_state(np.zeros((15, 16), np.uint8))
    params = RuleTableParams.from_dict(world.params.to_dict() | {"init": "blank"})
    again = RuleTableCA.from_params(params)
    assert again.params == params and again.rule is starter_rule("Evoloop")
    custom = parse_rule_file(
        "@RULE Mine\n@TABLE\nn_states:3\nneighborhood:Moore\nsymmetries:none\n"
    )
    mine = RuleTableCA.from_params(params.replace(rule="mine"), rule=custom)
    assert mine.rule is custom and mine.params.rule == "Mine"
    with pytest.raises(ValueError, match="not the params"):
        RuleTableCA.from_params(params, rule=custom)
    with pytest.raises(ValueError, match="init='array'"):
        RuleTableCA.from_params(params.replace(init="array"))


def test_frame_states_and_topology() -> None:
    world = RuleTableCA("Langtons-Loops", size=(20, 16), boundary="klein", shift=2, axis="y")
    assert np.array_equal(world.frame(), world.state) and world.frame() is not world.state
    assert world.states == 8 and world.topology.boundary == "klein"
    assert world.params.boundary == "klein" and world.params.shift == 2


def test_clear_and_advance() -> None:
    world = RuleTableCA("Langtons-Loops", size=(40, 40), init="starter")
    before = world.state.copy()
    world.advance_selection(10, 10, 30, 30, 20)
    assert world.generation == 0 and not np.array_equal(world.state, before)
    region = world.state[10:31, 10:31].copy()
    alone = RuleTableCA("Langtons-Loops", size=(40, 40), init=np.where(
        np.pad(np.ones((21, 21), bool), ((10, 9), (10, 9))), before, 0).astype(np.uint8))  # fmt: skip
    alone.step(20)
    assert np.array_equal(region, alone.state[10:31, 10:31])
    world.clear_rect(0, 0, 39, 39)
    assert world.state.sum() == 0

    world.set_state(before)
    steps = 0
    own_step = world.step

    def step_then_cancel(n: int = 1) -> None:  # cancel() as another thread would, mid-run
        nonlocal steps
        own_step(n)
        steps += 1
        if steps == 3:
            world.cancel()

    world.step = step_then_cancel  # type: ignore[method-assign]
    with pytest.raises(StepCanceled):
        world.advance_outside(0, 0, 5, 5, 10**9)
    assert steps == 3 and np.array_equal(world.state, before) and world.generation == 0


def test_stamps_check_the_states() -> None:
    pattern = np.array([[5, 7]], np.uint8)
    assert compatible("ruletable", "ruletable", pattern, 8) is None
    assert compatible("ruletable", "ruletable", pattern, 6) == (
        "pattern uses state 7, target has only 6 states"
    )
    assert compatible("ruletable", "wireworld", pattern) is not None


# -- the plane and files -----------------------------------------------------------------


def test_the_plane_runs_a_loop_as_the_grid_does() -> None:
    loop = _grid(LANGTON_FIG6)
    universe = MultiStateHashLife("Langtons-Loops")
    universe.set_rect(-999_999_007, 99, loop)
    world = RuleTableCA("Langtons-Loops", size=(48, 40), init=_placed(loop, (48, 40), (8, 14)))
    for generation in (1, 40, 151, 200):
        universe.step(generation - universe.generation)
        world.step(generation - world.generation)
        x0, y0 = -999_999_007 - 8, 99 - 14
        assert np.array_equal(universe.get_rect(x0, y0, x0 + 47, y0 + 39), world.state)
        assert universe.population == int(np.count_nonzero(world.state))


def test_the_plane_refuses_a_background_that_changes() -> None:
    flash = parse_rule_file(
        "@RULE Flash\n@TABLE\nn_states:2\nneighborhood:vonNeumann\nsymmetries:none\n0,0,0,0,0,1\n"
    )
    with pytest.raises(ValueError, match="background would change"):
        MultiStateHashLife(flash)
    world = RuleTableCA(flash, size=(5, 4), init="blank")
    world.step()
    assert world.state.all()  # a grid runs it as written


def test_a_rule_appended_to_an_rle_file() -> None:
    mine = parse_rule_file(
        starter_rule("Byl-Loop").text.replace("@RULE Byl-Loop", "@RULE My-Byl", 1)
    )
    rle = rle_encode(starter_pattern("Byl-Loop"), "My-Byl")
    text = append_rule(rle, mine)
    assert text == rle + mine.text
    found = embedded_rule(text)
    assert found is not None and found.tree_text() == mine.tree_text()
    assert embedded_rule(rle) is None
    assert embedded_rule("x = 1, y = 1, rule = A!B\nA!\n") is None  # a '!' in the header's rule
    universe = MultiStateHashLife.from_rle(text)
    assert universe.rule == "My-Byl" and universe.population == 12
    given = MultiStateHashLife.from_rle(text, rule=starter_rule("Byl-Loop"))
    assert given.rule == "My-Byl"  # the appended rule, not the reader's of another name
    broken = rle + "@RULE Broken\n@TABLE\nn_states:1\n"
    with pytest.raises(RuleFileError, match="n_states"):
        embedded_rule(broken)
    with pytest.raises(ValueError):
        MultiStateHashLife.from_rle(rle)  # My-Byl names no rule the reader knows


def test_default_palettes() -> None:
    from heaton_life.render import (
        default_palette,
        default_zoom_order,
        frame_values,
        multistate_palette,
        rule_table_palette,
    )

    for name in STARTER_RULES:  # no starter file gives colors: the multi-state palette
        rule = starter_rule(name)
        grid = RuleTableCA(rule, size=(8, 8), init="blank")
        expected = multistate_palette(rule.states)
        assert np.array_equal(default_palette(grid), expected)
        assert np.array_equal(default_palette(MultiStateHashLife(rule)), expected)
        assert frame_values(grid) == tuple(range(rule.states))
        assert default_zoom_order(grid) == ()
    colored = parse_rule_file(
        "@RULE C\n@TABLE\nn_states:4\nneighborhood:Moore\nsymmetries:none\n"
        "@COLORS\n3 1 2 3\n0 0 0 30 60 90\n2 5 5 5\n"
    )
    palette = rule_table_palette(colored)
    assert palette[:4].tolist() == [[0, 0, 0], [0, 0, 0], [5, 5, 5], [30, 60, 90]]
    assert not palette[4:].any()
    with pytest.raises(TypeError):
        rule_table_palette("C")
