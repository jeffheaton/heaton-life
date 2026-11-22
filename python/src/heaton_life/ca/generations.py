"""Generations (spec/generations.md): Life-like birth and survival, with dying states.

A cell is dead (0), alive (1), or dying (2 to C − 1). Births and survival come from a
Life-like rule (spec/rules.md) evaluated on the live cells only, so a dying cell counts as
a dead neighbor; a live cell that doesn't survive starts dying, and a dying cell moves one
state on each generation until C − 1 gives way to 0. A rule is written ``B…/S…/C…`` or in
survival/birth/count order (``345/2/4``); its canonical form is ``B2/S345/C4``.
"""

from __future__ import annotations

import dataclasses
import functools
import operator
from typing import cast

import numpy as np
from numpy.typing import NDArray

from heaton_life.ca._advance import AdvanceRegion
from heaton_life.ca.rulestring import _SPACE, LifeRule, compile_rule, try_compile_rule
from heaton_life.ca.state_rules import StateRule
from heaton_life.core.neighbors import moore_index
from heaton_life.core.params import Params
from heaton_life.core.topology import AXES, BOUNDARIES, Axis, Boundary, Halo, Topology
from heaton_life.init import blob, single, soup
from heaton_life.init.patterns import clear, fill_random

MIN_STATES = 2
MAX_STATES = 256
_SURVIVAL_BIRTH = frozenset("012345678")


@dataclasses.dataclass(frozen=True)
class GenerationsRule(StateRule):
    """A Generations rule compiled (spec/generations.md "Rules"): its canonical text, its C
    states, and the Life-like rule whose table gives births and survival. It is also the
    cell function the multi-state HashLife runs (spec/hashlife-multistate.md)."""

    canonical: str
    states: int
    life: LifeRule

    @property
    def has_b0(self) -> bool:
        """True when a dead cell with no live neighbors is born."""
        return self.life.has_b0

    def next_state(
        self, nw: int, n: int, ne: int, w: int, c: int, e: int, sw: int, s: int, se: int
    ) -> int:
        if c >= 2:  # dying: one state on, C − 1 to 0
            return c + 1 if c + 1 < self.states else 0
        index = (
            (nw == 1) << 8
            | (n == 1) << 7
            | (ne == 1) << 6
            | (w == 1) << 5
            | c << 4
            | (e == 1) << 3
            | (sw == 1) << 2
            | (s == 1) << 1
            | (se == 1)
        )
        if self.life.table[index]:
            return 1
        return 0 if c == 0 else 2 % self.states


class _GenerationsError(ValueError):
    """Text that is no Generations rule, with the reason spec/generations.md gives for it."""

    def __init__(self, text: str, reason: str) -> None:
        super().__init__(f"invalid Generations rule '{text}': {reason} (spec/generations.md)")
        self.reason = reason


def compile_generations_rule(text: str) -> GenerationsRule:
    """Compile Generations rule text (spec/generations.md "Rules"): ``B…/S…/C…`` with any
    Life-like rule of spec/rules.md before the count, or survival/birth/count digits
    (``345/2/4``). Raises ValueError, its message carrying the reason, for anything else."""
    if not isinstance(text, str):
        raise TypeError(f"a rule is text, not {type(text).__name__}")
    return _compile(text)


def try_compile_generations_rule(text: str) -> tuple[GenerationsRule, None] | tuple[None, str]:
    """``compile_generations_rule`` without raising: ``(rule, None)``, or ``(None, reason)``
    with the reason spec/generations.md "Reasons" gives for the first problem found."""
    try:
        return compile_generations_rule(text), None
    except _GenerationsError as error:
        return None, error.reason


def _states(text: str, digits: str) -> int:
    significant = digits.lstrip("0")
    if len(significant) > 3 or not MIN_STATES <= int(digits) <= MAX_STATES:
        raise _GenerationsError(text, f"a Generations rule has {MIN_STATES} to {MAX_STATES} states")
    return int(digits)


@functools.lru_cache(maxsize=64)
def _compile(text: str) -> GenerationsRule:
    start, end = 0, len(text)
    while start < end and text[start] in _SPACE:
        start += 1
    while end > start and text[end - 1] in _SPACE:
        end -= 1
    body = text[start:end]
    parts = body.split("/")
    if (
        len(parts) == 3
        and set(parts[0] + parts[1]) <= _SURVIVAL_BIRTH
        and parts[2].isascii()
        and parts[2].isdigit()
    ):
        survival, birth, count = parts
        life = compile_rule(
            f"B{''.join(sorted(set(birth)))}/S{''.join(sorted(set(survival)))}", presets=False
        )
        states = _states(text, count)
        return GenerationsRule(f"{life.canonical}/C{states}", states, life)
    slash = body.rfind("/")
    tail = body[slash + 1 :] if slash >= 0 else ""
    at = 0
    while at < len(tail) and tail[at] in _SPACE:
        at += 1
    tail = tail[at:]
    digits = tail[1:]
    if slash < 0 or tail[:1] not in ("C", "c") or not (digits.isascii() and digits.isdigit()):
        raise _GenerationsError(text, "expected '/C' and the number of states at the end")
    compiled, reason = try_compile_rule(body[:slash], presets=False)
    if compiled is None:
        assert reason is not None
        raise _GenerationsError(text, reason)
    states = _states(text, digits)
    return GenerationsRule(f"{compiled.canonical}/C{states}", states, compiled)


