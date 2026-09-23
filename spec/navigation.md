# Navigation: exact viewport arithmetic

A host that pans, recenters on a click, or zooms about the cursor moves a viewport's
decimal center by a pixel offset. Doing that in float64, or in C# `decimal` (28
places), runs out of digits long before the renderer does ([deep-zoom.md](deep-zoom.md)
goes to 1e290). Printing "enough digits" naively has the opposite failure: a center
printed with the bits its frame's orbit uses raises the next orbit's precision by the
64 guard bits, every step. These operations are exact instead, and they print a moved
center with a number of places set by the frame alone.

Everything here is **bit-exact** across ports: the output strings, and `pixel_delta`'s
doubles. Python `heaton_life.fractal.navigation`, C# `HeatonLife.Navigation`.

## Conventions

- A pixel offset `(dx, dy)` is measured in pixels of a `width × height` frame from its
  center: `dx` to the right, `dy` **down** (the row direction of
  [fractals.md](fractals.md) "Pixel mapping"). Fractional offsets are allowed; both
  must be finite. Recentering on pixel `(j, i)` is the offset
  `(j + 0.5 − width/2, i + 0.5 − height/2)`.
- `ps(width, z) = (4/width) · pow10(−z)`: the pixel scale, computed exactly as a
  render computes it ([fractals.md](fractals.md), [pow10.md](pow10.md)).
- The **exact value** of a decimal string is the rational its digits spell
  ([deep-zoom.md](deep-zoom.md) "Viewport contract" grammar); of a double, the rational
  it holds.
- **Center places**: `P(z, width, height) = max(⌈z⌉, 0) + digits(max(width, height)) + 2`,
  where `⌈z⌉` is the ceiling of the double `z` and `digits(n)` the number of decimal
  digits of the positive integer `n` (no logarithm). `10^−P ≤ ps/400`: a grid of at
  most 1/400 pixel.
- **Printing** a value `v` at `P` places: round `v · 10^P` to an integer, **ties away
  from zero**, and write it positionally with exactly `P` fraction digits — `-` only for
  a nonzero negative, no `+`, no exponent, a single `0` before the point when the
  magnitude is below 1 (`-0.00004`, `0.00000`, `12.34500`). A result with more than
  10,000 digits is an error (it could not be read back).
- A move whose **shifts are both exactly zero keeps the center strings** — a pan of
  `(0, 0)`, or a zoom about the center — so a host that compares centers as strings sees
  no motion that did not happen. **Any other move prints both components** at `P`,
  including one whose own shift is zero: a horizontal pan re-prints the imaginary part
  too, which is what keeps the orbit's precision at the zoom's own (below).
- Zooms must lie in `[−300, 300]`, [pow10.md](pow10.md)'s domain: the current zoom, a
  `pan`'s target zoom and `zoom_at`'s, and the argument of `P`. Anything else is an error,
  before any arithmetic.
