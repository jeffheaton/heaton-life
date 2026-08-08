# Lenia (classic, asymptotic, flow)

Conformance tier: **ε-tolerance** (ε = 1e-6, and keep cross-language comparisons to
few steps — Lenia is chaotic and FFT/`exp` rounding differences compound). Vectors:
[`vectors/lenia-classic/`](../vectors/lenia-classic/),
[`vectors/lenia-asymptotic/`](../vectors/lenia-asymptotic/),
[`vectors/lenia-flow/`](../vectors/lenia-flow/).

## Shared machinery

- **State**: single-channel float64 world `A ∈ [0,1]`, shape `(height, width)`, torus.
  (Single channel for now; the kernel/FFT utilities are channel-agnostic, so
  multi-channel later means looping channels, not rewriting.)
- **Kernel**: single exponential ring, radius `R` cells, built in wrapped coordinates
  (center at index `[0,0]`), normalized to sum 1:
  `K(r) = exp(4 − 4 / (4·r·(1−r)))` for `0 < r < 1` where `r = dist/R`, else 0.
- **Potential**: `U = K ∗ A`, circular convolution (FFT).
- **Growth**: `G(u) = 2·exp(−(u−mu)² / (2·sigma²)) − 1` ∈ [−1, 1].

## The three updates

| Variant | Update | Notes |
|---|---|---|
| Classic (Chan 2018) | `A ← clip(A + dt·G(U), 0, 1)` | canonical Lenia |
| Asymptotic (Kawaguchi et al. 2021) | `A ← A + dt·(T(U) − A)`, `T = (G+1)/2` | convex for dt ≤ 1, no clipping |
| Flow (Plantec et al. 2022, simplified) | mass advection along `F` (below) | conserves total mass exactly |

**Flow details** (single-channel, unit-square reintegration = bilinear scatter):
`alpha = clip((A/theta)², 0, 1)`; `F = (1−alpha)·∇G(U) − alpha·∇A` (central differences
on the torus); displacement `d = clip(dt·F, ±0.9)` cells; each cell's mass is
distributed to the 4 cells around its displaced position with bilinear weights,
torus-wrapped. There is no growth term — patterns emerge purely from transport.

## Parameters

```json
{ "radius": 13, "mu": 0.15, "sigma": 0.017, "dt": 0.1,
  "width": 128, "height": 128, "init": "blobs", "blobs": 40,
  "density": 0.5, "seed": 0 }
```

Flow adds `"theta": 2.0` and uses different defaults (`mu 0.3, sigma 0.08, dt 2.0`,
init `soup`): aggregation needs `mu` *above* the mean potential so growth gradients
point toward mass.

## Initialization

- **soup**: PCG32 seq 0, `width·height` draws row-major; `A = draw/2³² · density`.
- **blobs**: 3 draws per blob (cx, cy, amplitude∈(0.5,1.0]); gaussian bump of width
  `R/2` at wrapped distances; sum clipped to [0,1].

## Vector encoding

Raw little-endian float64 (`.f64`), shape in the checkpoint entry.

## Oracles

- Kernel sums to 1; `K[0,0] = 0`; wrapped point symmetry.
- The empty world stays (essentially) empty in all variants.
- Classic and asymptotic stay in [0,1]; asymptotic without any clipping.
- Flow conserves total mass to relative 1e-9 and aggregates soup (std grows).
