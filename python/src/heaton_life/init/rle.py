"""Run Length Encoded pattern files — the interchange format of the Life community.

Golly-compatible, both dialects (spec/patterns.md): two-state ``b``/``o`` and
extended multi-state ``.``/``A``–``X`` (states 1–24), ``$`` end of row, ``!`` end,
optional run counts, ``#`` comment lines, and the ``x = …, y = …[, rule = …]``
header. Encoding is canonical: two-state grids emit ``b``/``o``; grids with any
cell ≥ 2 emit ``.``/letters; cells above 24 are unencodable.
"""

from __future__ import annotations

import re

import numpy as np
from numpy.typing import NDArray

_HEADER = re.compile(
    r"x\s*=\s*(\d+)\s*,\s*y\s*=\s*(\d+)(?:\s*,\s*rule\s*=\s*(\S+))?", re.IGNORECASE
)
_LIFELIKE_RULE = re.compile(r"^[Bb][0-8]*/[Ss][0-8]*$")


def rle_decode(text: str) -> tuple[NDArray[np.uint8], str | None]:
    """Decode RLE text; returns (grid, rule) where rule is None if the header omitted it."""
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("#")]
    if not lines:
        raise ValueError("empty RLE input")

    rule: str | None = None
    header = _HEADER.match(lines[0])
    if header:
        declared_w, declared_h = int(header.group(1)), int(header.group(2))
        rule = header.group(3)
        body = "".join(lines[1:])
    else:
        declared_w = declared_h = 0
        body = "".join(lines)

    # Dialect detection (spec/patterns.md): uppercase B/O are dead/alive in
    # two-state files but states 2/15 in extended RLE. Extended iff the body
    # holds '.', any state letter other than B/O, or a non-Life-like rule.
    extended = (
        "." in body
        or any("A" <= ch <= "X" and ch not in ("B", "O") for ch in body)
        or (rule is not None and not _LIFELIKE_RULE.match(rule))
    )

    rows: list[list[int]] = [[]]
    count = 0
    for ch in body:
        if ch.isdigit():
            count = count * 10 + int(ch)
        elif ch == "b" or ch == "." or (not extended and ch == "B"):
            rows[-1].extend([0] * max(count, 1))
            count = 0
        elif ch == "o" or (not extended and ch == "O"):
            rows[-1].extend([1] * max(count, 1))
            count = 0
        elif extended and "A" <= ch <= "X":  # states 1..24 (B = 2, O = 15)
            rows[-1].extend([ord(ch) - ord("A") + 1] * max(count, 1))
            count = 0
        elif ch == "$":
            rows.extend([] for _ in range(max(count, 1)))
            count = 0
        elif ch == "!":
            break
        elif ch.isspace():
            continue
        else:
            raise ValueError(f"unsupported RLE tag: {ch!r}")

    width = max((len(r) for r in rows), default=0)
    width = max(width, declared_w)
    height = max(len(rows), declared_h)
    if width == 0 or height == 0:
        raise ValueError("RLE pattern has no cells")

    grid = np.zeros((height, width), dtype=np.uint8)
    for y, row in enumerate(rows):
        if row:
            grid[y, : len(row)] = row
    return grid, rule


def rle_encode(grid: NDArray[np.uint8], rule: str = "B3/S23", *, line_width: int = 70) -> str:
    """Encode a grid as canonical RLE; dialect chosen by content (spec/patterns.md)."""
    height, width = grid.shape
    top = int(grid.max(initial=0))
    if top > 24:
        raise ValueError(f"cell value {top} not RLE-encodable (extended RLE tops out at 24)")
    multistate = top > 1
    tokens: list[str] = []
    for y in range(height):
        run_val = -1
        run_len = 0
        for x in range(width):
            v = int(grid[y, x])
            if v == run_val:
                run_len += 1
            else:
                if run_len:
                    tokens.append(_run(run_len, run_val, multistate))
                run_val, run_len = v, 1
        if run_val > 0:  # trailing dead runs in a row are omitted by convention
            tokens.append(_run(run_len, run_val, multistate))
        tokens.append("$" if y < height - 1 else "!")

    body_lines: list[str] = []
    line = ""
    for tok in tokens:
        if len(line) + len(tok) > line_width:
            body_lines.append(line)
            line = ""
        line += tok
    body_lines.append(line)
    header = f"x = {width}, y = {height}, rule = {rule}"
    return "\n".join([header, *body_lines]) + "\n"


def _run(length: int, value: int, multistate: bool) -> str:
    if multistate:
        tag = "." if value == 0 else chr(ord("A") + value - 1)
    else:
        tag = "o" if value else "b"
    return tag if length == 1 else f"{length}{tag}"


def place(
    pattern: NDArray[np.uint8],
    size: tuple[int, int],
    *,
    at: tuple[int, int] | str = "center",
) -> NDArray[np.uint8]:
    """Place a pattern onto a dead grid of (width, height); ``at`` is (x, y) or "center"."""
    width, height = size
    ph, pw = pattern.shape
    if pw > width or ph > height:
        raise ValueError(f"pattern {pw}x{ph} does not fit in grid {width}x{height}")
    if at == "center":
        x, y = (width - pw) // 2, (height - ph) // 2
    elif isinstance(at, tuple):
        x, y = at
    else:
        raise ValueError(f"invalid placement: {at!r}")
    grid = np.zeros((height, width), dtype=np.uint8)
    grid[y : y + ph, x : x + pw] = pattern
    return grid
