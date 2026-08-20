# Evolving MergeLife rules (paper Secs. 4-5)

A search procedure over the [MergeLife](mergelife.md) genome space, ported from
the reference trainer (github.com/jeffheaton/mergelife). Because every random
decision is PCG32-seeded, it is *also* a conformance family: scoring and whole
runs replay bit-exact across languages (see Conformance below).

## Objective statistics (Sec. 4, 2018 trainer semantics)

A rule is scored by running it from a random lattice until convergence, then
measuring, on the *merged* (grayscale) lattice with the reference's one-generation
bookkeeping lag:

| stat | meaning |
|---|---|
| `steps` | generations until convergence (cap: a capped run records `max_steps + 1`) |
| `foreground` | fraction of cells stably non-background (>5 gens, not the mode) |
| `active` | fraction recently background (5–25 gens ago) but no longer |
| `rect` | largest all-background rectangle / grid area (histogram-stack DP) |
| `mage` | generations the current background (mode) color has persisted |

A **stable background** cell has held the mode color for **more than 50
consecutive generations** (the 2018 trainer's threshold; the paper's prose says
100, but every published score came from the trainer).

Convergence — deliberately the **2018 reference trainer's** detector, not the
paper Sec. 4.1 text (measured 2026-08: the Sec. 4.1 detector reads every world,
lively or static, as converged at ~101 generations — the stable-background
count is structurally zero for the first 100 generations, so its freeze counter
always fires; scoring under it inverts the historical score scale and ranks the
canonical gallery rules at or below zero). A run ends when any of:

- **dead world** — after generation 100, the stable-background fraction is
  below 1% (the world exploded into uniform foreground);
- **frozen background** — the stable-background count has not changed for more
  than 100 consecutive generations;
- **cap** — the generation count exceeds `max_steps` (default 1000); the run
  records `max_steps + 1` steps, which the `steps` objective rule scores as
  above-max (`max_weight`, +1) — staying alive to the cap is the treasure
  signature.

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

The trainer's own stream is `Pcg32(seed, seq=1)` (sequence 1, distinct from the
lattice-seeding stream); evaluation `i` scores with lattice seed
`seed + i * eval_cycles`, and cycle `j` of a scoring call runs from `seed + j`.

## Conformance

Bit-exact tier (integer statistics; plain-double scoring). Vectors in
[`../vectors/evolve/`](../vectors/evolve/):

- `objective-*` — per-cycle run statistics `(steps, foreground, active, rect,
  mage, score)` and the `(max_score, total_steps)` summary for seeded runs of a
  fixed genome, stored raw (`.f64`).
- `operators-seeded` — successive `mutate` / `crossover` / `tournament_select`
  results from fixed PCG32 seeds (strings and indices in `params.json`).
- `mini-run-24` — a complete small `Evolver` run: best genome, its score, the
  evaluation count, and the final population, all pinned.

`objective-*` and `mini-run-24` were regenerated 2026-08-19 when the evaluation
layer returned to the 2018 trainer semantics (above); `operators-seeded` scores
no lattices and was untouched by that change.

## Parallel evaluation

The GA loop itself is inherently sequential (steady-state admissions share one
PCG32 stream), but each candidate's objective cycles are independent — cycle
*i* seeds from `seed + i` — so implementations may evaluate them across worker
threads keyed by an explicit `workers` knob (C#: the `Evolver`/`ScoreGenome`
argument, default 1 = serial). The contract matches the fractal one: **output
is bit-identical for every worker count and schedule** — per-cycle results land
in per-index slots and the reduction (max of scores, integer sum of steps)
reads them in index order. Conformance suites replay the evolve vectors at
`workers = 1` and `workers > 1`. Python evaluates serially and takes no knob —
parallelism is a performance detail, never an algorithm change.
