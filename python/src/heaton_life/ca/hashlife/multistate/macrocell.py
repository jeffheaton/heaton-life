"""Multi-state Macrocell files (spec/macrocell.md "Multi-state files").

The format of the two-state universe, with leaves of four states: ``1 <nw> <ne> <sw> <se>``
lines are 2 × 2 squares of states, higher levels name their children by line number, and
``0`` is a square of 0 cells. Reading also takes the two-state leaf lines, as states 0 and
1. Writing is canonical, so two conforming ports write the same bytes for the same cells;
timelines read into snapshots and are written from them, as for two states.
"""

from __future__ import annotations

import dataclasses
import itertools
from collections.abc import Sequence
from typing import Protocol

from heaton_life.ca.hashlife.macrocell import (
    HEADER,
    STEP_LIMIT,
    _bits_box,
    _digits,
    _leaf_bits,
    _lines,
    _number,
    _power,
    _step,
)
from heaton_life.ca.hashlife.multistate.store import StateStore, pack, unpack
from heaton_life.ca.hashlife.multistate.universe import MultiStateHashLife
from heaton_life.ca.hashlife.universe import DEFAULT_MEMORY_MB, MAX_LEVEL, Snapshot
from heaton_life.ca.state_rules import (
    MAX_STATES,
    StateRule,
    check_state_rule,
    names_rule,
    resolve_rule,
    state_rule,
)
from heaton_life.core.decimal_text import digits_of, int_of_digits
from heaton_life.init.metadata import MetadataReader, PatternMetadata, metadata_lines

DEFAULT_RULE = "WireWorld"
"""The rule a file that names none is read under, unless the reader is given another."""


def file_rule(text: str, given: StateRule) -> StateRule:
    """The rule a file names (spec/hashlife-multistate.md "Pattern I/O"): ``given`` when the
    name is its canonical name, ignoring ASCII case, else the rule of that name."""
    if names_rule(text, given):
        return check_state_rule(given)
    return check_state_rule(state_rule(text))


def fallback_rule(rule: str | StateRule | None) -> StateRule:
    """The rule a reader gives a file that names none."""
    return resolve_rule(DEFAULT_RULE if rule is None else rule)


def _bits_node(store: StateStore, bits: int) -> int:
    """A two-state 8 × 8 leaf (bit 8r + c is row r, column c) as a level-3 node of states."""
    quads = []
    for qy in (0, 4):
        for qx in (0, 4):
            leaves = []
            for ly in (0, 2):
                for lx in (0, 2):
                    x, y = qx + lx, qy + ly
                    leaves.append(
                        store.leaf(
                            pack(
                                bits >> (8 * y + x) & 1,
                                bits >> (8 * y + x + 1) & 1,
                                bits >> (8 * y + x + 8) & 1,
                                bits >> (8 * y + x + 9) & 1,
                            )
                        )
                    )
            quads.append(store.join(*leaves))
    return store.join(*quads)


Box = tuple[int, int, int, int]
"""(x0, y0, x1, y1), inclusive."""


@dataclasses.dataclass
class Built:
    """A Macrocell file's tree built in a universe's store, which it hasn't become: the
    root as (node, level ≥ 2), ``#G``, the rule, the metadata, every node line as (node,
    level), the timeline lines, and whether the file named its rule."""

    root: int
    level: int
    generation: int
    rule: StateRule
    metadata: PatternMetadata
    nodes: list[tuple[int, int]]
    frames_lines: list[tuple[int, str]]
    frame_lines: list[tuple[int, str]]
    rule_named: bool = True


def place(universe: MultiStateHashLife, node: int, level: int) -> tuple[int, int]:
    """A node line as a root of level ≥ 2, placed by tree coordinates: a lone leaf is the
    center of a level-2 root."""
    if level == 1:
        return universe._grow(node, 1), 2
    return node, level


class _Nodes(Protocol):
    """Where a file's node lines go, as ids: a universe's store, or the boxes a measure
    keeps."""

    def bits(self, bits: int) -> int:
        """A two-state 8 × 8 leaf (bit 8r + c is row r, column c), a level-3 node."""

    def leaf(self, nw: int, ne: int, sw: int, se: int) -> int:
        """A level-1 leaf of four states."""

    def empty(self, level: int) -> int: ...

    def join(self, nw: int, ne: int, sw: int, se: int, level: int) -> int: ...


