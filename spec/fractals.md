# Fractals: escape-time fields + Newton basins

Conformance tier: **bit-exact** on integer outputs (iteration counts, root indices).
Vectors: [`vectors/mandelbrot/`](../vectors/mandelbrot/), [`vectors/julia/`](../vectors/julia/),
[`vectors/burning-ship/`](../vectors/burning-ship/), [`vectors/newton/`](../vectors/newton/).
Deep-zoom architecture (tiers, perturbation, rebasing): [deep-zoom.md](deep-zoom.md).

## Pixel mapping (all families)

- `span_x = 4 / 10^zoom_log10`; pixel scale `ps = span_x / width`; square pixels.
- Pixel (row i, col j), row-major, origin top-left:
  `re = center_re + (j + 0.5 − width/2)·ps`, `im = center_im − (i + 0.5 − height/2)·ps`
  (imaginary axis points up).
- T0 computes absolute coordinates in float64; T1 computes only the offsets in float64
  and keeps the center in the reference orbit.

## Counts convention

`counts[i] = n`, the 1-based iteration at which |z| first exceeds `escape_radius`
(default 1000); `−1` if it never does within `max_iter`. Smooth (presentation only):
`mu = n + 1 − log2(log|z| / log R)`, then per-frame contrast stretching between the
1st/99th escaped percentiles for display — deep frames cluster counts near
`max_iter`, and an absolute mapping would render monochrome. Only `counts` is a
conformance output.

## Family updates

- **Mandelbrot**: `z ← z² + c`, `z₀ = 0`, `c` = pixel.
- **Julia**: `z ← z² + c`, `c` fixed, `z₀` = pixel. Perturbation uses the center's
  orbit under the same `c`; `δ₀` = pixel offset, no `δc` term.
- **Burning Ship**: `x' = x² − y² + cx`, `y' = 2|x||y| + cy`. Perturbation in
  component form with `diffabs(X, d) = |X+d| − |X|` evaluated by case analysis
  (never by subtraction).
- **Newton** (float64 only, zoom ≤ 1e12): `z ← z − (z^d − 1)/(d·z^(d−1))`;
  converged when `|z^d − 1| < 1e-9`; outputs `roots` (nearest-root index, −1 if
  unconverged) and `iterations` (1-based, −1 if unconverged). Roots are
  `exp(2πik/d)`, k = 0..d−1.

## Tiering (automatic)

| Tier | zoom_log10 | Engine |
|---|---|---|
| T0 | ≤ 12 | direct float64 |
| T1 | ≤ 290 | perturbation + rebasing, reference index clamped to the last orbit sample |
| T2 | > 290 | not implemented (raises); floatexp reserved |

Determinism note: T1 counts are bit-stable given the reference orbit, and the two
sanctioned bignum backends (gmpy2, mpmath) produce **identical** orbits at equal
precision (tested). In chaotic boundary regions T0 and T1 legitimately disagree on
a few percent of pixels — by exactly as much as T0 disagrees with itself under a
1-ulp input perturbation. Conformance therefore always compares like against like:
the vector's tier is whatever the viewport's zoom selects.

## Parallel rendering

Implementations may split the per-pixel loops across worker threads, keyed by an
explicit `workers` knob (C#: the `workers` constructor argument, default 1 =
serial). The contract: **output is bit-identical for every worker count and
schedule.** This holds by construction — every pixel's computation is
independent, workers own disjoint rows of the output buffers, and no RNG is
drawn during rendering. Serial stages stay serial: the T1 reference orbit is
computed once before pixels fan out, and `NormalizeRender`'s percentile stretch
runs on the finished `mu` buffer. Conformance suites replay the same vectors at
`workers = 1` and `workers > 1`; both must match byte-for-byte. Python renders
whole-array through NumPy and takes no knob — parallelism is a host-side
performance detail, never an algorithm change.

## Vector schema (one-shot renders; no time axis)

```json
{
  "spec_version": "0.2.0", "family": "mandelbrot", "tier": "bit-exact",
  "params": { "max_iter": 500, "escape_radius": 1000.0 },
  "viewport": { "center_re": "-0.5", "center_im": "0.0", "zoom_log10": 0.0 },
  "size": [64, 64],
  "outputs": [ { "kind": "iterations", "file": "iterations.i32", "shape": [64, 64] } ],
  "reference_orbit": { "file": "orbit.c128", "length": 5001 }
}
```

- `.i32` = raw little-endian int32, C order.
- `.c128` = raw little-endian complex128 (re, im float64 pairs) — present on
  deep-zoom cases; regeneration must reproduce it bit-for-bit, and implementations
  without a bignum stack may consume it directly.
