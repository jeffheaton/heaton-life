"""Macrocell (``.mc``) files — HashLife's native file format (spec/macrocell.md).

A Macrocell file lists a pattern's distinct quadtree nodes, children before parents, so a
regular pattern of trillions of cells fits in a few lines. Reading covers two-state files
(two-state leaves, the multistate syntax with states 0 and 1, gzip); writing is canonical,
so two conforming ports write the same bytes for the same cells.
"""

from __future__ import annotations

import dataclasses
import itertools
from collections.abc import Sequence
from typing import Protocol

from heaton_life.ca.hashlife.leaves import SQUARE4, compose
from heaton_life.ca.hashlife.store import NodeStore
from heaton_life.ca.hashlife.universe import (
    DEFAULT_MEMORY_MB,
    MAX_LEVEL,
    HashLife,
    Snapshot,
    _hashlife_rule,
)
from heaton_life.core.decimal_text import digits_of, int_of_digits
from heaton_life.init.metadata import (
    MetadataReader,
    PatternMetadata,
    inflate,
    metadata_lines,
    text_from_bytes,
)

HEADER = "[M2] (heaton-life)"
STEP_LIMIT = 1 << 4096
"""A timeline's step is below 2^4096 (spec/macrocell.md "Timelines")."""
_TO_BITS = str.maketrans(".*", "01")
_TO_CELLS = str.maketrans("01", ".*")


def _text(source: str | bytes) -> str:
    """Gzip inflated, then UTF-8 or Latin-1 (spec/formats.md "Bytes and text")."""
    if isinstance(source, bytes):
        return text_from_bytes(inflate(source))
    return source


def _digits(text: str) -> bool:
    """One or more ASCII digits: no sign, no underscores, no other scripts' digits."""
    return text.isascii() and text.isdigit()


def _leaf_bits(line: str, number: int) -> int:
    rows = line.split("$")
    if len(rows) > 9 or (len(rows) == 9 and rows[8]):
        raise ValueError(f"line {number}: a leaf has at most 8 rows")
    bits = 0
    for r, row in enumerate(rows):
        if not row:
            continue
        if len(row) > 8 or row.strip(".*"):
            raise ValueError(f"line {number}: leaf rows hold at most 8 of '.' and '*'")
        bits |= int(row.translate(_TO_BITS)[::-1], 2) << (8 * r)
    return bits


def _leaf_line(bits: int) -> str:
    rows = [
        format((bits >> (8 * r)) & 0xFF, "08b")[::-1].rstrip("0").translate(_TO_CELLS)
        for r in range(8)
    ]
    while rows and not rows[-1]:
        rows.pop()
    return "".join(f"{row}$" for row in rows) or "$"


def read_macrocell(source: str | bytes, *, max_memory_mb: int = DEFAULT_MEMORY_MB) -> HashLife:
    """Build a universe from Macrocell text or bytes (gzip-compressed bytes are fine).

    The root is placed by tree coordinates: a level-k root covers x in [−2^(k−1), 2^(k−1) − 1]
    and y in [−2^(k−1) + 1, 2^(k−1)]. ``#R`` sets the rule, ``#G`` the generation; other
    ``#`` lines (comments, timeline frames) are skipped.
    """
    return _parse(source, max_memory_mb).universe


def read_macrocell_with_metadata(
    source: str | bytes, *, max_memory_mb: int = DEFAULT_MEMORY_MB
) -> tuple[HashLife, PatternMetadata]:
    """``read_macrocell`` and the file's ``#N``, ``#O`` and ``#C`` lines (spec/macrocell.md
    "Metadata")."""
    parsed = _parse(source, max_memory_mb)
    return parsed.universe, parsed.metadata


@dataclasses.dataclass
class _Parsed:
    """A Macrocell file read once: the universe at its root and ``#G``, its metadata, every
    node line as (value, level), and the timeline lines left for ``read_timeline``."""

    universe: HashLife
    metadata: PatternMetadata
    nodes: list[tuple[int, int]]
    frames_lines: list[tuple[int, str]]
    frame_lines: list[tuple[int, str]]