class _StoreNodes:
    """A file's nodes in a universe's store."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    def bits(self, bits: int) -> int:
        return _bits_node(self._store, bits)

    def leaf(self, nw: int, ne: int, sw: int, se: int) -> int:
        return self._store.leaf(pack(nw, ne, sw, se))

    def empty(self, level: int) -> int:
        return self._store.empty(level)

    def join(self, nw: int, ne: int, sw: int, se: int, level: int) -> int:
        return self._store.join(nw, ne, sw, se)


class _BoxNodes:
    """A file's nodes as their non-zero cells' boxes, each relative to its node's top-left
    corner; id 0 is every empty node. No universe is built (spec/hashlife-multistate.md
    "Measuring")."""

    def __init__(self) -> None:
        self.boxes: list[Box | None] = [None]

    def _add(self, box: Box | None) -> int:
        self.boxes.append(box)
        return len(self.boxes) - 1

    def bits(self, bits: int) -> int:
        return self._add(_bits_box(bits))

    def leaf(self, nw: int, ne: int, sw: int, se: int) -> int:
        xs = [x for x, state in ((0, nw), (1, ne), (0, sw), (1, se)) if state]
        ys = [y for y, state in ((0, nw), (0, ne), (1, sw), (1, se)) if state]
        return self._add((min(xs), min(ys), max(xs), max(ys)) if xs else None)

    def empty(self, level: int) -> int:
        return 0

    def join(self, nw: int, ne: int, sw: int, se: int, level: int) -> int:
        half = 1 << (level - 1)
        box: Box | None = None
        for child, dx, dy in ((nw, 0, 0), (ne, half, 0), (sw, 0, half), (se, half, half)):
            part = self.boxes[child]
            if part is None:
                continue
            x0, y0, x1, y1 = part[0] + dx, part[1] + dy, part[2] + dx, part[3] + dy
            box = (
                (x0, y0, x1, y1)
                if box is None
                else (min(box[0], x0), min(box[1], y0), max(box[2], x1), max(box[3], y1))
            )
        return self._add(box)


@dataclasses.dataclass
class _Scanned:
    """A Macrocell file's lines read into a node sink: the rule it names (or None), ``#G``,
    the metadata, every node line as (id, level), the timeline lines, the largest state,
    whether every leaf is a two-state 8 × 8 line, and the text of a rule file appended to
    it (or None)."""

    named: str | None
    generation: int
    metadata: PatternMetadata
    nodes: list[tuple[int, int]]
    frames_lines: list[tuple[int, str]]
    frame_lines: list[tuple[int, str]]
    top: int
    two_state: bool
    rule_text: str | None


def _scan(source: str | bytes, sink: _Nodes) -> _Scanned:
    """Read a Macrocell file's lines into ``sink``. Raises ValueError for a malformed file."""
    lines, start = _lines(source)
    generation = 0
    named: str | None = None
    notes = MetadataReader()
    frames_lines: list[tuple[int, str]] = []
    frame_lines: list[tuple[int, str]] = []
    nodes: list[tuple[int, int]] = []
    top = 0  # the largest state seen
    two_state = True

    def child(index: int, level: int, number: int) -> int:
        if index == 0:
            return sink.empty(level)
        if not 0 < index <= len(nodes):
            raise ValueError(f"line {number}: node {index} is not defined yet")
        node, found = nodes[index - 1]
        if found != level:
            raise ValueError(f"line {number}: node {index} has level {found}, not {level}")
        return node

    rule_text: str | None = None
    for number, raw in enumerate(lines[start + 1 :], start=start + 2):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("@RULE"):  # a rule file appended to the pattern (spec/ruletable.md)
            rule_text = "\n".join(lines[number - 1 :])
            break
        if line[0] == "#":
            if line.startswith("#R"):
                named = line[2:].strip()
            elif line.startswith("#G"):
                value = line[2:].strip()
                if not _digits(value):
                    raise ValueError(
                        f"line {number}: #G needs a generation in digits, got {value!r}"
                    )
                generation = int_of_digits(value)
            elif line.startswith("#FRAMES"):
                frames_lines.append((number, line))
            elif line.startswith("#FRAME"):
                frame_lines.append((number, line))
            else:
                notes.hash_line(line)
            continue
        if line[0] in ".*$":
            bits = _leaf_bits(line, number)
            top = max(top, 1 if bits else 0)
            nodes.append((sink.bits(bits), 3))
            continue
        fields = line.split()
        if len(fields) != 5 or not all(_digits(f) for f in fields):
            raise ValueError(f"line {number}: expected a leaf or 'level nw ne sw se'")
        level = int(fields[0])
        if level > MAX_LEVEL:
            raise ValueError(
                f"line {number}: level {level} is past the deepest tree, level {MAX_LEVEL} "
                '(spec/hashlife.md "Depth")'
            )
        if level == 0:
            raise ValueError(f"line {number}: level must be at least 1")
        if level == 1:
            nw, ne, sw, se = (int(f) for f in fields[1:])
            if max(nw, ne, sw, se) >= MAX_STATES:
                raise ValueError(f"line {number}: a state is at most {MAX_STATES - 1}")
            top = max(top, nw, ne, sw, se)
            two_state = False
            nodes.append((sink.leaf(nw, ne, sw, se), 1))
        else:
            nw, ne, sw, se = (child(int(f), level - 1, number) for f in fields[1:])
            nodes.append((sink.join(nw, ne, sw, se, level), level))
    if not nodes:
        raise ValueError("Macrocell file has no nodes")
    return _Scanned(
        named,
        generation,
        notes.result(),
        nodes,
        frames_lines,
        frame_lines,
        top,
        two_state,
        rule_text,
    )


