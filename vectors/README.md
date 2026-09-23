# Conformance vectors

Golden test data shared by every implementation. Each language's test suite replays these files (`python/tests/`, `dotnet/tests/`), and the manually dispatched Build Library workflows run those suites before packaging; discrete CAs must match bit-for-bit, float families within the ε declared in the family's spec page.

## Layout

```
vectors/<family>/<case-name>/
├── params.json      # full params + seed + steps + expected-state manifest
├── state_00000.png  # initial state (discrete families: lossless PNG, one byte/channel per cell)
├── state_00100.png  # expected state after 100 steps
└── state_00100.f64  # float families: raw little-endian float64, shape in params.json
```

- Discrete grids → PNG (lossless, human-viewable, both stacks read it).
- Float fields → raw little-endian f64 (C order); each checkpoint entry carries `"shape"`,
  and the case's `params.json` carries `"epsilon"` (max abs deviation for cross-language
  replay; same-language replay is exact).
- Fractal cases → viewport JSON + iteration-count grids (+ reference orbit as raw f64 pairs for deep-zoom cases).

Not every family is a time series. The other case shapes, each described on its spec page:

| Directory | Files beside `params.json` | Spec |
|---|---|---|
| `mandelbrot/`, `julia/`, `burning-ship/`, `newton/` | `iterations.i32` (raw little-endian int32 escape counts, row-major); `roots.i32` for Newton; `orbit.c128` (raw complex128 reference orbit) for deep-zoom cases; `critical.c128` (the critical orbit rebased pixels restart on) for deep Julia cases | [fractals.md](../spec/fractals.md), [deep-zoom.md](../spec/deep-zoom.md) |
| `render/` | `lut-*/`: `lut.png` (the 1×256 LUT); `apply-*/`: `frame.f64` in, `rgb.png` out; `frame-<family>/`: `state.f64` or `state.png` in, `frame.f64` or `frame.png` out; `fractal-render-*/`: `render.f64` (ε tier) | [render.md](../spec/render.md) |
| `patterns/` | `rle-*/`: `input.rle` in, `grid.png` + `canonical.rle` out; `transforms/`: `grid.png` in, `flip_h.png`, `flip_v.png`, `rotate90.png` out; `stamp-*/`: `pattern.png` in, `expected.png` out; `extract-*/`: `grid.png` in, `expected.png` out | [patterns.md](../spec/patterns.md) |
| `png-io/` | `input.png` in, `grid.png` out (MergeLife PNG decode at integer scale) | [png-io.md](../spec/png-io.md) |
| `evolve/` | `objective-*/`: `runs.f64` (per-cycle statistics) + `score.f64`; `operators-seeded/`: `params.json` only, expected operator results embedded; `mini-run-24/`: `best.f64`, with the best genome, evaluation count, and final population embedded in `params.json` | [evolve.md](../spec/evolve.md) |
| `mergelife-decode/` | `params.json` only; the expected decoded rule table is embedded | [mergelife.md](../spec/mergelife.md) |
| `locations/` | the input file (`input.kfr`, `input.f3.toml`, `input.json`, `input.txt` or `input.jsonl`) beside `params.json`, which holds the expected record and the viewports of three frames, or `"error": true` | [locations.md](../spec/locations.md) |
| `navigation/` | `params.json` only: an operation (`pan`, `zoom_at`, `pixel_delta`, `positional`, or a `sequence` of pans), its inputs, and the expected center strings — or `pixel_delta`'s doubles as IEEE-754 bit patterns | [navigation.md](../spec/navigation.md) |
| `mergelife-upstream/` | `vectors.txt`, copied from the upstream MergeLife project; see its README | [mergelife.md](../spec/mergelife.md) |

Vectors are versioned with the spec: every generated `params.json` carries `"spec_version"` (the `mergelife-decode` cases and the upstream `vectors.txt` are the exceptions). Regenerating a vector requires a spec-change justification in the PR. A version bump applies to the cases written under it; existing cases keep the version they were generated with, byte for byte.

| `spec_version` | What a runner must know to replay it |
|---|---|
| `0.2.0` | Everything up to 2026-09-22. |
| `0.3.0` | Fractal cases from 2026-09-23 ([deep-zoom.md](../spec/deep-zoom.md)): Julia's `critical_orbit` (rebased pixels restart on it), the fixed-point orbit arithmetic, the shared center grammar and exact float64 projection, orbit components far below `1e-292` converting without error, a deep Julia smooth render that needs an exact fma, and the optional `source` attribution key. (The precision rule's digit term and subnormal rounding are pinned by unit tests in both suites, not by a shipped vector.) |
| `0.4.0` | Fractal cases with an off-center reference ([deep-zoom.md](../spec/deep-zoom.md#off-center-reference)): `reference_re` / `reference_im` in the viewport; the stored orbit is the reference's, and every pixel's delta is `fl(round64(center − reference) + offset)`. |
| `0.5.0` | Navigation cases ([navigation.md](../spec/navigation.md)): exact pan, anchored zoom and pixel offsets on decimal centers, printed at the frame's places. Location cases ([locations.md](../spec/locations.md)): KF, Fraktaler-3 and Heaton Fractal files, their centers exact and their height-matched framing within a relative `1e-12`. |

Fractal runners are strict: a key at any level, a parameter, output kind, codec, or `spec_version` a runner does not know fails the case instead of being skipped.
