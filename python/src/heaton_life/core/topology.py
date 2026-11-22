"""Grid topologies (spec/topology.md): the plane, the torus (shifted or not), the Klein
bottle, the cross-surface and the sphere; the halo through which a grid family's step reads
past its edges; and the bounded-grid suffix that names a world in a rule's text
(``B3/S23:T30,20``)."""

from __future__ import annotations

import dataclasses
import functools
import operator
from typing import Any, Literal, TypeAlias

import numpy as np
from numpy.typing import DTypeLike, NDArray

Boundary: TypeAlias = Literal["torus", "dead", "klein", "cross", "sphere"]
"""A topology's name in params: ``dead`` is the plane."""
Axis: TypeAlias = Literal["x", "y"]
"""The pair of edges that carries a shift or a twist: ``x`` the top and bottom edges
(crossing them shifts or mirrors x), ``y`` the left and right edges."""

BOUNDARIES: tuple[Boundary, ...] = ("torus", "dead", "klein", "cross", "sphere")
AXES: tuple[Axis, ...] = ("x", "y")

MAX_SIDE = 2_000_000_000
"""The largest side, and the largest shift, a bounded-grid suffix may name."""

# How a shift reads (spec/topology.md "Where a point past an edge lands"), each in this one
# place for the scalar and the vectorized formulas below.
_SHIFT_SENSE = 1
"""A torus's shift moves a cell that leaves across the bottom (right) edge ``_SHIFT_SENSE ×
shift`` columns right (rows down)."""
_TWIST_SENSE = 1
"""A shifted Klein bottle's twisted crossing sends x to ``W − 1 + _TWIST_SENSE × shift − x``."""

# Names in reasons for the topologies without a shift, and the suffix's letters.
_PLAIN: dict[str, str] = {"dead": "the plane", "cross": "the cross-surface", "sphere": "the sphere"}
_KIND: dict[str, Boundary] = {"P": "dead", "T": "torus", "K": "klein", "C": "cross", "S": "sphere"}
_LETTER: dict[Boundary, str] = {boundary: letter for letter, boundary in _KIND.items()}
_KIND_CHARACTERS = frozenset("PTKCSptkcs")  # explicit: str.upper() maps U+017F 'ſ' to 'S'


class TopologyError(ValueError):
    """A topology, a halo or a bounded-grid suffix that isn't one, with the reason
    spec/topology.md gives for it."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


def _invalid(reason: str) -> TopologyError:
    return TopologyError(f"invalid topology: {reason} (spec/topology.md)", reason)


@dataclasses.dataclass(frozen=True)
class Topology:
    """How a grid's edges join (spec/topology.md "The topologies").

    ``axis`` is the pair of edges that carries a torus's shift or a Klein bottle's twist
    and shift. Where it means nothing (no Klein bottle, no shift) it reads back as ``x``.
    """

    boundary: Boundary = "torus"
    shift: int = 0
    axis: Axis = "x"

    def __post_init__(self) -> None:
        if self.boundary not in BOUNDARIES:
            raise _invalid(
                f"unknown boundary '{self.boundary}': expected dead, torus, klein, cross or sphere"
            )
        if self.axis not in AXES:
            raise _invalid(f"unknown axis '{self.axis}': expected x or y")
        shift = operator.index(self.shift)
        if shift != 0 and self.boundary in _PLAIN:
            raise _invalid(f"{_PLAIN[self.boundary]} has no shift")
        object.__setattr__(self, "shift", shift)
        if self.boundary != "klein" and shift == 0:
            object.__setattr__(self, "axis", "x")  # an axis that means nothing

    def check(self, width: int, height: int) -> None:
        """Raise unless a grid of ``width`` × ``height`` cells can have this topology
        (spec/topology.md "Errors", 4 to 6)."""
        if width < 1 or height < 1:
            raise _invalid("a grid has at least one row and one column")
        if self.boundary == "sphere" and width != height:
            raise _invalid("a sphere is square")
        twisted = width if self.axis == "x" else height
        if self.boundary == "klein" and self.shift != 0 and twisted % 2:
            raise _invalid("a Klein bottle shifts only a side of even length")

    def locate(self, x: int, y: int, width: int, height: int) -> tuple[int, int] | None:
        """The cell ``(x′, y′)`` the plane point ``(x, y)`` stands for on a grid of
        ``width`` × ``height`` cells, or None past the plane's edge (spec/topology.md
        "Where a point past an edge lands"). The cross-surface and the sphere reach one
        side's length past the grid; a point farther out is a ValueError."""
        if 0 <= x < width and 0 <= y < height:
            return x, y
        boundary = self.boundary
        if boundary == "dead":
            return None
        if boundary == "torus":
            s = _SHIFT_SENSE * self.shift
            if self.axis == "x":
                k = y // height
                return (x + k * s) % width, y - k * height
            k = x // width
            return x - k * width, (y + k * s) % height
        if boundary == "klein":
            s = _TWIST_SENSE * self.shift
            if self.axis == "x":
                k = y // height
                column = x % width if k % 2 == 0 else (width - 1 + s - x) % width
                return column, y - k * height
            k = x // width
            row = y % height if k % 2 == 0 else (height - 1 + s - y) % height
            return x - k * width, row
        j, k = x // width, y // height
        if abs(j) > 1 or abs(k) > 1:
            raise ValueError(
                f"({x}, {y}) is past the reach of the {boundary} formulas on a "
                f"{width} x {height} grid (spec/topology.md)"
            )
        x1, y1 = x - j * width, y - k * height
        if boundary == "cross":
            return (width - 1 - x1 if k else x1), (height - 1 - y1 if j else y1)
        n = width  # a sphere
        if j == 0:  # above or below
            return (-1 - y if k < 0 else 2 * n - 1 - y), x
        if k == 0:  # left or right
            return y, (-1 - x if j < 0 else 2 * n - 1 - x)
        return (-1 - x if j < 0 else 2 * n - 1 - x), (-1 - y if k < 0 else 2 * n - 1 - y)


