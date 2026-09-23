"""Fractals: escape-time fields with automatic deep-zoom tiering, plus Newton basins."""

from heaton_life.fractal.animate import zoom_animation
from heaton_life.fractal.engine import T0_MAX_ZOOM, T1_MAX_ZOOM, tier_of
from heaton_life.fractal.escape_fields import (
    BurningShip,
    BurningShipParams,
    Julia,
    JuliaParams,
    Mandelbrot,
    MandelbrotParams,
)
from heaton_life.fractal.newton import Newton, NewtonParams

__all__ = [
    "T0_MAX_ZOOM",
    "T1_MAX_ZOOM",
    "BurningShip",
    "BurningShipParams",
    "Julia",
    "JuliaParams",
    "Mandelbrot",
    "MandelbrotParams",
    "Newton",
    "NewtonParams",
    "tier_of",
    "zoom_animation",
]
