"""Grid topologies (spec/topology.md): where a point past an edge lands, the halo, the
grids that step through it, and the bounded-grid suffix read and written in RLE. The
vectors in vectors/topology/ pin the same; these tests check it independently."""

from __future__ import annotations

import itertools

import numpy as np
import pytest
from numpy.typing import NDArray

from heaton_life.ca import Elementary, LifeLike, Wireworld
from heaton_life.ca.hashlife import HashLife, read_universe
from heaton_life.core import (
    BoundedGrid,
    Halo,
    Topology,
    TopologyError,
    moore_index,
    moore_sum,
    parse_bounded_grid,
    split_rule_suffix,
    try_parse_bounded_grid,
)
from heaton_life.core.topology import MAX_SIDE, _locate_many
from heaton_life.init import measure_pattern, read_pattern, rle_decode, rle_encode, rle_measure
from heaton_life.init.seeding import soup

FLAT = [
    Topology("torus"),
    Topology("torus", 3, "x"),
    Topology("torus", -5, "x"),
    Topology("torus", 2, "y"),
    Topology("klein", 0, "x"),
    Topology("klein", 0, "y"),
    Topology("klein", 1, "x"),
    Topology("klein", -3, "y"),
]
EVERY = [Topology("dead"), *FLAT, Topology("cross"), Topology("sphere")]


def _sizes(topology: Topology) -> list[tuple[int, int]]:
    sizes = [(1, 1), (2, 3), (5, 4), (4, 5), (6, 6), (7, 7), (8, 6)]
    fits = []
    for width, height in sizes:
        try:
            topology.check(width, height)
        except ValueError:
            continue
        fits.append((width, height))
    return fits


# -- where a point lands ------------------------------------------------------------------


@pytest.mark.parametrize("topology", EVERY, ids=repr)
def test_the_halo_holds_what_locate_gives(topology: Topology) -> None:
    for width, height in _sizes(topology):
        for radius in (1, 2, 3):
            if topology.boundary in ("cross", "sphere") and radius > min(width, height):
                with pytest.raises(TopologyError) as error:
                    Halo(topology, width, height, radius)
                assert error.value.reason == "the halo is deeper than the grid"
                continue
            sources = Halo(topology, width, height, radius).sources()
            assert sources.shape == (height + 2 * radius, width + 2 * radius)
            for row, column in itertools.product(*map(range, sources.shape)):
                cell = topology.locate(column - radius, row - radius, width, height)
                expected = -1 if cell is None else cell[1] * width + cell[0]
                assert sources[row, column] == expected, (width, height, radius, row, column)


def _cross_one_edge(
    topology: Topology, x: int, y: int, n_w: int, n_h: int, first: str
) -> tuple[int, int]:
    """Cross one edge the point lies beyond, the ``first`` axis's when it lies beyond one of
    those: the cross-surface's and the sphere's single crossings as spec/topology.md words
    them (the cross-surface mirrors the other coordinate; the sphere folds top onto left and
    right onto bottom)."""
    beyond_x = x < 0 or x >= n_w
    beyond_y = y < 0 or y >= n_h
    across_x = beyond_x and (first == "x" or not beyond_y)
    if topology.boundary == "cross":
        if across_x:
            return (x + n_w if x < 0 else x - n_w), n_h - 1 - y
        return n_w - 1 - x, (y + n_h if y < 0 else y - n_h)
    n = n_w  # a sphere
    if across_x:
        return (y, -1 - x) if x < 0 else (y, 2 * n - 1 - x)
    return (-1 - y, x) if y < 0 else (2 * n - 1 - y, x)


@pytest.mark.parametrize("boundary", ["cross", "sphere"])
def test_past_a_corner_either_edge_may_be_crossed_first(boundary: str) -> None:
    """The cross-surface and the sphere aren't flat at their corners, yet a point past a
    corner lands where crossing its two edges in either order lands it (spec/topology.md)."""
    topology = Topology(boundary)  # type: ignore[arg-type]
    for width, height in _sizes(topology):
        reach = min(width, height)
        for x, y in itertools.product(range(-reach, width + reach), range(-reach, height + reach)):
            if 0 <= x < width and 0 <= y < height:
                continue
            landed = topology.locate(x, y, width, height)
            for first in ("x", "y"):
                point = (x, y)
                for _ in range(4):
                    if 0 <= point[0] < width and 0 <= point[1] < height:
                        break
                    point = _cross_one_edge(topology, *point, width, height, first)
                assert point == landed, (boundary, width, height, x, y, first)


