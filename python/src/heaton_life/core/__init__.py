"""Core contracts shared by every family: protocols, params, RNG, viewport, neighborhoods,
grid topologies."""

from heaton_life.core.neighbors import moore_index, moore_sum
from heaton_life.core.params import Params
from heaton_life.core.protocols import Field, Simulation
from heaton_life.core.rng import Pcg32
from heaton_life.core.topology import (
    AXES,
    BOUNDARIES,
    Axis,
    Boundary,
    BoundedGrid,
    Halo,
    Topology,
    TopologyError,
    parse_bounded_grid,
    split_rule_suffix,
    try_parse_bounded_grid,
)
from heaton_life.core.viewport import Viewport

__all__ = [
    "AXES",
    "BOUNDARIES",
    "Axis",
    "Boundary",
    "BoundedGrid",
    "Field",
    "Halo",
    "Params",
    "Pcg32",
    "Simulation",
    "Topology",
    "TopologyError",
    "Viewport",
    "moore_index",
    "moore_sum",
    "parse_bounded_grid",
    "split_rule_suffix",
    "try_parse_bounded_grid",
]
