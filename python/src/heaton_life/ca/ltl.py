"""Larger than Life (spec/ltl.md): Life over a neighborhood of range r, a box, a diamond or
a circle, with birth and survival as ranges of counts and, beyond two states, dying states
that decay as Generations rules do. Bounded grids only, on any topology of
spec/topology.md, read through the halo of radius r."""

from __future__ import annotations

import dataclasses
import functools
import math
import operator
from typing import Final, Literal, TypeAlias, cast

import numpy as np
from numpy.typing import NDArray

from heaton_life.ca._advance import AdvanceRegion
from heaton_life.ca.rulestring import _SPACE
from heaton_life.core.params import Params
from heaton_life.core.topology import AXES, BOUNDARIES, Axis, Boundary, Halo, Topology
from heaton_life.init import blob, single, soup
from heaton_life.init.patterns import clear, fill_random

LtlNeighborhood: TypeAlias = Literal["moore", "vonneumann", "circular"]

MAX_RANGE: Final = 500
MAX_STATES: Final = 256
MAX_COUNT: Final = (2 * MAX_RANGE + 1) ** 2
"""The most cells a neighborhood holds (the box at range 500), and so the largest count a
rule may name."""

BOSCO: Final = "R5,C0,M1,S34..58,B34..45,NM"
"""Bosco's Rule, the classic Larger than Life rule."""

_HOODS: Final[dict[str, LtlNeighborhood]] = {"M": "moore", "N": "vonneumann", "C": "circular"}
_LETTERS: Final[dict[LtlNeighborhood, str]] = {hood: letter for letter, hood in _HOODS.items()}
_DIGITS: Final = frozenset("0123456789")


class LtlRuleError(ValueError):
    """Text that is no Larger than Life rule, with the reason spec/ltl.md gives for it."""

    def __init__(self, text: str, reason: str) -> None:
        super().__init__(f"invalid Larger than Life rule '{text}': {reason} (spec/ltl.md)")
        self.reason = reason


@functools.lru_cache(maxsize=64)
def half_widths(radius: int, neighborhood: LtlNeighborhood) -> tuple[int, ...]:
    """``w(dy)`` for ``dy`` from ``-radius`` to ``radius`` (spec/ltl.md "Neighborhoods"): row
    ``dy`` of the neighborhood holds the offsets ``|dx| ≤ w(dy)``."""
    if neighborhood == "moore":
        return tuple(radius for _ in range(-radius, radius + 1))
    if neighborhood == "vonneumann":
        return tuple(radius - abs(dy) for dy in range(-radius, radius + 1))
    reach = radius * radius + radius  # the circle: dx² + dy² ≤ r² + r
    return tuple(math.isqrt(reach - dy * dy) for dy in range(-radius, radius + 1))


@dataclasses.dataclass(frozen=True)
class LtlRule:
    """A Larger than Life rule (spec/ltl.md "The rule"). ``states`` is 2 to 256; ``survival``
    and ``birth`` are inclusive ``(min, max)`` ranges of counts."""

    range: int
    states: int
    middle: bool
    survival: tuple[int, int]
    birth: tuple[int, int]
    neighborhood: LtlNeighborhood

    @property
    def canonical(self) -> str:
        """``R<r>,C<c>,M<m>,S<min>..<max>,B<min>..<max>,N<M|N|C>``, ``c`` 0 for two states."""
        states = 0 if self.states == 2 else self.states
        (smin, smax), (bmin, bmax) = self.survival, self.birth
        return (
            f"R{self.range},C{states},M{int(self.middle)},S{smin}..{smax},B{bmin}..{bmax},"
            f"N{_LETTERS[self.neighborhood]}"
        )

    @property
    def half_widths(self) -> tuple[int, ...]:
        return half_widths(self.range, self.neighborhood)

    @property
    def size(self) -> int:
        """The cells of the neighborhood, the cell itself included (spec/ltl.md)."""
        return sum(2 * w + 1 for w in self.half_widths)

    def __str__(self) -> str:
        return self.canonical