def _named_rule(name: str, given: StateRule, rule_text: str | None) -> StateRule:
    """The rule ``#R`` names: ``given`` when the name is its canonical name, else a rule file
    appended to the pattern under that name (spec/ruletable.md "Files"), else the rule of
    that name; as an RLE header's rule is found."""
    if names_rule(name, given) or rule_text is None:
        return file_rule(name, given)
    # Imported here: heaton_life.ca, the rule-table module's package, imports this one.
    from heaton_life.ca.rulefile import parse_rule_file

    appended = parse_rule_file(rule_text)
    if names_rule(name, appended):
        return check_state_rule(appended)
    return file_rule(name, given)


def _checked_rule(scanned: _Scanned, fallback: StateRule) -> StateRule:
    """The rule a scanned file runs under: the one it names, else ``fallback``; a state
    the rule lacks is refused."""
    if scanned.named is None:
        rule = fallback
    else:
        rule = _named_rule(scanned.named, fallback, scanned.rule_text)
    if scanned.top >= rule.states:
        raise ValueError(
            f"the file holds state {scanned.top}, which {rule.canonical} doesn't have "
            f"({rule.states} states)"
        )
    return rule


def build_macrocell(
    universe: MultiStateHashLife, source: str | bytes, fallback: StateRule
) -> Built:
    """Read a Macrocell file into ``universe``'s store without changing the universe: its
    root, level, generation and rule stay. ``fallback`` is the rule when the file names
    none. Raises ValueError for a malformed file, or a state the rule lacks."""
    scanned = _scan(source, _StoreNodes(universe._store))
    rule = _checked_rule(scanned, fallback)
    root, level = place(universe, *scanned.nodes[-1])
    return Built(
        root,
        level,
        scanned.generation,
        rule,
        scanned.metadata,
        scanned.nodes,
        scanned.frames_lines,
        scanned.frame_lines,
        scanned.named is not None,
    )


@dataclasses.dataclass(frozen=True)
class MacrocellMeasure:
    """A multi-state Macrocell file measured without a universe (spec/hashlife-multistate.md
    "Measuring"): its non-zero cells' box in the universe's coordinates (None without any),
    the canonical name of the rule it names (None when it names none), ``#G``, the metadata,
    and whether every leaf is a two-state line."""

    box: Box | None
    rule: str | None
    generation: int
    metadata: PatternMetadata
    two_state: bool


def measure_macrocell(source: str | bytes, fallback: StateRule) -> MacrocellMeasure:
    """Measure a Macrocell file from its tree, without building a universe: what
    ``build_macrocell`` checks is checked (``fallback`` is the rule a file that names none
    is read under), but there is no memory budget to run out of."""
    sink = _BoxNodes()
    scanned = _scan(source, sink)
    rule = _checked_rule(scanned, fallback)
    named = None if scanned.named is None else rule.canonical
    node, level = scanned.nodes[-1]
    found = sink.boxes[node]
    if found is None:
        return MacrocellMeasure(
            None, named, scanned.generation, scanned.metadata, scanned.two_state
        )
    # A level-k root covers x in [-2^(k-1), 2^(k-1) - 1] and y in [-2^(k-1) + 1, 2^(k-1)]
    # (a lone leaf, the center of a level-2 root, covers x in {-1, 0} and y in {0, 1}).
    left = -(1 << (level - 1))
    top = left + 1
    x0, y0, x1, y1 = found
    box = (left + x0, top + y0, left + x1, top + y1)
    return MacrocellMeasure(box, named, scanned.generation, scanned.metadata, scanned.two_state)


