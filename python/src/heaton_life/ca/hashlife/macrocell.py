"""Macrocell (``.mc``) files — Golly's native HashLife format (spec/macrocell.md).

A Macrocell file lists a pattern's distinct quadtree nodes, children before parents, so a
regular pattern of trillions of cells fits in a few lines. Reading follows Golly's reader
(two-state leaves, the multistate syntax with states 0 and 1, gzip); writing is canonical,
so two conforming ports write the same bytes for the same cells.
"""

from __future__ import annotations

import gzip

from heaton_life.ca.hashlife.leaves import SQUARE4, compose
from heaton_life.ca.hashlife.universe import DEFAULT_MEMORY_MB, HashLife

HEADER = "[M2] (heaton-life)"
_TO_BITS = str.maketrans(".*", "01")
_TO_CELLS = str.maketrans("01", ".*")


def _text(source: str | bytes) -> str:
    if isinstance(source, bytes):
        if source[:2] == b"\x1f\x8b":
            source = gzip.decompress(source)
        return source.decode("latin-1")
    return source


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

    Golly's placement: a level-k root covers x in [−2^(k−1), 2^(k−1) − 1] and y in
    [−2^(k−1) + 1, 2^(k−1)]. ``#R`` sets the rule, ``#G`` the generation; other ``#``
    lines (comments, timeline frames) are skipped.
    """
    lines = _text(source).splitlines()
    if not lines or not lines[0].lstrip().startswith("[M2]"):
        raise ValueError("not a Macrocell file: the first line must start with [M2]")
    universe = HashLife(max_memory_mb=max_memory_mb)
    store = universe._store
    generation = 0
    # Each node as (value, level): a store id for level ≥ 3, a spread bitmap below.
    nodes: list[tuple[int, int]] = []

    def child(index: int, level: int, number: int) -> int:
        if index == 0:
            return store.empty(level) if level >= 3 else 0
        if not 0 < index <= len(nodes):
            raise ValueError(f"line {number}: node {index} is not defined yet")
        value, found = nodes[index - 1]
        if found != level:
            raise ValueError(f"line {number}: node {index} has level {found}, not {level}")
        return value

    for number, raw in enumerate(lines[1:], start=2):
        line = raw.strip()
        if not line:
            continue
        if line[0] == "#":
            if line.startswith("#R"):
                universe.rule = line[2:].strip()
            elif line.startswith("#G"):
                generation = int(line[2:].strip())
            continue
        if line[0] in ".*$":
            nodes.append((store.leaf(_leaf_bits(line, number)), 3))
            continue
        fields = line.split()
        if len(fields) != 5 or not all(f.isdigit() for f in fields):
            raise ValueError(f"line {number}: expected a leaf or 'level nw ne sw se'")
        level, nw, ne, sw, se = (int(f) for f in fields)
        if level == 1:
            if max(nw, ne, sw, se) > 1:
                raise ValueError(f"line {number}: HashLife cells are 0 or 1")
            nodes.append((nw | ne << 1 | sw << 8 | se << 9, 1))
        elif level == 2:
            q = [child(i, 1, number) for i in (nw, ne, sw, se)]
            nodes.append((q[0] | q[1] << 2 | q[2] << 16 | q[3] << 18, 2))
        elif level == 3:
            q = [child(i, 2, number) for i in (nw, ne, sw, se)]
            nodes.append((store.leaf(compose(*q)), 3))
        elif level >= 4:
            kids = [child(i, level - 1, number) for i in (nw, ne, sw, se)]
            nodes.append((store.join(*kids), level))
        else:
            raise ValueError(f"line {number}: level must be at least 1")
    if not nodes:
        raise ValueError("Macrocell file has no nodes")
    root, level = nodes[-1]
    if level < 3:  # a 2×2 or 4×4 root, centered in a leaf
        root = store.leaf(root << (27 if level == 1 else 18))
        level = 3
    if level == 3:  # a leaf root becomes the center of a level-4 root
        b = store.data[root]
        root = store.join(
            store.leaf(compose(0, 0, 0, b & SQUARE4)),
            store.leaf(compose(0, 0, (b >> 4) & SQUARE4, 0)),
            store.leaf(compose(0, (b >> 32) & SQUARE4, 0, 0)),
            store.leaf(compose((b >> 36) & SQUARE4, 0, 0, 0)),
        )
        level = 4
    universe._adopt(root, level, generation)
    return universe


def write_macrocell(universe: HashLife) -> str:
    """The canonical Macrocell text of the universe (spec/macrocell.md "Writing")."""
    store = universe._store
    data = store.data
    lines = [HEADER, f"#R {universe.rule}"]
    if universe.generation:
        lines.append(f"#G {universe.generation}")
    root, level = universe._minimal()
    if level == 3:
        lines.append(_leaf_line(data[root]))
        return "\n".join(lines) + "\n"
    index: dict[int, int] = {}
    stack = [(root, level, False)]
    while stack:
        n, k, ready = stack.pop()
        if n in index:
            continue
        if k == 3:
            lines.append(_leaf_line(data[n]))
            index[n] = len(index) + 1
            continue
        a, b, c, d = data[n]
        e = store.empty(k - 1)
        if ready:
            ids = [0 if x == e else index[x] for x in (a, b, c, d)]
            lines.append(f"{k} {ids[0]} {ids[1]} {ids[2]} {ids[3]}")
            index[n] = len(index) + 1
        else:
            stack.append((n, k, True))
            stack.extend((x, k - 1, False) for x in (d, c, b, a) if x != e)
    return "\n".join(lines) + "\n"
