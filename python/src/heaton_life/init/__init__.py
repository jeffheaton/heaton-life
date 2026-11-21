"""Initialization strategies and pattern import. Draw order and thresholds are spec'd (spec/lifelike.md)."""

from heaton_life.init.builtins import BUILTIN_PATTERNS, BuiltinPattern
from heaton_life.init.patterns import (
    STAMP_MODES,
    StampMode,
    check_region,
    clear,
    compatible,
    extract,
    fill_random,
    flip_h,
    flip_v,
    rotate90,
    rotate90_ccw,
    stamp,
)
from heaton_life.init.png_io import mergelife_from_png, mergelife_to_png
from heaton_life.init.rle import (
    DEFAULT_MAX_CELLS,
    RleExtent,
    RleInfo,
    place,
    rle_decode,
    rle_encode,
    rle_measure,
    rle_runs,
)
from heaton_life.init.seeding import blob, single, soup

__all__ = [
    "BUILTIN_PATTERNS",
    "DEFAULT_MAX_CELLS",
    "STAMP_MODES",
    "BuiltinPattern",
    "RleExtent",
    "RleInfo",
    "StampMode",
    "blob",
    "check_region",
    "clear",
    "compatible",
    "extract",
    "fill_random",
    "flip_h",
    "flip_v",
    "mergelife_from_png",
    "mergelife_to_png",
    "place",
    "rle_decode",
    "rle_encode",
    "rle_measure",
    "rle_runs",
    "rotate90",
    "rotate90_ccw",
    "single",
    "soup",
    "stamp",
]
