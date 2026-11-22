"""Rule files (spec/rule-files.md): the ``.rule`` format the Life community shares rules in.

A rule file names a cellular automaton of 2 to 256 states on the 3 × 3 block and gives its
transition function as a table (``@TABLE``) or a tree (``@TREE``), with colors, state names
and icons for showing it. ``parse_rule_file`` reads one into a ``RuleTable``: the function
compiled to its canonical tree, the file's other data kept as read, and a ``StateRule``
(spec/hashlife-multistate.md "State rules") the multi-state universe runs. The rule-table
family (spec/ruletable.md, ``heaton_life.ca.ruletable``) runs one on a grid.
"""

from __future__ import annotations

import dataclasses
import itertools
from collections.abc import Iterator, Sequence
from typing import Final

import numpy as np
from numpy.typing import NDArray

from heaton_life.ca.rulestring import _SPACE
from heaton_life.ca.state_rules import StateRule

MAX_STATES: Final = 256
"""The most states a rule may have: a state is one byte."""

NEIGHBORHOODS: Final = ("vonNeumann", "Moore", "hexagonal", "oneDimensional")
"""The neighborhoods a table may have, in their canonical spellings."""

# Each neighborhood's symmetries, in their canonical spellings with their aliases, in the
# order a reason lists them (spec/rule-files.md "Symmetries").
_SYMMETRIES: Final[dict[str, tuple[tuple[str, str], ...]]] = {
    "vonNeumann": (
        ("none", "none"),
        ("rotate4", "rotate4"),
        ("rotate4reflect", "rotate4reflect"),
        ("reflect_horizontal", "reflect_horizontal"),
        ("reflect", "reflect_horizontal"),
        ("permute", "permute"),
    ),
    "Moore": (
        ("none", "none"),
        ("rotate4", "rotate4"),
        ("rotate8", "rotate8"),
        ("rotate4reflect", "rotate4reflect"),
        ("rotate8reflect", "rotate8reflect"),
        ("reflect_horizontal", "reflect_horizontal"),
        ("reflect", "reflect_horizontal"),
        ("permute", "permute"),
    ),
    "hexagonal": (
        ("none", "none"),
        ("rotate2", "rotate2"),
        ("rotate3", "rotate3"),
        ("rotate6", "rotate6"),
        ("rotate6reflect", "rotate6reflect"),
        ("permute", "permute"),
    ),
    "oneDimensional": (
        ("none", "none"),
        ("reflect", "reflect"),
        ("reflect_horizontal", "reflect"),
        ("permute", "permute"),
    ),
}

# The block's cells by name, in the order StateRule.next_state takes them.
_BLOCK: Final = ("nw", "n", "ne", "w", "c", "e", "sw", "s", "se")
# The cells a tree walks, root first (spec/rule-files.md "@TREE").
_TREE_ORDER: Final[dict[int, tuple[str, ...]]] = {
    8: ("nw", "ne", "sw", "se", "n", "w", "e", "s", "c"),
    4: ("n", "w", "e", "s", "c"),
}
# Each neighborhood's ring of neighbors (a transition's fields between C and C′), and the
# tree it compiles to.
_RING: Final[dict[str, tuple[str, ...]]] = {
    "vonNeumann": ("n", "e", "s", "w"),
    "Moore": ("n", "ne", "e", "se", "s", "sw", "w", "nw"),
    "hexagonal": ("n", "e", "se", "s", "w", "nw"),
    "oneDimensional": ("w", "e"),
}
_NEIGHBORS: Final[dict[str, int]] = {
    "vonNeumann": 4,
    "Moore": 8,
    "hexagonal": 8,
    "oneDimensional": 4,
}

_ICON_STYLES: Final = ("circles", "diamonds", "hexagons", "triangles")
_ICON_WIDTHS: Final = (7, 15, 31)
_HEX: Final = frozenset("0123456789abcdefABCDEF")
_DIGITS: Final = frozenset("0123456789")
_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


class RuleFileError(ValueError):
    """A text that is no rule file, with spec/rule-files.md's reason and the line (counted
    from 1) where the problem is, or None where the whole file is at fault."""

    def __init__(self, reason: str, line: int | None) -> None:
        where = "" if line is None else f"line {line}: "
        super().__init__(f"invalid rule file: {where}{reason} (spec/rule-files.md)")
        self.reason = reason
        self.line = line


@dataclasses.dataclass(frozen=True)
class StateColor:
    """A ``@COLORS`` line ``state r g b``."""

    state: int
    rgb: tuple[int, int, int]


@dataclasses.dataclass(frozen=True)
class Gradient:
    """A ``@COLORS`` line ``r1 g1 b1 r2 g2 b2``: a gradient over states 1 to S − 1."""

    start: tuple[int, int, int]
    end: tuple[int, int, int]


