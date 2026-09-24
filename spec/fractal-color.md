# Fractal color: stretch, phase, frequency and distance shading

How the escape-time fields' smooth values `μ` and [distance
estimates](fractals.md#distance-estimate) become pictures that hold still while a host
pans, zooms, dives, or trades a fast frame for a sharp one. Python
`heaton_life.fractal.coloring`, C# `FractalColor`. All of it is presentation: counts
never depend on it.

There are two ways to color an escape-time frame:

- **Stretch** (the default, [render.md](render.md) "Fractal render"): the frame's own
  1st and 99th percentiles of `μ` map onto a sequential colormap. Every frame is scaled
  to its own statistics, so the colors shift whenever what is on screen shifts — the
  "breathing" of a dive, and a color change when a view is re-rendered at another size.
- **Phase**: a pixel's color is a function of its `μ` alone, `t = c·(μ − A) + φ`,
  looked up in a palette that repeats ([render.md](render.md) "Phase lookup"). A point
  of the plane keeps its color at every zoom and every frame size. This is Heaton
  Fractal's model; its rule is never to normalize per frame.

Either can then be [shaded](#distance-shading) by the distance estimate.

**Tier.** Every function here is **bit-exact given its inputs** — plain IEEE float64
operations in the order written, no fma, no libm beyond correctly rounded `sqrt`. Its
inputs, `μ` and the distance estimate, are ε-tier, so a host's colors are exact given
the same fields, and the vectors take the fields as explicit inputs
([`../vectors/render/`](../vectors/render/)).

## Color scale

Parameters measured in pixels are given at 1080p and scaled to the frame (Heaton
Fractal's `colorScale`), so a 320-wide dive frame and the 1600-wide sharp frame of the
same view look alike:

```
scale(W, H) = sqrt(W·W + H·H) / sqrt(4852800)        4852800 = 1920² + 1080²
```

`W·W + H·H` is computed in integers (exact), then converted; the square roots are
correctly rounded. Never `hypot`, which is libm. Python `color_scale`, C#
`FractalColor.ColorScale`.

## Stretch

`measure_stretch(μ)` — the escaped values are those with `μ > 0`; none escaped → none
(C# `TryMeasureStretch` returns false). Otherwise sort them and take
`lo = P(1)`, `hi = P(99)` by NumPy's linear percentile over the `n` sorted values `s`:

```
v = q/100·(n − 1);  i = floor(v) clamped to [0, n − 1];  f = v − i
a = s[i];  b = s[min(i + 1, n − 1)];  d = b − a
P(q) = f ≥ 0.5 ? b − d·(1 − f) : a + d·f
```

`apply_stretch(μ, (lo, hi))` — per pixel, escaped: `0.6` if `hi ≤ lo` (a featureless
frame), else `clip((μ − lo) / (hi − lo), 0.02, 1)`; not escaped: `0`; then `sqrt`.
The floor keeps escaped pixels off the interior's color.

`normalize_render(μ)` is `apply_stretch(μ, measure_stretch(μ))`, and all zeros when
nothing escaped — bit for bit, so existing renders are unchanged.

A **frozen stretch** is a measurement kept and applied to later frames of the *same*
view: a host that renders a quick frame, then a larger one, then a sharp one measures
once and the colors stay put. It is not for dives: `μ` climbs with depth, so a stretch
frozen at the start saturates within a few decades. Dives use phase.

## Depth phase

Parameters: `c` cycles per iteration (default `0.01`), `k` cycles per octave of zoom
(default `0`), `φ` phase offset (`0`), `A` anchor (`0`). Per pixel:

```
u = zoom_log10 · LOG2_10                      LOG2_10 = 3.321928094887362 (0x400A934F0979A371)
t = (φ + k·u) + c·(μ − A)                     where μ > 0
t = NaN                                       elsewhere (did not escape)
```

`t` is in cycles and **unwrapped**; the lookup wraps it. Unwrapped because `μ` is ε-tier:
two ports' `t` then differ by ε, where a wrapped `0.9999999` and `0.0000001` would be a
whole palette apart.

With `k = 0` (the default) a point of the plane has the same color at every zoom, so
nothing changes color when a zoom lands. `k > 0` is Heaton Fractal's video "flow" (its
default there is `0.25`): colors drift with depth. A host that wants it during an
automatic dive measures `u` from the dive's start and folds `φ + k·u` into `φ` when the
dive stops, so the next manual zoom does not jump.

Python `depth_phase(μ, zoom_log10, PhaseParams)`, C# `FractalColor.DepthPhase`.

## Frequency

One `c` does not suit every depth: deep frames spread their counts over thousands of
iterations, and at `0.01` cycles per iteration neighboring pixels land cycles apart —
noise. `measure_frequency(counts, μ)` fits `c` (and the anchor `A`) to one frame, the
single-station form of Heaton Fractal's frequency fit:

```
steps  = |μ[y][x] − μ[y][x−1]|   (x > 0)   and   |μ[y][x] − μ[y−1][x]|   (y > 0),
         wherever both pixels escaped with a finite μ (0 < μ < ∞)
fewer than 64 steps → none
step   = sorted(steps)[n // 2]                                    upper median
A      = sorted(counts where counts > 0)[m // 2]                  an integer: counts are exact
c      = min(c_max, (target / scale(W, H)) / max(step, 1.0))
```

with `target = 0.03` cycles per pixel step at 1080p and `c_max = 0.01` (Heaton Fractal's
defaults). `retune(params, (c′, A′), pivot)` swaps in a new frequency without a jump
where it matters: it returns `(c′, k, φ′, A′)` with

```
φ′ = (φ + c·(pivot − A)) − c′·(pivot − A′)
```

so `t` at `μ = pivot` is unchanged, up to rounding (pivot: the frame's median count, the
new `A′`). Python `measure_frequency` / `retune`, C# `FractalColor.TryMeasureFrequency` /
`Retune`.

When to measure is the host's call (informative): when a view comes to rest, and during
a dive at most about once per octave, with a change in `c` limited to a factor of 2 per
retune. Measuring every frame is the per-frame normalization this page exists to avoid.

## Distance shading

After the lookup, darken each pixel by how close it is to the boundary. Parameters:
`width` (default `1.6` pixels at 1080p), `strength` (`0.85`), `dense_release` (`1.0`);
`width` finite and positive, the other two in `[0, 1]`, else an error.

```
w       = max(width · scale(W, H), 1e-4)          not finite (a width too large) → an error
r       = int(min(ceil(w) + 1, max(W, H)))
maxDE   = the largest of 0 and the DEs in the (2r+1)×(2r+1) window around the pixel,
          cut off at the frame's edges, a NaN counted as 0 and +∞ as +∞
for a pixel whose DE is not NaN:
    shade = smoothstep(0, w, DE)
    open  = smoothstep(0.25·w, w, maxDE)
    s     = strength · (1 + (open − 1) · dense_release)
    f     = 1 + (shade − 1) · s                  a factor in light, in [1 − strength, 1]
    g     = sqrt(f)                              the same factor on encoded values
    each channel ← clip(round_half_even(channel · g), 0, 255)
a pixel whose DE is NaN (did not escape) is left as it is
smoothstep(e0, e1, x) = (t·t)·(3 − 2·t),   t = clip((x − e0) / (e1 − e0), 0, 1)
```

The window maximum is separable — rows, then columns — and gives the same values.

`open` is Heaton Fractal's dense-region release: where nothing within reach is at least
a stroke's width from the boundary (a dense tangle of filaments finer than the stroke),
the darkening fades out instead of sinking the region to `1 − strength`.

Heaton Fractal shades in linear light, before encoding. The bytes here are sRGB-encoded,
and `sqrt` stands in for the encoding (gamma 2 against sRGB's ~2.2), so the arithmetic
stays exact and the look stays close: at full darkening (`f = 0.15`) a white pixel on
the boundary becomes `99` where shading in linear light and encoding with the sRGB curve
gives `108`, and a mid-gray `128` becomes `50` both ways. (Heaton Fractal itself encodes
with Rec.709 — [render.md](render.md) "Cyclic palettes" — so its frames show about `94`
and `40`.)

Python `shade_distance(rgb, distance, ShadeParams)`, C# `FractalColor.ShadeRgb` /
`ShadeRgba`.

## Order

```
fields (counts, μ, distance)
  → stretch → sequential lookup (render.md "Applying a colormap")
  | phase   → phase lookup      (render.md "Phase lookup")
  → distance shading (optional)
```

## Conformance

Bit-exact given the inputs, in [`../vectors/render/`](../vectors/render/):
`stretch-*` (`mu.f64` → the measured bounds and the render; one case applies bounds
measured on another frame), `phase-*` (`mu.f64` → `t.f64`), `frequency-*`
(`counts.i32`, `mu.f64` → `c` and `A`), `shade-*` (`input.png`, `distance.f64` →
`rgb.png`). Doubles in `params.json` are IEEE-754 bit patterns (`"0x…"`). A float64
output compares by value, every NaN equal to every NaN, the sign of a zero not compared.