def test_the_vectorized_locate_is_the_scalar_one() -> None:
    for topology in EVERY:
        for width, height in _sizes(topology):
            reach = min(width, height) if topology.boundary in ("cross", "sphere") else 9
            points = [
                (x, y)
                for x in range(-reach, width + reach)
                for y in range(-reach, height + reach)
                if not (0 <= x < width and 0 <= y < height)
            ]
            xs = np.array([p[0] for p in points], dtype=np.int64)
            ys = np.array([p[1] for p in points], dtype=np.int64)
            cx, cy, valid = _locate_many(topology, xs, ys, width, height)
            for i, (x, y) in enumerate(points):
                cell = topology.locate(x, y, width, height)
                assert (cell is None) == (not valid[i])
                if cell is not None:
                    assert cell == (cx[i], cy[i]), (topology, width, height, x, y)


def test_the_sphere_folds_the_top_onto_the_left() -> None:
    """The 3 × 3 sphere's halo, letter by letter (A is the top-left cell, I the
    bottom-right): leaving across the top at column c comes in across the left at row c."""
    letters = np.frombuffer(b"ABCDEFGHI", dtype=np.uint8).reshape(3, 3)
    halo = Halo(Topology("sphere"), 3, 3).fill(letters)
    rows = [bytes(row).decode("ascii") for row in halo]
    assert rows == ["AADGC", "AABCG", "BDEFH", "CGHII", "GCFII"]


def test_the_cross_surface_and_klein_bottle_mirror_their_twisted_edges() -> None:
    letters = np.frombuffer(b"ABCDEFGHIJKL", dtype=np.uint8).reshape(3, 4)

    def rows(topology: Topology) -> list[str]:
        return [bytes(r).decode("ascii") for r in Halo(topology, 4, 3).fill(letters)]

    assert rows(Topology("cross")) == ["ALKJID", "LABCDI", "HEFGHE", "DIJKLA", "IDCBAL"]
    assert rows(Topology("klein")) == ["ILKJIL", "DABCDA", "HEFGHE", "LIJKLI", "ADCBAD"]
    assert rows(Topology("klein", axis="y")) == [
        "DIJKLA",
        "LABCDI",
        "HEFGHE",
        "DIJKLA",
        "LABCDI",
    ]
    # A shift along x: leaving across the bottom moves a cell one column right.
    assert rows(Topology("torus", 1)) == ["KLIJKL", "DABCDA", "HEFGHE", "LIJKLI", "ABCDAB"]


# -- the grids ------------------------------------------------------------------------------


def _unfolded(
    topology: Topology, cells: NDArray[np.uint8], copies: int
) -> tuple[NDArray[np.uint8], tuple[slice, slice]]:
    """The plane around a flat topology's grid, every point holding the cell it stands for,
    out to ``copies`` grids in every direction; and where the grid itself sits in it."""
    height, width = cells.shape
    big_w, big_h = width * (2 * copies + 1), height * (2 * copies + 1)
    plane = np.zeros((big_h, big_w), dtype=np.uint8)
    for y in range(big_h):
        for x in range(big_w):
            cell = topology.locate(x - copies * width, y - copies * height, width, height)
            assert cell is not None
            plane[y, x] = cells[cell[1], cell[0]]
    middle = (
        slice(copies * height, copies * height + height),
        slice(copies * width, copies * width + width),
    )
    return plane, middle


@pytest.mark.parametrize("topology", FLAT, ids=repr)
def test_a_flat_topology_runs_as_its_unfolded_plane(topology: Topology) -> None:
    """The torus and the Klein bottle, shifted or not, are the plane folded up: a soup run
    on the topology equals the soup's unfolding run on a large plane, in the middle copy,
    for as many generations as the dead edges of that plane need to reach it."""
    for width, height in ((12, 10), (10, 12)):
        topology.check(width, height)
        start = soup((width, height), density=0.4, seed=width * 7 + height)
        world = LifeLike("B3/S23", size=(width, height), init=start, **_kwargs(topology))
        plane, middle = _unfolded(topology, start, copies=2)
        flat = LifeLike("B3/S23", size=plane.shape[::-1], init=plane, boundary="dead")
        for _ in range(min(width, height)):
            world.step()
            flat.step()
            assert np.array_equal(world.state, flat.state[middle])


