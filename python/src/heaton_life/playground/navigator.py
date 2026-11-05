"""The live view of a navigable family (HashLife), kept on the GUI side (Qt-free).

A gesture moves the view at once, with the spec's exact view arithmetic (spec/hashlife.md
"View and render"), and the engine renders it between steps, which can take seconds on a
giant pattern. Until it does, the canvas draws the last frame through ``frame_map``: where
a frame rendered at one view lands in another, so zooming and panning answer immediately.
The frame size follows the canvas too (``resize``), keeping the view's center in place.
"""

from __future__ import annotations

import dataclasses
from fractions import Fraction

from heaton_life.ca.hashlife import LifeView, pan, zoom_at

MIN_MAG = -4096  # the Mag field's own floor
_MAX_PREVIEW_STEPS = 12  # past 4096× either way a stale frame shows nothing useful


@dataclasses.dataclass(frozen=True)
class FrameMap:
    """Frame pixel (u, v) of the last frame lands at view pixel (u·scale + dx, v·scale + dy)."""

    scale: float
    dx: float
    dy: float


class ViewNavigator:
    """The view a frame of ``size`` (width, height) pixels should show, and its moves."""

    def __init__(self, view: LifeView, size: tuple[int, int]) -> None:
        self.view = view
        self.size = size
        self._carry = (0.0, 0.0)

    def zoom_at(self, i: int, j: int, steps: int) -> bool:
        """Zoom 2^steps about frame pixel (i, j); False when the view stayed (the deepest
        zoom, or the Mag field's floor)."""
        if steps < 0:
            steps = max(steps, MIN_MAG - self.view.mag)
        moved = zoom_at(self.view, i, j, steps)
        if moved == self.view:
            return False
        self.view = moved
        self._carry = (0.0, 0.0)  # the leftover fraction was in the old pixel plane
        return True

    def pan(self, dx: float, dy: float) -> bool:
        """Drag the picture by (dx, dy) frame pixels; fractions carry into the next drag.
        False when the drag was too small to move a whole pixel."""
        cx, cy = self._carry[0] + dx, self._carry[1] + dy
        ix, iy = int(cx), int(cy)  # toward zero: the remainder keeps its sign
        self._carry = (cx - ix, cy - iy)
        if not (ix or iy):
            return False
        self.view = pan(self.view, ix, iy)
        return True

    def recenter(self, i: int, j: int) -> bool:
        """Bring frame pixel (i, j) to the frame's center pixel."""
        width, height = self.size
        return self.pan(width // 2 - i, height // 2 - j)

    def resize(self, size: tuple[int, int]) -> bool:
        """Frames of ``size`` (width, height) from now on, the center pixel (width // 2,
        height // 2) still over the same point, so a resized window keeps its middle in
        place. False when the size stayed."""
        if size == self.size:
            return False
        (old_w, old_h), (new_w, new_h) = self.size, size
        self.view = pan(self.view, new_w // 2 - old_w // 2, new_h // 2 - old_h // 2)
        self.size = size
        return True

    def frame_map(self, frame_view: LifeView, frame_size: tuple[int, int]) -> FrameMap | None:
        """Where a frame of ``frame_size`` rendered at ``frame_view`` lands in this view, or
        None when it misses the view entirely or would be scaled past 4096× either way."""
        steps = self.view.mag - frame_view.mag
        if abs(steps) > _MAX_PREVIEW_STEPS:
            return None
        scale = Fraction(2) ** steps
        dx = frame_view.x * scale - self.view.x
        dy = frame_view.y * scale - self.view.y
        width, height = self.size
        fw, fh = frame_size
        if dx >= width or dy >= height or dx + fw * scale <= 0 or dy + fh * scale <= 0:
            return None
        return FrameMap(float(scale), float(dx), float(dy))
