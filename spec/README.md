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
| Bit-exact | Life-like, Elementary, Cyclic, Wireworld, MergeLife, fractal iteration counts | state equality after N steps |
| ε-tolerance | Lenia ×3, Gray-Scott, Boids, smooth coloring | max abs deviation < ε + fingerprints |

## Conventions

- Grids are row-major, index `i = y * width + x`, origin top-left.
- Default boundary is toroidal unless a family says otherwise.
- All params serialize to snake_case JSON; each language adapts naming at its own boundary.
- Fractal viewports store centers as decimal strings (arbitrary length) and zoom as log10 magnification — see [deep-zoom.md](deep-zoom.md).

## Index

- [rng.md](rng.md) — pinned PCG32 algorithm, known-answer test, draw-order convention
- [lifelike.md](lifelike.md) — Life-like CA (bit-exact tier)
- [deep-zoom.md](deep-zoom.md) — fractal precision architecture (perturbation + rebasing)
- Remaining family pages land alongside their implementations, per [ROADMAP.md](../ROADMAP.md).
