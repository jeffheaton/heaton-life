"""Run Length Encoded pattern files — the interchange format of the Life community.

Both dialects in common use (spec/patterns.md): two-state ``b``/``o`` and
extended multi-state ``.``/``A``–``X`` (states 1–24), ``$`` end of row, ``!`` end,
optional run counts, ``#`` comment lines, and the ``x = …, y = …[, rule = …]``
header. Encoding is canonical: two-state grids emit ``b``/``o``; grids with any
cell ≥ 2 emit ``.``/letters; cells above 24 are unencodable.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterator

import numpy as np
from numpy.typing import NDArray

from heaton_life.core.decimal_text import int_of_digits
from heaton_life.init.metadata import MetadataReader, PatternMetadata, metadata_lines

_HEADER = re.compile(
    r"x\s*=\s*(\d+)\s*,\s*y\s*=\s*(\d+)(?:\s*,\s*rule\s*=\s*(\S+))?", re.IGNORECASE
)
_LIFELIKE_RULE = re.compile(r"^[Bb][0-8]*/[Ss][0-8]*$")
_TOKEN = re.compile(r"(\d*)(\S)")


def _is_extended(body: str, rule: str | None) -> bool:
    """Dialect detection (spec/patterns.md): uppercase B/O are dead/alive in two-state
    files but states 2/15 in extended RLE. Extended iff the body holds '.', any state
    letter other than B/O, or the header names a non-Life-like rule."""
    return (
        "." in body
        or any("A" <= ch <= "X" and ch not in ("B", "O") for ch in body)
        or (rule is not None and not _LIFELIKE_RULE.match(rule))
    )


@dataclasses.dataclass(frozen=True)
class RleInfo:
    """What an RLE file says about itself besides its cells (spec/patterns.md)."""

    rule: str | None
    position: tuple[int, int] | None
    """``#CXRLE Pos=x,y``: the top-left cell of the bounding rectangle, if given."""
    generation: int
    """``#CXRLE Gen=n``, or 0."""
    extended: bool


def rle_runs(text: str) -> tuple[RleInfo, Iterator[tuple[int, int, int, int]]]:
    """Scan RLE text as runs of non-zero cells: ``(x, y, length, state)`` relative to the
    pattern's top-left, in file order. Streams, so a giant file never becomes a grid.

    Extended RLE's ``#CXRLE Pos=x,y Gen=n`` counts only on the first line; anywhere else it,
    like every other ``#`` line, is a comment.
    """
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    position: tuple[int, int] | None = None
    generation = 0
    if lines and lines[0].startswith("#CXRLE"):
        for field in lines[0].split()[1:]:
            key, _, value = field.partition("=")
            if key == "Pos":
                px, _, py = value.partition(",")
                position = (_cxrle_int(px, signed=True), _cxrle_int(py, signed=True))
            elif key == "Gen":
                generation = _cxrle_int(value, signed=False)
    lines = [ln for ln in lines if not ln.startswith("#")]
    rule: str | None = None
    if lines and (header := _HEADER.match(lines[0])):
        rule = header.group(3)
        lines = lines[1:]
    body = "".join(lines)
    extended = _is_extended(body, rule)
    return RleInfo(rule, position, generation, extended), _scan(body, extended)


def _cxrle_int(text: str, *, signed: bool) -> int:
    """A ``#CXRLE`` integer: ASCII digits, after an optional ``-`` where ``signed``."""
    negative = signed and text.startswith("-")
    digits = text[1:] if negative else text
    if not (digits.isascii() and digits.isdigit()):
        kind = "an integer" if signed else "a generation in digits"
        raise ValueError(f"#CXRLE needs {kind}, got {text!r}")
    value = int_of_digits(digits)  # any size: int() refuses past 4,300 digits
    return -value if negative else value


def is_rle_header(line: str) -> bool:
    """Whether a stripped line is an RLE header ``x = W, y = H[, rule = R]`` as the
    decoders read one (spec/formats.md "Detection")."""
    return _HEADER.match(line) is not None


def rle_metadata(text: str) -> PatternMetadata:
    """The pattern's name (``#N``), author (``#O``), and comment lines (``#C``, ``#c``),
    in file order (spec/formats.md "Metadata"). A ``#CXRLE`` first line is not a comment."""
    reader = MetadataReader()
    first = True
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if first:
            first = False
            if line.startswith("#CXRLE"):
                continue
        if line.startswith("#"):
            reader.hash_line(line)
    return reader.result()


def _scan(body: str, extended: bool) -> Iterator[tuple[int, int, int, int]]:
    x = y = 0
    for token in _TOKEN.finditer(body):  # one at a time: a giant file's tokens never pile up
        count_text, tag = token.groups()
        count = int(count_text) if count_text else 1
        if tag == "b" or tag == "." or (not extended and tag == "B"):
            x += count
        elif tag == "o" or (not extended and tag == "O"):
            yield x, y, count, 1
            x += count
        elif extended and "A" <= tag <= "X":
            yield x, y, count, ord(tag) - ord("A") + 1
            x += count
        elif tag == "$":
            y += count
            x = 0
        elif tag == "!":
            return
        else:
            raise ValueError(f"unsupported RLE tag: {tag!r}")


DEFAULT_MAX_CELLS = 1 << 26
"""The decode limit's default (spec/patterns.md "The decode limit"): 67,108,864 cells, an
8192 × 8192 grid."""


