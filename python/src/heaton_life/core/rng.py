"""PCG32 — the spec-pinned RNG (spec/rng.md).

Simulation state must only ever be seeded through this generator, never through
numpy or the standard library, so that runs replay identically across languages.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

_MULT = 6364136223846793005
_MASK64 = (1 << 64) - 1
_MASK32 = (1 << 32) - 1


class Pcg32:
    """Minimal PCG32 (XSH-RR variant), matching the pcg_basic reference implementation."""

    __slots__ = ("_inc", "_state")

    def __init__(self, seed: int, seq: int = 0) -> None:
        self._state = 0
        self._inc = ((seq << 1) | 1) & _MASK64
        self.next_u32()
        self._state = (self._state + (seed & _MASK64)) & _MASK64
        self.next_u32()

    def next_u32(self) -> int:
        """Advance one step and return a uniform 32-bit unsigned integer."""
        old = self._state
        self._state = (old * _MULT + self._inc) & _MASK64
        xorshifted = (((old >> 18) ^ old) >> 27) & _MASK32
        rot = old >> 59
        return ((xorshifted >> rot) | (xorshifted << (32 - rot))) & _MASK32

    def fill_u32(self, n: int) -> NDArray[np.uint32]:
        """Return the next ``n`` outputs as a uint32 array (draw order is part of the spec)."""
        return np.fromiter((self.next_u32() for _ in range(n)), dtype=np.uint32, count=n)
