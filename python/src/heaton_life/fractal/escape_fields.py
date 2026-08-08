"""Mandelbrot, Julia, and Burning Ship fields: tiered escape-time rendering.

Tier selection is automatic and invisible: T0 (direct float64) through zoom 1e12,
T1 (perturbation + rebasing) through ~1e290, beyond raises until floatexp lands.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from heaton_life.core.bignum import reference_orbit
from heaton_life.core.params import Params
from heaton_life.core.viewport import Viewport
from heaton_life.fractal.engine import (
    T0_MAX_ZOOM,
    T1_MAX_ZOOM,
    ComplexArray,
    FloatArray,
    IntArray,
    escape_time,
    normalize_render,
    pixel_grid,
    pixel_offsets,
    smooth_iterations,
)
from heaton_life.fractal.perturbation import perturb_burning_ship, perturb_z2


def _z2_update(z: ComplexArray, c: ComplexArray) -> ComplexArray:
    return z * z + c


def _ship_update(z: ComplexArray, c: ComplexArray) -> ComplexArray:
    folded = np.abs(z.real) + 1j * np.abs(z.imag)
    result: ComplexArray = folded * folded + c
    return result


class _EscapeField:
    """Shared tiering + output logic; subclasses define the two tier paths."""

    def __init__(self, max_iter: int = 500, escape_radius: float = 1000.0) -> None:
        if max_iter < 1:
            raise ValueError("max_iter must be positive")
        self.max_iter = max_iter
        self.escape_radius = escape_radius

    def _compute(
        self, size: tuple[int, int], viewport: Viewport
    ) -> tuple[IntArray, ComplexArray]:
        zoom = viewport.zoom_log10
        if zoom <= T0_MAX_ZOOM:
            return self._compute_t0(size, viewport)
        if zoom <= T1_MAX_ZOOM:
            return self._compute_t1(size, viewport)
        raise ValueError(
            f"zoom 1e{zoom:g} exceeds the float64 perturbation tier (~1e{T1_MAX_ZOOM:g}); "
            "the floatexp tier is not implemented yet"
        )

    def _compute_t0(
        self, size: tuple[int, int], viewport: Viewport
    ) -> tuple[IntArray, ComplexArray]:
        raise NotImplementedError

    def _compute_t1(
        self, size: tuple[int, int], viewport: Viewport
    ) -> tuple[IntArray, ComplexArray]:
        raise NotImplementedError

    def iterations(self, size: tuple[int, int], viewport: Viewport) -> IntArray:
        """Raw escape counts, shape (height, width). The bit-exact conformance output."""
        width, height = size
        counts, _ = self._compute(size, viewport)
        return counts.reshape(height, width)

    def outputs(self, size: tuple[int, int], viewport: Viewport) -> dict[str, IntArray]:
        return {"iterations": self.iterations(size, viewport)}

    def render(self, size: tuple[int, int], viewport: Viewport) -> FloatArray:
        """Smooth-colored field in [0,1] (Field protocol); interior is 0."""
        width, height = size
        counts, final = self._compute(size, viewport)
        mu = smooth_iterations(counts, final, self.escape_radius)
        return normalize_render(mu).reshape(height, width)


@dataclasses.dataclass(frozen=True)
class MandelbrotParams(Params):
    max_iter: int = 500
    escape_radius: float = 1000.0


class Mandelbrot(_EscapeField):
    """z <- z^2 + c, c = pixel, z0 = 0."""

    def _compute_t0(
        self, size: tuple[int, int], viewport: Viewport
    ) -> tuple[IntArray, ComplexArray]:
        c = pixel_grid(size, viewport)
        z0 = np.zeros_like(c)
        return escape_time(z0, c, _z2_update, self.max_iter, self.escape_radius)

    def _compute_t1(
        self, size: tuple[int, int], viewport: Viewport
    ) -> tuple[IntArray, ComplexArray]:
        orbit = reference_orbit(
            "mandelbrot", viewport.center_re, viewport.center_im,
            viewport.zoom_log10, self.max_iter,
        )
        dc = pixel_offsets(size, viewport)
        return perturb_z2(orbit, np.zeros_like(dc), dc, self.max_iter, self.escape_radius)


@dataclasses.dataclass(frozen=True)
class JuliaParams(Params):
    c_re: float = -0.7269
    c_im: float = 0.1889
    max_iter: int = 500
    escape_radius: float = 1000.0


class Julia(_EscapeField):
    """z <- z^2 + c, c fixed, z0 = pixel."""

    def __init__(
        self,
        c: complex = -0.7269 + 0.1889j,
        max_iter: int = 500,
        escape_radius: float = 1000.0,
    ) -> None:
        super().__init__(max_iter, escape_radius)
        self.c = complex(c)

    def _compute_t0(
        self, size: tuple[int, int], viewport: Viewport
    ) -> tuple[IntArray, ComplexArray]:
        z0 = pixel_grid(size, viewport)
        c = np.full_like(z0, self.c)
        return escape_time(z0, c, _z2_update, self.max_iter, self.escape_radius)

    def _compute_t1(
        self, size: tuple[int, int], viewport: Viewport
    ) -> tuple[IntArray, ComplexArray]:
        orbit = reference_orbit(
            "julia", viewport.center_re, viewport.center_im,
            viewport.zoom_log10, self.max_iter,
            c_re=self.c.real, c_im=self.c.imag,
        )
        dz0 = pixel_offsets(size, viewport)
        dc = np.zeros_like(dz0)
        return perturb_z2(orbit, dz0, dc, self.max_iter, self.escape_radius)


@dataclasses.dataclass(frozen=True)
class BurningShipParams(Params):
    max_iter: int = 500
    escape_radius: float = 1000.0


class BurningShip(_EscapeField):
    """z <- (|Re z| + i |Im z|)^2 + c, c = pixel, z0 = 0."""

    def _compute_t0(
        self, size: tuple[int, int], viewport: Viewport
    ) -> tuple[IntArray, ComplexArray]:
        c = pixel_grid(size, viewport)
        z0 = np.zeros_like(c)
        return escape_time(z0, c, _ship_update, self.max_iter, self.escape_radius)

    def _compute_t1(
        self, size: tuple[int, int], viewport: Viewport
    ) -> tuple[IntArray, ComplexArray]:
        orbit = reference_orbit(
            "burning_ship", viewport.center_re, viewport.center_im,
            viewport.zoom_log10, self.max_iter,
        )
        dc = pixel_offsets(size, viewport)
        return perturb_burning_ship(orbit, dc, self.max_iter, self.escape_radius)
