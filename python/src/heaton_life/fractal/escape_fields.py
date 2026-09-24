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
    CARDIOID_OR_BULB,
    ESCAPED,
    EXHAUSTED,
    T0_MAX_ZOOM,
    T1_MAX_ZOOM,
    ComplexArray,
    FloatArray,
    IntArray,
    StatusArray,
    cardioid_or_bulb,
    distance_estimate,
    escape_time,
    escape_time_distance,
    normalize_render,
    pixel_deltas,
    pixel_grid,
    pixel_scale,
    smooth_iterations,
)
from heaton_life.fractal.perturbation import (
    perturb_burning_ship,
    perturb_z2,
    perturb_z2_distance,
)

Derivative = tuple[FloatArray, FloatArray]
_Computed = tuple[IntArray, ComplexArray, StatusArray, Derivative | None]
_ComputedT1 = tuple[IntArray, ComplexArray, Derivative | None]


def _z2_update(z: ComplexArray, c: ComplexArray) -> ComplexArray:
    return z * z + c


def _ship_update(z: ComplexArray, c: ComplexArray) -> ComplexArray:
    folded = np.abs(z.real) + 1j * np.abs(z.imag)
    result: ComplexArray = folded * folded + c
    return result


@dataclasses.dataclass(frozen=True)
class EscapeFields:
    """What one escape-time computation yields, each (height, width): the counts, and
    whichever of smooth (mu, 0 where interior), status (spec/fractals.md "Status") and
    distance (spec/fractals.md "Distance estimate": pixels, NaN where not escaped) were
    asked for -- None otherwise."""

    counts: IntArray
    smooth: FloatArray | None = None
    status: StatusArray | None = None
    distance: FloatArray | None = None


class _EscapeField:
    """Shared tiering + output logic; subclasses define the two tier paths."""

    max_zoom_log10 = T1_MAX_ZOOM  # the deepest zoom these families render
    supports_distance = True  # a distance estimate needs an analytic map (not Burning Ship)

    def __init__(self, max_iter: int = 500, escape_radius: float = 1000.0) -> None:
        if max_iter < 1:
            raise ValueError("max_iter must be positive")
        self.max_iter = max_iter
        self.escape_radius = escape_radius

    def _compute(
        self, size: tuple[int, int], viewport: Viewport, distance: bool = False
    ) -> _Computed:
        zoom = viewport.zoom_log10
        if zoom <= T0_MAX_ZOOM:
            return self._compute_t0(size, viewport, distance)
        if zoom <= T1_MAX_ZOOM:
            counts, final, derivative = self._compute_t1(size, viewport, distance)
            status = np.where(counts > 0, ESCAPED, EXHAUSTED).astype(np.int8)
            return counts, final, status, derivative
        raise ValueError(
            f"zoom 1e{zoom:g} exceeds the float64 perturbation tier (~1e{T1_MAX_ZOOM:g}); "
            "the floatexp tier is not implemented yet"
        )

    def _compute_t0(
        self, size: tuple[int, int], viewport: Viewport, distance: bool = False
    ) -> _Computed:
        raise NotImplementedError

    def _compute_t1(
        self, size: tuple[int, int], viewport: Viewport, distance: bool = False
    ) -> _ComputedT1:
        raise NotImplementedError

    def fields(
        self,
        size: tuple[int, int],
        viewport: Viewport,
        *,
        smooth: bool = False,
        status: bool = False,
        distance: bool = False,
    ) -> EscapeFields:
        """One computation, every output a host asks for (spec/fractals.md): counts, and
        optionally smooth values, statuses and the distance estimate. Counts, smooth and
        status are exactly what iterations / counts_and_smooth / counts_and_status give.
        The distance estimate is Mandelbrot and Julia only, with 2 <= escape_radius <=
        1e64; it runs a separate loop that also carries the derivative."""
        if distance:
            if not self.supports_distance:
                raise ValueError(f"{type(self).__name__} has no distance estimate")
            if not 2.0 <= self.escape_radius <= 1e64:
                raise ValueError("a distance estimate needs 2 <= escape_radius <= 1e64")
        width, height = size
        counts, final, statuses, derivative = self._compute(size, viewport, distance)
        de = None
        if derivative is not None:
            de = distance_estimate(counts, final, *derivative).reshape(height, width)
        mu = smooth_iterations(counts, final, self.escape_radius) if smooth else None
        return EscapeFields(
            counts=counts.reshape(height, width),
            smooth=None if mu is None else mu.reshape(height, width),
            status=statuses.reshape(height, width) if status else None,
            distance=de,
        )

    def iterations(self, size: tuple[int, int], viewport: Viewport) -> IntArray:
        """Raw escape counts, shape (height, width). The bit-exact conformance output."""
        width, height = size
        counts, _, _, _ = self._compute(size, viewport)
        return counts.reshape(height, width)

    def counts_and_status(
        self, size: tuple[int, int], viewport: Viewport
    ) -> tuple[IntArray, StatusArray]:
        """Raw counts and how each was decided (spec/fractals.md "Status"), each
        (height, width): 0 escaped, 1 max_iter exhausted, 2 inside the cardioid or bulb,
        3 an exact cycle. A host tells "needs more iterations" (1) from "interior" (2, 3)."""
        width, height = size
        counts, _, status, _ = self._compute(size, viewport)
        return counts.reshape(height, width), status.reshape(height, width)

    def outputs(self, size: tuple[int, int], viewport: Viewport) -> dict[str, IntArray]:
        return {"iterations": self.iterations(size, viewport)}

    def counts_and_smooth(
        self, size: tuple[int, int], viewport: Viewport
    ) -> tuple[IntArray, FloatArray]:
        """Raw counts and smooth values mu (0 where interior), each (height, width),
        before normalization -- so a host can recolor without re-rendering."""
        width, height = size
        counts, final, _, _ = self._compute(size, viewport)
        mu = smooth_iterations(counts, final, self.escape_radius)
        return counts.reshape(height, width), mu.reshape(height, width)

    def render_and_counts(
        self, size: tuple[int, int], viewport: Viewport
    ) -> tuple[FloatArray, IntArray]:
        """One computation, both consumers: the render and the raw counts."""
        counts, mu = self.counts_and_smooth(size, viewport)
        return normalize_render(mu), counts

    def render(self, size: tuple[int, int], viewport: Viewport) -> FloatArray:
        """Smooth-colored field in [0,1] (Field protocol); interior is 0."""
        return self.render_and_counts(size, viewport)[0]


