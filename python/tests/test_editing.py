"""Editing primitives (spec/patterns.md "Extract and stamp", "Editing a region";
spec/hashlife.md "Editing"): paste modes, the counter-clockwise turn, random fill, Advance
Selection and Advance Outside on grids and in HashLife, and HashLife's rectangle tools."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray

from heaton_life.ca import Cyclic, LifeLike, Wireworld, clock_loop
from heaton_life.ca.hashlife import (
    EDIT_LIMIT,
    MAX_LEVEL,
    HashLife,
    HashLifeMemoryError,
    StepCanceled,
)
from heaton_life.ca.hashlife.universe import turn_center
from heaton_life.init import (
    BUILTIN_PATTERNS,
    fill_random,
    flip_h,
    rotate90,
    rotate90_ccw,
    soup,
    stamp,
)

GLIDER = np.array([[0, 1, 0], [0, 0, 1], [1, 1, 1]], dtype=np.uint8)


def _builtin(name: str) -> NDArray[np.uint8]:
    return next(p for p in BUILTIN_PATTERNS if p.name == name).cells()


def _noise(height: int, width: int, seed: int) -> NDArray[np.uint8]:
    """Incompressible 0/1 test input from an integer hash (simulation randomness stays
    PCG32)."""
    mask = np.uint64(0xFFFFFFFF)
    v = (
        np.arange(height * width, dtype=np.uint64) * np.uint64(0x9E3779B1) + np.uint64(seed)
    ) & mask
    v ^= v >> np.uint64(15)
    v = (v * np.uint64(0x85EBCA6B)) & mask
    v ^= v >> np.uint64(13)
    v = (v * np.uint64(0xC2B2AE35)) & mask
    v ^= v >> np.uint64(16)
    return ((v >> np.uint64(31)) & np.uint64(1)).astype(np.uint8).reshape(height, width)


# -- grids: transforms and stamping -----------------------------------------------------------


def test_rotate90_ccw_undoes_rotate90() -> None:
    pattern = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint8)
    assert rotate90_ccw(pattern).tolist() == [[3, 6], [2, 5], [1, 4]]
    assert np.array_equal(rotate90_ccw(rotate90(pattern)), pattern)
    assert np.array_equal(rotate90(rotate90_ccw(pattern)), pattern)
    assert np.array_equal(rotate90_ccw(pattern), rotate90(rotate90(rotate90(pattern))))
    rgb = np.arange(2 * 3 * 3, dtype=np.uint8).reshape(2, 3, 3)
    assert np.array_equal(rotate90(rotate90_ccw(rgb)), rgb)  # channels move as one cell


def test_stamp_modes_combine_two_state_cells() -> None:
    target = _noise(9, 11, 1)
    piece = _noise(5, 7, 2)
    for mode in ("copy", "or", "xor", "and"):
        got = target.copy()
        stamp(got, piece, 3, 2, torus=False, mode=mode)  # type: ignore[arg-type]
        want = target.copy()
        region = want[2:7, 3:10]
        if mode == "copy":
            region[:] = piece
        elif mode == "or":
            region |= piece
        elif mode == "xor":
            region ^= piece
        else:
            region &= piece
        assert np.array_equal(got, want), mode
    # Wrapping: every pattern cell lands somewhere, and xor toggles accumulate.
    got = np.zeros((3, 3), np.uint8)
    stamp(got, np.ones((4, 4), np.uint8), 0, 0, torus=True, mode="xor")
    counts = np.zeros((3, 3), np.int64)
    for r in range(4):
        for c in range(4):
            counts[r % 3, c % 3] += 1
    assert np.array_equal(got, (counts % 2).astype(np.uint8))
    # Clipping drops what falls off a dead edge.
    got = np.ones((3, 3), np.uint8)
    stamp(got, np.zeros((2, 2), np.uint8), 2, 2, torus=False, mode="and")
    assert got.sum() == 8 and got[2, 2] == 0


def test_transparent_is_mode_or() -> None:
    target = np.full((4, 4), 2, np.uint8)  # multi-state: or overlays nonzero cells
    a, b = target.copy(), target.copy()
    stamp(a, GLIDER * 3, 1, 1, torus=True, transparent=True)
    stamp(b, GLIDER * 3, 1, 1, torus=True, mode="or")
    assert np.array_equal(a, b) and a[1, 1] == 2 and a[1, 2] == 3
    with pytest.raises(ValueError, match="mode 'or'"):
        stamp(a, GLIDER, 0, 0, torus=True, transparent=True, mode="xor")
    with pytest.raises(ValueError, match="unknown stamp mode"):
        stamp(a, GLIDER, 0, 0, torus=True, mode="nand")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="2-D"):
        stamp(
            np.zeros((4, 4, 3), np.uint8), np.ones((2, 2, 3), np.uint8), 0, 0, torus=True, mode="or"
        )


@pytest.mark.parametrize("mode", ["xor", "and"])
def test_two_state_modes_refuse_other_values_unchanged(mode: Any) -> None:
    grid = np.zeros((4, 4), np.uint8)
    grid[3, 3] = 2  # under the pattern only when it wraps
    before = grid.copy()
    stamp(grid, GLIDER, 0, 0, torus=False, mode=mode)  # the 2 lies outside: fine
    grid = before.copy()
    with pytest.raises(ValueError, match="two-state"):
        stamp(grid, GLIDER, 2, 2, torus=True, mode=mode)
    assert np.array_equal(grid, before)
    with pytest.raises(ValueError, match="two-state"):
        stamp(grid, GLIDER * 2, 0, 0, torus=False, mode=mode)
    assert np.array_equal(grid, before)


# -- grids: random fill -----------------------------------------------------------------------


def test_fill_random_is_the_soup_of_the_region() -> None:
    life = LifeLike("B3/S23", size=(30, 20), init="soup", density=0.6, seed=4)
    before = life.state.copy()
    life.step(3)
    stepped = life.state.copy()
    life.fill_random(5, 3, 16, 14, 0.35, 99)
    want = stepped.copy()
    want[3:15, 5:17] = soup((12, 12), density=0.35, seed=99)
    assert np.array_equal(life.state, want) and life.generation == 3
    # The draws depend on the region's size alone: HashLife fills alike anywhere.
    u = HashLife()
    u.fill_random(-1000, 77, -989, 88, 0.35, 99)
    assert np.array_equal(u.get_rect(-1000, 77, -989, 88), want[3:15, 5:17])
    # A fill of the whole grid with the grid's own seed is its soup.
    whole = LifeLike("B3/S23", size=(30, 20), init="soup", density=0.6, seed=4)
    whole.step(1)
    whole.fill_random(0, 0, 29, 19, 0.6, 4)
    assert np.array_equal(whole.state, before)


@pytest.mark.parametrize(
    "rect", [(-1, 0, 3, 3), (0, 0, 30, 3), (5, 5, 4, 5), (0, 3, 3, 2), (0, 0, 0, 20)]
)
def test_regions_lie_inside_the_grid(rect: tuple[int, int, int, int]) -> None:
    life = LifeLike("B3/S23", size=(30, 20), init="soup", seed=1)
    before = life.state.copy()
    for call in (
        lambda: life.fill_random(*rect, 0.5, 1),
        lambda: life.advance_selection(*rect, 2),
        lambda: life.advance_outside(*rect, 2),
    ):
        with pytest.raises(ValueError, match="region"):
            call()
        assert np.array_equal(life.state, before) and life.generation == 0
    with pytest.raises(ValueError, match="density"):
        fill_random(life.state, 0, 0, 3, 3, density=1.5, seed=1)
    with pytest.raises(ValueError, match="two-state"):
        fill_random(np.zeros((4, 4, 3), np.uint8), 0, 0, 1, 1, density=0.5, seed=1)


# -- grids: Advance Selection and Advance Outside ----------------------------------------------


def _advanced_by_hand(
    make: Callable[[NDArray[np.uint8]], Any],
    state: NDArray[np.uint8],
    rect: tuple[int, int, int, int],
    n: int,
    outside: bool,
) -> NDArray[np.uint8]:
    """The spec's definition, spelled out: a blanked copy run n generations, then merged."""
    x0, y0, x1, y1 = rect
    region = (slice(y0, y1 + 1), slice(x0, x1 + 1))
    copy = state.copy()
    if outside:
        copy[region] = 0
    else:
        copy = np.zeros_like(state)
        copy[region] = state[region]
    world = make(copy)
    world.step(n)
    result = np.asarray(world.state).copy()
    if outside:
        result[region] = state[region]
        return result
    merged = state.copy()
    merged[region] = result[region]
    return merged


