"""RLE for the unbounded universe (spec/patterns.md "RLE in the unbounded universe").

Reading streams runs straight into quadtree leaves, so a file never becomes a dense grid;
``#CXRLE Pos=x,y`` places the pattern (top-left at (0, 0) without it) and ``Gen=n`` sets
the generation. Writing encodes the bounding box with the canonical rules of
``rle_encode`` — the same tokens, line for line — behind a ``#CXRLE`` line, and refuses a
pattern that reaches outside the editing box, which only Macrocell can carry.
"""

from __future__ import annotations

from heaton_life.ca.hashlife.universe import (
    DEFAULT_MEMORY_MB,
    EDIT_LIMIT,
    HashLife,
    check_box,
)
from heaton_life.init.rle import rle_runs

_LINE_WIDTH = 70


def _byte_runs(byte: int) -> tuple[tuple[int, int], ...]:
    runs: list[tuple[int, int]] = []
    x = 0
    while x < 8:
        if byte >> x & 1:
            start = x
            while x < 8 and byte >> x & 1:
                x += 1
            runs.append((start, x - start))
        else:
            x += 1
    return tuple(runs)


_RUNS = tuple(_byte_runs(b) for b in range(256))


def read_rle(text: str, *, max_memory_mb: int = DEFAULT_MEMORY_MB) -> HashLife:
    """Build a universe from two-state RLE text."""
    info, runs = rle_runs(text)
    if info.extended:
        raise ValueError("HashLife reads two-state RLE only (this file is extended RLE)")
    universe = HashLife(info.rule or "B3/S23", max_memory_mb=max_memory_mb)
    x0, y0 = info.position or (0, 0)
    blocks: dict[tuple[int, int], int] = {}
    width = height = 0
    for x, y, length, state in runs:
        if state != 1:
            raise ValueError(f"HashLife cells are 0 or 1, not {state}")
        width = max(width, x + length)
        height = max(height, y + 1)
        cx = x0 + x
        ty = y0 + y - 1  # tree row
        by, shift = ty >> 3, (ty & 7) * 8
        while length:
            bx, offset = cx >> 3, cx & 7
            take = min(8 - offset, length)
            blocks[bx, by] = blocks.get((bx, by), 0) | (((1 << take) - 1) << (offset + shift))
            cx += take
            length -= take
    if blocks:
        check_box(x0, y0, x0 + width - 1, y0 + height - 1)
        universe._paste_blocks(blocks, (x0, y0 - 1, x0 + width - 1, y0 + height - 2), "or")
    universe._generation = info.generation
    return universe


def write_rle(universe: HashLife) -> str:
    """The universe as RLE: ``#CXRLE Pos=x0,y0 [Gen=n]``, then canonical RLE of the box."""
    gen = f" Gen={universe.generation}" if universe.generation else ""
    box = universe.bounding_box()
    if box is None:
        return f"#CXRLE Pos=0,0{gen}\nx = 0, y = 0, rule = {universe.rule}\n!\n"
    x0, y0, x1, y1 = box
    if max(abs(x0), abs(x1), abs(y0), abs(y1)) > EDIT_LIMIT:
        raise ValueError(
            f"the pattern ({x0}, {y0})..({x1}, {y1}) reaches outside the editing box "
            f"|x|, |y| <= {EDIT_LIMIT:,}; RLE can't carry it — save as Macrocell"
        )
    # Every row's live runs, built leaf by leaf in x order (leaves never overlap).
    rows: dict[int, list[list[int]]] = {}
    for tx, ty, bits in sorted(universe._leaves(), key=lambda leaf: (leaf[1], leaf[0])):
        for r in range(8):
            byte = (bits >> (8 * r)) & 0xFF
            if not byte:
                continue
            row = rows.setdefault(ty + r + 1, [])
            for start, length in _RUNS[byte]:
                s = tx + start
                if row and row[-1][0] + row[-1][1] == s:
                    row[-1][1] += length
                else:
                    row.append([s, length])
    # Live rows only: the gap between two is one "k$" token (spec/patterns.md), so the
    # text grows with the live rows, not the box's height.
    tokens: list[str] = []
    prev = y0
    for y in sorted(rows):
        if y > y0:
            tokens.append(_run(y - prev, "$"))
        pos = x0
        for start, length in rows[y]:
            if start > pos:
                tokens.append(_run(start - pos, "b"))
            tokens.append(_run(length, "o"))
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
    return "\n".join([f"#CXRLE Pos={x0},{y0}{gen}", header, *body]) + "\n"


def _run(length: int, tag: str) -> str:
    return tag if length == 1 else f"{length}{tag}"
