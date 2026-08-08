"""Headless tests for the playground fractal adapter (no Qt): autozoom mechanics."""

import numpy as np

from heaton_life.playground.fractal_sim import (
    AUTOZOOM_ZOOM_PER_STEP,
    FractalSim,
    MandelbrotSimParams,
    make_mandelbrot,
)


def make_sim(**overrides: object) -> FractalSim:
    params = MandelbrotSimParams.from_dict(
        {"width": 64, "height": 64, "max_iter": 300, **overrides}  # type: ignore[dict-item]
    )
    return FractalSim(params, make_mandelbrot)


def test_autozoom_zooms_and_drifts_toward_boundary() -> None:
    sim = make_sim()
    sim.frame()  # populate counts for targeting
    sim.step(5)
    assert sim.params.zoom_log10 == 5 * AUTOZOOM_ZOOM_PER_STEP  # type: ignore[attr-defined]
    assert sim.params.center_re != "-0.5", "center should drift toward structure"  # type: ignore[attr-defined]
    assert sim.generation == 5
    # the next frame renders at the new viewport
    frame = sim.frame()
    assert frame.shape == (64, 64)


def test_autozoom_holds_center_when_frame_is_all_interior() -> None:
    # Span 0.04 around the origin: entirely inside the main cardioid, all black.
    sim = make_sim(center_re="0.0", center_im="0.0", zoom_log10=2.0)
    sim.frame()
    assert sim._counts is not None
    assert not (sim._counts > 0).any()
    sim.step()
    assert sim.params.center_re == "0.0"  # type: ignore[attr-defined]
    assert sim.params.zoom_log10 > 2.0, "still zooms, just without retargeting"  # type: ignore[attr-defined]


def test_autozoom_without_a_rendered_frame_still_zooms() -> None:
    sim = make_sim()
    sim.step()  # no counts yet
    assert sim.params.zoom_log10 == AUTOZOOM_ZOOM_PER_STEP  # type: ignore[attr-defined]
    assert sim.params.center_re == "-0.5"  # type: ignore[attr-defined]


def test_autozoom_clamps_at_zoom_max() -> None:
    params = MandelbrotSimParams.from_dict(
        {"width": 32, "height": 32, "max_iter": 100, "zoom_log10": 0.99}
    )
    sim = FractalSim(params, make_mandelbrot, zoom_max=1.0)
    sim.frame()
    sim.step()
    assert sim.params.zoom_log10 == 1.0  # type: ignore[attr-defined]
    sim.step(3)
    assert sim.params.zoom_log10 == 1.0, "clamped: no further zoom"  # type: ignore[attr-defined]
    assert sim.generation == 4


def test_target_prefers_high_counts_near_center() -> None:
    sim = make_sim()
    counts = np.zeros((64, 64), dtype=np.int32)
    counts[:, :] = 5
    counts[30, 30] = 250  # near center
    counts[2, 2] = 250  # same count, far corner
    sim._counts = counts
    assert sim._find_target() == (30, 30)