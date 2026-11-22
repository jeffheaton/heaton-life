# Grid topologies

Conformance tier: **bit-exact**. Vectors: [`vectors/topology/`](../vectors/topology/)
(where a point past an edge lands, the halo, the bounded-grid suffix), grid runs in
[`vectors/lifelike/`](../vectors/lifelike/) and [`vectors/wireworld/`](../vectors/wireworld/),
and bounded pattern files in [`vectors/formats/`](../vectors/formats/).

A grid world is `W × H` cells. Its **topology** says what lies past each edge: nothing,
or more of the grid, when edges are joined. Life programs share a notation for these
bounded worlds, a suffix to the rule that names the topology and the size
(`B3/S23:T30,20` is Life on a torus 30 cells wide and 20 high), described on LifeWiki's
page "Bounded grids". This page defines the five topologies of that notation that a grid
can have, the one **halo fill** through which a family's step reads past its edges, and
the suffix itself, read and written in RLE files.

## The topologies

| `boundary` | Topology | Suffix | Edges |
|---|---|---|---|
| `dead` | plane | `P` | none joined: past every edge lies the family's blank |
| `torus` | torus | `T` | left to right and top to bottom; one pair may be shifted |
| `klein` | Klein bottle | `K` | one pair joined reversed (twisted), the other as on a torus; the twisted pair may be shifted |
| `cross` | cross-surface | `C` | both pairs joined reversed |
| `sphere` | sphere | `S` | each edge to the one beside it: top to left, right to bottom; square grids only |

A topology is three parameters:

- `boundary` — one of the five names above. The plane keeps the name the plane has
  always had in params, `dead`.
- `axis` — `x` or `y`, which pair of edges carries a shift or a twist: `x` the top and
  bottom edges, which a cell crosses moving along y and which shift or mirror its x; `y` the
  left and right edges. Default `x`.
- `shift` — an integer, default 0: how far a cell moves along `axis` when it crosses that
  pair of edges. Only a torus and a Klein bottle have one.

A Klein bottle's `axis` is its twisted pair. A torus's `axis` matters only with a shift,
and the plane, the cross-surface and the sphere have none, so a topology whose `axis`
means nothing has `axis` `x`: giving `y` there is allowed, and it reads back as `x`. A
shift on the plane, the cross-surface or the sphere is an error.

## Where a point past an edge lands

For a grid of `W × H` cells, a plane point `(x, y)` (any integers) stands for one cell
`(x′, y′)` of the grid, or, on the plane, for none. Inside the grid, `0 ≤ x < W` and
`0 ≤ y < H`, it is the cell itself. Outside, `⌊a / b⌋` is the floor of the quotient and
`a mod b` the remainder in `[0, b)`:

- **plane:** none.
- **torus**, axis `x`, shift `s`: with `k = ⌊y / H⌋`,
  `(x′, y′) = ((x + k·s) mod W, y − k·H)`. A cell that leaves across the bottom edge comes
  back across the top one `s` columns to its right (to its left for a negative `s`); one
  that leaves across the top comes back `s` columns to its left.
- **torus**, axis `y`, shift `s`: with `k = ⌊x / W⌋`,
  `(x′, y′) = (x − k·W, (y + k·s) mod H)`: leaving across the right edge moves a cell `s`
  rows down.
- **Klein bottle**, axis `x`, shift `s`: with `k = ⌊y / H⌋`, `y′ = y − k·H`, and
  `x′ = x mod W` when `k` is even, `(W − 1 + s − x) mod W` when `k` is odd. Crossing the top
  or bottom edge mirrors a cell's column (and moves it `s` columns); crossing the left or
  right edge doesn't.
- **Klein bottle**, axis `y`, shift `s`: with `k = ⌊x / W⌋`, `x′ = x − k·W`, and
  `y′ = y mod H` when `k` is even, `(H − 1 + s − y) mod H` when `k` is odd.
