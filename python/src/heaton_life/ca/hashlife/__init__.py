"""HashLife: Life-like rules on an unbounded plane (spec/hashlife.md), and rules of many
states on one (``MultiStateHashLife``, spec/hashlife-multistate.md).

A hash-consed quadtree with memoized futures runs regular patterns of trillions of cells
and jumps any number of generations. Editing reaches |x|, |y| ≤ 10⁹ (``EDIT_LIMIT``);
queries and rendering reach everywhere. Trees stop at level 512 (``MAX_LEVEL``).
"""

from heaton_life.ca.hashlife.files import (
    PatternSnapshot,
    PatternUniverse,
    read_snapshot,
    read_universe,
)
from heaton_life.ca.hashlife.macrocell import MacrocellTimeline, read_timeline, write_timeline
from heaton_life.ca.hashlife.multistate import (
    STATE_RENDER_MODES,
    MultiStateHashLife,
    MultiStatePatternUniverse,
    MultiStateTimeline,
    StateRenderMode,
    read_multistate_universe,
)
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
    SnapshotFootprint,
    StepCanceled,
)
from heaton_life.ca.hashlife.view import (
    MAX_MAG,
    LifeView,
    cell_at,
    center_cell,
    centered,
    fit,
    frame_map,
    pan,
    resized,
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
    "STATE_RENDER_MODES",
    "HashLife",
    "HashLifeMemoryError",
    "HashLifeParams",
    "LifeView",
    "MacrocellTimeline",
    "MultiStateHashLife",
    "MultiStatePatternUniverse",
    "MultiStateTimeline",
    "PasteMode",
    "PatternSnapshot",
    "PatternUniverse",
    "RenderMode",
    "Snapshot",
    "SnapshotFootprint",
    "StateRenderMode",
    "StepCanceled",
    "cell_at",
    "center_cell",
    "centered",
    "fit",
    "frame_map",
    "pan",
    "read_multistate_universe",
    "read_snapshot",
    "read_timeline",
    "read_universe",
    "resized",
    "write_timeline",
    "zoom_at",
]