@dataclasses.dataclass(frozen=True)
class MandelbrotParams(Params):
    max_iter: int = 500
    escape_radius: float = 1000.0


class Mandelbrot(_EscapeField):
    """z <- z^2 + c, c = pixel, z0 = 0."""

    def _compute_t0(
        self, size: tuple[int, int], viewport: Viewport, distance: bool = False
    ) -> _Computed:
        c = pixel_grid(size, viewport)
        # Only where no interior orbit can cross the radius (|z| stays below 2 in M).
        inside = cardioid_or_bulb(c) if self.escape_radius >= 2.0 else np.zeros(c.size, dtype=bool)
        counts = np.full(c.size, -1, dtype=np.int32)
        final = np.zeros(c.size, dtype=np.complex128)
        status = np.full(c.size, CARDIOID_OR_BULB, dtype=np.int8)
        rest = ~inside
        rest_c = c[rest]
        if not distance:
            counts[rest], final[rest], status[rest] = escape_time(
                np.zeros_like(rest_c), rest_c, _z2_update, self.max_iter, self.escape_radius
            )
            return counts, final, status, None
        dr = np.zeros(c.size, dtype=np.float64)
        di = np.zeros(c.size, dtype=np.float64)
        ps = pixel_scale(size, viewport)
        counts[rest], final[rest], status[rest], (dr[rest], di[rest]) = escape_time_distance(
            np.zeros_like(rest_c), rest_c, self.max_iter, self.escape_radius, (0.0, 0.0), ps
        )
        return counts, final, status, (dr, di)

    def _compute_t1(
        self, size: tuple[int, int], viewport: Viewport, distance: bool = False
    ) -> _ComputedT1:
        orbit = reference_orbit(
            "mandelbrot", *viewport.orbit_center, viewport.zoom_log10, self.max_iter
        )
        dc = pixel_deltas(size, viewport)
        if not distance:
            counts, final = perturb_z2(
                orbit, np.zeros_like(dc), dc, self.max_iter, self.escape_radius
            )
            return counts, final, None
        ps = pixel_scale(size, viewport)
        return perturb_z2_distance(
            orbit, np.zeros_like(dc), dc, self.max_iter, self.escape_radius, (0.0, 0.0), ps
        )


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
        self, size: tuple[int, int], viewport: Viewport, distance: bool = False
    ) -> _Computed:
        z0 = pixel_grid(size, viewport)
        c = np.full_like(z0, self.c)
        if not distance:
            return (*escape_time(z0, c, _z2_update, self.max_iter, self.escape_radius), None)
        ps = pixel_scale(size, viewport)
        return escape_time_distance(z0, c, self.max_iter, self.escape_radius, (ps, 0.0), None)

    def _compute_t1(
        self, size: tuple[int, int], viewport: Viewport, distance: bool = False
    ) -> _ComputedT1:
        orbit = reference_orbit(
            "julia",
            *viewport.orbit_center,
            viewport.zoom_log10,
            self.max_iter,
            c_re=self.c.real,
            c_im=self.c.imag,
        )
        # Rebasing restarts a pixel on an orbit that begins at 0; the reference
        # above begins at the center, so rebased pixels follow the critical orbit
        # (spec/deep-zoom.md "Rebasing"): center "0", so the zoom alone sets its precision.
        critical = reference_orbit(
            "julia",
            "0",
            "0",
            viewport.zoom_log10,
            self.max_iter,
            c_re=self.c.real,
            c_im=self.c.imag,
        )
        dz0 = pixel_deltas(size, viewport)
        dc = np.zeros_like(dz0)
        if not distance:
            counts, final = perturb_z2(
                orbit, dz0, dc, self.max_iter, self.escape_radius, rebase_orbit=critical
            )
            return counts, final, None
        ps = pixel_scale(size, viewport)
        return perturb_z2_distance(
            orbit, dz0, dc, self.max_iter, self.escape_radius, (ps, 0.0), None, critical
        )


@dataclasses.dataclass(frozen=True)
class BurningShipParams(Params):
    max_iter: int = 500
    escape_radius: float = 1000.0


class BurningShip(_EscapeField):
    """z <- (|Re z| + i |Im z|)^2 + c, c = pixel, z0 = 0."""

    supports_distance = False  # the folds make the map non-analytic

    def _compute_t0(
        self, size: tuple[int, int], viewport: Viewport, distance: bool = False
    ) -> _Computed:
        c = pixel_grid(size, viewport)
        z0 = np.zeros_like(c)
        return (*escape_time(z0, c, _ship_update, self.max_iter, self.escape_radius), None)

    def _compute_t1(
        self, size: tuple[int, int], viewport: Viewport, distance: bool = False
    ) -> _ComputedT1:
        orbit = reference_orbit(
            "burning_ship", *viewport.orbit_center, viewport.zoom_log10, self.max_iter
        )
        dc = pixel_deltas(size, viewport)
        return (*perturb_burning_ship(orbit, dc, self.max_iter, self.escape_radius), None)
