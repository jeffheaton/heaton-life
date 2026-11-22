"""RLE for the unbounded multi-state universe (spec/hashlife-multistate.md "Pattern I/O",
spec/patterns.md "RLE in the unbounded universe").

Reading streams runs of states straight into quadtree leaves, so a file never becomes a
dense grid; ``#CXRLE Pos=x,y`` places the pattern (top-left at (0, 0) without it) and
``Gen=n`` sets the generation. Either dialect reads, its cells taken as the decoder gives
them. Writing encodes the bounding box's states with the canonical rules of ``rle_encode``
— the same tokens, line for line — behind a ``#CXRLE`` line, and refuses what only
Macrocell can carry: cells outside the editing box. A bounded grid's file is refused.
"""

from __future__ import annotations

from heaton_life.ca.hashlife.multistate.macrocell import fallback_rule, file_rule
from heaton_life.ca.hashlife.multistate.store import unpack
from heaton_life.ca.hashlife.multistate.universe import MultiStateHashLife
from heaton_life.ca.hashlife.universe import DEFAULT_MEMORY_MB, EDIT_LIMIT, check_box
from heaton_life.ca.state_rules import StateRule
from heaton_life.core.decimal_text import digits_of
from heaton_life.init.metadata import PatternMetadata, metadata_lines
from heaton_life.init.rle import rle_runs, state_tag

_LINE_WIDTH = 70


def read_rle(
    text: str,
    *,
    rule: str | StateRule | None = None,
    max_memory_mb: int = DEFAULT_MEMORY_MB,
) -> MultiStateHashLife:
    """A multi-state universe from RLE text; ``rule`` is the rule when the header names
    none (default WireWorld)."""
    fallback = fallback_rule(rule)
    universe = MultiStateHashLife(fallback, max_memory_mb=max_memory_mb)
    root, level, generation, found = build_rle(universe, text, fallback)
    universe.state_rule = found
    universe._adopt(root, level, generation)
    return universe


def build_rle(
    universe: MultiStateHashLife, text: str, fallback: StateRule
) -> tuple[int, int, int, StateRule]:
    """Read RLE text into ``universe``'s store without changing the universe: the pattern's
    tree as (root, level), its generation, and its rule (``fallback`` when the header names
    none)."""
    info, runs = rle_runs(text)
    if info.bounded_grid is not None:  # spec/patterns.md "RLE in the unbounded universe"
        raise ValueError(
            f"the unbounded universe has no bounded grid ('{info.bounded_grid.suffix}' "
            "in the rule): open the file in a grid world (spec/topology.md)"
        )
    rule = fallback if info.rule is None else file_rule(info.rule, fallback)
    x0, y0 = info.position or (0, 0)
    blocks: dict[tuple[int, int], int] = {}
    width = height = top = 0
    for x, y, length, state in runs:
        width = max(width, x + length)
        height = max(height, y + 1)
        top = max(top, state)
        # A cell outside the box dooms the file: refuse it now rather than spell out a run
        # that may be astronomically long.
        check_box(x0 + x, y0 + y, x0 + x + length - 1, y0 + y)
        add_run(blocks, x0 + x, y0 + y - 1, length, state)  # tree row: one above the cell's y
    if top >= rule.states:
        raise ValueError(
            f"the file holds state {top}, which {rule.canonical} doesn't have "
            f"({rule.states} states)"
        )
    rect = (x0, y0 - 1, x0 + width - 1, y0 + height - 2)
    if blocks:
        check_box(x0, y0, x0 + width - 1, y0 + height - 1)

    def paste() -> None:
        if blocks:
            universe._paste_blocks(blocks, rect, "or")

    root, level = universe._build(paste)
    return root, level, info.generation, rule


def add_run(blocks: dict[tuple[int, int], int], cx: int, ty: int, length: int, state: int) -> None:
    """Set ``length`` cells from tree position (cx, ty) rightward to ``state``, in the 2 × 2
    leaves ``blocks`` keeps by leaf position."""
    by, row = ty >> 1, (ty & 1) << 4
    for x in range(cx, cx + length):
        key = (x >> 1, by)
        blocks[key] = blocks.get(key, 0) | state << (row + ((x & 1) << 3))


def write_rle(universe: MultiStateHashLife, metadata: PatternMetadata | None = None) -> str:
    """The universe as RLE: ``#CXRLE Pos=x0,y0 [Gen=n]``, ``metadata``'s lines, then the
    canonical RLE of the bounding box."""
    notes = metadata_lines(metadata)
    gen = f" Gen={digits_of(universe.generation)}" if universe.generation else ""
    box = universe.bounding_box()
    if box is None:
        empty = [f"#CXRLE Pos=0,0{gen}", *notes, f"x = 0, y = 0, rule = {universe.rule}", "!"]
        return "\n".join(empty) + "\n"
    x0, y0, x1, y1 = box
    if max(abs(x0), abs(x1), abs(y0), abs(y1)) > EDIT_LIMIT:
        raise ValueError(
            f"the pattern ({x0}, {y0})..({x1}, {y1}) reaches outside the editing box "
            f"|x|, |y| <= {EDIT_LIMIT:,}; RLE can't carry it — save as Macrocell"
        )
    # Every row's runs of one state, built leaf by leaf in x order (leaves never overlap).
    rows: dict[int, list[list[int]]] = {}
    top = 0
    for tx, ty, packed in sorted(universe._leaves(), key=lambda leaf: (leaf[1], leaf[0])):
        cells = unpack(packed)
        for r in (0, 1):
            for c in (0, 1):
                state = cells[2 * r + c]
                if not state:
                    continue
                top = max(top, state)
                row = rows.setdefault(ty + r + 1, [])
                x = tx + c
                if row and row[-1][0] + row[-1][1] == x and row[-1][2] == state:
                    row[-1][1] += 1
                else:
                    row.append([x, 1, state])
    multistate = top > 1
    # Live rows only: the gap between two is one "k$" token (spec/patterns.md), so the
    # text grows with the live rows, not the box's height.
    tokens: list[str] = []
    prev = y0
    for y in sorted(rows):
        if y > y0:
            tokens.append(_run(y - prev, "$"))
        pos = x0
        for start, length, state in rows[y]:
            if start > pos:
                tokens.append(_run(start - pos, "." if multistate else "b"))
            tag = state_tag(state) if multistate else "o"
            tokens.append(_run(length, tag))
            pos = start + length
        prev = y
    tokens.append("!")
    body: list[str] = []
    line = ""
    for tok in tokens:
        if len(line) + len(tok) > _LINE_WIDTH:
            body.append(line)
            line = ""
        line += tok
    body.append(line)
    header = f"x = {x1 - x0 + 1}, y = {y1 - y0 + 1}, rule = {universe.rule}"
    first = f"#CXRLE Pos={x0},{y0}{gen}"
    return "\n".join([first, *notes, header, *body]) + "\n"


def _run(length: int, tag: str) -> str:
    return tag if length == 1 else f"{length}{tag}"
