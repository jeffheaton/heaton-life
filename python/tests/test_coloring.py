"""Fractal color and the phase lookup (spec/fractal-color.md, spec/render.md "Cyclic
palettes" and "Phase lookup", spec/rng.md "Presentation noise")."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from heaton_life.core.viewport import Viewport
from heaton_life.fractal import Julia, Mandelbrot
from heaton_life.fractal.coloring import (
    Frequency,
    PhaseParams,
    ShadeParams,
    Stretch,
    apply_stretch,
    color_scale,
    depth_phase,
    measure_frequency,
    measure_stretch,
    retune,
    shade_distance,
)
from heaton_life.fractal.engine import normalize_render
from heaton_life.render import (
    apply_phase,
    get_colormap,
    is_cyclic,
    list_colormaps,
    list_cyclic_colormaps,
)
from heaton_life.render._palette_tables import TABLES
from heaton_life.render.dither import tpdf, tpdf_frame, triple32

SEAHORSE = ("-0.743643887037158704752191506114774", "0.131825904205311970493132056385139")


def _fields(zoom: float = 4.0, size: tuple[int, int] = (96, 64)) -> tuple[np.ndarray, ...]:
    fields = Mandelbrot(max_iter=1600).fields(
        size, Viewport(*SEAHORSE, zoom), smooth=True, distance=True
    )
    assert fields.smooth is not None and fields.distance is not None
    return fields.counts, fields.smooth, fields.distance


# --- stretch ------------------------------------------------------------------------------


def test_normalize_render_is_the_measured_stretch_applied() -> None:
    _, mu, _ = _fields()
    stretch = measure_stretch(mu)
    assert stretch is not None and stretch.lo < stretch.hi
    assert np.array_equal(normalize_render(mu), apply_stretch(mu, stretch))
    assert measure_stretch(np.zeros((4, 4))) is None
    assert np.array_equal(normalize_render(np.zeros((4, 4))), np.zeros((4, 4)))
    # A featureless frame: one mid tone for every escaped pixel.
    flat = apply_stretch(np.array([[3.0, 0.0]]), Stretch(5.0, 5.0))
    assert np.array_equal(flat, np.sqrt(np.array([[0.6, 0.0]])))


def test_a_frozen_stretch_keeps_colors_across_frame_sizes() -> None:
    """The tier ladder: a stretch measured on the quick frame recolors the sharp frame of
    the same view with the same mapping -- the same mu gives the same value."""
    _, small, _ = _fields(size=(48, 32))
    _, large, _ = _fields(size=(96, 64))
    frozen = measure_stretch(small)
    assert frozen is not None
    values = apply_stretch(large, frozen)
    for mu in (large[10, 10], large[40, 70]):
        assert values[large == mu][0] == apply_stretch(np.array([[mu]]), frozen)[0, 0]


# --- depth phase, frequency ------------------------------------------------------------------


def test_depth_phase() -> None:
    _, mu, _ = _fields()
    params = PhaseParams(cycles_per_iteration=0.02, cycles_per_octave=0.25, phase_offset=0.3)
    t = depth_phase(mu, 4.0, params)
    escaped = mu > 0
    assert np.array_equal(np.isnan(t), ~escaped)
    base = 0.3 + 0.25 * (4.0 * 3.321928094887362)
    assert np.array_equal(t[escaped], base + 0.02 * (mu[escaped] - 0.0))
    # cycles_per_octave 0: a point keeps its phase at any zoom.
    assert np.array_equal(depth_phase(mu, 0.0), depth_phase(mu, 9.5))
    with pytest.raises(ValueError):
        PhaseParams(cycles_per_iteration=float("nan"))


def test_measure_frequency() -> None:
    counts, mu, _ = _fields(zoom=7.0, size=(64, 48))
    fit = measure_frequency(counts, mu, max_cycles_per_iteration=1.0)
    assert fit is not None
    assert fit.anchor == float(np.sort(counts[counts > 0])[(counts > 0).sum() // 2])
    capped = measure_frequency(counts, mu)
    assert capped is not None and capped.cycles_per_iteration == min(0.01, fit.cycles_per_iteration)
    # The target is per 1080p pixel: a 1920x1080 frame's scale is exactly 1.
    assert color_scale(1920, 1080) == 1.0
    sparse = np.full((6, 6), -1, dtype=np.int32)
    assert measure_frequency(sparse, np.zeros((6, 6))) is None
    # Only finite escaped values step: an infinite pair would step by NaN, which the two
    # ports would sort to opposite ends.
    inf_mu = np.concatenate([5.0 + np.cumsum(np.arange(1, 81.0)), np.full(20, np.inf)])
    sevens = np.full((1, 100), 7, dtype=np.int32)
    fit = measure_frequency(sevens, inf_mu.reshape(1, 100), max_cycles_per_iteration=1.0)
    assert fit == Frequency(0.01611802707061469, 7.0)  # FractalColorTests pins the same
    assert measure_frequency(np.full((9, 9), 7, dtype=np.int32), np.full((9, 9), np.inf)) is None


def test_retune_keeps_the_pivot_still() -> None:
    old = PhaseParams(
        cycles_per_iteration=0.01, cycles_per_octave=0.25, phase_offset=0.2, anchor=100.0
    )
    new = retune(old, Frequency(0.004, 950.0), pivot=900.0)
    # Bit for bit (FractalColorTests pins the same): phase offset 0x4020CCCCCCCCCCCC.
    assert new == PhaseParams(0.004, 0.25, 8.399999999999999, 950.0)
    mu = np.array([[900.0]])
    before = depth_phase(mu, 5.0, old)[0, 0]
    after = depth_phase(mu, 5.0, new)[0, 0]
    assert abs(after - before) < 1e-12


# --- palettes and the phase lookup ------------------------------------------------------------


def test_registries_stay_apart() -> None:
    assert list_colormaps() == ["fire", "gray", "ice", "phosphor", "rainbow", "violet", "wireworld"]
    assert list_cyclic_colormaps() == ["deep", "classic", "embers", "glacier"]
    assert is_cyclic("deep") and not is_cyclic("rainbow")
    with pytest.raises(ValueError):
        is_cyclic("nope")
    assert get_colormap("deep").shape == (256, 3)


def test_the_tables_are_what_the_recipe_bakes() -> None:
    """The tables are data; re-baking them here must agree. A different platform's cbrt or
    pow could move a value by an ulp, so allow one code where it lands on a boundary."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import gen_palettes

    for name, _, stops in gen_palettes.PALETTES:
        baked = np.frombuffer(gen_palettes.bake(stops), dtype=np.uint8).astype(int)
        shipped = np.frombuffer(bytes.fromhex(TABLES[name]), dtype=np.uint8).astype(int)
        assert np.abs(baked - shipped).max() <= 1 and (baked == shipped).mean() > 0.99


