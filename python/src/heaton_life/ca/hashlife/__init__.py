"""HashLife: Life-like rules on an unbounded plane (spec/hashlife.md).

A hash-consed quadtree with memoized futures runs regular patterns of trillions of cells
and jumps any number of generations. Editing reaches |x|, |y| ≤ 10⁹ (``EDIT_LIMIT``);
queries and rendering reach everywhere. Trees stop at level 512 (``MAX_LEVEL``).
"""

from heaton_life.ca.hashlife.render import RENDER_MODES, RenderMode
from heaton_life.ca.hashlife.universe import (
    DEFAULT_MEMORY_MB,
    EDIT_LIMIT,
    MAX_LEVEL,
    MIN_MEMORY_MB,
    PASTE_MODES,
    HashLife,
    HashLifeMemoryError,
    HashLifeParams,
    PasteMode,
    Snapshot,
    StepCanceled,
)
from heaton_life.ca.hashlife.view import (
    MAX_MAG,
    LifeView,
    cell_at,
    center_cell,
    centered,
    fit,
    pan,
    zoom_at,
)

__all__ = [
    "DEFAULT_MEMORY_MB",
    "EDIT_LIMIT",
    "MAX_LEVEL",
    "MAX_MAG",
    "MIN_MEMORY_MB",
    "PASTE_MODES",
    "RENDER_MODES",
    "HashLife",
    "HashLifeMemoryError",
    "HashLifeParams",
    "LifeView",
    "PasteMode",
    "RenderMode",
    "Snapshot",
    "StepCanceled",
    "cell_at",
    "center_cell",
    "centered",
    "fit",
    "pan",
    "zoom_at",
]