@dataclasses.dataclass(frozen=True)
class StateName:
    """A ``@NAMES`` line: a state and its name."""

    state: int
    name: str


@dataclasses.dataclass(frozen=True)
class IconSet:
    """One XPM set of ``@ICONS``: the icons' width (7, 15 or 31), the colors (each a key
    and ``#RRGGBB`` in uppercase, or None for no color) and the rows as written. Icon k
    (rows k·width to k·width + width − 1) is for state k + 1."""

    width: int
    colors: tuple[tuple[str, str | None], ...]
    rows: tuple[str, ...]

    @property
    def count(self) -> int:
        """How many icons the set holds."""
        return len(self.rows) // self.width


@dataclasses.dataclass(frozen=True)
class Icons:
    """A file's ``@ICONS``: a style (``circles``, ``diamonds``, ``hexagons`` or
    ``triangles``), or the XPM sets kept (those of width 7, 15 or 31), in file order."""

    style: str | None
    sets: tuple[IconSet, ...]


ColorEntry = StateColor | Gradient


# -- lines -----------------------------------------------------------------------------


def _trim(text: str) -> str:
    start, end = 0, len(text)
    while start < end and text[start] in _SPACE:
        start += 1
    while end > start and text[end - 1] in _SPACE:
        end -= 1
    return text[start:end]


def _words(text: str) -> list[str]:
    """``text`` split at runs of spec/rules.md's whitespace, empty words dropped."""
    words: list[str] = []
    start = -1
    for i, ch in enumerate(text):
        if ch in _SPACE:
            if start >= 0:
                words.append(text[start:i])
                start = -1
        elif start < 0:
            start = i
    if start >= 0:
        words.append(text[start:])
    return words


def _lower(text: str) -> str:
    return text.translate(_LOWER)


def _is_digits(text: str) -> bool:
    return bool(text) and all(ch in _DIGITS for ch in text)


def _number(text: str, limit: int) -> int | None:
    """Decimal digits as a number when it is at most ``limit``, else None."""
    if not _is_digits(text):
        return None
    significant = text.lstrip("0")
    if len(significant) > len(str(limit)):
        return None
    value = int(significant or "0")
    return value if value <= limit else None


def _section(trimmed: str) -> tuple[str, str] | None:
    """A section line's name and argument, or None for any other line."""
    if not trimmed.startswith("@"):
        return None
    end = 1
    while end < len(trimmed) and "A" <= trimmed[end] <= "Z":
        end += 1
    if end == 1 or (end < len(trimmed) and trimmed[end] not in _SPACE):
        return None
    return trimmed[1:end], _trim(trimmed[end:])


def _uncomment(line: str) -> str:
    """A line without its ``#`` comment, trimmed."""
    hash_at = line.find("#")
    return _trim(line if hash_at < 0 else line[:hash_at])


@dataclasses.dataclass
class _Section:
    name: str
    argument: str
    line: int
    lines: list[tuple[int, str]]


def _split_sections(text: str) -> list[_Section]:
    text = text.removeprefix("\N{BYTE ORDER MARK}")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    first = next((k for k, line in enumerate(lines) if _trim(line)), None)
    start_reason = "a rule file starts with '@RULE' and the rule's name"
    if first is None:
        raise RuleFileError(start_reason, None)
    head = _section(_trim(lines[first]))
    if head is None or head[0] != "RULE":
        raise RuleFileError(start_reason, first + 1)
    sections: list[_Section] = []
    for k in range(first, len(lines)):
        found = _section(_trim(lines[k]))
        if found is not None:
            sections.append(_Section(found[0], found[1], k + 1, []))
        else:
            sections[-1].lines.append((k + 1, lines[k]))
    return sections


# -- @RULE -------------------------------------------------------------------------------


def _rule_name(section: _Section) -> str:
    name = section.argument
    if not name:
        raise RuleFileError("'@RULE' has no name", section.line)
    if any(ch in _SPACE for ch in name):
        raise RuleFileError("a rule's name has no spaces", section.line)
    if any(not "!" <= ch <= "~" or ch in ",:" for ch in name):
        raise RuleFileError("a rule's name is printable ASCII without ',' or ':'", section.line)
    return name


def _description(section: _Section) -> str:
    lines = [line for _, line in section.lines]
    while lines and not _trim(lines[0]):
        lines.pop(0)
    while lines and not _trim(lines[-1]):
        lines.pop()
    return "\n".join(lines)


# -- @TABLE ------------------------------------------------------------------------------

# A field of a parsed transition: a state, or a variable's name.
_Field = int | str


@dataclasses.dataclass(frozen=True)
class _Transition:
    inputs: tuple[_Field, ...]  # C, then the ring in the neighborhood's order
    output: _Field


@dataclasses.dataclass(frozen=True)
class _Table:
    states: int
    neighborhood: str
    symmetries: str
    variables: dict[str, tuple[int, ...]]
    transitions: tuple[_Transition, ...]


