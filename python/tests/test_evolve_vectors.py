"""Evolve conformance: replay vectors/evolve/ — objective stats per seeded run,
GA operator sequences, and one end-to-end mini evolution run. Bit-exact tier;
the same files the .NET suite replays."""

import json
from pathlib import Path

import numpy as np
import pytest

from heaton_life.core.rng import Pcg32
from heaton_life.evolve import Evolver, crossover, mutate, tournament_select
from heaton_life.evolve.objective import PAPER_OBJECTIVE, _run_once, _score_stats

VECTOR_ROOT = Path(__file__).resolve().parents[2] / "vectors" / "evolve"

CASES = sorted(VECTOR_ROOT.glob("*/params.json"))


def _f64(path: Path) -> np.ndarray:
    return np.frombuffer(path.read_bytes(), dtype="<f8")


def test_evolve_vectors_exist() -> None:
    kinds = {json.loads(c.read_text())["kind"] for c in CASES}
    assert kinds == {"objective", "operators", "run"}


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.parent.name)
def test_evolve_vector(case: Path) -> None:
    meta = json.loads(case.read_text())
    assert meta["tier"] == "bit-exact"
    p = meta["params"]
    if meta["kind"] == "objective":
        assert p["objective"] == "paper"
        expected_runs = _f64(case.parent / meta["outputs"]["runs"]["file"]).reshape(
            tuple(meta["outputs"]["runs"]["shape"])
        )
        runs = np.empty_like(expected_runs)
        for i in range(p["cycles"]):
            stats = _run_once(
                p["genome"], (p["width"], p["height"]), p["seed"] + i, p["max_steps"]
            )
            runs[i] = [
                stats["steps"], stats["foreground"], stats["active"],
                stats["rect"], stats["mage"], _score_stats(stats, PAPER_OBJECTIVE),
            ]
        assert np.array_equal(runs, expected_runs)
        expected_score = _f64(case.parent / meta["outputs"]["score"]["file"])
        assert np.array_equal(
            np.array([runs[:, 5].max(), runs[:, 0].sum()]), expected_score
        )
    elif meta["kind"] == "operators":
        rng = Pcg32(p["mutate_seed"])
        genome = p["genome"]
        for expected in meta["expected"]["mutations"]:
            genome = mutate(genome, rng)
            assert genome == expected
        rng = Pcg32(p["crossover_seed"])
        for expected_pair in meta["expected"]["crossovers"]:
            assert crossover(p["genome"], p["parent2"], rng) == expected_pair
        rng = Pcg32(p["tournament_seed"])
        scores = p["tournament_scores"]
        rounds = p["tournament_rounds"]
        for expected_idx in meta["expected"]["winners_best"]:
            assert tournament_select(scores, rounds, rng) == expected_idx
        for expected_idx in meta["expected"]["winners_worst"]:
            assert tournament_select(scores, rounds, rng, worst=True) == expected_idx
    else:  # run
        evolver = Evolver(
            size=(p["width"], p["height"]),
            population_size=p["population_size"],
            crossover_rate=p["crossover_rate"],
            tournament_rounds=p["tournament_rounds"],
            eval_cycles=p["eval_cycles"],
            patience=p["patience"],
            max_steps=p["max_steps"],
            seed=p["seed"],
        )
        best = evolver.run(max_evals=p["max_evals"])
        assert best.genome == meta["expected"]["best_genome"]
        assert evolver.evals == meta["expected"]["evals"]
        assert [c.genome for c in evolver.population] == meta["expected"]["population"]
        expected_best = _f64(case.parent / meta["expected"]["best_score"]["file"])
        assert np.array_equal(np.array([best.score]), expected_best)
