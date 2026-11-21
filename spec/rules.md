# Life-like rules

Conformance tier: **bit-exact** (canonical strings and tables). Vectors:
[`vectors/rules/`](../vectors/rules/), plus grid runs in
[`vectors/lifelike/`](../vectors/lifelike/) and unbounded runs in
[`vectors/hashlife/`](../vectors/hashlife/).

A Life-like rule is a two-state rule in which a cell's next state depends only on the
cell itself and its eight neighbors, the 3 × 3 block centered on it. Every such rule is
one table of 512 entries, one for each way the block can be filled. The notations below
are ways of writing that table down; each compiles to it. The
[Life-like](lifelike.md) grid and the [HashLife](hashlife.md) universe both run the
table, so every rule on this page runs on a bounded grid and, unless it has B0, on the
unbounded plane.

## The transition table

A cell's **neighborhood index** is the sum of the weights of the live cells in its
3 × 3 block, the cell itself (C) included:

```
NW 256   N 128   NE 64
 W  32   C  16    E  8
SW   4   S   2   SE  1
```

The index runs from 0 (all nine dead) to 511 (all nine alive); bit 4 (weight 16) is the
cell's own state. The rule's **table** maps each index to the next state, 0 or 1, and a
generation replaces every cell by `table[index]` at once. MAP strings use the same
numbering (below).

A rule has **B0** when `table[0] = 1`: a dead cell with no live neighbors is born.

## Neighborhoods

| Neighborhood | Suffix | Neighbors counted | Digits |
|---|---|---|---|
| Moore | none | all eight | 0–8 |
| hexagonal | `H` | NW, N, W, E, S, SE: Moore without NE and SW | 0–6 |
| von Neumann | `V` | N, W, E, S | 0–4 |

The hexagonal neighborhood is a hexagonal grid drawn on the square one by shearing it, so
that each cell touches six others. A hexagonal or von Neumann rule ignores the cells
outside its neighborhood: its table has equal entries at any two indices that differ only
in those cells.

## Grammar

```
rule    = ws* ( bs | map ) ws*
bs      = "B" counts ws* "/" ws* "S" counts [ "H" | "V" ]
counts  = { digit [ [ "-" ] letter { letter } ] }
map     = "MAP" payload [ "==" ]
```

- `B`, `S`, `H`, `V`, `MAP` and the letters may be written in either case. A MAP
  payload is base64 and keeps its case.
- `digit` is an ASCII digit `0`–`8`, limited further by the neighborhood (the table
  above). `letter` is one of `c e k a i n y q j r t w z` (next section).
- `ws` is a whitespace character: U+0009–U+000D, U+0020, U+0085, U+00A0, U+1680,
  U+2000–U+200A, U+2028, U+2029, U+202F, U+205F or U+3000. It may appear only at the two
  ends and on either side of the `/`.
- Nothing may follow the rule. Variants that give these rules more states will be named by
  a word after the rule; until one is specified, any such suffix is an error.

### Birth and survival

Each side of a `B…/S…` rule names a set of **arrangements** of live neighbors. A digit
`n` alone names every arrangement of `n` live neighbors in the rule's neighborhood. A
digit followed by letters names only the arrangements of those letter classes; with a
`-` between them it names all arrangements of `n` except those classes. Groups add up, so
`B2a2c` is `B2ac` and a repeated digit changes nothing.