def _parse_table(section: _Section) -> _Table:
    settings: dict[str, tuple[str, int]] = {}
    states = 0
    neighborhood = ""
    symmetries = ""
    settled = False
    variables: dict[str, tuple[int, ...]] = {}
    transitions: list[_Transition] = []

    def settle(line: int | None) -> None:
        nonlocal symmetries
        for key in ("n_states", "neighborhood", "symmetries"):
            if key not in settings:
                raise RuleFileError(f"'{key}' is missing", line)
        value, value_line = settings["symmetries"]
        allowed = _SYMMETRIES[neighborhood]
        for spelling, canonical in allowed:
            if _lower(value) == _lower(spelling):
                symmetries = canonical
                return
        listed = ", ".join(spelling for spelling, _ in allowed)
        raise RuleFileError(
            f"the {neighborhood} neighborhood has no '{value}' symmetries: expected {listed}",
            value_line,
        )

    for line_no, raw in section.lines:
        text = _uncomment(raw)
        if not text:
            continue
        words = _words(text)
        if words[0] == "var":
            if not settled:
                settle(line_no)
                settled = True
            name, members = _parse_variable(text, line_no, states, variables)
            variables[name] = members
        elif ":" in text:
            key_text, _, value = text.partition(":")
            key_text, value = _trim(key_text), _trim(value)
            key = _lower(key_text)
            if key not in ("n_states", "neighborhood", "symmetries"):
                raise RuleFileError(f"unknown setting '{key_text}'", line_no)
            if settled:
                raise RuleFileError(f"'{key}' comes before the variables and transitions", line_no)
            if key in settings:
                raise RuleFileError(f"'{key}' is set twice", line_no)
            if key == "n_states":
                number = _number(value, MAX_STATES)
                if number is None or number < 2:
                    raise RuleFileError("n_states is a whole number from 2 to 256", line_no)
                states = number
            elif key == "neighborhood":
                found = next((n for n in NEIGHBORHOODS if _lower(n) == _lower(value)), None)
                if found is None:
                    raise RuleFileError(
                        f"unknown neighborhood '{value}': expected vonNeumann, Moore, "
                        "hexagonal or oneDimensional",
                        line_no,
                    )
                neighborhood = found
            settings[key] = (value, line_no)
        else:
            if not settled:
                settle(line_no)
                settled = True
            transitions.append(_parse_transition(text, line_no, states, neighborhood, variables))
    if not settled:
        settle(None)
    return _Table(states, neighborhood, symmetries, variables, tuple(transitions))


def _state_or_variable(
    text: str, line: int, states: int, variables: dict[str, tuple[int, ...]]
) -> _Field:
    if _is_digits(text):
        value = _number(text, states - 1)
        if value is None:
            raise RuleFileError(f"state {text} is not below n_states {states}", line)
        return value
    if text not in variables:
        raise RuleFileError(f"unknown variable '{text}'", line)
    return text


def _parse_variable(
    text: str, line: int, states: int, variables: dict[str, tuple[int, ...]]
) -> tuple[str, tuple[int, ...]]:
    syntax = RuleFileError("expected 'var name = {states}'", line)
    rest = _trim(text[3:])
    end = 0
    while end < len(rest) and rest[end] not in _SPACE and rest[end] != "=":
        end += 1
    name = rest[:end]
    rest = _trim(rest[end:])
    if not name or not rest.startswith("="):
        raise syntax
    rest = _trim(rest[1:])
    if not rest.startswith("{") or not rest.endswith("}") or len(rest) < 2:
        raise syntax
    inner = rest[1:-1]
    if "{" in inner or "}" in inner:
        raise syntax
    if _is_digits(name):
        raise RuleFileError("a variable's name can't be a number", line)
    if any(not "!" <= ch <= "~" or ch in ",{}=:" for ch in name):
        raise RuleFileError(
            "a variable's name is printable ASCII without ',', '{', '}', '=' or ':'", line
        )
    if name in variables:
        raise RuleFileError(f"variable '{name}' is defined twice", line)
    if not _trim(inner):
        raise RuleFileError(f"variable '{name}' has no states", line)
    members: set[int] = set()
    for part in inner.split(","):
        member = _trim(part)
        if not member:
            raise syntax
        field = _state_or_variable(member, line, states, variables)
        if isinstance(field, int):
            members.add(field)
        else:
            members.update(variables[field])
    return name, tuple(sorted(members))


def _field_count(neighborhood: str) -> int:
    return len(_RING[neighborhood]) + 2