def parse_ltl_rule(text: str) -> LtlRule:
    """The rule a text names, in either form of spec/ltl.md ("Rule text"). Raises
    ``LtlRuleError`` (a ValueError) with the reason for the first problem found."""
    if not isinstance(text, str):
        raise TypeError(f"a rule is text, not {type(text).__name__}")
    return _parse(text)


def try_parse_ltl_rule(text: str) -> tuple[LtlRule, None] | tuple[None, str]:
    """``parse_ltl_rule`` without raising: ``(rule, None)``, or ``(None, reason)``."""
    try:
        return _parse(text), None
    except LtlRuleError as error:
        return None, error.reason


def ltl_refusal(text: str) -> str | None:
    """Why the unbounded universe refuses ``text`` (spec/ltl.md "Topologies"): a message when
    it names a Larger than Life rule, or None when it doesn't."""
    rule, _ = try_parse_ltl_rule(text) if isinstance(text, str) else (None, None)
    if rule is None:
        return None
    return (
        f"{rule.canonical} is a Larger than Life rule: it runs on a bounded grid, never on "
        "the unbounded plane (spec/ltl.md)"
    )


def _trimmed(text: str) -> str:
    start, end = 0, len(text)
    while start < end and text[start] in _SPACE:
        start += 1
    while end > start and text[end - 1] in _SPACE:
        end -= 1
    return text[start:end]


@dataclasses.dataclass(frozen=True)
class _Number:
    value: int
    """The number, any past 10⁹ as 10⁹ + 1 (past every limit)."""
    text: str
    """Its digits without leading zeros, for reasons."""


def _number(digits: str) -> _Number | None:
    if not digits or not set(digits) <= _DIGITS:
        return None
    text = digits.lstrip("0") or "0"
    return _Number(10**9 + 1 if len(text) > 9 else int(text), text)


def _lettered(field: str, letter: str) -> _Number | None:
    """A field that is ``letter`` (either case) and a number."""
    if len(field) < 2 or field[0] not in (letter, letter.lower()):
        return None
    return _number(field[1:])


def _span(field: str, letter: str) -> tuple[_Number, _Number] | None:
    """A field that is ``letter`` (either case), a number, ``..`` and a number."""
    if len(field) < 2 or field[0] not in (letter, letter.lower()):
        return None
    low, dots, high = field[1:].partition("..")
    if not dots:
        return None
    first, second = _number(low), _number(high)
    return None if first is None or second is None else (first, second)


def _parse(text: str) -> LtlRule:
    body = _trimmed(text)
    if not body or not (body[0] in "Rr" or body[0] in _DIGITS):
        raise LtlRuleError(text, "expected R…,C…,M…,S…,B…,N… or five numbers r,bmin,bmax,smin,smax")
    fields = body.split(",")
    if body[0] in "Rr":
        if not 5 <= len(fields) <= 6:
            raise LtlRuleError(text, "expected the fields R, C, M, S, B and N, in that order")
        radius = _lettered(fields[0], "R")
        if radius is None:
            raise LtlRuleError(text, f"expected R and the range, not '{fields[0]}'")
        count = _lettered(fields[1], "C")
        if count is None:
            raise LtlRuleError(text, f"expected C and the number of states, not '{fields[1]}'")
        if fields[2] not in ("M0", "M1", "m0", "m1"):
            raise LtlRuleError(text, f"expected M0 or M1, not '{fields[2]}'")
        middle = fields[2][1] == "1"
        survival = _span(fields[3], "S")
        if survival is None:
            raise LtlRuleError(
                text, f"expected S and a range of counts S<min>..<max>, not '{fields[3]}'"
            )
        birth = _span(fields[4], "B")
        if birth is None:
            raise LtlRuleError(
                text, f"expected B and a range of counts B<min>..<max>, not '{fields[4]}'"
            )
        hood: LtlNeighborhood = "moore"
        if len(fields) == 6:
            field = fields[5]
            if len(field) != 2 or field[0] not in "Nn" or field[1].upper() not in _HOODS:
                raise LtlRuleError(text, f"expected NM, NN or NC, not '{field}'")
            hood = _HOODS[field[1].upper()]
    else:
        numbers = [_number(field) for field in fields]
        if len(fields) != 5 or any(number is None for number in numbers):
            raise LtlRuleError(text, "expected five numbers r,bmin,bmax,smin,smax")
        radius, bmin, bmax, smin, smax = cast(list[_Number], numbers)
        count, middle, survival, birth = _Number(0, "0"), True, (smin, smax), (bmin, bmax)
        hood = "moore"
    if not 1 <= radius.value <= MAX_RANGE:
        raise LtlRuleError(text, f"the range is 1 to {MAX_RANGE}, not {radius.text}")
    if count.value == 1 or count.value > MAX_STATES:
        raise LtlRuleError(text, f"C is 0 or 2 (two states) or 3 to {MAX_STATES}, not {count.text}")
    for letter, (low, high) in (("S", survival), ("B", birth)):
        if max(low.value, high.value) > MAX_COUNT:
            raise LtlRuleError(text, f"a count is at most {MAX_COUNT}")
        if low.value > high.value:
            raise LtlRuleError(text, f"{letter}{low.text}..{high.text} is empty")
    return LtlRule(
        radius.value,
        max(count.value, 2),
        middle,
        (survival[0].value, survival[1].value),
        (birth[0].value, birth[1].value),
        hood,
    )