def _locate_many(
    topology: Topology, x: NDArray[np.int64], y: NDArray[np.int64], width: int, height: int
) -> tuple[NDArray[np.int64], NDArray[np.int64], NDArray[np.bool_]]:
    """``Topology.locate`` over arrays of points, all past the grid or inside it: the cells'
    columns and rows, and whether each point stands for a cell at all. The same formulas;
    the suites compare the two on every halo."""
    everywhere = np.ones(x.shape, dtype=np.bool_)
    if topology.boundary == "dead":
        inside = (x >= 0) & (x < width) & (y >= 0) & (y < height)
        return x, y, inside
    if topology.boundary == "torus":
        s = _SHIFT_SENSE * topology.shift
        if topology.axis == "x":
            k = y // height
            return (x + k * s) % width, y - k * height, everywhere
        k = x // width
        return x - k * width, (y + k * s) % height, everywhere
    if topology.boundary == "klein":
        s = _TWIST_SENSE * topology.shift
        if topology.axis == "x":
            k = y // height
            column = np.where(k % 2 == 0, x % width, (width - 1 + s - x) % width)
            return column, y - k * height, everywhere
        k = x // width
        row = np.where(k % 2 == 0, y % height, (height - 1 + s - y) % height)
        return x - k * width, row, everywhere
    j, k = x // width, y // height
    if np.any(np.abs(j) > 1) or np.any(np.abs(k) > 1):
        raise ValueError("a point is past the reach of the cross-surface or sphere formulas")
    x1, y1 = x - j * width, y - k * height
    if topology.boundary == "cross":
        return (
            np.where(k != 0, width - 1 - x1, x1),
            np.where(j != 0, height - 1 - y1, y1),
            everywhere,
        )
    n = width  # a sphere
    left, above = j < 0, k < 0
    turned_x = np.where(left, -1 - x, 2 * n - 1 - x)  # half a turn about a corner
    turned_y = np.where(above, -1 - y, 2 * n - 1 - y)
    column = np.where(
        (j == 0) & (k == 0), x, np.where(j == 0, np.where(above, -1 - y, 2 * n - 1 - y), y)
    )
    row = np.where(
        (j == 0) & (k == 0), y, np.where(k == 0, np.where(left, -1 - x, 2 * n - 1 - x), x)
    )
    corner = (j != 0) & (k != 0)
    return np.where(corner, turned_x, column), np.where(corner, turned_y, row), everywhere