_WORLDS: list[tuple[str, Callable[[NDArray[np.uint8]], Any], NDArray[np.uint8]]] = [
    (
        "life-torus",
        lambda g: LifeLike("B36/S23", size=(24, 18), init=g, boundary="torus"),
        _noise(18, 24, 5),
    ),
    (
        "life-dead",
        lambda g: LifeLike("B3/S23", size=(24, 18), init=g, boundary="dead"),
        _noise(18, 24, 6),
    ),
    (
        "life-b0",
        lambda g: LifeLike("B0123478/S01234678", size=(20, 16), init=g, boundary="torus"),
        _noise(16, 20, 7),
    ),
    (
        "wireworld",
        lambda g: Wireworld(size=(20, 20), init=g, boundary="dead"),
        clock_loop((20, 20), margin=1),
    ),
    (
        "cyclic",
        lambda g: Cyclic(4, size=(20, 16), init=g),
        (_noise(16, 20, 8) + 2 * _noise(16, 20, 9)).astype(np.uint8),
    ),
]


@pytest.mark.parametrize("name,make,state", _WORLDS, ids=[w[0] for w in _WORLDS])
@pytest.mark.parametrize("outside", [False, True])
def test_advance_is_a_blanked_copy_merged_back(
    name: str, make: Callable[[NDArray[np.uint8]], Any], state: NDArray[np.uint8], outside: bool
) -> None:
    for rect, n in (((3, 2, 12, 9), 7), ((0, 0, 5, 15), 4), ((8, 1, 8, 1), 1), ((2, 3, 9, 7), 0)):
        world = make(state.copy())
        world.step(2)
        stepped = np.asarray(world.state).copy()
        if outside:
            world.advance_outside(*rect, n)
        else:
            world.advance_selection(*rect, n)
        want = _advanced_by_hand(make, stepped, rect, n, outside)
        assert np.array_equal(world.state, want), (name, rect, n)
        assert world.generation == 2


