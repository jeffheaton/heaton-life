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
| `mandelbrot/`, `julia/`, `burning-ship/`, `newton/` | `iterations.i32` (raw little-endian int32 escape counts, row-major); `roots.i32` for Newton; `orbit.c128` (raw complex128 reference orbit) for deep-zoom cases | [fractals.md](../spec/fractals.md), [deep-zoom.md](../spec/deep-zoom.md) |
| `render/` | `lut-*/`: `lut.png` (the 1×256 LUT); `apply-*/`: `frame.f64` in, `rgb.png` out; `frame-<family>/`: `state.f64` or `state.png` in, `frame.f64` or `frame.png` out; `fractal-render-*/`: `render.f64` (ε tier) | [render.md](../spec/render.md) |
| `patterns/` | `rle-*/`: `input.rle` in, `grid.png` + `canonical.rle` out; `transforms/`: `grid.png` in, `flip_h.png`, `flip_v.png`, `rotate90.png` out; `stamp-*/`: `pattern.png` in, `expected.png` out; `extract-*/`: `grid.png` in, `expected.png` out | [patterns.md](../spec/patterns.md) |
| `png-io/` | `input.png` in, `grid.png` out (MergeLife PNG decode at integer scale) | [png-io.md](../spec/png-io.md) |
| `evolve/` | `objective-*/`: `runs.f64` (per-cycle statistics) + `score.f64`; `operators-seeded/`: `params.json` only, expected operator results embedded; `mini-run-24/`: `best.f64`, with the best genome, evaluation count, and final population embedded in `params.json` | [evolve.md](../spec/evolve.md) |
| `mergelife-decode/` | `params.json` only; the expected decoded rule table is embedded | [mergelife.md](../spec/mergelife.md) |
| `mergelife-upstream/` | `vectors.txt`, copied from the upstream MergeLife project; see its README | [mergelife.md](../spec/mergelife.md) |

Vectors are versioned with the spec: every generated `params.json` carries `"spec_version"` (the `mergelife-decode` cases and the upstream `vectors.txt` are the exceptions). Regenerating a vector requires a spec-change justification in the PR.
