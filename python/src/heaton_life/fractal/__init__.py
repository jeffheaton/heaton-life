"""Fractals: escape-time fields with automatic deep-zoom tiering, plus Newton basins."""

from heaton_life.fractal.animate import zoom_animation
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
from heaton_life.fractal.engine import T0_MAX_ZOOM, T1_MAX_ZOOM, tier_of
from heaton_life.fractal.escape_fields import (
    BurningShip,
    BurningShipParams,
    EscapeFields,
    Julia,
    JuliaParams,
    Mandelbrot,
    MandelbrotParams,
)
from heaton_life.fractal.navigation import center_places, pan, pixel_delta, zoom_at
from heaton_life.fractal.newton import Newton, NewtonParams
from heaton_life.fractal.nucleus import BoxResult, Nucleus, box_period, find_nucleus
from heaton_life.fractal.policy import auto_max_iter, need_from_counts, suggest_max_iter

__all__ = [
    "T0_MAX_ZOOM",
    "T1_MAX_ZOOM",
    "BoxResult",
    "BurningShip",
    "BurningShipParams",
    "EscapeFields",
    "Frequency",
    "Julia",
    "JuliaParams",
    "Mandelbrot",
    "MandelbrotParams",
    "Newton",
    "NewtonParams",
    "Nucleus",
    "PhaseParams",
    "ShadeParams",
    "Stretch",
    "apply_stretch",
    "auto_max_iter",
    "box_period",
    "center_places",
    "color_scale",
    "depth_phase",
    "find_nucleus",
    "measure_frequency",
    "measure_stretch",
    "need_from_counts",
    "pan",
    "pixel_delta",
    "retune",
    "shade_distance",
    "suggest_max_iter",
    "tier_of",
    "zoom_animation",
    "zoom_at",
]
