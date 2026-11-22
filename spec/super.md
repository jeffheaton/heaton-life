# Super rules

Conformance tier: **bit-exact**. Vectors: [`vectors/lifelike-super/`](../vectors/lifelike-super/)
(grid runs), [`vectors/rules/`](../vectors/rules/) (`super`, `super-two-state`),
[`vectors/patterns/`](../vectors/patterns/), [`vectors/render/`](../vectors/render/),
[`vectors/formats/`](../vectors/formats/) and
[`vectors/hashlife-multistate/`](../vectors/hashlife-multistate/) (`*-super*`).

A **Super rule** is a Life-like rule ([rules.md](rules.md)) with 26 states. It extends a
[History rule](history.md): its states 0–6 are History's and behave exactly as they do
there, and states 7–25 add on cells that leave no trail, two more trails with envelopes of
their own, and labels: off cells that vanish, wait to be cleared, cycle, or appear when
something touches them. The on cells still evolve exactly as the base rule's live cells
do. It is the LifeSuper rule as LifeWiki describes it, for any base rule: `B3/S23Super`
is LifeSuper itself, and `B36/S23Super`, `B2/S34HSuper` or `MAP…Super` add the same states
to other rules (rules.md, "Variants").

## States

| State | Name | On | RLE tag |
|---|---|---|---|
| 0 | off | no | `.` (also `b`) |
| 1 | on | yes | `A` (also `o`) |
| 2 | envelope: off, once on | no | `B` |
| 3 | marked on | yes | `C` |
| 4 | marked off | no | `D` |
| 5 | start on | yes | `E` |
| 6 | boundary | no | `F` |
| 7 | marked on, no trail | yes | `G` |
| 8 | marked off, no trail | no | `H` |
| 9 | second trail: on | yes | `I` |
| 10 | second trail: envelope | no | `J` |
| 11 | third trail: on | yes | `K` |
| 12 | third trail: envelope | no | `L` |
| 13 | no trail 1 | yes | `M` |
| 14 | vanishing label | no | `N` |
| 15 | no trail 2 | yes | `O` |
| 16 | clearable label | no | `P` |
| 17 | no trail 3 | yes | `Q` |
| 18 | cycling label 1 | no | `R` |
| 19 | no trail 4 | yes | `S` |
| 20 | cycling label 2 | no | `T` |
| 21 | no trail 5 | yes | `U` |
| 22 | cycling label 3 | no | `V` |
| 23 | no trail 6 | yes | `W` |
| 24 | hidden label | no | `X` |
| 25 | no trail 7 | yes | `pA` |

A cell is **on** when its state is odd and **off** when it is even. The tags are the
extended dialect of RLE ([patterns.md](patterns.md)): state n is the n-th letter, and 25
the two-letter tag `pA`, so files shared as LifeSuper read as they were written.

Three groups recur below: the **no-trail states** 13, 15, 17, 19, 21, 23 and 25; the
**trail states** 9 and 11; and the **labels** 14, 16, 18, 20, 22 and 24.

## Evolution

