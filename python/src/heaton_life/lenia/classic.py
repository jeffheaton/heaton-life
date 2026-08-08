"""Classic Lenia (Chan 2018): additive growth with clipping."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from heaton_life.lenia.base import LeniaBase, LeniaParams, make_lenia_params


class ClassicLenia(LeniaBase):
    """A <- clip(A + dt * G(K * A), 0, 1)"""

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
    def from_params(cls, params: LeniaParams) -> ClassicLenia:
        if params.init == "array":
            raise ValueError("params with init='array' need the array: ClassicLenia(init=...)")
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
        growth = self._growth(self._potential())
        self._state = np.clip(self._state + self.params.dt * growth, 0.0, 1.0)
