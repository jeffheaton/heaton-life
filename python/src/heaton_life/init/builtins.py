"""The built-in pattern set — spec/patterns.md "Built-in patterns".

Code-defined encodings of public mathematical commons (authored from their
published cell coordinates, no copied pattern files). Every implementation
ships this same set; apps surface it as the zoo's built-in shelf. Bodies are
canonical RLE without headers; ``cells()`` decodes through the origin rule.
The set is behavior-pinned in tests/test_builtin_patterns.py: stills stay,
periods hold, ships translate, the gun fires, the replicator copies itself,
the clock keeps circulating, and the diode passes exactly one way.
"""

from __future__ import annotations

import dataclasses

import numpy as np
from numpy.typing import NDArray

from heaton_life.init.rle import rle_decode


@dataclasses.dataclass(frozen=True)
class BuiltinPattern:
    """One built-in: family-bound (spec/patterns.md); rule is the origin context."""

    name: str
    family: str
    rule: str
    rle: str

    def cells(self) -> NDArray[np.uint8]:
        """Decode the canonical body to a fresh (height, width) cell grid."""
        grid, _ = rle_decode(f"x = 0, y = 0, rule = {self.rule}\n{self.rle}")
        return grid


def _life(name: str, rle: str, rule: str = "B3/S23") -> BuiltinPattern:
    return BuiltinPattern(name, "lifelike", rule, rle)


def _wire(name: str, rle: str) -> BuiltinPattern:
    return BuiltinPattern(name, "wireworld", "WireWorld", rle)


BUILTIN_PATTERNS: tuple[BuiltinPattern, ...] = (
    # Spaceships.
    _life("Glider", "bo$2bo$3o!"),
    _life("Lightweight spaceship", "bo2bo$o$o3bo$4o!"),
    _life("Middleweight spaceship", "3bo$bo3bo$o$o4bo$5o!"),
    _life("Heavyweight spaceship", "3b2o$bo4bo$o$o5bo$6o!"),
    # Oscillators.
    _life("Blinker", "3o!"),
    _life("Toad", "b3o$3o!"),
    _life("Beacon", "2o$2o$2b2o$2b2o!"),
    _life(
        "Pulsar",
        "2b3o3b3o2$o4bobo4bo$o4bobo4bo$o4bobo4bo$2b3o3b3o2$"
        "2b3o3b3o$o4bobo4bo$o4bobo4bo$o4bobo4bo2$2b3o3b3o!",
    ),
    _life("Pentadecathlon", "2bo4bo$2ob4ob2o$2bo4bo!"),
    # Still lifes.
    _life("Block", "2o$2o!"),
    _life("Beehive", "b2o$o2bo$b2o!"),
    _life("Loaf", "b2o$o2bo$bobo$2bo!"),
    # Methuselahs.
    _life("R-pentomino", "b2o$2o$bo!"),
    _life("Diehard", "6bo$2o$bo3b3o!"),
    _life("Acorn", "bo$3bo$2o2b3o!"),
    # Guns.
    _life(
        "Gosper glider gun",
        "24bo$22bobo$12b2o6b2o12b2o$11bo3bo4b2o12b2o$2o8bo5bo3b2o$"
        "2o8bo3bob2o4bobo$10bo5bo7bo$11bo3bo$12b2o!",
    ),
    # HighLife: stamp into a B36/S23 world to watch it self-copy.
    _life("Replicator (HighLife)", "2b3o$bo2bo$o3bo$o2bo$3o!", "B36/S23"),
    # Wireworld logic. Clock: an electron circulating a conductor ring.
    # Diode: the 2-cell cap passes rightward electrons and kills leftward ones.
    _wire("Clock", "CBA3C$C4.C$6C!"),
    _wire("Diode (passes right)", "3.2C$4C.3C$3.2C!"),
)
