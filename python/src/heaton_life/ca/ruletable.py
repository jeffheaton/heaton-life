"""Rule tables (spec/ruletable.md): any rule a rule file defines, run on a grid.

A rule file (spec/rule-files.md, ``heaton_life.ca.rulefile``) gives a rule of up to 256
states on the 3 × 3 block; ``RuleTableCA`` runs one on every topology of spec/topology.md,
reading each cell's block from the grid's halo and walking the rule's canonical tree for all
cells at once. The library's starter set (``STARTER_RULES``) holds the self-reproducing loops
of Langton, Byl and Sayama and a few ants, re-authored from their publications.
"""

from __future__ import annotations

import dataclasses
import functools
import importlib.resources
import operator
from typing import Final, cast

import numpy as np
from numpy.typing import NDArray

from heaton_life.ca._advance import AdvanceRegion
from heaton_life.ca.rulefile import RuleTable, block_cells, parse_rule_file
from heaton_life.core.params import Params
from heaton_life.core.rng import Pcg32
from heaton_life.core.topology import AXES, BOUNDARIES, Axis, Boundary, Halo, Topology
from heaton_life.init.patterns import clear

STARTER_RULES: Final = (
    "Langtons-Loops",
    "Byl-Loop",
    "Evoloop",
    "Langtons-Ant",
    "Ant-LLRR",
    "Ant-RLR",
)
"""The starter set's names (spec/ruletable.md "The starter set")."""

_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _starter_name(name: str) -> str | None:
    """The starter set's spelling of ``name`` (ASCII case ignored), or None."""
    key = name.translate(_LOWER)
    return next((s for s in STARTER_RULES if s.translate(_LOWER) == key), None)


def _resource(name: str) -> str:
    return (
        importlib.resources.files("heaton_life.ca")
        .joinpath("rules", name)
        .read_text(encoding="utf-8")
    )


@functools.cache
def _starter(name: str) -> RuleTable:
    return parse_rule_file(_resource(f"{name}.rule"))


def starter_rule(name: str) -> RuleTable:
    """The starter set's rule of that name (ASCII case ignored). Raises ValueError for any
    other name."""
    found = _starter_name(name)
    if found is None:
        raise ValueError(
            f"{name!r} is not in the starter set ({', '.join(STARTER_RULES)}; spec/ruletable.md)"
        )
    return _starter(found)


def starter_rule_or_none(name: str) -> RuleTable | None:
    """``starter_rule`` for a name in the starter set, None for any other."""
    found = _starter_name(name)
    return None if found is None else _starter(found)


def starter_pattern(name: str) -> NDArray[np.uint8]:
    """The starter pattern of a starter rule: the cells of the publication's figure
    (spec/ruletable.md "The starter set"), a new array each call."""
    from heaton_life.init.rle import rle_decode

    rule = starter_rule(name)
    cells, _ = rle_decode(_resource(f"{rule.canonical}.rle"))
    return cells


def embedded_rule(text: str) -> RuleTable | None:
    """The rule file appended to an RLE pattern (spec/ruletable.md "Files"): the text from
    the first line after the pattern's ``!`` that starts with ``@RULE``, read as a rule file;
    None when the text has none. Comment lines (``#``) and the header come before the
    pattern, so its end is the first ``!`` in a line after them. An appended text that is no
    rule file raises ``RuleFileError``."""
    from heaton_life.init.rle import is_rle_header

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    index = 0
    while index < len(lines) and (not lines[index].strip() or lines[index].strip().startswith("#")):
        index += 1
    if index < len(lines) and is_rle_header(lines[index].strip()):
        index += 1
    while index < len(lines) and "!" not in lines[index]:
        index += 1
    for later in range(index + 1, len(lines)):
        if lines[later].strip().startswith("@RULE"):
            return parse_rule_file("\n".join(lines[later:]))
    return None


def append_rule(rle: str, rule: RuleTable) -> str:
    """An RLE pattern's text with ``rule``'s file appended after it (spec/ruletable.md
    "Files"), so the pattern carries its rule."""
    body = rle if rle.endswith("\n") else rle + "\n"
    text = rule.text.replace("\r\n", "\n").replace("\r", "\n")
    return body + text + ("" if text.endswith("\n") else "\n")


