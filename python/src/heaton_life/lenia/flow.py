"""Flow Lenia (Plantec et al. 2022, simplified single-channel form): mass-conserving.

Matter flows along the growth gradient, switching to diffusion (down its own
concentration gradient) where it crowds: F = (1-alpha)*grad(G) - alpha*grad(A),
alpha = clip((A/theta)^2, 0, 1). Mass then advects by bilinear reintegration —
each cell's mass is distributed over the 4 cells around its displaced position
(this is the paper's reintegration tracking with a unit square). Total mass is
conserved by construction; patterns emerge purely from transport.
"""

from __future__ import annotations

import dataclasses

import numpy as np
from numpy.typing import NDArray

from heaton_life.core.stencil import gradient_torus
from heaton_life.lenia.base import LeniaBase, LeniaParams, make_lenia_params

MAX_DISPLACEMENT = 0.9  # cells per step; keeps the bilinear scatter local


@dataclasses.dataclass(frozen=True)
class FlowLeniaParams(LeniaParams):
    # Flow works at larger dt and higher mu than classic Lenia (mass must aggregate:
    # mu above the mean potential makes growth gradients point toward mass).
    mu: float = dataclasses.field(
        default=0.3, metadata={"min": 0.01, "max": 1.0, "step": 0.005, "decimals": 4}
    )
    sigma: float = dataclasses.field(
        default=0.08, metadata={"min": 0.001, "max": 0.2, "step": 0.001, "decimals": 4}
    )
    dt: float = dataclasses.field(default=2.0, metadata={"min": 0.1, "max": 8.0, "step": 0.1})
    theta: float = dataclasses.field(
        default=2.0, metadata={"min": 0.1, "max": 5.0, "step": 0.1}
    )


class FlowLenia(LeniaBase):
    params: FlowLeniaParams

    def __init__(
        self,
        *,
        size: tuple[int, int] = (128, 128),
        radius: int = 13,
        mu: float = 0.3,
        sigma: float = 0.08,
        dt: float = 2.0,
        theta: float = 2.0,
        init: str | NDArray[np.float64] = "soup",
        blobs: int = 40,
        density: float = 0.5,
        seed: int = 0,
    ) -> None:
        params, initial = make_lenia_params(
            FlowLeniaParams,
            size,
            init,
            radius=radius,
            mu=mu,
            sigma=sigma,
            dt=dt,
            theta=theta,
            blobs=blobs,
            density=density,
            seed=seed,
        )
        assert isinstance(params, FlowLeniaParams)
        super().__init__(params, initial)

    @classmethod
    def from_params(cls, params: FlowLeniaParams) -> FlowLenia:
        if params.init == "array":
            raise ValueError("params with init='array' need the array: FlowLenia(init=...)")
        return cls(
            size=(params.width, params.height),
            radius=params.radius,
            mu=params.mu,
            sigma=params.sigma,
            dt=params.dt,
            theta=params.theta,
            init=params.init,
            blobs=params.blobs,
            density=params.density,
            seed=params.seed,
        )

    def _step_once(self) -> None:
        p = self.params
        a = self._state
        growth = self._growth(self._potential())
        gy_g, gx_g = gradient_torus(growth)
        gy_a, gx_a = gradient_torus(a)
        alpha = np.clip((a / p.theta) ** 2, 0.0, 1.0)
        flow_y = (1.0 - alpha) * gy_g - alpha * gy_a
        flow_x = (1.0 - alpha) * gx_g - alpha * gx_a
        dy = np.clip(p.dt * flow_y, -MAX_DISPLACEMENT, MAX_DISPLACEMENT)
        dx = np.clip(p.dt * flow_x, -MAX_DISPLACEMENT, MAX_DISPLACEMENT)
        self._state = _advect_bilinear(a, dy, dx)


def _advect_bilinear(
    a: NDArray[np.float64], dy: NDArray[np.float64], dx: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Scatter each cell's mass to the 4 cells around (y+dy, x+dx), torus wrap."""
    height, width = a.shape
    yy, xx = np.mgrid[0:height, 0:width]
    ty = yy + dy
    tx = xx + dx
    y0 = np.floor(ty).astype(np.int64)
    x0 = np.floor(tx).astype(np.int64)
    wy = ty - y0
    wx = tx - x0
    new = np.zeros_like(a)
    for iy, ix, w in (
        (y0, x0, (1.0 - wy) * (1.0 - wx)),
        (y0, x0 + 1, (1.0 - wy) * wx),
        (y0 + 1, x0, wy * (1.0 - wx)),
        (y0 + 1, x0 + 1, wy * wx),
    ):
        np.add.at(new, (iy % height, ix % width), a * w)
    return new