@functools.lru_cache(maxsize=8)
def _ring(
    topology: Topology, width: int, height: int, radius: int
) -> tuple[NDArray[np.intp], NDArray[np.intp], NDArray[np.intp]]:
    """A halo's cells past the grid, as flat indices into the halo: those holding a cell
    (with that cell's flat index) and those holding the blank."""
    stride = width + 2 * radius
    # The bands above and below the grid (whole rows), then those left and right of it.
    band_rows = np.r_[0:radius, height + radius : height + 2 * radius]
    side_columns = np.r_[0:radius, width + radius : stride]
    above_below = np.meshgrid(band_rows, np.arange(stride), indexing="ij")
    beside = np.meshgrid(np.arange(radius, height + radius), side_columns, indexing="ij")
    rows = np.concatenate([above_below[0].ravel(), beside[0].ravel()]).astype(np.int64)
    columns = np.concatenate([above_below[1].ravel(), beside[1].ravel()]).astype(np.int64)
    targets = (rows * stride + columns).astype(np.intp)
    cell_x, cell_y, valid = _locate_many(topology, columns - radius, rows - radius, width, height)
    sources = (cell_y * width + cell_x).astype(np.intp)
    held = (targets[valid], sources[valid], targets[~valid])
    for array in held:
        array.setflags(write=False)
    return held


class Halo:
    """The halo of radius ``radius`` around a ``width`` × ``height`` grid with a topology
    (spec/topology.md "The halo"): ``(height + 2r) × (width + 2r)`` cells, the grid in the
    middle and, past its edges, the cells its topology puts there (the blank on the
    plane). A family's step fills one from each generation and reads neighbors from it."""

    def __init__(self, topology: Topology, width: int, height: int, radius: int = 1) -> None:
        topology.check(width, height)
        radius = operator.index(radius)
        if radius < 1:
            raise _invalid("the halo radius is at least 1")
        if topology.boundary in ("cross", "sphere") and radius > min(width, height):
            raise _invalid("the halo is deeper than the grid")
        self.topology = topology
        self.width = width
        self.height = height
        self.radius = radius
        self._targets, self._sources, self._blanks = _ring(topology, width, height, radius)

    @property
    def shape(self) -> tuple[int, int]:
        """The halo's (rows, columns)."""
        return self.height + 2 * self.radius, self.width + 2 * self.radius

    def fill(
        self, cells: NDArray[Any], blank: int = 0, *, dtype: DTypeLike | None = None
    ) -> NDArray[Any]:
        """A new halo array of ``cells`` (``(height, width)``), in ``dtype`` (the cells'
        own by default), with ``blank`` wherever the topology puts no cell."""
        if cells.shape != (self.height, self.width):
            raise ValueError(
                f"cells of shape {cells.shape} for a halo of a {self.width} x {self.height} grid"
            )
        r = self.radius
        halo = np.empty(self.shape, dtype=cells.dtype if dtype is None else dtype)
        halo[r : r + self.height, r : r + self.width] = cells
        flat = halo.reshape(-1)
        flat[self._targets] = cells.reshape(-1)[self._sources]
        flat[self._blanks] = blank
        return halo

    def sources(self) -> NDArray[np.intp]:
        """Each halo cell's source: the flat index ``y·width + x`` of the cell it holds, or
        −1 for the blank (spec/topology.md "Vector encoding", ``map``)."""
        index = np.arange(self.width * self.height, dtype=np.intp).reshape(self.height, self.width)
        sources: NDArray[np.intp] = self.fill(index, -1)
        return sources


# -- the bounded-grid suffix (spec/topology.md "The bounded-grid suffix") -----------------


@dataclasses.dataclass(frozen=True)
class BoundedGrid:
    """A world a bounded-grid suffix names: its size and topology."""

    width: int
    height: int
    topology: Topology

    def __post_init__(self) -> None:
        if not (0 < self.width <= MAX_SIDE and 0 < self.height <= MAX_SIDE):
            if self.width == 0 or self.height == 0:
                raise _invalid("a side of 0 (an unbounded strip or tube) is not supported")
            raise _invalid(f"a side or a shift is at most {MAX_SIDE}")
        if abs(self.topology.shift) > MAX_SIDE:
            raise _invalid(f"a side or a shift is at most {MAX_SIDE}")
        self.topology.check(self.width, self.height)

    @property
    def suffix(self) -> str:
        """The canonical suffix, ``:`` included: ``:T30,20``, ``:K30*+1,20``, ``:S30``."""
        topology = self.topology
        if topology.boundary == "sphere":
            return f":S{self.width}"
        marks = {"x": "", "y": ""}
        if topology.boundary == "klein":
            marks[topology.axis] = "*"
        if topology.shift:
            marks[topology.axis] += f"{topology.shift:+d}"
        letter = _LETTER[topology.boundary]
        return f":{letter}{self.width}{marks['x']},{self.height}{marks['y']}"

    def __str__(self) -> str:
        return self.suffix


class _SuffixError(TopologyError):
    def __init__(self, text: str, reason: str) -> None:
        super().__init__(f"invalid bounded grid '{text}': {reason} (spec/topology.md)", reason)