- **cross-surface**, for points with `−W ≤ x < 2W` and `−H ≤ y < 2H`: with `j = ⌊x / W⌋`,
  `k = ⌊y / H⌋`, `x₁ = x − j·W` and `y₁ = y − k·H`, `x′ = W − 1 − x₁` when `k ≠ 0` (else
  `x₁`) and `y′ = H − 1 − y₁` when `j ≠ 0` (else `y₁`). Crossing the top or bottom edge
  mirrors the column, and crossing the left or right edge mirrors the row.
- **sphere** (`W = H = n`), for points with `−n ≤ x < 2n` and `−n ≤ y < 2n`, by where the
  point lies:

  | where | `(x′, y′)` |
  |---|---|
  | above the grid: `0 ≤ x < n`, `y < 0` | `(−1 − y, x)` |
  | left of it: `x < 0`, `0 ≤ y < n` | `(y, −1 − x)` |
  | right of it: `x ≥ n`, `0 ≤ y < n` | `(y, 2n − 1 − x)` |
  | below it: `0 ≤ x < n`, `y ≥ n` | `(2n − 1 − y, x)` |
  | past a corner | the point turned half a turn about that corner: `x′` is `−1 − x` left of the grid and `2n − 1 − x` right of it, `y′` is `−1 − y` above and `2n − 1 − y` below |

  The top edge is folded onto the left edge, and the right edge onto the bottom: a cell
  that leaves across the top edge at column `c` comes in across the left edge at row `c`,
  and one that leaves across the right edge at row `r` comes in across the bottom edge at
  column `r`.

The cross-surface lands a point past a corner the same way as the sphere, half a turn about
that corner (the two formulas above agree there). The corners are where these two surfaces
are not flat: a corner cell is its own diagonal neighbor, and a pattern that runs into a
corner doesn't come out of it whole. Each formula is the same whichever edge a point is
taken across first, so a point past a corner lands where crossing its two edges in either
order lands it.

## The halo

A family's step reads each cell's neighbors from the **halo** of radius `r`: a grid of
`(W + 2r)` columns and `(H + 2r)` rows, row-major, whose cell `(i, j)` holds the value at
the plane point `(i − r, j − r)` — the grid's own cell inside it, the cell that point lands
on outside it, and the family's blank ([patterns.md](patterns.md#the-pattern-model)) where
it lands on none. The halo is filled from a generation's cells before the generation is
computed, so a cell at an edge has the same neighbors as one in the middle of the grid, and
every family whose neighborhood reaches at most `r` cells runs on every topology the same
way. `r` is the family's reach: 1 for Life-like and Wireworld, the range for a larger
neighborhood.

Life-like and Wireworld fill their halo this way, on every topology; a family built on
the halo later (Generations, Larger than Life, History, rule tables) takes all of them with
it. The other grid families keep their own edges: Elementary its torus or dead ends,
Cyclic its torus, MergeLife its padding.

