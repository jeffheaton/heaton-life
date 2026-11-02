"""The giant HashLife patterns (spec/hashlife.md): the Caterpillar and Annelid land where
the Macrocell placement puts them and come back to themselves, moved, after one period.

Neither file has a stated license, so neither is committed: tools/fetch_patterns.py
downloads pinned copies into a git-ignored cache, and these tests run only when
HEATON_LIFE_PATTERNS points at it (they skip otherwise). Each period builds 12 to 17
million nodes in pure Python: about a minute and 4 GB of memory per giant
(python/DEVELOPMENT.md, "HashLife giants").
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from heaton_life.ca.hashlife import HashLife

pytestmark = pytest.mark.slow

BUDGET_MB = 8000  # one period fits without collecting
TIGHT_MB = 1500  # the Caterpillar's 2^8 sub-step overflows: abandon, collect, halve
CATERPILLAR = (11_967_399, (0, 0, 4194, 330_720))  # population, inclusive box
ANNELID = (168_807_151, (-3_511_772, -224, 1_653_126, 16_698_877))


def _load(name: str, budget: int = BUDGET_MB) -> HashLife:
    cache = os.environ.get("HEATON_LIFE_PATTERNS")
    if not cache:
        pytest.skip("HEATON_LIFE_PATTERNS is not set; run tools/fetch_patterns.py")
    path = Path(cache) / name
    if not path.is_file():
        pytest.skip(f"{name} is not in {cache}; run tools/fetch_patterns.py")
    return HashLife.from_file(path, max_memory_mb=budget)


def _regions(u: HashLife, box: tuple[int, int, int, int], n: int) -> list[list[int]]:
    """Populations of an n × n grid of regions splitting ``box`` (integer edges)."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0 + 1, y1 - y0 + 1
    xs = [x0 + i * w // n for i in range(n + 1)]
    ys = [y0 + j * h // n for j in range(n + 1)]
    return [
        [u.population_in(xs[i], ys[j], xs[i + 1] - 1, ys[j + 1] - 1) for i in range(n)]
        for j in range(n)
    ]


def _live_cell(u: HashLife, x0: int, y0: int, x1: int, y1: int) -> tuple[int, int]:
    """A live cell of the inclusive rectangle, found by halving it (it must hold one)."""
    while (x0, y0) != (x1, y1):
        if x1 - x0 >= y1 - y0:
            mid = (x0 + x1) // 2
            x0, x1 = (x0, mid) if u.population_in(x0, y0, mid, y1) else (mid + 1, x1)
        else:
            mid = (y0 + y1) // 2
            y0, y1 = (y0, mid) if u.population_in(x0, y0, x1, mid) else (mid + 1, y1)
    return x0, y0


def test_caterpillar_lands_at_the_origin() -> None:
    """The Macrocell placement of a level-20 root puts the published file's top-left cell at
    (0, 0): the one-row y offset of spec/hashlife.md "Tree coordinates"."""
    u = _load("caterpillar.mc")
    assert (u.population, u.bounding_box()) == CATERPILLAR
    assert u.generation == 0


@pytest.mark.parametrize("budget", [BUDGET_MB, TIGHT_MB], ids=["roomy", "tight"])
def test_caterpillar_moves_102_cells_up_every_270_generations(budget: int) -> None:
    """17c/45: after one period every row is the row 102 below it at generation 0. Under
    the tight budget the period also takes the memory path of spec/hashlife.md "Memory"
    (abandon the sub-step, collect, halve), which must not change a cell."""
    u = _load("caterpillar.mc", budget)
    start = u.snapshot()
    u.step(270)
    population, (x0, y0, x1, y1) = CATERPILLAR
    assert u.generation == 270
    assert u.population == population
    assert u.bounding_box() == (x0, y0 - 102, x1, y1 - 102)
    assert (u.collections > 0) == (budget == TIGHT_MB)
    end = u.snapshot()
    strip = 1 << 14  # 4,195 × 16,384 cells per comparison
    for top in range(y0, y1 + 1, strip):
        bottom = min(top + strip - 1, y1)
        u.restore(start)
        before = u.get_rect(x0, top, x1, bottom)
        u.restore(end)
        after = u.get_rect(x0, top - 102, x1, bottom - 102)
        assert np.array_equal(before, after), f"rows {top}..{bottom} differ"


def test_annelid_lands_on_its_measured_box() -> None:
    u = _load("annelid.mc.gz")
    assert (u.population, u.bounding_box()) == ANNELID
    assert u.rule == "B3/S23"


def test_annelid_moves_9_left_84_up_every_252_generations() -> None:
    """(28,3)c/84: one period moves the ship (−9, −84). The whole 169-million-cell state is
    too big to compare cell for cell here, so the check is a 128 × 128 grid of region
    populations relative to the box, plus 512 × 512 windows compared exactly around a
    live cell of every occupied region on the grid's diagonals."""
    u = _load("annelid.mc.gz")
    population, box = ANNELID
    n = 128
    before = _regions(u, box, n)
    x0, y0, x1, y1 = box
    w, h = x1 - x0 + 1, y1 - y0 + 1
    cells = []
    for i in range(n):
        for j in (i, n - 1 - i):
            if before[j][i]:
                cx0, cy0 = x0 + i * w // n, y0 + j * h // n
                cx1, cy1 = x0 + (i + 1) * w // n - 1, y0 + (j + 1) * h // n - 1
                cells.append(_live_cell(u, cx0, cy0, cx1, cy1))
    assert len(cells) >= 8
    windows = [u.get_rect(x - 255, y - 255, x + 256, y + 256) for x, y in cells]

    u.step(252)
    dx, dy = -9, -84
    assert u.generation == 252
    assert u.population == population
    assert u.bounding_box() == (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
    assert _regions(u, (x0 + dx, y0 + dy, x1 + dx, y1 + dy), n) == before
    for (x, y), window in zip(cells, windows, strict=True):
        moved = u.get_rect(x + dx - 255, y + dy - 255, x + dx + 256, y + dy + 256)
        assert np.array_equal(window, moved), f"the window around ({x}, {y}) differs"
