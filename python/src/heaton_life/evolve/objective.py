"""The MergeLife objective function (paper Sec. 4), ported from the reference engine.

A candidate rule is scored by running it from a random lattice until it converges
(paper Sec. 4.1), then measuring five statistics of the run:

- steps:      CA generations until convergence
- foreground: fraction of cells stably holding a non-background color (>5 gens)
- active:     fraction of cells that recently were background but no longer are
- rect:       largest all-background rectangle, as a fraction of the grid
- mage:       how long the current background (mode) color has persisted

Each objective rule scores one statistic against [min, max]: inside the range the
contribution rises to `weight` at the midpoint; outside it is the flat penalty
`min_weight` / `max_weight`. The reference tracks statistics on the *merged*
(grayscale) lattice of the previous two generations; this port reproduces that
bookkeeping exactly, including its one-generation lag.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from heaton_life.ca import MergeLife

MAX_STEPS = 1000  # paper Sec. 4.1: hard stop


@dataclasses.dataclass(frozen=True)
class ObjectiveRule:
    stat: str
    min: float
    max: float
    weight: float
    min_weight: float
    max_weight: float


# examples/paperObjective.json from the reference repository.
PAPER_OBJECTIVE: tuple[ObjectiveRule, ...] = (
    ObjectiveRule("steps", 300, 1000, 1, -1, 1),
    ObjectiveRule("foreground", 0.001, 0.1, 1, -0.1, -1),
    ObjectiveRule("active", 0.001, 0.1, 1, -1, -1),
    ObjectiveRule("rect", 0.02, 0.25, 2, -2, 2),
    ObjectiveRule("mage", 5, 10, 0, -5, 0),
)


def _merged(state: NDArray[np.uint8]) -> NDArray[np.int64]:
    result: NDArray[np.int64] = state.astype(np.int64).sum(axis=2) // 3
    return result


class _RunEvaluator:
    """Streams the reference's per-step statistics over one MergeLife run.

    Mirrors calc_objective_stats/is_lattice_stable: 'e1' is the merged lattice of
    the state *before* the latest step, 'e2' one step earlier (the reference
    stores evals with exactly this lag).
    """

    def __init__(self, height: int, width: int) -> None:
        self.height = height
        self.width = width
        self.time_step = 0
        self.e1: tuple[NDArray[np.int64], int] | None = None
        self.e2: tuple[NDArray[np.int64], int] | None = None
        self.mode_cnt = np.zeros((height, width), dtype=np.int64)
        self.same_cnt = np.zeros((height, width), dtype=np.int64)
        self.last_mode = np.zeros((height, width), dtype=np.int64)
        self.last_change = np.zeros((height, width), dtype=np.int64)
        self.mode_age = 0
        self.last_mode_val: int | None = None
        self.mc_nochange = 0
        self.last_mc = 0

    def step(self, sim: MergeLife) -> None:
        avg = _merged(sim.state)
        mode = int(np.bincount(avg.ravel()).argmax())
        sim.step(1)
        self.e2 = self.e1
        self.e1 = (avg, mode)
        self.time_step += 1

    def stats(self) -> dict[str, float]:
        size = self.height * self.width
        if self.e1 is None or self.e2 is None:
            return {"mage": 0, "mode": 0, "mc": 0, "bg": 0, "fg": 0, "act": 0, "chaos": 0}
        d1_avg, _ = self.e1
        d2_avg, md2 = self.e2

        mode_mask = d2_avg == md2
        self.mode_cnt[~mode_mask] = 0
        self.mode_cnt += mode_mask
        mc = int(np.sum(self.mode_cnt > 100))

        same_mask = (d1_avg == d2_avg) & ~mode_mask
        self.same_cnt[~same_mask] = 0
        self.same_cnt += same_mask
        sc = int(np.sum(self.same_cnt > 5))

        if self.last_mode_val is None or self.last_mode_val != md2:
            self.last_mode_val = md2
            self.mode_age = 0
        else:
            self.mode_age += 1

        self.last_mode[mode_mask] = self.time_step

        if self.time_step >= 25:
            since = self.time_step - self.last_mode
            active = int(np.sum((since > 5) & (since < 25)))
        else:
            active = 0

        return {
            "mage": self.mode_age,
            "mode": md2,
            "mc": mc,
            "bg": mc / size,
            "fg": sc / size,
            "act": active / size,
            "chaos": (size - (mc + sc + active)) / size,
        }

    def is_stable(self, stats: dict[str, float]) -> bool:
        if self.e1 is not None and self.e2 is not None:
            self.last_change[self.e1[0] != self.e2[0]] = self.time_step
        if self.time_step > 100:
            changed_recently = int(np.sum((self.time_step - self.last_change) < 100))
            if changed_recently < 0.01 * self.height * self.width:
                return True
        if self.last_mc == stats["mc"]:
            self.mc_nochange += 1
            if self.mc_nochange > 100:
                return True
        else:
            self.mc_nochange = 0
            self.last_mc = int(stats["mc"])
        return self.time_step > MAX_STEPS

    def largest_rect_fraction(self, stats: dict[str, float]) -> float:
        assert self.e2 is not None
        mask = self.e2[0] == stats["mode"]
        return largest_rectangle_area(mask) / (self.height * self.width)


def largest_rectangle_area(mask: NDArray[np.bool_]) -> int:
    """Area of the largest axis-aligned all-True rectangle (histogram-stack method)."""
    heights = np.zeros(mask.shape[1], dtype=np.int64)
    best = 0
    for row in mask:
        heights = np.where(row, heights + 1, 0)
        best = max(best, _max_histogram_area(heights))
    return best


def _max_histogram_area(heights: NDArray[np.int64]) -> int:
    stack: list[tuple[int, int]] = []  # (start index, height)
    best = 0
    pos = 0
    for pos, height in enumerate(heights):
        start = pos
        while stack and height < stack[-1][1]:
            begin, tall = stack.pop()
            best = max(best, int(tall) * (pos - begin))
            start = begin
        if not stack or height > stack[-1][1]:
            stack.append((start, int(height)))
    end = pos + 1 if heights.size else 0
    for begin, tall in stack:
        best = max(best, tall * (end - begin))
    return best


def _run_once(
    genome: str, size: tuple[int, int], seed: int, max_steps: int
) -> dict[str, float]:
    """One convergence run: the reference's calc_objective_function body."""
    width, height = size
    sim = MergeLife(genome, size=size, seed=seed)
    ev = _RunEvaluator(height, width)
    while True:
        ev.step(sim)
        stats = ev.stats()
        if ev.time_step >= max_steps or ev.is_stable(stats):
            break
    return {
        "steps": ev.time_step,
        "foreground": stats["fg"],
        "active": stats["act"],
        "rect": ev.largest_rect_fraction(stats),
        "mage": stats["mage"],
    }