def _parse_transition(
    text: str, line: int, states: int, neighborhood: str, variables: dict[str, tuple[int, ...]]
) -> _Transition:
    fields: list[str] = []
    for part in text.split(","):
        piece = _trim(part)
        if not piece:
            raise RuleFileError("a transition has an empty field", line)
        fields.extend(_words(piece))
    count = _field_count(neighborhood)
    if len(fields) != count:
        if len(fields) == 1 and states <= 10 and _is_digits(fields[0]) and len(fields[0]) == count:
            fields = list(fields[0])
        else:
            raise RuleFileError(
                f"a {neighborhood} transition has {count} fields, not {len(fields)}", line
            )
    parsed = [_state_or_variable(field, line, states, variables) for field in fields]
    inputs, output = tuple(parsed[:-1]), parsed[-1]
    if isinstance(output, str) and output not in inputs and len(variables[output]) != 1:
        raise RuleFileError(f"the output '{output}' has several states and no input binds it", line)
    return _Transition(inputs, output)


# -- symmetries --------------------------------------------------------------------------


def variant_orders(neighborhood: str, symmetries: str) -> tuple[tuple[int, ...], ...]:
    """The variants of a transition under ``symmetries``, in the order they are tried
    (spec/rule-files.md "Symmetries"): each a tuple ``p`` saying that the variant's ring
    position ``i`` takes the transition's neighbor at position ``p[i]``."""
    k = len(_RING[neighborhood])
    if symmetries == "permute":
        return tuple(itertools.permutations(range(k)))

    def rotation(r: int) -> tuple[int, ...]:
        return tuple((i + r) % k for i in range(k))

    def reflected(order: tuple[int, ...]) -> tuple[int, ...]:
        if neighborhood == "oneDimensional":
            return (order[1], order[0])
        return tuple(order[(k - i) % k] for i in range(k))

    steps = {
        "none": [0],
        "rotate2": [0, 3],
        "rotate3": [0, 2, 4],
        "rotate4": [0, 1, 2, 3] if k == 4 else [0, 2, 4, 6],
        "rotate4reflect": [0, 1, 2, 3] if k == 4 else [0, 2, 4, 6],
        "rotate6": list(range(6)),
        "rotate6reflect": list(range(6)),
        "rotate8": list(range(8)),
        "rotate8reflect": list(range(8)),
        "reflect_horizontal": [0],
        "reflect": [0],
    }[symmetries]
    rotations = [rotation(r) for r in steps]
    if symmetries in ("rotate4reflect", "rotate6reflect", "rotate8reflect"):
        return tuple(rotations + [reflected(order) for order in rotations])
    if symmetries in ("reflect_horizontal", "reflect"):
        return (rotations[0], reflected(rotations[0]))
    return tuple(rotations)


# -- compiling a table -------------------------------------------------------------------

# A pattern's field at one level of the tree: None (any state), or (kind, value, mask):
# kind 0 a state (value), 1 an unbound set (mask), 2 a bound variable (value = its slot).
_Spec = tuple[int, int, int] | None


@dataclasses.dataclass(frozen=True)
class _Pattern:
    specs: tuple[_Spec, ...]  # one per tree level, root first
    output: tuple[int, int]  # (0, state) or (2, slot)
    slots: int


def _patterns(table: _Table, order: tuple[str, ...]) -> list[_Pattern]:
    """Every variant of every transition, in the order they are tried, each as one field
    per tree level: a variant equal to an earlier variant of its transition adds nothing."""
    orders = variant_orders(table.neighborhood, table.symmetries)
    patterns: list[_Pattern] = []
    for transition in table.transitions:
        patterns.extend(_variants(table, transition, orders, order))
    return patterns


def _variants(
    table: _Table,
    transition: _Transition,
    orders: tuple[tuple[int, ...], ...],
    order: tuple[str, ...],
) -> list[_Pattern]:
    ring = _RING[table.neighborhood]
    uses: dict[str, int] = {}
    for field in transition.inputs:
        if isinstance(field, str):
            uses[field] = uses.get(field, 0) + 1
    slots: dict[str, int] = {}

    def spec(field: _Field) -> tuple[int, int, int]:
        if isinstance(field, int):
            return (0, field, 0)
        mask = sum(1 << v for v in table.variables[field])
        if uses[field] > 1 or field == transition.output:  # a bound variable
            return (2, slots.setdefault(field, len(slots)), mask)
        return (1, 0, mask)

    center = spec(transition.inputs[0])
    neighbors = [spec(field) for field in transition.inputs[1:]]
    output = transition.output
    if isinstance(output, int):
        out = (0, output)
    elif output in slots:
        out = (2, slots[output])
    else:
        out = (0, table.variables[output][0])  # a variable of one state
    variants: list[_Pattern] = []
    seen: set[tuple[tuple[int, int, int], ...]] = set()
    for permutation in orders:
        variant = tuple(neighbors[permutation[i]] for i in range(len(ring)))
        if variant in seen:
            continue
        seen.add(variant)
        cells: dict[str, tuple[int, int, int]] = dict(zip(ring, variant, strict=True))
        cells["c"] = center
        variants.append(_Pattern(tuple(cells.get(name) for name in order), out, len(slots)))
    return variants


