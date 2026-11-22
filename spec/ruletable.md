# Rule tables

Conformance tier: **bit-exact**. Vectors: [`vectors/ruletable/`](../vectors/ruletable/) (grid
runs), [`vectors/ruletable-files/`](../vectors/ruletable-files/) (files read and compiled)
and [`vectors/hashlife-multistate/`](../vectors/hashlife-multistate/) (`*-ruletable-*`).

The **rule-table family** runs any rule a [rule file](rule-files.md) defines: up to 256
states, the von Neumann, Moore, hexagonal or one-dimensional neighborhood, given as a table
or a tree. Self-reproducing loops, ants and turmites, and many other automata of the
literature are rule files. The library carries a **starter set** of them, re-authored
from the original publications (below).

## State

A grid of states 0 to S − 1 (S the rule's `states`), one byte each, shape
`(height, width)`, row-major. State 0 is the blank.

## Evolution

Every cell's next state is its rule's function of its 3 × 3 block
([rule-files.md](rule-files.md#tree)): the canonical tree walked over the block's states,
read from the grid's [halo](topology.md#the-halo) of radius 1, whose cells past a dead
edge are 0. All cells change at once. Every [topology](topology.md#the-topologies) is
allowed; the default is `dead`.

A rule's function at an all-0 block need not be 0 on a grid: the first generation then
changes every blank cell there, as a B0 rule does.

## The rule

A world's rule is a rule file's rule (Python `RuleTable`, .NET `RuleTable`), or the name of
one in the starter set. `rule` in a world's params is the rule's name. Changing a world's
rule is not offered: a world is made with its rule.

## Parameters

```json
{ "rule": "Langtons-Loops", "width": 64, "height": 64, "init": "starter",
  "density": 0.35, "seed": 0, "boundary": "dead", "shift": 0, "axis": "x" }
```

`shift` and `axis` are the topology's ([lifelike.md](lifelike.md#parameters)).

## Initialization

- **starter**: the rule's starter pattern (below), its top-left cell at
  ((width − w) div 2, (height − h) div 2) for a pattern of w × h cells. A rule without a
  starter pattern, or a grid it doesn't fit, is an error.
- **blank**: every cell 0. No draws.
- **soup**: PCG32 seq 0, width × height draws row-major; a cell is 0 unless its draw is
  below ⌊density · 2³²⌋, and then it is 1 + (draw mod (S − 1)).
- **array**: given cells, each below S.

## Frames

A frame is the states themselves, 0 to S − 1, one byte a cell, for a palette of a color
per state. The default palette ([render.md](render.md#default-palettes)) is the rule
table's: the multi-state palette of its S with the rule file's `@COLORS` applied, so a
file that gives its colors is shown in them, on a grid and on the plane alike. The
default zoom order is the empty one. `@ICONS` are kept for a host to draw.

## Editing

As for the other grid families ([patterns.md](patterns.md#editing-a-region)):
`set_state` (any state below S), .NET's `SetCell`, `clear_rect` (to 0), stamps (`copy` and `or`;
`xor` and `and` take 0 and 1 only, as in every world of more states), transforms, and
Advance Selection and Advance Outside, whose blank is 0 and which can be canceled.

## Files

- **RLE** ([patterns.md](patterns.md)): a header whose rule is a rule table's name
  (`rule = Langtons-Loops`) is extended RLE, its states the letters (`A` is 1, and so on).
  The encoder writes the name as the rule gives it.
- **A rule appended to a pattern file.** A pattern carries a rule outside the starter set
  as the rule's file, appended after the pattern:
  - in **RLE**, text after the pattern's `!` that begins, at the start of a line, with
    `@RULE`;
  - in **Macrocell**, a line after the header that begins with `@RULE`, which ends the
    file's Macrocell lines (its node, leaf and `#` lines come before it, a timeline's
    `#FRAME` lines among them).

  Lines are those of [formats.md](formats.md#bytes-and-text) ("Lines"). In either, the rule
  file is the rest of the text from the start of that line to the text's end, a final line
  end included, its `\r\n` and `\r` line ends read as `\n`: so a rule has one text, its
  `text`, whichever file carries it and in either port. `embedded_rule(text)` (.NET
  `RuleTables.Embedded`) gives it, reading a text whose first line that isn't blank starts
  with `[M2]` as Macrocell and any other as RLE, or nothing when there is none; an appended
  text that is no rule file is an error. A reader of the
  [multi-state universe](hashlife-multistate.md#pattern-io) takes an appended rule whose
  name the header or `#R` names before it looks the name up. `append_rule(text, rule)`
  (.NET `RuleTables.Append`) writes the rule's file text after a pattern file's text, RLE
  or Macrocell. The canonical writers append nothing: a host appends the rule to a file
  that should carry it, such as an export of a world whose rule is outside the starter
  set.
- **Macrocell**: a rule-table pattern is a multi-state file
  ([hashlife-multistate.md](hashlife-multistate.md#pattern-io)), its `#R` the rule's name,
  and a rule outside the starter set travels appended after it, as above
  ([macrocell.md](macrocell.md#multi-state-files)).

## On the unbounded plane

A rule table is a [state rule](hashlife-multistate.md#state-rules): its name, its states,
and its function as the cell function, the tree walked over the block. The multi-state
universe runs it like any other, and refuses one whose function turns an all-0 block into
another state: the plane's background would change.

**Names, and no registry.** The starter set's names resolve wherever a state rule's name
does ([hashlife-multistate.md](hashlife-multistate.md#state-rules), "Names"). Any other
rule file is given as the object: the universes, the grid family and the readers all take
one, and a file carrying its own rule (appended to RLE) is read with it. There is no
process-wide registry to add rules to: what a name means never depends on what a program
loaded before, so the same file and the same calls give the same result everywhere.

## The starter set

Each rule is a rule file in the library, re-authored from the publication that defined
it (its source is in the file's description), with a **starter pattern**: the
publication's own where it gives one. The files are `python/src/heaton_life/ca/rules/<name>.rule` and
`<name>.rle`; the .NET assembly embeds the same files. `starter_rule(name)` and
`starter_pattern(name)` (.NET `RuleTables.Starter`, `RuleTables.StarterPattern`) give them,
names matched ignoring ASCII case.

| Name | States | Neighborhood, symmetries | Source | What the vectors pin |
|---|---|---|---|---|
| `Langtons-Loops` | 8 | von Neumann, `rotate4` | C. G. Langton, *Self-reproduction in cellular automata*, Physica D 10 (1984) 135–144: Table I, its 219 transitions as printed; the loop of Fig. 6 | generation 151 equals Fig. 9: the parent and an exact copy of the loop of generation 0, eleven cells to its right |
| `Byl-Loop` | 6 | von Neumann, `rotate4` | J. Byl, *Self-reproduction in small cellular automata*, Physica D 34 (1989) 295–299: Table II and its `C----` defaults, with one transition Fig. 3 requires (below); the loop of Fig. 3, mirrored (below) | generations 0 to 27 equal Fig. 3's, mirrored left to right; at 25 an exact copy of the loop of generation 0 stands beside its parent |
| `Evoloop` | 9 | von Neumann, `rotate4` | H. Sayama, *Self-protection and diversity in self-replicating cellular automata*, Artificial Life 10 (2004) 83–98: Appendix A.1, Table 2 and the four steps that complete it; Langton's loop, whose structure the evoloop keeps | the loop reproduces: its first offspring separates at generation 128, and the run to 400 |
| `Langtons-Ant` | 10 | von Neumann, `none` | C. G. Langton, *Studying artificial life with cellular automata*, Physica D 22 (1986) 120–149: on a white (0) cell the ant turns right, on a black (1) one left; it flips the cell and steps forward. The starter pattern: one ant, facing north (the library's choice), on an all-white plane | the run to 11,000 steps: from step 9,976 on, every 104 steps carry the ant two cells along a diagonal (the published highway, after step 9,977 counted from 1) |
| `Ant-LLRR` | 20 | von Neumann, `none` | the many-color ants of Turk and Propp (D. Gale, J. Propp, S. Sutherland and S. Troubetzkoy, *Further travels with my ant*, Mathematical Intelligencer 17:3 (1995)): on color k the ant turns as the name's k-th letter says, sets the cell to color k + 1 (mod the colors) and steps forward | the run to 4,000 steps, where its pattern is mirror-symmetric (it grows symmetrically) |
| `Ant-RLR` | 15 | von Neumann, `none` | as above | its run, which grows chaotically |

**The ants.** A cell's state is its color c (0 to K − 1, for K colors), or, where the ant
is, K + 4c + d with d its heading (0 north, 1 east, 2 south, 3 west). Each generation the
ant's cell takes its next color, and the ant appears on the neighbor its new heading points
to, facing that way. Two ants that would land on one cell: the one coming from the north
wins, then east, south, west; the others are gone. The tables are generated from these
definitions by `python/tools/gen_rule_tables.py`.

**Byl's loop.** Table II as printed has 56 entries, the 6 defaults among them; the paper's
text counts 57. Fig. 3 shows every generation from 0 to 27, and with the table as printed
the run matches it to generation 22, then at 23 one cell differs: the transition
`31523 → 1` (in Table II's reading of CTRBL) is the one Fig. 3 needs, and with it every
generation of Fig. 3 matches. The file adds it, marked. Fig. 3 is drawn as the mirror image
(left and right swapped) of what Table II gives under the paper's own reading of the
neighbors, so the starter pattern is Fig. 3's loop mirrored, and its run is Fig. 3's,
mirrored.

**Not yet in the set.** Codd's 8-state automaton (E. F. Codd, *Cellular Automata*,
Academic Press, 1968): its transitions could not be taken from the original publication
here, so the set leaves it out rather than copy a later reconstruction.

## Vector encoding

- `vectors/ruletable/`: grid runs. `params.json` holds the params above (`init` `array`
  starts from the first checkpoint's cells) and, for a rule outside the starter set,
  `rule_text`: the rule file's text. Each checkpoint is a grayscale PNG whose pixel is the
  state itself.
- `vectors/ruletable-files/`: files read and compiled ([rule-files.md](rule-files.md#vector-encoding)).
- `vectors/hashlife-multistate/`: rule tables on the plane, the `grid` cases running the
  rule-table grid beside the universe cell for cell (dead edges).

Runners are strict: an unknown key or `spec_version` fails the case.

## Oracles (implementation tests)

- A table and its compiled tree, written as a `@TREE` file and read back, give the same
  canonical tree.
- Tables that restate other families (Wireworld, Life with `permute`, a hexagonal Life-like
  rule, an elementary rule run row by row) run as those families do.
- Every variant order the symmetries list, on random blocks, against a direct reading of
  the table (first match, binding, unchanged when nothing matches).
- The ants against a direct simulation of the ant's definition.