- Centers that did not move keep whatever notation they arrived in. A host writing
  centers for a reader that takes no exponent (C# `decimal.Parse`) passes them through
  `positional` first.
- The viewport's off-center reference, if any, is carried over unchanged. Choosing it
  is the host's job ([deep-zoom.md](deep-zoom.md) "Off-center reference"); keeping it
  is what lets a pan hit the orbit cache.

## Operations

**`pan(viewport, dx, dy, (width, height), zoom = viewport's)`** — recenter on the point
now `(dx, dy)` pixels from the center, optionally at a new zoom. A click passes the
clicked pixel's offset; a drag passes minus the drag.

```
ps     = ps(width, viewport.zoom)          -- the CURRENT zoom's scale
o_re   = fl(dx · ps)
o_im   = −fl(dy · ps)                      -- the same doubles a render gives that pixel
center = print(C + o, P(zoom, width, height))   -- both offsets zero: unchanged
```

**`zoom_at(viewport, dx, dy, (width, height), zoom)`** — change the zoom holding the
point at pixel offset `(dx, dy)` fixed (a cursor-anchored wheel or pinch).

```
ps0, ps1 = ps(width, viewport.zoom), ps(width, zoom)
s_re     = fl(dx · ps0) − fl(dx · ps1)      -- exact difference of the two doubles
s_im     = (−fl(dy · ps0)) − (−fl(dy · ps1))
center   = print(C + s, P(zoom, width, height))  -- both shifts zero: unchanged
```

The anchor pixel's rendered coordinate, `C + fl(dx · ps)`, is then the same in both
frames up to the one rounding to `P` places.

**`pixel_delta(from, to, (width, height))`** — where `to`'s center lies from `from`'s,
in pixels of `from`'s frame (x right, y down):

```
ps = ps(width, from.zoom)
dx = round64((to.re − from.re) / ps)       -- exact quotient, one rounding
dy = round64((from.im − to.im) / ps)
```

`round64` rounds to the nearest double, ties to even, `±∞` past the range, and an exact
zero (`"0.1"` against `"0.10"`) is `+0.0`. `to`'s zoom does not enter; `height` is not
used and is taken for symmetry with the other operations.

**`positional(text)`** — the same value written positionally ("print" above) with the
same number of decimal places the precision rule counts, `max(−net_exponent, 0)`:
`"1e-5"` → `"0.00001"`, `"-1.2E-7"` → `"-0.00000012"`, `"2.5E1"` → `"25"`, `"0.10"` →
`"0.10"`, `"-0.0"` → `"0.0"`. For writing centers where a reader expects no exponent
(C# `decimal.Parse`). Python `decimal_text.positional`, C# `Navigation.Positional`.

## Why the places come from the frame

The orbit's working precision ([deep-zoom.md](deep-zoom.md) "Reference orbit") is
`F = max(zoom_bits, digit_bits) + 64`, with `digit_bits = bitlen(10^places)` from the
center's written places. A moved center carries `P ≈ z + digits(width) + 2` places, so
`digit_bits ≈ 3.32 z + 3.32 (digits + 2)`, while `zoom_bits = trunc(3.33 z) + 64`: for
any `digits + 2 ≤ 17` the digit term never wins anywhere in `z ∈ [−2, 290]`. So:

- **After any move that shifts the center, `F` is the zoom's own** — whatever the
  center was before, since both components now carry `P` places — so repeating `pan` or
  `zoom_at` at one zoom never changes the orbit's working bits. A zoom-only change (both
  shifts zero: `zoom_at(0, 0)`, or `pan(0, 0)` to a new zoom) keeps the strings, and
  with them any digit term they carry.
- The first move of a center with more places than its frame resolves (a long imported
  location) shortens it, both components. That is the point: a pan is a new location,
  and carrying digits the frame cannot show would only make every later orbit more
  expensive. A zoom about the center moves nothing and keeps the digits.
- Printing instead the places `F` covers would add at least the 64 guard bits per step
  — Heaton Fractal's `PrecisionPlan` ratchet — and printing a fixed number of
  significant digits (the Python playground's old `int(zoom) + 40`) lets the digit term
  dominate near an axis (82 places at zoom 20).

## Accuracy

- A recenter lands within `ps/800` of `C + fl(dx·ps)`: the rounding to `P` places.
- `pixel_delta(v, pan(v, dx, dy))` returns `(dx, dy)` within 1/800 pixel plus one
  rounding of the quotient.
- Under a long drag the rounding is systematic (every step re-rounds to the grid): at
  most `n/800` pixel over `n` steps. Tests that pin a drag or a recenter to tighter than
  the grid must allow for it.

## Conformance

Bit-exact. Vectors in [`../vectors/navigation/`](../vectors/navigation/), one case per
directory: `params.json` names the operation, its inputs, and the expected strings
(`center_re`, `center_im`, `zoom_log10`) or, for `pixel_delta`, the expected doubles as
IEEE-754 bit patterns (`dx_bits`, `dy_bits`). A `sequence` case applies a list of
operations in turn and pins every intermediate viewport, and the working bits after
each; they must not change at a fixed zoom. The cases include portrait frames (the
places come from the height's digits there) and a thirty-decade `zoom_at`, where a
difference of doubles instead of the exact one lands on the wrong grid point.