def _root(store: NodeStore, value: int, level: int) -> tuple[int, int]:
    """A node line as a root of level ≥ 4, placed by tree coordinates: a 2 × 2 or 4 × 4
    square is centered in a leaf, and a leaf is the center of a level-4 root."""
    if level < 3:
        value = store.leaf(value << (27 if level == 1 else 18))
        level = 3
    if level == 3:
        b = store.data[value]
        value = store.join(
            store.leaf(compose(0, 0, 0, b & SQUARE4)),
            store.leaf(compose(0, 0, (b >> 4) & SQUARE4, 0)),
            store.leaf(compose(0, (b >> 32) & SQUARE4, 0, 0)),
            store.leaf(compose((b >> 36) & SQUARE4, 0, 0, 0)),
        )
        level = 4
    return value, level


class _Nodes(Protocol):
    """Where a file's nodes of level 3 and up go, as ids: a universe's store, or the boxes a
    measure keeps. (Levels 1 and 2 are spread bitmaps in the leaf layout, made here.)"""

    def leaf(self, bits: int) -> int:
        """A level-3 node from its 8 × 8 bitmap (bit 8r + c is row r, column c)."""
        ...

    def empty(self, level: int) -> int: ...

    def join(self, nw: int, ne: int, sw: int, se: int, level: int) -> int: ...

    def rule(self, text: str) -> None:
        """An ``#R`` line's rule; raises ValueError for one the universe can't run."""
        ...


@dataclasses.dataclass
class _Lines:
    """A file's lines read once: every node line as (value, level), ``#G``, the metadata,
    and the timeline lines left for ``read_timeline``."""

    nodes: list[tuple[int, int]]
    generation: int
    metadata: PatternMetadata
    frames_lines: list[tuple[int, str]]
    frame_lines: list[tuple[int, str]]


def _lines(source: str | bytes) -> tuple[list[str], int]:
    """The file's lines and the index of its ``[M2]`` header, checked."""
    lines = _text(source).splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip()), len(lines))
    if start == len(lines) or not lines[start].strip().startswith("[M2]"):
        raise ValueError("not a Macrocell file: the first line must start with [M2]")
    return lines, start


def _read_lines(lines: list[str], start: int, tree: _Nodes) -> _Lines:
    """Every line after the header, checked, its nodes built in ``tree`` (spec/macrocell.md
    "Reading"): the one reading of the format, for a universe and for a measure alike."""
    generation = 0
    notes = MetadataReader()
    frames_lines: list[tuple[int, str]] = []
    frame_lines: list[tuple[int, str]] = []
    # Each node as (value, level): a tree id for level ≥ 3, a spread bitmap below.
    nodes: list[tuple[int, int]] = []

    def child(index: int, level: int, number: int) -> int:
        if index == 0:
            return tree.empty(level) if level >= 3 else 0
        if not 0 < index <= len(nodes):
            raise ValueError(f"line {number}: node {index} is not defined yet")
        value, found = nodes[index - 1]
        if found != level:
            raise ValueError(f"line {number}: node {index} has level {found}, not {level}")
        return value

    for number, raw in enumerate(lines[start + 1 :], start=start + 2):
        line = raw.strip()
        if not line:
            continue
        if line[0] == "#":
            if line.startswith("#R"):
                tree.rule(line[2:].strip())
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
            nodes.append((tree.leaf(_leaf_bits(line, number)), 3))
            continue
        fields = line.split()
        if len(fields) != 5 or not all(_digits(f) for f in fields):
            raise ValueError(f"line {number}: expected a leaf or 'level nw ne sw se'")
        level, nw, ne, sw, se = (int(f) for f in fields)
        if level > MAX_LEVEL:
            raise ValueError(
                f"line {number}: level {level} is past the deepest tree, level {MAX_LEVEL} "
                '(spec/hashlife.md "Depth")'
            )
        if level == 1:
            if max(nw, ne, sw, se) > 1:
                raise ValueError(f"line {number}: HashLife cells are 0 or 1")
            nodes.append((nw | ne << 1 | sw << 8 | se << 9, 1))
        elif level == 2:
            q = [child(i, 1, number) for i in (nw, ne, sw, se)]
            nodes.append((q[0] | q[1] << 2 | q[2] << 16 | q[3] << 18, 2))
        elif level == 3:
            q = [child(i, 2, number) for i in (nw, ne, sw, se)]
            nodes.append((tree.leaf(compose(*q)), 3))
        elif level >= 4:
            kids = [child(i, level - 1, number) for i in (nw, ne, sw, se)]
            nodes.append((tree.join(kids[0], kids[1], kids[2], kids[3], level), level))
        else:
            raise ValueError(f"line {number}: level must be at least 1")
    if not nodes:
        raise ValueError("Macrocell file has no nodes")
    return _Lines(nodes, generation, notes.result(), frames_lines, frame_lines)


