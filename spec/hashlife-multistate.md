# Multi-state HashLife — rules of many states on an unbounded plane

Conformance tier: **bit-exact**. Vectors:
[`vectors/hashlife-multistate/`](../vectors/hashlife-multistate/).

The `hashlife-multistate` family runs rules whose cells have more than two states on an
unbounded plane, with the HashLife algorithm of [hashlife.md](hashlife.md): a hash-consed
quadtree whose nodes memoize their own future. Two-state Life-like rules keep their own
engine, [hashlife.md](hashlife.md); this page is its counterpart for every rule whose next
state is a function of the 3 × 3 block of states around a cell: Wireworld, every
Generations rule, and History and Super rules so far, and rule tables as their page adds
them
(Larger than Life's neighborhoods reach past the 3 × 3 block, and it stays on bounded
grids).

Everything this page does not change is as [hashlife.md](hashlife.md) says: tree
coordinates and depth, the evolution's recursion and sub-steps, cancellation, the memory
budget, snapshots, views and their arithmetic, and the editing box.

## State

- **Cells.** Every point (x, y) of the integer plane holds a state from 0 to S − 1, where S
  is the rule's number of states. State 0 is the background: all but finitely many cells
  are 0. x grows to the right and y grows downward, as in RLE.
- **Population.** The number of cells whose state is not 0. The bounding box and the
  queries of [hashlife.md](hashlife.md#observables) count those cells, whatever their
  state.
- **Generation.** A non-negative integer.
- **Rule.** A state rule (next section), named by its canonical name.

## State rules

A **state rule** is everything the engine knows about a rule:

- `states`: S, from 2 to 256.
- `canonical`: its canonical name, the text a file names it by: printable ASCII with no
  whitespace and no comma, so that a Macrocell `#R` line and an RLE header carry it.
- The **cell function** f, which gives a cell's next state from the 3 × 3 block centered on
  it: f(NW, N, NE, W, C, E, SW, S, SE), every argument and the result a state from 0 to
  S − 1, laid out as in [rules.md](rules.md#the-transition-table):

```
NW  N  NE
 W  C   E
SW  S  SE
```

A rule must give f(0, 0, 0, 0, 0, 0, 0, 0, 0) = 0, or it is refused: a background that
changes in one generation can't be run on the infinite plane. A family plugs in by
providing these three things, so every rule of the 3 × 3 block runs here, whatever its
neighborhood within the block (Moore, von Neumann, hexagonal) and however it computes f.

**Names.** A rule is given by its name, with any whitespace of [rules.md](rules.md#grammar)
at the two ends; the name is matched ignoring ASCII case, and the canonical spelling is the
family's. Any other text is an error. The names so far:

| Name | Rule | States |
|---|---|---|
| `WireWorld` | Wireworld ([wireworld.md](wireworld.md)): 0 empty, 1 electron head, 2 electron tail, 3 conductor | 4 |
| `Langtons-Loops`, `Byl-Loop`, `Evoloop`, `Langtons-Ant`, `Ant-LLRR`, `Ant-RLR` | the [rule-table](ruletable.md) starter set: each rule's function is its canonical tree ([rule-files.md](rule-files.md)) | 8, 6, 9, 10, 20, 15 |
| a [History rule](history.md), `B3/S23History` or `LifeHistory`, any rule of [rules.md](rules.md) with the `History` variant | its cell function is history.md's evolution; canonical name and spellings as rules.md gives them (`LifeHistory` is `B3/S23History`). A base rule with B0 is refused: its background would change | 7 |
| a [Super rule](super.md), `B3/S23Super` or `LifeSuper`, any rule of [rules.md](rules.md) with the `Super` variant | its cell function is super.md's evolution; canonical name and spellings as rules.md gives them (`LifeSuper` is `B3/S23Super`). A base rule with B0 is refused: its background would change | 26 |
| a Generations rule, `B…/S…/C…` or survival/birth/count | Generations ([generations.md](generations.md#rules)): 0 dead, 1 alive, 2 … C − 1 dying; canonical name its canonical form. A rule with B0 is refused: its background would change | C |

A text is first matched against the fixed names, then read as a History rule, then as a
Super rule, then as a Generations rule in either of its spellings (`345/2/4` names
`B2/S345/C4`).

A [Larger than Life](ltl.md) rule names no state rule: it is refused with the reason that it
runs on bounded grids only.

**Reasons.** A text that names no rule the universe runs has a **reason**, the same in
every port, the first of these that applies:

1. A History or Super rule whose base has B0, or a Generations rule with B0: `<rule> has
   B0: its first generation would turn the whole plane on, and the unbounded universe's
   background must stay 0; a grid runs it`, `<rule>` the rule's canonical name.
2. A Larger than Life rule: `<rule> is a Larger than Life rule: it runs on a bounded grid,
   never on the unbounded plane`, `<rule>` its canonical form ([ltl.md](ltl.md#rules)).
3. Any other text: `'<text>' is not a state rule (known: WireWorld, Langtons-Loops,
   Byl-Loop, Evoloop, Langtons-Ant, Ant-LLRR, Ant-RLR, History rules such as
   B3/S23History, Super rules such as B3/S23Super, and Generations rules such as
   B2/S345/C4)`, `<text>` the text as given.

So a name gives only rules the engine runs, rules that the check of a rule given as an
object (below) passes: `B03/S23/C3` names no rule, for the first reason, as
`B03/S23History` names none.

**API.** `state_rule(text)` (.NET `StateRules.Compile(text)`) gives the rule, or raises
(throws) an error whose message is the reason followed by the page that says why, in
parentheses: `(spec/history.md "On the unbounded plane")`, `(spec/super.md "On the
unbounded plane")` or `(spec/generations.md "The unbounded plane")` for the first reason,
`(spec/ltl.md)` for the second, and `(spec/hashlife-multistate.md "Names")` for the third.
`try_state_rule(text)` gives the rule and no reason, or no rule and the reason, without
raising; .NET's `StateRules.TryCompile(text, out rule, out reason)` answers true or false
likewise, and reads null as empty text. A rule given as an object is checked as the
universe checks it (`check_state_rule`, .NET `StateRules.Check`): 2 to 256 states, a
canonical name a file can carry, and f of the all-0 block 0.

A port may also take a state rule as an object (Python a `StateRule`, .NET a `StateRule`),
for a family's own rules; files still name a rule by its canonical name (Pattern I/O,
below). Any [rule file](rule-files.md)'s rule is one (`RuleTable`); there is no registry
of names beyond the table above ([ruletable.md](ruletable.md#on-the-unbounded-plane)).

**Changing the rule.** The cells stay and every cached result goes. A rule with fewer
states than the largest state present is an error that changes nothing.

## Quadtree

As [hashlife.md](hashlife.md#quadtree), except for the leaves:

- A level-k node is a 2^k × 2^k square of cells, k ≥ 1. A level-1 node — a **leaf** — is
  four states in the order NW, NE, SW, SE. A level-k node with k ≥ 2 has four level-(k−1)
  children in the same order.
- The **empty node** of each level is all 0.
- Tree coordinates: cell (x, y) is tree position (x, y − 1), and a level-k root covers
  tree positions [−2^(k−1), 2^(k−1))². A level-1 root covers the cells x ∈ {−1, 0},
  y ∈ {0, 1}.
- Depth: a tree is at most level 512.

## Evolution

`step(n)` advances exactly n generations, for any integer n with 0 ≤ n < 2^510: the cell
function applied n times, synchronously, over the whole plane. The answer is unique, so any
correct algorithm conforms. The reference algorithm is that of
[hashlife.md](hashlife.md#evolution), with one base case:

- **The base case.** A level-2 node's `result_0` is its center 2 × 2 one generation later:
  each of the four center cells becomes f of its 3 × 3 block. No table can hold every
  block of up to 256 states, so the result is computed from the cell function and cached
  per node; the cell function runs once for each distinct 4 × 4 square the evolution
  meets, until a collection drops the square.
- Every other result follows the full-speed and fixed-step recursion of
  [hashlife.md](hashlife.md#evolution), from level 3 up.
- **Sub-steps.** For each set bit j of n, expand the root until its level k ≥ j + 3 and
  every non-zero cell lies in the centered square of side 2^(k−2), then replace the root by
  `result_j(root)`.

The deepest step, [cancellation](hashlife.md#cancellation), and the
[memory budget](hashlife.md#memory) are as hashlife.md says: `step(n)` with n ≥ 2^510 is
an error before anything changes; a sub-step whose root would pass level 512 is an error
at that sub-step's boundary; `cancel()` stops a step at a completed sub-step; a sub-step
that cannot fit is collected, retried, and split down to single generations, and
`HashLifeMemoryError` (.NET `HashLifeMemoryException`) is raised when one generation can't
fit. The budget changes speed, never results.

## Observables

- `generation`, `population`, `bounding_box()`, `population_in`, and `bounding_box_in` as
  [hashlife.md](hashlife.md#observables) defines them, counting and bounding the non-zero
  cells.
- `live_population` and `live_population_in(x0, y0, x1, y1)` (.NET `LivePopulation` and
  `LivePopulationIn`) count the **live** cells, of the whole plane and of an inclusive
  rectangle (any coordinates): the cells whose state the rule calls live. Under a
  [History](history.md) or [Super](super.md) rule those are the on cells, the odd states,
  so an envelope, a mark that is off, a boundary cell or a label isn't one; under every
  other rule (a Generations rule, Wireworld, a rule table, a rule given as an object) every
  non-zero state is live, and the two counts are `population` and `population_in`. So the
  plane counts as alive what a grid of its rule's family shows alive: a Life-like grid's
  on cells, and every other grid's non-zero cells, a dying cell and a wire among them.
- `get_cell(x, y)` gives the cell's state; `get_rect(x0, y0, x1, y1)` the states of an
  inclusive rectangle, a (y1 − y0 + 1) × (x1 − x0 + 1) array, row-major.
- The canonical Macrocell text ([macrocell.md](macrocell.md#multi-state-files)) pins the
  whole state in one string.

## Editing

The [editing box](hashlife.md#editing) is the same, and so is the rule that an editing
call checks every cell it would touch and, if one lies outside the box or the call is
refused, changes nothing.

- `set_cell(x, y, state)`: 0 ≤ state < S.
- `set_rect(x, y, cells, mode)`: `cells` is h × w states, each below S, landing with its
  top-left cell at (x, y). The modes are the stamp modes of
  [patterns.md](patterns.md#extract-and-stamp): `copy` writes every cell; `or` writes the
  non-zero cells, 0 being transparent; `xor` and `and` are two-state modes, which need
  every cell of `cells`, and every cell of the rectangle it lands on, to be 0 or 1, and are
  otherwise an error.
- `clear_rect`, `clear_outside` and `clear()`: the cells become 0.
- `rotate_rect`, `flip_rect`, `advance_selection`, `advance_outside` and `set_generation`
  as [hashlife.md](hashlife.md#editing) defines them, the cells carrying their states and
  the blank being 0.

Random fill is a Life-like tool ([patterns.md](patterns.md#editing-a-region)): the
universe of a [History](history.md), [Super](super.md) or
[Generations](generations.md) rule has it, `fill_random(x0, y0, x1, y1, density, seed)`
as [hashlife.md](hashlife.md#editing) defines it, its live cells state 1 and its dead
ones 0. Under any other rule it is an error.

## Snapshots

As [hashlife.md](hashlife.md#snapshots): `snapshot()`, `restore(snapshot)`, `release()`,
and `measure_snapshots(snapshots)`, in the same snapshot type as the two-state universe
(Python `Snapshot`, .NET `HashLifeSnapshot`), which a universe of either kind refuses from
the other. A snapshot holds cells, not results, so it survives a rule change; restoring one
that holds a state the current rule lacks is an error that changes nothing.

The **nodes of a state** are the distinct non-empty nodes of its minimal tree, the node
lines of its canonical Macrocell text ([macrocell.md](macrocell.md#multi-state-files)),
leaves included; the empty universe has none. `measure_snapshots` counts them as
[hashlife.md](hashlife.md#what-snapshots-hold) says. `estimated_bytes` is each port's
estimate of those nodes in its store: 145 bytes a node in Python, 40 in .NET.

## Converting between the engines

A Life-like world moves between the two engines, and between History and Super rules,
without its cells becoming a grid:

- `HashLife.to_multistate(rule)` (.NET `HashLife.ToMultiState(rule)`): a new multi-state
  universe of `rule`, a [History](history.md) or [Super](super.md) rule, its cells the
  two-state universe's live cells as state 1.
- `to_two_state(rule)` (.NET `ToTwoState(rule)`) on a universe of a History or Super rule:
  a new two-state [HashLife](hashlife.md) universe of `rule`, a rule of rules.md without a
  variant, whose live cells are the on cells, the odd states; every even state is a dead
  cell.
- `to_multistate(rule)` (.NET `ToMultiState(rule)`) on a universe of a History or Super
  rule: a new multi-state universe of another History or Super rule, each state the rule
  has kept and each other state turned into its parity, as `convert_cells` turns a grid's
  ([history.md](history.md#two-states-and-seven)): a Super world under a History rule keeps
  its states 0–6.

The new universe has the old one's generation, its cells where they were, the old one's
memory budget unless another is given (`max_memory_mb`, .NET `maxMemoryMb`), no snapshots
(they belong to the universe that took them), and the default zoom order. The old universe
is unchanged. The conversion runs on the tree, each distinct node once, so a world converts
in the time and memory its tree takes, however far its cells spread; the vectors pin the
result, not the way.

Refused, with nothing made: a rule here or there that is not a History, Super or (for the
two-state side) two-state Life-like rule, since only a Life-like world's cells have a
meaning under the other rule; a two-state universe whose background is alive at its
generation (a rule with B0, [hashlife.md](hashlife.md#rules-with-b0)), since the cells it
holds are those that differ from a live plane and a multi-state universe's background is 0;
and a two-state rule whose background would be alive at the generation, for the same
reason.

## View and render

Views and every function on them — `pan`, `zoom_at`, `cell_at`, `center_cell`,
`centered`, `fit`, `resized` and `frame_map` — are those of
[hashlife.md](hashlife.md#view-and-render), shared by both kinds of universe. A frame of
size (width, height) is a height × width array of bytes, row-major; its pixel values, by
mode:

- **`state`** (the default). At `mag ≥ 0`, the cell's state, repeated over its square. At
  `mag < 0`, the block's **shown state**: of the non-zero states the block holds, the one
  that comes first in the universe's zoom order; 0 for a block of 0 cells.
- **`density`**. As in [hashlife.md](hashlife.md#view-and-render), counting non-zero
  cells: at `mag ≥ 0`, 255 for a non-zero cell and 0 for a 0 cell; at `mag < 0`,
  ⌈255 · p / 4^s⌉ for a block of p non-zero cells.

**The zoom order** is how a zoomed-out pixel chooses among the states it covers: a list of
distinct states from 1 to 255, set on the universe (`zoom_order`, .NET `ZoomOrder`). The
listed states come first, in the list's order, and every state not listed follows them in
increasing order, so the default, the empty list, shows the lowest non-zero state a block
holds. The frame gives states, and the host colors them:
[render.md](render.md#state-palettes) gives each rule's default palette and the zoom order
that goes with it (`default_zoom_order`), which the host sets. The zoom order changes
`state` frames and nothing else: snapshots and files don't carry it.

## Parameters

```json
{
  "rule": "WireWorld",
  "max_memory_mb": 500
}
```

## Pattern I/O

- **[Macrocell](macrocell.md#multi-state-files)** carries any state, of any size:
  `1 <nw> <ne> <sw> <se>` leaves of four states, and canonical writing.
  [Timelines](macrocell.md#timelines) read into snapshots and are written from them, as
  for two states.
- **RLE** carries patterns inside the editing box, as
  [patterns.md](patterns.md#rle-in-the-unbounded-universe) says for two states, with these
  differences. Reading: either dialect, its cells taken as the decoder gives them, each
  below S; a file whose rule carries a [bounded-grid suffix](topology.md#the-bounded-grid-suffix)
  is refused, as the two-state universe refuses it. Writing: the canonical encoding of
  [patterns.md](patterns.md#rle-text-encoding-life-like-wireworld-cyclic) for the bounding
  box's states (`b`/`o` when every state is 0 or 1, `.` and the extended tags otherwise,
  every state up to 255 included); a pattern outside the editing box is an error:
  Macrocell carries it.
- **Loading by content**: Macrocell and RLE, gzip-compressed or not, recognized as
  [formats.md](formats.md#detection) says, and [MCell](formats.md#mcell) files of the
  Generations family: the cell data's states as written, the top-left cell at (0, 0), and
  a file with a `#BOARD` line refused as the two-state universe refuses it. An MCell file
  of the Life family is two-state (that universe reads it) and one of Larger than Life
  runs on grids only, so both are refused by their rules. The other formats hold two
  states and are refused.
- **The rule.** A file names its rule by its canonical name (Macrocell's `#R`, RLE's
  header). The name is read as "Names" above says; a reader given a state rule object
  also takes that rule where the file's name matches its canonical name, ignoring ASCII
  case. A file that names no rule takes the rule the reader is given (default
  `WireWorld`); `read_snapshot` gives it the universe's rule. A state at or above the
  rule's S is an error. An RLE or Macrocell file may carry its rule: a [rule file appended
  after the pattern](ruletable.md#files) is taken when the header or `#R` names it and the
  reader's rule object doesn't, before the name is looked up.
- **Into a universe that exists**: `read_snapshot(source)` reads any file that loading by
  content reads into the universe's own store, as
  [formats.md](formats.md#reading-into-a-universe-that-exists) says: a snapshot of its
  cells and generation, its format, rule, metadata, and a timeline's frames; the
  universe's state, rule and earlier snapshots stay as they were.
- **Whether a file named its rule.** Loading by content (`read_multistate_universe`, .NET
  `MultiStateFiles.ReadUniverse`) also gives `rule_named` (.NET `RuleNamed`): true when the
  file names its rule (Macrocell's `#R`, RLE's header, an MCell file's rule line), false
  when it names none and the universe took the reader's rule.

### Measuring

`measure_multistate_pattern(source, rule)` (.NET `MultiStateFiles.Measure(source, rule)`)
gives what loading by content with the same `rule` would give, except the cells, found
without building a universe, as the `PatternExtent` of
[formats.md](formats.md#measuring):

- `format`: `macrocell`, `rle` or `mcell`.
- `width`, `height`, `x` and `y`: the bounding box of the file's non-zero cells where the
  universe would hold them, its `bounding_box()` once read; 0 × 0 at (0, 0) for a file
  without a non-zero cell. Macrocell's comes from its tree, as formats.md measures a
  two-state Macrocell file: each node line's non-zero cells have a box, a leaf's from its
  states (a two-state leaf's from its rows) and every other node's from its children's,
  and the root's box is placed as reading places the root. RLE's comes from its runs at
  its `#CXRLE Pos`, and MCell's from its cell data at (0, 0).
- `rule`: the canonical name of the rule the file names, found as reading finds it (the
  reader's rule where the name is its canonical name, a rule file appended to the file,
  else "Names" above); or none when the file names none.
- `generation` and `metadata`, as loading gives them.
- `two_state`: whether the cells are written in a two-state format: false for an RLE file
  in the extended dialect, whatever states it uses, for an MCell file of the Generations
  family, and for a Macrocell file with a `1 <nw> <ne> <sw> <se>` leaf; true otherwise.
- `bounded_grid`: none, since a file with a bounded grid is refused.

Measuring refuses what loading refuses before it builds a node: every format but these
three; a malformed file; an RLE file whose rule carries a bounded-grid suffix and an MCell
file with a board; a non-zero RLE or MCell cell outside the editing box; a rule that names
no state rule; and a state at or above the rule's S, the named rule's or, for a file that
names none, the reader's rule (default `WireWorld`). So a file that measures also loads,
within the universe's memory budget, under the same rule. A timeline's frame lines are
checked when it is read, as formats.md's measure leaves them.

## Vector encoding

Each case under `vectors/hashlife-multistate/` has a `params.json` with
`family: "hashlife-multistate"`, `tier: "bit-exact"`, `spec_version`, and a `kind`. A
state is pinned as [hashlife.md](hashlife.md#vector-encoding) pins one: `generation`,
`population`, and `bounding_box` as decimal strings (the box `null` when empty), and the
canonical Macrocell text in the file named by `state`, or past 4 KiB its `state_sha256`
and `state_lines`.

| kind | inputs | expected |
|---|---|---|
| `evolve` | `input` (an `.rle` or `.mc` file, loaded by content) | `checkpoints`: states in order; a runner steps by each difference |
| `grid` | `rule`, `grid` (an 8-bit grayscale PNG of the states as the rule's grid family stores them: × 85 for `WireWorld`, as the [wireworld](wireworld.md#vector-encoding) vectors do; the state itself for a [History](history.md#vector-encoding) or [Super](super.md#vector-encoding) rule, a [Generations](generations.md#vector-encoding) rule and a [rule table](ruletable.md#vector-encoding) of the starter set), `origin` (`[x, y]`, the cell the grid's top-left lands on) | `checkpoints`: each a state, and `cells` (a PNG like `grid`): the rule's grid family (Wireworld, Life-like under the History or Super rule, Generations under the case's rule, or the rule-table family) run from `grid` with dead edges to that generation, which the universe's rectangle under the grid must equal, every non-zero cell of the universe lying in it |
| `macrocell` | `input.mc`, and `rule` (the reader's rule) when given | the state, and `rle` (the RLE file) or `rle_error: true`; or `error: true` |
| `rle` | `input.rle`, and `rule` when given | the state and `rle`; or `error: true` |
| `edit` | `rule`, then `ops` in order on an empty universe: `set_cell` (`x`, `y`, `state`), `set_rect` (`x`, `y`, `mode`, `cells` as rows of state digits, `0`–`9` then `a`–`z` for 10–35), `clear_rect`, `clear_outside`, `rotate_rect` (with `expect`), `flip_rect`, `advance_selection`, `advance_outside` (`n`), `set_generation` (`n`), `step` (`n`), `clear`, `set_rule` (`rule`), `fill_random` (`x0`…`y1`, `density`, `seed`; under a History, Super or Generations rule), and the queries `get_rect` (`x0`…`y1`; `expect`: rows of state digits), `bounding_box_in` (`expect`), `live_population` (`expect`, a decimal string) and `live_population_in` (`x0`…`y1`; `expect`) — coordinates as in [hashlife.md](hashlife.md#vector-encoding) | the final state; an op with `error: true` must raise and change nothing |
| `render` | `input`, stepped to `generation`; each frame's `view`, `size`, `mode`, and `order` (the zoom order) | each frame's 8-bit grayscale PNG of pixel values (compared by decoded pixels) |
| `snapshots` | `rule`, then `ops`: every `edit` op, and `snapshot`, `release`, `restore` (`expect`: the state), `read` (`input`, `name`, `frames`; `expect`: `format`, `rule`, `metadata`, `step`) and `measure` (`names`; `expect`: `universe_nodes`, `added`, `nodes`) as in [hashlife.md](hashlife.md#vector-encoding) | the final state; an op with `error: true` must raise and change nothing |
| `timeline` | `input` (a pattern), `generations` (a frame at each, from the input's own), `metadata` | `timeline`: the file [macrocell.md](macrocell.md#timelines) writes; reading it back gives each frame's state (`frames`) again |
| `names` | `cases`, a list of texts, each an `input` | for each, the rule's `canonical` and `states`; or `error: true` and the `reason` (Names, "Reasons") |
| `convert` | `input` (a file, loaded by content: by the two-state reader when `from` is `two-state`, by the multi-state reader when it is `multistate`), `from`, and `rule` (the new universe's) | the new universe's state, pinned as its own engine pins one (a two-state universe's canonical Macrocell text is [hashlife.md](hashlife.md#vector-encoding)'s); or `error: true` |
| `carried-rule` | `inputs`: files carrying a rule after the pattern ([ruletable.md](ruletable.md#files)), each loaded by content | `rule_text`: the file holding the one text every input's rule has, the loaded universe's rule's `text` and `embedded_rule`'s |
| `measure` | `input` (a file, loaded by content), and `rule` (the reader's rule) when given | `extent`: `format`, `width`, `height`, `x`, `y` (decimal strings), `rule` (or null), `generation`, `metadata` and `two_state` (Measuring); and `rule_named`, what loading the file with the same rule gives, its universe's bounding box the extent's; or `error: true`, both measuring and loading refusing it |

Runners are strict: an unknown key, kind, op, or `spec_version` fails the case.

## Oracles (implementation tests)

- Against the grid: a Wireworld pattern run here and on a [wireworld](wireworld.md) grid
  with dead edges agree cell for cell at every generation, wherever the grid lies on the
  plane. (Wireworld's empty cells stay empty, so its patterns never grow past their
  conductors and the edge never matters.) A [Generations](generations.md) pattern agrees
  with its dead-edged grid for as long as it stays inside the grid.
- Wireworld's clock loop has the period of its perimeter, and a step of any size lands
  where that period says.
- The same run under budgets of 10 MiB and 500 MiB ends in identical cells.
- A rule given as an object runs exactly as the same rule given by name.
