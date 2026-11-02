# Macrocell — HashLife's native file format

Conformance tier: **bit-exact** (canonical writing). Vectors:
[`vectors/hashlife/`](../vectors/hashlife/) (`macrocell-*` and every `evolve-*` state).

Macrocell (`.mc`, often gzip-compressed as `.mc.gz`) is Golly's format for HashLife
patterns. It lists a pattern's distinct [quadtree](hashlife.md#quadtree) nodes, children
before parents, so a regular pattern of trillions of cells fits in a few lines. Where RLE
needs one token per run of cells, Macrocell needs one line per distinct node — the only
practical format for patterns like the Caterpillar (12 million cells, 337k lines) or
Annelid (169 million cells, 778k lines).

## Reading

Readers follow Golly's two-state reader. A file is lines of ASCII text:

1. **Header.** The first line starts with `[M2]`, usually followed by the writing program
   and version, e.g. `[M2] (golly 4.3)`.
2. **`#` lines**, anywhere after the header:
   - `#R <rule>` — the rule: a Life-like rulestring ([lifelike.md](lifelike.md)); B0 rules
     are rejected ([hashlife.md](hashlife.md#state)). Without `#R` the rule is `B3/S23`.
   - `#G <n>` — the generation: one or more ASCII digits `0`–`9`, any size, no sign (a
     sign or any other character is an error); 0 without it.
   - `#FRAMES …` and `#FRAME …` — Golly's timeline frames; skipped.
   - Any other `#` line is a comment (Golly writes them as `#C …`); skipped.
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
4. **Root.** The last node line. A root of level k is placed as Golly places it: the root
   covers x ∈ [−2^(k−1), 2^(k−1) − 1] and y ∈ [−2^(k−1) + 1, 2^(k−1)] (the tree
   coordinates of [hashlife.md](hashlife.md#quadtree); the upper-left cell of the root's SE
   child is (0, 1)).

A file with no node lines, a child that refers forward or to the wrong level, or any other
malformed line is an error. Gzip compression is a container: a reader handed bytes that
begin `1f 8b` decompresses them first.

## Writing

Writing is canonical — conforming ports write identical bytes for identical cells,
generation, and rule — and every file written can be read back by Golly.

1. `[M2] (heaton-life)`
2. `#R <rule>` in canonical form (`B3/S23`).
3. `#G <generation>` in decimal, only when the generation is above 0.
4. The nodes of the **minimal root**: the smallest level k ≥ 3 whose square (placed as in
   "Reading") holds every live cell. Equivalently, start from any centered root and
   replace it by its centered child-of-children square while that square holds the whole
   population.
5. **Node order.** Depth-first from the root, children in the order NW, NE, SW, SE, each
   node written after its children — post-order — and only the first time it is reached.
   Line numbers count from 1 in that order; an empty child is written as `0` and never
   gets a line.
6. **Leaf lines** as Golly writes them: rows 0 through the last row that holds a live
   cell, each with its trailing `.` removed and then `$` appended (so an empty row is `$`).
   For example a glider in the lower right of a leaf: `$$$.....*$......*$....***$`.
7. **Internal lines** `<level> <nw> <ne> <sw> <se>`, single spaces.
8. The **empty universe** is the empty leaf, written `$`.

Lines end with `\n` (LF), including the last. No comments are written.

## Notes

- The y offset of one row is Golly's: it keeps y pointing up internally and negates it at
  the edge. Files written by heaton-life and by Golly therefore agree cell for cell. For
  example, the Caterpillar's published file places its top-left cell at (0, 0) in both.
- RLE ([patterns.md](patterns.md#rle-in-the-unbounded-universe)) carries patterns inside
  the editing box; Macrocell carries anything.
