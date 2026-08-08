"""Playground adapter: fractal Fields exposed through the Simulation protocol.

A fractal doesn't step — step() is a no-op and frame() lazily renders the current
params (viewport lives in the params so the auto-generated form edits it). Click
and wheel zoom arrive through the paint path and return a *new* sim, which the
engine swaps in and reports back so the form stays in sync.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from decimal import Decimal, localcontext
from math import log10
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from heaton_life.core.params import Params
from heaton_life.core.viewport import Viewport
from heaton_life.fractal import BurningShip, Julia, Mandelbrot, Newton


class _RenderField(Protocol):
    def render(
        self, size: tuple[int, int], viewport: Viewport
    ) -> NDArray[np.float64]: ...


_VIEW_META = {"label": "Center Re"}
_ZOOM_META = {"min": -2.0, "max": 290.0, "step": 0.5, "label": "Zoom (log10)"}
_ITER_META = {"min": 16, "max": 200000}


@dataclasses.dataclass(frozen=True)
class MandelbrotSimParams(Params):
    center_re: str = dataclasses.field(default="-0.5", metadata=_VIEW_META)
    center_im: str = dataclasses.field(default="0.0", metadata={"label": "Center Im"})
    zoom_log10: float = dataclasses.field(default=0.0, metadata=_ZOOM_META)
    max_iter: int = dataclasses.field(default=500, metadata=_ITER_META)
    width: int = dataclasses.field(default=384, metadata={"min": 64, "max": 1024})
    height: int = dataclasses.field(default=384, metadata={"min": 64, "max": 1024})


@dataclasses.dataclass(frozen=True)
class JuliaSimParams(Params):
    c_re: float = dataclasses.field(
        default=-0.7269, metadata={"min": -2.0, "max": 2.0, "step": 0.001, "decimals": 4}
    )
    c_im: float = dataclasses.field(
        default=0.1889, metadata={"min": -2.0, "max": 2.0, "step": 0.001, "decimals": 4}
    )
    center_re: str = dataclasses.field(default="0.0", metadata=_VIEW_META)
    center_im: str = dataclasses.field(default="0.0", metadata={"label": "Center Im"})
    zoom_log10: float = dataclasses.field(default=0.0, metadata=_ZOOM_META)
    max_iter: int = dataclasses.field(default=500, metadata=_ITER_META)
    width: int = dataclasses.field(default=384, metadata={"min": 64, "max": 1024})
    height: int = dataclasses.field(default=384, metadata={"min": 64, "max": 1024})


@dataclasses.dataclass(frozen=True)
class BurningShipSimParams(Params):
    center_re: str = dataclasses.field(default="-0.5", metadata=_VIEW_META)
    center_im: str = dataclasses.field(default="-0.5", metadata={"label": "Center Im"})
    zoom_log10: float = dataclasses.field(default=-0.2, metadata=_ZOOM_META)
    max_iter: int = dataclasses.field(default=500, metadata=_ITER_META)
    width: int = dataclasses.field(default=384, metadata={"min": 64, "max": 1024})
    height: int = dataclasses.field(default=384, metadata={"min": 64, "max": 1024})


@dataclasses.dataclass(frozen=True)
class NewtonSimParams(Params):
    degree: int = dataclasses.field(default=3, metadata={"min": 2, "max": 8})
    center_re: str = dataclasses.field(default="0.0", metadata=_VIEW_META)
    center_im: str = dataclasses.field(default="0.0", metadata={"label": "Center Im"})
    zoom_log10: float = dataclasses.field(
        default=-0.1, metadata={"min": -2.0, "max": 12.0, "step": 0.5, "label": "Zoom (log10)"}
    )
    max_iter: int = dataclasses.field(default=60, metadata={"min": 8, "max": 500})
    width: int = dataclasses.field(default=384, metadata={"min": 64, "max": 1024})
    height: int = dataclasses.field(default=384, metadata={"min": 64, "max": 1024})


def make_mandelbrot(p: Params) -> _RenderField:
    assert isinstance(p, MandelbrotSimParams)
    return Mandelbrot(max_iter=p.max_iter)


def make_julia(p: Params) -> _RenderField:
    assert isinstance(p, JuliaSimParams)
    return Julia(c=complex(p.c_re, p.c_im), max_iter=p.max_iter)


def make_burning_ship(p: Params) -> _RenderField:
    assert isinstance(p, BurningShipSimParams)
    return BurningShip(max_iter=p.max_iter)


def make_newton(p: Params) -> _RenderField:
    assert isinstance(p, NewtonSimParams)
    return Newton(degree=p.degree, max_iter=p.max_iter)


AUTOZOOM_ZOOM_PER_STEP = 0.02  # decades of magnification per step (speed slider throttles)
_AUTOZOOM_DRIFT = Decimal("0.2")  # fraction of the way toward the target per step


class FractalSim:
    """Simulation-protocol adapter around a Field; render is lazy and cached.

    step() is autozoom: drift the center toward nearby boundary structure (the
    highest escape counts — never the black interior) and zoom in a notch. Play
    starts it, Pause stops it, the speed slider sets the dive rate.
    """

    def __init__(
        self,
        params: Params,
        make_field: Callable[[Params], _RenderField],
        *,
        zoom_max: float = 290.0,
    ) -> None:
        self.params = params
        self.zoom_max = zoom_max
        self._make_field = make_field
        self._field = make_field(params)
        self._frame: NDArray[np.float64] | None = None
        self._counts: NDArray[np.int32] | None = None
        self._generation = 0

    def step(self, n: int = 1) -> None:
        self._generation += n
        p: Any = self.params
        old_zoom = float(p.zoom_log10)
        if old_zoom >= self.zoom_max:
            return
        new_zoom = min(old_zoom + AUTOZOOM_ZOOM_PER_STEP * n, self.zoom_max)
        target = self._find_target()
        if target is None:  # nothing non-black to chase: hold center, keep zooming
            self.params = p.replace(zoom_log10=new_zoom)
        else:
            x, y = target
            with localcontext() as ctx:
                ctx.prec = max(int(old_zoom), 0) + 40
                pixel = (
                    Decimal(4) / (Decimal(10) ** Decimal(repr(old_zoom))) / Decimal(p.width)
                )
                off_x = (Decimal(x) + Decimal("0.5") - Decimal(p.width) / 2) * pixel
                off_y = (Decimal(y) + Decimal("0.5") - Decimal(p.height) / 2) * pixel
                new_re = Decimal(p.center_re) + off_x * _AUTOZOOM_DRIFT
                new_im = Decimal(p.center_im) - off_y * _AUTOZOOM_DRIFT
            self.params = p.replace(
                center_re=str(new_re), center_im=str(new_im), zoom_log10=new_zoom
            )
        self._frame = None  # counts stay until the next render refreshes them

    def _find_target(self) -> tuple[int, int] | None:
        """Nearest-to-center pixel among the top escape counts (boundary huggers).

        Threshold is relative to the frame's max count — a percentile collapses to
        the mode when most escaped pixels tie at a low count, which would stop the
        drift dead.
        """
        counts = self._counts
        if counts is None:
            return None
        escaped = counts > 0
        if not escaped.any():
            return None
        threshold = 0.9 * float(counts.max())
        ys, xs = np.nonzero(escaped & (counts >= threshold))
        height, width = counts.shape
        d2 = (xs - width / 2.0) ** 2 + (ys - height / 2.0) ** 2
        nearest = int(np.argmin(d2))
        return int(xs[nearest]), int(ys[nearest])

    def reset(self, seed: int | None = None) -> None:
        self._frame = None
        self._generation = 0

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def state(self) -> NDArray[np.float64]:
        return self.frame()

    def frame(self) -> NDArray[np.float64]:
        if self._frame is None:
            p: Any = self.params
            viewport = Viewport(p.center_re, p.center_im, p.zoom_log10)
            render_and_counts = getattr(self._field, "render_and_counts", None)
            if callable(render_and_counts):
                self._frame, self._counts = render_and_counts((p.width, p.height), viewport)
            else:
                self._frame = self._field.render((p.width, p.height), viewport)
        return self._frame


_LOG4 = log10(4.0)
_LOG2 = log10(2.0)


def zoom_paint(
    sim: FractalSim,
    x: int,
    y: int,
    button: int,
    build: Callable[[Params], FractalSim],
    zoom_max: float,
) -> FractalSim | None:
    """Click/wheel navigation. 1: recenter (zoom unchanged); 2: out x4 (keep center);
    3 (Ctrl+click): recenter + in x4; 4/5: wheel in/out x2 anchored at the cursor."""
    if button not in (1, 2, 3, 4, 5):
        return None
    p: Any = sim.params
    old_zoom = float(p.zoom_log10)
    delta = {1: 0.0, 2: -_LOG4, 3: _LOG4, 4: _LOG2, 5: -_LOG2}[button]
    new_zoom = min(max(old_zoom + delta, -2.0), zoom_max)

    with localcontext() as ctx:
        ctx.prec = max(int(old_zoom), 0) + 40
        pixel = (
            Decimal(4)
            / (Decimal(10) ** Decimal(repr(old_zoom)))
            / Decimal(p.width)
        )
        off_x = (Decimal(x) + Decimal("0.5") - Decimal(p.width) / 2) * pixel
        off_y = (Decimal(y) + Decimal("0.5") - Decimal(p.height) / 2) * pixel
        point_re = Decimal(p.center_re) + off_x
        point_im = Decimal(p.center_im) - off_y
        if button in (1, 3):  # recenter on the click
            new_re, new_im = point_re, point_im
        elif button == 2:  # zoom out about the current center
            new_re, new_im = Decimal(p.center_re), Decimal(p.center_im)
        else:  # wheel: keep the point under the cursor fixed
            shrink = Decimal(10) ** (Decimal(repr(old_zoom)) - Decimal(repr(new_zoom)))
            new_re = point_re - (point_re - Decimal(p.center_re)) * shrink
            new_im = point_im - (point_im - Decimal(p.center_im)) * shrink

    new_params = sim.params.replace(
        center_re=str(new_re), center_im=str(new_im), zoom_log10=new_zoom
    )
    return build(new_params)