class _TreeBuilder:
    """Nodes made once each: a level and its children (states at level 1, node indices
    above), numbered as they are made."""

    def __init__(self) -> None:
        self.nodes: list[tuple[int, tuple[int, ...]]] = []
        self._index: dict[tuple[int, tuple[int, ...]], int] = {}

    def node(self, level: int, children: tuple[int, ...]) -> int:
        key = (level, children)
        found = self._index.get(key)
        if found is None:
            found = len(self.nodes)
            self._index[key] = found
            self.nodes.append(key)
        return found


def _compile(table: _Table) -> tuple[int, list[tuple[int, tuple[int, ...]]], int]:
    """The tree of ``table``'s function: (neighbors, nodes, root)."""
    neighbors = _NEIGHBORS[table.neighborhood]
    order = _TREE_ORDER[neighbors]
    patterns = _patterns(table, order)
    states = table.states
    levels = len(order)
    builder = _TreeBuilder()
    memo: dict[tuple[int, tuple[tuple[int, tuple[int, ...]], ...]], int] = {}

    def advance(
        active: tuple[tuple[int, tuple[int, ...]], ...], depth: int, value: int
    ) -> tuple[tuple[int, tuple[int, ...]], ...]:
        kept: list[tuple[int, tuple[int, ...]]] = []
        for index, binding in active:
            spec = patterns[index].specs[depth]
            if spec is None:
                kept.append((index, binding))
                continue
            kind, slot, mask = spec
            if kind == 0:
                if value == slot:
                    kept.append((index, binding))
            elif kind == 1:
                if mask >> value & 1:
                    kept.append((index, binding))
            elif binding[slot] >= 0:
                if binding[slot] == value:
                    kept.append((index, binding))
            elif mask >> value & 1:
                bound = binding[:slot] + (value,) + binding[slot + 1 :]
                kept.append((index, bound))
        return tuple(kept)

    def build(active: tuple[tuple[int, tuple[int, ...]], ...], depth: int) -> int:
        key = (depth, active)
        found = memo.get(key)
        if found is not None:
            return found
        level = levels - depth
        children: list[int] = []
        for value in range(states):
            matched = advance(active, depth, value)
            if depth == levels - 1:
                if matched:
                    index, binding = matched[0]
                    kind, out = patterns[index].output
                    children.append(out if kind == 0 else binding[out])
                else:
                    children.append(value)  # nothing matches: the center keeps its state
            else:
                children.append(build(matched, depth + 1))
        node = builder.node(level, tuple(children))
        memo[key] = node
        return node

    start = tuple((index, (-1,) * pattern.slots) for index, pattern in enumerate(patterns))
    root = build(start, 0)
    return neighbors, builder.nodes, root


def canonical_tree(
    nodes: Sequence[tuple[int, Sequence[int]]], root: int
) -> list[tuple[int, tuple[int, ...]]]:
    """A tree in its canonical form (spec/rule-files.md "Compiling a table to a tree"):
    alike nodes merged, unreachable ones gone, numbered in post-order from the root."""
    builder = _TreeBuilder()
    renamed: dict[int, int] = {}

    def visit(index: int) -> int:
        done = renamed.get(index)
        if done is not None:
            return done
        level, children = nodes[index]
        if level == 1:
            new = builder.node(1, tuple(children))
        else:
            new = builder.node(level, tuple(visit(child) for child in children))
        renamed[index] = new
        return new

    visit(root)
    return builder.nodes


# -- @TREE -------------------------------------------------------------------------------