def resolve_rule_table(rule: str | RuleTable) -> RuleTable:
    """A rule table given as one, or by a starter set's name."""
    if isinstance(rule, RuleTable):
        return rule
    if isinstance(rule, str):
        return starter_rule(rule)
    raise TypeError(f"expected a RuleTable or a name, got {type(rule).__name__}")


@dataclasses.dataclass(frozen=True)
class RuleTableParams(Params):
    # Field metadata documents the spec'd ranges/choices; UIs build forms from it.
    rule: str = dataclasses.field(
        default="Langtons-Loops", metadata={"label": "Rule", "choices": list(STARTER_RULES)}
    )
    width: int = dataclasses.field(default=64, metadata={"min": 8, "max": 2048})
    height: int = dataclasses.field(default=64, metadata={"min": 8, "max": 2048})
    init: str = dataclasses.field(
        default="starter", metadata={"choices": ["starter", "blank", "soup"]}
    )
    density: float = dataclasses.field(
        default=0.35, metadata={"min": 0.0, "max": 1.0, "step": 0.01}
    )
    seed: int = dataclasses.field(default=0, metadata={"min": 0, "max": 4294967295, "role": "seed"})
    # The topology (spec/topology.md): a shift and an axis matter for a torus or a Klein bottle.
    boundary: str = dataclasses.field(
        default="dead", metadata={"choices": ["dead", *(b for b in BOUNDARIES if b != "dead")]}
    )
    shift: int = dataclasses.field(default=0, metadata={"min": -2048, "max": 2048})
    axis: str = dataclasses.field(default="x", metadata={"choices": list(AXES)})


def rule_table_soup(
    size: tuple[int, int], states: int, *, density: float = 0.35, seed: int = 0
) -> NDArray[np.uint8]:
    """spec/ruletable.md "Initialization", soup: PCG32 seq 0, a draw per cell row-major;
    a cell is 0 unless its draw is below ⌊density · 2³²⌋, and then 1 + (draw mod (S − 1))."""
    if not 0.0 <= density <= 1.0:
        raise ValueError(f"density must be in [0, 1], got {density}")
    width, height = size
    draws = Pcg32(seed).fill_u32(width * height).reshape(height, width).astype(np.int64)
    alive = draws < int(density * 4294967296.0)
    cells = np.where(alive, 1 + draws % (states - 1), 0)
    return cells.astype(np.uint8)


