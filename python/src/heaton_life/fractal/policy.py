"""Iteration policy -- spec/fractals.md "Iteration policy" (policy version 1).

How many iterations a frame deserves is a host's choice, not part of what a count
means, so the policy is versioned apart from the counts: changing it changes which
max_iter a host asks for, never what a given max_iter renders. Integer and pinned
float arithmetic only -- no libm pow -- so every port suggests the same budget.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray

__all__ = ["auto_max_iter", "need_from_counts", "suggest_max_iter"]


MAX_SUGGESTION = 2**31 - 1  # a count is an int32


def auto_max_iter(zoom_log10: float) -> int:
    """The depth ramp: 400 + round(200 * max(0, zoom)), rounding half to even, capped at
    the largest int32 (reached near zoom 1.07e7)."""
    if not math.isfinite(zoom_log10):
        raise ValueError(f"zoom must be finite, got {zoom_log10!r}")
    scaled = 200.0 * max(0.0, zoom_log10)
    if scaled >= 2.0**31:  # past the cap (and past round() once it overflows to inf)
        return MAX_SUGGESTION
    return min(400 + round(scaled), MAX_SUGGESTION)


def need_from_counts(counts: NDArray[np.integer]) -> int:
    """The iteration by which 99.9% of a frame's escaped pixels escaped: the
    nearest-rank 99.9th percentile of the positive counts, rank ceil(0.999 n) computed
    in integers; 0 when nothing escaped."""
    escaped = np.sort(np.asarray(counts).ravel()[np.asarray(counts).ravel() > 0])
    n = int(escaped.size)
    if n == 0:
        return 0
    rank = (999 * n + 999) // 1000  # ceil(999 n / 1000), 1-based
    return int(escaped[rank - 1])


def suggest_max_iter(zoom_log10: float, counts: NDArray[np.integer]) -> int:
    """max(the depth ramp, twice what the frame's own escapes needed), capped at the
    largest int32."""
    return min(max(auto_max_iter(zoom_log10), 2 * need_from_counts(counts)), MAX_SUGGESTION)
