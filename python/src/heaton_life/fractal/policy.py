"""Iteration policy -- spec/fractals.md "Iteration policy" (policy version 1).

How many iterations a frame deserves is a host's choice, not part of what a count
means, so the policy is versioned apart from the counts: changing it changes which
max_iter a host asks for, never what a given max_iter renders. Integer and pinned
float arithmetic only -- no libm pow -- so every port suggests the same budget.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "auto_max_iter",
    "measured_max_iter",
    "movie_max_iter",
    "need_at",
    "need_from_counts",
    "suggest_max_iter",
]


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


# --- movies (spec/zoom.md "Iteration budget") ------------------------------------------


def movie_max_iter(
    zoom_log10: float, target_zoom_log10: float, user_limit: int | None = None
) -> int:
    """A movie frame's budget. Without a limit, the depth ramp. With a user limit U
    (1 <= U <= 2^31 - 1), the ramp scaled so it reaches exactly U at the target:
    min(U, max(a, (U * a) // a_T)) with a = auto_max_iter(zoom), a_T =
    auto_max_iter(target), in exact integers (64-bit in a port with fixed-width ints)."""
    ramp = auto_max_iter(zoom_log10)
    if user_limit is None:
        return ramp
    _check_limit(user_limit)
    scaled = (user_limit * ramp) // auto_max_iter(target_zoom_log10)
    return min(user_limit, max(ramp, scaled))


def need_at(zoom_log10: float, knots: Sequence[tuple[float, int]]) -> int:
    """The measured need at a depth, from a survey's knots (zoom, need) in ascending zoom
    order: the larger of the two knots around it; the nearer knot's past either end; at a
    knot, the largest of it and its two neighbors. No knots: 0."""
    if not math.isfinite(zoom_log10):
        raise ValueError(f"zoom must be finite, got {zoom_log10!r}")
    if not knots:
        return 0
    for index, (zoom, _) in enumerate(knots):
        if zoom == zoom_log10:
            around = knots[max(0, index - 1) : index + 2]
            return max(need for _, need in around)
    if not zoom_log10 > knots[0][0]:
        return knots[0][1]
    if not zoom_log10 < knots[-1][0]:
        return knots[-1][1]
    deeper = next(i for i, (zoom, _) in enumerate(knots) if zoom > zoom_log10)
    return max(knots[deeper - 1][1], knots[deeper][1])


def measured_max_iter(zoom_log10: float, knots: Sequence[tuple[float, int]]) -> int:
    """A movie frame's budget from a survey (Heaton Fractal's measured mode):
    min(max(auto_max_iter(zoom), 2 * need_at(zoom, knots)), 2^31 - 1)."""
    return min(max(auto_max_iter(zoom_log10), 2 * need_at(zoom_log10, knots)), MAX_SUGGESTION)


def _check_limit(user_limit: int) -> None:
    if isinstance(user_limit, bool) or not isinstance(user_limit, int):
        raise TypeError("an iteration limit must be an int")
    if not 1 <= user_limit <= MAX_SUGGESTION:
        raise ValueError(f"an iteration limit must lie in [1, 2^31 - 1], got {user_limit}")
