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

The Life community's interchange format, in both of its common dialects.

**Decoding** (liberal): `#`-prefixed lines are not cells (`#N`, `#O`, `#C` and `#c`
carry the pattern's [metadata](formats.md#metadata), the others are skipped); an optional
header `x = W, y = H[, rule = R]` may declare size and rule; the body uses run
counts followed by tags; whitespace is ignored; `!` ends the pattern. Lines split and
strip as [formats.md](formats.md#bytes-and-text) says.

**Bounded grids.** The header's rule may end in a [bounded-grid
suffix](topology.md#the-bounded-grid-suffix), `rule = B3/S23:T30,20`: the pattern lives in
a world of that size and topology. The rule is the text before the first `:`, and
everything below that reads the header's rule reads that text; the suffix is read as
topology.md says (a bad one is an error of the decode) and reported beside the rule.
[formats.md](formats.md#bounded-grids) places the pattern in its world.

**Survival/birth order.** A header's rule written survival digits first, `rule = 23/3`,
is the Life-like rule `B3/S23`, read as [formats.md](formats.md#rules-in-survivalbirth-order)
says, after any bounded-grid suffix comes off (`rule = 23/3:T30,20`). Everything below
reads the rule so converted, and so does the encoder: given `23/3`, it writes `B3/S23`.

The two dialects overlap: uppercase `B`/`O` mean dead/alive in two-state files
but states 2/15 in extended RLE. **Dialect detection** (normative): the pattern
is extended iff its body contains `.`, or any letter `A`–`X` other than `B`/`O`,
or its header rule is present and is not a Life-like rule ([rules.md](rules.md): any
of its notations, preset names excluded).
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

**Extent.** What a decode would give is found by a scan that keeps only counters, so
a pattern is measured without a grid being made of it:

- `width`, `height` — the decoded size above: the larger of the header's `W`, `H` and
  the body's own extents, where a row is as long as its runs add up to (dead runs
  included) and the rows are one more than the row ends before `!`;
- `live` — the inclusive box `(x0, y0, x1, y1)` of the non-zero cells, or none;
- `population` — how many cells are non-zero;
- `rule` and the dialect, as decoding finds them, and the bounded grid, if any.

A run count is any number of digits and every one of these is an exact integer, since a
few bytes of RLE can describe more cells than any memory holds: `o999999999b!` is a
billion cells wide, and `x = 1000000000, y = 1000000000` declares 10¹⁸ of them around
whatever follows. Measure a file that came from outside before decoding it.

**The decode limit.** A decoder finds the extent first and refuses (an error) a pattern
whose `width × height` is past its cell limit, before any grid is made. The limit
defaults to 2²⁶ = 67,108,864 cells, an 8192 × 8192 grid, and the caller may set another
or lift it.

**Trimmed decoding** gives only the `live` box: the header's size and any dead margin are
dropped, the limit applies to that box, and a pattern with no non-zero cell is an error.
It is the decode for loading a pattern file into a world, where what matters is the
pattern and not the rectangle its author saved around it.

**Encoding** (canonical): header `x = W, y = H, rule = R`; two-state grids
(max cell ≤ 1) use `b`/`o`; grids with any cell ≥ 2 use `.`/`A`..`X` (cells
above 24 are unencodable — an error). Runs of length 1 omit the count; trailing
dead runs in a row are omitted; rows end with `$` (last row with `!`), and k ≥ 2
consecutive `$` are written as one token `k$`, so a run of empty rows costs one
token; lines wrap at 70 characters. The header names a Life-like rule in its canonical
form ([rules.md](rules.md#canonical-form)), so it reads back as the same rule however it
was spelled (`b3 / s32` is written `B3/S23`), and any other rule as given. Encoding then
decoding reproduces the grid exactly. Given [metadata](formats.md#metadata), the
encoder writes its lines (`#N`, `#O`, then `#C`) before the header; without it, the text
is exactly the above. Given a [topology](topology.md), the grid is a whole world: the
header's rule is followed by the world's suffix in canonical form, `x = 30, y = 20, rule =
B3/S23:T30,20` for a 30 × 20 torus, and the body is unchanged; without one, no suffix is
written.

MergeLife, Lenia, and Gray-Scott patterns are **not RLE-representable**; they
travel as raw cell payloads (the catalog/zoo container format, app-level).

## RLE in the unbounded universe

The [HashLife](hashlife.md) universe has no grid, so RLE there carries a position and
never becomes a dense array. The position goes on the file's **first line**, in extended
RLE's `#CXRLE` comment:

```
#CXRLE Pos=<x>,<y> Gen=<n>
```

Space-separated `key=value` fields: `Pos` is the top-left cell of the pattern's
rectangle (y down), two integers separated by a comma, each an optional `-` and one or
more ASCII digits; `Gen` is the generation, ASCII digits only. Both may be any size; any
other spelling of either is an error. Either may be missing; unknown keys are ignored. The `#C` prefix makes other readers skip the
line as a comment. Anywhere but the first line, `#CXRLE` is an ordinary comment.

**Reading into the universe.** The dialect rules above apply, and the file must be
two-state (an extended file, or a state above 1, is an error) and unbounded (a rule with a
[bounded-grid suffix](topology.md#the-bounded-grid-suffix) is an error: the universe has
no edges). The pattern's top-left
cell lands at `Pos`, or at (0, 0) without it — never centered, since the plane has no
center to speak of. Cells are placed as decoded; the header's `x`/`y` declare nothing the
universe needs. The rule is the header's, or `B3/S23` without one. The generation is
`Gen`, or 0. Every cell must lie in the [editing box](hashlife.md#editing), or the file
is refused.

**Writing from the universe.** The first line is `#CXRLE Pos=<x0>,<y0>`, with
` Gen=<n>` appended when the generation is above 0, where (x0, y0) is the top-left of
the bounding box. Then comes the canonical encoding above of the bounding box's cells,
the header naming the universe's rule: the same tokens and line breaks `rle_encode`
produces for that rectangle. Since a run of row ends is one token, the text grows with
the live rows, not the box's height: two live rows 2·10⁹ apart are joined by one
`2000000000$`. An empty universe writes `#CXRLE Pos=0,0`, then
`x = 0, y = 0, rule = <rule>`, then `!`. A pattern that reaches outside the editing box
is refused; [Macrocell](macrocell.md) carries it. Given [metadata](formats.md#metadata),
its lines go right after the `#CXRLE` line, before the header.

## Transforms

`rotate90` (clockwise), `flip_h` (mirror left-right), `flip_v` (mirror
top-bottom), defined on the cell grid: `rotate90(p)[y][x] = p[h-1-x][y]`
(result is h×w), `flip_h(p)[y][x] = p[y][w-1-x]`, `flip_v(p)[y][x] =
p[h-1-y][x]`. For Gray-Scott both planes transform together; for MergeLife the
RGB triple moves as one cell.

`rotate90_ccw` turns the other way: `rotate90_ccw(p)[y][x] = p[x][w-1-y]`
(result is h×w). It undoes `rotate90`, and equals three of them.

## Extract and stamp

Both take a target grid `(W, H)`, a position `(x, y)` (pattern top-left), and
the target's boundary mode: torus or dead. A world whose [topology](topology.md) is a
torus without a shift wraps; every other topology clips, as dead edges do.

- **Extract**`(grid, x, y, w, h)` — copies the region into a new pattern.
  Torus targets wrap coordinates; dead-boundary targets read 0 outside.
- **Stamp**`(grid, pattern, x, y, mode)` — writes the pattern.
  Torus targets wrap; dead-boundary targets clip (out-of-range cells are
  dropped). The pattern's cells land in row-major order, so a pattern larger
  than a torus lands its later cells over its earlier ones. Stamping does not
  reset the target's generation. The mode says how a pattern cell `p` and the
  target cell `t` it lands on combine:

  | mode | result | families |
  |---|---|---|
  | `copy` (the default) | `p` | all |
  | `or` | `t` where `p` is the family's transparent value (table above), else `p` | all but the opaque-only |
  | `xor` | `t xor p` | life-like |
  | `and` | `t and p` | life-like |

  `or` lands a spaceship without erasing its surroundings; `transparent = true`
  is the same mode under its older name. `xor` toggles each cell under a live
  pattern cell, and `and` keeps a cell alive only where the pattern is alive
  too, so the pattern's dead cells clear what lies under them. Both are
  two-state operations: every pattern cell, and every target cell the pattern
  lands on, must be 0 or 1, and a stamp that finds another value is an error
  that changes nothing. The multi-state families (wireworld, cyclic) stamp with
  `copy` and `or`, and the opaque-only families with `copy` alone.
- **Clear**`(grid, x0, y0, x1, y1)` — restores every cell of the inclusive
  rectangle to the family **blank** (table above). The blank is a family fact,
  not an app choice: Gray-Scott's blank is the substrate (U = 1, V = 0), not
  zero. Clearing, like stamping, does not reset the generation.

## Editing a region

A **region** is an inclusive rectangle `(x0, y0, x1, y1)` of a grid with
`0 ≤ x0 ≤ x1 < W` and `0 ≤ y0 ≤ y1 < H`; any other rectangle is an error that
changes nothing, and a region never wraps around a torus. Like stamping, these
operations leave the generation alone. [HashLife](hashlife.md#editing) has the
same ones on the unbounded plane.

- **Random fill**`(grid, x0, y0, x1, y1, density, seed)` — life-like only, the
  one two-state grid family. Every cell of the region becomes the matching cell
  of the soup of a world the region's size ([lifelike.md](lifelike.md)
  "Initialization"): [PCG32](rng.md) stream 0 seeded with `seed`, one draw per
  cell of the region in row-major order (y outer, x inner), alive iff
  `draw < floor(density · 2³²)`, `density` in [0, 1]. The draws depend on the
  region's size alone, not on where it lies, so HashLife's `fill_random` of a
  rectangle of the same size and seed gives the same cells.
- **Advance Selection**`(x0, y0, x1, y1, n)` — the region evolves n ≥ 0
  generations as if nothing else existed: make a copy of the world in which
  every cell outside the region is the family blank, run the copy n generations
  under the world's own rule and boundary, and copy the copy's region back.
  Cells outside the region are untouched.
- **Advance Outside**`(x0, y0, x1, y1, n)` — the mirror image: the copy has the
  region blank instead, and everything outside the region is copied back; the
  region keeps its cells.

Advance Selection and Advance Outside are defined for life-like, wireworld, and
cyclic grids. (MergeLife pads its edges with the most common value of the whole
grid, so no part of a MergeLife world evolves on its own; the continuous
families don't have them.)

**Turning a region** in place turns it as [HashLife](hashlife.md#rectangle-transforms)
turns a rectangle: a quarter turn about its center that never drifts, the rectangle
turning with its cells. `turned_rect(x0, y0, x1, y1, clockwise)` gives the rectangle the
cells land on — the one HashLife's `rotate_rect` returns, by the same formula — for any
integers and without changing anything; a rectangle with x1 < x0 or y1 < y0 is an error.
A grid of any family turns a region by extracting it, turning the copy with `rotate90`
(clockwise) or `rotate90_ccw`, clearing the region, and stamping the copy (mode `copy`)
at the turned rectangle's top-left: the new rectangle takes the turned cells, the rest of
the old one is blank, and in a life-like grid the cells are exactly the ones
`rotate_rect` gives. A region that isn't square can turn past an edge of the grid; a
turned rectangle that isn't a region of the grid is the caller's to refuse.

Nothing is held back inside the copy. In Advance Selection the region's cells
may grow past it during the n generations, and what they grow into acts back on
the region until the copy's region is taken, just as it would if the region
were alone in its world. Only one generation is as simple as "the region's
cells, with blank neighbors outside it". Advance Outside likewise lets the
outside grow into the blank region, and back out of it, before the region's own
cells are put back.

**Edges.** The copy has the world's boundary, its whole [topology](topology.md). With
dead edges, cells beyond them read dead in the copy as in the world. On a torus, cells
that cross an edge come back at the opposite one, in the copy as in the world: a pattern
advanced in a region can leave it, wrap around, and enter it again within n generations,
and Advance Outside's outside wraps across the seam as usual. A region spanning the
whole width of a torus is its own neighbor across the seam (its left column sees
its right column), as in the world, and likewise for its height. The other topologies
join their edges in the copy as they do in the world. On the whole grid, Advance
Selection is n ordinary generations that leave the counter alone, and Advance Outside
changes nothing.

**Canceling.** A host can stop an advance from another thread, as it stops a
[HashLife step](hashlife.md#cancellation): .NET passes a `CancellationToken` to
`AdvanceSelection` or `AdvanceOutside`, and in Python another thread calls the world's
`cancel()`. The advance stops between generations (.NET's grids poll within one too) and
throws what a canceled HashLife step throws, `OperationCanceledException` in .NET and
`StepCanceled` in Python, and the world is exactly as it was before the advance began: its
cells, its generation, and its start, with no partial result for undo to repair.
Cancellation never changes a result: an advance that runs to its end gives the same cells
with a token or without one. As with HashLife, an advance of 0 generations checks nothing,
and a Python `cancel()` reaches only an advance that is running; each advance starts by
forgetting an earlier request. HashLife's own Advance Selection and Advance Outside cancel the
same way and leave the universe as it was ([hashlife.md](hashlife.md#advancing-part-of-the-universe)).

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
codecs. `extent-*` pin the measured extent of files no decoder could hold (the numbers
are decimal strings: some pass 2⁶⁴), `limit-*` the decode limit, default and given, and
`trim-*` trimmed decoding. Round-trip (encode∘decode = identity) is additionally
property-tested in every implementation. RLE in the unbounded universe is pinned by the `rle-*` cases of
[`../vectors/hashlife/`](../vectors/hashlife/). Metadata, read and written, and the other
pattern file formats are pinned by [`../vectors/formats/`](../vectors/formats/)
([formats.md](formats.md#conformance)).

Region editing (spec 0.16.0): `transform-ccw` adds `rotate90_ccw` to the transform
outputs; `stamp-mode-*` stamp with a `mode` instead of `transparent` (with `error: true`
where a two-state mode meets another value, and the grid must come back unchanged);
`fill-random-*` (kind `fill-random`) fill a region of a background grid; and
`advance-*` (kind `advance`) build a `world` — `family` (`lifelike`, `wireworld` or
`cyclic`) and that family's parameters — from `grid`, run Advance Selection or, with
`outside: true`, Advance Outside on `region` for `n` generations, and expect the grid
`expected` at generation 0, or `error: true` and the grid unchanged. HashLife's editing
tools are pinned by the `edit-*` cases of [`../vectors/hashlife/`](../vectors/hashlife/).
`turned-rect` (kind `turned-rect`) lists `cases`, each a `rect` `[x0, y0, x1, y1]` and
`clockwise`, with the `expect`ed rectangle or `error: true`; the numbers are decimal
strings, some past 2⁶⁴. The rectangles cover every parity of x0, y0, x1 and y1, and a
runner also checks that HashLife's `rotate_rect` returns the same rectangle wherever both
lie in its editing box.

Bounded grids (spec 0.16.0): `rle-bounded-*` decode headers whose rule carries a
[bounded-grid suffix](topology.md#the-bounded-grid-suffix), the dialect and the expected
`rule` being the text before its `:`; an `advance` case's `world` may name a whole
topology, `shift` and `axis` beside `boundary` where they aren't 0 and `x`
(`advance-selection-life-klein`, `advance-outside-wireworld-sphere`). Bounded files read
into their world are pinned under [`../vectors/formats/`](../vectors/formats/).
`rle-survival-birth*` and `extent-survival-birth` decode headers whose rule is written in
survival/birth order, one with a bounded-grid suffix: the expected `rule` is the
`B…/S…` form, and the dialect two-state.