A generation replaces every cell at once. A cell's **neighbors** are the rule's own:
Moore's eight, the hexagonal six, or von Neumann's four
([rules.md](rules.md#neighborhoods)). Its **parents** are the neighbors that are on.

1. A **boundary** cell (6) stays 6.
2. A cell with a boundary cell among its neighbors is off in the next generation. States
   7 and 8, the no-trail states and the labels become 0; the others become what they
   become on turning off or staying off (below): 1 → 2, 3 → 4, 5 → 4, 9 → 10, 11 → 12,
   and 0, 2, 4, 10 and 12 stay.
3. Any other cell is on in the next generation when the base rule's table, read at the
   neighborhood index of the block's on cells ([rules.md](rules.md#the-transition-table)),
   gives 1. A boundary cell is off, so it never counts toward a birth or a survival. Then:

| The cell | Next state |
|---|---|
| on, and on next | its own state |
| on, and off next | 1 → 2, 3 → 4, 5 → 4, 7 → 8, 9 → 10, 11 → 12, a no-trail state → 0 |
| off, and on next (a birth) | 4 → 3, 8 → 7, any other state → the newborn's state (below) |
| 14, staying off | 0 |
| 16, staying off | 14 when a neighbor is on or is 14, else 16 |
| 18, staying off | 22 when a neighbor is 22, else 18 |
| 20, staying off | 18 when a neighbor is 18, else 20 |
| 22, staying off | 20 when a neighbor is 20, else 22 |
| 24, staying off | 18 when a neighbor is on, 14 or 18, else 24 |
| any other state, staying off | its own state |

So the on cells run the base rule exactly, away from boundary cells, as a two-state world
runs it. A cell of state 1, 9 or 11 leaves its own envelope (2, 10 or 12) where it dies,
and a no-trail cell leaves nothing. Marks survive birth and death, in History's pair 3
and 4 and in the no-trail pair 7 and 8. The vanishing label lasts one generation; the
clearable label turns vanishing when something on, or vanishing, touches it; the hidden
label turns into cycling label 1 when touched by something on, a vanishing label or
cycling label 1; and the three cycling labels chase each other, 22 overrunning 18, 18
overrunning 20, and 20 overrunning 22.

### The newborn's state

A newborn whose state is not fixed by the table above takes it from its parents, by the
first of these that applies:

1. Every parent is one no-trail state s, or 3, and at least one parent is s: s.
2. Every parent is one trail state t, or 7, and at least one parent is t: t.
3. There is a parent, and every parent is 7 or a no-trail state: 13.
4. Otherwise: 1. A birth with no parents (a base rule with B0) gives 1.

So parents that agree pass their state on, the marked on cells going along with them (3
with a no-trail state, 7 with a trail); a mixture of no-trail cells, with or without 7,
gives 13; and any other mixture gives 1. A pattern of states 0–6 alone evolves exactly as
under the History rule: its parents are 1, 3 and 5, so each newborn is 1, or 3 where the
cell was 4.

A base rule with B0 runs as written on a grid: on the first generation every off cell
whose block is all off (and not beside a boundary) is born, as state 1.

### Readings

LifeWiki's LifeSuper page names the states and what each is for; its rule table gives
the transitions for Life, where a birth has three parents. Three points are readings this
page takes, beyond what those state:

1. The newborn's rules are written for any number of parents. For three parents they are
   the table's; for other counts, which other base rules give, they are this page's.
2. A cell beside a boundary cell is never born, as for History rules
   ([history.md](history.md#evolution)), so that a Super world of states 0–6 runs as the
   History world does.
3. The labels and the boundary look at the rule's own neighbors, as History's boundary
   does.

## Two, seven and twenty-six states

- **A two-state pattern is a Super pattern** as it stands, and so is a **History
  pattern**: states 0–6 mean the same in both. Life parts and LifeHistory parts paste into
  a Super world unchanged.
- **A Super pattern under a two-state rule** keeps its on cells: each odd state becomes 1
  and each even state 0. **Under a History rule** states 0–6 stay, and each of 7–25
  becomes 1 or 0 by its parity. Both are `convert_cells` (.NET `ConvertCells`;
  [history.md](history.md#two-states-and-seven)): a state the rule has stays, and any other
  becomes its parity.
- **The same base.** `B3/S23`, `B3/S23History` and `B3/S23Super` share a base
  ([rules.md](rules.md#variants)), so a host asking whether a pattern belongs in a world
  compares bases: a Life pattern is native to a `B3/S23Super` world.

## On a grid

The [Life-like](lifelike.md) family runs a Super rule on every topology
([topology.md](topology.md)), as it runs a History rule: the halo copies the states, the
blank past a dead edge is 0, and the step reads them as above.

- **Initialization.** `soup`, `blob` and `single` make the base rule's cells, states 0
  and 1. `array`, `set_state` and `set_cell` take any state 0–25; a larger one is an
  error.
- **Frames** ([render.md](render.md)) are the states themselves, 0–25, for a palette of
  a color per state. Super's default palette and zoom order are render.md's
  ([State palettes](render.md#state-palettes)): History's colors for states 0–6, and an
  order that shows the live and marked cells over trails and labels.
- **Editing** ([patterns.md](patterns.md#editing-a-region)): stamps paste states (`copy`
  and `or`; `xor` and `and` take 0 and 1 only); transforms move them; `clear_rect` and the
  blank of Advance Selection and Advance Outside are 0, and an advance cancels as on every
  grid. **Random fill** is the base rule's soup, its live cells state 1 and its dead ones
  0.

## Files

- **RLE** ([patterns.md](patterns.md)): a header naming a Super rule (`B3/S23Super`, or
  `LifeSuper`) makes the file extended, so `B` is state 2 and the tags are the states;
  lowercase `b` and `o` still read as 0 and 1. The canonical encoder writes the rule's
  canonical name (`LifeSuper` is written `B3/S23Super`) and chooses its tags by the
  cells, state 25 as `pA`. `#CXRLE` places a Super pattern, and a
  [bounded-grid suffix](topology.md#the-bounded-grid-suffix) follows the rule
  (`rule = B3/S23Super:T30,20`).
- **Macrocell**: a Super pattern is a multi-state file
  ([hashlife-multistate.md](hashlife-multistate.md#pattern-io)), its `#R` the rule's
  canonical name.
- The two-state formats (plaintext, Life 1.05 and 1.06, images) hold states 0 and 1; a
  Super rule in a Life 1.05 or 1.06 `#R` is read as written.

## On the unbounded plane

- The two-state [HashLife](hashlife.md) universe refuses a Super rule, with the reason
  that it has 26 states.
- The [multi-state universe](hashlife-multistate.md) runs a Super rule as a state rule of
  26 states, named by the rule's canonical name. Its cell function is the evolution above.
- A Super rule whose base has B0 can't run there: its first generation would light the
  whole plane, and the plane's background must stay 0. The universe refuses it with the
  reason that the background would change. A grid runs it as written.
- Random fill there is the grid's: states 1 and 0, the draws of the two-state universe's
  `fill_random`.

## Vector encoding

- `vectors/lifelike-super/`: grid runs as [lifelike.md](lifelike.md) encodes them, with a
  Super rule in `params`. Each checkpoint is a grayscale PNG whose pixel is the state
  itself (0–25); `init: "array"` starts from the first checkpoint's cells.
- `vectors/rules/`: `super` (with `variants: true`) and `super-two-state` (without), as
  [rules.md](rules.md#vector-encoding) says.
- `vectors/patterns/`: RLE cases (`rle-super-*`) read and written canonically, and
  stamps, random fill and Advance Selection and Outside in Super worlds.
- `vectors/render/frame-lifelike-super`: a Super grid's frame, the states themselves.
- `vectors/formats/`: Super files read into grids and measured, and refused by the
  two-state universe.
- `vectors/hashlife-multistate/`: Super rules on the plane. The `grid` cases run a Super
  grid beside the universe, cell for cell, inside walls of boundary cells; the others are
  as [hashlife-multistate.md](hashlife-multistate.md#vector-encoding) says.

Runners are strict: an unknown key or `spec_version` fails the case.
