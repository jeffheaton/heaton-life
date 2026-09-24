"""Render conformance: rebuild every colormap LUT and replay frame indexing,
per-family frame() transforms, ε-tier fractal renders, and (0.7.0) fractal color and
the phase lookup against vectors/render/ — the same files the .NET suite replays."""

import json
import struct
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from heaton_life.boids import Boids
from heaton_life.ca import Cyclic, LifeLike, Wireworld
from heaton_life.conformance import bytes_to_state
from heaton_life.core.viewport import Viewport
from heaton_life.fractal import Julia, Mandelbrot, Newton
from heaton_life.fractal.coloring import (
    PhaseParams,
    ShadeParams,
    Stretch,
    apply_stretch,
    depth_phase,
    measure_frequency,
    measure_stretch,
    shade_distance,
)
from heaton_life.rd import GrayScott
from heaton_life.render import apply_colormap, apply_phase, get_colormap

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


BASE_KEYS = {"spec_version", "family", "tier", "kind"}
# Cases from 0.7.0 on are strict: a key the runner does not know fails the case.
STRICT_KEYS = {
    "lut": {"cmap", "output"},
    "stretch": {"input", "output"},  # plus exactly one of "measured" / "stretch"
    "phase": {"input", "zoom_log10", "phase", "output"},
    "frequency": {
        "counts",
        "input",
        "target_cycles_per_step",
        "max_cycles_per_iteration",
        "expected",
    },
    "phase-apply": {
        "cmap",
        "wrap",
        "interior",
        "antialias",
        "dither",
        "frame_index",
        "input",
        "output",
    },
    "shade": {"rgb", "input", "shade", "output"},
}
PHASE_KEYS = {"cycles_per_iteration", "cycles_per_octave", "phase_offset", "anchor"}
SHADE_KEYS = {"width", "strength", "dense_release"}


def _double(bits: str) -> float:
    """A double from its IEEE-754 bit pattern ("0x" + 16 hex digits)."""
    assert bits.startswith("0x") and len(bits) == 18, bits
    value: float = struct.unpack("<d", struct.pack("<Q", int(bits, 16)))[0]
    return value


def _same_f64(got: np.ndarray, want: np.ndarray) -> bool:
    """Float64 outputs compare by value; every NaN equals every NaN, zero signs aside."""
    return got.shape == want.shape and bool(np.array_equal(got, want, equal_nan=True))


def test_render_vectors_exist() -> None:
    kinds = {json.loads(c.read_text())["kind"] for c in CASES}
    assert kinds == {"lut", "apply", "frame", "fractal-render", *STRICT_KEYS}


