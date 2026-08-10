"""Render conformance: rebuild every colormap LUT and replay frame indexing,
per-family frame() transforms, and ε-tier fractal renders against
vectors/render/ — the same files the .NET suite replays."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from heaton_life.boids import Boids
from heaton_life.ca import Cyclic, LifeLike, Wireworld
from heaton_life.conformance import bytes_to_state
from heaton_life.core.viewport import Viewport
from heaton_life.fractal import Mandelbrot, Newton
from heaton_life.rd import GrayScott
from heaton_life.render import apply_colormap, get_colormap

VECTOR_ROOT = Path(__file__).resolve().parents[2] / "vectors" / "render"

CASES = sorted(VECTOR_ROOT.glob("*/params.json"))


def _png_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as img:
        return np.asarray(img.convert("RGB"))


def _png_gray(path: Path) -> np.ndarray:
    with Image.open(path) as img:
        return np.asarray(img.convert("L"))


def _f64(path: Path, shape: list[int]) -> np.ndarray:
    return np.frombuffer(path.read_bytes(), dtype="<f8").reshape(tuple(shape))


def test_render_vectors_exist() -> None:
    kinds = {json.loads(c.read_text())["kind"] for c in CASES}
    assert kinds == {"lut", "apply", "frame", "fractal-render"}


def _build_sim(sim_family: str, p: dict[str, Any], initial: np.ndarray) -> Any:
    size = (p["width"], p["height"])
    if sim_family == "lifelike":
        return LifeLike(p["rule"], size=size, init=initial, boundary=p["boundary"])
    if sim_family == "cyclic":
        return Cyclic(
            p["states"], size=size, threshold=p["threshold"], reach=p["reach"],
            neighborhood=p["neighborhood"], init=initial,
        )
    if sim_family == "wireworld":
        return Wireworld(size=size, init=initial, boundary=p["boundary"])
    if sim_family == "grayscott":
        return GrayScott(
            size=size, du=p["du"], dv=p["dv"], feed=p["feed"], kill=p["kill"],
            dt=p["dt"], init=initial,
        )
    if sim_family == "boids":
        return Boids(
            p["count"], dimensions=p.get("dimensions", 2), size=size,
            depth=p.get("depth", 256), perception=p["perception"],
            separation_radius=p["separation_radius"], w_separation=p["w_separation"],
            w_alignment=p["w_alignment"], w_cohesion=p["w_cohesion"],
            max_speed=p["max_speed"], min_speed=p["min_speed"],
            max_force=p["max_force"], boundary=p["boundary"], init=initial,
        )
    raise ValueError(f"no frame builder for {sim_family!r}")


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.parent.name)
def test_render_vector(case: Path) -> None:
    meta = json.loads(case.read_text())
    kind = meta["kind"]
    if kind == "lut":
        assert meta["tier"] == "bit-exact"
        expected = _png_rgb(case.parent / meta["output"]["file"]).reshape(256, 3)
        assert np.array_equal(get_colormap(meta["cmap"]), expected)
    elif kind == "apply":
        assert meta["tier"] == "bit-exact"
        frame = _f64(case.parent / meta["input"]["file"], meta["input"]["shape"])
        expected = _png_rgb(case.parent / meta["output"]["file"])
        assert np.array_equal(apply_colormap(frame, meta["cmap"]), expected)
    elif kind == "frame":
        assert meta["tier"] == "bit-exact"
        data = (case.parent / meta["input"]["file"]).read_bytes()
        initial = bytes_to_state(meta["sim_family"], data, meta["input"].get("shape"))
        sim = _build_sim(meta["sim_family"], meta["params"], initial)
        produced = np.asarray(sim.frame())
        if meta["output"]["file"].endswith(".f64"):
            expected_f = _f64(case.parent / meta["output"]["file"], meta["output"]["shape"])
            assert np.array_equal(produced, expected_f)
        else:
            expected_b = _png_gray(case.parent / meta["output"]["file"])
            assert np.array_equal(produced, expected_b)
    else:  # fractal-render
        assert meta["tier"] == "epsilon"
        p = meta["params"]
        field: Any
        if meta["sim_family"] == "mandelbrot":
            field = Mandelbrot(max_iter=p["max_iter"], escape_radius=p["escape_radius"])
        else:
            field = Newton(degree=p["degree"], max_iter=p["max_iter"])
        viewport = Viewport.from_dict(meta["viewport"])
        produced = field.render(tuple(meta["size"]), viewport)
        expected_f = _f64(case.parent / meta["output"]["file"], meta["output"]["shape"])
        assert float(np.max(np.abs(produced - expected_f))) <= meta["epsilon"]
