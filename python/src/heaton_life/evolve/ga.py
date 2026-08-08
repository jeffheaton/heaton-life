"""GA operators and trainer for MergeLife genomes (paper Sec. 5).

Operators are verbatim ports of the reference: mutation exchanges two distinct
hex digits (dashes untouched); crossover cuts the dashed string at two points
CUT_LENGTH apart (one sub-rule plus a dash) and swaps the middle; selection is
best-of-N tournament. The trainer differs from the reference in exactly one way:
every random decision draws from one PCG32 stream, so a run replays from its seed.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence

from heaton_life.ca import random_genome
from heaton_life.core.rng import Pcg32
from heaton_life.evolve.objective import PAPER_OBJECTIVE, ObjectiveRule, score_genome

CUT_LENGTH = 5  # paper Sec. 5.2: one 4-digit sub-rule plus a dash


def mutate(genome: str, rng: Pcg32) -> str:
    """Exchange two random, distinct, non-dash characters (paper Sec. 5.3)."""
    if len(set(genome) - {"-"}) < 2:
        return genome  # all digits identical: no swap can change anything
    while True:
        i = rng.next_u32() % len(genome)
        j = rng.next_u32() % len(genome)
        if genome[i] != "-" and genome[j] != "-" and genome[i] != genome[j]:
            lo, hi = (i, j) if i < j else (j, i)
            return (
                genome[:lo] + genome[hi] + genome[lo + 1 : hi] + genome[lo] + genome[hi + 1 :]
            )


def crossover(genome1: str, genome2: str, rng: Pcg32, cut_length: int = CUT_LENGTH) -> list[str]:
    """Two complementary children; the middle splice swaps parents (paper Sec. 5.2)."""
    cut1 = rng.next_u32() % (len(genome1) - cut_length)
    cut2 = cut1 + cut_length
    return [
        genome1[:cut1] + genome2[cut1:cut2] + genome1[cut2:],
        genome2[:cut1] + genome1[cut1:cut2] + genome2[cut2:],
    ]


def tournament_select(
    scores: Sequence[float], rounds: int, rng: Pcg32, *, worst: bool = False
) -> int:
    """Best-of-`rounds` tournament over indices (or worst-of, for eviction)."""
    winner: int | None = None
    for _ in range(rounds):
        challenger = rng.next_u32() % len(scores)
        if winner is None:
            winner = challenger
        elif worst:
            if scores[challenger] < scores[winner]:
                winner = challenger
        elif scores[challenger] > scores[winner]:
            winner = challenger
    assert winner is not None
    return winner


@dataclasses.dataclass
class Candidate:
    genome: str
    score: float


class Evolver:
    """Steady-state GA over MergeLife genomes, deterministic from `seed`."""

    def __init__(
        self,
        objective: Sequence[ObjectiveRule] = PAPER_OBJECTIVE,
        *,
        size: tuple[int, int] = (100, 100),
        population_size: int = 100,
        crossover_rate: float = 0.75,
        tournament_rounds: int = 5,
        eval_cycles: int = 5,
        patience: int = 1000,
        max_steps: int = 1000,
        seed: int = 0,
        on_progress: Callable[[Evolver], None] | None = None,
    ) -> None:
        self.objective = tuple(objective)
        self.size = size
        self.population_size = population_size
        self.crossover_rate = crossover_rate
        self.tournament_rounds = tournament_rounds
        self.eval_cycles = eval_cycles
        self.patience = patience
        self.max_steps = max_steps
        self.seed = seed
        self.on_progress = on_progress
        self.rng = Pcg32(seed, 1)  # seq 1: distinct stream from sim seeding
        self.population: list[Candidate] = []
        self.best: Candidate | None = None
        self.evals = 0
        self.no_improvement = 0

    def _score(self, genome: str) -> Candidate:
        result = score_genome(
            genome,
            self.objective,
            cycles=self.eval_cycles,
            size=self.size,
            seed=self.seed + self.evals * self.eval_cycles,
            max_steps=self.max_steps,
        )
        self.evals += 1
        candidate = Candidate(genome, result["score"])
        if self.on_progress is not None:
            self.on_progress(self)
        return candidate

    def _admit(self, genome: str) -> None:
        while len(self.population) + 1 > self.population_size:
            scores = [c.score for c in self.population]
            evict = tournament_select(scores, self.tournament_rounds, self.rng, worst=True)
            del self.population[evict]
        candidate = self._score(genome)
        self.population.append(candidate)
        if self.best is None or candidate.score > self.best.score:
            self.best = candidate
            self.no_improvement = 0
        else:
            self.no_improvement += 1

    def run(self, max_evals: int) -> Candidate:
        """Seed a random population, then evolve until max_evals or patience runs out."""
        while len(self.population) < self.population_size and self.evals < max_evals:
            self._admit(random_genome(self.rng.next_u32()))
        while self.evals < max_evals and self.no_improvement <= self.patience:
            scores = [c.score for c in self.population]
            if len(scores) > 1 and (self.rng.next_u32() / 4294967296.0) < self.crossover_rate:
                first = tournament_select(scores, self.tournament_rounds, self.rng)
                second = first
                while second == first:
                    second = tournament_select(scores, self.tournament_rounds, self.rng)
                parent1 = self.population[first].genome
                parent2 = self.population[second].genome
                if parent1 != parent2:
                    for child in crossover(parent1, parent2, self.rng):
                        self._admit(child)
            else:
                parent_idx = tournament_select(scores, self.tournament_rounds, self.rng)
                self._admit(mutate(self.population[parent_idx].genome, self.rng))
        assert self.best is not None
        return self.best