# -- evolution (spec/ltl.md "Evolution") --------------------------------------------------


def counts(padded: NDArray[np.uint8], rule: LtlRule) -> NDArray[np.int32]:
    """Every cell's count of alive (state-1) cells in its neighborhood, from the grid's halo
    of radius ``rule.range`` (spec/topology.md "The halo"). Exact integers: a summed-area
    table for the box, row prefix sums for the diamond and the circle."""
    r = rule.range
    height, width = padded.shape[0] - 2 * r, padded.shape[1] - 2 * r
    alive = (padded == 1).astype(np.int32)
    if rule.neighborhood == "moore":
        table = np.zeros((height + 2 * r + 1, width + 2 * r + 1), dtype=np.int32)
        table[1:, 1:] = alive.cumsum(axis=0, dtype=np.int32).cumsum(axis=1, dtype=np.int32)
        k = 2 * r + 1
        found = (
            table[k : k + height, k : k + width]
            - table[0:height, k : k + width]
            - table[k : k + height, 0:width]
            + table[0:height, 0:width]
        )
    else:
        rows = np.zeros((height + 2 * r, width + 2 * r + 1), dtype=np.int32)
        rows[:, 1:] = alive.cumsum(axis=1, dtype=np.int32)
        found = np.zeros((height, width), dtype=np.int32)
        for dy, w in zip(range(-r, r + 1), rule.half_widths, strict=True):
            band = rows[r + dy : r + dy + height]
            found += band[:, r + w + 1 : r + w + 1 + width] - band[:, r - w : r - w + width]
    if not rule.middle:
        found -= alive[r : r + height, r : r + width]
    return found


def step(cells: NDArray[np.uint8], halo: Halo, rule: LtlRule) -> NDArray[np.uint8]:
    """One generation of a Larger than Life grid (spec/ltl.md "Evolution"), its edges read
    through ``halo`` (radius ``rule.range``). A new array."""
    found = counts(halo.fill(cells), rule)
    (smin, smax), (bmin, bmax) = rule.survival, rule.birth
    alive = cells == 1
    born = (cells == 0) & (found >= bmin) & (found <= bmax)
    stays = alive & (found >= smin) & (found <= smax)
    stepped = np.zeros_like(cells)
    stepped[born | stays] = 1
    if rule.states > 2:
        stepped[alive & ~stays] = 2
        dying = cells >= 2
        aged = cells.astype(np.uint16) + 1
        aged[aged >= rule.states] = 0
        stepped[dying] = aged[dying].astype(np.uint8)
    return stepped