`r` is at least 1. A torus, a Klein bottle and the plane take any radius. The
cross-surface and the sphere take a radius up to `min(W, H)`, the reach of the formulas
above. A family may ask more: a [Larger than Life](ltl.md#topologies) world of range r is
at least `2r + 1` cells wide and high, on every topology.

## Errors

A topology is an error, with a **reason**, the same in every port:

1. A `boundary` that isn't one of the five names: `unknown boundary 'NAME': expected dead,
   torus, klein, cross or sphere`.
2. An `axis` other than `x` or `y`: `unknown axis 'NAME': expected x or y`.
3. A nonzero shift on the plane, the cross-surface or the sphere: `the plane has no
   shift`, `the cross-surface has no shift`, `the sphere has no shift`.

With a grid's size, in this order:

4. A width or height below 1: `a grid has at least one row and one column`.
5. A sphere that isn't square: `a sphere is square`.
6. A Klein bottle with a shift whose twisted side (its width for axis `x`, its height for
   axis `y`) is odd: `a Klein bottle shifts only a side of even length`. On an odd side a
   shift gives nothing new: it moves the mirror line to another cell, and the bottle
   without a shift, moved over, is the same.

And a halo with a radius below 1, `the halo radius is at least 1`, or past `min(W, H)` on a
cross-surface or a sphere, `the halo is deeper than the grid`.

## The bounded-grid suffix

A file names a bounded world by adding a suffix to its rule: `B3/S23:T30,20`.

```
suffix = ":" kind side marks [ "," side marks ]
kind   = "P" | "T" | "K" | "C" | "S"          (either case)
side   = digit { digit }
marks  = [ "*" ] [ ( "+" | "-" ) digit { digit } ]
```

The first side is the width and the second the height; without a second side the height
is the width (a square grid, the way some programs write one). The kinds are the
topologies of the table above. A `*` marks a Klein bottle's twisted side, and `+n` or `-n`
a shift on that side: on the width it is axis `x` (the top and bottom edges), on the
height axis `y`. On a Klein bottle the shift follows the `*`.

```
:P30,20      plane, 30 × 20                :K30*,20     Klein bottle, top and bottom twisted
:T30,20      torus                         :K30,20*     Klein bottle, left and right twisted
:T30+5,20    torus, shift 5 along x        :K30*+1,20   Klein bottle, twisted and shifted along x
:T30,20-2    torus, shift −2 along y       :C30,20      cross-surface
:S30         sphere, 30 × 30
```

**Reasons.** Read from the left, the first problem found:

1. Text that doesn't start with `:`: `a bounded grid starts with ':'`.
2. After the `:`, no kind: `expected P, T, K, C or S after ':'`.
3. No digit where a side or a shift's size goes: `expected a number after 'C'`, where `C`
   is the character before (the kind, `,`, `+` or `-`).
4. Anything left that the grammar doesn't read: `unexpected 'TEXT' in the bounded grid`,
   `TEXT` everything from there to the end, as written.

Then, in this order, where a shift of 0 (`+0`, `-0`) counts as none:

5. A plane, cross-surface or sphere with a `*` or a shift: `the plane has no shift or
   twist`, `the cross-surface has no shift or twist`, `the sphere has no shift or twist`.
6. A torus with a `*`: `a torus has no twist`; with a shift on both sides: `a torus shifts
   one side only`.
7. A Klein bottle without a `*`, or with one on both sides: `a Klein bottle twists one
   side: '*' after its width or its height`; with a shift on the side without the `*`:
   `a Klein bottle shifts only its twisted side`.
8. A side of 0: `a side of 0 (an unbounded strip or tube) is not supported`. The notation
   writes an unbounded side as 0; a grid has none.
9. A side or a shift's size past 2,000,000,000: `a side or a shift is at most 2000000000`.
10. The topology's own errors with the size, 5 and 6 above.

**Canonical form.** `:`, the kind in uppercase, the width and its marks, `,`, the height
and its marks; the sphere is `:S` and its side alone. The marks are a Klein bottle's `*`
on its twisted side and a nonzero shift as `+n` or `-n` on its side (after the `*`).
Numbers have no leading zeros, and a shift of 0 is not written. Reading a suffix and
writing it gives its canonical form, and reading the canonical form gives the same world:
`:t30+0,20` is written `:T30,20`, `:K30*` is written `:K30*,30`, and `:S30,30` is written
`:S30`.

**API.** Reading raises (throws) an error that carries the reason: its message is
`invalid bounded grid '<text>': <reason> (spec/topology.md)`, and a topology's own is
`invalid topology: <reason> (spec/topology.md)`. `try_parse_bounded_grid(text)` gives the
grid and no reason, or no grid and the reason, without raising; .NET's
`BoundedGrid.TryParse(text, out grid, out reason)` answers true or false likewise.

**In a rule's text.** Where a rule is written with a suffix (an RLE header's `rule`, a
rule field a person types), the rule is everything before the first `:`, and the suffix
everything from it on, without the whitespace at its end
([rules.md](rules.md#grammar) lists the whitespace). A text without a `:` has no suffix.
`split_rule_suffix(text)` (.NET `BoundedGrid.SplitRule`) gives the rule's text and the
bounded grid, or none, and raises a bad suffix's error; the rule's text is compiled as
[rules.md](rules.md) says, by whoever uses it.

## Bounded patterns in files

An RLE header's rule may carry a suffix (`x = 30, y = 20, rule = B3/S23:T30,20`). The RLE
reader takes it off before it looks at the rule
([patterns.md](patterns.md#rle-text-encoding-life-like-wireworld-cyclic)): the dialect is
the rule's, the rule it reports is the text before the `:`, and the bounded grid is
reported beside it.

- **Into a grid,** a bounded file reads as its whole world, the pattern placed in it
  ([formats.md](formats.md#bounded-grids)). A host that opens the file as a world gives
  the world the suffix's size and topology.
- **Writing** a world, the RLE encoder adds the world's suffix to the rule and writes the
  whole grid, `x` and `y` its size, so any reader places it exactly in its world.
- **The unbounded universe** has no edges, so a bounded file is not read into it: the
  universe's readers refuse it, whatever its topology
  ([formats.md](formats.md#reading-into-the-unbounded-universe)). Only RLE carries a
  suffix; a Macrocell, Life 1.05 or Life 1.06 rule with one is no rule.
- **A family without topologies** has no world to give such a file: a host refuses to
  make one, or pastes the file's cells into a world it has. Cells pasted from a bounded
  file land like any pattern's; the suffix, like the rule, says where they came from.

## Editing

[Stamp and extract](patterns.md#extract-and-stamp) wrap on a torus without a shift; on
every other topology they clip, and read the blank past an edge. Advance Selection and
Advance Outside ([patterns.md](patterns.md#editing-a-region)) run their copy under the
world's own topology.

## API

- **Python** (`heaton_life.core.topology`, also exported from `heaton_life.core`):
  `Topology(boundary, shift=0, axis="x")` with `locate(x, y, width, height)` (the cell, or
  `None`) and `check(width, height)`; `Halo(topology, width, height, radius=1)` with
  `fill(cells, blank=0)` (a new halo array) and `sources` (each halo cell's source index,
  `−1` for the blank); `BoundedGrid(width, height, topology)` with `suffix`;
  `parse_bounded_grid`, `try_parse_bounded_grid` and `split_rule_suffix`. `LifeLike` and
  `Wireworld` take `boundary`, `shift` and `axis` and give `topology`.
- **.NET:** `Boundary` (`Torus`, `Dead`, `Klein`, `Cross`, `Sphere`), `TopologyAxis`
  (`X`, `Y`), the `Topology` struct (`Locate`, `Check`, `Parse` from the params' names,
  `Name`), `Halo` (`Fill` into a caller's buffer, allocating nothing; `Source`),
  `BoundedGrid` (`Parse`, `TryParse`, `SplitRule`, `Suffix`), and `LifeLike` and
  `Wireworld` constructors that take a `Topology`.

## Vector encoding

Each case under `vectors/topology/` has a `params.json` with `family: "topology"`,
`tier: "bit-exact"`, `spec_version`, a `kind`, and `cases`:

- `halo` — each case a `width`, `height`, `boundary`, `shift`, `axis` and `radius`, and the
  halo's `map`: its rows, each entry the index `y′·W + x′` of the cell the halo cell holds,
  or −1 for the blank; or `error: true` with the `reason`. The maps of a torus or Klein
  bottle with a shift are in `halo-shifted/`, the rest in `halo/`.
- `suffix` — each case an `input` and its `canonical` suffix with the world's `width`,
  `height`, `boundary`, `shift` and `axis`; or `error: true` with the `reason`.
- `split` — each case an `input` (a rule's text) with its `rule` and its canonical
  `suffix` (or `null`); or `error: true` with the `reason`.

Grid runs on every topology are cases of [`vectors/lifelike/`](../vectors/lifelike/) and
[`vectors/wireworld/`](../vectors/wireworld/) whose params carry `shift` and `axis`
(absent, they are 0 and `x`). Bounded files read, measured and refused by the universe are
cases of [`vectors/formats/`](../vectors/formats/) with a `bounded_grid` (the canonical
suffix). Runners are strict: an unknown key or `spec_version` fails the case.
