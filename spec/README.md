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
- **Discrete CAs are specified in integer math** (Life-like, Elementary, Cyclic, Wireworld, MergeLife) so cross-language runs match bit-for-bit.
- **Float families** (Lenia, Gray-Scott, boids, smooth fractal coloring) conform within a per-family ε after N steps; transcendentals and FFT rounding make bitwise equality unrealistic.

| Tier | Families | Test |
|---|---|---|
| Bit-exact | Life-like, Elementary, Cyclic, Wireworld, MergeLife (and its decoded rule table), fractal iteration counts and Newton root indices, colormap LUTs and per-family frame indexing, patterns (RLE, transforms, stamp/extract), PNG grid I/O (decoded grids), evolve (objective statistics, operators, whole runs); pow10 via the known-answer bit patterns on its page | byte-for-byte equality with the vector: states at each checkpoint step, or the one-shot output |
| ε-tolerance | Lenia ×3, Gray-Scott, Boids, smooth fractal coloring (the fractal render) | max abs deviation ≤ the `epsilon` in the case's `params.json` (1e-6 for Lenia and boids, 1e-9 for Gray-Scott and the fractal render) |

## Conventions

- Grids are row-major, index `i = y * width + x`, origin top-left.
- Default boundary is toroidal unless a family says otherwise.
- All params serialize to snake_case JSON; each language adapts naming at its own boundary.
- Fractal viewports store centers as decimal strings (arbitrary length) and zoom as log10 magnification — see [deep-zoom.md](deep-zoom.md).

## Index

- [rng.md](rng.md) — pinned PCG32 algorithm, known-answer test, draw-order convention
- [pow10.md](pow10.md) — pinned deterministic 10^x (the fractal pixel scale's power; libm `pow` is forbidden on bit-exact paths)
- [lifelike.md](lifelike.md) — Life-like CA (bit-exact tier)
- [elementary.md](elementary.md) — Wolfram elementary CA (bit-exact tier)
- [cyclic.md](cyclic.md) — cyclic CA (bit-exact tier)
- [wireworld.md](wireworld.md) — Wireworld (bit-exact tier)
- [mergelife.md](mergelife.md) — MergeLife, byte-identical with the upstream reference engines
- [grayscott.md](grayscott.md) — Gray-Scott reaction-diffusion (ε tier)
- [lenia.md](lenia.md) — Lenia classic / asymptotic / flow (ε tier)
- [boids.md](boids.md) — Reynolds flocking (ε tier, point-cloud state)
- [evolve.md](evolve.md) — the MergeLife GA and paper objective (bit-exact tier: objective statistics, GA operators, and whole seeded runs replay across languages; vectors in `../vectors/evolve/`)
- [fractals.md](fractals.md) — escape-time + Newton conventions, pixel mapping, vector schema
- [deep-zoom.md](deep-zoom.md) — fractal precision architecture (perturbation + rebasing)
- [render.md](render.md) — colormap LUT construction and frame indexing (bit-exact tier)
- [patterns.md](patterns.md) — pattern model, RLE dialects, transforms, extract/stamp, family-bound compatibility
- [png-io.md](png-io.md) — MergeLife PNG import/export at integer scale; grid-level bit-exact contract (PNG bytes are per-encoder)
- Every family in the library has a page above. A new family adds its page here (the index and the tier table) before it merges; see [python/DEVELOPMENT.md, "Adding or changing a family"](../python/DEVELOPMENT.md#adding-or-changing-a-family).