# -- the family ------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class LargerThanLifeParams(Params):
    # Field metadata documents the spec'd ranges/choices; UIs build forms from it.
    rule: str = dataclasses.field(default=BOSCO, metadata={"label": "Rule (R,C,M,S,B,N)"})
    width: int = dataclasses.field(default=256, metadata={"min": 8, "max": 2048})
    height: int = dataclasses.field(default=256, metadata={"min": 8, "max": 2048})
    init: str = dataclasses.field(default="soup", metadata={"choices": ["soup", "blob", "single"]})
    density: float = dataclasses.field(default=0.5, metadata={"min": 0.0, "max": 1.0, "step": 0.01})
    seed: int = dataclasses.field(default=0, metadata={"min": 0, "max": 4294967295, "role": "seed"})
    # The topology (spec/topology.md): a shift and an axis matter for a torus or a Klein bottle.
    boundary: str = dataclasses.field(default="torus", metadata={"choices": list(BOUNDARIES)})
    shift: int = dataclasses.field(default=0, metadata={"min": -2048, "max": 2048})
    axis: str = dataclasses.field(default="x", metadata={"choices": list(AXES)})


class LargerThanLife(AdvanceRegion):
    """A Larger than Life grid. State is uint8 0..states−1, shape (height, width), row-major."""

    def __init__(
        self,
        rule: str | LtlRule = BOSCO,
        *,
        size: tuple[int, int] = (256, 256),
        init: str | NDArray[np.uint8] = "soup",
        density: float = 0.5,
        seed: int = 0,
        boundary: Boundary = "torus",
        shift: int = 0,
        axis: Axis = "x",
    ) -> None:
        width, height = size
        parsed = rule if isinstance(rule, LtlRule) else parse_ltl_rule(rule)
        self._rule = parsed
        side = 2 * parsed.range + 1
        if width < side or height < side:
            raise ValueError(
                f"a Larger than Life world of range {parsed.range} is at least {side} cells "
                "wide and high (spec/ltl.md)"
            )
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
        # The cells past the edges, r deep, filled each generation (spec/topology.md "The halo").
        self._halo = Halo(topology, width, height, parsed.range)
        self.params = LargerThanLifeParams(
            rule=parsed.canonical,
            width=width,
            height=height,
            init=init_name,
            density=density,
            seed=seed,
            boundary=topology.boundary,
            shift=topology.shift,
            axis=topology.axis,
        )
        self._generation = 0
        self._state: NDArray[np.uint8]
        self.reset()

    @classmethod
    def from_params(cls, params: LargerThanLifeParams) -> LargerThanLife:
        if params.init == "array":
            raise ValueError(
                "params with init='array' cannot be reconstructed; pass the array to "
                "LargerThanLife(init=...)"
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

    def _checked(self, cells: NDArray[np.generic]) -> NDArray[np.uint8]:
        array = np.asarray(cells)
        if array.size and (array.dtype.kind not in "biu" or int(array.min()) < 0):
            raise ValueError(f"Larger than Life cells are states 0 to {self._rule.states - 1}")
        if array.size and int(array.max()) >= self._rule.states:
            raise ValueError(
                f"state {int(array.max())} is past this rule's {self._rule.states} states"
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
        """Replace the state (values 0 to states − 1) and set the generation (spec/README.md
        "A world's state and its start"). The state also becomes the start ``reset()``
        returns to (``init`` ``array``), unless ``keep_start``: then the start stays as it
        was, and no copy of the state is kept for it."""
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
        halo, rule = self._halo, self._rule
        for _ in range(n):
            self._state = step(self._state, halo, rule)
        self._generation += n

    @property
    def state(self) -> NDArray[np.uint8]:
        return self._state

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def rule(self) -> LtlRule:
        return self._rule

    @property
    def topology(self) -> Topology:
        """How the grid's edges join (spec/topology.md)."""
        return self._halo.topology

    def clear_rect(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """spec/patterns.md "Clear": the inclusive rectangle to this family's blank, 0 (dead).
        The generation is untouched."""
        clear(self._state, x0, y0, x1, y1, 0)

    def fill_random(self, x0: int, y0: int, x1: int, y1: int, density: float, seed: int) -> None:
        """spec/patterns.md "Random fill": the region becomes the soup of a world its size,
        alive cells state 1, the same cells Life's random fill gives. The generation is
        untouched."""
        fill_random(self._state, x0, y0, x1, y1, density=density, seed=seed)

    def frame(self) -> NDArray[np.uint8]:
        """spec/ltl.md "Frames": ``state * 255`` for two states, and the state itself (a
        color per state from the host's palette) for more."""
        if self._rule.states > 2:
            return self._state.copy()
        return self._state * np.uint8(255)