class RuleTableCA(AdvanceRegion):
    """A grid running a rule table (spec/ruletable.md). State is uint8, values 0 to S − 1,
    shape (height, width)."""

    def __init__(
        self,
        rule: str | RuleTable = "Langtons-Loops",
        *,
        size: tuple[int, int] = (64, 64),
        init: str | NDArray[np.uint8] = "starter",
        density: float = 0.35,
        seed: int = 0,
        boundary: Boundary = "dead",
        shift: int = 0,
        axis: Axis = "x",
    ) -> None:
        self._rule = resolve_rule_table(rule)
        width, height = size
        self._initial: NDArray[np.uint8] | None = None
        if isinstance(init, np.ndarray):
            if init.shape != (height, width):
                raise ValueError(
                    f"init array shape {init.shape} does not match (h={height}, w={width})"
                )
            self._initial = self._checked(init)
            init_name = "array"
        else:
            init_name = init
        topology = Topology(boundary, shift, axis)
        # The cells past the edges, filled each generation (spec/topology.md "The halo").
        self._halo = Halo(topology, width, height)
        self.params = RuleTableParams(
            rule=self._rule.canonical,
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
    def from_params(cls, params: RuleTableParams, *, rule: RuleTable | None = None) -> RuleTableCA:
        """A world from its params; ``rule`` gives the rule when it is no starter rule (its
        name must be the params' rule)."""
        if params.init == "array":
            raise ValueError("params with init='array' need the array: RuleTableCA(init=...)")
        if rule is not None and _ascii_lower(rule.canonical) != _ascii_lower(params.rule):
            raise ValueError(f"the rule {rule.canonical!r} is not the params' {params.rule!r}")
        return cls(
            params.rule if rule is None else rule,
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
        if array.size and (int(array.min()) < 0 or int(array.max()) >= self._rule.states):
            raise ValueError(
                f"{self._rule.canonical} has states 0 to {self._rule.states - 1}; "
                f"the cells hold {int(array.max()) if int(array.min()) >= 0 else int(array.min())}"
            )
        return array.astype(np.uint8)

    def reset(self, seed: int | None = None) -> None:
        p = self.params
        if seed is not None:
            self.params = p = p.replace(seed=seed)
        if p.init == "array":
            assert self._initial is not None
            self._state = self._initial.copy()
        elif p.init == "blank":
            self._state = np.zeros((p.height, p.width), dtype=np.uint8)
        elif p.init == "soup":
            self._state = rule_table_soup(
                (p.width, p.height), self._rule.states, density=p.density, seed=p.seed
            )
        elif p.init == "starter":
            self._state = self._starter_cells()
        else:
            raise ValueError(f"unknown init strategy: {p.init!r}")
        self._generation = 0

    def _starter_cells(self) -> NDArray[np.uint8]:
        p = self.params
        name = self._rule.canonical
        starter = starter_rule_or_none(name)
        if starter is None or (
            starter is not self._rule and starter.tree_text() != self._rule.tree_text()
        ):
            raise ValueError(f"{name} has no starter pattern (spec/ruletable.md)")
        pattern = starter_pattern(name)
        h, w = pattern.shape
        if w > p.width or h > p.height:
            raise ValueError(
                f"the starter pattern of {name} is {w} x {h} cells, bigger than the "
                f"{p.width} x {p.height} grid"
            )
        cells = np.zeros((p.height, p.width), dtype=np.uint8)
        x0, y0 = (p.width - w) // 2, (p.height - h) // 2
        cells[y0 : y0 + h, x0 : x0 + w] = pattern
        return cells

    def set_state(
        self, state: NDArray[np.generic], generation: int = 0, *, keep_start: bool = False
    ) -> None:
        """Replace the state (values 0 to S − 1) and set the generation (spec/README.md "A
        world's state and its start"). The state also becomes the start ``reset()`` returns
        to (``init`` ``array``), unless ``keep_start``: then the start stays as it was, and
        no copy of the state is kept for it."""
        p = self.params
        cells = np.asarray(state)
        if cells.shape != (p.height, p.width):
            raise ValueError(
                f"state shape {cells.shape} does not match (h={p.height}, w={p.width})"
            )
        checked = self._checked(cells)
        generation = operator.index(generation)
        if not keep_start:
            self._initial = checked.copy()
            self.params = p.replace(init="array")
        self._state = checked
        self._generation = generation

    def step(self, n: int = 1) -> None:
        halo, rule = self._halo, self._rule
        height, width = self._state.shape
        for _ in range(n):
            padded = halo.fill(self._state, 0)
            self._state = rule.evaluate(dict(block_cells(padded, height, width)))
        self._generation += n

    @property
    def state(self) -> NDArray[np.uint8]:
        return self._state

    @property
    def rule(self) -> RuleTable:
        """The world's rule table."""
        return self._rule

    @property
    def states(self) -> int:
        """S: the rule's number of states."""
        return self._rule.states

    @property
    def topology(self) -> Topology:
        """How the grid's edges join (spec/topology.md)."""
        return self._halo.topology

    @property
    def generation(self) -> int:
        return self._generation

    def clear_rect(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """spec/patterns.md "Clear": an inclusive rectangle to the family's blank, 0. The
        generation is untouched, as for a stamp."""
        clear(self._state, x0, y0, x1, y1, 0)

    def frame(self) -> NDArray[np.uint8]:
        """The states themselves (spec/ruletable.md "Frames"), for a palette of a color per
        state."""
        return self._state.copy()


def _ascii_lower(text: str) -> str:
    return text.translate(_LOWER)