def test_phase_lookup_hits_entries_and_wraps() -> None:
    lut = get_colormap("deep")
    k = np.arange(256, dtype=np.float64)
    t = (k / 256.0).reshape(16, 16)
    plain = apply_phase(t, lut, antialias=False, dither=0.0)
    assert np.array_equal(plain.reshape(256, 3), lut)
    shifted = apply_phase(t + 3.0, lut, antialias=False, dither=0.0)
    assert np.array_equal(shifted, plain)
    assert np.array_equal(apply_phase(t - 5.0, lut, antialias=False, dither=0.0), plain)
    # Halfway between entries 255 and 0: the cycle closes.
    half = apply_phase(np.array([[255.5 / 256]]), lut, antialias=False, dither=0.0)[0, 0]
    assert np.array_equal(half, np.round((lut[255].astype(float) + lut[0]) / 2).astype(np.uint8))
    # Mirror: a sequential map runs up at t in [0, 1/2] and back down after.
    fire = get_colormap("fire")
    mirror = apply_phase(
        np.array([[0.0, 255.0 / 510, 0.5, 1.0 - 1.0 / 510]]),
        fire,
        wrap="mirror",
        antialias=False,
        dither=0.0,
    )[0]
    assert np.array_equal(mirror, np.stack([fire[0], fire[255], fire[255], fire[1]]))


def test_interior_and_non_finite_phases() -> None:
    t = np.array([[np.nan, np.inf, -np.inf, 1e308, 0.25]])
    rgb = apply_phase(t, "glacier", interior=(7, 8, 9), dither=0.0)
    assert np.array_equal(rgb[0, :4], np.tile([7, 8, 9], (4, 1)))
    with pytest.raises(ValueError):
        apply_phase(t, "glacier", dither=-1.0)
    with pytest.raises(ValueError):
        apply_phase(t, "glacier", wrap="sideways")


def test_antialias_fades_noise_to_the_mean() -> None:
    rng = np.random.default_rng(3)
    noise = rng.uniform(0.0, 50.0, (32, 32))  # tens of cycles per pixel
    lut = get_colormap("classic")
    rgb = apply_phase(noise, lut, dither=0.0)
    mean = np.round(lut.astype(np.int64).sum(axis=0) / 256.0)
    assert np.all(np.abs(rgb.astype(int) - mean) <= 0)
    calm = np.add.outer(np.arange(32), np.arange(32)) / 2048.0  # a slow ramp
    assert np.array_equal(
        apply_phase(calm, lut, dither=0.0), apply_phase(calm, lut, antialias=False, dither=0.0)
    )


