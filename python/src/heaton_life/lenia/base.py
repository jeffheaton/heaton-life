"""Shared Lenia machinery: params, seeding, kernel/potential/growth pipeline."""

from __future__ import annotations

import dataclasses

import numpy as np
from numpy.typing import NDArray

from heaton_life.core.fftconv import fft_convolve, kernel_fft
from heaton_life.core.params import Params
from heaton_life.core.rng import Pcg32
from heaton_life.lenia.kernels import ring_kernel


@dataclasses.dataclass(frozen=True)
class LeniaParams(Params):
    radius: int = dataclasses.field(default=13, metadata={"min": 2, "max": 64})
    mu: float = dataclasses.field(
        default=0.15, metadata={"min": 0.01, "max": 1.0, "step": 0.005, "decimals": 4}
    )
    sigma: float = dataclasses.field(
        default=0.017, metadata={"min": 0.001, "max": 0.2, "step": 0.001, "decimals": 4}
    )
    dt: float = dataclasses.field(default=0.1, metadata={"min": 0.01, "max": 1.0, "step": 0.05})
    width: int = dataclasses.field(default=128, metadata={"min": 32, "max": 1024})
    height: int = dataclasses.field(default=128, metadata={"min": 32, "max": 1024})
    init: str = dataclasses.field(default="blobs", metadata={"choices": ["blobs", "soup"]})
    blobs: int = dataclasses.field(default=40, metadata={"min": 1, "max": 100})
    density: float = dataclasses.field(
        default=0.5, metadata={"min": 0.0, "max": 1.0, "step": 0.05}
    )
    seed: int = dataclasses.field(
        default=0, metadata={"min": 0, "max": 4294967295, "role": "seed"}
    )


class LeniaBase:
    """Common state/kernel/growth plumbing; subclasses implement `_step_once`."""

    def __init__(self, params: LeniaParams, initial: NDArray[np.float64] | None) -> None:
        self.params = params
        self._initial = initial
        self._kfft = kernel_fft(ring_kernel((params.width, params.height), params.radius))
        self._generation = 0
        self._state: NDArray[np.float64]
        self.reset()

    def reset(self, seed: int | None = None) -> None:
        if seed is not None:
            self.params = self.params.replace(seed=seed)
        p = self.params
        if p.init == "array":
            assert self._initial is not None
            self._state = self._initial.copy()
        elif p.init == "soup":
            draws = Pcg32(p.seed).fill_u32(p.width * p.height).reshape(p.height, p.width)
            self._state = draws.astype(np.float64) / 4294967296.0 * p.density
        elif p.init == "blobs":
            self._state = _blobs(p)
        else:
            raise ValueError(f"unknown init strategy: {p.init!r}")
        self._generation = 0

    def step(self, n: int = 1) -> None:
        for _ in range(n):
            self._step_once()
        self._generation += n

    def _step_once(self) -> None:
        raise NotImplementedError

    def _potential(self) -> NDArray[np.float64]:
        return fft_convolve(self._state, self._kfft)

    def _growth(self, potential: NDArray[np.float64]) -> NDArray[np.float64]:
        """Exponential growth in [-1, 1]: 2*exp(-(u-mu)^2 / (2 sigma^2)) - 1."""
        p = self.params
        diff = potential - p.mu
        result: NDArray[np.float64] = 2.0 * np.exp(-(diff * diff) / (2.0 * p.sigma * p.sigma)) - 1.0
        return result

    @property
    def state(self) -> NDArray[np.float64]:
        return self._state

    @property
    def generation(self) -> int:
        return self._generation

    def frame(self) -> NDArray[np.float64]:
        return self._state


def _blobs(p: LeniaParams) -> NDArray[np.float64]:
    """Seeded gaussian bumps; wrapped distances; 3 draws per blob (cx, cy, amplitude)."""
    rng = Pcg32(p.seed)
    a = np.zeros((p.height, p.width), dtype=np.float64)
    ys = np.arange(p.height, dtype=np.float64)[:, None]
    xs = np.arange(p.width, dtype=np.float64)[None, :]
    rb = max(p.radius / 2.0, 1.0)
    for _ in range(p.blobs):
        cx = rng.next_u32() % p.width
        cy = rng.next_u32() % p.height
        amp = 0.5 + 0.5 * (rng.next_u32() / 4294967296.0)
        dy = np.minimum(np.abs(ys - cy), p.height - np.abs(ys - cy))
        dx = np.minimum(np.abs(xs - cx), p.width - np.abs(xs - cx))
        a += amp * np.exp(-(dx * dx + dy * dy) / (2.0 * rb * rb))
    result: NDArray[np.float64] = np.clip(a, 0.0, 1.0)
    return result


def make_lenia_params(
    cls: type[LeniaParams],
    size: tuple[int, int],
    init: str | NDArray[np.float64],
    **kwargs: object,
) -> tuple[LeniaParams, NDArray[np.float64] | None]:
    """Shared constructor plumbing: array-init detection + params assembly."""
    width, height = size
    initial: NDArray[np.float64] | None = None
    if isinstance(init, np.ndarray):
        if init.shape != (height, width):
            raise ValueError(f"init array shape {init.shape} does not match (h={height}, w={width})")
        initial = init.astype(np.float64)
        init_name = "array"
    else:
        init_name = init
    params = cls(width=width, height=height, init=init_name, **kwargs)  # type: ignore[arg-type]
    return params, initial
