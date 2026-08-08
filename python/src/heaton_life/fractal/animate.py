"""Zoom movies: render a viewport approach as an Animation."""

from __future__ import annotations

from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from heaton_life.core.viewport import Viewport
from heaton_life.render import Animation, apply_colormap


class _Renderable(Protocol):
    def render(
        self, size: tuple[int, int], viewport: Viewport
    ) -> NDArray[np.float64]: ...


def zoom_animation(
    field: _Renderable,
    size: tuple[int, int],
    target: Viewport,
    *,
    steps: int = 60,
    start_zoom: float = 0.0,
    cmap: str = "fire",
    fps: int = 30,
    scale: int = 1,
) -> Animation:
    """Frames from start_zoom to target.zoom_log10 at the target's center."""
    if steps < 2:
        raise ValueError("steps must be >= 2")
    zooms = np.linspace(start_zoom, target.zoom_log10, steps)
    frames = []
    for zoom in zooms:
        viewport = Viewport(target.center_re, target.center_im, float(zoom))
        frames.append(apply_colormap(field.render(size, viewport), cmap))
    return Animation(frames, fps=fps, scale=scale)
