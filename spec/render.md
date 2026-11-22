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
| life-like, History rule | the state itself, 0–6 ([history.md](history.md)), for a color per state | index bytes |
| elementary | space-time diagram `* 255` | index bytes |
| cyclic | `state * 255 / max(states - 1, 1)` (integer math) | index bytes |
| wireworld | `state * 85` (hits the `wireworld` anchors exactly) | index bytes |
| generations | 0 for state 0, `(C - state) * 255 / (C - 1)` (integer math) otherwise: alive 255, the dying states fading | index bytes |
| ruletable | the state itself, 0 to S − 1 ([ruletable.md](ruletable.md)), for a color per state | index bytes |
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

## State palettes

A **state palette** gives each state of a world a color of its own. It has a colormap's
shape, 256 RGB entries, but is indexed by state instead of by frame value, so a world's
colors are the indexed path of [Applying a colormap](#applying-a-colormap) over a byte
frame of its **states**: a grid world's state (Elementary's, its diagram), or a
[multi-state universe](hashlife-multistate.md#view-and-render)'s `state` frame. Entry s
is state s's color; in a world of S states the entries from S on are black, (0, 0, 0),
and unused. A host that lets a person choose the color of each state edits the entries.

**Frame values.** Each byte frame of [Frames](#frames) is a function of the cell's state
alone, f(s), with f(0) = 0. A world's frame values are f(0) … f(S − 1) (`frame_values`,
.NET `StatePalettes.FrameValues`): for the two-state universe 0 and 255, its frames'
live cell ([hashlife.md](hashlife.md#view-and-render)), and for a multi-state universe
and a [rule table](ruletable.md)'s grid the states themselves, f(s) = s, as their frames
give them.

**A colormap's palette** for a world (`colormap_palette(world, cmap)`, .NET
`StatePalettes.FromColormap`) has entry s = lut[f(s)]. It shows the world's states as the
colormap shows its frames, `apply(states, colormap_palette(world, lut)) =
apply(frame, lut)`, so it is where a host starts when the colors it shows today are to
be edited state by state.

### Default palettes

`default_palette(world)` (.NET `StatePalettes.Default`) is the palette of the table:

| World | Default palette |
|---|---|
| Life-like, a two-state rule | `phosphor`'s: (6, 10, 6) and (170, 255, 190) |
| Life-like, a [History](history.md) rule | History's |
| Elementary | `gray`'s |
| Cyclic | `rainbow`'s |
| Wireworld | `wireworld`'s: the classic empty, head, tail and conductor colors |
| Generations | Generations' of its C |
| a [rule table](ruletable.md)'s grid | the rule table's |
| the two-state universe | `phosphor`'s |
| a multi-state universe | its rule's on a grid: History's, Generations' of its C, `wireworld`'s for `WireWorld`, a rule table's; for any other rule, the multi-state palette of its S |

A colormap's palette there keeps the look of the frames through the colormap the app
and the playground give that family. The rest are defined here:

- **History's** (`history_palette`, .NET `StatePalettes.ForHistory`) are the colors
  LifeHistory pictures are known by, in shades chosen here:

  | State | | Color |
  |---|---|---|
  | 0 | off | black (0, 0, 0) |
  | 1 | on | green (0, 255, 0) |
  | 2 | envelope | blue (0, 0, 160) |
  | 3 | marked on | white (255, 255, 255) |
  | 4 | marked off | red (255, 0, 0) |
  | 5 | start on | yellow (255, 255, 0) |
  | 6 | boundary | gray (128, 128, 128) |

- **Generations'** (`generations_palette(C)`, .NET `ForGenerations`) is `fire`'s palette
  of a Generations world of C states: entry 0 is `fire`'s entry 0, and entry s ≥ 1 is
  `fire`'s entry ⌊255 · (C − s) / (C − 1)⌋, the frame value. A live cell is pale yellow,
  and the dying states fade through orange and red toward the black of the dead.
- **The multi-state palette** (`multistate_palette(S)`, .NET `ForMultiState`), for a rule
  with no palette of its own: entry 0 black, and entry s from 1 to S − 1 `rainbow`'s entry
  ⌊255 · (s − 1) / (S − 1)⌋, S − 1 hues and none twice.
- **A gradient** (`gradient_palette(S, first, last, background)`, .NET `Gradient`):
  entry 0 the background, black unless given, and states 1 to S − 1 from `first` to
  `last`. Entry s is, channel by channel, (first · (S − 1 − s) + last · (s − 1)) / (S − 2)
  rounded half to even, in exact integer arithmetic; with S = 2, state 1 is `first`.
- **A rule table's** (`rule_table_palette(rule)`, .NET `ForRuleTable`): the multi-state
  palette of the rule's S, then its rule file's [`@COLORS`](rule-files.md#colors) entries
  in the file's order. A gradient sets states 1 to S − 1 as `gradient_palette` sets them,
  entry 0 staying as it is; a state color sets its state, state 0 among them. A rule file
  without `@COLORS` keeps the multi-state palette.

**Still to come.** Each of these takes its place in the table when its family lands:

- *Larger than Life*: with two states, `phosphor`'s palette; with C of three or more,
  Generations' of its C, since its dying cells are Generations' dying cells.
- *Super* rules (26 states): states 0 to 6 take History's colors; the other 19, and
  Super's zoom order, are defined with Super.

### Zoomed out

Zoomed out, a pixel shows one of the states it covers: on the plane by the universe's
[zoom order](hashlife-multistate.md#view-and-render), and on a grid by the order given to
its [window](#sampling-a-window-of-a-grid). `default_zoom_order(world)` (.NET
`StatePalettes.DefaultZoomOrder`) is the order that keeps what matters in view:

- a History rule: (3, 5, 1, 4, 6, 2). The on states come first, marked ones before plain
  ones; then marked off and the boundary; and last the envelope, which covers everything
  a pattern has touched and would otherwise hide the cells alive in it.
- every other world: the empty order, the lowest non-zero state first. A Generations cell
  alive shows before one dying, and the younger dying before the older; a Wireworld
  electron's head before its tail, and both before the wire.

A host sets the order on a universe (`zoom_order`) or passes it to a window. Nothing sets
it for the host, so no frame changes unless the host asks.

A frame whose pixels count live cells, any frame of the two-state universe (255 or 0 for
a cell or an `any` block, or a block's density) and every `density` frame, is colored by
the **shade** from state 0's color to state 1's (`shade_colormap(background, color)`,
.NET `StatePalettes.Shade`): entry v is, channel by channel, b + (c − b) · v / 255
rounded half to even, in exact integer arithmetic. It is the
[LUT construction](#lut-construction) of those two anchors, so the shade from black to
white is `gray`.

### Inverted colors

A host's "invert colors" shows each color by its complement, each byte v as 255 − v. It
is the display's to do, not the library's: the app inverts in its shader, which reaches
its grid lines and swatches too, where no table holds the colors, and keeps a world's own
colors in its pictures and exports. The library stores no inverted table and has no
function for it, since a table's complement is the one expression 255 − v, the same bytes
whoever computes it.

## Sampling a window of a grid

A grid world too big to show whole is shown a window at a time, with fewer pixels than
cells. `sample_window(cells, x0, y0, width, height, out_width, out_height, mode, order)`
(.NET `GridWindow.Sample`) reads the window of `width` × `height` cells whose top-left
cell is (x0, y0) from a grid of bytes, a world's states or one of its frames, and writes
an `out_height` × `out_width` array of bytes, row-major. The window lies inside the grid,
with 1 ≤ out_width ≤ width and 1 ≤ out_height ≤ height.

- **The cells a pixel covers** are those whose centers lie in its share of the window.
  For pixel (i, j), with W, H the window's width and height and w, h the output's: the
  columns x0 + c for ⌊(2iW + w − 1) / (2w)⌋ ≤ c < ⌊(2(i + 1)W + w − 1) / (2w)⌋, and the
  rows y0 + r for ⌊(2jH + h − 1) / (2h)⌋ ≤ r < ⌊(2(j + 1)H + h − 1) / (2h)⌋. The pixels
  share out the window, each covering a cell or more; with as many pixels as cells, a
  pixel is a cell.
- **Its nearest cell** is the one under its center: column x0 + ⌊(2i + 1) · W / (2w)⌋,
  row y0 + ⌊(2j + 1) · H / (2h)⌋. It is always among the cells the pixel covers.

The mode says what a pixel holds:

- **`nearest`**: its nearest cell's value.
- **`state`** (the default): of the non-zero values among its cells, the one first in the
  zoom order `order`, or 0 when every one is 0. A zoom order lists distinct values from 1
  to 255; they come first, in the list's order, and every value not listed follows them
  in increasing order ([hashlife-multistate.md](hashlife-multistate.md#view-and-render)),
  so the empty order shows the lowest. In a two-state grid a pixel is live when any cell
  it covers is: a lone live cell never vanishes, and a pixel live under `nearest` is live
  here too.
- **`density`**: ⌈255 · p / n⌉ for a pixel that covers n cells, p of them not 0, in
  integer arithmetic, (255p + n − 1) div n.

A window outside the grid, an output size out of range, or a list that is no zoom order
is an error, and nothing is written. Arithmetic on the bounds is exact (64-bit integers
in .NET).

So a host gives a world's states with its zoom order (`default_zoom_order`) and colors
the result with its palette, or colors a `density` result with the shade; a two-state
frame (0 and 255) works as it is, any live cell lighting its pixel.

## Conformance

Vectors in [`../vectors/render/`](../vectors/render/):

- `lut-<name>/` — the full LUT as a 1×256 RGB PNG (`lut.png`). Implementations
  rebuild the LUT from the anchors and must match byte-for-byte.
- `apply-ramp-fire/` — a 16×16 float frame (`frame.f64`, row-major, values
  `i/255`) applied through `fire`; expected RGB as `rgb.png`.
- `apply-half-rainbow/` — a 16×32 float frame (values `i/512`) applied through
  `rainbow`: round-to-nearest indices. Its one exact tie (127.5) rounds to 128 under
  half-even and half-away alike; `phase-apply-halfway` is the case that pins half-even.
- `palette-<case>/` — a state palette as a 1×256 RGB PNG (`palette.png`): a world's
  default palette (`world`: its family and what its palette depends on, a `rule` or a
  number of `states`; a [rule table](ruletable.md)'s world, family `ruletable` or
  `hashlife-multistate`, carries its rule file as `rule_text` unless the `rule` is in the
  starter set), with its `frame_values` and `zoom_order`; with a `cmap` as well,
  that colormap's palette for the world instead; or a palette made by name (`builder`:
  `history`, `generations`, `multistate` or `gradient`, with their arguments).
- `palette-shade-<case>/` — the shade between a `background` and a `color`, as a 1×256
  RGB PNG (`lut.png`).
- `window-<case>/` — a grid of bytes (`cells.png`, 8-bit grayscale, the values as they
  are) and the window, the output size, the `mode` and the `order` in `params.json`;
  `window.png` out. The palette, shade and window cases are strict (every key known).
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
