"""Initialization strategies and pattern import. Draw order and thresholds are spec'd (spec/lifelike.md)."""

from heaton_life.init.patterns import compatible, extract, flip_h, flip_v, rotate90, stamp
from heaton_life.init.png_io import mergelife_from_png, mergelife_to_png
from heaton_life.init.rle import place, rle_decode, rle_encode
from heaton_life.init.seeding import blob, single, soup

__all__ = [
    "blob",
    "compatible",
    "extract",
    "flip_h",
    "flip_v",
    "mergelife_from_png",
    "mergelife_to_png",
    "place",
    "rle_decode",
    "rle_encode",
    "rotate90",
    "single",
    "soup",
    "stamp",
]