@pytest.mark.parametrize("topology", FLAT, ids=repr)
def test_wireworld_runs_as_its_unfolded_plane_too(topology: Topology) -> None:
    width, height = 12, 10
    topology.check(width, height)
    # Every Wireworld state, from two PCG32 soups.
    start = soup((width, height), density=0.5, seed=1) + 2 * soup(
        (width, height), density=0.5, seed=2
    )
    world = Wireworld(size=(width, height), init=start, **_kwargs(topology))
    plane, middle = _unfolded(topology, start, copies=2)
    flat = Wireworld(size=plane.shape[::-1], init=plane, boundary="dead")
    for _ in range(height):
        world.step()
        flat.step()
        assert np.array_equal(world.state, flat.state[middle])


def _kwargs(topology: Topology) -> dict[str, object]:
    return {"boundary": topology.boundary, "shift": topology.shift, "axis": topology.axis}


def test_the_torus_and_the_plane_read_their_neighbors_as_they_always_did() -> None:
    """The halo refactor guard: torus indices are np.roll's, dead ones a zero pad's."""
    grid = soup((23, 17), density=0.45, seed=5)
    cells = grid.astype(np.uint16)
    rolled = np.zeros(grid.shape, dtype=np.uint16)
    padded = np.zeros((19, 25), dtype=np.uint16)
    padded[1:-1, 1:-1] = cells
    dead = np.zeros(grid.shape, dtype=np.uint16)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            weight = 4 - 3 * dy - dx
            rolled |= np.roll(cells, (-dy, -dx), axis=(0, 1)) << weight
            dead |= padded[1 + dy : 18 + dy, 1 + dx : 24 + dx] << weight
    assert np.array_equal(moore_index(grid, "torus"), rolled)
    assert np.array_equal(moore_index(grid, "dead"), dead)
    sums = sum(
        np.roll(grid, (dy, dx), axis=(0, 1)) for dy, dx in itertools.product((-1, 0, 1), repeat=2)
    )
    assert np.array_equal(moore_sum(grid, "torus"), sums - grid)


def test_a_glider_crossing_a_shifted_edge_comes_back_shifted() -> None:
    """spec/lifelike.md's oracle: across the bottom edge of a torus shifted 5 along x, a
    glider heading down and right comes back across the top 5 columns farther right."""
    glider = np.array([[0, 1, 0], [0, 0, 1], [1, 1, 1]], dtype=np.uint8)
    start = np.zeros((16, 20), dtype=np.uint8)
    start[10:13, 4:7] = glider
    plain = LifeLike("B3/S23", size=(20, 16), init=start)
    shifted = LifeLike("B3/S23", size=(20, 16), init=start, shift=5)
    plain.step(24)  # 6 cells down and right: across the bottom edge, rows 0..2 again
    shifted.step(24)
    assert np.array_equal(np.roll(plain.state, 5, axis=1), shifted.state)


def test_a_glider_crossing_a_twisted_edge_comes_back_mirrored() -> None:
    glider = np.array([[0, 1, 0], [0, 0, 1], [1, 1, 1]], dtype=np.uint8)
    start = np.zeros((16, 20), dtype=np.uint8)
    start[10:13, 4:7] = glider
    klein = LifeLike("B3/S23", size=(20, 16), init=start, boundary="klein")
    klein.step(24)
    plane = np.zeros((32, 20), dtype=np.uint8)  # the same run where nothing folds
    plane[10:13, 4:7] = glider
    unfolded = LifeLike("B3/S23", size=(20, 32), init=plane, boundary="dead")
    unfolded.step(24)
    # The glider crossed the bottom edge: it is the plane's, mirrored left to right.
    assert np.array_equal(klein.state, unfolded.state[16:32, ::-1])


# -- params and errors ------------------------------------------------------------------------


