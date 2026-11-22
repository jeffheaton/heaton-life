# Specifications

Language-neutral definitions of every algorithm in the library. Implementations (Python, .NET) conform to these documents and to the golden vectors in [`../vectors/`](../vectors/); when an implementation and the spec disagree, the spec wins (or gets fixed).

## Spec page template

Each family gets one page structured as:

1. **State** — arrays/fields, shapes, value ranges, memory layout (row-major).
2. **Gather** — the neighborhood/kernel summary each site computes.
3. **Respond** — the pointwise nonlinearity.
4. **Integrate** — replace (discrete) or `+= dt·…` (continuous), boundary handling.
5. **Parameters** — names (snake_case), types, ranges, JSON schema.
6. **Initialization** — seeding procedures, defined exactly (fill order, RNG draws).
7. **Conformance** — tier (bit-exact or ε-tolerance), vector references.

## Determinism contract

- **RNG is pinned**: PCG32 (`state = state * 6364136223846793005 + inc`, XSH-RR output). Both implementations carry their own ~10-line copy; native RNGs never touch simulation state. Seeding and draw order are part of each family's init spec.
- **Discrete CAs are specified in integer math** (Life-like, HashLife, Elementary, Cyclic, Wireworld, MergeLife) so cross-language runs match bit-for-bit.
- **Float families** (Lenia, Gray-Scott, boids, smooth fractal coloring) conform within a per-family ε after N steps; transcendentals and FFT rounding make bitwise equality unrealistic.
- **The platform is part of the contract.** Every float bit-exact output rests on IEEE-754 binary64 rounded to nearest even, with no contraction of `a·b ± c` into a fused multiply-add (a C++ backend such as IL2CPP is built with `-ffp-contract=off`), no x87 extended precision or exponent range, and gradual underflow (no flush-to-zero, no denormals-are-zero). Where the ports rely on a fused multiply-add they say so and compute it exactly ([deep-zoom.md](deep-zoom.md)). A host on a runtime the suites do not cover runs the [platform self-check](self-check.md) there.

