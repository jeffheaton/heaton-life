"""Evolving MergeLife rules (Heaton 2017, Secs. 4-5) — spec/evolve.md.

Faithful port of the reference objective statistics and GA operators
(github.com/jeffheaton/mergelife), with one deliberate change: all randomness
flows through PCG32, so scoring and whole evolution runs replay from a seed.
"""

from heaton_life.evolve.ga import Evolver, crossover, mutate, tournament_select
from heaton_life.evolve.objective import (
    PAPER_OBJECTIVE,
    ObjectiveRule,
    largest_rectangle_area,
    score_genome,
)

__all__ = [
    "PAPER_OBJECTIVE",
    "Evolver",
    "ObjectiveRule",
    "crossover",
    "largest_rectangle_area",
    "mutate",
    "score_genome",
    "tournament_select",
]