A dead cell is born when its live neighbors form an arrangement on the `B` side; a live
cell survives when they form one on the `S` side; every other cell is dead in the next
generation. A rule written with digits only is **outer-totalistic**: only the count of
live neighbors matters (`B3/S23` is Conway's Life).

Letters are allowed only in Moore rules, only after the digits 1–7, and only those
defined for their digit. Either side may be empty (`B2/S`, `B/S`).

### Letter classes (isotropic non-totalistic rules)

Letters split the arrangements of a count into classes, following the notation published
by Alan Hensel and documented on LifeWiki's page on isotropic non-totalistic rules. A
class is one arrangement together with everything it becomes under the eight symmetries
of the square (four rotations, each with or without a mirror image), so a rule written
with letters is **isotropic**: rotating or reflecting a pattern rotates or reflects its
future.

One arrangement of each class, as its live neighbors:

| Count | c | e | k | a | i | n | y | q | j | r | t | w | z |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | NW | N | | | | | | | | | | | |
| 2 | NW NE | N W | N SE | NW N | N S | NW SE | | | | | | | |
| 3 | NW NE SE | N W E | N W SE | NW N W | NW W SW | NW NE W | NW NE S | NW W SE | NE E S | N NE S | | | |
| 4 | NW NE SW SE | N W E S | N NE W SE | NW W SW S | NW NE W E | NW W SW SE | NW NE SW S | NW N W SE | N W E SE | N NE E S | NW N NE S | NW W S SE | NW N S SE |

Counts 5, 6 and 7 use the letters of 3, 2 and 1: class `(8 − n)x` is class `nx` with
every neighbor flipped (live to dead, dead to live). For example `7c` is all neighbors but
one corner, and `6i` is all but N and S. Counts 0 and 8 have one arrangement each and take
no letters. The 51 classes (1 + 2 + 6 + 10 + 13 + 10 + 6 + 2 + 1) divide the 256
arrangements of eight neighbors between them, each arrangement in exactly one class.

### MAP strings (any table)

`MAP` followed by the table in base64 writes any rule, isotropic or not:

- The alphabet is `A`–`Z`, `a`–`z`, `0`–`9`, `+`, `/`, for the values 0–63 in that
  order. Each character carries six bits, most significant first, and bit i of the
  string (from 0, the first character's most significant bit) is entry i of the table.
- The payload's length names the neighborhood:

| Payload | Neighborhood | Entries | Entry index |
|---|---|---|---|
| 86 characters | Moore | 512 | the neighborhood index above |
| 22 characters | hexagonal | 128 | NW·64 + N·32 + W·16 + C·8 + E·4 + S·2 + SE·1 |
| 6 characters | von Neumann | 32 | N·16 + W·8 + C·4 + E·2 + S·1 |

  The hexagonal and von Neumann indices keep the Moore order of the cells they have.
  Their 512-entry table repeats each entry for every value of the cells they lack.
- In each length the last character carries four bits past the table's end. A reader
  ignores them.
- The payload may be followed by `==`, the base64 padding to a multiple of four
  characters, and by nothing else.

## Canonical form

Every rule has one canonical string, and params and files always carry it. Compiling a
canonical string gives the same table, and canonicalizing it again gives the same string.

- **`B…/S…` rules:** `B`, the birth groups, `/S`, the survival groups, then `H`, `V` or
  nothing for the neighborhood. Within a side, each digit with at least one arrangement
  appears once, in increasing order:
  - every class of the digit present: the digit alone (always so for 0 and 8, and in
    hexagonal and von Neumann rules);
  - otherwise the shorter of the digit followed by its classes' letters and the digit
    followed by `-` and the letters of the classes it lacks, the letters in alphabetical
    order. When the two are the same length, the letters without the `-`.

  So `b3/s32` is `B3/S23`, `B2cekin/S12` is `B2-a/S12`, and `B4-eijryz/S` is
  `B4acknqtw/S` (eight characters either way).
- **MAP rules:** `MAP` and the payload at its neighborhood's length, without `==`, the
  unused low bits of its last character zero.

A rule keeps its notation. A MAP string stays a MAP string even when digits or letters
could write its table, and `B/S`, `B/SH`, `B/SV` and the all-`A` MAP strings all name the
all-zero table. Two rules behave identically exactly when their tables are equal.

## Errors

A rule is an error when it breaks the grammar or its limits: an unknown character; a
digit past the neighborhood's largest count; a letter not defined for its digit, or any
letter in a hexagonal or von Neumann rule; a `-` without letters; whitespace anywhere but
the ends and around the `/`; a MAP payload of another length, a character outside the
alphabet, or `=` other than a final `==`; anything after the rule.

## Preset names

A port may accept short names where a person types a rule (the Python reference's
`RULE_PRESETS`: `life` for `B3/S23`, `highlife` for `B36/S23`, …). Preset names are a
convenience at that edge: they are not part of this grammar, of the canonical form, or of
any file format.

## Vector encoding

Each case under `vectors/rules/` has a `params.json` with `family: "rules"`,
`tier: "bit-exact"`, `spec_version`, and `cases`, a list of rule texts:

- `input` — the text to compile;
- `canonical`, `neighborhood` (`moore`, `hexagonal` or `vonneumann`) and `table` — the
  512 entries as 128 lowercase hexadecimal digits, entry 0 in the high bit of the first
  digit (the bit order of a Moore MAP payload); or `error: true` where compiling must fail.

Runners are strict: an unknown key or `spec_version` fails the case.
