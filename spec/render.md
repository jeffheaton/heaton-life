# Render: colormaps (bit-exact tier)

The one rendering pipeline every family feeds: a frame becomes RGB by indexing a
256-entry lookup table. The LUTs and the indexing rules are part of the
cross-language contract — a Unity build and the PyQt playground must color the
same state the same way, byte for byte.

## LUT construction

A colormap is defined by its ordered anchor list (RGB triples). The LUT is built
by piecewise-linear interpolation:

```
positions = linspace(0, 1, len(anchors))     # anchor x-coordinates
xs        = linspace(0, 1, 256)              # sample points
lut[i][c] = round_half_even(interp(xs[i], positions, anchor[c]))   # per channel
```

- `linspace(0, 1, n)`: `step = 1/(n-1)`, sample `k` is `k * step`, and the final
  sample is exactly `1.0`.
- `interp` is standard piecewise-linear interpolation:
  `y = y_j + (x - x_j) * (y_{j+1} - y_j) / (x_{j+1} - x_j)` on the enclosing
  segment, with exact anchor hits returning the anchor value.
- Rounding is **half-to-even** (banker's), then cast to uint8.

## Built-in anchors

| Name | Anchors (RGB) |
|---|---|
| `gray` | (0,0,0) (255,255,255) |
| `phosphor` | (6,10,6) (10,60,25) (40,200,90) (170,255,190) |
| `fire` | (0,0,0) (120,16,0) (255,140,0) (255,255,220) |
| `ice` | (0,0,0) (0,40,110) (70,160,255) (230,250,255) |
| `violet` | (8,4,16) (90,30,140) (200,100,255) (255,240,255) |
| `wireworld` | (0,0,0) (70,130,255) (255,80,60) (255,210,70) |
| `rainbow` | (220,40,40) (230,200,40) (60,200,70) (50,200,220) (70,70,230) (200,60,220) (220,40,40) |

`wireworld`'s four anchors land exactly on indices 0/85/170/255, so Wireworld
frames encoded as `state * 85` hit the classic empty/head/tail/conductor colors
exactly. `rainbow` is a closed hue wheel (index 255 = index 0), suited to cyclic
CA states.

## Applying a colormap

`apply(frame, lut) -> RGB (H, W, 3) uint8`, by frame type:

1. **(H, W, 3) uint8** — already RGB: passed through unchanged.
2. **(H, W) float** — index = `round_half_even(clip(frame, 0, 1) * 255)` as
   uint8, then `lut[index]`.
3. **(H, W) uint8** — direct index: `lut[frame]`.

Anything else is an error. The float path's half-even rounding is part of the
contract: `0.5 * 255 = 127.5` must index entry 128 in every language.

## Frames

Simulations expose their renderable view as a *frame* — always Height×Width,
in one of the three shapes of core/protocols.py: palette-index bytes
(colormapped via the LUTs above), floats in [0, 1] (ditto, after the float
indexing rule), or raw RGB (passed through).

| family | frame | shape |
|---|---|---|
| life-like | `state * 255` | index bytes |
| elementary | space-time diagram `* 255` | index bytes |
| cyclic | `state * 255 / max(states - 1, 1)` (integer math) | index bytes |
| wireworld | `state * 85` (hits the `wireworld` anchors exactly) | index bytes |
| mergelife | the RGB state itself | RGB |
| gray-scott | `clip(V * 2.5, 0, 1)` | float |
| lenia (all three) | the state itself | float |
| boids | soft-dot rasterization (below) | float |

**Boids rasterization** (bit-exact): pixel = `trunc(position)` with floored
wrap; each boid adds the kernel
`(dy, dx, w)` ∈ (0,0,1.0) (−1,0,.55) (1,0,.55) (0,−1,.55) (0,1,.55)
(−1,−1,.3) (−1,1,.3) (1,−1,.3) (1,1,.3), kernel entries outermost and boids in
index order within each pass — the accumulation order is part of the contract —
then the image is clipped to [0, 1].

**Fractal render** (ε tier, 1e-9): smooth value
`mu = n + 1 - log2(log|z| / log R)` for escaped pixels, else 0; then a
per-frame percentile stretch over the escaped mus:
`clip((mu - p1) / (p99 - p1), 0.02, 1)` (a flat 0.6 if `p99 <= p1`), interior
stays 0, and the final frame is `sqrt(values)`. Percentiles use linear
interpolation on the sorted escaped values. Newton's shade:
`(root + 1 - 0.7 * iters / max_iter) / degree`, clipped; unconverged pixels 0.

## Conformance

Vectors in [`../vectors/render/`](../vectors/render/):

- `lut-<name>/` — the full LUT as a 1×256 RGB PNG (`lut.png`). Implementations
  rebuild the LUT from the anchors and must match byte-for-byte.
- `apply-ramp-fire/` — a 16×16 float frame (`frame.f64`, row-major, values
  `i/255`) applied through `fire`; expected RGB as `rgb.png`.
- `apply-half-rainbow/` — a 16×32 float frame (values `i/512`, hitting exact
  `.5` index products) applied through `rainbow`; pins half-even rounding.
- `frame-<family>/` — an explicit input state (family codec encoding) and the
  expected frame (bit-exact). Inputs are explicit so the frame contract stays
  decoupled from the ε of evolved states.
- `fractal-render-<case>/` — params + viewport and the expected float frame
  (`render.f64`, ε = 1e-9).