def test_advance_selection_on_a_big_dead_grid_is_hashlifes_isolated_plane() -> None:
    soup_cells = _noise(30, 40, 11)
    world = LifeLike(
        "B3/S23", size=(200, 160), init=np.zeros((160, 200), np.uint8), boundary="dead"
    )
    world.state[60:90, 80:120] = soup_cells
    u = HashLife()
    u.set_rect(-20, -15, soup_cells)
    world.advance_selection(85, 65, 114, 84, 30)
    u.advance_selection(-15, -10, 14, 9, 30)
    assert np.array_equal(world.state[60:90, 80:120], u.get_rect(-20, -15, 19, 14))


def test_advance_on_a_torus_wraps_back_into_the_region() -> None:
    grid = np.zeros((8, 8), np.uint8)
    grid[0:3, 0:3] = GLIDER
    life = LifeLike("B3/S23", size=(8, 8), init=grid, boundary="torus")
    plain = LifeLike("B3/S23", size=(8, 8), init=grid, boundary="torus")
    # A glider period carries it (1, 1) cells; 32 generations carry it once round the
    # torus, out of the region and back in.
    life.advance_selection(0, 0, 3, 3, 32)
    plain.step(32)
    assert np.array_equal(life.state, plain.state) and life.generation == 0
    # The whole grid: n plain generations, the counter untouched; its outside is empty.
    life.advance_selection(0, 0, 7, 7, 5)
    plain.step(5)
    assert np.array_equal(life.state, plain.state) and life.generation == 0
    before = life.state.copy()
    life.advance_outside(0, 0, 7, 7, 9)
    assert np.array_equal(life.state, before)


