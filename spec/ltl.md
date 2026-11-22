# Larger than Life

Conformance tier: **bit-exact**. Vectors: [`vectors/ltl/`](../vectors/ltl/) (grid runs),
[`vectors/ltl-rules/`](../vectors/ltl-rules/) (rule texts and neighborhoods),
[`vectors/patterns/`](../vectors/patterns/) (`*-ltl*`) and
[`vectors/formats/`](../vectors/formats/) (`*-ltl*`).

**Larger than Life** (LtL) generalizes Life to a neighborhood of range r: a cell counts the
live cells in a box, a diamond or a disk of radius r around it, and is born or survives
when that count falls in a range of numbers. It may also have more than two states, cells
that stop surviving then decaying through dying states as Generations rules do. Bosco's
Rule, `R5,C0,M1,S34..58,B34..45,NM`, is the classic example. LtL runs on bounded grids
only, with any [topology](topology.md).

## State

- A grid of cells, unsigned bytes, shape `(height, width)`, row-major.
- A rule of S states (2 to 256): `0` dead, `1` alive, and, when S ≥ 3, the dying states
  `2` to `S − 1`. A cell is **alive** only in state 1.

## The rule

A rule is six things: the **range** r (1 to 500), the number of **states** S, whether the
**middle** cell counts itself (M), the **survival** counts `smin..smax`, the **birth**
counts `bmin..bmax` (each an inclusive range of whole numbers), and the **neighborhood**:
the Moore box, the von Neumann diamond or the circle.

### Rule text

```
rule   = ws* ( long | short ) ws*
long   = "R" n "," "C" n "," "M" ("0"|"1") "," "S" n ".." n "," "B" n ".." n [ "," "N" hood ]
short  = n "," n "," n "," n "," n            (r, bmin, bmax, smin, smax)
hood   = "M" | "N" | "C"
n      = digit { digit }
```

