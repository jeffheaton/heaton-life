"""State palettes (spec/render.md "State palettes"): a color for each state of a world.

A state palette has a colormap's shape, a (256, 3) uint8 table, but is indexed by state
instead of by frame value, so ``apply_colormap(states, palette)`` colors a byte frame of
states: a grid world's ``state`` (Elementary's ``diagram``) or a multi-state universe's
``state`` frames. Entry s is state s's color; the entries from the world's number of
states on are black and unused. A host that lets a person choose each state's color edits
the entries.
"""

from __future__ import annotations

import operator
from collections.abc import Iterable, Sequence

import numpy as np
from numpy.typing import NDArray

from heaton_life.render.colormap import get_colormap

RGB = tuple[int, int, int]

HISTORY_COLORS: tuple[RGB, ...] = (
    (0, 0, 0),  # 0 off: black
    (0, 255, 0),  # 1 on: green
    (0, 0, 160),  # 2 envelope: blue
    (255, 255, 255),  # 3 marked on: white
    (255, 0, 0),  # 4 marked off: red
    (255, 255, 0),  # 5 start on: yellow
    (128, 128, 128),  # 6 boundary: gray
)
"""History's colors, state by state: those LifeHistory pictures are known by, in shades
chosen here (spec/render.md "Default palettes")."""

HISTORY_ZOOM_ORDER: tuple[int, ...] = (3, 5, 1, 4, 6, 2)
"""The zoom order of a History rule (spec/render.md "Zoomed out"): the on states, marked
before plain, then marked off and the boundary, and the envelope last."""


def _count(states: int) -> int:
    count = operator.index(states)
    if not 2 <= count <= 256:
        raise ValueError(f"a state palette is for 2 to 256 states, not {count}")
    return count


def _color(color: Iterable[int], what: str) -> RGB:
    values = tuple(operator.index(v) for v in color)
    if len(values) != 3 or any(not 0 <= v <= 255 for v in values):
        raise ValueError(f"{what} is three bytes from 0 to 255, not {tuple(color)!r}")
    return values[0], values[1], values[2]


def _lut(cmap: str | NDArray[np.uint8]) -> NDArray[np.uint8]:
    lut = get_colormap(cmap) if isinstance(cmap, str) else np.asarray(cmap)
    if lut.shape != (256, 3) or lut.dtype != np.uint8:
        raise ValueError("a colormap is a (256, 3) uint8 array")
    return lut


def _half_even(numerator: int, denominator: int) -> int:
    """numerator / denominator rounded half to even (numerator >= 0, denominator > 0)."""
    quotient, remainder = divmod(numerator, denominator)
    if 2 * remainder > denominator or (2 * remainder == denominator and quotient % 2 == 1):
        quotient += 1
    return quotient


def _sampled(lut: NDArray[np.uint8], values: Sequence[int]) -> NDArray[np.uint8]:
    palette = np.zeros((256, 3), dtype=np.uint8)
    palette[: len(values)] = lut[np.asarray(values, dtype=np.intp)]
    return palette