def _parse_tree(section: _Section) -> tuple[int, int, list[tuple[int, tuple[int, ...]]]]:
    settings: dict[str, int] = {}
    nodes: list[tuple[int, tuple[int, ...]]] = []
    keys = ("num_states", "num_neighbors", "num_nodes")

    def settle(line: int | None) -> None:
        for key in keys:
            if key not in settings:
                raise RuleFileError(f"'{key}' is missing", line)

    settled = False
    for line_no, raw in section.lines:
        text = _uncomment(raw)
        if not text:
            continue
        if "=" in text:
            key_text, _, value = text.partition("=")
            key = _lower(_trim(key_text))
            value = _trim(value)
            if key not in keys:
                raise RuleFileError(
                    "expected 'num_states', 'num_neighbors' or 'num_nodes' and '='", line_no
                )
            if key in settings:
                raise RuleFileError(f"'{key}' is set twice", line_no)
            if key == "num_states":
                number = _number(value, MAX_STATES)
                if number is None or number < 2:
                    raise RuleFileError("num_states is a whole number from 2 to 256", line_no)
            elif key == "num_neighbors":
                number = _number(value, 8)
                if number not in (4, 8):
                    raise RuleFileError("num_neighbors is 4 or 8", line_no)
            else:
                number = _number(value, 1 << 30)
                if number is None or number < 1:
                    raise RuleFileError("num_nodes is a positive whole number", line_no)
            settings[key] = number
            continue
        if not settled:
            settle(line_no)
            settled = True
        states, top = settings["num_states"], settings["num_neighbors"] + 1
        if len(nodes) == settings["num_nodes"]:
            raise RuleFileError("the tree has more than num_nodes nodes", line_no)
        words = _words(text)
        if len(words) != states + 1 or not all(_is_digits(word) for word in words):
            raise RuleFileError(
                f"a node is its level and {states} children, all whole numbers", line_no
            )
        level = _number(words[0], top)
        if level is None or level < 1:
            raise RuleFileError(f"a node's level is 1 to {top}", line_no)
        children: list[int] = []
        for word in words[1:]:
            if level == 1:
                child = _number(word, states - 1)
                if child is None:
                    raise RuleFileError(
                        f"a level-1 node's children are states below {states}", line_no
                    )
            else:
                child = _number(word, len(nodes) - 1) if nodes else None
                if child is None or nodes[child][0] != level - 1:
                    raise RuleFileError(
                        f"a level-{level} node's children are earlier nodes of level {level - 1}",
                        line_no,
                    )
            children.append(child)
        nodes.append((level, tuple(children)))
    if not settled:
        settle(None)
    if len(nodes) != settings["num_nodes"]:
        raise RuleFileError(
            f"the tree has {len(nodes)} nodes, not num_nodes {settings['num_nodes']}", None
        )
    top = settings["num_neighbors"] + 1
    if nodes[-1][0] != top:
        raise RuleFileError(f"the root, the last node, is at level {top}", None)
    return settings["num_states"], settings["num_neighbors"], nodes


# -- @COLORS, @NAMES, @ICONS -------------------------------------------------------------


def _parse_colors(section: _Section) -> list[ColorEntry]:
    entries: list[ColorEntry] = []
    for line_no, raw in section.lines:
        text = _trim(raw)
        if not text or text.startswith("#"):
            continue
        numbers: list[str] = []
        for word in _words(text):
            if not _is_digits(word):
                break
            numbers.append(word)
        if len(numbers) < 4:
            raise RuleFileError("a '@COLORS' line is 'state r g b' or 'r1 g1 b1 r2 g2 b2'", line_no)
        components = numbers[1:4] if len(numbers) < 6 else numbers[:6]
        values = [_number(word, 255) for word in components]
        if any(value is None for value in values):
            raise RuleFileError("a color component is 0 to 255", line_no)
        rgb = [value for value in values if value is not None]
        if len(numbers) >= 6:
            entries.append(Gradient((rgb[0], rgb[1], rgb[2]), (rgb[3], rgb[4], rgb[5])))
        else:
            state = _number(numbers[0], MAX_STATES - 1)
            entries.append(
                StateColor(MAX_STATES if state is None else state, (rgb[0], rgb[1], rgb[2]))
            )
    return entries


def _parse_names(section: _Section) -> list[StateName]:
    entries: list[StateName] = []
    for line_no, raw in section.lines:
        text = _trim(raw)
        if not text or text.startswith("#"):
            continue
        end = 0
        while end < len(text) and text[end] in _DIGITS:
            end += 1
        name = _trim(text[end:])
        if end == 0 or end == len(text) or text[end] not in _SPACE or not name:
            raise RuleFileError("a '@NAMES' line is a state and its name", line_no)
        state = _number(text[:end], MAX_STATES - 1)
        entries.append(StateName(MAX_STATES if state is None else state, name))
    return entries


def _quoted(text: str, line: int) -> str:
    close = text.find('"', 1)
    if close < 0:
        raise RuleFileError("a quoted string has no closing '\"'", line)
    return text[1:close]


def _parse_icons(section: _Section) -> Icons:
    style: str | None = None
    sets: list[IconSet] = []
    both = "'@ICONS' holds one style or XPM sets, not both"
    # The XPM set being read: its line, and its strings so far.
    current: tuple[int, list[tuple[int, str]]] | None = None

    def finish() -> None:
        nonlocal current
        if current is not None:
            kept = _xpm_set(current[0], current[1])
            if kept is not None:
                sets.append(kept)
        current = None

    for line_no, raw in section.lines:
        text = _trim(raw)
        if not text or text.startswith(("#", "/")):
            continue
        if text.startswith('"'):
            if current is None:
                raise RuleFileError(
                    "an '@ICONS' line is 'XPM', a quoted string, or circles, diamonds, "
                    "hexagons or triangles",
                    line_no,
                )
            current[1].append((line_no, _quoted(text, line_no)))
        elif text == "XPM":
            if style is not None:
                raise RuleFileError(both, line_no)
            finish()
            current = (line_no, [])
        elif _lower(text) in _ICON_STYLES:
            if style is not None or sets or current is not None:
                raise RuleFileError(both, line_no)
            style = _lower(text)
        else:
            raise RuleFileError(
                "an '@ICONS' line is 'XPM', a quoted string, or circles, diamonds, "
                "hexagons or triangles",
                line_no,
            )
    finish()
    return Icons(style, tuple(sets))


