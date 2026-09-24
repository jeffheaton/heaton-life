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

## Cyclic palettes

Four more 256-entry tables that wrap — entry 255 is followed by entry 0 — for the
[phase lookup](#phase-lookup):

| Name | Heaton Fractal's name |
|---|---|
| `deep` | Ultra Fractal Deep (its default) |
| `classic` | Ultra Fractal |
| `embers` | Embers |
| `glacier` | Glacier |

They are **data**: the bytes in both ports (C# `PaletteTables`, Python
`render/_palette_tables.py`), pinned by `lut-<name>/lut.png`. How they were made is
recorded, not re-run: `python/tools/gen_palettes.py` takes Heaton Fractal's gradient
stops, linearizes them with the sRGB curve, converts to Oklab (Ottosson's matrices, the
reverse ones by cofactor inversion), interpolates linearly in Oklab around the cycle,
and samples entry `i` at position `i/256`, clamped to `[0, 1]` in linear light,
sRGB-encoded and rounded half to even from `×255` (an entry exactly on a stop takes the
stop's own bytes). They are sRGB for sRGB displays; Heaton Fractal encodes its frames
with Rec.709, so its screenshots differ by up to ~16 codes and are not a reference.

The registries stay separate: `list_colormaps()` / `Colormaps.Names` are the anchor
colormaps above, `list_cyclic_colormaps()` / `Colormaps.CyclicNames` these four;
`get_colormap` / `Colormaps.Get` resolve either; `is_cyclic` / `Colormaps.IsCyclic`
tell them apart. A cyclic table used by the clipping lookup above maps 0 and 1 to
nearly the same color — hosts offer them for the phase lookup. (`rainbow` is closed but
not cyclic in this sense: its entry 255 repeats entry 0.)

## Phase lookup

`apply_phase(t, lut, wrap, interior, antialias, dither, frame_index) → RGB (H, W, 3)
uint8` colors an unwrapped phase `t` in cycles ([fractal-color.md](fractal-color.md)
"Depth phase"), `NaN` where a pixel did not escape.

`wrap` picks how many positions a cycle has and which entry each one reads:

- `cyclic`: `P = 256`, `entry(k) = k` — for the cyclic palettes;
- `mirror`: `P = 510`, `entry(k) = k` for `k ≤ 255`, `510 − k` above — any colormap runs
  up and back down each cycle, so `fire` or `gray` work with phase coloring without a
  seam.

For the pixel in column `x`, row `y`, in this order:

```
if t is not finite, or X = t·P is not finite:   the interior color, exactly (default (0, 0, 0))
F  = floor(X);  f = X − F
k0 = F − P·floor(F / P);  then k0 += P if k0 < 0,  k0 −= P if k0 ≥ P
k1 = k0 + 1, or 0 when k0 + 1 = P
per channel ch:
    a, b = lut[entry(k0)][ch], lut[entry(k1)][ch]            as doubles
    v    = a + (b − a)·f
    antialias:  v = v + (mean_ch − v)·alias
    dither:     v = v + amplitude·(D_ch·2⁻³²)
    out  = clip(round_half_even(v), 0, 255)
```

- **Interpolation** between neighboring entries, with `floor`, so entry `k` sits exactly
  at `t = k/P`.
- **Antialias** (on by default): `need` = the largest `|t − t_n|` over the pixel's four
  neighbors in the frame whose `t` is finite (0 if none), `alias = smoothstep(0.35, 1.0,
  need)` (`smoothstep` as in [fractal-color.md](fractal-color.md)), and
  `mean_ch = S_ch / P` with `S_ch = Σ_{k<P} lut[entry(k)][ch]`, an integer. Where the
  phase moves more than about a third of a cycle per pixel the color is noise — it would
  flicker as the view moves — so it fades to the palette's mean (Heaton Fractal's
  threshold, measured on neighbors instead of predicted from the distance estimate).
- **Dither** (amplitude `1` by default; `0` turns it off; finite and `≥ 0`): per channel,
  a triangular ±1-code noise at amplitude 1, `D_ch` from [rng.md](rng.md) "Presentation
  noise" at `(x, y, frame_index, ch)` — Heaton Fractal's dither, which it applies after
  encoding exactly so. `frame_index` is `0` for stills and interactive views, the frame
  number in an animation; `0 ≤ frame_index < 2³²`.

Python `apply_phase`, C# `Colormaps.ApplyPhase` / `ApplyPhaseRgba` (alpha 255).

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
- `lut-deep/`, `lut-classic/`, `lut-embers/`, `lut-glacier/` — the cyclic tables.
- `phase-apply-<case>/` — `t.f64` in (with `NaN`s), the lookup's options in
  `params.json`, `rgb.png` out (bit-exact).
- The fractal coloring cases (`stretch-*`, `phase-*`, `frequency-*`, `shade-*`):
  [fractal-color.md](fractal-color.md).

A float64 output compares by value: every NaN equals every NaN, and the sign of a zero is
not compared. Cases from 0.7.0 on are checked strictly (every key known).
