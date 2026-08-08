"""Asymptotic Lenia (Kawaguchi et al. 2021): relax toward a target, no clipping.

T(u) = (G(u) + 1) / 2 in [0, 1];  A <- A + dt * (T(K * A) - A).
With dt <= 1 the update is a convex combination, so A stays in [0, 1] naturally.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from heaton_life.lenia.base import LeniaBase, LeniaParams, make_lenia_params


class AsymptoticLenia(LeniaBase):
    """A <- A + dt * (T(K * A) - A), T = (G + 1) / 2"""

    def __init__(
        self,
        *,
        size: tuple[int, int] = (128, 128),
        radius: int = 13,
        mu: float = 0.15,
        sigma: float = 0.017,
        dt: float = 0.1,
        init: str | NDArray[np.float64] = "blobs",
        blobs: int = 40,
        density: float = 0.5,
        seed: int = 0,
    ) -> None:
        params, initial = make_lenia_params(
            LeniaParams,
            size,
            init,
            radius=radius,
            mu=mu,
            sigma=sigma,
            dt=dt,
            blobs=blobs,
            density=density,
            seed=seed,
        )
        super().__init__(params, initial)

    @classmethod
    def from_params(cls, params: LeniaParams) -> AsymptoticLenia:
        if params.init == "array":
            raise ValueError("params with init='array' need the array: AsymptoticLenia(init=...)")
        return cls(
            size=(params.width, params.height),
            radius=params.radius,
            mu=params.mu,
            sigma=params.sigma,
            dt=params.dt,
            init=params.init,
            blobs=params.blobs,
            density=params.density,
            seed=params.seed,
        )

    def _step_once(self) -> None:
        target = (self._growth(self._potential()) + 1.0) / 2.0
        self._state = self._state + self.params.dt * (target - self._state)
