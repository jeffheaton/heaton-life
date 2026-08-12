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

| family | cell payload | transparent cell (see Stamp) | blank (see Clear) |
|---|---|---|---|
| life-like | byte 0/1 | 0 | 0 |
| wireworld | byte 0..3 | 0 (empty) | 0 (empty) |
| cyclic | byte 0..states−1 | 0 | 0 |
| mergelife | RGB byte triple | — (opaque only) | (0, 0, 0) black |
| lenia (each variant its own family) | float64 [0,1] | 0.0 | 0.0 |
| gray-scott | (u, v) float64 pair | — (opaque only) | (1.0, 0.0) substrate |

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
- **Clear**`(grid, x0, y0, x1, y1)` — restores every cell of the inclusive
  rectangle to the family **blank** (table above). The blank is a family fact,
  not an app choice: Gray-Scott's blank is the substrate (U = 1, V = 0), not
  zero. Clearing, like stamping, does not reset the generation.

## Built-in patterns

Every implementation ships the same canonical set of built-in patterns —
code-defined encodings of public mathematical commons (authored from their
published cell coordinates, no copied pattern files). Names, families, origin
rules, and cells are all part of the set; the bodies below are canonical RLE
(decode with the listed rule as the header rule). Life patterns carry their
home rule; the HighLife replicator exists to show same-family-different-rule
stamping.

| name | family | rule | RLE body |
|---|---|---|---|
| Glider | life-like | B3/S23 | `bo$2bo$3o!` |
| Lightweight spaceship | life-like | B3/S23 | `bo2bo$o$o3bo$4o!` |
| Middleweight spaceship | life-like | B3/S23 | `3bo$bo3bo$o$o4bo$5o!` |
| Heavyweight spaceship | life-like | B3/S23 | `3b2o$bo4bo$o$o5bo$6o!` |
| Blinker | life-like | B3/S23 | `3o!` |
| Toad | life-like | B3/S23 | `b3o$3o!` |
| Beacon | life-like | B3/S23 | `2o$2o$2b2o$2b2o!` |
| Pulsar | life-like | B3/S23 | `2b3o3b3o2$o4bobo4bo$o4bobo4bo$o4bobo4bo$2b3o3b3o2$2b3o3b3o$o4bobo4bo$o4bobo4bo$o4bobo4bo2$2b3o3b3o!` |
| Pentadecathlon | life-like | B3/S23 | `2bo4bo$2ob4ob2o$2bo4bo!` |
| Block | life-like | B3/S23 | `2o$2o!` |
| Beehive | life-like | B3/S23 | `b2o$o2bo$b2o!` |
| Loaf | life-like | B3/S23 | `b2o$o2bo$bobo$2bo!` |
| R-pentomino | life-like | B3/S23 | `b2o$2o$bo!` |
| Diehard | life-like | B3/S23 | `6bo$2o$bo3b3o!` |
| Acorn | life-like | B3/S23 | `bo$3bo$2o2b3o!` |
| Gosper glider gun | life-like | B3/S23 | `24bo$22bobo$12b2o6b2o12b2o$11bo3bo4b2o12b2o$2o8bo5bo3b2o$2o8bo3bob2o4bobo$10bo5bo7bo$11bo3bo$12b2o!` |
| Replicator (HighLife) | life-like | B36/S23 | `2b3o$bo2bo$o3bo$o2bo$3o!` |
| Clock | wireworld | WireWorld | `CBA3C$C4.C$6C!` |
| Diode (passes right) | wireworld | WireWorld | `3.2C$4C.3C$3.2C!` |

The set is **behavior-pinned** in every implementation's test suite: stills
stay, oscillator periods hold, ships translate, the gun fires, the replicator
copies itself in B36/S23, the Wireworld clock keeps circulating, and the diode
passes electrons exactly one way.

## Conformance

Bit-exact tier. Vectors in [`../vectors/patterns/`](../vectors/patterns/):
RLE decode cases (both dialects, comments/whitespace/no-header variants) with
expected grids, canonical encode strings, transform results, and stamp results
(wrap, clip, and transparent cases), all encoded with the families' vector
codecs. Round-trip (encode∘decode = identity) is additionally property-tested
in every implementation.