@dataclasses.dataclass(frozen=True)
class RleExtent:
    """What decoding an RLE text would give, found without making a grid (spec/patterns.md
    "Extent"). Every number is exact, however large the file's run counts are."""

    width: int
    """The decoded grid's size: the larger of what the header declares and the body holds."""
    height: int
    live: tuple[int, int, int, int] | None
    """(x0, y0, x1, y1): the inclusive extremes of the non-zero cells, or None without any."""
    population: int
    """How many cells are non-zero."""
    rule: str | None
    extended: bool


def _parse(text: str) -> tuple[int, int, str | None, str, bool]:
    """An RLE text as (declared width, declared height, rule, body, extended)."""
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
    return declared_w, declared_h, rule, body, _is_extended(body, rule)


def _walk(body: str, extended: bool) -> Iterator[tuple[int, int, int, int]]:
    """The body as runs ``(x, y, length, state)`` in file order, dead runs (state 0)
    included, and last of all ``(0, rows, 0, -1)``: how many rows it has. Measuring and
    decoding both read this, so they can't disagree, and neither holds more than a run."""
    x = y = count = 0
    for ch in body:
        if ch.isdigit():
            count = count * 10 + int(ch)
        elif ch == "b" or ch == "." or (not extended and ch == "B"):
            length = max(count, 1)
            yield x, y, length, 0
            x, count = x + length, 0
        elif ch == "o" or (not extended and ch == "O"):
            length = max(count, 1)
            yield x, y, length, 1
            x, count = x + length, 0
        elif extended and "A" <= ch <= "X":  # states 1..24 (B = 2, O = 15)
            length = max(count, 1)
            yield x, y, length, ord(ch) - ord("A") + 1
            x, count = x + length, 0
        elif ch == "$":
            x, y, count = 0, y + max(count, 1), 0
        elif ch == "!":
            break
        elif ch.isspace():
            continue
        else:
            raise ValueError(f"unsupported RLE tag: {ch!r}")
    yield 0, y + 1, 0, -1


def _measure(
    declared_w: int, declared_h: int, rule: str | None, body: str, extended: bool
) -> RleExtent:
    longest = rows = population = 0
    live: tuple[int, int, int, int] | None = None
    for x, y, length, state in _walk(body, extended):
        if state < 0:
            rows = y
            break
        longest = max(longest, x + length)
        if state:
            population += length
            last = x + length - 1
            if live is None:
                live = (x, y, last, y)
            else:
                live = (min(live[0], x), live[1], max(live[2], last), y)  # rows only go down
    width, height = max(declared_w, longest), max(declared_h, rows)
    return RleExtent(width, height, live, population, rule, extended)


def rle_measure(text: str) -> RleExtent:
    """What ``rle_decode`` would give, without making it: the grid's size, the non-zero
    cells' box, and how many there are. A few bytes of RLE can describe more cells than
    memory holds (a run of a billion, a header that declares one), so measure a file that
    came from outside before decoding it."""
    return _measure(*_parse(text))


def rle_decode(
    text: str, *, max_cells: int | None = DEFAULT_MAX_CELLS, trim: bool = False
) -> tuple[NDArray[np.uint8], str | None]:
    """Decode RLE text; returns (grid, rule) where rule is None if the header omitted it.

    The extent is found first, and a grid past ``max_cells`` (width × height) is refused
    before any memory is asked for; ``None`` lifts the limit. With ``trim`` the grid is
    only the non-zero cells' bounding box: the header's size and any dead margin are
    dropped, the limit applies to that box, and a pattern with no such cell is an error.
    """
    declared_w, declared_h, rule, body, extended = _parse(text)
    extent = _measure(declared_w, declared_h, rule, body, extended)
    left = top = 0
    width, height = extent.width, extent.height
    if trim:
        if extent.live is None:
            raise ValueError("RLE pattern has no live cells")
        left, top, right, bottom = extent.live
        width, height = right - left + 1, bottom - top + 1
    elif width == 0 or height == 0:
        raise ValueError("RLE pattern has no cells")
    if max_cells is not None and width * height > max_cells:
        raise ValueError(
            f"RLE pattern is {width:,} × {height:,} cells, past the limit of {max_cells:,}"
        )
    grid = np.zeros((height, width), dtype=np.uint8)
    for x, y, length, state in _walk(body, extended):
        if state > 0:
            grid[y - top, x - left : x - left + length] = state
    return grid, rule


def rle_encode(
    grid: NDArray[np.uint8],
    rule: str = "B3/S23",
    *,
    line_width: int = 70,
    metadata: PatternMetadata | None = None,
) -> str:
    """Encode a grid as canonical RLE; dialect chosen by content (spec/patterns.md).
    ``metadata``'s ``#N``, ``#O`` and ``#C`` lines go before the header."""
    notes = metadata_lines(metadata)
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
    tokens = _row_end_runs(tokens)

    body_lines: list[str] = []
    line = ""
    for tok in tokens:
        if len(line) + len(tok) > line_width:
            body_lines.append(line)
            line = ""
        line += tok
    body_lines.append(line)
    header = f"x = {width}, y = {height}, rule = {rule}"
    return "\n".join([*notes, header, *body_lines]) + "\n"


def _row_end_runs(tokens: list[str]) -> list[str]:
    """Write k ≥ 2 consecutive ``$`` tokens as one ``k$`` (spec/patterns.md "Encoding")."""
    out: list[str] = []
    ends = 0
    for tok in tokens:
        if tok == "$":
            ends += 1
            continue
        if ends:
            out.append("$" if ends == 1 else f"{ends}$")
            ends = 0
        out.append(tok)
    if ends:
        out.append("$" if ends == 1 else f"{ends}$")
    return out


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
