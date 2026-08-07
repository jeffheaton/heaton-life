"""Life-like cellular automata (spec/lifelike.md): binary state, Moore neighborhood, B/S rules."""

from __future__ import annotations

import dataclasses
from typing import cast

import numpy as np
from numpy.typing import NDArray

from heaton_life.ca.rulestring import canonical_rule, parse_rule
from heaton_life.core.neighbors import Boundary, moore_sum
from heaton_life.core.params import Params
from heaton_life.init import blob, single, soup


@dataclasses.dataclass(frozen=True)
class LifeLikeParams(Params):
    rule: str = "B3/S23"
    width: int = 256
    height: int = 256
    init: str = "soup"
    density: float = 0.35
    seed: int = 0
    boundary: str = "torus"


class LifeLike:
    """A Life-like CA. State is uint8 0/1, shape (height, width), row-major."""

    def __init__(
        self,
        rule: str = "B3/S23",
        *,
        size: tuple[int, int] = (256, 256),
        init: str | NDArray[np.uint8] = "soup",
        density: float = 0.35,
        seed: int = 0,
        boundary: Boundary = "torus",
    ) -> None:
        width, height = size
        self._initial: NDArray[np.uint8] | None = None
        if isinstance(init, np.ndarray):
            if init.shape != (height, width):
                raise ValueError(
                    f"init array shape {init.shape} does not match size (h={height}, w={width})"
                )
            self._initial = (init > 0).astype(np.uint8)
            init_name = "array"
        else:
            init_name = init
        self.params = LifeLikeParams(
            rule=canonical_rule(rule),
            width=width,
            height=height,
            init=init_name,
            density=density,
            seed=seed,
            boundary=boundary,
        )
        birth, survive = parse_rule(self.params.rule)
        self._lut = np.zeros((2, 9), dtype=np.uint8)
        self._lut[0, sorted(birth)] = 1
        self._lut[1, sorted(survive)] = 1
        self._generation = 0
        self._state: NDArray[np.uint8]
        self.reset()

    @classmethod
    def from_params(cls, params: LifeLikeParams) -> LifeLike:
        if params.init == "array":
            raise ValueError("params with init='array' cannot be reconstructed; pass the array to LifeLike(init=...)")
        return cls(
            params.rule,
            size=(params.width, params.height),
            init=params.init,
            density=params.density,
            seed=params.seed,
            boundary=cast(Boundary, params.boundary),
        )

    def reset(self, seed: int | None = None) -> None:
        if seed is not None:
            self.params = self.params.replace(seed=seed)
        p = self.params
        size = (p.width, p.height)
        if p.init == "array":
            assert self._initial is not None
            state = self._initial.copy()
        elif p.init == "soup":
            state = soup(size, density=p.density, seed=p.seed)
        elif p.init == "blob":
            state = blob(size, density=p.density, seed=p.seed)
        elif p.init == "single":
            state = single(size)
        else:
            raise ValueError(f"unknown init strategy: {p.init!r}")
        self._state = state
        self._generation = 0

    def step(self, n: int = 1) -> None:
        boundary = cast(Boundary, self.params.boundary)
        for _ in range(n):
            counts = moore_sum(self._state, boundary)
            self._state = self._lut[self._state, counts]
        self._generation += n

    @property
    def state(self) -> NDArray[np.uint8]:
        return self._state

    @property
    def generation(self) -> int:
        return self._generation

    def frame(self) -> NDArray[np.uint8]:
        return self._state * np.uint8(255)
