# Pattern files

Conformance tier: **bit-exact**: what a file reads as (its format, cells, position, rule,
generation, and metadata), what it measures as, and the canonical text the writers make.
Vectors: [`vectors/formats/`](../vectors/formats/).

Life patterns travel in seven file formats, and a reader recognizes each by its content,
never by the file's name:

- RLE ([patterns.md](patterns.md#rle-text-encoding-life-like-wireworld-cyclic)),
- Macrocell ([macrocell.md](macrocell.md)), including its timelines,
- plaintext (`.cells`),
- Life 1.05 and Life 1.06 (`.lif`, `.life`),
- PNG and BMP images.

Any of them may arrive gzip-compressed. This page defines how bytes become text, how a
format is recognized, what the five formats without a page of their own mean, the
metadata every text format can carry, and the two readers built on top: one that gives a
dense grid and one that gives a [HashLife](hashlife.md) universe. A file can also be
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
   - starts with `!`: `plaintext`.
7. Skipping blank lines and the lines that start with `#` once stripped, the first line
   left is an RLE header (`x = <digits>, y = <digits>`, read as
   [patterns.md](patterns.md#rle-text-encoding-life-like-wireworld-cyclic) reads it):
   `rle`.
8. Every non-blank line, stripped, consists only of `.`, `O` and `*`: `plaintext`.
9. Anything else: `rle`. (The RLE reader then reports what it can't read.)

The names above are the formats' names everywhere (results, vectors): `rle`,
`macrocell`, `plaintext`, `life-1.05`, `life-1.06`, `png`, `bmp`. Python's
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
exactly the canonical text their own pages describe.

**API.** Python: `PatternMetadata(name, author, comments)`; `rle_metadata(text)`; the
`metadata=` argument of `rle_encode`, `HashLife.to_rle`, `HashLife.to_macrocell`,
`HashLife.save` and `write_timeline`; and the `metadata` of every reader's result below.
.NET: `PatternMetadata` (`Name`, `Author`, `Comments`); `Patterns.RleMetadata`; overloads
of `Patterns.RleEncode`, `HashLife.ToRle`, `HashLife.ToMacrocell`, `HashLife.EncodeFile`
and `Macrocell.Write` that take one; and `Metadata` on every result.

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
  Conway's Life. Text of the form `<digits>/<digits>`, every digit `0`–`8` and either
  side possibly empty, becomes `B<birth>/S<survival>` with each side's digits sorted and
  repeats dropped; any other text is the rule as written, and an `#R` with nothing after
  it is ignored. The last `#N` or `#R` line counts.
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
| `rle` | the RLE decode of [patterns.md](patterns.md#rle-text-encoding-life-like-wireworld-cyclic): the declared size, either dialect, states up to 24 | `#CXRLE Pos`, or (0, 0) | the header's, as written, or none | `#CXRLE Gen`, or 0 |
| `macrocell` | the live cells' bounding box | the box's top-left | `#R` in [canonical form](rules.md#canonical-form), or `B3/S23` | `#G`, or 0 |
| `plaintext` | the rows: the longest row's width × the number of rows | (0, 0) | none | 0 |
| `life-1.05`, `life-1.06` | the live cells' bounding box | the box's top-left | from `#N` or `#R`, or none | 0 |
| `png`, `bmp` | the image | (0, 0) | none | 0 |

With `trim`, a grid that is not already a bounding box is cut to its live cells' box, and
(x, y) moves with it. A pattern without a live cell is an error for the bounding-box
formats always and for every format with `trim`; an untrimmed grid with no cells at all
(zero rows, or rows with nothing in them) is an error too.

**The decode limit** of [patterns.md](patterns.md#rle-text-encoding-life-like-wireworld-cyclic)
applies to the grid a read gives, `width × height` against `max_cells` (default 2²⁶, or
none), and a grid past it is refused before memory is asked for. An image is refused,
trimmed or not, when the image itself is past the limit, since all of its pixels must be
read. Positions, sizes, and generations are exact integers of any size.

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
  and true for every other file. Only a two-state file can be read into the unbounded
  universe.

Each format is measured without a cell being kept:

- **RLE** by the scan of patterns.md "Extent", which keeps only counters, and its
  `#CXRLE` line.
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

## Reading into the unbounded universe

`read_universe(source, max_memory_mb)` (.NET `PatternFiles.ReadUniverse`) detects the
format and gives a `PatternUniverse`: the format's name, a [HashLife](hashlife.md)
universe, and the metadata. `HashLife.from_file` (.NET `HashLife.Load`) is this reader's
universe.

- **Cells.** Two states only: an extended RLE, or an RLE state above 1, is an error.
- **Placement.** RLE as [patterns.md](patterns.md#rle-in-the-unbounded-universe) places
  it; Macrocell by its tree coordinates ([macrocell.md](macrocell.md)); plaintext and
  images with their top-left cell at (0, 0); Life 1.05 and Life 1.06 with every cell at
  its own coordinates.
- **Editing box.** Every live cell must lie in the [editing box](hashlife.md#editing),
  |x|, |y| ≤ 10⁹, or the file is refused — except Macrocell, which carries anything.
- **Rule.** The format's rule, or `B3/S23` without one, in any notation of
  [rules.md](rules.md). A rule the universe can't run (not a Life-like rule, or one with
  B0) is an error, and so is a [preset name](rules.md#preset-names) such as `life`: a
  file names its rule, never a preset.
- **Generation.** RLE's `Gen`, Macrocell's `#G`, otherwise 0.

An empty pattern gives an empty universe. Macrocell timelines have their own reader and
writer ([macrocell.md](macrocell.md#timelines)); this reader takes a timeline file's root
and `#G`, as any timeline-unaware reader does.

## Conformance

Bit-exact. Each case under [`vectors/formats/`](../vectors/formats/) has a `params.json`
with `family: "formats"`, `tier: "bit-exact"`, `spec_version` and a `kind`. Big integers
are decimal strings; metadata is `{"name", "author", "comments"}` with `null` for none.

| kind | inputs | expected |
|---|---|---|
| `read` | `input` (a file in any format, perhaps gzip-compressed); `trim`; `limit` (`"default"`, a number, or `null`) | `format`, `x`, `y`, `rule`, `generation`, `metadata`; `grid` (raw cell values in an 8-bit grayscale PNG, and its `shape`); `canonical`: the grid as canonical RLE with the metadata, under the rule or `B3/S23` — or `error: true` |
| `universe` | `input` | `format`, `metadata`, and the universe's state as [hashlife.md](hashlife.md#vector-encoding) pins one (`generation`, `population`, `bounding_box`, `state`); `with_metadata`: its canonical Macrocell with the metadata; `rle`: its RLE with the metadata, or `rle_error: true` — or `error: true` |
| `detect` | `inputs`: a list of byte strings in hex | each one's `format`, or `error: true` |
| `measure` | `input` (a file in any format, perhaps gzip-compressed) | `format`, `width`, `height`, `x`, `y`, `rule`, `generation`, `metadata`, `two_state` — or `error: true` |
| `timeline-read` | `input.mc` | `count`, `first`, `step`, `metadata`, the file's own state, and `frames`: each frame's state, its canonical Macrocell in `frame-<i>.mc` — or `error: true` |
| `timeline-write` | `input` (a pattern), `generations` (a frame at each), `metadata` | `timeline`: the file [macrocell.md](macrocell.md#timelines) writes; reading it back gives each frame's state again |

The round trips (write, then read: the same cells and metadata) are property-tested in
both suites, and so is measuring against reading: every `read` case's input that reads
untrimmed measures as that read gives it.