def read_macrocell(
    source: str | bytes,
    *,
    rule: str | StateRule | None = None,
    max_memory_mb: int = DEFAULT_MEMORY_MB,
) -> MultiStateHashLife:
    """A multi-state universe from Macrocell text or bytes (gzip-compressed bytes too),
    placed by tree coordinates; ``rule`` is the rule when the file names none (default
    WireWorld). Timeline lines are skipped."""
    return read_macrocell_with_metadata(source, rule=rule, max_memory_mb=max_memory_mb)[0]


def read_macrocell_with_metadata(
    source: str | bytes,
    *,
    rule: str | StateRule | None = None,
    max_memory_mb: int = DEFAULT_MEMORY_MB,
) -> tuple[MultiStateHashLife, PatternMetadata]:
    """``read_macrocell`` and the file's ``#N``, ``#O`` and ``#C`` lines."""
    fallback = fallback_rule(rule)
    universe = MultiStateHashLife(fallback, max_memory_mb=max_memory_mb)
    built = build_macrocell(universe, source, fallback)
    universe.state_rule = built.rule
    universe._adopt(built.root, built.level, built.generation)
    return universe, built.metadata


def write_macrocell(universe: MultiStateHashLife, metadata: PatternMetadata | None = None) -> str:
    """The canonical Macrocell text of the universe (spec/macrocell.md "Multi-state
    files"), with ``metadata``'s lines after ``#R`` and ``#G`` when given."""
    lines = [HEADER, f"#R {universe.rule}"]
    if universe.generation:
        lines.append(f"#G {digits_of(universe.generation)}")
    lines += metadata_lines(metadata)
    nodes: list[str] = []
    write_tree(universe._store, *universe._minimal(), nodes, {})
    return "\n".join(lines + nodes) + "\n"


def write_tree(
    store: StateStore, root: int, level: int, nodes: list[str], index: dict[int, int]
) -> int:
    """Append the node lines of the tree (root, level ≥ 1) not written yet — post-order,
    children NW, NE, SW, SE, each node once — and return the root's line number. ``index``
    maps each written node to its line; an empty child is ``0`` and never gets a line, but
    an empty root does."""
    data = store.data
    if root in index:
        return index[root]
    stack = [(root, level, False)]
    while stack:
        n, k, ready = stack.pop()
        if n in index:
            continue
        if k == 1:
            nw, ne, sw, se = unpack(data[n])
            nodes.append(f"1 {nw} {ne} {sw} {se}")
            index[n] = len(nodes)
            continue
        a, b, c, d = data[n]
        e = store.empty(k - 1)
        if ready:
            ids = [0 if x == e else index[x] for x in (a, b, c, d)]
            nodes.append(f"{k} {ids[0]} {ids[1]} {ids[2]} {ids[3]}")
            index[n] = len(nodes)
        else:
            stack.append((n, k, True))
            stack.extend((x, k - 1, False) for x in (d, c, b, a) if x != e)
    return index[root]


# -- timelines (spec/macrocell.md "Timelines") ------------------------------------------------


@dataclasses.dataclass(frozen=True)
class MultiStateTimeline:
    """A timeline file's frames: snapshots of one multi-state universe that holds every
    frame's nodes. ``universe`` is left at the file's own root and ``#G``; ``frames[i]`` is
    the universe at generation ``frames[0].generation + i * step``."""

    universe: MultiStateHashLife
    frames: tuple[Snapshot, ...]
    step: int
    metadata: PatternMetadata


