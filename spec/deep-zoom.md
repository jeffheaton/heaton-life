# Deep-zoom fractal rendering: precision architecture

## Problem

At magnification 10^k, pixel spacing is roughly `4·10⁻ᵏ / width`. float64 carries ~15–16 significant digits, so around zoom **1e13** adjacent pixels collapse to the same float64 coordinate and the image pixelates. Naive arbitrary precision per pixel per iteration (mpmath everywhere) is correct but 100–1000× too slow to be interactive.

## Approach: perturbation theory + rebasing

One point pays the bignum bill; every other pixel rides on hardware floats.

### Reference orbit (the only high-precision computation)

Iterate the center once at high precision:

```
Z₀ = 0;  Zₙ₊₁ = Zₙ² + C        C = viewport center
```

- Precision: `bits = ceil(3.33 · zoom_digits) + 64` guard bits.
- Arithmetic: gmpy2 (GMP) when installed, mpmath as pure-Python fallback, behind one internal shim.
- The orbit values themselves are O(1) magnitude, so they are **stored as complex128** — the array `Z[0..N]` is plain doubles and is exportable (see cross-language notes).

### Per-pixel perturbation (hardware floats)

Each pixel is `c = C + δc`, its orbit `zₙ = Zₙ + δₙ`, and the recurrence for the small difference needs only float64:

```
δₙ₊₁ = 2·Zₙ·δₙ + δₙ² + δc          (Mandelbrot)
```

Escape test and smooth coloring use the reconstructed `z = Z[m] + δ`:
`|z| > R` escapes; `μ = n + 1 − log₂(log|z| / log R)`.

### Rebasing (single reference, no glitches)

Classic perturbation suffers "glitches" where `|δ|` grows comparable to `|Zₙ|` and cancellation corrupts pixels; the old fix was glitch detection plus re-rendering with extra references. We use rebasing instead: each pixel tracks its reference index `m`, and

> when `|Z[m] + δ| < |δ|`, set `δ ← Z[m] + δ` and `m ← 0`.

One reference orbit suffices for the whole frame; no glitch passes. Vectorizes cleanly in NumPy: all pixels advance in lockstep, `Z[m]` is a fancy-indexed gather, escaped pixels are masked out. An optional numba kernel covers the scalar-loop fast path; the NumPy version is the reference.

### Per-family formulas

- **Mandelbrot**: recurrence above; `δc` = pixel offset, `δ₀ = 0`.
- **Julia**: `c` is a fixed global parameter; the reference orbit iterates the viewport center as `z₀`; pixels have `δ₀` = pixel offset and `δₙ₊₁ = 2·Zₙ·δₙ + δₙ²` (no `δc` term).
- **Burning Ship**: component form; the `|·|` folds use the stable piecewise `diffabs(X, x) = |X + x| − |X|` so cancellation never happens inside an abs.
- **Newton**: root-basin rendering, no self-similar deep zoom of the same kind — float64 direct only in v1; no perturbation tier.

## Precision tiers (auto-selected from zoom)

| Tier | Range (zoom = 10^k) | δ arithmetic | Status |
|---|---|---|---|
| T0 direct | k ≤ 12 | none — plain float64 escape-time | v1 |
| T1 perturbation | 12 < k ≲ 290 | float64 (δc underflows near 1e308; margin kept) | v1 |
| T2 perturbation | k > 290 | floatexp (float64 mantissa + int64 exponent) | reserved, future |

Tier selection is automatic and invisible to the caller; the API surface is identical across tiers.

## Viewport contract (lands in core on day one)

```json
{
  "center_re": "-0.743643887037158704752191506114774",
  "center_im": "0.131825904205311970493132056385139",
  "zoom_log10": 11.5,
  "max_iter": 50000
}
```

- `center_re` / `center_im` are **decimal strings** of arbitrary length — JSON-safe, language-neutral, parsed to gmpy2/mpmath (or BigInteger fixed-point in C#) only where needed.
- `zoom_log10` is a float; span derives from it. The public API never represents a viewport center as complex128 — retrofitting precision into a complex128 API breaks every downstream consumer, which is why this contract exists before the first fractal is implemented.

## Caching & interactivity

- The reference orbit depends only on `(C, max_iter)` → cache it; zooming toward a fixed center reuses it. v1 recomputes on center change (one orbit ≈ max_iter bignum ops ≈ ms–100s of ms, amortized over a frame).
- Playground: progressive refinement (iteration ladder, coarse-to-fine tiles) with cancellation on viewport change.

## Cross-language notes

- The perturbation loop is plain doubles — the same code shape in Python and C#; iteration counts are bit-comparable in T0/T1.
- C# has no bignum float. Two sanctioned options: fixed-point over `System.Numerics.BigInteger` for the reference orbit (only ~max_iter multiplies — cheap), or consume reference orbits exported in conformance vectors.
- Vectors for fractals include: viewport JSON, iteration-count grids (bit-exact tier), and the reference orbit as raw little-endian f64 pairs.

## Future work (explicitly out of v1)

- **BLA** (bivariate linear approximation) for iteration skipping at extreme depth.
- T2 floatexp arithmetic.
- Interior detection, distance-estimation anti-aliasing.
