# Generations

Conformance tier: **bit-exact**. Vectors: grid runs in
[`vectors/generations/`](../vectors/generations/), rule texts in
[`vectors/generations-rules/`](../vectors/generations-rules/), and unbounded runs in
[`vectors/hashlife-multistate/`](../vectors/hashlife-multistate/).

A Generations rule is a Life-like rule ([rules.md](rules.md)) whose cells take time to
die: a live cell that does not survive passes through C − 2 dying states before it is
dead, and while dying it neither counts as a live neighbor nor can be born again. Brian's
Brain (`B2/S/C3`) and Star Wars (`B2/S345/C4`) are the best known; with C = 2 a
Generations rule is its Life-like rule.

## State

- 2-D grid of cells, unsigned bytes from `0` to `C − 1`, C the rule's number of states
  (2 to 256): `0` is dead, `1` alive, and `2` … `C − 1` dying, `C − 1` the last stage
  before dead.
- Shape `(height, width)`, row-major, origin top-left, index `i = y * width + x`.

## Gather

Each cell's neighborhood index ([rules.md](rules.md#the-transition-table)) over the
**live cells only**: a cell counts as alive exactly when its state is 1, so a dying cell
counts as dead. The block is read from the grid's [halo](topology.md#the-halo) of radius
1, the cells past an edge the ones the grid's [topology](topology.md) puts there, and 0
(dead) past a dead edge.

## Respond + Integrate

Synchronous replacement, every cell at once, with the Life-like rule's table:

| state s | next |
|---|---|
| 0 (dead) | `table[index]`: 1 when born, else 0 |
| 1 (alive) | 1 when `table[index]` is 1 (it survives); else it starts dying: 2, or 0 when C = 2 |
| 2 … C − 1 (dying) | s + 1, and C − 1 becomes 0 |