def _color_case(case: Path, meta: dict[str, Any]) -> None:
    """The 0.7.0 kinds (spec/fractal-color.md, spec/render.md "Phase lookup")."""
    kind = meta["kind"]
    here = case.parent
    extra = set(meta) - BASE_KEYS - STRICT_KEYS[kind]
    if kind == "stretch":
        assert extra in ({"measured"}, {"stretch"}), f"{case}: unexpected keys {extra}"
    else:
        assert not extra, f"{case}: runner does not understand {sorted(extra)}"
    assert meta["tier"] == "bit-exact" and meta["family"] == "render"
    if kind == "stretch":
        mu = _f64(here / meta["input"]["file"], meta["input"]["shape"])
        if "measured" in meta:
            got = measure_stretch(mu)
            if meta["measured"] is None:
                assert got is None
                render = np.zeros(mu.shape)
            else:
                assert set(meta["measured"]) == {"lo", "hi"}
                assert got == Stretch(
                    _double(meta["measured"]["lo"]), _double(meta["measured"]["hi"])
                )
                render = apply_stretch(mu, got)
        else:
            assert set(meta["stretch"]) == {"lo", "hi"}
            given = Stretch(_double(meta["stretch"]["lo"]), _double(meta["stretch"]["hi"]))
            render = apply_stretch(mu, given)
        expected = _f64(here / meta["output"]["file"], meta["output"]["shape"])
        assert _same_f64(render, expected)
    elif kind == "phase":
        assert set(meta["phase"]) == PHASE_KEYS
        mu = _f64(here / meta["input"]["file"], meta["input"]["shape"])
        params = PhaseParams(**{k: _double(v) for k, v in meta["phase"].items()})
        t = depth_phase(mu, _double(meta["zoom_log10"]), params)
        assert _same_f64(t, _f64(here / meta["output"]["file"], meta["output"]["shape"]))
    elif kind == "frequency":
        mu = _f64(here / meta["input"]["file"], meta["input"]["shape"])
        counts = np.frombuffer((here / meta["counts"]["file"]).read_bytes(), dtype="<i4")
        fit = measure_frequency(
            counts.reshape(tuple(meta["counts"]["shape"])),
            mu,
            target_cycles_per_step=_double(meta["target_cycles_per_step"]),
            max_cycles_per_iteration=_double(meta["max_cycles_per_iteration"]),
        )
        if meta["expected"] is None:
            assert fit is None
        else:
            assert set(meta["expected"]) == {"cycles_per_iteration", "anchor"}
            assert fit is not None
            assert fit.cycles_per_iteration == _double(meta["expected"]["cycles_per_iteration"])
            assert fit.anchor == _double(meta["expected"]["anchor"])
    elif kind == "phase-apply":
        t = _f64(here / meta["input"]["file"], meta["input"]["shape"])
        rgb = apply_phase(
            t,
            meta["cmap"],
            wrap=meta["wrap"],
            interior=tuple(meta["interior"]),
            antialias=meta["antialias"],
            dither=_double(meta["dither"]),
            frame_index=meta["frame_index"],
        )
        assert np.array_equal(rgb, _png_rgb(here / meta["output"]["file"]))
    elif kind == "shade":
        assert set(meta["shade"]) == SHADE_KEYS
        rgb = _png_rgb(here / meta["rgb"]["file"])
        de = _f64(here / meta["input"]["file"], meta["input"]["shape"])
        params = ShadeParams(**{k: _double(v) for k, v in meta["shade"].items()})
        shaded = shade_distance(rgb, de, params)
        assert np.array_equal(shaded, _png_rgb(here / meta["output"]["file"]))
    else:  # lut
        expected = _png_rgb(here / meta["output"]["file"]).reshape(256, 3)
        assert np.array_equal(get_colormap(meta["cmap"]), expected)


def _build_sim(sim_family: str, p: dict[str, Any], initial: np.ndarray) -> Any:
    size = (p["width"], p["height"])
    if sim_family == "lifelike":
        return LifeLike(p["rule"], size=size, init=initial, boundary=p["boundary"])
    if sim_family == "cyclic":
        return Cyclic(
            p["states"],
            size=size,
            threshold=p["threshold"],
            reach=p["reach"],
            neighborhood=p["neighborhood"],
            init=initial,
        )
    if sim_family == "wireworld":
        return Wireworld(size=size, init=initial, boundary=p["boundary"])
    if sim_family == "grayscott":
        return GrayScott(
            size=size,
            du=p["du"],
            dv=p["dv"],
            feed=p["feed"],
            kill=p["kill"],
            dt=p["dt"],
            init=initial,
        )
    if sim_family == "boids":
        return Boids(
            p["count"],
            dimensions=p.get("dimensions", 2),
            size=size,
            depth=p.get("depth", 256),
            perception=p["perception"],
            separation_radius=p["separation_radius"],
            w_separation=p["w_separation"],
            w_alignment=p["w_alignment"],
            w_cohesion=p["w_cohesion"],
            max_speed=p["max_speed"],
            min_speed=p["min_speed"],
            max_force=p["max_force"],
            boundary=p["boundary"],
            init=initial,
        )
    raise ValueError(f"no frame builder for {sim_family!r}")


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.parent.name)
def test_render_vector(case: Path) -> None:
    meta = json.loads(case.read_text())
    kind = meta["kind"]
    if meta["spec_version"] == "0.7.0":
        _color_case(case, meta)
        return
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
        elif meta["sim_family"] == "julia":
            field = Julia(
                c=complex(p["c_re"], p["c_im"]),
                max_iter=p["max_iter"],
                escape_radius=p["escape_radius"],
            )
        else:
            field = Newton(degree=p["degree"], max_iter=p["max_iter"])
        viewport = Viewport.from_dict(meta["viewport"])
        produced = field.render(tuple(meta["size"]), viewport)
        expected_f = _f64(case.parent / meta["output"]["file"], meta["output"]["shape"])
        assert float(np.max(np.abs(produced - expected_f))) <= meta["epsilon"]
