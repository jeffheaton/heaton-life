# Patterns (bit-exact tier)

A **pattern** is a rectangular region of cells lifted out of one simulation
family, carried around (clipboard, zoo, RLE files), transformed, and stamped
back into a compatible world. Patterns are shareable artifacts: two
implementations must decode, transform, and stamp them identically.

## The pattern model

A pattern is `(family, width, height, cells, rule)`:

- `family` — the simulation family the cells belong to. **Patterns are
  family-bound**: a pattern may only be stamped into the family it came from.
  A Life-like glider cannot enter Wireworld or MergeLife — there is no
  conversion, only rejection.
- `cells` — row-major, the family's cell payload:

| family | cell payload | transparent cell (see Stamp) |
|---|---|---|
| life-like | byte 0/1 | 0 |
| wireworld | byte 0..3 | 0 (empty) |
| cyclic | byte 0..states−1 | 0 |
| mergelife | RGB byte triple | — (opaque only) |
| lenia (each variant its own family) | float64 [0,1] | 0.0 |
| gray-scott | (u, v) float64 pair | — (opaque only) |

  Elementary, boids, and fractals have no patterns (a space-time diagram, a
  point cloud, and a coordinate view are not cell regions).
- `rule` — the origin context, informative: the rulestring (life-like), states
  count (cyclic), or MergeLife rule. Stamping into the same family under a
  *different* rule is allowed — that is the point of a zoo — but implementations
  surface the origin rule so the user knows the pattern's home.

**Compatibility check** (normative, applied before any stamp):
1. Pattern family == target family, else reject.
2. Cyclic: `max(cells) < target.states`, else reject (values outside the target
   state range would corrupt the world).

## RLE text encoding (life-like, wireworld, cyclic)

The Life community's interchange format, Golly-compatible.

**Decoding** (liberal): `#`-prefixed comment lines are skipped; an optional
header `x = W, y = H[, rule = R]` may declare size and rule; the body uses run
counts followed by tags; whitespace is ignored; `!` ends the pattern.

The two dialects overlap: uppercase `B`/`O` mean dead/alive in two-state files
but states 2/15 in extended RLE. **Dialect detection** (normative): the pattern
is extended iff its body contains `.`, or any letter `A`–`X` other than `B`/`O`,
or its header rule is present and is not a Life-like rulestring (`B…/S…`).
Otherwise it is two-state. Then:

- Two-state: `b`/`B` = 0, `o`/`O` = 1.
- Extended: `.` = 0 (lowercase `b` also accepted as 0, `o` as 1),
  `A`..`X` = 1..24 (so `B` = 2, `O` = 15).
- `$` = end of row (run counts repeat rows) in both dialects.

Rows shorter than the width are padded with 0. The decoded size is the maximum
of the declared and actual extents. (A headerless extended pattern whose only
tags are `B`/`O` is indistinguishable from a two-state file and decodes as
two-state — canonical encodings always carry a header, so this never round-trips
wrong from a conforming encoder.)

**Encoding** (canonical): header `x = W, y = H, rule = R`; two-state grids
(max cell ≤ 1) use `b`/`o`; grids with any cell ≥ 2 use `.`/`A`..`X` (cells
above 24 are unencodable — an error). Runs of length 1 omit the count; trailing
dead runs in a row are omitted; rows end with `$` (last row with `!`); lines
wrap at 70 characters. Encoding then decoding reproduces the grid exactly.

MergeLife, Lenia, and Gray-Scott patterns are **not RLE-representable**; they
travel as raw cell payloads (the catalog/zoo container format, app-level).

## Transforms

`rotate90` (clockwise), `flip_h` (mirror left-right), `flip_v` (mirror
top-bottom), defined on the cell grid: `rotate90(p)[y][x] = p[h-1-x][y]`
(result is h×w), `flip_h(p)[y][x] = p[y][w-1-x]`, `flip_v(p)[y][x] =
p[h-1-y][x]`. For Gray-Scott both planes transform together; for MergeLife the
RGB triple moves as one cell.

## Extract and stamp

Both take a target grid `(W, H)`, a position `(x, y)` (pattern top-left), and
the target's boundary mode:

- **Extract**`(grid, x, y, w, h)` — copies the region into a new pattern.
  Torus targets wrap coordinates; dead-boundary targets read 0 outside.
- **Stamp**`(grid, pattern, x, y, transparent)` — writes the pattern.
  Torus targets wrap; dead-boundary targets clip (out-of-range cells are
  dropped). With `transparent = true`, cells equal to the family's transparent
  value (table above) are skipped, so a spaceship lands without erasing its
  surroundings; families marked opaque-only ignore the flag. Stamping does not
  reset the target's generation.

## Conformance

Bit-exact tier. Vectors in [`../vectors/patterns/`](../vectors/patterns/):
RLE decode cases (both dialects, comments/whitespace/no-header variants) with
expected grids, canonical encode strings, transform results, and stamp results
(wrap, clip, and transparent cases), all encoded with the families' vector
codecs. Round-trip (encode∘decode = identity) is additionally property-tested
in every implementation.