That is, `next = 1` if s ≤ 1 and `table[index] = 1`, `next = 0` if s = 0 otherwise, and
`next = (s + 1) mod C` for every other cell. Rules with B0 run as written on a grid, as
Life-like rules do ([lifelike.md](lifelike.md#respond--integrate)).

## Rules

A rule names its Life-like rule and its number of states, in either of two spellings:

```
generations = ws* ( bsc | sbc ) ws*
bsc         = life ws* "/" ws* ( "C" | "c" ) count
sbc         = digits "/" digits "/" count
digits      = { "0"–"8" }
count       = digit { digit }
```

- **`B…/S…/C…`** (`bsc`): `life` is any Life-like rule as [rules.md](rules.md#grammar)'s
  grammar reads it — `B…/S…` with digits or letter classes, with `H` or `V`, or a `MAP`
  string — and the count follows a `/` and a `C` in either case. Preset names are not
  rules here.
- **Survival/birth/count** (`sbc`): the survival digits, the birth digits and the count,
  with nothing else between them, as older programs write Generations rules. Each side's
  digits are sorted and repeats dropped: `345/2/4` is `B2/S345/C4`, and `/2/3` is
  `B2/S/C3`.
- `count` is a decimal number of states from 2 to 256 (leading zeros allowed).
- `ws` is the whitespace of [rules.md](rules.md#grammar).

**Canonical form:** the Life-like rule's canonical form ([rules.md](rules.md#canonical-form)),
`/C`, and the count in decimal without leading zeros: `B2/S345/C4`, `B2/S/C3`,
`B2a/S23/C5`, `B2/S34H/C5`. Two Generations rules behave identically exactly when their
canonical forms are equal.

### Reasons

Every text that is no Generations rule has a **reason**, the same in every port, that of
the first problem found:

1. Whitespace at the two ends is skipped. A survival/birth/count text has only its count
   checked (step 4).
2. Otherwise the text after the last `/`, whitespace before it skipped, must be `C` or `c`
   followed by one or more ASCII digits and nothing else: `expected '/C' and the number of
   states at the end` (a text without a `/` included).
3. The text before that `/` must be a Life-like rule; if it isn't, the reason is the one
   [rules.md](rules.md#reasons) gives for it: `B9/S/C3` gives `expected '/' after the birth
   counts`.
4. The count: `a Generations rule has 2 to 256 states`.

**API.** Compiling raises (throws) an error whose message is `invalid Generations rule
'<text>': <reason> (spec/generations.md)`. `try_compile_generations_rule(text)` (Python)
and `GenerationsRule.TryCompile(text, out rule, out reason)` (.NET) give the rule or the
reason without raising.

## Parameters

```json
{
  "rule": "B2/S/C3",
  "width": 256,
  "height": 256,
  "init": "soup",
  "density": 0.35,
  "seed": 0,
  "boundary": "torus"
}
```

`init` ∈ `soup | blob | single | array`. `boundary`, `shift` and `axis` are those of
[lifelike.md](lifelike.md#parameters), and a vector's params leave out `shift` 0 and
`axis` `x`. Params carry the canonical rule.

## Initialization

As [lifelike.md](lifelike.md#initialization): `soup`, `blob` and `single` draw exactly as
there, every live cell state 1; no cell starts out dying.

## Frames

A frame ([render.md](render.md#frames)) is palette-index bytes: 0 for a dead cell, and
⌊255 · (C − s) / (C − 1)⌋ for state s ≥ 1, so a live cell is 255 and the dying states fade
toward the background. Through `fire` it shows the colors of Generations' state palette
([render.md](render.md#default-palettes)), which colors the states themselves the same way.

## Editing and patterns

- **Patterns** ([patterns.md](patterns.md)) of family `generations` hold states from 0
  to C − 1; 0 is both the transparent cell and the blank. A pattern stamps only into a
  world whose C is above every cell of it.
- Stamp modes (`copy`, `or`, and `xor` and `and` on cells of states 0 and 1), Clear,
  turning a region, Advance Selection and Advance Outside, and canceling an advance, are
  those of [patterns.md](patterns.md#editing-a-region). **Random fill** gives a region the
  life-like soup, each live cell state 1.
- **RLE**: the extended dialect ([patterns.md](patterns.md#rle-text-encoding-life-like-wireworld-cyclic)),
  states past 24 as two-letter tags. A header naming a Generations rule, in either
  spelling, makes the file extended, and the encoder writes the rule's canonical form. A
  world saves with its topology as the rule's [bounded-grid
  suffix](topology.md#the-bounded-grid-suffix) (`rule = B2/S345/C4:T64,48`), and a file
  with one opens as that world.

## The unbounded plane

A Generations rule is a [state rule](hashlife-multistate.md#state-rules): its S is C, its
canonical name is its canonical form, and its cell function is the table above. So
[multi-state HashLife](hashlife-multistate.md) runs every Generations rule, of any count,
and its name is one of the names a multi-state universe and its files accept, in either
spelling. A rule with B0 is refused there, its background being one that changes. The
two-state [HashLife](hashlife.md) refuses a Generations rule, saying that it is one and
that its dying states need the multi-state universe.

## Vector encoding

- `vectors/generations/` — grid runs, laid out as every grid family's
  ([`vectors/README.md`](../vectors/README.md)): state PNGs are 8-bit grayscale, pixel = the
  raw state.
- `vectors/generations-rules/` — each case's `params.json` has `family:
  "generations-rules"`, `tier: "bit-exact"`, `spec_version` and `cases`, a list of rule
  texts: `input`, then `canonical`, `states`, `life` (the Life-like rule's canonical form)
  and `table` (its 512 entries as in [rules.md](rules.md#vector-encoding)), or
  `error: true` and the `reason`.

Runners are strict: an unknown key or `spec_version` fails the case.

## Oracles (implementation tests)

- With C = 2, a run is the Life-like rule's run, cell for cell.
- A cell whose neighbors are all dying is never born; a cell in dying state s reaches 0
  after exactly C − s more generations, whatever its neighbors.
- Brian's Brain grows: a pair of live cells is a seed.
- A pattern run on the plane ([hashlife-multistate.md](hashlife-multistate.md)) and on a
  grid with dead edges agree cell for cell for as long as it stays inside the grid.