def test_an_axis_that_means_nothing_reads_back_as_x() -> None:
    assert Topology("torus", 0, "y").axis == "x"
    assert Topology("sphere", 0, "y").axis == "x"
    assert Topology("klein", 0, "y").axis == "y"
    life = LifeLike("B3/S23", size=(8, 8), boundary="torus", axis="y")
    assert (life.params.boundary, life.params.shift, life.params.axis) == ("torus", 0, "x")
    assert life.topology == Topology("torus")


@pytest.mark.parametrize(
    ("arguments", "size", "reason"),
    [
        (
            ("moebius",),
            (8, 8),
            "unknown boundary 'moebius': expected dead, torus, klein, cross or sphere",
        ),
        (("torus", 0, "z"), (8, 8), "unknown axis 'z': expected x or y"),
        (("dead", 1), (8, 8), "the plane has no shift"),
        (("cross", 2), (8, 8), "the cross-surface has no shift"),
        (("sphere", -1), (8, 8), "the sphere has no shift"),
        (("sphere",), (8, 9), "a sphere is square"),
        (("klein", 1, "x"), (9, 8), "a Klein bottle shifts only a side of even length"),
        (("klein", 1, "y"), (8, 9), "a Klein bottle shifts only a side of even length"),
        (("torus",), (0, 8), "a grid has at least one row and one column"),
    ],
)
def test_a_topology_that_is_none_says_why(
    arguments: tuple[object, ...], size: tuple[int, int], reason: str
) -> None:
    with pytest.raises(TopologyError) as error:
        Topology(*arguments).check(*size)  # type: ignore[arg-type]
    assert error.value.reason == reason
    assert str(error.value) == f"invalid topology: {reason} (spec/topology.md)"
    if "boundary" not in reason and "axis" not in reason and "no shift" not in reason:
        with pytest.raises(ValueError, match="spec/topology.md"):
            LifeLike(
                "B3/S23",
                size=size,
                init="single",
                **dict(zip(("boundary", "shift", "axis"), arguments)),
            )  # type: ignore[arg-type]


def test_a_klein_bottle_may_shift_an_odd_side_only_without_a_shift() -> None:
    Topology("klein", 0, "x").check(9, 8)
    Topology("klein", 2, "x").check(10, 7)


def test_elementary_keeps_its_two_ends() -> None:
    with pytest.raises(ValueError, match="'torus' or 'dead'"):
        Elementary(30, size=(16, 8), boundary="klein")