class _StoreNodes:
    """A file's nodes in a universe's store, its ``#R`` the universe's rule."""

    def __init__(self, universe: HashLife) -> None:
        self._universe = universe
        self._store = universe._store

    def leaf(self, bits: int) -> int:
        return self._store.leaf(bits)

    def empty(self, level: int) -> int:
        return self._store.empty(level)

    def join(self, nw: int, ne: int, sw: int, se: int, level: int) -> int:
        return self._store.join(nw, ne, sw, se)

    def rule(self, text: str) -> None:
        self._universe.rule = _hashlife_rule(text, presets=False)  # a file names no preset


def _parse(source: str | bytes, max_memory_mb: int) -> _Parsed:
    lines, start = _lines(source)
    universe = HashLife(max_memory_mb=max_memory_mb)
    read = _read_lines(lines, start, _StoreNodes(universe))
    universe._adopt(*_root(universe._store, *read.nodes[-1]), read.generation)
    return _Parsed(universe, read.metadata, read.nodes, read.frames_lines, read.frame_lines)


Box = tuple[int, int, int, int]
"""An inclusive box (x0, y0, x1, y1)."""


def _bits_box(bits: int) -> Box | None:
    """The live cells' box in a leaf-layout bitmap (bit 8r + c is row r, column c)."""
    if not bits:
        return None
    rows = [r for r in range(8) if (bits >> (8 * r)) & 0xFF]
    columns = 0
    for r in rows:
        columns |= (bits >> (8 * r)) & 0xFF
    return (columns & -columns).bit_length() - 1, rows[0], columns.bit_length() - 1, rows[-1]


class _BoxNodes:
    """A file's nodes as their live cells' boxes, each relative to its node's top-left
    corner; id 0 is every empty node. No universe is built (spec/formats.md "Measuring")."""

    def __init__(self) -> None:
        self.boxes: list[Box | None] = [None]
        self.canonical = "B3/S23"

    def leaf(self, bits: int) -> int:
        self.boxes.append(_bits_box(bits))
        return len(self.boxes) - 1

    def empty(self, level: int) -> int:
        return 0

    def join(self, nw: int, ne: int, sw: int, se: int, level: int) -> int:
        half = 1 << (level - 1)
        box: Box | None = None
        for node, dx, dy in ((nw, 0, 0), (ne, half, 0), (sw, 0, half), (se, half, half)):
            part = self.boxes[node]
            if part is None:
                continue
            x0, y0, x1, y1 = part[0] + dx, part[1] + dy, part[2] + dx, part[3] + dy
            if box is not None:
                x0, y0 = min(x0, box[0]), min(y0, box[1])
                x1, y1 = max(x1, box[2]), max(y1, box[3])
            box = (x0, y0, x1, y1)
        self.boxes.append(box)
        return len(self.boxes) - 1

    def rule(self, text: str) -> None:
        self.canonical = _hashlife_rule(text, presets=False)