def parse_bounded_grid(text: str) -> BoundedGrid:
    """The world a bounded-grid suffix names (``:T30,20``, the ``:`` included). Raises
    ValueError with the reason spec/topology.md gives for the first problem found."""
    try:
        return _parse(text)
    except _SuffixError:
        raise
    except TopologyError as error:  # the topology's own errors with the size
        raise _SuffixError(text, error.reason) from None


def try_parse_bounded_grid(text: str) -> tuple[BoundedGrid, None] | tuple[None, str]:
    """``parse_bounded_grid`` without raising: ``(grid, None)``, or ``(None, reason)``."""
    try:
        return parse_bounded_grid(text), None
    except TopologyError as error:
        return None, error.reason


def split_rule_suffix(text: str) -> tuple[str, BoundedGrid | None]:
    """A rule's text and the bounded grid its suffix names, or None without a ``:``: the
    rule is everything before the first ``:``, the suffix the rest without the whitespace
    at its end (spec/topology.md "In a rule's text"). A bad suffix raises its error."""
    colon = text.find(":")
    if colon < 0:
        return text, None
    from heaton_life.ca.rulestring import _SPACE  # the whitespace of spec/rules.md

    suffix = text[colon:]
    end = len(suffix)
    while end > 0 and suffix[end - 1] in _SPACE:
        end -= 1
    return text[:colon], parse_bounded_grid(suffix[:end])


_DIGITS = frozenset("0123456789")


def _number(digits: str) -> int:
    """A side's or shift's digits as a number, any past ``MAX_SIDE`` as ``MAX_SIDE + 1``."""
    significant = digits.lstrip("0")
    return MAX_SIDE + 1 if len(significant) > 10 else min(int(significant or "0"), MAX_SIDE + 1)


def _parse(text: str) -> BoundedGrid:
    if not text.startswith(":"):
        raise _SuffixError(text, "a bounded grid starts with ':'")
    if len(text) < 2 or text[1] not in _KIND_CHARACTERS:
        raise _SuffixError(text, "expected P, T, K, C or S after ':'")
    boundary = _KIND[text[1].upper()]
    pos = 2
    sides: list[tuple[int, bool, int]] = []  # (side, '*', shift) as written

    def digits() -> int:
        nonlocal pos
        start = pos
        while pos < len(text) and text[pos] in _DIGITS:
            pos += 1
        if pos == start:
            raise _SuffixError(text, f"expected a number after '{text[pos - 1]}'")
        return _number(text[start:pos])

    while True:
        side = digits()
        star = pos < len(text) and text[pos] == "*"
        if star:
            pos += 1
        shift = 0
        if pos < len(text) and text[pos] in "+-":
            sign = -1 if text[pos] == "-" else 1
            pos += 1
            shift = sign * digits()
        sides.append((side, star, shift))
        if len(sides) == 2 or pos >= len(text) or text[pos] != ",":
            break
        pos += 1
    if pos < len(text):
        raise _SuffixError(text, f"unexpected '{text[pos:]}' in the bounded grid")

    if len(sides) == 1:
        sides.append(sides[0][:1] + (False, 0))  # one side: a square, marks on the width
    (width, star_x, shift_x), (height, star_y, shift_y) = sides
    if boundary in _PLAIN:
        if star_x or star_y or shift_x or shift_y:
            raise _SuffixError(text, f"{_PLAIN[boundary]} has no shift or twist")
    elif boundary == "torus":
        if star_x or star_y:
            raise _SuffixError(text, "a torus has no twist")
        if shift_x and shift_y:
            raise _SuffixError(text, "a torus shifts one side only")
    elif star_x == star_y:
        raise _SuffixError(
            text, "a Klein bottle twists one side: '*' after its width or its height"
        )
    elif (shift_y if star_x else shift_x) != 0:
        raise _SuffixError(text, "a Klein bottle shifts only its twisted side")
    if width == 0 or height == 0:
        raise _SuffixError(text, "a side of 0 (an unbounded strip or tube) is not supported")
    if max(width, height, abs(shift_x), abs(shift_y)) > MAX_SIDE:
        raise _SuffixError(text, f"a side or a shift is at most {MAX_SIDE}")
    if boundary == "klein":
        axis: Axis = "x" if star_x else "y"
    else:
        axis = "y" if shift_y else "x"
    topology = Topology(boundary, shift_x if axis == "x" else shift_y, axis)
    return BoundedGrid(width, height, topology)