def test_dither_known_answers_and_amplitude() -> None:
    assert [triple32(v) for v in (0, 1, 2, 0x68BC21EB, 0xDEADBEEF)] == [
        0x00000000,
        0x042741D6,
        0xF1DFE8E9,
        0xA5D6919E,
        0x0921725E,
    ]
    expected = {
        (0, 0, 0, 0): -2782302622,
        (0, 0, 0, 1): -3302658959,
        (0, 0, 0, 2): 239395147,
        (1, 0, 0, 0): 964350720,
        (0, 1, 0, 0): 179844703,
        (3, 5, 7, 1): -3366029565,
    }
    for args, value in expected.items():
        assert tpdf(*args) == value
    frame = tpdf_frame(9, 6, 7)
    assert all(
        frame[y, x, ch] == tpdf(x, y, 7, ch) for y in range(6) for x in range(9) for ch in range(3)
    )
    assert tpdf_frame(2, 2, 2**32 - 1).shape == (2, 2, 3)
    with pytest.raises(ValueError):
        tpdf_frame(2, 2, 2**32)
    # Amplitude 1 moves a code by at most one; amplitude 0 is no dither.
    _, mu, _ = _fields()
    t = depth_phase(mu, 4.0)
    clean = apply_phase(t, "deep", dither=0.0).astype(int)
    dithered = apply_phase(t, "deep").astype(int)
    assert np.abs(dithered - clean).max() <= 1 and (dithered != clean).any()


# --- distance shading ------------------------------------------------------------------------


def test_shading() -> None:
    rgb = np.full((8, 10, 3), 200, dtype=np.uint8)
    de = np.full((8, 10), 1000.0)
    de[0, 0] = np.nan
    de[4, 5] = 0.0
    out = shade_distance(rgb, de, ShadeParams(width=1.6 / color_scale(10, 8)))
    assert np.array_equal(out[0, 0], rgb[0, 0])  # not escaped: untouched
    far = np.ones((8, 10), dtype=bool)
    far[4, 5] = False
    assert np.array_equal(out[far], rgb[far])  # a stroke's width away: untouched
    assert np.array_equal(out[4, 5], np.round(200 * np.sqrt(np.full(3, 0.15))).astype(np.uint8))
    # A dense patch -- nothing in reach clears the stroke width -- is released.
    dense = np.full((8, 10), 0.01)
    stroke = 1.6 / color_scale(10, 8)  # 1.6 pixels on this small frame
    assert np.array_equal(shade_distance(rgb, dense, ShadeParams(width=stroke)), rgb)
    unreleased = ShadeParams(width=stroke, dense_release=0.0)
    assert (shade_distance(rgb, dense, unreleased) < rgb).all()
    for bad in ({"width": 0.0}, {"strength": 1.5}, {"dense_release": -0.1}):
        with pytest.raises(ValueError):
            ShadeParams(**bad)  # type: ignore[arg-type]
    # A width that overflows once scaled to the frame is an error in both ports.
    wide = np.full((1, 4000, 3), 200, dtype=np.uint8)
    with pytest.raises(ValueError, match="finite"):
        shade_distance(wide, np.full((1, 4000), 5.0), ShadeParams(width=1e308))
    # A tie: strength 0.75 at DE 0 halves a byte exactly, and 201 rounds to even (100).
    tie = shade_distance(
        np.array([[[201, 7, 3]]], dtype=np.uint8),
        np.array([[0.0]]),
        ShadeParams(width=1.0 / color_scale(1, 1), strength=0.75, dense_release=0.0),
    )
    assert tie.tolist() == [[[100, 4, 2]]]


def test_a_whole_frame_colors() -> None:
    """The pieces compose: fields -> phase -> lookup -> shading, for Julia too."""
    fields = Julia(c=complex(-0.123, 0.745), max_iter=500).fields(
        (48, 48), Viewport("0", "0", 0.0), smooth=True, distance=True
    )
    assert fields.smooth is not None and fields.distance is not None
    fit = measure_frequency(fields.counts, fields.smooth)
    assert fit is not None
    params = retune(PhaseParams(), fit, fit.anchor)
    rgb = apply_phase(depth_phase(fields.smooth, 0.0, params), "embers")
    shaded = shade_distance(rgb, fields.distance)
    assert shaded.shape == (48, 48, 3) and (shaded <= rgb).all()