def measure_macrocell(source: str | bytes) -> tuple[Box | None, str, int, PatternMetadata]:
    """A Macrocell file's live cells' bounding box (or None without any) in the universe's
    coordinates, its rule in canonical form, its generation and its metadata, read from its
    tree without building a universe (spec/formats.md "Measuring"). Refuses what reading
    refuses, but has no memory budget to run out of."""
    lines, start = _lines(source)
    tree = _BoxNodes()
    read = _read_lines(lines, start, tree)
    value, level = read.nodes[-1]
    box = tree.boxes[value] if level >= 3 else _bits_box(value)
    if box is None:
        return None, tree.canonical, read.generation, read.metadata
    # A level-k root covers x in [-2^(k-1), 2^(k-1) - 1] and y in [-2^(k-1) + 1, 2^(k-1)].
    left = -(1 << (level - 1))
    top = left + 1
    x0, y0, x1, y1 = box
    return (
        (left + x0, top + y0, left + x1, top + y1),
        tree.canonical,
        read.generation,
        read.metadata,
    )


def write_macrocell(universe: HashLife, metadata: PatternMetadata | None = None) -> str:
    """The canonical Macrocell text of the universe (spec/macrocell.md "Writing"), with
    ``metadata``'s lines after ``#R`` and ``#G`` when given."""
    lines = [HEADER, f"#R {universe.rule}"]
    if universe.generation:
        lines.append(f"#G {digits_of(universe.generation)}")
    lines += metadata_lines(metadata)
    nodes: list[str] = []
    _write_tree(universe._store, *universe._minimal(), nodes, {})
    return "\n".join(lines + nodes) + "\n"


def _write_tree(
    store: NodeStore, root: int, level: int, nodes: list[str], index: dict[int, int]
) -> int:
    """Append the node lines of the tree (root, level ≥ 3) not written yet — post-order,
    children NW, NE, SW, SE, each node once — and return the root's line number. ``index``
    maps each written node to its line; an empty child is ``0`` and never gets a line, but
    an empty root does."""
    data = store.data
    if root in index:
        return index[root]
    if level == 3:
        nodes.append(_leaf_line(data[root]))
        index[root] = len(nodes)
        return len(nodes)
    stack = [(root, level, False)]
    while stack:
        n, k, ready = stack.pop()
        if n in index:
            continue
        if k == 3:
            nodes.append(_leaf_line(data[n]))
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
class MacrocellTimeline:
    """A timeline file's frames: snapshots of one universe that holds every frame's nodes.
    ``universe`` is left at the file's own root and ``#G``; ``frames[i]`` is the universe
    at generation ``frames[0].generation + i * step``."""

    universe: HashLife
    frames: tuple[Snapshot, ...]
    step: int
    metadata: PatternMetadata


def _number(text: str, number: int, what: str) -> int:
    if not _digits(text):
        raise ValueError(f"line {number}: {what} must be ASCII digits, got {text!r}")
    return int_of_digits(text)


def _step(text: str, number: int) -> int:
    """``<digits>`` or ``<b>^<e>``, at least 1 and below 2^4096; a power is measured before
    it is computed."""
    if "^" in text:
        base_text, _, exponent_text = text.partition("^")
        base = _number(base_text, number, "a step's base")
        exponent = _number(exponent_text, number, "a step's exponent")
        if exponent == 0 or base == 1:
            step = 1
        elif base == 0:
            step = 0
        elif (base.bit_length() - 1) * exponent >= 4096:
            raise ValueError(f"line {number}: the step {text} is not below 2^4096")
        else:
            step = base**exponent
    else:
        step = _number(text, number, "the step")
    if not 0 < step < STEP_LIMIT:
        raise ValueError(f"line {number}: the step must be at least 1 and below 2^4096")
    return step