def _generations_values(count: int) -> tuple[int, ...]:
    return (0, *(255 * (count - s) // (count - 1) for s in range(1, count)))


def frame_values(world: object) -> tuple[int, ...]:
    """Each state's frame value f(s), state 0 first (spec/render.md "State palettes"): the
    byte a world's frame gives a cell in that state. For the two-state universe 0 and 255
    (its frames' live cell), for a multi-state universe the states themselves."""
    from heaton_life.ca import Cyclic, Elementary, Generations, HashLife, LifeLike, Wireworld
    from heaton_life.ca.hashlife import MultiStateHashLife

    if isinstance(world, LifeLike):
        return tuple(range(world.states)) if world.rule.variant else (0, 255)
    if isinstance(world, Elementary | HashLife):
        return (0, 255)
    if isinstance(world, Cyclic):
        count = world.params.states
        span = max(count - 1, 1)
        return tuple(s * 255 // span for s in range(count))
    if isinstance(world, Wireworld):
        return (0, 85, 170, 255)
    if isinstance(world, Generations):
        return _generations_values(world.states)
    if isinstance(world, MultiStateHashLife):
        return tuple(range(world.states))
    raise TypeError(f"{type(world).__name__} has no byte states to color")


def colormap_palette(world: object, cmap: str | NDArray[np.uint8]) -> NDArray[np.uint8]:
    """A colormap's palette for a world: entry s is the colormap's entry at state s's frame
    value, so ``apply_colormap(states, colormap_palette(world, lut))`` equals
    ``apply_colormap(frame, lut)``. Where a host starts when the colors it shows today
    are to be edited state by state."""
    return _sampled(_lut(cmap), frame_values(world))


def history_palette() -> NDArray[np.uint8]:
    """History's palette (spec/render.md "Default palettes"): off black, on green, the
    envelope blue, marked on white, marked off red, start on yellow, the boundary gray."""
    palette = np.zeros((256, 3), dtype=np.uint8)
    palette[: len(HISTORY_COLORS)] = HISTORY_COLORS
    return palette


def generations_palette(states: int) -> NDArray[np.uint8]:
    """Generations' palette of C states: ``fire`` at the Generations frame values, so a live
    cell is pale yellow and the dying states fade through orange and red toward black."""
    return _sampled(get_colormap("fire"), _generations_values(_count(states)))


def multistate_palette(states: int) -> NDArray[np.uint8]:
    """The palette of a rule with none of its own: black, then ``rainbow``'s entry
    ⌊255 · (s − 1) / (S − 1)⌋ for each state s from 1, S − 1 hues and none twice."""
    count = _count(states)
    rainbow = get_colormap("rainbow")
    palette = np.zeros((256, 3), dtype=np.uint8)
    for s in range(1, count):
        palette[s] = rainbow[255 * (s - 1) // (count - 1)]
    return palette


def gradient_palette(
    states: int,
    first: Iterable[int],
    last: Iterable[int],
    background: Iterable[int] = (0, 0, 0),
) -> NDArray[np.uint8]:
    """Entry 0 the background, and states 1 to S − 1 from ``first`` to ``last``: per
    channel (first · (S − 1 − s) + last · (s − 1)) / (S − 2), rounded half to even in exact
    integers; with two states, state 1 is ``first``."""
    count = _count(states)
    a = _color(first, "first")
    b = _color(last, "last")
    palette = np.zeros((256, 3), dtype=np.uint8)
    palette[0] = _color(background, "background")
    if count == 2:
        palette[1] = a
        return palette
    span = count - 2
    for s in range(1, count):
        palette[s] = [_half_even(a[c] * (count - 1 - s) + b[c] * (s - 1), span) for c in range(3)]
    return palette


def shade_colormap(background: Iterable[int], color: Iterable[int]) -> NDArray[np.uint8]:
    """The shade from state 0's color to state 1's, for frames whose pixels count live cells
    (spec/render.md "Zoomed out"): entry v is b + (c − b) · v / 255 per channel, rounded
    half to even in exact integers. The shade from black to white is ``gray``."""
    b = _color(background, "background")
    c = _color(color, "color")
    lut = np.zeros((256, 3), dtype=np.uint8)
    for v in range(256):
        lut[v] = [_half_even(b[k] * (255 - v) + c[k] * v, 255) for k in range(3)]
    return lut


def _rule_palette(rule: object) -> NDArray[np.uint8]:
    """A multi-state universe's palette, by its rule: the palette the rule has on a grid."""
    from heaton_life.ca.generations import GenerationsRule
    from heaton_life.ca.history import HistoryRule
    from heaton_life.ca.state_rules import StateRule
    from heaton_life.ca.wireworld import WireworldRule

    if isinstance(rule, HistoryRule):
        return history_palette()
    if isinstance(rule, GenerationsRule):
        return generations_palette(rule.states)
    if isinstance(rule, WireworldRule):
        return _sampled(get_colormap("wireworld"), (0, 85, 170, 255))
    # Rule tables (their @COLORS over the multi-state palette) and Super rules plug in
    # here when they land (spec/render.md "Still to come").
    assert isinstance(rule, StateRule)
    return multistate_palette(rule.states)


def default_palette(world: object) -> NDArray[np.uint8]:
    """A world's default palette (spec/render.md "Default palettes"): History's under a
    History rule, Generations' for Generations, the rule's own on a multi-state universe,
    and otherwise the palette of the colormap its family is shown with (``phosphor`` for
    two-state Life-like worlds and the two-state universe, ``gray`` for Elementary,
    ``rainbow`` for Cyclic, ``wireworld`` for Wireworld)."""
    from heaton_life.ca import Cyclic, Elementary, Generations, HashLife, LifeLike, Wireworld
    from heaton_life.ca.hashlife import MultiStateHashLife

    if isinstance(world, LifeLike):
        # Super rules (26 states) plug in here when they land.
        if world.rule.variant:
            return history_palette()
        return colormap_palette(world, "phosphor")
    if isinstance(world, HashLife):
        return colormap_palette(world, "phosphor")
    if isinstance(world, Elementary):
        return colormap_palette(world, "gray")
    if isinstance(world, Cyclic):
        return colormap_palette(world, "rainbow")
    if isinstance(world, Wireworld):
        return colormap_palette(world, "wireworld")
    if isinstance(world, Generations):
        return generations_palette(world.states)
    if isinstance(world, MultiStateHashLife):
        return _rule_palette(world.state_rule)
    raise TypeError(f"{type(world).__name__} has no byte states to color")


def default_zoom_order(world: object) -> tuple[int, ...]:
    """The zoom order that goes with a world's default palette (spec/render.md "Zoomed
    out"): History's for a History rule, on a grid or the plane; the empty order (lowest
    non-zero state first) for every other world. Set it on a universe (``zoom_order``) or
    pass it to ``sample_window``; nothing sets it for the host."""
    from heaton_life.ca import LifeLike
    from heaton_life.ca.hashlife import MultiStateHashLife
    from heaton_life.ca.history import HistoryRule

    frame_values(world)  # refuses a world without byte states, as the palettes do
    if isinstance(world, LifeLike) and world.rule.variant:
        return HISTORY_ZOOM_ORDER
    if isinstance(world, MultiStateHashLife) and isinstance(world.state_rule, HistoryRule):
        return HISTORY_ZOOM_ORDER
    return ()