def _xpm_set(line: int, strings: list[tuple[int, str]]) -> IconSet | None:
    header_reason = (
        "an XPM set's first string is its width, height, colors and characters per pixel"
    )
    if not strings:
        raise RuleFileError(header_reason, line)
    header_line, header = strings[0]
    words = _words(header)
    numbers = [_number(word, 1 << 20) for word in words] if len(words) == 4 else []
    if len(numbers) != 4 or any(n is None for n in numbers):
        raise RuleFileError(header_reason, header_line)
    width, height, colors, per_pixel = (n for n in numbers if n is not None)
    if width < 1 or height < width or height % width or colors < 1 or per_pixel not in (1, 2):
        raise RuleFileError(header_reason, header_line)
    needed = 1 + colors + height
    palette: list[tuple[str, str | None]] = []
    keys: set[str] = set()
    color_reason = "an XPM color is a key, 'c' and #RRGGBB or None"
    for string_line, string in strings[1 : 1 + colors]:
        key, rest = string[:per_pixel], string[per_pixel:]
        words = _words(rest)
        if (
            len(key) != per_pixel
            or key in keys
            or not rest
            or rest[0] not in _SPACE
            or len(words) != 2
            or words[0] != "c"
        ):
            raise RuleFileError(color_reason, string_line)
        color = words[1]
        if _lower(color) == "none":
            value: str | None = None
        elif len(color) == 7 and color[0] == "#" and all(ch in _HEX for ch in color[1:]):
            value = color.upper()
        else:
            raise RuleFileError(color_reason, string_line)
        keys.add(key)
        palette.append((key, value))
    rows: list[str] = []
    for string_line, string in strings[1 + colors : needed]:
        if len(string) != width * per_pixel or any(
            string[i : i + per_pixel] not in keys for i in range(0, len(string), per_pixel)
        ):
            raise RuleFileError(
                f"an XPM row is {width * per_pixel} characters, a color's key for each of its "
                f"{width} pixels",
                string_line,
            )
        rows.append(string)
    if len(strings) < needed:
        raise RuleFileError(f"the XPM set has {len(strings)} strings, not {needed}", line)
    if width not in _ICON_WIDTHS:
        return None
    return IconSet(width, tuple(palette), tuple(rows))


# -- the rule ----------------------------------------------------------------------------


class RuleTable(StateRule):
    """A rule file's rule (spec/rule-files.md): its name, states, neighborhood, its
    function as a canonical tree, and the file's colors, names and icons as read. A
    ``StateRule``: the multi-state universe runs it, and the rule-table family runs it on a
    grid. Made by ``parse_rule_file``."""

    def __init__(
        self,
        *,
        name: str,
        states: int,
        neighbors: int,
        nodes: list[tuple[int, tuple[int, ...]]],
        neighborhood: str | None,
        symmetries: str | None,
        source: str,
        description: str,
        colors: tuple[ColorEntry, ...],
        names: tuple[StateName, ...],
        icons: Icons | None,
        text: str,
    ) -> None:
        self.canonical = name
        self.states = states
        self.neighbors = neighbors
        """4 (the von Neumann cells) or 8 (the Moore block): the tree's neighbors."""
        self.neighborhood = neighborhood
        """A table's neighborhood (``vonNeumann``, ``Moore``, ``hexagonal`` or
        ``oneDimensional``), or None for a tree."""
        self.symmetries = symmetries
        """A table's symmetries in their canonical spelling, or None for a tree."""
        self.source = source
        """``table`` or ``tree``: the section that gave the function."""
        self.description = description
        self.colors = colors
        self.names = names
        self.icons = icons
        self.text = text
        """The file's text as given."""
        self._nodes = nodes
        self._root = len(nodes) - 1
        self._rows = [children for _, children in nodes]
        children = np.array([list(c) for _, c in nodes], dtype=np.int32)
        children.setflags(write=False)
        self._children: NDArray[np.int32] = children
        self._cells = _TREE_ORDER[neighbors]

    @property
    def name(self) -> str:
        """The rule's name, as the file writes it: its canonical name."""
        return self.canonical

    @property
    def nodes(self) -> list[tuple[int, tuple[int, ...]]]:
        """The canonical tree's nodes, the root last: each a level and its children."""
        return list(self._nodes)

    def tree_text(self) -> str:
        """The canonical tree as ``@TREE`` text (spec/rule-files.md "Compiling a table to
        a tree")."""
        lines = [
            f"num_states={self.states}",
            f"num_neighbors={self.neighbors}",
            f"num_nodes={len(self._nodes)}",
        ]
        lines += [" ".join(str(v) for v in (level, *children)) for level, children in self._nodes]
        return "\n".join(lines) + "\n"

    def next_state(
        self, nw: int, n: int, ne: int, w: int, c: int, e: int, sw: int, s: int, se: int
    ) -> int:
        rows = self._rows
        if self.neighbors == 8:
            i = rows[self._root][nw]
            i = rows[i][ne]
            i = rows[i][sw]
            i = rows[i][se]
            i = rows[i][n]
        else:
            i = rows[self._root][n]
        i = rows[i][w]
        i = rows[i][e]
        i = rows[i][s]
        return rows[i][c]

    def evaluate(self, cells: dict[str, NDArray[np.uint8]]) -> NDArray[np.uint8]:
        """The next states of many blocks at once: ``cells`` maps each cell the tree reads
        (``nw`` … ``se`` by the block's names) to an array of states, all of one shape."""
        children = self._children
        order = self._cells
        index = children[self._root][cells[order[0]]]
        for name in order[1:]:
            index = children[index, cells[name]]
        result: NDArray[np.uint8] = index.astype(np.uint8)
        return result

    def __repr__(self) -> str:
        return f"RuleTable({self.canonical!r}, states={self.states}, neighbors={self.neighbors})"


