"""Check that the metapixels compute Life: run the board and compare what each metapixel
shows against plain Life on the 6×6 inner grid.

A metapixel's state is read from its display, the big square an ON tile fills with
spaceship streams: a probe over the middle of it counts thousands of cells when ON, none
when OFF. The first 35,328-generation cycle is setup; after it, each cycle advances the
inner world one generation, with the displays switching about 6,900 generations in.

Usage: python verify.py [--cycles 3] [--tiles out/tiles.npz] [--board out/board.mc]
(--cycles N checks inner generations 1..N.)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from board import OUT, PERIOD, PITCH, SIZE, inner_cells, life_step
from numpy.typing import NDArray

from heaton_life.ca.hashlife import HashLife


def display_probe(tiles: Path) -> tuple[int, int, int, int]:
    """The middle half of the display: the box of cells ON tiles have and OFF tiles lack."""
    with np.load(tiles) as t:
        off = {(int(x), int(y)) for x, y in t["off"]}
        extra = np.array([c for c in t["on"].tolist() if tuple(c) not in off])
    x0, y0 = (int(v) for v in extra.min(axis=0))
    x1, y1 = (int(v) for v in extra.max(axis=0))
    qx, qy = (x1 - x0) // 4, (y1 - y0) // 4
    return x0 + qx, y0 + qy, x1 - qx, y1 - qy


def picture(u: HashLife, probe: tuple[int, int, int, int]) -> NDArray[np.uint8]:
    """The inner world as the metapixels show it."""
    x0, y0, x1, y1 = probe
    pop = np.array(
        [
            [
                u.population_in(PITCH * i + x0, PITCH * j + y0, PITCH * i + x1, PITCH * j + y1)
                for i in range(SIZE)
            ]
            for j in range(SIZE)
        ]
    )
    return (pop > pop.max() // 2).astype(np.uint8) if pop.max() else pop.astype(np.uint8)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cycles", type=int, default=3)
    ap.add_argument("--tiles", type=Path, default=OUT / "tiles.npz")
    ap.add_argument("--board", type=Path, default=OUT / "board.mc")
    args = ap.parse_args()

    probe = display_probe(args.tiles)
    u = HashLife.from_macrocell(args.board.read_text(), max_memory_mb=8000)
    expected = [inner_cells()]
    for _ in range(args.cycles):
        expected.append(life_step(expected[-1]))

    seen = [(0, picture(u, probe))]
    t0 = time.perf_counter()
    # A quarter cycle past the last one, so its displays have finished switching.
    for _ in range(args.cycles * 16 + 4):
        u.step(PERIOD // 16)
        pic = picture(u, probe)
        if not np.array_equal(pic, seen[-1][1]):
            seen.append((u.generation, pic))
    print(f"ran {u.generation:,} generations in {time.perf_counter() - t0:.1f} s")

    ok = len(seen) == len(expected)
    for k, (gen, pic) in enumerate(seen):
        match = k < len(expected) and np.array_equal(pic, expected[k])
        ok = ok and match
        print(f"inner generation {k} shown from generation {gen:,}: {'ok' if match else 'WRONG'}")
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
