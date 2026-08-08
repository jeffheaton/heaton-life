# Evolving MergeLife rules (paper Secs. 4-5)

Not a conformance family — a search procedure over the [MergeLife](mergelife.md)
genome space, ported from the reference trainer (github.com/jeffheaton/mergelife).

## Objective statistics (Sec. 4)

A rule is scored by running it from a random lattice until convergence, then
measuring, on the *merged* (grayscale) lattice with the reference's one-generation
bookkeeping lag:

| stat | meaning |
|---|---|
| `steps` | generations until convergence (hard cap 1000) |
| `foreground` | fraction of cells stably non-background (>5 gens, not the mode) |
| `active` | fraction recently background (5–25 gens ago) but no longer |
| `rect` | largest all-background rectangle / grid area (histogram-stack DP) |
| `mage` | generations the current background (mode) color has persisted |

Convergence (Sec. 4.1): <1% of merged cells changed in the last 100 generations,
OR the stable-background count unchanged for 100 generations, OR 1000 generations.

Each objective rule scores one stat: below `min` → `min_weight`; above `max` →
`max_weight`; inside, a tent function scaled by `weight` — peaked, verbatim from
the reference, at `(max−min)/2` (not the interval midpoint; faithfulness wins).
The score of a genome is the **max** over `evalCycles` independent runs.
`PAPER_OBJECTIVE` reproduces `examples/paperObjective.json`.

## GA operators (Sec. 5)

- **Mutation**: exchange two random, distinct, non-dash characters (a permutation
  of the genome's digits).
- **Crossover**: two cut points exactly 5 characters apart (one sub-rule plus a
  dash); the two children are complementary middle-splice swaps.
- **Selection**: best-of-5 tournament; eviction uses worst-of-5.
- Steady state: crossover with probability 0.75, else mutation; stop after
  `patience` evaluations without improvement.

## Determinism (deliberate deviation)

The reference uses numpy's global RNG. This implementation draws every random
decision — lattice seeds, operator choices, cut points — from PCG32 streams, so
`score_genome(...)` and entire `Evolver` runs replay exactly from their seed.
Scores are comparable with the reference trainer's, but runs are reproducible.