def read_timeline(
    source: str | bytes, *, max_memory_mb: int = DEFAULT_MEMORY_MB
) -> MacrocellTimeline:
    """A timeline file's frames (spec/macrocell.md "Timelines"): one ``#FRAMES count first
    step`` line and a ``#FRAME i n`` line for every frame; anything else is an error."""
    parsed = _parse(source, max_memory_mb)
    if not parsed.frames_lines:
        raise ValueError("not a timeline: the file has no #FRAMES line")
    if len(parsed.frames_lines) > 1:
        raise ValueError(f"line {parsed.frames_lines[1][0]}: a second #FRAMES line")
    number, line = parsed.frames_lines[0]
    fields = line[len("#FRAMES") :].split()
    if len(fields) != 3:
        raise ValueError(f"line {number}: expected '#FRAMES count first step'")
    count = _number(fields[0], number, "the frame count")
    first = _number(fields[1], number, "the first generation")
    step = _step(fields[2], number)
    if count == 0:
        raise ValueError(f"line {number}: a timeline has at least one frame")
    refs: dict[int, int] = {}
    for number, line in parsed.frame_lines:
        fields = line[len("#FRAME") :].split()
        if len(fields) != 2:
            raise ValueError(f"line {number}: expected '#FRAME index node'")
        index = _number(fields[0], number, "a frame index")
        node = _number(fields[1], number, "a frame's node")
        if index >= count:
            raise ValueError(f"line {number}: frame {index} is past the {count} frames")
        if index in refs:
            raise ValueError(f"line {number}: frame {index} is given twice")
        if not 0 < node <= len(parsed.nodes):
            raise ValueError(f"line {number}: the file has no node {node}")
        refs[index] = node
    if len(refs) != count:
        missing = next(i for i in range(count) if i not in refs)
        raise ValueError(f"the timeline has no #FRAME line for frame {missing}")
    universe = parsed.universe
    store = universe._store
    frames = tuple(
        universe._snapshot_at(*_root(store, *parsed.nodes[refs[i] - 1]), first + i * step)
        for i in range(count)
    )
    return MacrocellTimeline(universe, frames, step, parsed.metadata)


def _root_of(n: int, e: int) -> int:
    """floor(n^(1/e)) for n ≥ 1, e ≥ 1, by Newton's method from above."""
    x = 1 << -(-n.bit_length() // e)
    while True:
        y = ((e - 1) * x + n // x ** (e - 1)) // e
        if y >= x:
            return x
        x = y


def _power(step: int) -> tuple[int, int]:
    """(b, e) with step = b^e and b the smallest integer of at least 2 that works."""
    if step == 1:
        return 2, 0
    for exponent in range(step.bit_length() - 1, 1, -1):
        base = _root_of(step, exponent)
        if base**exponent == step:
            return base, exponent
    return step, 1


def write_timeline(
    universe: HashLife,
    frames: Sequence[Snapshot],
    *,
    metadata: PatternMetadata | None = None,
) -> str:
    """The canonical timeline file of ``frames``, snapshots of ``universe`` at evenly spaced
    generations (spec/macrocell.md "Timelines", "Writing"). The file's own root and ``#G``
    are the last frame's."""
    frames = list(frames)
    if not frames:
        raise ValueError("a timeline needs at least one frame")
    if any(frame._owner() is not universe for frame in frames):
        raise ValueError("every frame must be a snapshot of the universe being written")
    generations = [frame.generation for frame in frames]
    step = generations[1] - generations[0] if len(frames) > 1 else 1
    if any(b - a != step for a, b in itertools.pairwise(generations)):
        raise ValueError("a timeline's frames are evenly spaced in generations")
    if not 0 < step < STEP_LIMIT:
        raise ValueError(f"a timeline's step is at least 1 and below 2^4096, not {step}")
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
        _write_tree(store, *universe._minimal_of(frame._root, frame._level), nodes, index)
        for frame in frames
    ]
    if roots[-1] != len(nodes):  # a reader without timelines loads the last frame
        nodes.append(nodes[roots[-1] - 1])
    frame_lines = [f"#FRAME {i} {root}" for i, root in enumerate(roots)]
    return "\n".join(lines + nodes + frame_lines) + "\n"
