#!/usr/bin/env python3
"""Render the family gallery montage to ../../docs/gallery.png.

One representative tile per system, 5 columns x 3 rows, labeled.
Usage: .venv/bin/python tools/gen_gallery.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from heaton_life.boids import Boids
from heaton_life.ca import Cyclic, Elementary, LifeLike, MergeLife, Wireworld, clock_loop
from heaton_life.core.viewport import Viewport
from heaton_life.fractal import BurningShip, Julia, Mandelbrot, Newton
from heaton_life.lenia import AsymptoticLenia, ClassicLenia, FlowLenia
from heaton_life.rd import GrayScott
from heaton_life.render import apply_colormap

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "docs" / "gallery.png"

TILE = 256
LABEL_H = 22


def sim_tile(sim: object, steps: int, cmap: str) -> np.ndarray:
    sim.step(steps)  # type: ignore[attr-defined]
    return apply_colormap(sim.frame(), cmap)  # type: ignore[attr-defined]


def fractal_tile(field: object, viewport: Viewport, cmap: str) -> np.ndarray:
    render = field.render((TILE, TILE), viewport)  # type: ignore[attr-defined]
    return apply_colormap(render, cmap)


def main() -> None:
    size = (TILE, TILE)
    tiles: list[tuple[str, np.ndarray]] = [
        ("Life-like (B3/S23)", sim_tile(LifeLike(size=size, seed=42), 300, "phosphor")),
        ("Elementary (rule 30)", sim_tile(Elementary(30, size=size), 255, "gray")),
        ("Cyclic (demons)", sim_tile(Cyclic(14, size=size, seed=7), 220, "rainbow")),
        (
            "Wireworld",
            sim_tile(Wireworld(size=(64, 64), init=clock_loop((64, 64), margin=8)), 23, "wireworld"),
        ),
        (
            "MergeLife (Red World)",
            sim_tile(MergeLife(size=(128, 128), seed=5), 150, "gray"),
        ),
        (
            "Gray-Scott (coral)",
            sim_tile(GrayScott(size=size, feed=0.0545, kill=0.062, seed=3), 4000, "fire"),
        ),
        ("Lenia (classic)", sim_tile(ClassicLenia(size=(128, 128), seed=0), 300, "ice")),
        (
            "Lenia (asymptotic)",
            sim_tile(AsymptoticLenia(size=(128, 128), seed=1), 250, "violet"),
        ),
        ("Flow Lenia", sim_tile(FlowLenia(size=(128, 128), seed=0), 200, "phosphor")),
        ("Boids", sim_tile(Boids(400, size=size, seed=4), 300, "phosphor")),
        (
            "Mandelbrot",
            fractal_tile(
                Mandelbrot(max_iter=2000), Viewport("-0.7435", "0.1314", 2.5), "fire"
            ),
        ),
        ("Julia", fractal_tile(Julia(max_iter=500), Viewport("0.0", "0.0", -0.05), "ice")),
        (
            "Burning Ship",
            fractal_tile(
                BurningShip(max_iter=1500), Viewport("-1.755", "-0.03", 1.8), "violet"
            ),
        ),
        ("Newton (z^3-1)", fractal_tile(Newton(3), Viewport("0.0", "0.0", -0.1), "rainbow")),
        (
            "Deep zoom 1e14",
            fractal_tile(
                Mandelbrot(max_iter=5000),
                Viewport(
                    "-0.743643887037158704752191506114774",
                    "0.131825904205311970493132056385139",
                    14.0,
                ),
                "fire",
            ),
        ),
    ]

    cols, rows = 5, 3
    montage = Image.new("RGB", (cols * TILE, rows * (TILE + LABEL_H)), (12, 12, 16))
    draw = ImageDraw.Draw(montage)
    for index, (label, rgb) in enumerate(tiles):
        img = Image.fromarray(rgb, "RGB")
        if img.size != (TILE, TILE):
            img = img.resize((TILE, TILE), Image.Resampling.NEAREST)
        col, row = index % cols, index // cols
        x, y = col * TILE, row * (TILE + LABEL_H)
        montage.paste(img, (x, y))
        draw.text((x + 6, y + TILE + 4), label, fill=(220, 220, 220))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    montage.save(OUT, optimize=True)
    print(f"wrote {OUT.relative_to(REPO_ROOT)} ({OUT.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