| Tier | Families | Test |
|---|---|---|
| Bit-exact | Life-like rules (canonical strings, tables, and the reasons for errors), grid topologies (where a point past an edge lands, the halo, the bounded-grid suffix and its reasons), Life-like, History rules (on grids and on the plane), HashLife (cells, populations and bounding boxes at any generation, their canonical Macrocell text, and the nodes snapshots hold), multi-state HashLife (states, populations and bounding boxes at any generation, the canonical multi-state Macrocell text, the nodes snapshots hold, and frames under a zoom order), Generations (rule texts to canonical forms and reasons; grid runs), Elementary, Cyclic, Wireworld, MergeLife (and its decoded rule table), fractal iteration counts (with or without BLA), their status, and Newton root indices, colormap LUTs and per-family frame indexing, patterns (RLE, transforms, stamp/extract, region editing), pattern files (format detection, every format's reading and measuring, metadata read and written, Macrocell timelines), PNG grid I/O (decoded grids), evolve (objective statistics, operators, whole runs); pow10, turns and floatexp via the known-answer bit patterns on their pages; the T2 loop on crafted states; navigation (moved centers, pixel deltas); discovery (box periods, Newton's nucleus: its verdict, stop, counts and printed center); the iteration policy; zoom movies (schedule, frame zooms and speeds, movie budgets, the survey's stations and patience rule, whole surveys at the pinned probe); fractal color given its inputs (stretch, depth phase, frequency, distance shading) and the phase lookup with its dither and cyclic palettes | byte-for-byte equality with the vector: states at each checkpoint step, or the one-shot output (float64 outputs by value, every NaN equal to every NaN) |
| ε-tolerance | Lenia ×3, Gray-Scott, Boids, smooth fractal coloring (the fractal render), the fractal distance estimate (relative: ε·|value|, its NaN, 0 and ±∞ exact), location framing (the zoom an imported location converts to, compared relatively: ε·max(1, |value|); its centers are exact), the atom size estimate (relative, its NaN exact) | max abs deviation ≤ the `epsilon` in the case's `params.json` (1e-6 for Lenia and boids, 1e-9 for Gray-Scott and the fractal render), or the output's `relative_epsilon` (1e-12 for the distance estimate and the atom size) |

## Conventions

- Grids are row-major, index `i = y * width + x`, origin top-left.
- Default boundary is toroidal unless a family says otherwise. Life-like and Wireworld
  grids take any [topology](topology.md).
- All params serialize to snake_case JSON; each language adapts naming at its own boundary.
- Fractal viewports store centers as decimal strings (arbitrary length) and zoom as log10 magnification — see [deep-zoom.md](deep-zoom.md).

## A world's state and its start

Every time-stepped family but the two HashLife universes (whose
[snapshots](hashlife.md#snapshots) do this job) keeps a **start**: the state `reset(seed)`
returns to at generation 0, its `init` strategy replayed. Life-like, Elementary, Cyclic,
Wireworld, MergeLife, Gray-Scott, the three Lenias and boids take an explicit state with
`set_state(state, generation)` (.NET `SetState`):

- The state becomes the given one, its values taken as the family's `array` init takes
  them (Life-like and Elementary cells as 0 or 1, the rest as given; a value the init
  refuses, or a state of the wrong shape, is an error that changes nothing). The
  generation becomes `generation`, 0 when it isn't given.
- By default the state also becomes the start, `init` `array`, so `reset()` returns to it.
- With `keep_start` the start stays as it was, and nothing of the new state is kept for
  it. A host that shows a saved frame or puts back an undo point moves the world this
  way: Reset still goes to the world's own start, and no copy of the world is made.

Elementary takes its space-time diagram too ([elementary.md](elementary.md#state)).

## Index

- [rng.md](rng.md) — pinned PCG32 algorithm, known-answer test, the streams in use, draw-order convention
- [pow10.md](pow10.md) — pinned deterministic 10^x (the fractal pixel scale's power; libm `pow` is forbidden on bit-exact paths)
- [turns.md](turns.md) — pinned cos and sin of a rational number of turns (Newton's roots; bit-exact tier, no libm)
- [floatexp.md](floatexp.md) — a float64 mantissa with an unbounded exponent: T2's numbers, every operation correctly rounded (bit-exact tier)
- [rules.md](rules.md) — Life-like rules: one 512-entry table over the 3×3 neighborhood, compiled from `B…/S…` (outer-totalistic, isotropic letters, hexagonal `H`, von Neumann `V`) or `MAP` strings; grammar, canonical form, bit order, and why a text is no rule (bit-exact tier)
- [lifelike.md](lifelike.md) — Life-like CA (bit-exact tier)
- [history.md](history.md) — History rules: any Life-like rule with seven states (off, on, envelope, marked on and off, start on, boundary), its on cells running the base rule; mixing with two-state patterns, grids on every topology, RLE letters and the multi-state universe (bit-exact tier)
- [topology.md](topology.md) — grid topologies: the plane, the torus (shifted or not), the Klein bottle, the cross-surface and the sphere; the one halo fill through which Life-like and Wireworld (and the grid families after them) read past their edges; the bounded-grid rule suffix (`B3/S23:T30,20`) read and written in RLE (bit-exact tier)
- [hashlife.md](hashlife.md) — HashLife: Life-like rules on an unbounded plane, B0 rules among them (the cells that differ from the background) — any generation count, editing within ±10⁹ (paste modes, rectangle transforms at any size, advancing a selection or its outside), a memory budget that never changes results, snapshots (what they hold, releasing them) (bit-exact tier)
- [hashlife-multistate.md](hashlife-multistate.md) — multi-state HashLife: rules of many states on an unbounded plane, through one cell-function interface every family of the 3 × 3 block plugs into (Wireworld first); the two-state engine's evolution, budget, snapshots and editing with states, and frames whose zoomed-out pixels choose among states by a zoom order (bit-exact tier)
- [elementary.md](elementary.md) — Wolfram elementary CA (bit-exact tier)
- [generations.md](generations.md) — Generations: Life-like birth and survival with dying states, C from 2 to 256; both rule spellings (`B2/S345/C4`, `345/2/4`), the canonical form and the reasons a text is refused; grids on every topology and the unbounded plane (bit-exact tier)
- [cyclic.md](cyclic.md) — cyclic CA (bit-exact tier)
- [wireworld.md](wireworld.md) — Wireworld (bit-exact tier)
- [mergelife.md](mergelife.md) — MergeLife, byte-identical with the upstream reference engines
- [grayscott.md](grayscott.md) — Gray-Scott reaction-diffusion (ε tier)
- [lenia.md](lenia.md) — Lenia classic / asymptotic / flow (ε tier)
- [boids.md](boids.md) — Reynolds flocking (ε tier, point-cloud state)
- [evolve.md](evolve.md) — the MergeLife GA and paper objective (bit-exact tier: objective statistics, GA operators, whole seeded runs, and the restart search's run seeds replay across languages; vectors in `../vectors/evolve/`)
- [fractals.md](fractals.md) — escape-time + Newton conventions, pixel mapping, vector schema
- [deep-zoom.md](deep-zoom.md) — fractal precision architecture (perturbation + rebasing; T2 past 1e290 and its platform contract)
- [locations.md](locations.md) — the framing conventions of heaton-life, Heaton Fractal, Kalles Fraktaler and Fraktaler-3, the conversions between them, and the importers for their files
- [nucleus.md](nucleus.md) — discovery: the box period test, Newton's method for a minibrot's nucleus, and the atom size estimate (bit-exact tier, the size ε)
- [navigation.md](navigation.md) — exact viewport arithmetic: pan, anchored zoom and pixel offsets on decimal centers, printed at the frame's places so the orbit's precision never ratchets (bit-exact tier)
- [render.md](render.md) — colormap LUT construction and frame indexing, the cyclic palettes and the phase lookup (bit-exact tier)
- [fractal-color.md](fractal-color.md) — fractal color that holds still: stretch (and a frozen stretch), depth phase, frequency, distance shading (bit-exact given its inputs)
- [self-check.md](self-check.md) — the platform self-check: embedded known answers a host runs on its own runtime (IL2CPP, Mono, a phone) to learn whether it reproduces the bit-exact contract, and what each failure invalidates
- [zoom.md](zoom.md) — zoom movies: Heaton Fractal's schedule with its end pinned, each frame's zoom, the movie iteration budget and the survey that measures it (bit-exact tier); the frame renderer (Python presentation)
- [macrocell.md](macrocell.md) — Macrocell, HashLife's native file format: reading, root placement, and a canonical writer (bit-exact tier)
- [patterns.md](patterns.md) — pattern model, RLE dialects, transforms, extract/stamp, family-bound compatibility
- [png-io.md](png-io.md) — MergeLife PNG import/export at integer scale; grid-level bit-exact contract (PNG bytes are per-encoder)
- [formats.md](formats.md) — pattern files: detection by content (gzip, PNG, BMP, text), metadata (name, author, comments), plaintext, Life 1.05, Life 1.06, PNG and BMP images, the readers into a grid, a new HashLife universe or one that exists, and measuring a file before reading it (bit-exact tier)
- Every family in the library has a page above. A new family adds its page here (the index and the tier table) before it merges; see [python/DEVELOPMENT.md, "Adding or changing a family"](../python/DEVELOPMENT.md#adding-or-changing-a-family).
