"""Advance Selection and Advance Outside for the grid families (spec/patterns.md "Editing a
region"): life-like, wireworld, and cyclic, whose blank is 0."""

from __future__ import annotations

import operator

import numpy as np
from numpy.typing import NDArray

from heaton_life.init.patterns import check_region


class AdvanceRegion:
    """Adds ``advance_selection`` and ``advance_outside`` to a grid family that keeps its
    cells in ``_state`` (indexed ``[y, x]``, blank 0), counts generations in
    ``_generation``, and evolves with ``step`` under its own rule and boundary."""

    _state: NDArray[np.uint8]
    _generation: int

    def step(self, n: int = 1) -> None:  # the family's own
        raise NotImplementedError

    def advance_selection(self, x0: int, y0: int, x1: int, y1: int, n: int = 1) -> None:
        """Evolve the region (x0, y0)..(x1, y1), inclusive, ``n`` generations as if nothing
        else existed: a copy of the world blank outside it runs ``n`` generations under the
        world's rule and boundary (a torus wraps), and its region is copied back. Cells
        outside the region and the generation counter are untouched."""
        self._advance(x0, y0, x1, y1, n, outside=False)

    def advance_outside(self, x0: int, y0: int, x1: int, y1: int, n: int = 1) -> None:
        """Advance Selection's mirror image: the world with the region blank runs ``n``
        generations and everything outside the region is copied back; the region keeps its
        cells, and the generation counter stays."""
        self._advance(x0, y0, x1, y1, n, outside=True)

    def _advance(self, x0: int, y0: int, x1: int, y1: int, n: int, *, outside: bool) -> None:
        x0, y0, x1, y1, n = (operator.index(v) for v in (x0, y0, x1, y1, n))
        height, width = self._state.shape
        check_region(width, height, x0, y0, x1, y1)
        if n < 0:
            raise ValueError(f"cannot advance backward ({n} generations)")
        saved, generation = self._state, self._generation
        region = (slice(y0, y1 + 1), slice(x0, x1 + 1))
        if outside:
            copy = saved.copy()
            copy[region] = 0
        else:
            copy = np.zeros_like(saved)
            copy[region] = saved[region]
        self._state = copy
        try:
            self.step(n)
            grown = self._state
        finally:
            self._state, self._generation = saved, generation
        if outside:
            result = grown.copy()
            result[region] = saved[region]
        else:
            result = saved.copy()
            result[region] = grown[region]
        self._state = result