# -- the suffix --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "canonical", "size", "topology"),
    [
        (":T30,20", ":T30,20", (30, 20), Topology("torus")),
        (":t30+0,20", ":T30,20", (30, 20), Topology("torus")),
        (":T30+5,20", ":T30+5,20", (30, 20), Topology("torus", 5, "x")),
        (":T30,20-2", ":T30,20-2", (30, 20), Topology("torus", -2, "y")),
        (":T030,0020", ":T30,20", (30, 20), Topology("torus")),
        (":P30,20", ":P30,20", (30, 20), Topology("dead")),
        (":p7", ":P7,7", (7, 7), Topology("dead")),
        (":K30*,20", ":K30*,20", (30, 20), Topology("klein", 0, "x")),
        (":K30,20*", ":K30,20*", (30, 20), Topology("klein", 0, "y")),
        (":K30*+1,20", ":K30*+1,20", (30, 20), Topology("klein", 1, "x")),
        (":K30,20*-4", ":K30,20*-4", (30, 20), Topology("klein", -4, "y")),
        (":k30*", ":K30*,30", (30, 30), Topology("klein", 0, "x")),
        (":K30*,20+0", ":K30*,20", (30, 20), Topology("klein", 0, "x")),
        (":C30,20", ":C30,20", (30, 20), Topology("cross")),
        (":S30", ":S30", (30, 30), Topology("sphere")),
        (":s30,30", ":S30", (30, 30), Topology("sphere")),
        (":T30+5", ":T30+5,30", (30, 30), Topology("torus", 5, "x")),
        (
            f":T{MAX_SIDE},1-{MAX_SIDE}",
            f":T{MAX_SIDE},1-{MAX_SIDE}",
            (MAX_SIDE, 1),
            Topology("torus", -MAX_SIDE, "y"),
        ),
    ],
)
def test_a_suffix_reads_and_writes_canonically(
    text: str, canonical: str, size: tuple[int, int], topology: Topology
) -> None:
    grid = parse_bounded_grid(text)
    assert (grid.width, grid.height, grid.topology) == (*size, topology)
    assert grid.suffix == str(grid) == canonical
    assert parse_bounded_grid(canonical) == grid


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("T30,20", "a bounded grid starts with ':'"),
        ("", "a bounded grid starts with ':'"),
        (":", "expected P, T, K, C or S after ':'"),
        (":X30,20", "expected P, T, K, C or S after ':'"),
        (":ſ30", "expected P, T, K, C or S after ':'"),  # 'ſ' uppercases to 'S'
        (":T", "expected a number after 'T'"),
        (":T,20", "expected a number after 'T'"),
        (":T30,", "expected a number after ','"),
        (":T30+,20", "expected a number after '+'"),
        (":T30,20-", "expected a number after '-'"),
        (":T٣٠,20", "expected a number after 'T'"),  # Arabic-Indic digits
        (":T30,20,10", "unexpected ',10' in the bounded grid"),
        (":T30 ,20", "unexpected ' ,20' in the bounded grid"),
        (":K30+1*,20", "unexpected '*,20' in the bounded grid"),
        (":P30+1,20", "the plane has no shift or twist"),
        (":C30*,20", "the cross-surface has no shift or twist"),
        (":S30-1", "the sphere has no shift or twist"),
        (":T30*,20", "a torus has no twist"),
        (":T30+5,20-2", "a torus shifts one side only"),
        (":K30,20", "a Klein bottle twists one side: '*' after its width or its height"),
        (":K30*,20*", "a Klein bottle twists one side: '*' after its width or its height"),
        (":K30*,20+1", "a Klein bottle shifts only its twisted side"),
        (":T0,20", "a side of 0 (an unbounded strip or tube) is not supported"),
        (":P30,0", "a side of 0 (an unbounded strip or tube) is not supported"),
        (":T2000000001,20", "a side or a shift is at most 2000000000"),
        (":T30+99999999999999999999,20", "a side or a shift is at most 2000000000"),
        (":S30,20", "a sphere is square"),
        (":K31*+1,20", "a Klein bottle shifts only a side of even length"),
    ],
)
def test_a_suffix_that_is_none_says_why(text: str, reason: str) -> None:
    assert try_parse_bounded_grid(text) == (None, reason)
    with pytest.raises(ValueError) as error:
        parse_bounded_grid(text)
    assert str(error.value) == f"invalid bounded grid '{text}': {reason} (spec/topology.md)"


def test_a_rule_text_splits_at_its_first_colon() -> None:
    assert split_rule_suffix("B3/S23") == ("B3/S23", None)
    assert split_rule_suffix("B3/S23:T30,20") == ("B3/S23", parse_bounded_grid(":T30,20"))
    assert split_rule_suffix(" B3 / S23 :K8*,6 　") == (" B3 / S23 ", parse_bounded_grid(":K8*,6"))
    assert split_rule_suffix("WireWorld:P40,30")[0] == "WireWorld"
    with pytest.raises(ValueError, match="expected P, T, K, C or S"):
        split_rule_suffix("B3/S23:")
    with pytest.raises(ValueError, match=r"unexpected ':T20,20'"):
        split_rule_suffix("B3/S23:T30,20:T20,20")


# -- RLE ---------------------------------------------------------------------------------------


GLIDER_BO = "x = 3, y = 3, rule = B3/S23:T30,20\nBOB$2BO$3O!\n"


def test_a_suffix_leaves_the_dialect_to_the_rule() -> None:
    """Uppercase B and O are dead and alive under a Life-like rule, whatever follows it."""
    grid, rule = rle_decode(GLIDER_BO)
    assert rule == "B3/S23"
    assert grid.tolist() == [[0, 1, 0], [0, 0, 1], [1, 1, 1]]
    extent = rle_measure(GLIDER_BO)
    assert extent.bounded_grid == parse_bounded_grid(":T30,20")
    assert not extent.extended
    wire, wire_rule = rle_decode("x = 3, y = 1, rule = WireWorld:P10,4\nCBA!\n")
    assert wire_rule == "WireWorld" and wire.tolist() == [[3, 2, 1]]


