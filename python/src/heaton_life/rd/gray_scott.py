"""Gray-Scott reaction-diffusion — spec/grayscott.md.

Two species U (substrate) and V (activator) on a torus:

    dU/dt = du * lap(U) - U*V^2 + feed * (1 - U)
    dV/dt = dv * lap(V) + U*V^2 - (feed + kill) * V

Explicit Euler, 5-point Laplacian, the classic discrete formulation (du=0.16,
dv=0.08, dt=1 is stable). The (feed, kill) plane is the phase diagram; the presets
are well-known coordinates in it.
"""

from __future__ import annotations

import dataclasses

import numpy as np
from numpy.typing import NDArray

from heaton_life.core.params import Params
from heaton_life.core.rng import Pcg32
from heaton_life.core.stencil import laplacian5

GRAY_SCOTT_PRESETS: dict[str, dict[str, float]] = {
    "Mitosis": {"feed": 0.0367, "kill": 0.0649},
    "Coral": {"feed": 0.0545, "kill": 0.062},
    "Worms": {"feed": 0.046, "kill": 0.063},
    "Maze": {"feed": 0.029, "kill": 0.057},
    "Solitons": {"feed": 0.03, "kill": 0.062},
    "Chaos": {"feed": 0.026, "kill": 0.051},
    "U-Skate": {"feed": 0.062, "kill": 0.0609},
}


@dataclasses.dataclass(frozen=True)
class GrayScottParams(Params):
    du: float = dataclasses.field(default=0.16, metadata={"min": 0.01, "max": 0.4, "step": 0.01})
    dv: float = dataclasses.field(default=0.08, metadata={"min": 0.01, "max": 0.4, "step": 0.01})
    feed: float = dataclasses.field(
        default=0.0545, metadata={"min": 0.0, "max": 0.12, "step": 0.001, "decimals": 4}
    )
    kill: float = dataclasses.field(
        default=0.062, metadata={"min": 0.0, "max": 0.08, "step": 0.001, "decimals": 4}
    )
    dt: float = dataclasses.field(default=1.0, metadata={"min": 0.1, "max": 1.5, "step": 0.1})
    width: int = dataclasses.field(default=256, metadata={"min": 16, "max": 1024})
    height: int = dataclasses.field(default=256, metadata={"min": 16, "max": 1024})
    init: str = dataclasses.field(default="spots", metadata={"choices": ["spots", "center"]})
    spots: int = dataclasses.field(default=20, metadata={"min": 1, "max": 200})
    seed: int = dataclasses.field(
        default=0, metadata={"min": 0, "max": 4294967295, "role": "seed"}
    )


class GrayScott:
    """Gray-Scott. State is float64, shape (2, height, width): state[0]=U, state[1]=V."""

    def __init__(
        self,
        *,
        size: tuple[int, int] = (256, 256),
        du: float = 0.16,
        dv: float = 0.08,
        feed: float = 0.0545,
        kill: float = 0.062,
        dt: float = 1.0,
        init: str | NDArray[np.float64] = "spots",
        spots: int = 20,
        seed: int = 0,
    ) -> None:
        width, height = size
        self._initial: NDArray[np.float64] | None = None
        if isinstance(init, np.ndarray):
            if init.shape != (2, height, width):
                raise ValueError(
                    f"init array shape {init.shape} does not match (2, h={height}, w={width})"
                )
            self._initial = init.astype(np.float64)
            init_name = "array"
        else:
            init_name = init
        self.params = GrayScottParams(
            du=du,
            dv=dv,
            feed=feed,
            kill=kill,
            dt=dt,
            width=width,
            height=height,
            init=init_name,
            spots=spots,
            seed=seed,
        )
        self._generation = 0
        self._state: NDArray[np.float64]
        self.reset()

    @classmethod
    def from_params(cls, params: GrayScottParams) -> GrayScott:
        if params.init == "array":
            raise ValueError("params with init='array' need the array: GrayScott(init=...)")
        return cls(
            size=(params.width, params.height),
            du=params.du,
            dv=params.dv,
            feed=params.feed,
            kill=params.kill,
            dt=params.dt,
            init=params.init,
            spots=params.spots,
            seed=params.seed,
        )

    def reset(self, seed: int | None = None) -> None:
        if seed is not None:
            self.params = self.params.replace(seed=seed)
        p = self.params
        if p.init == "array":
            assert self._initial is not None
            self._state = self._initial.copy()
            self._generation = 0
            return
        u = np.ones((p.height, p.width), dtype=np.float64)
        v = np.zeros((p.height, p.width), dtype=np.float64)
        if p.init == "spots":
            rng = Pcg32(p.seed)
            for _ in range(p.spots):
                cx = rng.next_u32() % p.width
                cy = rng.next_u32() % p.height
                _seed_box(u, v, cx, cy)
        elif p.init == "center":
            _seed_box(u, v, p.width // 2, p.height // 2)
        else:
            raise ValueError(f"unknown init strategy: {p.init!r}")
        self._state = np.stack([u, v])
        self._generation = 0

    def step(self, n: int = 1) -> None:
        p = self.params
        u, v = self._state[0], self._state[1]
        for _ in range(n):
            lap_u = laplacian5(u)
            lap_v = laplacian5(v)
            uvv = u * v * v
            u += p.dt * (p.du * lap_u - uvv + p.feed * (1.0 - u))
            v += p.dt * (p.dv * lap_v + uvv - (p.feed + p.kill) * v)
        self._generation += n

    @property
    def state(self) -> NDArray[np.float64]:
        return self._state

    @property
    def generation(self) -> int:
        return self._generation

    def frame(self) -> NDArray[np.float64]:
        # V is where the patterns live; ~0.4 is its practical ceiling.
        result: NDArray[np.float64] = np.clip(self._state[1] * 2.5, 0.0, 1.0)
        return result


def _seed_box(
    u: NDArray[np.float64], v: NDArray[np.float64], cx: int, cy: int, half: int = 3
) -> None:
    """Spec'd seed: a clipped (2*half+1)^2 box with U=0.5, V=0.25."""
    height, width = u.shape
    ys = slice(max(0, cy - half), min(height, cy + half + 1))
    xs = slice(max(0, cx - half), min(width, cx + half + 1))
    u[ys, xs] = 0.5
    v[ys, xs] = 0.25
