import numpy as np
import pytest

from heaton_life.core.rng import Pcg32
from heaton_life.evolve import (
    PAPER_OBJECTIVE,
    Evolver,
    crossover,
    largest_rectangle_area,
    mutate,
    score_genome,
    tournament_select,
)

REDWORLD = "e542-5f79-9341-f31e-6c6b-7f08-8773-7068"


def test_largest_rectangle_known_cases() -> None:
    # Reference doctest cases (histogram method), expressed as masks.
    mask = np.array([[1, 1, 1], [1, 1, 0], [1, 0, 0]], dtype=bool)
    assert largest_rectangle_area(mask) == 4  # 2x2 top-left
    assert largest_rectangle_area(np.ones((3, 5), dtype=bool)) == 15
    assert largest_rectangle_area(np.zeros((3, 5), dtype=bool)) == 0
    ragged = np.array([[1, 0, 1, 1, 1], [1, 1, 1, 1, 0], [0, 1, 1, 1, 0]], dtype=bool)
    assert largest_rectangle_area(ragged) == 6  # cols 1-3 x rows 1-2... verified by brute force


def test_largest_rectangle_matches_bruteforce() -> None:
    rng = np.random.default_rng(1)  # test-only randomness, not simulation state
    for _ in range(20):
        mask = rng.random((7, 9)) < 0.6

        def brute(m: np.ndarray) -> int:
            best = 0
            h, w = m.shape
            for y0 in range(h):
                for y1 in range(y0, h):
                    for x0 in range(w):
                        for x1 in range(x0, w):
                            if m[y0 : y1 + 1, x0 : x1 + 1].all():
                                best = max(best, (y1 - y0 + 1) * (x1 - x0 + 1))
            return best

        assert largest_rectangle_area(mask) == brute(mask)


def test_mutate_is_a_digit_swap() -> None:
    rng = Pcg32(7)
    child = mutate(REDWORLD, rng)
    assert child != REDWORLD
    assert sorted(child) == sorted(REDWORLD), "mutation must be a permutation"
    assert [i for i, ch in enumerate(child) if ch == "-"] == [
        i for i, ch in enumerate(REDWORLD) if ch == "-"
    ], "dashes must not move"


def test_mutate_degenerate_genome_unchanged() -> None:
    flat = "0000-0000-0000-0000-0000-0000-0000-0000"
    assert mutate(flat, Pcg32(1)) == flat


def test_crossover_children_are_complementary() -> None:
    rng = Pcg32(3)
    parent1 = "a" * 4 + "-" + "b" * 4 + "-" + "c" * 4  # simple dashed strings
    parent2 = "x" * 4 + "-" + "y" * 4 + "-" + "z" * 4
    child1, child2 = crossover(parent1, parent2, rng)
    assert len(child1) == len(parent1) and len(child2) == len(parent2)
    for i in range(len(parent1)):
        if child1[i] == parent2[i]:
            assert child2[i] == parent1[i]  # swapped region is mirrored
        else:
            assert child1[i] == parent1[i] and child2[i] == parent2[i]


def test_tournament_prefers_high_scores() -> None:
    # The peak wins iff it is sampled at all: p = 1 - (3/4)^5 = 0.763 over 4 entries.
    scores = [0.0, 10.0, 0.0, 0.0]
    wins = sum(tournament_select(scores, 5, Pcg32(s)) == 1 for s in range(60))
    assert 35 < wins < 60  # expect ~46; a uniform pick would give ~15
    evictions = sum(
        tournament_select([5.0, -9.0, 5.0], 5, Pcg32(s), worst=True) == 1 for s in range(60)
    )
    assert evictions > 42  # p = 1 - (2/3)^5 = 0.868, expect ~52


def test_score_genome_deterministic_and_bounded() -> None:
    a = score_genome(REDWORLD, cycles=1, size=(32, 32), seed=5, max_steps=200)
    b = score_genome(REDWORLD, cycles=1, size=(32, 32), seed=5, max_steps=200)
    assert a == b
    max_possible = sum(max(r.weight, r.min_weight, r.max_weight) for r in PAPER_OBJECTIVE)
    min_possible = sum(min(r.weight, r.min_weight, r.max_weight) for r in PAPER_OBJECTIVE)
    assert min_possible <= a["score"] <= max_possible


def test_interesting_rule_outscores_degenerate() -> None:
    # An all-zero-percent genome never changes any cell: no foreground, no activity.
    dead = "0000-0000-0000-0000-0000-0000-0000-0000"
    lively = score_genome(REDWORLD, cycles=2, size=(48, 48), seed=1, max_steps=400)
    boring = score_genome(dead, cycles=2, size=(48, 48), seed=1, max_steps=400)
    assert lively["score"] > boring["score"]


@pytest.mark.slow
def test_evolver_runs_and_is_deterministic() -> None:
    def small() -> Evolver:
        return Evolver(
            size=(24, 24),
            population_size=4,
            eval_cycles=1,
            max_steps=120,
            patience=50,
            seed=11,
        )

    best1 = small().run(max_evals=10)
    best2 = small().run(max_evals=10)
    assert best1.genome == best2.genome
    assert best1.score == best2.score
