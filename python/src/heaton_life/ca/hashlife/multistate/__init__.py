"""Multi-state HashLife: rules of many states on an unbounded plane
(spec/hashlife-multistate.md).

The two-state engine's algorithm on a quadtree whose leaves are 2 × 2 squares of states,
its base case computed from the rule's cell function and memoized. Wireworld runs today;
every family whose rule is a function of the 3 × 3 block plugs in through ``StateRule``.
"""

from heaton_life.ca.hashlife.multistate.files import (
    MultiStatePatternUniverse,
    read_multistate_snapshot,
    read_multistate_universe,
)
from heaton_life.ca.hashlife.multistate.macrocell import (
    MultiStateTimeline,
    read_timeline,
    write_timeline,
)
from heaton_life.ca.hashlife.multistate.universe import (
    STATE_RENDER_MODES,
    MultiStateHashLife,
    StateRenderMode,
)

__all__ = [
    "STATE_RENDER_MODES",
    "MultiStateHashLife",
    "MultiStatePatternUniverse",
    "MultiStateTimeline",
    "StateRenderMode",
    "read_multistate_snapshot",
    "read_multistate_universe",
    "read_timeline",
    "write_timeline",
]