def parse_rule_file(text: str) -> RuleTable:
    """The rule a rule file defines (spec/rule-files.md). Raises ``RuleFileError`` with the
    reason the page gives for the first problem found."""
    if not isinstance(text, str):
        raise TypeError(f"a rule file is text, not {type(text).__name__}")
    sections = _split_sections(text)
    name = ""
    description = ""
    source: str | None = None
    table: _Table | None = None
    tree: tuple[int, int, list[tuple[int, tuple[int, ...]]]] | None = None
    colors: list[ColorEntry] | None = None
    names: list[StateName] | None = None
    icons: Icons | None = None
    seen: set[str] = set()
    for section in sections:
        kind = section.name
        slot = "FUNCTION" if kind in ("TABLE", "TREE") else kind
        if slot in seen or kind not in ("RULE", "TABLE", "TREE", "COLORS", "NAMES", "ICONS"):
            continue
        seen.add(slot)
        if kind == "RULE":
            name = _rule_name(section)
            description = _description(section)
        elif kind == "TABLE":
            source, table = "table", _parse_table(section)
        elif kind == "TREE":
            source, tree = "tree", _parse_tree(section)
        elif kind == "COLORS":
            colors = _parse_colors(section)
        elif kind == "NAMES":
            names = _parse_names(section)
        else:
            icons = _parse_icons(section)
    neighborhood: str | None = None
    symmetries: str | None = None
    if table is not None:
        neighbors, built, root = _compile(table)
        nodes = canonical_tree(built, root)
        states = table.states
        neighborhood, symmetries = table.neighborhood, table.symmetries
    elif tree is not None:
        states, neighbors, raw_nodes = tree
        nodes = canonical_tree(raw_nodes, len(raw_nodes) - 1)
    else:
        raise RuleFileError("no '@TABLE' or '@TREE' section", None)
    assert source is not None
    kept_colors = tuple(
        entry for entry in colors or () if isinstance(entry, Gradient) or entry.state < states
    )
    kept_names = tuple(entry for entry in names or () if entry.state < states)
    return RuleTable(
        name=name,
        states=states,
        neighbors=neighbors,
        nodes=nodes,
        neighborhood=neighborhood,
        symmetries=symmetries,
        source=source,
        description=description,
        colors=kept_colors,
        names=kept_names,
        icons=icons,
        text=text,
    )


def try_parse_rule_file(text: str) -> tuple[RuleTable, None] | tuple[None, RuleFileError]:
    """``parse_rule_file`` without raising: ``(rule, None)``, or ``(None, error)`` with the
    error's ``reason`` and ``line``."""
    try:
        return parse_rule_file(text), None
    except RuleFileError as error:
        return None, error


_OFFSETS: Final[dict[str, tuple[int, int]]] = {
    "nw": (0, 0), "n": (0, 1), "ne": (0, 2),
    "w": (1, 0), "c": (1, 1), "e": (1, 2),
    "sw": (2, 0), "s": (2, 1), "se": (2, 2),
}  # fmt: skip


def block_cells(
    halo: NDArray[np.uint8], height: int, width: int
) -> Iterator[tuple[str, NDArray[np.uint8]]]:
    """The nine views of a radius-1 halo, one per cell of the block, named as the block
    names them: each ``height`` × ``width``, the cell at that offset from every grid cell."""
    for name in _BLOCK:
        dy, dx = _OFFSETS[name]
        yield name, halo[dy : dy + height, dx : dx + width]