def _score_stats(stats: dict[str, float], objective: Sequence[ObjectiveRule]) -> float:
    score = 0.0
    for rule in objective:
        actual = stats[rule.stat]
        span = rule.max - rule.min
        # Verbatim from the reference: the in-range peak sits at `span/2`, NOT at
        # the interval midpoint (min + span/2). Faithfulness beats aesthetics here;
        # scores must be comparable with the reference trainer's.
        ideal = span / 2
        if actual < rule.min:
            adjust = rule.min_weight
        elif actual > rule.max:
            adjust = rule.max_weight
        else:
            adjust = ((span / 2) - abs(actual - ideal)) / (span / 2)
            adjust *= rule.weight
        score += adjust
    return score


def score_genome(
    genome: str,
    objective: Sequence[ObjectiveRule] = PAPER_OBJECTIVE,
    *,
    cycles: int = 5,
    size: tuple[int, int] = (100, 100),
    seed: int = 0,
    max_steps: int = MAX_STEPS,
) -> dict[str, float]:
    """Best score over `cycles` seeded runs (the reference takes the max too).

    Deterministic: cycle i runs from seed `seed + i`.
    """
    scores = []
    steps = 0
    for i in range(cycles):
        stats = _run_once(genome, size, seed + i, max_steps)
        scores.append(_score_stats(stats, objective))
        steps += int(stats["steps"])
    return {"score": float(np.max(scores)), "time_step": float(steps)}