def test_advance_outside_keeps_the_region_frozen() -> None:
    life = LifeLike("B3/S23", size=(30, 30), init=np.zeros((30, 30), np.uint8), boundary="dead")
    life.state[10:13, 10:13] = np.ones((3, 3), np.uint8)  # would explode if advanced
    life.state[0:3, 20:23] = GLIDER
    life.advance_outside(9, 9, 13, 13, 12)
    assert life.state[10:13, 10:13].sum() == 9 and life.generation == 0
    assert life.state[3:6, 23:26].sum() == 5  # the glider moved (3, 3)
    with pytest.raises(ValueError, match="backward"):
        life.advance_outside(9, 9, 13, 13, -1)


# -- HashLife: paste and, generation, queries -------------------------------------------------


def test_paste_and_matches_numpy() -> None:
    u = HashLife()
    u.set_rect(-37, -21, _noise(60, 80, 3))
    mirror = u.get_rect(-37, -21, 42, 38).copy()
    for i in range(6):
        piece = _noise(13 + 3 * i, 29 - 2 * i, 20 + i)
        px, py = 4 * i + 1, 5 * i + 2
        h, w = piece.shape
        u.set_rect(-37 + px, -21 + py, piece, "and")
        mirror[py : py + h, px : px + w] &= piece
        assert np.array_equal(u.get_rect(-37, -21, 42, 38), mirror), i
    assert u.population == int(mirror.sum())


def test_set_generation_moves_only_the_counter() -> None:
    u = HashLife()
    u.set_rect(0, 0, GLIDER)
    text = u.to_macrocell()
    big = 3**300
    u.set_generation(big)
    assert u.generation == big
    assert u.to_macrocell().replace(f"#G {big}\n", "") == text
    u.set_generation(0)
    assert u.to_macrocell() == text
    with pytest.raises(ValueError, match="negative"):
        u.set_generation(-1)
    with pytest.raises(TypeError):
        u.set_generation(1.5)  # type: ignore[arg-type]


def test_bounding_box_in_matches_the_cells() -> None:
    u = HashLife()
    a = _noise(70, 90, 4)
    u.set_rect(-45, -35, a)
    for x0, y0, x1, y1 in (
        (-45, -35, 44, 34),
        (-30, -10, 3, 7),
        (0, 0, 0, 0),
        (10, -35, 12, 34),
        (-100, -100, -46, 100),
        (44, -35, 200, 34),
    ):
        sub = a[max(y0 + 35, 0) : max(y1 + 36, 0), max(x0 + 45, 0) : max(x1 + 46, 0)]
        ys, xs = np.nonzero(sub)
        ox, oy = max(x0, -45), max(y0, -35)
        want = (
            None if len(xs) == 0 else (ox + xs.min(), oy + ys.min(), ox + xs.max(), oy + ys.max())
        )
        assert u.bounding_box_in(x0, y0, x1, y1) == want, (x0, y0, x1, y1)
    assert u.bounding_box_in(5, 5, 4, 5) is None
    assert u.bounding_box_in(-(10**40), -(10**40), 10**40, 10**40) == u.bounding_box()
    # Far past the editing box: a glider 2^100 cells out.
    far = HashLife()
    far.set_rect(0, 0, GLIDER)
    far.step(4 * 2**100)
    m = 2**100  # the glider's cells: (m+1, m), (m+2, m+1), (m, m+2), (m+1, m+2), (m+2, m+2)
    assert far.bounding_box_in(m - 5, m - 5, m + 1, m + 1) == (m + 1, m, m + 1, m)
    assert far.bounding_box_in(m + 2, m, m + 2, m + 2) == (m + 2, m + 1, m + 2, m + 2)
    assert far.bounding_box_in(m, m + 1, m + 2, m + 2) == (m, m + 1, m + 2, m + 2)
    assert far.bounding_box_in(0, 0, m - 1, m + 9) is None


