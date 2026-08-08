"""Cyclic cellular automata (Griffeath) — spec/cyclic.md.

Each cell advances to the successor state (mod n) when at least `threshold`
neighbors within `reach` already hold that successor. Toroidal by definition.
"""

from __future__ import annotations

import dataclasses

import numpy as np
from numpy.typing import NDArray

from heaton_life.core.params import Params
from heaton_life.core.rng import Pcg32


@dataclasses.dataclass(frozen=True)
class CyclicParams(Params):
    states: int = dataclasses.field(default=14, metadata={"min": 2, "max": 24})
    threshold: int = dataclasses.field(default=1, metadata={"min": 1, "max": 48})
    reach: int = dataclasses.field(default=1, metadata={"min": 1, "max": 3, "label": "Range"})
    neighborhood: str = dataclasses.field(
        default="moore", metadata={"choices": ["moore", "vonneumann"]}
    )
    width: int = dataclasses.field(default=256, metadata={"min": 8, "max": 2048})
    height: int = dataclasses.field(default=256, metadata={"min": 8, "max": 2048})
    init: str = dataclasses.field(default="soup", metadata={"choices": ["soup"]})
    seed: int = dataclasses.field(
        default=0, metadata={"min": 0, "max": 4294967295, "role": "seed"}
    )


def _offsets(reach: int, neighborhood: str) -> list[tuple[int, int]]:
    out = []
    for dy in range(-reach, reach + 1):
        for dx in range(-reach, reach + 1):
            if (dy, dx) == (0, 0):
                continue
            if neighborhood == "vonneumann" and abs(dy) + abs(dx) > reach:
                continue
            out.append((dy, dx))
    return out


class Cyclic:
    """A cyclic CA. State is uint8 in [0, states), shape (height, width), torus."""

    def __init__(
        self,
        states: int = 14,
        *,
        size: tuple[int, int] = (256, 256),
        threshold: int = 1,
        reach: int = 1,
        neighborhood: str = "moore",
        init: str | NDArray[np.uint8] = "soup",
        seed: int = 0,
    ) -> None:
        if neighborhood not in ("moore", "vonneumann"):
            raise ValueError(f"unknown neighborhood: {neighborhood!r}")
        width, height = size
        self._initial: NDArray[np.uint8] | None = None
        if isinstance(init, np.ndarray):
            if init.shape != (height, width):
                raise ValueError(
                    f"init array shape {init.shape} does not match (h={height}, w={width})"
                )
            if init.max(initial=0) >= states:
                raise ValueError("init array has values >= states")
            self._initial = init.astype(np.uint8)
            init_name = "array"
        else:
            init_name = init
        self.params = CyclicParams(
            states=states,
            threshold=threshold,
            reach=reach,
            neighborhood=neighborhood,
            width=width,
            height=height,
            init=init_name,
            seed=seed,
        )
        self._generation = 0
        self._state: NDArray[np.uint8]
        self.reset()

    @classmethod
    def from_params(cls, params: CyclicParams) -> Cyclic:
        if params.init == "array":
            raise ValueError("params with init='array' need the array: Cyclic(init=...)")
        return cls(
            params.states,
            size=(params.width, params.height),
            threshold=params.threshold,
            reach=params.reach,
            neighborhood=params.neighborhood,
            init=params.init,
            seed=params.seed,
        )

    def reset(self, seed: int | None = None) -> None:
        if seed is not None:
            self.params = self.params.replace(seed=seed)
        p = self.params
        if p.init == "array":
            assert self._initial is not None
            self._state = self._initial.copy()
        elif p.init == "soup":
            draws = Pcg32(p.seed).fill_u32(p.width * p.height).reshape(p.height, p.width)
            self._state = (draws % np.uint32(p.states)).astype(np.uint8)
        else:
            raise ValueError(f"unknown init strategy: {p.init!r}")
        self._generation = 0

    def step(self, n: int = 1) -> None:
        p = self.params
        offsets = _offsets(p.reach, p.neighborhood)
        for _ in range(n):
            state = self._state
            succ = ((state.astype(np.uint16) + 1) % p.states).astype(np.uint8)
            count = np.zeros(state.shape, dtype=np.uint8)
            for dy, dx in offsets:
                count += np.roll(state, (dy, dx), axis=(0, 1)) == succ
            self._state = np.where(count >= p.threshold, succ, state)
        self._generation += n

    @property
    def state(self) -> NDArray[np.uint8]:
        return self._state

    @property
    def generation(self) -> int:
        return self._generation

    def frame(self) -> NDArray[np.uint8]:
        span = max(self.params.states - 1, 1)
        return (self._state.astype(np.uint16) * 255 // span).astype(np.uint8)
