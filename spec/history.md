# History rules

Conformance tier: **bit-exact**. Vectors: [`vectors/lifelike-history/`](../vectors/lifelike-history/)
(grid runs), [`vectors/rules/`](../vectors/rules/) (`history`, `history-two-state`),
[`vectors/patterns/`](../vectors/patterns/) (`*-history*`) and
[`vectors/hashlife-multistate/`](../vectors/hashlife-multistate/) (`*-history*`).

A **History rule** is a Life-like rule ([rules.md](rules.md)) with seven states in place of
two. Its on cells evolve exactly as the base rule's live cells do, and the other states
record where on cells have been (the **envelope**) and mark cells for a reader: which
cells a pattern started with, which are of interest, and walls that keep patterns apart.
It is the LifeHistory rule as LifeWiki describes it, for any base rule: `B3/S23History` is
LifeHistory itself, and `B36/S23History`, `B2/S34HHistory` or `MAP…History` add the same
states to other rules (rules.md, "Variants").

## States

| State | Name | On | RLE letter |
|---|---|---|---|
| 0 | off | no | `.` (also `b`) |
| 1 | on | yes | `A` (also `o`) |
| 2 | envelope: off, once on | no | `B` |
| 3 | marked on | yes | `C` |
| 4 | marked off | no | `D` |
| 5 | start on | yes | `E` |
| 6 | boundary | no | `F` |

A cell is **on** when its state is odd (1, 3, 5) and **off** when it is even (0, 2, 4, 6).
The letters are the extended dialect of RLE ([patterns.md](patterns.md)), state n the
n-th letter, so files shared as LifeHistory read as they were written.

## Evolution

A generation replaces every cell at once:

- A **boundary** cell (6) stays 6.
- Any other cell is on in the next generation when the base rule's table, read at the
  neighborhood index of the block's on cells ([rules.md](rules.md#the-transition-table)),
  gives 1 — **unless** a boundary cell is among its neighbors: then it is off. The
  neighbors are the rule's own: Moore's eight, the hexagonal six, or von Neumann's four
  ([rules.md](rules.md#neighborhoods)). A boundary cell is off, so it never counts toward
  a birth or a survival.
- Its next state follows from its state and whether it is on next:

| State | On next | Off next |
|---|---|---|
| 0 off | 1 | 0 |
| 1 on | 1 | 2 |
| 2 envelope | 1 | 2 |
| 3 marked on | 3 | 4 |
| 4 marked off | 3 | 4 |
| 5 start on | 5 | 4 |
| 6 boundary | 6 | 6 |

So, away from boundary cells, the on cells run the base rule exactly as a two-state world
runs it. The envelope is every cell that has been on and is off now. A marked cell keeps
its mark through birth and death. A start-on cell is marked off once it dies and is never
start-on again. A boundary cell never changes, and every cell beside it stays off: two
patterns on either side of a wall of boundary cells never meet.

A base rule with B0 runs as written on a grid: on the first generation every off cell
whose block is all off (and not beside a boundary) is born.

## Two states and seven

- **A two-state pattern is a History pattern** as it stands: its 0 and 1 are off and on.
  Life parts paste into a History world unchanged.
- **A History pattern under a two-state rule** keeps its on cells: each odd state becomes
  1 and each even state 0.
- **Converting a world's cells to a rule** (`convert_cells`, .NET `ConvertCells`): a cell
  whose state the rule has keeps it, and any other becomes 1 or 0 by its parity. So
  changing a world's rule from X to XHistory changes no cell, and from XHistory to X maps
  odd to 1 and even to 0.
- **The same base.** A rule's `base` is its two-state rule ([rules.md](rules.md#variants)).
  Two rules with the same base run a two-state pattern identically, so a host asking
  whether a pattern belongs in a world compares their bases: a Life pattern is native to
  a `B3/S23History` world.

## On a grid

The [Life-like](lifelike.md) family runs a History rule on every topology
([topology.md](topology.md)). The halo copies the states, and the blank past a dead edge
is 0. The step reads on and off from them as above. The two-state rules run as before.

- **Initialization.** `soup`, `blob` and `single` make the same cells they make for the
  base rule, states 0 and 1. `array`, `set_state` and `set_cell` take any state 0–6; a
  larger one is an error.
- **Frames** ([render.md](render.md)) are the states themselves, 0–6, for a palette of a
  color per state; the host's palette, until multi-state rendering defines History's.
- **Editing** ([patterns.md](patterns.md#editing-a-region)): stamps paste states (`copy`
  and `or`; `xor` and `and` take 0 and 1 only, as in every world of more states);
  transforms move them; `clear_rect` and the blank of Advance Selection and Advance
  Outside are 0. **Random fill** is the base rule's soup, its live cells state 1 and its
  dead ones 0: the draws of the two-state rule.

## Files

- **RLE** ([patterns.md](patterns.md)): a header naming a History rule makes the file
  extended, so `B` is state 2 and the table's letters are the states; lowercase `b` and
  `o` still read as 0 and 1. The canonical encoder writes the rule's canonical name
  (`LifeHistory` is written `B3/S23History`) and chooses its letters by the cells, as for
  every rule. `#CXRLE` places a History pattern, and a
  [bounded-grid suffix](topology.md#the-bounded-grid-suffix) follows the rule
  (`rule = B3/S23History:T30,20`).
- **Macrocell**: a History pattern is a multi-state file
  ([hashlife-multistate.md](hashlife-multistate.md#pattern-io)), its `#R` the rule's
  canonical name.
- The two-state formats (plaintext, Life 1.05 and 1.06, images) hold states 0 and 1; a
  History rule in a Life 1.05 or 1.06 `#R` is read as written.

## On the unbounded plane

- The two-state [HashLife](hashlife.md) universe refuses a History rule, with the reason
  that it has seven states.
- The [multi-state universe](hashlife-multistate.md) runs a History rule as a state rule
  of seven states, named by the rule's canonical name. Its cell function is the evolution
  above.
- A History rule whose base has B0 can't run there: its first generation would light the
  whole plane, and the plane's background must stay 0. The universe refuses it with the
  reason that the background would change. A grid runs it as written.
- Random fill there is the grid's: states 1 and 0, the draws of the two-state universe's
  `fill_random`.

## Later: Super

A `Super` variant of 26 states, whose states 0–6 behave as these do, is planned on the
same model: one more variant word with its own table of states and its own cell function.

## Vector encoding

- `vectors/lifelike-history/`: grid runs as [lifelike.md](lifelike.md) encodes them, with
  a History rule in `params`. Each checkpoint is a grayscale PNG whose pixel is the state
  itself (0–6); `init: "array"` starts from the first checkpoint's cells.
- `vectors/rules/`: `history` (with `variants: true`) and `history-two-state` (without),
  as [rules.md](rules.md#vector-encoding) says.
- `vectors/patterns/`: RLE cases (`rle-history-*`) read and written canonically, stamps
  and random fill in History worlds.
- `vectors/hashlife-multistate/`: History rules on the plane. The `grid` cases run a
  History grid beside the universe, cell for cell; the others are as
  [hashlife-multistate.md](hashlife-multistate.md#vector-encoding) says.

Runners are strict: an unknown key or `spec_version` fails the case.