# -- HashLife: clear outside, turns, and flips ------------------------------------------------


def test_clear_outside_keeps_only_the_rectangle() -> None:
    u = HashLife()
    a = _noise(50, 60, 5)
    u.set_rect(-30, -25, a)
    u.set_cell(EDIT_LIMIT, EDIT_LIMIT, 1)
    u.clear_outside(-10, -5, 12, 9)
    assert u.population == int(a[20:35, 20:43].sum())
    assert np.array_equal(u.get_rect(-10, -5, 12, 9), a[20:35, 20:43])
    with pytest.raises(ValueError, match="empty"):
        u.clear_outside(3, 3, 2, 3)
    with pytest.raises(ValueError, match="editing box"):
        u.clear_outside(0, 0, EDIT_LIMIT + 1, 0)


def _turned_by_hand(
    cells: NDArray[np.uint8], frame: int, rect: tuple[int, int, int, int], kind: str
) -> NDArray[np.uint8]:
    """The spec's maps applied cell by cell to a dense picture of [-frame, frame]²."""
    x0, y0, x1, y1 = rect
    out = cells.copy()
    out[y0 + frame : y1 + frame + 1, x0 + frame : x1 + frame + 1] = 0
    s, d = turn_center(x0, y0, x1, y1)
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if kind == "cw":
                tx, ty = s - y, x + d
            elif kind == "ccw":
                tx, ty = y - d, s - x
            elif kind == "h":
                tx, ty = x0 + x1 - x, y
            else:
                tx, ty = x, y0 + y1 - y
            out[ty + frame, tx + frame] = cells[y + frame, x + frame]
    return out


@pytest.mark.parametrize("kind", ["cw", "ccw", "h", "v"])
def test_turns_and_flips_match_the_maps(kind: str) -> None:
    frame = 70
    for i, (w, h) in enumerate(((7, 4), (4, 7), (6, 6), (5, 8), (9, 2), (1, 1), (1, 6))):
        u = HashLife()
        u.set_rect(-40, -38, _noise(76, 80, 30 + i))
        x0, y0 = (-9 + 5 * i) * (1 if i % 2 else -1), 3 - 4 * i
        rect = (x0, y0, x0 + w - 1, y0 + h - 1)
        before = u.get_rect(-frame, -frame, frame, frame)
        if kind in ("cw", "ccw"):
            new = u.rotate_rect(*rect, clockwise=kind == "cw")
            assert (new[2] - new[0] + 1, new[3] - new[1] + 1) == (h, w)
        else:
            u.flip_rect(*rect, horizontal=kind == "h")
        want = _turned_by_hand(before, frame, rect, kind)
        assert np.array_equal(u.get_rect(-frame, -frame, frame, frame), want), (kind, rect)


@pytest.mark.parametrize(
    "rect,cw,ccw",
    [
        ((0, 0, 1, 0), (0, 0, 0, 1), (0, -1, 0, 0)),  # X odd: about (0, 0), whose x + y is even
        ((1, 0, 2, 0), (2, -1, 2, 0), (2, 0, 2, 1)),  # about (2, 0), not (1, 0)
        ((0, 0, 2, 0), (1, -1, 1, 1), (1, -1, 1, 1)),  # odd × odd: about the center cell
        ((0, 0, 1, 1), (0, 0, 1, 1), (0, 0, 1, 1)),  # even × even: about a cell corner
        ((-3, -2, -2, 0), (-4, -1, -2, 0), (-4, -2, -2, -1)),  # X odd, negative: about (-3, -1)
        ((-2, -3, 0, -2), (-2, -4, -1, -2), (-1, -4, 0, -2)),  # Y odd, negative: about (-1, -3)
    ],
)
def test_turned_rectangles(
    rect: tuple[int, int, int, int],
    cw: tuple[int, int, int, int],
    ccw: tuple[int, int, int, int],
) -> None:
    assert HashLife().rotate_rect(*rect) == cw
    assert HashLife().rotate_rect(*rect, clockwise=False) == ccw


