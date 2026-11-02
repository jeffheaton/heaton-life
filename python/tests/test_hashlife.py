"""HashLife (spec/hashlife.md): known answers, the dense engine as oracle, editing in the
±10⁹ box, snapshots, cancellation, and results that never depend on the memory budget."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray

from heaton_life.ca import LifeLike
from heaton_life.ca.hashlife import (
    EDIT_LIMIT,
    HashLife,
    HashLifeMemoryError,
    HashLifeParams,
    LifeView,
    StepCanceled,
    cell_at,
    center_cell,
    centered,
    fit,
    pan,
    zoom_at,
)
from heaton_life.init import BUILTIN_PATTERNS, soup


def _builtin(name: str) -> NDArray[np.uint8]:
    return next(p for p in BUILTIN_PATTERNS if p.name == name).cells()


def _universe(name: str, rule: str = "B3/S23", at: tuple[int, int] = (0, 0)) -> HashLife:
    u = HashLife(rule)
    u.set_rect(at[0], at[1], _builtin(name))
    return u


def _noise(height: int, width: int, seed: int) -> NDArray[np.uint8]:
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
    return ((v >> np.uint64(31)) & np.uint64(1)).astype(np.uint8).reshape(height, width)


def _cells(u: HashLife) -> tuple[tuple[int, int, int, int] | None, bytes]:
    """The whole state as (bounding box, packed cells of the box)."""
    box = u.bounding_box()
    if box is None:
        return None, b""
    return box, np.packbits(u.get_rect(*box)).tobytes()


# -- known answers ---------------------------------------------------------------------------


def test_methuselahs_settle_to_their_populations() -> None:
    r = _universe("R-pentomino")
    r.step(1103)
    assert (r.generation, r.population) == (1103, 116)
    r.step(1000)
    assert r.population == 116
    acorn = _universe("Acorn")
    acorn.step(5206)
    assert acorn.population == 633


def test_glider_crosses_past_64_bit_coordinates() -> None:
    g = _universe("Glider")
    assert g.bounding_box() == (0, 0, 2, 2)
    g.step(4)
    assert g.bounding_box() == (1, 1, 3, 3)
    g.step(2**64 - 4)
    m = 2**62
    assert g.generation == 2**64
    assert g.bounding_box() == (m, m, m + 2, m + 2)
    assert g.population == 5


def test_still_life_and_oscillator() -> None:
    blinker = _universe("Blinker", at=(-1, 0))
    before = _cells(blinker)
    blinker.step(1)
    assert _cells(blinker) != before
    blinker.step(1)
    assert _cells(blinker) == before
    block = _universe("Block")
    block.step(2**40 + 12345)
    assert _cells(block) == (((0, 0, 1, 1)), np.packbits(np.ones((2, 2), np.uint8)).tobytes())


def test_gun_population_grows_without_bound() -> None:
    gun = _universe("Gosper glider gun")
    gun.step(2**200)
    # 2^200 generations at one glider (5 cells) per 30, plus the gun's own cells.
    assert gun.population > 5 * (2**200 // 30)
    box = gun.bounding_box()
    assert box is not None and box[2] > 2**197


# -- the dense engine as oracle ---------------------------------------------------------------

DENSE_CASES = [
    ("B3/S23", 40, [1, 2, 5, 10, 33, 100, 211]),
    ("B36/S23", 40, [1, 3, 17, 64, 150]),
    ("B3678/S34678", 40, [1, 2, 9, 40, 120]),
    ("B3/S12345", 32, [1, 4, 23, 80]),
    ("B2/S", 12, [1, 2, 5, 13, 30, 41]),
    ("B1357/S1357", 12, [1, 3, 7, 15, 31, 45]),
]


@pytest.mark.parametrize(
    ("rule", "start", "checkpoints"), DENSE_CASES, ids=[c[0] for c in DENSE_CASES]
)
def test_agrees_with_the_dense_engine(rule: str, start: int, checkpoints: list[int]) -> None:
    """Mixed step sizes against LifeLike on a dead-boundary grid the pattern never reaches."""
    size = 192
    grid = np.zeros((size, size), np.uint8)
    lo = (size - start) // 2
    grid[lo : lo + start, lo : lo + start] = soup((start, start), density=0.4, seed=11)
    dense = LifeLike(rule, size=(size, size), init=grid, boundary="dead")
    u = HashLife(rule)
    u.set_rect(-90, 7, grid)  # anywhere: the plane has no preferred origin
    current = 0
    for gen in checkpoints:
        dense.step(gen - current)
        u.step(gen - current)
        current = gen
        assert u.generation == gen
        assert np.array_equal(u.get_rect(-90, 7, -90 + size - 1, 7 + size - 1), dense.state), gen
        box = u.bounding_box()
        assert box is not None
        assert box[0] > -90 and box[2] < -90 + size - 1, "pattern reached the dense grid's edge"


# -- editing -----------------------------------------------------------------------------------


def test_cells_round_trip_through_rectangles_anywhere_in_the_box() -> None:
    u = HashLife()
    a = _noise(37, 53, 1)
    for x, y in ((-13, 7), (EDIT_LIMIT - 52, -EDIT_LIMIT), (-EDIT_LIMIT, EDIT_LIMIT - 36)):
        u.set_rect(x, y, a)
        assert np.array_equal(u.get_rect(x, y, x + 52, y + 36), a)
    assert u.population == 3 * int(a.sum())


def test_paste_modes_match_numpy() -> None:
    u = HashLife()
    mirror = np.zeros((70, 90), np.uint8)
    x0, y0 = -40, -33
    for i, mode in enumerate(("copy", "or", "xor", "copy", "xor", "or")):
        piece = _noise(21 + i, 34 - i, 10 + i)
        px, py = 3 * i + 1, 5 * i + 2
        h, w = piece.shape
        region = mirror[py : py + h, px : px + w]
        if mode == "copy":
            region[:] = piece
        elif mode == "or":
            region |= piece
        else:
            region ^= piece
        u.set_rect(x0 + px, y0 + py, piece, mode)  # type: ignore[arg-type]
        assert np.array_equal(u.get_rect(x0, y0, x0 + 89, y0 + 69), mirror), mode
    assert u.population == int(mirror.sum())


def test_set_get_and_clear() -> None:
    u = HashLife()
    u.set_cell(5, -9, True)
    u.set_cell(-1_000_000, 777_777, 1)
    assert u.get_cell(5, -9) == 1 and u.get_cell(-1_000_000, 777_777) == 1
    assert u.get_cell(6, -9) == 0 and u.get_cell(-EDIT_LIMIT, EDIT_LIMIT) == 0
    assert u.bounding_box() == (-1_000_000, -9, 5, 777_777)
    u.set_cell(5, -9, 0)
    assert u.population == 1
    u.set_rect(-20, -20, np.ones((41, 41), np.uint8))
    u.clear_rect(-3, -2, 4, 6)
    assert u.population == 41 * 41 - 8 * 9 + 1
    assert u.population_in(-3, -2, 4, 6) == 0
    u.clear()
    assert u.population == 0 and u.bounding_box() is None


def test_population_and_box_match_the_cells() -> None:
    u = HashLife()
    a = _noise(60, 45, 3)
    u.set_rect(100, -500, a)
    ys, xs = np.nonzero(a)
    assert u.bounding_box() == (100 + xs.min(), -500 + ys.min(), 100 + xs.max(), -500 + ys.max())
    for x0, y0, x1, y1 in ((100, -500, 144, -441), (110, -480, 120, -470), (0, 0, 5, 5)):
        sub = a[max(y0 + 500, 0) : y1 + 501, max(x0 - 100, 0) : x1 - 99]
        assert u.population_in(x0, y0, x1, y1) == int(sub.sum())
    # Queries reach past the editing box.
    assert u.population_in(-(10**30), -(10**30), 10**30, 10**30) == int(a.sum())


def test_fill_random_is_the_lifelike_soup() -> None:
    u = HashLife()
    u.set_rect(-5, -3, np.ones((24, 40), np.uint8))
    u.fill_random(-5, -3, 34, 20, density=0.4, seed=7)
    assert np.array_equal(u.get_rect(-5, -3, 34, 20), soup((40, 24), density=0.4, seed=7))


@pytest.mark.parametrize(
    "call",
    [
        lambda u: u.set_cell(EDIT_LIMIT + 1, 0, 1),
        lambda u: u.get_cell(0, -EDIT_LIMIT - 1),
        lambda u: u.get_rect(EDIT_LIMIT - 1, 0, EDIT_LIMIT + 1, 0),
        lambda u: u.clear_rect(-EDIT_LIMIT - 1, 0, 0, 0),
        lambda u: u.set_rect(EDIT_LIMIT, 0, np.ones((1, 2), np.uint8)),
        lambda u: u.fill_random(0, EDIT_LIMIT, 0, EDIT_LIMIT + 1, 0.5, 1),
    ],
)
def test_editing_stops_at_the_box(call: object) -> None:
    u = HashLife()
    u.set_cell(EDIT_LIMIT, -EDIT_LIMIT, 1)  # the corners themselves are inside
    with pytest.raises(ValueError, match="editing box"):
        call(u)  # type: ignore[operator]
    assert u.population == 1


def test_rules_and_budgets_are_validated() -> None:
    with pytest.raises(ValueError, match="B0"):
        HashLife("B03/S23")
    with pytest.raises(ValueError, match="at least 10"):
        HashLife(max_memory_mb=9)
    u = HashLife.from_params(HashLifeParams(rule="b36 / s32", max_memory_mb=64))
    assert u.params == HashLifeParams(rule="B36/S23", max_memory_mb=64)
    with pytest.raises(ValueError, match="backward"):
        u.step(-1)


def test_rule_changes_keep_the_cells() -> None:
    u = _universe("Replicator (HighLife)")
    u.step(12)
    u.rule = "highlife"
    u.step(20)
    v = _universe("Replicator (HighLife)")
    v.step(12)
    w = HashLife("B36/S23")
    box = v.bounding_box()
    assert box is not None
    w.set_rect(box[0], box[1], v.get_rect(*box))
    w.step(20)
    assert _cells(u) == _cells(w)


# -- snapshots, memory, cancellation ---------------------------------------------------------


def test_snapshots_survive_collection_and_restore() -> None:
    u = _universe("Acorn")
    start = u.snapshot()
    u.step(300)
    mid = u.snapshot()
    middle = _cells(u)
    u.step(700)
    u.collect_garbage()
    u.restore(start)
    assert u.generation == 0 and u.population == 7
    u.restore(mid)
    assert (u.generation, _cells(u)) == (300, middle)
    with pytest.raises(ValueError, match="another universe"):
        HashLife().restore(mid)


def test_results_do_not_depend_on_the_budget() -> None:
    a = _noise(160, 160, 5)
    roomy = HashLife()
    roomy.set_rect(0, 0, a)
    roomy.step(1500)
    tight = HashLife(max_memory_mb=10)
    tight.set_rect(0, 0, a)
    for n in (1, 1, 1000, 498):  # a mix of sub-step sizes under constant pressure
        tight.step(n)
    assert tight.collections > 0
    assert _cells(tight) == _cells(roomy)


def test_a_universe_too_big_for_its_budget_refuses_to_step_unchanged() -> None:
    u = HashLife(max_memory_mb=10)
    u.set_rect(0, 0, _noise(2000, 2000, 9))  # ~83k nodes; loading never fails for budget
    before = (u.generation, _cells(u))
    with pytest.raises(HashLifeMemoryError, match="max_memory_mb=10"):
        u.step(1)
    assert (u.generation, _cells(u)) == before
    u.max_memory_mb = 2000
    u.step(1)
    assert u.generation == 1


def test_cancel_stops_at_a_completed_sub_step() -> None:
    u = HashLife()
    u.set_rect(0, 0, _noise(256, 256, 2))
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
    time.sleep(1.0)  # the first generation takes milliseconds, 2^20 takes far longer
    u.cancel()
    worker.join(timeout=60)
    assert len(outcome) == 1 and isinstance(outcome[0], StepCanceled)
    assert u.generation == 1
    u.step(1)  # a stale request does not leak into the next step
    assert u.generation == 2


# -- files ---------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["gun.rle", "gun.mc", "gun.mc.gz"])
def test_files_round_trip(tmp_path: Path, name: str) -> None:
    u = _universe("Gosper glider gun", at=(-18, -4))
    u.step(777)
    u.save(tmp_path / name)
    back = HashLife.from_file(tmp_path / name)
    assert back.to_macrocell() == u.to_macrocell()
    assert back.generation == 777


def test_save_refuses_unknown_extensions_and_rle_past_the_box(tmp_path: Path) -> None:
    u = HashLife()
    with pytest.raises(ValueError, match="extension"):
        u.save(tmp_path / "gun.cells")
    u.set_cell(EDIT_LIMIT, 0, 1)
    u.step(0)
    far = HashLife.from_macrocell(u.to_macrocell().replace("#R B3/S23", "#R B3/S23\n#C far"))
    assert far.to_rle().startswith(f"#CXRLE Pos={EDIT_LIMIT},0")
    glider = _universe("Glider")
    glider.step(4 * (EDIT_LIMIT + 1))  # it walks out of the box on its own
    with pytest.raises(ValueError, match="Macrocell"):
        glider.to_rle()
    assert HashLife.from_macrocell(glider.to_macrocell()).bounding_box() == glider.bounding_box()


# -- views and frames -------------------------------------------------------------------------


def test_frames_match_the_cells_at_every_scale() -> None:
    u = HashLife()
    u.set_rect(-30, -20, soup((64, 48), density=0.4, seed=2))
    cells = u.get_rect(-40, -31, 59, 48)  # tree rows -32..47: aligned to 2 and 4
    assert np.array_equal(u.render(LifeView(-40, -32, 0), (100, 80)), cells * 255)
    up = u.render(LifeView(-160, -128, 2), (400, 320))
    assert np.array_equal(up, (cells * 255).repeat(4, 0).repeat(4, 1))
    for s in (1, 2):
        f = 1 << s
        pooled = cells.reshape(80 // f, f, 100 // f, f)
        view = LifeView(-40 >> s, -32 >> s, -s)
        size = (100 // f, 80 // f)
        assert np.array_equal(u.render(view, size), pooled.max(axis=(1, 3)) * 255)
        density = (255 * pooled.sum(axis=(1, 3)) + f * f - 1) // (f * f)
        assert np.array_equal(u.render(view, size, "density"), density)
    with pytest.raises(ValueError, match="render mode"):
        u.render(LifeView(0, 0, 0), (4, 4), "sum")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="deepest zoom"):
        LifeView(0, 0, 6)


def test_view_arithmetic_round_trips() -> None:
    for view in (LifeView(-7, 13, 0), LifeView(3**50, -(3**50), -20), LifeView(5, -5, 4)):
        assert pan(pan(view, 9, -4), -9, 4) == view
        if view.mag < 5:
            assert zoom_at(zoom_at(view, 17, 3, 1), 17, 3, -1) == view
    for x, y, mag in ((0, 0, 0), (-17, 23, 4), (5, -1, 5)):
        assert center_cell(centered(x, y, mag, (101, 77)), (101, 77)) == (x, y)
    box = (-1000, -20, 1000, 20)
    view = fit(box, (640, 480))
    corners = [(0, 0), (639, 479)]
    tl, br = (cell_at(view, *c) for c in corners)
    assert tl[0] <= box[0] and tl[1] <= box[1] and br[0] >= box[2] and br[1] >= box[3]
    assert fit((0, 0, 2, 2), (640, 480)).mag == 5
