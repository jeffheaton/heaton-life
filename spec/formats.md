# Pattern files

Conformance tier: **bit-exact**: what a file reads as (its format, cells, position, rule,
generation, and metadata), what it measures as, and the canonical text the writers make.
Vectors: [`vectors/formats/`](../vectors/formats/).

Life patterns travel in eight file formats, and a reader recognizes each by its content,
never by the file's name:

- RLE ([patterns.md](patterns.md#rle-text-encoding-life-like-wireworld-cyclic)),
- Macrocell ([macrocell.md](macrocell.md)), including its timelines,
- plaintext (`.cells`),
- Life 1.05 and Life 1.06 (`.lif`, `.life`),
- [MCell](#mcell) (`.mcl`),
- PNG and BMP images.

Any of them may arrive gzip-compressed. This page defines how bytes become text, how a
format is recognized, what the six formats without a page of their own mean, the
metadata every text format can carry, and the readers built on top: one that gives a
dense grid, one that gives a [HashLife](hashlife.md) universe, and one that reads into a
universe that exists. A file can also be
measured, its grid's size found without the grid being made, before either reader is
asked for memory.

## Bytes and text

- **Gzip.** Bytes that begin `1f 8b` are a gzip stream (RFC 1952) of exactly one member.
  A reader inflates it once and goes on with the inflated bytes; inflated bytes that begin
  `1f 8b` again are not inflated a second time. The member's CRC-32 and length are
  checked: a stream that is cut short, damaged, or followed by more bytes (a second member
  included) is an error.
- **Images.** Bytes that begin with PNG's signature `89 50 4E 47 0D 0A 1A 0A` are a PNG
  image. Bytes that begin `42 4D` (`BM`) and hold, at offset 14, a little-endian 32-bit
  header size of 12, 40, 52, 56, 108 or 124 are a BMP image.
- **Text.** Any other bytes are text, unless they hold a NUL byte (`00`): then they are
  not a pattern file, an error. Text bytes that are well-formed UTF-8 (Unicode's
  definition: no overlong forms, no surrogates, nothing past U+10FFFF) decode as UTF-8,
  and one leading U+FEFF (a byte-order mark) is dropped. Otherwise each byte is the
  Latin-1 character of the same value. A reader handed text (a string, say from the
  clipboard) starts here.
- **Lines.** Text splits into lines at `\n`, `\r\n` and `\r`, and at U+000B, U+000C,
  U+001C, U+001D, U+001E, U+0085, U+2028 and U+2029 — the line ends of Python's
  `str.splitlines`. A line end at the very end of the text does not begin another line.
- **Stripping** a line removes the whitespace at its ends: Unicode's White_Space
  characters and U+001C through U+001F (the characters of Python's `str.isspace`). A
  **blank** line is one that strips to nothing.

## Detection

The first rule that matches names the format.

1. Gzip: inflate, then go on with the inflated bytes.
2. PNG's signature: `png`.
3. BMP's signature: `bmp`.
4. A NUL byte: not a pattern file (an error).
5. Decode the text. Text without a non-blank line is empty (an error).
6. The first non-blank line, stripped:
   - starts with `[M2]`: `macrocell`;
   - starts with `#Life 1.05`: `life-1.05`;
   - starts with `#Life 1.06`: `life-1.06`;
   - starts with `#MCell`: `mcell`;
   - starts with `!`: `plaintext`.
7. Skipping blank lines and the lines that start with `#` once stripped, the first line
   left is an RLE header (`x = <digits>, y = <digits>`, read as
   [patterns.md](patterns.md#rle-text-encoding-life-like-wireworld-cyclic) reads it):
   `rle`.
8. Every non-blank line, stripped, consists only of `.`, `O` and `*`: `plaintext`.
9. Anything else: `rle`. (The RLE reader then reports what it can't read.)

The names above are the formats' names everywhere (results, vectors): `rle`,
`macrocell`, `plaintext`, `life-1.05`, `life-1.06`, `mcell`, `png`, `bmp`. Python's
`detect_format(source)` and .NET's `PatternFiles.Detect` give the name alone.

## Metadata

Every text format can carry three kinds of text besides its cells, and a reader returns
them as the pattern's **metadata**:

- `name` — what the pattern is called, or none;
- `author` — who found or made it (free text: names, an address, a date), or none;
- `comments` — the comment lines in file order, each a string, empty ones included.

| format | name | author | comment lines |
|---|---|---|---|
| RLE, Macrocell | `#N <text>` | `#O <text>` | `#C <text>`, `#c <text>` |
| plaintext | `!Name: <text>` | `!Author: <text>` | any other line that starts with `!` |
| Life 1.05, Life 1.06 | — | — | `#D <text>`, `#C <text>` |
| MCell | — | — | `#D <text>` |
| PNG, BMP | — | — | — |

Lines are stripped first. A value is the rest of its line after the tag (`#N`, `!Name:`,
`!`, …), stripped, and an empty name or author counts as none. The first name line and
the first author line count; later ones are ignored. In RLE a `#CXRLE` first line is not a
comment ([patterns.md](patterns.md#rle-in-the-unbounded-universe)); anywhere else it is a
`#C` line, and its text begins `XRLE`. The formats' other `#` lines (RLE's `#P`, `#R` and
`#r`; Macrocell's `#R`, `#G`, `#FRAMES` and `#FRAME`) are not metadata.

**Writing.** RLE (a grid's, [patterns.md](patterns.md#rle-text-encoding-life-like-wireworld-cyclic),
and the universe's, [patterns.md](patterns.md#rle-in-the-unbounded-universe)) and
[Macrocell](macrocell.md#metadata) write metadata as lines: `#N <name>` when there is a
name, `#O <author>` when there is an author, then `#C <text>` for each comment, or `#C`
alone for an empty one. Values are written stripped, and a value that holds a line end
(any character that ends a line, above) is an error. Without metadata the writers make
exactly the canonical text their own pages describe. The [MCell](#mcell) writer has only
`#D` lines, and writes the name, the author and the comments as those.

**API.** Python: `PatternMetadata(name, author, comments)`; `rle_metadata(text)`; the
`metadata=` argument of `rle_encode`, `HashLife.to_rle`, `HashLife.to_macrocell`,
`HashLife.save` and `write_timeline`; and the `metadata` of every reader's result below.
.NET: `PatternMetadata` (`Name`, `Author`, `Comments`); `Patterns.RleMetadata`; overloads
of `Patterns.RleEncode`, `HashLife.ToRle`, `HashLife.ToMacrocell`, `HashLife.EncodeFile`
and `Macrocell.Write` that take one; and `Metadata` on every result.

## Rules in survival/birth order

Older programs write a Life-like rule with its survival digits first: `23/3` is Conway's
Life, `B3/S23`. Text of the form `<digits>/<digits>`, every digit `0`–`8` and either side
possibly empty, reads as `B<birth>/S<survival>`, each side's digits sorted and repeats
dropped: `23/3` is `B3/S23`, `/2` is `B2/S`, and `3/` is `B/S3`. Any other text is left as
written. Life 1.05's `#R` line and an RLE header's rule are read this way.

In an RLE header the [bounded-grid suffix](topology.md#the-bounded-grid-suffix) comes off
first, and the rest is read this way: `rule = 23/3:T30,20` is `B3/S23` on a 30 × 20 torus.
A rule so read is a Life-like rule, so it makes the file two-state
([patterns.md](patterns.md#rle-text-encoding-life-like-wireworld-cyclic)), and it is the
rule the reader reports. Writers write the `B…/S…` form, canonical RLE included: an RLE
read from `rule = 23/3` writes `rule = B3/S23`.

## Plaintext

A line that starts with `!` once stripped is a comment ([Metadata](#metadata)). Every other
line is a row of cells, top to bottom from y = 0: `.` is dead, and `O` or `*` is alive,
left to right from x = 0. A row is read once its trailing whitespace is stripped; the
cells past its end are dead, so an empty line is a row of dead cells. Blank lines at the
end of the text are not rows. Any other character in a row (leading whitespace included)
is an error.

The grid is as wide as the longest row and as tall as the rows. A plaintext file names no
rule and no generation.

## Life 1.05

The first non-blank line starts with `#Life 1.05`. A later line that starts with `#` once
stripped is read from its stripped form: its tag is its first two characters, and its
value the rest, stripped. Any other line is a row, read once its trailing whitespace is
stripped. Each line is one of:

- `#D <text>` or `#C <text>` — a comment ([Metadata](#metadata)).
- `#N` — the rule is `B3/S23`.
- `#R <rule>` — the rule. Life 1.05 writes rules as survival/birth, so `#R 23/3` is
  Conway's Life: the text is read in [survival/birth order](#rules-in-survivalbirth-order).
  An `#R` with nothing after it is ignored. The last `#N` or `#R` line counts.
- `#P <x> <y>` — begins a block whose top-left cell is (x, y): two integers, each an
  optional `-` and one or more ASCII digits, any size, separated by whitespace, with
  nothing else on the line. Any other form is an error.
- Another line that starts with `#`: ignored.
- A row: `.` is dead, and `*` or `O` is alive. A block's first row is at its y, each later
  row one lower, and the cell in column i is at x + i. Cells past a row's end are dead,
  so an empty line is a row of dead cells. Any other character in a row is an error.

Rows before the first `#P` line form a block at (0, 0). Blocks may overlap; a cell is
alive if any block makes it alive. x grows to the right and y grows downward. The file
names no generation.

## Life 1.06

The first non-blank line starts with `#Life 1.06`. Every line after it is blank, a line
that starts with `#` once stripped, read as in Life 1.05 (`#D` and `#C` comments, `#N` and
`#R` rules; any other `#` line, `#P` included, is ignored), or one live cell: once
stripped, two integers `<x> <y>` (each an optional `-` and one or more ASCII digits, any
size) separated by whitespace, with nothing else. Any other line is an error. x grows to
the right and y grows downward. A cell may be listed more than once. The file names no
generation.

## MCell

MCell files (`.mcl`) come from MCell, a cellular automaton program for Windows, and its
predecessor MCLife. This section follows the format's description by MCell's author,
for the families this library runs: Life, Generations and Larger than Life. MCell has no
[History](history.md) rules; what it calls a cell's history is the dying states of its
Generations and Larger than Life rules, which those families here keep.

The first non-blank line starts with `#MCell`, then a version (`#MCell 4.20`) that is not
checked. Every later line is read stripped: a blank line is skipped, and any other line
must start with `#`. A line's **keyword** is its text up to its first whitespace, and its
**value** the rest, stripped. Keywords are matched exactly as written:

| keyword | meaning |
|---|---|
| `#GAME <family>` | the rule's family; without one, `Life` |
| `#RULE <text>` | the rule; the values of every `#RULE` line, joined in order with nothing between (MCell splits a long rule); without one, `23/3` |
| `#BOARD <w>x<h>` | the board: `w` columns and `h` rows |
| `#WRAP 1` or `#WRAP 0` | whether the board's edges wrap |
| `#D <text>` | a comment line ([Metadata](#metadata)) |
| `#L <data>` | cell data: the values of every `#L` line, joined in order |

Of `#GAME`, `#BOARD` and `#WRAP` the last line counts. Every other line that starts with
`#` is ignored: `#SPEED`, `#CCOLORS`, `#COLORING`, `#PALETTE` and `#DIV` say how MCell
shows and runs a pattern, not what the pattern is, and later versions may add more.

**Families.** `#GAME`'s value, with ASCII case ignored, names the family, and the family
says how the rule reads:

- `Life`: survival/birth digits, read in [survival/birth order](#rules-in-survivalbirth-order):
  `23/3` is `B3/S23`. MCell's Life rules have one bit per cell, so every cell state from 1
  to 255 is alive, state 1.
- `Generations`: survival/birth/states digits, `<digits>/<digits>/<digits>`, read by
  [generations.md](generations.md#rules) as written: `345/2/4` is `B2/S345/C4`.
- `Larger than Life`: [ltl.md](ltl.md#rule-text)'s rule text, its whitespace dropped first
  (MCell's own lists space the fields: `R5,C0,M1, S34..58, B34..45,NM`).

The reader reports the rule as these give it: Life's as `B…/S…`, Generations' as written,
and Larger than Life's without its whitespace. In the last two a cell keeps its state,
which must be below the rule's number of states. Any other family (`Weighted Life`,
`Vote for Life`, `Rules table`, `Cyclic CA`, `1-D totalistic`, `Neumann binary`,
`General binary`, `Margolus`, `User DLL`, `Special rules`, …) is an error.

**Cell data.** The joined data is [extended RLE](patterns.md#rle-text-encoding-life-like-wireworld-cyclic)
without a header or an end mark. Whitespace is ignored, and the rest is items, each an
optional run count (ASCII digits) and a tag:

- `.` is state 0, and `A`–`X` are states 1–24;
- a prefix `a`–`j` and a letter `A`–`X` make one tag: the prefix adds 24 (`a`) to 240
  (`j`) to the letter's state, so `aA` is 25, `aX` 48, `bA` 49 and `jO` 255;
- `$` ends a row.

A run count repeats its tag, a two-letter tag included (`9aB` is nine cells of state 26),
and a count of 0 makes nothing. Rows run top to bottom from y = 0, each left to right from
x = 0, and the cells past a row's end are dead. As in RLE's extent, a row is as long as its
runs add up to (dead runs included), the pattern is as wide as its longest row, and its
rows are one more than its row ends; data without an item has no rows.

**The board.** A file with a `#BOARD` line is a [bounded grid](#bounded-grids): a world
of `w × h` cells that is a torus when `#WRAP` is 1 or missing, and the plane when it is 0.
Without `#BOARD` the file is a pattern alone, and `#WRAP`, which must still be 0 or 1,
plays no part. `#BOARD`'s value is ASCII digits, `x` or `X`, and ASCII digits, with
whitespace allowed around the `x`; each side is 1 to 2,000,000,000.

**Errors.** A file that breaks these rules is refused, with the message `invalid MCell
file: ` and one of these reasons (the vectors pin them). The checks run in this order, and
the first problem found is the one reported: the lines top to bottom, the family, the
rule, `#BOARD`, `#WRAP`, the cell data from its start, and last, for a board, whether
the pattern fits it.

| problem | reason |
|---|---|
| a line that doesn't start with `#` | `line <n> does not start with '#'` |
| a family not read here | `the family '<value>' is not read here (Life, Generations and Larger than Life are)` |
| a Life rule of another form | `a Life rule is survival/birth digits, such as 23/3, not '<rule>'` |
| a Generations rule of another form | `a Generations rule is survival/birth/states digits, such as 345/2/4, not '<rule>'` |
| a rule its family's parser refuses | that parser's own message |
| a bad `#BOARD` | `#BOARD is <width>x<height>, not '<value>'` |
| a bad `#WRAP` | `#WRAP is 0 or 1, not '<value>'` |
| any other character in the data | `'<character>' in the cell data is no run count, state or '$'` |
| a run count with nothing after it | `a run count in the cell data has no state or '$' after it` |
| a prefix without its letter | `'<prefix>' in the cell data has no state letter A to X after it` |
| a two-letter state past 255 | `the cell data's state <n> is past 255` |
| a state at or past the rule's count | `the cell data's state <n> is past the rule's <count> states` |
| a live cell outside the board | `the pattern reaches past its board (<suffix>)`, the board's world written as its [suffix](topology.md#the-bounded-grid-suffix) |

Here `<n>` counts lines from 1, `<value>` and `<rule>` are as written (a rule as joined),
and `<character>` and `<prefix>` are the one character found.

**Writing.** `mcell_encode(cells, rule, topology=None, metadata=None)` (.NET
`Patterns.McellEncode`) writes a grid as an MCell file that reads back as the same cells,
rule and world, its metadata all comments:

```
#MCell 4.00
#GAME <family>
#RULE <rule>
#BOARD <w>x<h>
#WRAP <1 or 0>
#D <text>
#L <data>
```

- **The rule** picks the family. A Life-like rule whose [canonical form](rules.md#canonical-form)
  is `B<digits>/S<digits>`, an outer totalistic rule of the Moore neighborhood (B0
  included), is `Life`, written survival/birth: `B3/S23` as `23/3`. A
  [Generations](generations.md) rule whose Life-like rule is one is `Generations`, written
  `<survival>/<birth>/<states>`: `B2/S345/C4` as `345/2/4`. A [Larger than Life](ltl.md)
  rule is `Larger than Life`, written in canonical form. Any other rule (isotropic,
  hexagonal, von Neumann or MAP rules, a History rule, Wireworld, …) is an error: no
  family of MCell's holds it.
- **The world.** With a topology, `#BOARD` is the grid's size and `#WRAP` is 1 for the
  torus and 0 for the plane; any other topology, a shifted torus included, is an error.
  Without one there is no `#BOARD` and no `#WRAP` line.
- **Metadata**: a `#D` line for the name and one for the author when there are any, then
  one for each comment (`#D` alone for an empty one), stripped; a value that holds a line
  end is an error.
- **Cells**: each below the rule's number of states (0 or 1 for a Life rule), else an
  error. A grid with no rows or no columns is an error too.
- **The data** decodes to exactly the grid: each row as runs of equal states, with its
  trailing dead cells left out; rows ended by `$`, k ≥ 2 row ends in a row written `k$`,
  so an empty row is one more row end and empty rows at the end are row ends after the
  last row; and when no row reaches the grid's last column, the first row is padded with
  dead cells to the grid's width. States are written `.`, `A`–`X`, and `aA`–`jO` past
  24. The data is cut into `#L` lines of at most 70 characters after `#L `, between
  items.

The MCell reader also feeds [measuring](#measuring) and both unbounded universes: the
[two-state one](#reading-into-the-unbounded-universe) reads a Life file, and the
[multi-state one](hashlife-multistate.md#pattern-io) a Generations file.

## Images

Each pixel of a PNG or BMP image is a cell: the top-left pixel at (0, 0), x to the right,
y downward. A pixel is **dead when it is white and alive otherwise**. Transparency plays
no part: a transparent pixel counts by its color. An image names no rule, no generation,
and no metadata.

**PNG.** Any valid PNG image (ISO/IEC 15948): every color type and bit depth, interlaced
(Adam7) or not. White means:

- grayscale (color type 0) and grayscale with alpha (4): the gray sample is the largest
  its depth holds (1, 3, 15 or 255) at depths 1 to 8; at depth 16, its high byte is 255
  (the sample is at least 65,280);
- truecolor (2) and truecolor with alpha (6): red, green and blue are each 255 at depth
  8; at depth 16, each one's high byte is 255;
- indexed color (3): the pixel's palette entry is (255, 255, 255). A pixel whose index has
  no entry in the palette is an error.

Alpha samples and the `tRNS` chunk are never read, and no ancillary chunk changes a
sample (no gamma, no color management). An animated PNG gives its default image, the one
in `IDAT`. Anything that is not a valid PNG is an error: a broken chunk, a missing `IHDR`
or `IDAT`, a forbidden depth for the color type, a palette image without `PLTE`, image data
that doesn't inflate to exactly the rows the header implies. A port may also check the
chunks' CRCs and refuse a file whose CRC is wrong; the vectors hold none.

**BMP.** A file header of 14 bytes (`BM`, then at offset 10 the little-endian offset of
the pixel data) and an info header whose size, at offset 14, is one of:

- 12 (the core header): width and height as unsigned 16-bit numbers at offsets 18 and
  20, the bit count at 24; bit counts 1, 4, 8 and 24; a palette of 3-byte entries
  (blue, green, red); rows bottom to top.
- 40, 52, 56, 108 or 124 (the info header and its later versions): width (signed 32-bit,
  at least 1) at 18, height (signed 32-bit, not 0; negative means the rows run top to
  bottom, positive bottom to top) at 22, the bit count at 28, the compression at 30, and
  the number of palette colors at 46; a palette of 4-byte entries (blue, green, red,
  unused). The other fields are ignored.

Compression 0 (none) takes bit counts 1, 4, 8, 16, 24 and 32. Compression 3 (bit fields)
takes 16 and 32, with the red, green and blue masks at offsets 54, 58 and 62 (after a
40-byte header, inside a longer one); the masks must be 5-6-5 (`F800`, `07E0`, `001F`) or
5-5-5 (`7C00`, `03E0`, `001F`) for 16 bits, and for 32 bits each must select one whole
byte (`FF` shifted left by 0, 8, 16 or 24 bits), a different byte each. Any other
compression (including the run-length forms 1 and 2), header size, bit count, or mask is
an error.

Bit counts 1, 4 and 8 index the palette, which follows the info header (and the masks,
when a 40-byte header has them). Its size is the header's color count, or 2^bits when the
count is 0; entries past 2^bits are never used. Rows start at the pixel data offset, each
`((width × bits + 31) div 32) × 4` bytes long; a 1- or 4-bit pixel is read from the high
bits of its byte first. Pixel data that ends before the last row, or a palette that runs
past the end of the file, is an error. White means:

- 1, 4 and 8 bits: the palette entry is (255, 255, 255); an index past the palette's
  entries is an error;
- 16 bits without bit fields: the 5-bit fields (red bits 10–14, green 5–9, blue 0–4 of
  the little-endian word; bit 15 unused) are each 31; with bit fields, each field is the
  largest its mask holds (31, or 63 for 5-6-5's green);
- 24 bits: the three bytes (blue, green, red) are 255;
- 32 bits: without bit fields the first three bytes are 255 (the fourth is unused); with
  them, the three bytes the masks select are 255.

## Reading into a grid

`read_pattern(source, max_cells, trim)` (.NET `PatternFiles.Read`) detects the format and
gives a `PatternFile`: the format's name, the cells as a dense grid (row-major bytes), the
position (x, y) of the grid's top-left cell in the file's own coordinates, the rule (or
none), the generation, and the metadata.

| format | grid | x, y | rule | generation |
|---|---|---|---|---|
| `rle` | the RLE decode of [patterns.md](patterns.md#rle-text-encoding-life-like-wireworld-cyclic): the declared size, either dialect, states up to 255; for a [bounded grid](#bounded-grids), its whole world | `#CXRLE Pos`, or (0, 0); for a bounded grid, the world's top-left | the header's, without a [bounded-grid suffix](topology.md#the-bounded-grid-suffix), as written or, [in survival/birth order](#rules-in-survivalbirth-order), as `B…/S…`; or none | `#CXRLE Gen`, or 0 |
| `macrocell` | the live cells' bounding box | the box's top-left | `#R` in [canonical form](rules.md#canonical-form), or `B3/S23`; a rule of more than two states (a [History](history.md), [Super](super.md) or [Generations](generations.md) rule among them) is an error here, since such a file is the [multi-state universe's](hashlife-multistate.md#pattern-io) | `#G`, or 0 |
| `plaintext` | the rows: the longest row's width × the number of rows | (0, 0) | none | 0 |
| `life-1.05`, `life-1.06` | the live cells' bounding box | the box's top-left | from `#N` or `#R`, or none | 0 |
| `mcell` | the [cell data's](#mcell) rows; for a board, its whole world | (0, 0); for a board, the world's top-left | the family's, as [MCell](#mcell) reports it | 0 |
| `png`, `bmp` | the image | (0, 0) | none | 0 |

A grid takes a file's cells as written, whatever its rule. Under a rule with B0 they are
what the file holds, the cells that differ from the unbounded universe's background at
the file's generation ([hashlife.md](hashlife.md#rules-with-b0)), and a grid runs them
as its own cells. An RLE file of a [History rule](history.md) (`rule = B3/S23History`,
or `LifeHistory`) is extended, so its cells are History's states 0–6 and its rule as
written: a Life-like world of that rule takes them. So is one of a
[Super rule](super.md) (`rule = B3/S23Super`, or `LifeSuper`), its cells states 0–25.

With `trim`, a grid that is not already a bounding box is cut to its live cells' box, and
(x, y) moves with it. A pattern without a live cell is an error for the bounding-box
formats always and for every format with `trim`; an untrimmed grid with no cells at all
(zero rows, or rows with nothing in them) is an error too.

**The decode limit** of [patterns.md](patterns.md#rle-text-encoding-life-like-wireworld-cyclic)
applies to the grid a read gives, `width × height` against `max_cells` (default 2²⁶, or
none), and a grid past it is refused before memory is asked for. An image is refused,
trimmed or not, when the image itself is past the limit, since all of its pixels must be
read. Positions, sizes, and generations are exact integers of any size.

The result also gives the file's `bounded_grid`: the world a bounded file names, or none.

### Bounded grids

An RLE file whose header rule carries a [bounded-grid
suffix](topology.md#the-bounded-grid-suffix) (`rule = B3/S23:T30,20`) is a pattern in a
world of `W × H` cells with the suffix's topology, and reading it into a grid gives that
world:

- The world's top-left cell sits at `(−⌊W/2⌋, −⌊H/2⌋)` in the file's coordinates: the
  world is centered on the origin.
- The pattern's top-left cell sits at `#CXRLE Pos`, or, without one, at
  `(−⌊w/2⌋, −⌊h/2⌋)`, where `w × h` is its decoded size
  ([patterns.md](patterns.md#rle-text-encoding-life-like-wireworld-cyclic) "Extent"): the
  pattern is centered on the origin too. A pattern written whole, its `x` and `y` the
  world's size, fills its world exactly, wherever a reader centers it.
- The grid is the world, `W × H` cells at the world's top-left: the pattern's cells where
  they land, every other cell 0. Every non-zero cell must land in the world; a pattern
  with one outside it is an error.
- The rule is the header's without the suffix, and `bounded_grid` is the suffix's world.
- With `trim`, the grid is cut to the world's live cells' box like any other. The decode
  limit applies to the world, or, trimmed, to the box.

Measuring a bounded file gives the world's size and top-left and its `bounded_grid`, and
refuses a pattern that reaches past its world, from the pattern's live box (no cell is
decoded).

An [MCell](#mcell) file with a `#BOARD` line is placed the same way: its world is the
board, and the pattern is the cell data, its decoded size centered on the origin.

Bounded grids are RLE's and MCell's alone: a Macrocell, Life 1.05 or Life 1.06 rule with
a suffix is read as written, which no rule compiler accepts.

## Measuring

`measure_pattern(source)` (.NET `PatternFiles.Measure`) detects the format and gives a
`PatternExtent`: what [reading into a grid](#reading-into-a-grid) without `trim` gives,
except the cells, found without making the grid. A file that came from outside is
measured before it is read, so a pattern too large for any grid can be sent to the
[unbounded universe](#reading-into-the-unbounded-universe), or refused, by its size, before
a reader asks for memory. The extent holds:

- `format`;
- `width` and `height`, the grid's size, and `x` and `y`, where its top-left cell sits, as
  the table above gives them: RLE's decoded size
  ([patterns.md](patterns.md#rle-text-encoding-life-like-wireworld-cyclic) "Extent") at
  its `#CXRLE Pos`, plaintext's longest row by its rows, the live cells' bounding box for
  Macrocell, Life 1.05 and Life 1.06, and an image's own size;
- `rule`, `generation` and `metadata`, as the table gives them;
- `two_state`: false for an RLE file in the extended dialect, whatever states it uses,
  and for an MCell file of the Generations or Larger than Life family; true for every
  other file. Only a two-state file can be read into the unbounded universe;
- `bounded_grid`: the world a [bounded file](#bounded-grids) names, or none. Only a file
  without one can be read into the unbounded universe.

Each format is measured without a cell being kept:

- **RLE** by the scan of patterns.md "Extent", which keeps only counters, and its
  `#CXRLE` line; **MCell** by the same kind of scan of its cell data.
- **Plaintext** by its rows' lengths; **Life 1.05** and **Life 1.06** by their cells'
  coordinates, each of which only widens a box.
- **Macrocell** from its tree: each node line's live cells have a bounding box, a leaf's
  found from its rows and every other node's from its children's, and the root's box is
  placed as reading places the root ([macrocell.md](macrocell.md#reading), step 4). No
  universe is built, so a file measures whatever its universe would need in memory.
- **PNG and BMP** from the image's header. A picture's extent is the picture: every pixel
  is a cell, alive or dead, so the grid is the whole image, its width × height pixels at
  (0, 0). The pixels are not decoded, so which of them are alive, and where their
  bounding box lies, is not part of a picture's extent.

Measuring checks what reading checks before reading would decode a cell. Text is read
whole and refused as the readers refuse it, so text that measures also reads, within the
decode limit (and, for Macrocell, the universe's memory budget). An image is checked as
far as its pixel data: PNG's chunks up to `IEND`, its `IHDR` and `PLTE` checked and an
`IDAT` present; BMP's headers, masks and palette, and the length of its pixel data. Image
data that doesn't inflate, or a pixel whose palette index has no entry, is found only
when the pixels are read, so such an image measures and is still refused by a read.

A pattern that reading refuses as empty (no cells at all, or, for Macrocell, Life 1.05
and Life 1.06, no live cell) measures 0 × 0 at (0, 0). There is no decode limit, since
nothing the size of the pattern is made, and every number is an exact integer of any
size.

A Macrocell file of more than two states is refused here, as reading it into a grid
refuses it: it is the multi-state universe's, and
[its measure](hashlife-multistate.md#measuring) gives its extent.

## Reading into the unbounded universe

`read_universe(source, max_memory_mb)` (.NET `PatternFiles.ReadUniverse`) detects the
format and gives a `PatternUniverse`: the format's name, a [HashLife](hashlife.md)
universe, and the metadata. `HashLife.from_file` (.NET `HashLife.Load`) is this reader's
universe.

- **Cells.** Two states only: an extended RLE, or an RLE state above 1, is an error.
- **Placement.** RLE as [patterns.md](patterns.md#rle-in-the-unbounded-universe) places
  it; Macrocell by its tree coordinates ([macrocell.md](macrocell.md)); plaintext,
  [MCell](#mcell) and images with their top-left cell at (0, 0); Life 1.05 and Life 1.06
  with every cell at its own coordinates.
- **Editing box.** Every live cell must lie in the [editing box](hashlife.md#editing),
  |x|, |y| ≤ 10⁹, or the file is refused — except Macrocell, which carries anything.
- **Rule.** The format's rule, or `B3/S23` without one, in any notation of
  [rules.md](rules.md), B0 included: the cells of a file of a rule with B0 are the
  universe's cells at its generation ([hashlife.md](hashlife.md#rules-with-b0)). A rule
  that is not a Life-like rule is an error, and so is a rule with a
  [variant](rules.md#variants) such as `B3/S23History` or `B3/S23Super`, whose states the two-state
  universe can't hold (the [multi-state universe](hashlife-multistate.md) reads it), and
  a [preset name](rules.md#preset-names) such as `life`: a file names its rule, never a
  preset.
- **Larger than Life.** A file whose rule is a [Larger than Life](ltl.md) rule is refused
  with that reason: LtL runs on bounded grids only.
- **Bounded grids.** An RLE file whose rule carries a [bounded-grid
  suffix](topology.md#the-bounded-grid-suffix) is an error, whatever its topology: the
  universe has no edges to give it. So is an [MCell](#mcell) file with a `#BOARD` line:
  `the unbounded universe has no bounded grid (the MCell board '<suffix>'): open the file
  in a grid world (spec/topology.md)`, the board's world written as its suffix. An MCell
  file of the Generations or Larger than Life family is refused by its rule, as above.
- **Generation.** RLE's `Gen`, Macrocell's `#G`, otherwise 0.

An empty pattern gives an empty universe.

**Timelines.** A Macrocell file with a `#FRAMES` line is a
[timeline](macrocell.md#timelines), and this reader reads it as one. The universe is left
at the file's own root and `#G`, and the result also gives the timeline's `frames` (a
snapshot of the universe for each frame, in order) and its `step`. The frame lines are
read as macrocell.md says, so a malformed timeline is an error of the read. Any other file
gives no frames and no step: a file with `#FRAME` lines but no `#FRAMES` line is not a
timeline, and its `#FRAME` lines are skipped.

## Reading into a universe that exists

`read_snapshot(source)`, a method of a [HashLife](hashlife.md) universe (.NET
`HashLife.ReadSnapshot`), reads a pattern file into the universe's own store and gives a
`PatternSnapshot`: the format's name, a [snapshot](hashlife.md#snapshots) of the file's
cells and generation, the file's rule in canonical form, its metadata, and a timeline's
`frames` and `step` (none for any other file).

- **The file** is read exactly as [reading into the unbounded
  universe](#reading-into-the-unbounded-universe) reads it: the same files are accepted
  and refused, with the same cells, placement, rule and generation. Restored, with the
  file's rule taken, the snapshot is the state that reader gives, and each frame is its
  frame.
- **The universe** doesn't change: its cells, generation and rule stay, and so does every
  snapshot taken before, which stays restorable. Restoring the file's snapshot, and taking
  its rule, is the caller's choice. A host keeps its history across a file this way: a
  world's start that lives in a file becomes a snapshot of the world's own universe, and
  going back to it can be undone like any other change.
- **Memory.** The file's nodes are built in the universe's store, so a node of the file
  that has the level and cells of a node the store already holds is that node. Reading
  never fails for lack of budget ([hashlife.md](hashlife.md#memory)). A refused file
  leaves the universe and its snapshots as they were; the store may keep some of the
  file's nodes until its next collection.

## Conformance

Bit-exact. Each case under [`vectors/formats/`](../vectors/formats/) has a `params.json`
with `family: "formats"`, `tier: "bit-exact"`, `spec_version` and a `kind`. Big integers
are decimal strings; metadata is `{"name", "author", "comments"}` with `null` for none.

| kind | inputs | expected |
|---|---|---|
| `read` | `input` (a file in any format, perhaps gzip-compressed); `trim`; `limit` (`"default"`, a number, or `null`) | `format`, `x`, `y`, `rule`, `generation`, `metadata`; `grid` (raw cell values in an 8-bit grayscale PNG, and its `shape`); `canonical`: the grid as canonical RLE with the metadata, under the rule or `B3/S23` (and, untrimmed, the bounded grid's topology); `bounded_grid`, the canonical suffix, in the cases of a bounded file (absent: none); in some cases `mcell`, the same grid as [MCell](#mcell) writes it, or `mcell_error: true` when the writer refuses it — or `error: true` |
| `universe` | `input` | `format`, `metadata`, and the universe's state as [hashlife.md](hashlife.md#vector-encoding) pins one (`generation`, `population`, `bounding_box`, `state`); `with_metadata`: its canonical Macrocell with the metadata; `rle`: its RLE with the metadata, or `rle_error: true`; for a timeline, `step` and `frames` (each frame's state), and a case without them gives no frames — or `error: true` |
| `detect` | `inputs`: a list of byte strings in hex | each one's `format`, or `error: true` |
| `measure` | `input` (a file in any format, perhaps gzip-compressed) | `format`, `width`, `height`, `x`, `y`, `rule`, `generation`, `metadata`, `two_state`; `bounded_grid` as for `read` — or `error: true` |
| `timeline-read` | `input.mc` | `count`, `first`, `step`, `metadata`, the file's own state, and `frames`: each frame's state, its canonical Macrocell in `frame-<i>.mc` — or `error: true` |
| `timeline-write` | `input` (a pattern), `generations` (a frame at each), `metadata` | `timeline`: the file [macrocell.md](macrocell.md#timelines) writes; reading it back gives each frame's state again |
| `mcell-reasons` | `cases`, each an `input` (MCell text) | each one's `message`: the full message of the error reading it into a grid gives |

The round trips (write, then read: the same cells and metadata) are property-tested in
both suites, and a case's `mcell` file reads back as its grid, rule and bounded grid,
its metadata all comments (the name, the author, then the comments), and so is measuring against reading: every `read` case's input that reads
untrimmed measures as that read gives it. So is reading into a universe that exists: every
`universe` case's input, read with `read_snapshot` into a universe that already holds a
state and a snapshot, is accepted or refused as the case says, gives a snapshot and frames
that restore to the case's states, and leaves that universe as it was. A `timeline-read`
case's input with a `#FRAMES` line is accepted or refused by `read_universe` as by the
timeline reader, with the same frames. The `snapshots` cases of
[`../vectors/hashlife/`](../vectors/hashlife/) read files into universes that hold more.