def test_turns_undo_each_other_and_never_drift() -> None:
    for i, (w, h) in enumerate(((3, 2), (2, 3), (5, 2), (4, 4), (1, 4), (6, 3))):
        for x0, y0 in ((0, 0), (1, 0), (0, 1), (-3, 7), (11, -4)):
            u = HashLife()
            u.set_rect(x0 - 3, y0 - 3, _noise(h + 6, w + 6, 50 + i))
            text = u.to_macrocell()
            rect = (x0, y0, x0 + w - 1, y0 + h - 1)
            back = u.rotate_rect(*u.rotate_rect(*rect), clockwise=False)
            assert back == rect
            r = rect
            for _ in range(4):
                r = u.rotate_rect(*r)
            assert r == rect
            u.flip_rect(*rect)
            u.flip_rect(*rect)
            u.flip_rect(*rect, horizontal=False)
            u.flip_rect(*rect, horizontal=False)
            # Turns lift the neighbors under a non-square rectangle's sweep, so only the
            # rectangle's own cells are compared after the round trips.
            ref = HashLife.from_macrocell(text)
            assert np.array_equal(u.get_rect(*rect), ref.get_rect(*rect)), (rect,)


def test_transforms_reach_any_size_and_stop_at_the_box() -> None:
    gun = _builtin("Gosper glider gun")  # 36 × 9
    u = HashLife()
    for x, y in ((-999_999_000, -999_999_000), (999_990_000, 3), (5, 999_999_000), (-7, -7)):
        u.set_rect(x, y, gun)
    pop = u.population
    started = time.perf_counter()
    # X = 0, Y = -1: s = 0, d = 0, so a clockwise turn sends (x, y) to (-y, x).
    r = u.rotate_rect(-EDIT_LIMIT, -EDIT_LIMIT, EDIT_LIMIT, EDIT_LIMIT - 1)
    assert r == (-EDIT_LIMIT + 1, -EDIT_LIMIT, EDIT_LIMIT, EDIT_LIMIT)
    u.flip_rect(-EDIT_LIMIT, -EDIT_LIMIT, EDIT_LIMIT, EDIT_LIMIT, horizontal=False)
    assert time.perf_counter() - started < 10  # the tree, never a dense copy
    assert u.population == pop
    # The gun at (-7, -7) went to (-x, -y) of where it was: turned, then mirrored.
    turned = HashLife()
    turned.set_rect(-1, -28, np.flipud(rotate90(gun)))
    assert np.array_equal(u.get_rect(-50, -50, 50, 50), turned.get_rect(-50, -50, 50, 50))
    text = u.to_macrocell()
    with pytest.raises(ValueError, match="editing box"):  # its new rectangle leaves the box
        u.rotate_rect(EDIT_LIMIT - 9, 0, EDIT_LIMIT, 100)
    with pytest.raises(ValueError, match="empty"):
        u.flip_rect(4, 4, 3, 4)
    assert u.to_macrocell() == text
    mirror = HashLife()
    mirror.set_rect(-1, -1, gun)
    mirror.flip_rect(-1, -1, 34, 7)
    assert np.array_equal(mirror.get_rect(-1, -1, 34, 7), flip_h(gun))


# -- HashLife: Advance Selection and Advance Outside -------------------------------------------


