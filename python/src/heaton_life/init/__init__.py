"""Initialization strategies and pattern import. Draw order and thresholds are spec'd (spec/lifelike.md)."""

from heaton_life.init.rle import place, rle_decode, rle_encode
from heaton_life.init.seeding import blob, single, soup

__all__ = ["blob", "place", "rle_decode", "rle_encode", "single", "soup"]