- Letters may be written in either case; `digit` is an ASCII digit, and `ws` is
  [rules.md](rules.md#grammar)'s whitespace, allowed only at the two ends.
- `R`: the range. `C`: the states, where `0` and `2` both mean two states. `M1`: the
  middle cell counts itself. `S`, `B`: the survival and birth counts. `N`: `M` the Moore
  box, `N` the von Neumann diamond, `C` the circle; without the field, the Moore box.
- The short form is the five numbers range, birth min, birth max, survival min and
  survival max; it means two states, `M1` and the Moore box.
- The fields come in the order above.

**Canonical form:** `R<r>,C<c>,M<m>,S<smin>..<smax>,B<bmin>..<bmax>,N<hood>`, in uppercase,
numbers without leading zeros, `c` 0 for two states (the state count otherwise), and the
`N` field always written. Bosco's Rule in canonical form is `R5,C0,M1,S34..58,B34..45,NM`;
`5,34,45,34,58` and `r5,c2,m1,s34..58,b34..45` are the same rule.

### Reasons

A text that is no rule gives a **reason**, the same in every port, for the first problem
found. Reading the text, whitespace at the ends skipped:

1. Text that starts with neither `R` nor a digit: `expected R…,C…,M…,S…,B…,N… or five
   numbers r,bmin,bmax,smin,smax`.
2. The long form, its fields split at the commas:
   - fewer than five fields or more than six: `expected the fields R, C, M, S, B and N, in
     that order`;
   - then each field in turn: `expected R and the range, not 'TEXT'`, `expected C and the
     number of states, not 'TEXT'`, `expected M0 or M1, not 'TEXT'`, `expected S and a range
     of counts S<min>..<max>, not 'TEXT'`, the same for `B`, and `expected NM, NN or NC, not
     'TEXT'`, where `TEXT` is the field as written.
3. The short form: anything but five fields of digits: `expected five numbers
   r,bmin,bmax,smin,smax`.

Then, in this order:

4. A range outside 1 to 500: `the range is 1 to 500, not N`.
5. A state count other than 0, or 2 to 256: `C is 0 or 2 (two states) or 3 to 256, not N`.
6. Survival, then birth: a count past 1002001 (the cells of the largest neighborhood):
   `a count is at most 1002001`; a min above its max: `S<min>..<max> is empty` (or `B…`),
   the numbers without leading zeros.

**API.** Parsing raises (throws) an error whose message is `invalid Larger than Life rule
'<text>': <reason> (spec/ltl.md)`. `try_parse_ltl_rule(text)` gives the rule and no reason,
or no rule and the reason; .NET's `LtlRule.TryParse(text, out rule, out reason)` answers
true or false likewise. A rule's text may carry a [bounded-grid
suffix](topology.md#the-bounded-grid-suffix), which is no part of the rule.

## Neighborhoods

The neighborhood of a cell holds the cells at offsets (dx, dy) from it with:

| `N` | Neighborhood | Cells |
|---|---|---|
| `M` | Moore box | `|dx| ≤ r` and `|dy| ≤ r` |
| `N` | von Neumann diamond | `|dx| + |dy| ≤ r` |
| `C` | circle | `dx² + dy² ≤ r² + r`: the cells whose centers lie closer than r + ½ to the cell's own |

Each is a stack of rows: row `dy`, for `|dy| ≤ r`, holds `|dx| ≤ w(dy)`, where the
**half-width** `w(dy)` is `r` (box), `r − |dy|` (diamond), or `⌊√(r² + r − dy²)⌋` (circle,
an exact integer square root). The neighborhood's **size** is `Σ (2·w(dy) + 1)`, the cell
itself included; under `M0` the cell itself is not in it. At `r = 1` the circle is the
3 × 3 box.

## Evolution

Every cell's **count** is the number of alive cells (state 1) in its neighborhood, read
through the grid's [halo](topology.md#the-halo) of radius r, so the cells past an edge are
the ones the topology puts there, and dead past the plane's edge. Then, synchronously:

| State | Next |
|---|---|
| 0 dead | 1 if `bmin ≤ count ≤ bmax`, else 0 |
| 1 alive | 1 if `smin ≤ count ≤ smax`; else 2 when S ≥ 3, 0 when S = 2 |
| k dying (2 ≤ k < S) | k + 1, or 0 after `S − 1` |

Under `M1` a cell's own state counts when it is alive. A dying cell is neither alive nor
born. Counts are exact integers; summed-area tables (the box) and row prefix sums (the
diamond and the circle) give them in a time that does not grow with r for the box and grows
with the rows of the neighborhood for the others.

## Topologies

LtL runs on grids only, with any topology of [topology.md](topology.md): the plane, the
torus or Klein bottle with or without a shift, the cross-surface, and the sphere. A world
of range r is at least `2r + 1` cells wide and high, on every topology, so no cell is in a
neighborhood twice and the cross-surface's and sphere's halos reach: a smaller world is an
error, `a Larger than Life world of range <r> is at least <2r + 1> cells wide and high`,
with the numbers.

The [HashLife universes](hashlife.md) never run LtL: the two-state universe and the
[multi-state](hashlife-multistate.md) one refuse an LtL rule, whether it is given or read
from a file, with the reason `R… is a Larger than Life rule: it runs on a bounded grid,
never on the unbounded plane`.

## Parameters

```json
{
  "rule": "R5,C0,M1,S34..58,B34..45,NM",
  "width": 128,
  "height": 128,
  "init": "soup",
  "density": 0.5,
  "seed": 0,
  "boundary": "torus",
  "shift": 0,
  "axis": "x"
}
```

`rule` is canonical. `init` is `soup`, `blob`, `single` or `array`, seeded exactly as
[lifelike.md](lifelike.md#initialization) seeds a grid (alive is state 1). `boundary`,
`shift` and `axis` are a [topology](topology.md#the-topologies).

## Files

An RLE file whose header names an LtL rule, in either form and with or without a
bounded-grid suffix (`rule = R5,C0,M1,S34..58,B34..45,NM:T200,200`), holds an LtL world
or pattern. Its header's rule is no Life-like rule, so the file is in the extended
dialect ([patterns.md](patterns.md#rle-text-encoding-life-like-wireworld-cyclic)): `b` or
`.` is state 0, `o` or `A` state 1, and `B`, `C`, … the dying states, past 24 the
two-letter tags `pA` … `yO` (25 to 255). A world writes its canonical rule, and its
topology's suffix, as canonical RLE does any rule.

## Editing

LtL grids are a pattern family of their own (`ltl`: byte states, transparent 0, blank 0;
[patterns.md](patterns.md#the-pattern-model)) and have every editing tool the other grid
families have: paste modes (`xor` and `and` on two-state cells only), transforms, clear,
random fill (state 1 for alive), Advance Selection and Advance Outside
([patterns.md](patterns.md#editing-a-region), cancelable), and `set_state` with
`keep_start` ([README.md](README.md#a-worlds-state-and-its-start)).

## Frames

A two-state rule's frame is `state × 255`, as Life's is. With more states it is the state
itself (0 to S − 1), for a color per state: by default Generations' palette of its C
([render.md](render.md#default-palettes)).

## Vector encoding

- `vectors/ltl/`: grid runs, each checkpoint a grayscale PNG of the raw states; `params`
  has every key above.
- `vectors/ltl-rules/`: `params.json` only, with a `kind`:
  - `rules` — each case an `input` and its `canonical`, `range`, `states`, `middle`,
    `survival` and `birth` (`[min, max]`), `neighborhood` (`moore`, `vonneumann` or
    `circular`) and `size`; or `error: true` with the `reason`.
  - `neighborhoods` — each case a `neighborhood` and `range`, its `half_widths`
    (`w(dy)` for `dy` from `−r` to `r`) and `size`.

Runners are strict: an unknown key or `spec_version` fails the case.

## Oracles (implementation tests)

- `R1,C0,M0,S2..3,B3..3,NM` is Conway's Life: a run equals the Life-like grid's under
  `B3/S23` on the same topology.
- Counts from the prefix sums equal a direct sum over the neighborhood's cells, on every
  topology.
