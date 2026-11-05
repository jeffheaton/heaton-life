"""Pick the glider the zoom lands on (render.py's TARGET and LEAN_CELLS).

Candidates are NW gliders inside the dive metapixel that are in the opening glider's
phase (OOO/O../.O.) on the last frame. Each is followed backward generation by generation
as an isolated glider (an empty ring around its box) to find when it flew free, and the
final 6×6-cell view around it is checked for anything else.

Usage: python pick_glider.py [--board out/board.mc]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from board import GLIDER_NW, OUT, PITCH, life_step
from numpy.typing import NDArray
from render import FPS, N_FRAMES, Schedule, dive_cell, inner_step

from heaton_life.ca.hashlife import HashLife


def phases() -> list[NDArray[np.uint8]]:
    """The NW glider's four phases, each cropped to its box, starting from GLIDER_NW."""
    seed = np.array([[ch == "o" for ch in row] for row in GLIDER_NW], dtype=np.uint8)
    out, g = [], np.pad(seed, 4)
    for _ in range(4):
        ys, xs = np.nonzero(g)
        out.append(g[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1].copy())
        g = life_step(g)
    return out


PHASES = phases()


def nw_gliders(grid: NDArray[np.uint8]) -> list[tuple[int, int, int]]:
    """(phase, x, y) of every isolated NW glider; (x, y) is its box's top-left in ``grid``."""
    hits = []
    h, w = grid.shape
    for k, ph in enumerate(PHASES):
        win = np.pad(ph, 1)
        wh, ww = win.shape
        ok = np.ones((h - wh + 1, w - ww + 1), dtype=bool)
        for dy in range(wh):
            for dx in range(ww):
                ok &= grid[dy : dy + h - wh + 1, dx : dx + w - ww + 1] == win[dy, dx]
        hits += [(k, int(x) + 1, int(y) + 1) for y, x in zip(*np.nonzero(ok))]
    return hits


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--board", type=Path, default=OUT / "board.mc")
    args = ap.parse_args()

    gens, _ = Schedule().plan()
    g_end = int(gens[-1])
    g_from = int(gens[N_FRAMES * 2 // 3])  # follow gliders over the last 20 s
    di, dj = dive_cell(inner_step(g_end))
    x0, y0 = PITCH * di - 16, PITCH * dj - 16
    x1, y1 = x0 + PITCH + 32, y0 + PITCH + 32
    u = HashLife.from_macrocell(args.board.read_text(), max_memory_mb=8000)
    u.step(g_from)
    seen: dict[int, list[tuple[int, int, int]]] = {}
    for g in range(g_from, g_end + 1):
        if g > u.generation:
            u.step(g - u.generation)
        seen[g] = [(k, x0 + x, y0 + y) for k, x, y in nw_gliders(u.get_rect(x0, y0, x1, y1))]
    last = u.get_rect(x0, y0, x1, y1)
    final = [(x, y) for k, x, y in seen[g_end] if k == 0]
    print(
        f"dive metapixel ({di}, {dj}); last frame generation {g_end:,}: "
        f"{len(final)} NW glider(s) in the opening's phase"
    )
    for x, y in final:
        g = g_end
        while g > g_from:  # one generation further back, the box was (d // 4) cells SE
            d = g_end - (g - 1)
            if not any(abs(hx - x - d // 4) <= 1 and abs(hy - y - d // 4) <= 1
                       for _, hx, hy in seen[g - 1]):  # fmt: skip
                break
            g -= 1
        vx, vy = x - 2 - x0, y - 2 - y0  # the final view: the box at columns/rows 2..4
        others = int(last[max(vy, 0) : vy + 6, max(vx, 0) : vx + 6].sum()) - 5
        t_free = next(f for f in range(N_FRAMES) if gens[f] >= g) / FPS
        print(
            f"  box at ({x}, {y}): free since generation {g:,} (t ≈ {t_free:.1f} s), "
            f"{others} other cell(s) in the final view → TARGET = ({x + 1}, {y + 1}), "
            f"LEAN_CELLS = {(g_end - g) / 4}"
        )


if __name__ == "__main__":
    main()
