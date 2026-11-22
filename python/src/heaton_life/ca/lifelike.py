"""Life-like cellular automata (spec/lifelike.md): binary state, any rule of spec/rules.md,
and the seven states of a History rule (spec/history.md)."""

from __future__ import annotations

import dataclasses
import operator
from typing import cast

import numpy as np
from numpy.typing import NDArray

from heaton_life.ca import history
from heaton_life.ca._advance import AdvanceRegion
from heaton_life.ca.rulestring import LifeRule, compile_rule
from heaton_life.core.neighbors import moore_index
from heaton_life.core.params import Params
from heaton_life.core.topology import AXES, BOUNDARIES, Axis, Boundary, Halo, Topology
from heaton_life.init import blob, single, soup
from heaton_life.init.patterns import clear, fill_random


@dataclasses.dataclass(frozen=True)
class LifeLikeParams(Params):
    # Field metadata documents the spec'd ranges/choices; UIs build forms from it.
    rule: str = dataclasses.field(default="B3/S23", metadata={"label": "Rule (B/S)"})
    width: int = dataclasses.field(default=256, metadata={"min": 8, "max": 2048})
    height: int = dataclasses.field(default=256, metadata={"min": 8, "max": 2048})
    init: str = dataclasses.field(default="soup", metadata={"choices": ["soup", "blob", "single"]})
    density: float = dataclasses.field(
        default=0.35, metadata={"min": 0.0, "max": 1.0, "step": 0.01}
    )
    seed: int = dataclasses.field(default=0, metadata={"min": 0, "max": 4294967295, "role": "seed"})
    # The topology (spec/topology.md): a shift and an axis matter for a torus or a Klein bottle.
    boundary: str = dataclasses.field(default="torus", metadata={"choices": list(BOUNDARIES)})
    shift: int = dataclasses.field(default=0, metadata={"min": -2048, "max": 2048})
    axis: str = dataclasses.field(default="x", metadata={"choices": list(AXES)})


class LifeLike(AdvanceRegion):
    """A Life-like CA. State is uint8 0/1, shape (height, width), row-major; under a History
    rule (``B3/S23History``) a cell is any of the seven states 0–6 (spec/history.md)."""

    def __init__(
        self,
        rule: str = "B3/S23",
        *,
        size: tuple[int, int] = (256, 256),
        init: str | NDArray[np.uint8] = "soup",
        density: float = 0.35,
        seed: int = 0,
        boundary: Boundary = "torus",
        shift: int = 0,
        axis: Axis = "x",
    ) -> None:
        width, height = size
        compiled = compile_rule(rule, variants=True)
        self._rule = compiled
        self._initial: NDArray[np.uint8] | None = None
        if isinstance(init, np.ndarray):
            if init.shape != (height, width):
                raise ValueError(
                    f"init array shape {init.shape} does not match size (h={height}, w={width})"
                )
            self._initial = self._cells(init)
            init_name = "array"
        else:
            init_name = init
        topology = Topology(boundary, shift, axis)
        # The cells past the edges, filled each generation (spec/topology.md "The halo").
        self._halo = Halo(topology, width, height)
        self.params = LifeLikeParams(
            rule=compiled.canonical,
            width=width,
            height=height,
            init=init_name,
            density=density,
            seed=seed,
            boundary=topology.boundary,
            shift=topology.shift,
            axis=topology.axis,
        )
        # The rule's transition table, indexed by each cell's 3×3 neighborhood (spec/rules.md).
        self._table = np.frombuffer(compiled.table, dtype=np.uint8)
        self._generation = 0
        self._state: NDArray[np.uint8]
        self.reset()

    @classmethod
    def from_params(cls, params: LifeLikeParams) -> LifeLike:
        if params.init == "array":
            raise ValueError(
                "params with init='array' cannot be reconstructed; pass the array to LifeLike(init=...)"
            )
        return cls(
            params.rule,
            size=(params.width, params.height),
            init=params.init,
            density=params.density,
            seed=params.seed,
            boundary=cast(Boundary, params.boundary),
            shift=params.shift,
            axis=cast(Axis, params.axis),
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

    def set_state(
        self, state: NDArray[np.generic], generation: int = 0, *, keep_start: bool = False
    ) -> None:
        """Replace the state, nonzero cells alive (History's states 0–6 kept as they are,
        under a History rule), and set the generation (spec/README.md "A world's state and
        its start"). The state also becomes the start ``reset()``
        returns to (``init`` ``array``), unless ``keep_start``: then the start stays as it
        was, and no copy of the state is kept for it."""
        p = self.params
        cells = np.asarray(state)
        if cells.shape != (p.height, p.width):
            raise ValueError(
                f"state shape {cells.shape} does not match (h={p.height}, w={p.width})"
            )
        cells = self._cells(cells)
        generation = operator.index(generation)
        if not keep_start:
            self._initial = cells.copy()
            self.params = p.replace(init="array")
        self._state = cells
        self._generation = generation

    def _cells(self, cells: NDArray[np.generic]) -> NDArray[np.uint8]:
        """Cells as this world's states: nonzero alive under a two-state rule, and History's
        states 0–6 under a History rule (anything else an error)."""
        if self._rule.variant:
            return history.check_cells(cells)
        return (np.asarray(cells) > 0).astype(np.uint8)

    def step(self, n: int = 1) -> None:
        halo = self._halo
        if self._rule.variant:
            for _ in range(n):
                self._state = history.step(self._state, halo, self._rule)
        else:
            for _ in range(n):
                self._state = self._table[moore_index(self._state, halo=halo)]
        self._generation += n

    @property
    def rule(self) -> LifeRule:
        """The compiled rule: its canonical string, table, variant and number of states."""
        return self._rule

    @property
    def states(self) -> int:
        """The number of states a cell can have: 2, or 7 under a History rule."""
        return self._rule.states

    @property
    def topology(self) -> Topology:
        """How the grid's edges join (spec/topology.md)."""
        return self._halo.topology

    @property
    def state(self) -> NDArray[np.uint8]:
        return self._state

    @property
    def generation(self) -> int:
        return self._generation

    def clear_rect(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """spec/patterns.md "Clear": inclusive rectangle to this family's blank.

        LifeLike's blank is 0 (dead). The generation is untouched, exactly like stamping. The C# port has
        carried this per family as ``ClearRect`` all along; the Python library had
        no equivalent at all, even though the spec lists Clear alongside Extract
        and Stamp as normative.
        """
        clear(self._state, x0, y0, x1, y1, 0)

    def fill_random(self, x0: int, y0: int, x1: int, y1: int, density: float, seed: int) -> None:
        """spec/patterns.md "Random fill": the region (x0, y0)..(x1, y1), inclusive, becomes
        the soup of a world its size (PCG32 stream 0, row-major draws, alive iff
        ``draw < floor(density * 2**32)``), the same cells HashLife's ``fill_random`` gives
        a rectangle of that size and seed. The generation is untouched."""
        fill_random(self._state, x0, y0, x1, y1, density=density, seed=seed)

    def frame(self) -> NDArray[np.uint8]:
        """spec/render.md: ``state * 255``, and under a History rule the state itself (0–6),
        for a color per state (History's palette, spec/render.md "State palettes")."""
        if self._rule.variant:
            return self._state.copy()
        return self._state * np.uint8(255)
