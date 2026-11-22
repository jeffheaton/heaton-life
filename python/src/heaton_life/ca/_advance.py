"""Advance Selection and Advance Outside for the grid families (spec/patterns.md "Editing a
region"): life-like, wireworld, and cyclic, whose blank is 0."""

from __future__ import annotations

import operator

import numpy as np
from numpy.typing import NDArray

from heaton_life.init.patterns import check_region


class AdvanceRegion:
    """Adds ``advance_selection``, ``advance_outside`` and ``cancel`` to a grid family that
    keeps its cells in ``_state`` (indexed ``[y, x]``, blank 0), counts generations in
    ``_generation``, and evolves with ``step`` under its own rule and boundary."""

    _state: NDArray[np.uint8]
    _generation: int
    _cancel_requested: bool = False

    def step(self, n: int = 1) -> None:  # the family's own
        raise NotImplementedError

    def advance_selection(self, x0: int, y0: int, x1: int, y1: int, n: int = 1) -> None:
        """Evolve the region (x0, y0)..(x1, y1), inclusive, ``n`` generations as if nothing
        else existed: a copy of the world blank outside it runs ``n`` generations under the
        world's rule and boundary (a torus wraps), and its region is copied back. Cells
        outside the region and the generation counter are untouched. ``cancel()`` from
        another thread stops it between generations with ``StepCanceled``, the world as it
        was."""
        self._advance(x0, y0, x1, y1, n, outside=False)

    def advance_outside(self, x0: int, y0: int, x1: int, y1: int, n: int = 1) -> None:
        """Advance Selection's mirror image: the world with the region blank runs ``n``
        generations and everything outside the region is copied back; the region keeps its
        cells, and the generation counter stays. ``cancel()`` stops it as it does
        ``advance_selection``."""
        self._advance(x0, y0, x1, y1, n, outside=True)

    def cancel(self) -> None:
        """Ask a running ``advance_selection`` or ``advance_outside`` (on another thread) to
        stop between generations (spec/patterns.md "Editing a region", "Canceling"): it
        raises ``StepCanceled``, HashLife's, and leaves the world exactly as it was. As with
        ``HashLife.cancel``, an advance starts by forgetting any earlier request."""
        self._cancel_requested = True

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
        self._cancel_requested = False
        self._state = copy
        try:
            for _ in range(n):
                if self._cancel_requested:
                    raise _canceled(generation)
                self.step(1)
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


def _canceled(generation: int) -> Exception:
    """The error a canceled advance raises: HashLife's ``StepCanceled``, so one ``except``
    catches a canceled step or advance of either kind of world."""
    # Imported here: heaton_life.ca.hashlife imports the package this module belongs to.
    from heaton_life.ca.hashlife.universe import StepCanceled

    return StepCanceled(f"canceled; the world is at generation {generation}")
