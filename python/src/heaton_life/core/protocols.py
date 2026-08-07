"""The two public contracts: time-stepped simulations and rendered fields.

Frames are always renderable arrays: 2-D uint8 (palette index), 2-D float in [0, 1]
(colormapped by the render layer), or HxWx3 uint8 RGB (passed through).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from heaton_life.core.viewport import Viewport


@runtime_checkable
class Simulation(Protocol):
    """A time-stepped system: CA, Lenia, reaction-diffusion, boids."""

    def step(self, n: int = 1) -> None: ...

    def reset(self, seed: int | None = None) -> None: ...

    @property
    def state(self) -> NDArray[Any]:
        """Raw simulation state, family-shaped. Not necessarily renderable."""
        ...

    def frame(self) -> NDArray[Any]:
        """A renderable view of the current state (see module docstring for shapes)."""
        ...


@runtime_checkable
class Field(Protocol):
    """A rendered field over the complex plane: fractals. No time evolution."""

    def render(self, size: tuple[int, int], viewport: Viewport) -> NDArray[np.float64]:
        """Render at (width, height) pixels; returns a 2-D float array for colormapping."""
        ...
