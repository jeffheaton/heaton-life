"""Wireworld (Silverman) — spec/wireworld.md.

States: 0 empty, 1 electron head, 2 electron tail, 3 conductor.
head -> tail; tail -> conductor; conductor -> head iff exactly 1 or 2 Moore
neighbors are heads; empty stays empty. Default boundary is dead (circuits
rarely want a torus); every topology of spec/topology.md is allowed.
"""

from __future__ import annotations

import dataclasses
import operator
from typing import cast

import numpy as np
from numpy.typing import NDArray

from heaton_life.ca._advance import AdvanceRegion
from heaton_life.core.neighbors import moore_sum
from heaton_life.core.params import Params
from heaton_life.core.topology import AXES, BOUNDARIES, Axis, Boundary, Halo, Topology
from heaton_life.init.patterns import clear

EMPTY, HEAD, TAIL, CONDUCTOR = 0, 1, 2, 3

_CHARS = {".": EMPTY, "H": HEAD, "T": TAIL, "#": CONDUCTOR}


def wireworld_from_text(text: str) -> NDArray[np.uint8]:
    """Parse ASCII art: '.' empty, 'H' head, 'T' tail, '#' conductor."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("empty wireworld pattern")
    width = max(len(line) for line in lines)
    grid = np.zeros((len(lines), width), dtype=np.uint8)
    for y, line in enumerate(lines):
        for x, ch in enumerate(line):
            if ch == " ":
                continue
            if ch not in _CHARS:
                raise ValueError(f"unknown wireworld character {ch!r} at row {y}")
            grid[y, x] = _CHARS[ch]
    return grid


def clock_loop(size: tuple[int, int], *, margin: int = 2) -> NDArray[np.uint8]:
    """A rectangular conductor loop with one circulating electron (period = perimeter)."""
    width, height = size
    if width < 2 * margin + 4 or height < 2 * margin + 4:
        raise ValueError(f"grid {width}x{height} too small for a clock loop")
    grid = np.zeros((height, width), dtype=np.uint8)
    top, bottom = margin, height - 1 - margin
    left, right = margin, width - 1 - margin
    grid[top, left : right + 1] = CONDUCTOR
    grid[bottom, left : right + 1] = CONDUCTOR
    grid[top : bottom + 1, left] = CONDUCTOR
    grid[top : bottom + 1, right] = CONDUCTOR
    grid[top, left + 1] = TAIL
    grid[top, left + 2] = HEAD
    return grid


@dataclasses.dataclass(frozen=True)
class WireworldParams(Params):
    width: int = dataclasses.field(default=64, metadata={"min": 8, "max": 2048})
    height: int = dataclasses.field(default=64, metadata={"min": 8, "max": 2048})
    init: str = dataclasses.field(default="clock", metadata={"choices": ["clock"]})
    # The topology (spec/topology.md): a shift and an axis matter for a torus or a Klein bottle.
    boundary: str = dataclasses.field(
        default="dead", metadata={"choices": ["dead", *(b for b in BOUNDARIES if b != "dead")]}
    )
    shift: int = dataclasses.field(default=0, metadata={"min": -2048, "max": 2048})
    axis: str = dataclasses.field(default="x", metadata={"choices": list(AXES)})


class Wireworld(AdvanceRegion):
    """Wireworld. State is uint8 in {0,1,2,3}, shape (height, width)."""

    def __init__(
        self,
        *,
        size: tuple[int, int] = (64, 64),
        init: str | NDArray[np.uint8] = "clock",
        boundary: Boundary = "dead",
        shift: int = 0,
        axis: Axis = "x",
    ) -> None:
        width, height = size
        self._initial: NDArray[np.uint8] | None = None
        if isinstance(init, np.ndarray):
            if init.shape != (height, width):
                raise ValueError(
                    f"init array shape {init.shape} does not match (h={height}, w={width})"
                )
            if init.max(initial=0) > CONDUCTOR:
                raise ValueError("wireworld init array has values > 3")
            self._initial = init.astype(np.uint8)
            init_name = "array"
        else:
            init_name = init
        topology = Topology(boundary, shift, axis)
        # The cells past the edges, filled each generation (spec/topology.md "The halo").
        self._halo = Halo(topology, width, height)
        self.params = WireworldParams(
            width=width,
            height=height,
            init=init_name,
            boundary=topology.boundary,
            shift=topology.shift,
            axis=topology.axis,
        )
        self._generation = 0
        self._state: NDArray[np.uint8]
        self.reset()

    @classmethod
    def from_params(cls, params: WireworldParams) -> Wireworld:
        if params.init == "array":
            raise ValueError("params with init='array' need the array: Wireworld(init=...)")
        return cls(
            size=(params.width, params.height),
            init=params.init,
            boundary=cast(Boundary, params.boundary),
            shift=params.shift,
            axis=cast(Axis, params.axis),
        )

    def reset(self, seed: int | None = None) -> None:
        p = self.params
        if p.init == "array":
            assert self._initial is not None
            self._state = self._initial.copy()
        elif p.init == "clock":
            self._state = clock_loop((p.width, p.height))
        else:
            raise ValueError(f"unknown init strategy: {p.init!r}")
        self._generation = 0

    def set_state(
        self, state: NDArray[np.generic], generation: int = 0, *, keep_start: bool = False
    ) -> None:
        """Replace the state (values 0 to 3) and set the generation (spec/README.md "A
        world's state and its start"). The state also becomes the start ``reset()`` returns
        to (``init`` ``array``), unless ``keep_start``: then the start stays as it was, and
        no copy of the state is kept for it."""
        p = self.params
        cells = np.asarray(state)
        if cells.shape != (p.height, p.width):
            raise ValueError(
                f"state shape {cells.shape} does not match (h={p.height}, w={p.width})"
            )
        if cells.max(initial=0) > CONDUCTOR:
            raise ValueError("wireworld state has values > 3")
        cells = cells.astype(np.uint8)
        generation = operator.index(generation)
        if not keep_start:
            self._initial = cells.copy()
            self.params = p.replace(init="array")
        self._state = cells
        self._generation = generation

    def step(self, n: int = 1) -> None:
        halo = self._halo
        for _ in range(n):
            state = self._state
            heads = (state == HEAD).astype(np.uint8)
            head_count = moore_sum(heads, halo=halo)
            new = state.copy()
            new[state == HEAD] = TAIL
            new[state == TAIL] = CONDUCTOR
            fires = (state == CONDUCTOR) & ((head_count == 1) | (head_count == 2))
            new[fires] = HEAD
            self._state = new
        self._generation += n

    @property
    def state(self) -> NDArray[np.uint8]:
        return self._state

    @property
    def topology(self) -> Topology:
        """How the grid's edges join (spec/topology.md)."""
        return self._halo.topology

    @property
    def generation(self) -> int:
        return self._generation

    def clear_rect(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """spec/patterns.md "Clear": inclusive rectangle to this family's blank.

        Wireworld's blank is Empty (0). The generation is untouched, exactly like stamping. The C# port has
        carried this per family as ``ClearRect`` all along; the Python library had
        no equivalent at all, even though the spec lists Clear alongside Extract
        and Stamp as normative.
        """
        clear(self._state, x0, y0, x1, y1, 0)

    def frame(self) -> NDArray[np.uint8]:
        return self._state * np.uint8(85)  # 0/85/170/255 -> exact colormap anchors
