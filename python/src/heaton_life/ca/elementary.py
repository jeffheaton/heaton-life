"""Elementary (Wolfram) cellular automata — spec/elementary.md.

State is the 1-D tape; the frame is the scrolling space-time diagram, which is
the canonical way to *look* at these — a clean example of state != frame.
"""

from __future__ import annotations

import dataclasses

import numpy as np
from numpy.typing import NDArray

from heaton_life.core.params import Params
from heaton_life.init import soup


@dataclasses.dataclass(frozen=True)
class ElementaryParams(Params):
    rule: int = dataclasses.field(default=30, metadata={"min": 0, "max": 255})
    width: int = dataclasses.field(default=256, metadata={"min": 8, "max": 4096})
    height: int = dataclasses.field(
        default=256, metadata={"min": 8, "max": 4096, "label": "Diagram Rows"}
    )
    init: str = dataclasses.field(default="single", metadata={"choices": ["single", "soup"]})
    density: float = dataclasses.field(
        default=0.5, metadata={"min": 0.0, "max": 1.0, "step": 0.01}
    )
    seed: int = dataclasses.field(
        default=0, metadata={"min": 0, "max": 4294967295, "role": "seed"}
    )
    boundary: str = dataclasses.field(default="torus", metadata={"choices": ["torus", "dead"]})


class Elementary:
    """An elementary CA. State is the uint8 0/1 tape, shape (width,)."""

    def __init__(
        self,
        rule: int = 30,
        *,
        size: tuple[int, int] = (256, 256),
        init: str | NDArray[np.uint8] = "single",
        density: float = 0.5,
        seed: int = 0,
        boundary: str = "torus",
    ) -> None:
        if not 0 <= rule <= 255:
            raise ValueError(f"rule must be 0..255, got {rule}")
        width, height = size
        self._initial: NDArray[np.uint8] | None = None
        if isinstance(init, np.ndarray):
            if init.shape != (width,):
                raise ValueError(f"init tape shape {init.shape} does not match (width={width},)")
            self._initial = (init > 0).astype(np.uint8)
            init_name = "array"
        else:
            init_name = init
        self.params = ElementaryParams(
            rule=rule,
            width=width,
            height=height,
            init=init_name,
            density=density,
            seed=seed,
            boundary=boundary,
        )
        # Rule table indexed by (left<<2 | center<<1 | right).
        self._table = np.array([(rule >> i) & 1 for i in range(8)], dtype=np.uint8)
        self._generation = 0
        self._tape: NDArray[np.uint8]
        self._diagram: NDArray[np.uint8]
        self.reset()

    @classmethod
    def from_params(cls, params: ElementaryParams) -> Elementary:
        if params.init == "array":
            raise ValueError("params with init='array' need the tape: Elementary(init=...)")
        return cls(
            params.rule,
            size=(params.width, params.height),
            init=params.init,
            density=params.density,
            seed=params.seed,
            boundary=params.boundary,
        )

    def reset(self, seed: int | None = None) -> None:
        if seed is not None:
            self.params = self.params.replace(seed=seed)
        p = self.params
        if p.init == "array":
            assert self._initial is not None
            tape = self._initial.copy()
        elif p.init == "single":
            tape = np.zeros(p.width, dtype=np.uint8)
            tape[p.width // 2] = 1
        elif p.init == "soup":
            tape = soup((p.width, 1), density=p.density, seed=p.seed)[0]
        else:
            raise ValueError(f"unknown init strategy: {p.init!r}")
        self._tape = tape
        self._diagram = np.zeros((p.height, p.width), dtype=np.uint8)
        self._diagram[0] = tape
        self._generation = 0

    def step(self, n: int = 1) -> None:
        p = self.params
        for _ in range(n):
            tape = self._tape
            if p.boundary == "torus":
                left = np.roll(tape, 1)
                right = np.roll(tape, -1)
            else:  # dead
                left = np.zeros_like(tape)
                left[1:] = tape[:-1]
                right = np.zeros_like(tape)
                right[:-1] = tape[1:]
            index = (left << 2) | (tape << 1) | right
            self._tape = self._table[index]
            self._generation += 1
            row = self._generation
            if row < p.height:
                self._diagram[row] = self._tape
            else:  # scroll up
                self._diagram[:-1] = self._diagram[1:]
                self._diagram[-1] = self._tape

    @property
    def state(self) -> NDArray[np.uint8]:
        return self._tape

    @property
    def generation(self) -> int:
        return self._generation

    def frame(self) -> NDArray[np.uint8]:
        return self._diagram * np.uint8(255)