def test_advance_selection_is_an_isolated_plane() -> None:
    for i, rule in enumerate(("B3/S23", "B36/S23", "B2/S")):
        u = HashLife(rule)
        u.set_rect(-20, -20, _noise(41, 41, 60 + i))
        frame = 80
        before = u.get_rect(-frame, -frame, frame, frame)
        rect = (-15 + i, -18, 9, 4 + i)
        u.set_generation(5)
        u.advance_selection(*rect, 13)
        assert u.generation == 5
        # The plane, approximated by a dead-edged grid the pattern never reaches.
        x0, y0, x1, y1 = (v + frame for v in rect)
        isolated = np.zeros_like(before)
        isolated[y0 : y1 + 1, x0 : x1 + 1] = before[y0 : y1 + 1, x0 : x1 + 1]
        grid = LifeLike(rule, size=before.shape[::-1], init=isolated, boundary="dead")
        grid.step(13)
        want = before.copy()
        want[y0 : y1 + 1, x0 : x1 + 1] = grid.state[y0 : y1 + 1, x0 : x1 + 1]
        assert np.array_equal(u.get_rect(-frame, -frame, frame, frame), want), rule


def test_advance_jumps_like_step() -> None:
    gun = _builtin("Gosper glider gun")
    u = HashLife()
    u.set_rect(0, 0, gun)
    u.set_rect(500, 500, np.ones((2, 2), np.uint8))
    alone = HashLife()
    alone.set_rect(0, 0, gun)
    alone.step(2**40)
    u.advance_selection(-5, -5, 40, 15, 2**40)
    assert np.array_equal(u.get_rect(-5, -5, 40, 15), alone.get_rect(-5, -5, 40, 15))
    assert u.population_in(490, 490, 510, 510) == 4 and u.generation == 0
    # Outside: the gun fires on as if the frozen rectangle were empty.
    v = HashLife()
    v.set_rect(0, 0, gun)
    v.set_rect(100, 100, np.ones((2, 2), np.uint8))
    v.set_cell(103, 100, 1)  # a lone cell that would die if advanced
    v.advance_outside(99, 99, 104, 102, 1000)
    assert v.population_in(99, 99, 104, 102) == 5 and v.get_cell(103, 100) == 1
    fired = HashLife()
    fired.set_rect(0, 0, gun)
    fired.step(1000)
    assert np.array_equal(v.get_rect(-10, -10, 90, 90), fired.get_rect(-10, -10, 90, 90))


@pytest.mark.parametrize(
    "call",
    [
        lambda u: u.advance_selection(0, 0, 10, 10, 2 ** (MAX_LEVEL - 2)),
        lambda u: u.advance_outside(0, 0, 10, 10, -1),
        lambda u: u.advance_selection(0, 0, EDIT_LIMIT + 1, 10, 1),
        lambda u: u.advance_outside(5, 5, 4, 5, 1),
    ],
)
def test_advance_refusals_change_nothing(call: Callable[[HashLife], None]) -> None:
    u = HashLife()
    u.set_rect(0, 0, _builtin("Gosper glider gun"))
    u.step(77)
    before = (u.to_macrocell(), u.generation)
    with pytest.raises(ValueError):
        call(u)
    assert (u.to_macrocell(), u.generation) == before


def test_advance_out_of_memory_leaves_the_universe() -> None:
    u = HashLife(max_memory_mb=10)
    u.fill_random(-700, -700, 700, 700, 0.5, 3)
    before = (u.to_macrocell(), u.generation)
    with pytest.raises(HashLifeMemoryError):
        u.advance_outside(-10, -10, 10, 10, 2**12)
    assert (u.to_macrocell(), u.generation) == before


def test_advance_canceled_leaves_the_universe() -> None:
    u = HashLife()
    u.set_rect(0, 0, _noise(256, 256, 2))
    before = (u.to_macrocell(), u.generation)
    outcome: list[BaseException | None] = []

    def run() -> None:
        try:
            u.advance_outside(100, 100, 120, 120, 2**20 + 1)
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
    assert (u.to_macrocell(), u.generation) == before  # not a sub-step boundary: as it was