def test_a_world_writes_its_suffix_and_reads_back_as_itself() -> None:
    for topology in EVERY:
        size = (12, 12) if topology.boundary == "sphere" else (12, 10)
        world = soup(size, density=0.3, seed=3)
        text = rle_encode(world, "b3/s32", topology=topology)
        expected = BoundedGrid(*size, topology)
        assert (
            text.splitlines()[0] == f"x = {size[0]}, y = {size[1]}, rule = B3/S23{expected.suffix}"
        )
        found = read_pattern(text)
        assert found.bounded_grid == expected
        assert (found.x, found.y) == (-(size[0] // 2), -(size[1] // 2))
        assert found.rule == "B3/S23"
        assert np.array_equal(found.cells, world)
        extent = measure_pattern(text)
        assert (extent.width, extent.height, extent.x, extent.y) == (*size, found.x, found.y)
        assert extent.bounded_grid == expected


def test_a_bounded_pattern_is_centered_in_its_world_without_a_position() -> None:
    found = read_pattern(GLIDER_BO)
    assert found.cells.shape == (20, 30)
    assert (found.x, found.y) == (-15, -10)
    # The 3 × 3 pattern's top-left sits at (-1, -1): world cell (14, 9).
    assert found.cells[9:12, 14:17].tolist() == [[0, 1, 0], [0, 0, 1], [1, 1, 1]]
    assert int(found.cells.sum()) == 5
    trimmed = read_pattern(GLIDER_BO, trim=True)
    assert (trimmed.x, trimmed.y, trimmed.cells.shape) == (-1, -1, (3, 3))
    assert trimmed.bounded_grid == found.bounded_grid


def test_a_bounded_pattern_goes_where_its_position_says() -> None:
    text = "#CXRLE Pos=-15,7\n" + GLIDER_BO
    found = read_pattern(text)
    assert found.cells[17:20, 0:3].tolist() == [[0, 1, 0], [0, 0, 1], [1, 1, 1]]
    assert int(found.cells.sum()) == 5
    with pytest.raises(ValueError, match="reaches past its bounded grid"):
        read_pattern("#CXRLE Pos=-15,8\n" + GLIDER_BO)
    with pytest.raises(ValueError, match="reaches past its bounded grid"):
        measure_pattern("#CXRLE Pos=-16,0\n" + GLIDER_BO)
    with pytest.raises(ValueError, match="reaches past its bounded grid"):
        read_pattern("#CXRLE Pos=-16,0\n" + GLIDER_BO, trim=True)


def test_a_dead_margin_may_reach_past_the_world() -> None:
    text = "x = 40, y = 3, rule = B3/S23:P30,20\n19b3o!\n"
    found = read_pattern(text)  # the pattern's top-left at (-20, -1): its live cells fit
    assert found.cells.shape == (20, 30)
    assert found.cells[9, 14:17].tolist() == [1, 1, 1]


def test_a_run_count_of_any_length_places_in_its_world() -> None:
    """A dead run 5,001 digits long: centered, it widens the pattern past any world; placed
    by its position, the live cell after it lands where it says (as .NET's walker reads it)."""
    run = "1" + "0" * 5000
    body = f"x = 3, y = 3, rule = B3/S23:T30,20\n{run}b$bo!\n"
    with pytest.raises(ValueError, match="reaches past its bounded grid"):
        read_pattern(body)
    found = read_pattern("#CXRLE Pos=-15,-10\n" + body)
    assert (found.x, found.y, found.cells.shape) == (-15, -10, (20, 30))
    assert found.cells[1, 1] == 1 and int(found.cells.sum()) == 1


def test_the_universe_has_no_bounded_grid() -> None:
    with pytest.raises(ValueError, match="no bounded grid"):
        read_universe(GLIDER_BO)
    with pytest.raises(ValueError, match="no bounded grid"):
        HashLife.from_rle(GLIDER_BO)
    u = HashLife()
    with pytest.raises(ValueError, match="no bounded grid"):
        u.read_snapshot(GLIDER_BO)


def test_a_bad_suffix_is_an_error_of_the_decode() -> None:
    with pytest.raises(ValueError, match="invalid bounded grid"):
        rle_decode("x = 3, y = 3, rule = B3/S23:T0,20\nbo$2bo$3o!\n")
    with pytest.raises(ValueError, match="invalid bounded grid"):
        read_pattern("x = 3, y = 3, rule = B3/S23:Q\nbo$2bo$3o!\n")