def timeline_frames(
    universe: MultiStateHashLife, built: Built
) -> tuple[int, list[tuple[int, int, int]]] | None:
    """A file's timeline: its step, and each frame's root as (node, level, generation) in
    order, placed in ``universe``'s store as a file's root is; or None for a file without a
    ``#FRAMES`` line. A malformed timeline raises ValueError."""
    if not built.frames_lines:
        return None
    if len(built.frames_lines) > 1:
        raise ValueError(f"line {built.frames_lines[1][0]}: a second #FRAMES line")
    number, line = built.frames_lines[0]
    fields = line[len("#FRAMES") :].split()
    if len(fields) != 3:
        raise ValueError(f"line {number}: expected '#FRAMES count first step'")
    count = _number(fields[0], number, "the frame count")
    first = _number(fields[1], number, "the first generation")
    step = _step(fields[2], number)
    if count == 0:
        raise ValueError(f"line {number}: a timeline has at least one frame")
    refs: dict[int, int] = {}
    for number, line in built.frame_lines:
        fields = line[len("#FRAME") :].split()
        if len(fields) != 2:
            raise ValueError(f"line {number}: expected '#FRAME index node'")
        index = _number(fields[0], number, "a frame index")
        node = _number(fields[1], number, "a frame's node")
        if index >= count:
            raise ValueError(f"line {number}: frame {index} is past the {count} frames")
        if index in refs:
            raise ValueError(f"line {number}: frame {index} is given twice")
        if not 0 < node <= len(built.nodes):
            raise ValueError(f"line {number}: the file has no node {node}")
        refs[index] = node
    if len(refs) != count:
        missing = next(i for i in range(count) if i not in refs)
        raise ValueError(f"the timeline has no #FRAME line for frame {missing}")
    roots = [(*place(universe, *built.nodes[refs[i] - 1]), first + i * step) for i in range(count)]
    return step, roots


def read_timeline(
    source: str | bytes,
    *,
    rule: str | StateRule | None = None,
    max_memory_mb: int = DEFAULT_MEMORY_MB,
) -> MultiStateTimeline:
    """A multi-state timeline file's frames (spec/macrocell.md "Timelines"): one
    ``#FRAMES count first step`` line and a ``#FRAME i n`` line for every frame."""
    fallback = fallback_rule(rule)
    universe = MultiStateHashLife(fallback, max_memory_mb=max_memory_mb)
    built = build_macrocell(universe, source, fallback)
    universe.state_rule = built.rule
    universe._adopt(built.root, built.level, built.generation)
    found = timeline_frames(universe, built)
    if found is None:
        raise ValueError("not a timeline: the file has no #FRAMES line")
    step, roots = found
    states = built.rule.states
    frames = tuple(universe._snapshot_at(*root, states) for root in roots)
    return MultiStateTimeline(universe, frames, step, built.metadata)


def write_timeline(
    universe: MultiStateHashLife,
    frames: Sequence[Snapshot],
    *,
    metadata: PatternMetadata | None = None,
) -> str:
    """The canonical timeline file of ``frames``, snapshots of ``universe`` at evenly spaced
    generations (spec/macrocell.md "Timelines"). The file's own root and ``#G`` are the
    last frame's."""
    frames = list(frames)
    if not frames:
        raise ValueError("a timeline needs at least one frame")
    if any(frame._owner() is not universe for frame in frames):
        raise ValueError("every frame must be a snapshot of the universe being written")
    if any(frame.released for frame in frames):
        raise ValueError("a released snapshot holds no cells to write")
    generations = [frame.generation for frame in frames]
    step = generations[1] - generations[0] if len(frames) > 1 else 1
    if any(b - a != step for a, b in itertools.pairwise(generations)):
        raise ValueError("a timeline's frames are evenly spaced in generations")
    if not 0 < step < STEP_LIMIT:
        raise ValueError(f"a timeline's step is at least 1 and below 2^4096, not {step}")
    for frame in frames:
        universe._check_states(frame)  # the file names the universe's rule
    base, exponent = _power(step)
    lines = [HEADER, f"#R {universe.rule}"]
    if generations[-1]:
        lines.append(f"#G {digits_of(generations[-1])}")
    lines.append(f"#FRAMES {len(frames)} {digits_of(generations[0])} {base}^{exponent}")
    lines += metadata_lines(metadata)
    store = universe._store
    nodes: list[str] = []
    index: dict[int, int] = {}
    roots = [
        write_tree(store, *universe._minimal_of(frame._root, frame._level), nodes, index)
        for frame in frames
    ]
    if roots[-1] != len(nodes):  # a reader without timelines loads the last frame
        nodes.append(nodes[roots[-1] - 1])
    frame_lines = [f"#FRAME {i} {root}" for i, root in enumerate(roots)]
    return "\n".join(lines + nodes + frame_lines) + "\n"