@dataclasses.dataclass(frozen=True)
class GenerationsParams(Params):
    # Field metadata documents the spec'd ranges/choices; UIs build forms from it.
    rule: str = dataclasses.field(default="B2/S/C3", metadata={"label": "Rule (B/S/C)"})
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


class Generations(AdvanceRegion):
    """A Generations CA. State is uint8 0..C − 1, shape (height, width), row-major: 0 dead,
    1 alive, 2..C − 1 dying."""

    def __init__(
        self,
        rule: str = "B2/S/C3",
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
        compiled = compile_generations_rule(rule)
        self._rule = compiled
        self._initial: NDArray[np.uint8] | None = None
        if isinstance(init, np.ndarray):
            if init.shape != (height, width):
                raise ValueError(
                    f"init array shape {init.shape} does not match size (h={height}, w={width})"
                )
            self._initial = self._checked(init)
            init_name = "array"
        else:
            init_name = init
        topology = Topology(boundary, shift, axis)
        # The cells past the edges, filled each generation (spec/topology.md "The halo").
        self._halo = Halo(topology, width, height)
        self.params = GenerationsParams(
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
        # Births and survival by each cell's 3×3 neighborhood of live cells (spec/rules.md).
        self._table = np.frombuffer(compiled.life.table, dtype=np.uint8)
        self._generation = 0
        self._state: NDArray[np.uint8]
        self.reset()

    @classmethod
    def from_params(cls, params: GenerationsParams) -> Generations:
        if params.init == "array":
            raise ValueError(
                "params with init='array' cannot be reconstructed; pass the array to "
                "Generations(init=...)"
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

    @property
    def rule(self) -> GenerationsRule:
        """The compiled rule: its canonical text, C states, and births and survival."""
        return self._rule

    @property
    def states(self) -> int:
        """C: every cell is a state from 0 to C − 1."""
        return self._rule.states

    def _checked(self, cells: NDArray[np.generic]) -> NDArray[np.uint8]:
        array = np.asarray(cells)
        if array.size and (int(array.min()) < 0 or int(array.max()) >= self._rule.states):
            raise ValueError(
                f"a Generations state is 0 to {self._rule.states - 1} under {self._rule.canonical}"
            )
        return array.astype(np.uint8)

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
        """Replace the state (values 0 to C − 1) and set the generation (spec/README.md "A
        world's state and its start"). The state also becomes the start ``reset()`` returns
        to (``init`` ``array``), unless ``keep_start``: then the start stays as it was, and
        no copy of the state is kept for it."""
        p = self.params
        cells = np.asarray(state)
        if cells.shape != (p.height, p.width):
            raise ValueError(
                f"state shape {cells.shape} does not match (h={p.height}, w={p.width})"
            )
        cells = self._checked(cells)
        generation = operator.index(generation)
        if not keep_start:
            self._initial = cells.copy()
            self.params = p.replace(init="array")
        self._state = cells
        self._generation = generation

    def step(self, n: int = 1) -> None:
        halo = self._halo
        count = self._rule.states
        for _ in range(n):
            state = self._state
            alive = (state == 1).astype(np.uint8)
            verdict = self._table[moore_index(alive, halo=halo)]
            # Dying and refused cells move one state on; C − 1 wraps to 0 (spec/generations.md).
            nxt = ((state.astype(np.uint16) + 1) % count).astype(np.uint8)
            dead = state == 0
            nxt[dead] = verdict[dead]
            nxt[(state == 1) & (verdict == 1)] = 1
            self._state = nxt
        self._generation += n

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
        """spec/patterns.md "Clear": the inclusive rectangle to this family's blank, 0 (dead).
        The generation is untouched."""
        clear(self._state, x0, y0, x1, y1, 0)

    def fill_random(self, x0: int, y0: int, x1: int, y1: int, density: float, seed: int) -> None:
        """spec/patterns.md "Random fill": the region becomes the soup of a world its size,
        each live cell state 1 (alive), every other cell 0: the cells a life-like grid's
        fill gives. The generation is untouched."""
        fill_random(self._state, x0, y0, x1, y1, density=density, seed=seed)

    def frame(self) -> NDArray[np.uint8]:
        """spec/render.md "Frames": 0 for a dead cell, ⌊255 · (C − s) / (C − 1)⌋ for state
        s ≥ 1, so a live cell is 255 and a dying one fades: through ``fire``, the colors of
        Generations' state palette (spec/render.md "State palettes")."""
        count = self._rule.states
        state = self._state.astype(np.int32)
        fade = (count - state) * 255 // (count - 1)
        return np.where(state == 0, 0, fade).astype(np.uint8)
