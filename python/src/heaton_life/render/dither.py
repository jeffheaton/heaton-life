"""Presentation noise -- spec/rng.md "Presentation noise".

A stateless per-pixel hash (Chris Wellons' triple32, as Heaton Fractal uses it), not
simulation randomness: no state, no draw order, so any row order gives the same noise.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

_MASK32 = 0xFFFFFFFF
_SEED_X = 0x9E3779B9
_SEED_Y = 0x85EBCA6B
_SEED_FRAME = 0xC2B2AE35
_SEED_CHANNEL = 0x27D4EB2F
_SECOND = 0x68BC21EB

U32Array = NDArray[np.uint32]


def triple32(x: int) -> int:
    """The hash on one 32-bit value (Python integers, masked)."""
    x &= _MASK32
    x ^= x >> 17
    x = (x * 0xED5AD4BB) & _MASK32
    x ^= x >> 11
    x = (x * 0xAC4C1B51) & _MASK32
    x ^= x >> 15
    x = (x * 0x31848BAB) & _MASK32
    x ^= x >> 14
    return x


def _triple32_array(x: U32Array) -> U32Array:
    """triple32 elementwise; uint32 array arithmetic wraps mod 2^32."""
    x = x.copy()
    x ^= x >> 17
    x *= np.uint32(0xED5AD4BB)
    x ^= x >> 11
    x *= np.uint32(0xAC4C1B51)
    x ^= x >> 15
    x *= np.uint32(0x31848BAB)
    x ^= x >> 14
    return x


def tpdf(x: int, y: int, frame_index: int, channel: int) -> int:
    """D = triple32(seed) - triple32(seed ^ 0x68BC21EB): an exact integer in
    (-2^32, 2^32); D * 2^-32 is triangular on (-1, 1)."""
    _check(frame_index)
    if x < 0 or y < 0 or not 0 <= channel <= 2:
        raise ValueError("x, y must be non-negative and channel in 0..2")
    seed = (
        ((x * _SEED_X) & _MASK32)
        ^ ((y * _SEED_Y) & _MASK32)
        ^ ((frame_index * _SEED_FRAME) & _MASK32)
        ^ ((channel * _SEED_CHANNEL) & _MASK32)
    )
    return triple32(seed) - triple32(seed ^ _SECOND)


def tpdf_frame(width: int, height: int, frame_index: int = 0) -> NDArray[np.int64]:
    """D for every pixel and channel of a frame: (height, width, 3) int64."""
    _check(frame_index)
    xs = np.arange(width, dtype=np.uint32) * np.uint32(_SEED_X)
    ys = np.arange(height, dtype=np.uint32) * np.uint32(_SEED_Y)
    base = ys[:, None] ^ xs[None, :] ^ np.uint32((frame_index * _SEED_FRAME) & _MASK32)
    out = np.empty((height, width, 3), dtype=np.int64)
    for channel in range(3):
        seed = base ^ np.uint32((channel * _SEED_CHANNEL) & _MASK32)
        first = _triple32_array(seed).astype(np.int64)
        second = _triple32_array(seed ^ np.uint32(_SECOND)).astype(np.int64)
        out[:, :, channel] = first - second
    return out


def _check(frame_index: int) -> None:
    if not 0 <= frame_index <= _MASK32:
        raise ValueError("frame_index must be in [0, 2^32)")
