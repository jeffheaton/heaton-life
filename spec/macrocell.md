# Macrocell — HashLife's native file format

Conformance tier: **bit-exact** (canonical writing). Vectors:
[`vectors/hashlife/`](../vectors/hashlife/) (`macrocell-*` and every `evolve-*` state);
metadata and timelines in [`vectors/formats/`](../vectors/formats/); multi-state files in
[`vectors/hashlife-multistate/`](../vectors/hashlife-multistate/).

Macrocell (`.mc`, often gzip-compressed as `.mc.gz`) is the Life community's format for
HashLife patterns. It lists a pattern's distinct [quadtree](hashlife.md#quadtree) nodes,
children before parents, so a regular pattern of trillions of cells fits in a few lines.
Where RLE needs one token per run of cells, Macrocell needs one line per distinct node —
the only practical format for patterns like the Caterpillar (12 million cells, 337k lines)
or Annelid (169 million cells, 778k lines).

## Reading

The readers of this section handle two-state files; a universe of more states reads and
writes [multi-state files](#multi-state-files). A file is lines of ASCII text:

1. **Header.** The first line starts with `[M2]`, usually followed by the writing program
   and version, e.g. `[M2] (example 1.0)`.
2. **`#` lines**, anywhere after the header:
   - `#R <rule>` — the rule: any Life-like rule ([rules.md](rules.md)), B0 included,
     but no preset name such as `life` ([rules.md](rules.md#preset-names)). Without
     `#R` the rule is `B3/S23`. Under a rule with B0 the file's cells are the universe's
     cells at its generation, those that differ from the background
     ([hashlife.md](hashlife.md#rules-with-b0)).
   - `#G <n>` — the generation: one or more ASCII digits `0`–`9`, any size, no sign (a
     sign or any other character is an error); 0 without it.
   - `#FRAMES …` and `#FRAME …` — a [timeline](#timelines); a reader that wants one
     universe skips them.
   - `#N`, `#O`, `#C` and `#c` — the pattern's [metadata](#metadata).
   - Any other `#` line is skipped.
3. **Node lines**, numbered 1, 2, 3, … in file order (blank and `#` lines don't count):
   - **Leaf** (level 3, an 8 × 8 square): rows top to bottom, cells left to right, `.` dead
     and `*` alive, each row ended by `$`. Trailing `.` in a row, and trailing empty rows,
     may be omitted, as may the final `$`. No whitespace; more than 8 rows or more than 8
     cells in a row is an error. A line is a leaf iff it starts with `.`, `*`, or `$`.
   - **Internal**: `<level> <nw> <ne> <sw> <se>` — five decimal integers; each child is
     the number of an earlier node line of level `level − 1`, or `0` for an empty square.
     Two-state files use level ≥ 4 here. A level above 512 is an error
     ([hashlife.md](hashlife.md#quadtree), "Depth").
   - **Multistate syntax**, accepted when every state is 0 or 1: `1 <nw> <ne> <sw> <se>`
     is a 2 × 2 square whose four values are cell states; `2 …` and `3 …` lines have
     children of level 1 and 2. (A level-3 line built this way is a leaf.)
4. **Root.** The last node line. A root of level k is placed by the tree coordinates of
   [hashlife.md](hashlife.md#quadtree): the root covers x ∈ [−2^(k−1), 2^(k−1) − 1] and
   y ∈ [−2^(k−1) + 1, 2^(k−1)] (the upper-left cell of the root's SE child is (0, 1)).

A file with no node lines, a child that refers forward or to the wrong level, or any other
malformed line is an error. Blank lines before the header are skipped. Gzip compression is
a container: a reader handed bytes that begin `1f 8b` decompresses them first, and bytes
become text as [formats.md](formats.md#bytes-and-text) says (UTF-8 when they are valid
UTF-8, otherwise Latin-1).

## Writing

Writing is canonical — conforming ports write identical bytes for identical cells,
generation, and rule — and every file written is an ordinary Macrocell file that other
readers of the format accept.

1. `[M2] (heaton-life)`
2. `#R <rule>` in canonical form ([rules.md](rules.md#canonical-form); `B3/S23`).
3. `#G <generation>` in decimal, only when the generation is above 0.
4. The nodes of the **minimal root**: the smallest level k ≥ 3 whose square (placed as in
   "Reading") holds every live cell. Equivalently, start from any centered root and
   replace it by its centered child-of-children square while that square holds the whole
   population.
5. **Node order.** Depth-first from the root, children in the order NW, NE, SW, SE, each
   node written after its children — post-order — and only the first time it is reached.
   Line numbers count from 1 in that order; an empty child is written as `0` and never
   gets a line.
6. **Leaf lines** in the format's compact form: rows 0 through the last row that holds a
   live cell, each with its trailing `.` removed and then `$` appended (so an empty row is
   `$`). For example a glider in the lower right of a leaf: `$$$.....*$......*$....***$`.
7. **Internal lines** `<level> <nw> <ne> <sw> <se>`, single spaces.
8. The **empty universe** is the empty leaf, written `$`.

Lines end with `\n` (LF), including the last. [Metadata](#metadata), when a writer is
given some, goes after `#R` and `#G`, before the nodes; without it no comment lines are
written.

## Metadata

A file carries the metadata of [formats.md](formats.md#metadata): `#N <name>`,
`#O <author>`, and comment lines `#C <text>` (or `#c`), anywhere after the header. The
first `#N` and `#O` count; comments keep their order. The canonical writer, given
metadata, writes `#N` (when there is a name), `#O` (when there is an author), then one
`#C` line per comment, between `#G` (or `#R`) and the nodes. For example a named glider
whose top-left cell is (0, 0):

```
[M2] (heaton-life)
#R B3/S23
#N Glider
#C The first spaceship found.
$$$.....*$......*$....***$
```

## Timelines

A **timeline** file holds several frames of one universe — its cells at evenly spaced
generations — and the frames share the file's one node table, so structure that frames
have in common is written once.

**Reading.** On top of an ordinary file:

- `#FRAMES <count> <first> <step>` — exactly one such line, anywhere after the header.
  `count` (at least 1) and `first` are ASCII digits, any size, no sign. `step` is ASCII
  digits, or `<b>^<e>`: two runs of ASCII digits joined by `^`, meaning b to the power e
  (`2^3` is 8; any b to the power 0 is 1). The step is at least 1 and below 2⁴⁰⁹⁶; a power
  that would pass that is refused before it is computed. Frame i, for i from 0 to
  count − 1, is the universe at generation `first + i × step`.
- `#FRAME <i> <n>` — frame i's root is node line n, both ASCII digits. Every i from 0 to
  count − 1 has exactly one `#FRAME` line. n is any node line of the file (1 up to the
  number of node lines), of any level, and a frame's root is placed as the file's root is
  ("Reading", step 4). References are resolved once the whole file is read, so a `#FRAME`
  line may come before or after its node; writers put them after the nodes.

Anything else is an error for a timeline reader: no `#FRAMES` line or two of them, a
malformed field, a count of 0, a frame index past `count − 1` or given twice, a missing
frame, n of 0 or past the last node line, a step of 0 or one too large. The file's own
root and `#G` still describe one universe, the one a reader without timelines loads; the
writer below makes it the last frame. Python: `read_timeline(source)`, giving a
`MacrocellTimeline` (one `universe` holding every frame's nodes, left at the file's root
and generation, and `frames`, a snapshot of each); .NET: `Macrocell.ReadTimeline`. The
reader by content gives a timeline's frames too
([formats.md](formats.md#reading-into-the-unbounded-universe)), and `read_snapshot` reads
them into a universe that exists
([formats.md](formats.md#reading-into-a-universe-that-exists)).

**Writing.** From frames that are snapshots of one universe, in order, at generations
spaced evenly by a step of at least 1 (a single frame has step 1). Writing is canonical:

1. `[M2] (heaton-life)`
2. `#R <rule>`: the universe's rule, in canonical form.
3. `#G <generation>` of the last frame, only when it is above 0.
4. `#FRAMES <count> <first> <b>^<e>`: the number of frames, the first one's generation,
   and the step written as a power, b the smallest integer of at least 2 that the step is
   a power of: 1 is `2^0`, 8 is `2^3`, 12 is `12^1`, 36 is `6^2`.
5. The metadata lines, when there is metadata ([Metadata](#metadata)).
6. The nodes: frame by frame in order, each frame's minimal root ("Writing", step 4)
   written in the order, and with the lines, of "Writing" steps 5–8, except that a node
   already written for an earlier frame is not written again. An empty frame's root, the
   empty leaf, gets the line `$` the first time; under a parent it is still the child `0`.
7. When the last line written is not the last frame's root, that root's line is written
   once more, so a reader without timelines loads the last frame.
8. `#FRAME <i> <n>` for each frame in order, n the number of the line where its root was
   first written.

Every frame must belong to the universe being written, there must be at least one, and
the steps between frames must all be the same step of at least 1 and below 2⁴⁰⁹⁶, or
writing is an error. Python: `write_timeline(universe, frames, metadata=None)`; .NET:
`Macrocell.WriteTimeline`. For example, a blinker on (−1, 0), (0, 0) and (1, 0) at
generations 0, 1 and 2 — each frame's minimal root is a leaf, and the third frame's root
was written for the first, so its line is written again at the end:

```
[M2] (heaton-life)
#R B3/S23
#G 2
#FRAMES 3 0 2^0
$$$...***$
$$....*$....*$....*$
$$$...***$
#FRAME 0 1
#FRAME 1 2
#FRAME 2 1
```

## Multi-state files

A [multi-state HashLife](hashlife-multistate.md) universe is read and written in the same
format, with leaves of four states. Its nodes are those of
[hashlife-multistate.md](hashlife-multistate.md#quadtree): a level-1 node is a 2 × 2
square of states, and a node of level k ≥ 2 has four children of level k − 1.

**Reading.** As "Reading" above, with these differences:

- `#R <rule>` names a state rule ([hashlife-multistate.md](hashlife-multistate.md#state-rules)).
  Without it the file takes the rule its reader is given (`WireWorld` by default).
- **Leaf lines** `1 <nw> <ne> <sw> <se>`: a 2 × 2 square, its four values the states of
  its NW, NE, SW and SE cells, each one or more ASCII digits from 0 to 255.
- **Internal lines** `<level> <nw> <ne> <sw> <se>` for any level from 2 to 512: each child
  is the number of an earlier node line of level `level − 1`, or `0` for a square of 0
  cells.
- Two-state leaf lines (`.`, `*`, `$`) read too, as level-3 nodes of states 0 and 1.
- Every state must be below the rule's number of states; the check is made once the
  whole file is read, so `#R` may come anywhere after the header.
- The root is the last node line, placed as "Reading", step 4, says: a level-1 root
  covers the cells x ∈ {−1, 0}, y ∈ {0, 1}.
- **A rule appended to the file.** A line that starts with `@RULE` ends the file's
  Macrocell lines: it and the whole rest of the text are a rule file appended to the
  pattern ([ruletable.md](ruletable.md#files)), as an RLE file carries one. When `#R`
  names that rule, and the reader isn't given a rule object of that name, the file runs
  under it, before the name is looked up.

**Writing.** Canonical, as "Writing" above says, with these differences:

- `#R` gives the universe's rule by its canonical name.
- The minimal root is the smallest level k ≥ 1 whose square holds every non-zero cell.
- A leaf is written `1 <nw> <ne> <sw> <se>`, the states in decimal, single spaces; a leaf
  of four 0 cells is the child `0` and never gets a line.
- The empty universe is the empty leaf, written `1 0 0 0 0`.
- No rule file is appended: the canonical text is the cells'. A host appends a rule
  outside the starter set with `append_rule` ([ruletable.md](ruletable.md#files)).

For example, the Wireworld clock `CBA3C$C4.C$6C!` with its top-left cell at (0, 0):

```
[M2] (heaton-life)
#R WireWorld
1 0 0 3 2
1 0 0 1 3
2 0 0 1 2
1 0 0 3 3
2 0 0 4 0
3 0 0 3 5
1 3 0 3 3
2 7 4 0 0
1 0 3 3 3
2 9 0 0 0
3 8 10 0 0
4 0 6 0 11
```

[Timelines](#timelines) are read and written as for two states, from these node lines; an
empty frame's root is written `1 0 0 0 0` the first time. Python:
`heaton_life.ca.hashlife.multistate.read_timeline` and `write_timeline`; .NET:
`MultiStateMacrocell.ReadTimeline` and `WriteTimeline`.

## Notes

- The y offset of one row is part of Macrocell's convention: a tree keeps y pointing up
  and negates it at the edge. Files therefore agree cell for cell between heaton-life and
  any other Macrocell reader or writer that places the root this way. For example, the
  Caterpillar's published file places its top-left cell at (0, 0) in both.
- RLE ([patterns.md](patterns.md#rle-in-the-unbounded-universe)) carries patterns inside
  the editing box; Macrocell carries anything.
