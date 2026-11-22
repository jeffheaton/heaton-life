# HashLife — an unbounded Life universe

Conformance tier: **bit-exact**. Vectors: [`vectors/hashlife/`](../vectors/hashlife/).

The `hashlife` family runs two-state Life-like rules on an unbounded plane with Bill
Gosper's HashLife: a hash-consed quadtree whose nodes memoize their own future. Regular
patterns of trillions of cells fit in memory, and a generation count can be any
non-negative integer. The dense [`lifelike`](lifelike.md) family stays the bounded-grid
engine (torus or dead edges); this page is its unbounded counterpart.

## State

- **Cells.** Every point (x, y) of the integer plane is dead (0) or alive (1); finitely
  many are alive. x grows to the right and y grows downward, as in RLE.
- **Generation.** A non-negative integer.
- **Rule.** A Life-like rule in canonical form ([rules.md](rules.md)): any notation, any
  of its three neighborhoods. A rule with B0 (`table[0] = 1`) is rejected: births with no
  live neighbors would light the infinite background. (A B0 rule whose table also keeps
  a cell alive among eight live neighbors, `table[511] = 1`, can be run as its complement
  rule; that is a possible later extension.)
- Coordinates, generations, and populations are unbounded integers wherever the API takes
  or returns them. Ports use big integers at their public edges and whatever they like
  inside.

## Quadtree

A level-k node is a 2^k × 2^k square of cells, k ≥ 3. A level-3 node — a **leaf** — is an
8 × 8 bitmap. A level-k node with k ≥ 4 has four level-(k−1) children in the order NW,
NE, SW, SE; with y down, NW is the top-left quarter. Nodes are hash-consed: two nodes with
equal content are the same node, so a node's identity stands for its content and a
repeated region costs one node however often it repeats.

**Tree coordinates.** The engine stores cell (x, y) at tree position (x, y − 1). Nodes
are aligned in tree coordinates (a level-k node's tree origin is a multiple of 2^k), and a
level-k root covers tree positions [−2^(k−1), 2^(k−1))² — that is, cells

- x ∈ [−2^(k−1), 2^(k−1) − 1]
- y ∈ [−2^(k−1) + 1, 2^(k−1)].

This is the placement [Macrocell](macrocell.md) files assume. Their convention keeps y
pointing up internally and negates it at the edge, which shifts rows by one: the
upper-left cell of the root's SE child is (0, 1). A Macrocell file therefore lands on the
same cells here as in any other reader that places the root this way (the Caterpillar's
file puts its top-left cell at (0, 0) in both).

**Depth.** A tree is at most level 512 (`MAX_LEVEL`), so every live cell lies within
±2^511, and a port that recurses once per level never goes deeper than 512 calls. A
[Macrocell](macrocell.md) node above level 512 is an error, and `step` refuses work that
would need a deeper root ("The deepest step", below).

How a port lays nodes out — ids, hashing, leaf encoding, caches — is not observable and
not specified.

## Evolution

`step(n)` advances exactly n generations, for any integer n ≥ 0: the rule applied n times,
synchronously, over the whole plane. The answer is unique, so any correct algorithm
conforms; the reference algorithm follows.

**The result of a node.** For a level-k node N (k ≥ 3) and 0 ≤ j ≤ k − 2,
`result_j(N)` is the level-(k−1) node at N's center, 2^j generations later. It depends on
N alone: a 3 × 3 neighborhood moves information at most one cell per generation, and in
2^j ≤ 2^(k−2) generations nothing crosses the 2^(k−2)-cell margin around the center.

- **Full speed**, j = k − 2. Form the nine overlapping level-(k−1) squares at offsets of
  2^(k−2) (the four children plus the five straddling squares). Take their full-speed
  results: nine level-(k−2) nodes, 2^(k−3) generations on. Assemble those into four
  overlapping level-(k−1) squares and take their full-speed results again; the four
  answers are the result's quarters, 2^(k−3) + 2^(k−3) = 2^(k−2) generations on.
- **Fixed step**, j < k − 2. The same, except that the first phase takes the nine squares'
  centers with no time advance, and the second phase recurses with `result_j`.
- **Leaves.** A leaf's center 4 × 4 after one or two generations is computed directly from
  the rule's table ([rules.md](rules.md#the-transition-table)), so every rule runs through
  the same machinery and no other part of the engine sees the rule.

**Sub-steps.** Write n in binary. For each set bit j, advance 2^j generations:

1. Expand the root — wrap it in a node twice its size, centered, with empty margins —
   until its level k ≥ max(j + 3, 6) and every live cell lies in the centered square of
   side 2^(k−2) (the union of the root's four innermost great-grandchildren).
2. Replace the root by `result_j(root)`. The pattern grows at most 2^j ≤ 2^(k−3) cells on
   each side, so the result's centered 2^(k−1) square holds all of it.

Full-speed results are cached per node; fixed-step results per node for the current j,
cleared when j changes. Caches never change results. A port may decompose n another way;
only the cells after n generations are observable.

**The deepest step.** Sub-step j needs a root of level j + 3, so `step(n)` with
n ≥ 2^510 raises an error before changing anything. A sub-step whose root would have to
grow past level 512 to hold the pattern (one that has spread to about ±2^509) raises an
error at that sub-step's boundary: as with cancellation, the universe holds the last
completed sub-step.

### Cancellation

`cancel()`, called from another thread, stops a running `step` at the boundary of a
completed sub-step; `step` then raises `StepCanceled`. The universe is consistent: it holds
the state at some generation between the start and the target, and `generation` says which.
A cancel that arrives while no step is running is forgotten (the next `step` clears it).

## Observables

- `generation` and `population` (the number of live cells).
- `bounding_box()`: (x0, y0, x1, y1), the inclusive extremes of the live cells, or none
  for an empty universe.
- `population_in(x0, y0, x1, y1)`: the live cells in an inclusive rectangle.
- `bounding_box_in(x0, y0, x1, y1)`: the inclusive extremes of the live cells inside an
  inclusive rectangle, or none when it holds none (an empty rectangle holds none): where
  a Shrink Selection tool moves a selection.
- The cells themselves: `get_cell`, `get_rect`, and the canonical Macrocell text
  ([macrocell.md](macrocell.md)), which pins the whole state in one string.

Queries take any integers. Editing does not.

## Editing

The **editing box** is |x| ≤ 1,000,000,000 and |y| ≤ 1,000,000,000, inclusive. Every
editing call checks every cell it would touch and, if any lies outside the box, raises an
error and changes nothing.

- `get_cell(x, y)`, `set_cell(x, y, alive)`.
- `get_rect(x0, y0, x1, y1)` → a (y1 − y0 + 1) × (x1 − x0 + 1) array of 0/1, row-major,
  origin top-left. An empty rectangle (x1 < x0 or y1 < y0) is an error.
- `set_rect(x, y, cells, mode)`: `cells` (h × w, nonzero = alive) lands with its top-left
  cell at (x, y). Modes: `copy` replaces every cell of the rectangle, `or` adds the live
  cells, `xor` toggles each cell where `cells` is alive, and `and` keeps a cell of the
  rectangle alive only where `cells` is alive too.
- `clear_rect(x0, y0, x1, y1)`: every cell of the inclusive rectangle dies.
- `clear_outside(x0, y0, x1, y1)`: every cell outside the inclusive rectangle dies,
  wherever it lies. An empty rectangle is an error (`clear()` empties everything).
- `fill_random(x0, y0, x1, y1, density, seed)`: `set_rect(x0, y0, soup, copy)` with the
  rectangle's soup: [PCG32](rng.md) with seq 0, one draw per cell in row-major order
  (y outer, x inner), alive iff `draw < floor(density · 2³²)`. These are the draws of
  lifelike's `soup` for the same width and height ([lifelike.md](lifelike.md),
  "Initialization"); `density` must lie in [0, 1].
- `rotate_rect(x0, y0, x1, y1, clockwise)` → the rectangle the cells land on, and
  `flip_rect(x0, y0, x1, y1, horizontal)`: turn or mirror the cells of an inclusive
  rectangle in place ("Rectangle transforms", below).
- `advance_selection(x0, y0, x1, y1, n)` and `advance_outside(x0, y0, x1, y1, n)`: evolve
  the inside or the outside of an inclusive rectangle on its own ("Advancing part of the
  universe", below).
- `set_generation(n)`: the generation becomes n, any integer ≥ 0; no cell changes.
- `clear()`: every cell dies.

Editing never changes the generation, except `set_generation`. A pattern larger than the
box still loads, runs, renders, and reports; it just can't be edited outside the box.

### Rectangle transforms

A quarter turn moves an inclusive rectangle (x0, y0, x1, y1) about its center, and the
rectangle turns with its cells: w × h becomes h × w. With X = x0 + x1 and Y = y0 + y1
(twice the center), let

- s = (X + Y) / 2 and d = (Y − X) / 2 when X and Y have the same parity: the turn is
  about the center itself;
- otherwise s = the even one of (X + Y − 1) / 2 and (X + Y + 1) / 2, and d = Y − s when
  X is odd, or d = s − X when Y is odd: the center lies half a cell off the grid along one
  axis, and the turn is about whichever of the two cells it lies between has an even
  x + y.

A clockwise turn sends cell (x, y) to (s − y, x + d), and the rectangle to
(s − y1, x0 + d, s − y0, x1 + d); a counter-clockwise turn sends (x, y) to (y − d, s − x),
and the rectangle to (y0 − d, s − x1, y1 − d, s − x0). Both turns of a rectangle pick the
same (s, d) as each other and as the turns of their results, so each turn undoes the
other, four make a full turn, and nothing ever drifts.

`rotate_rect` returns the new rectangle, which `turned_rect`
([patterns.md](patterns.md#editing-a-region)) gives without turning anything, so a grid
can turn a region onto the same cells. Every cell of the new rectangle takes the turned
value, live or dead (as `copy` pastes); a cell of the old rectangle outside the new one
dies; cells outside both are untouched. `flip_rect` mirrors in place: horizontally
(x, y) → (x0 + x1 − x, y), vertically (x, y) → (x, y0 + y1 − y).

Both rectangles must lie in the editing box, so a turn whose new rectangle would leave it
is an error that changes nothing; an empty rectangle is an error too. Neither operation
makes a dense copy of the rectangle: a port works on the tree, so the cost follows the
tree, not the rectangle's area or population.

### Advancing part of the universe

`advance_selection` and `advance_outside` are Advance Selection and Advance Outside
([patterns.md](patterns.md#editing-a-region)) with the plane as the world. The selection,
an inclusive rectangle in the editing box, evolves n generations as an isolated plane:
every cell outside it counts as dead at the start, the plane evolves, and the result is
clipped to the selection, whose outside is untouched. Advance Outside is the mirror
image: the outside evolves as if the selection were empty, and the selection keeps its
cells. Nothing is held back in between: cells grown outside the selection act back on it
until the result is taken, and Advance Outside's outside may grow into the empty
selection and out again before the selection's own cells are put back.

`n` is any count `step` takes (0 ≤ n < 2⁵¹⁰), and the generation doesn't change. The
evolution reaches everywhere, as `step` does; only the rectangle must lie in the box, and
it must not be empty. Each raises what `step` raises (cancellation, `HashLifeMemoryError`,
a tree too deep) and then leaves the universe exactly as it was: unlike `step`, it never
stops at a sub-step boundary.

## Snapshots

`snapshot()` records the cells and the generation in O(1) time and space: it holds the
root node. `restore(snapshot)` returns the universe to it. A snapshot keeps its nodes
alive through garbage collection until it is released or the snapshot object is dropped,
and it survives rule changes (it holds cells, not results). A snapshot belongs to the
universe that made it; restoring it into another is an error.

**Releasing.** `release()` lets go of a snapshot's nodes at once, so the next collection
can free whatever nothing else holds, without waiting for the snapshot object to be
dropped (a runtime that finds dropped objects by tracing finds them only when its own
collector runs). A released snapshot holds no cells: restoring it, or writing it into a
[timeline](macrocell.md#timelines), is an error. Its generation can still be read, and
releasing it again does nothing.

### What snapshots hold

The **nodes of a state** are the distinct non-empty nodes of its minimal tree: the minimal
root of [macrocell.md](macrocell.md#writing) "Writing", step 4, and every non-empty node
below it. They are the nodes its canonical Macrocell text writes, one line each, and the
empty universe has none. Nodes are compared by level and cells, the identity hash-consing
gives them, so a node that two states share is one node, wherever it lies in each.

`measure_snapshots(snapshots)` counts, for a list of the universe's snapshots, what they
hold beyond its current state:

- `universe_nodes`: the nodes of the current state;
- `added`: for each snapshot in order, how many of its nodes are neither the current
  state's nor those of an earlier snapshot in the list. A released snapshot adds 0, and so
  does a snapshot listed a second time;
- `nodes`: the sum of `added`, the nodes the list holds beyond the current state.

The nodes that the last k snapshots of the list hold, and that neither the current state
nor an earlier snapshot in the list holds, therefore number exactly the sum of those k
counts. Releasing those k snapshots lets a collection free that many nodes, when nothing
outside the list holds them. Listing a history newest first thus tells how much letting go
of its oldest points would free. A snapshot of another universe is an error.

The counts are exact, and the same in every port: the vectors pin them. They measure
trees, not a port's store. A store also keeps nodes the counts leave out (the empty nodes,
the few between a minimal root and the root a state is held by, and cached results), so
what a collection frees differs from them by about that much. Each port also gives
`estimated_bytes`, its own estimate of those nodes' memory: `nodes` at its store's size of
a node, 130 bytes in Python and 40 in .NET.

## Memory

`max_memory_mb` bounds the node store in MiB (2²⁰ bytes): default 500, minimum 10. The
accounting is each port's own estimate of its store (nodes and caches); the process's
whole footprint is larger.

- When the store is full the engine collects garbage, keeping what is reachable from the
  current root and the live snapshots (and, in a port that collects mid-step, work in
  flight). Cached results whose nodes are collected are dropped.
- A sub-step that cannot finish within the budget is retried after collection, then split
  into two half sub-steps, recursively, down to single generations. If one generation
  cannot fit, `step` raises `HashLifeMemoryError` at that sub-step's boundary: as with
  cancellation, the universe holds the last completed sub-step, and `generation` says
  which.
- Loading and editing never fail for lack of budget: a tree larger than the budget loads,
  renders, and reports, and the next `step` raises if it cannot make room.

The budget changes speed, never results.

## View and render

A **view** is three integers `(x, y, mag)`. `mag` is the magnification exponent:

- `mag ≥ 0`: each cell is a 2^mag × 2^mag square of pixels, up to `mag = 5` (1:32); a
  larger `mag` is an error.
- `mag < 0`: each pixel is an aligned block of 2^s × 2^s cells, s = −mag — one quadtree
  node — so a frame costs the same at any scale.

`(x, y)` is the frame's top-left pixel in the **pixel plane** of that magnification, in
tree coordinates (cell y − 1): pixel (i, j) of a frame is pixel-plane point
P = (x + i, y + j), which shows

- at `mag ≥ 0`, the cell (⌊Px / 2^mag⌋, ⌊Py / 2^mag⌋ + 1);
- at `mag < 0`, the block of cells whose top-left is (Px · 2^s, Py · 2^s + 1).

A **frame** of size (width, height) is a height × width array of bytes, row-major. Its
pixel values are:

- At `mag ≥ 0`: 255 for a live cell, 0 for a dead one, repeated over the cell's square.
- At `mag < 0`, mode `any`: 255 if the block holds a live cell, else 0.
- At `mag < 0`, mode `density`: ⌈255 · p / 4^s⌉ for a block of population p — integer
  arithmetic, (255p + 4^s − 1) div 4^s. One live cell anywhere in the block lights it.

Every function below is exact integer arithmetic (floor division and shifts on unbounded
integers), so ports move views identically and an app keeps no copy of the math:

- `pan(view, dx, dy)` = `(x − dx, y − dy, mag)`: the picture moves by (dx, dy) pixels.
- `zoom_at(view, i, j, steps)` applies |steps| single doublings, keeping pixel (i, j) over
  the same pixel-plane point: in, `(2(x + i) − i, 2(y + j) − j, mag + 1)`, stopping at
  `mag = 5`; out, `(⌊(x + i) / 2⌋ − i, ⌊(y + j) / 2⌋ − j, mag − 1)`.
- `cell_at(view, i, j)`: the cell shown by pixel (i, j), as above.
- `center_cell(view, (w, h))` = `cell_at(view, w div 2, h div 2)`.
- `centered(cx, cy, mag, (w, h))`: the view whose center pixel (w div 2, h div 2) shows
  cell (cx, cy): at `mag ≥ 0`, `(cx · 2^mag − w div 2, (cy − 1) · 2^mag − h div 2, mag)`;
  at `mag < 0`, `(⌊cx / 2^s⌋ − w div 2, ⌊(cy − 1) / 2^s⌋ − h div 2, mag)`.
- `fit(box, (w, h))`: for mag from 5 down, the first whose pixel-plane span of the box —
  at `mag ≥ 0` left = x0 · 2^mag, right = (x1 + 1) · 2^mag − 1, top = (y0 − 1) · 2^mag,
  bottom = y1 · 2^mag − 1; at `mag < 0` left = ⌊x0 / 2^s⌋, right = ⌊x1 / 2^s⌋,
  top = ⌊(y0 − 1) / 2^s⌋, bottom = ⌊(y1 − 1) / 2^s⌋ — satisfies right − left < w and
  bottom − top < h; the view is then `(⌊(left + right) / 2⌋ − w div 2,
  ⌊(top + bottom) / 2⌋ − h div 2, mag)`. An empty universe fits as `centered(0, 0, 0, …)`.
  From −mag = b + 1 on, where b is the largest bit length of x0, x1, y0 − 1, and y1 − 1
  (a negative v counted as −v − 1), every span is fixed, so a box that does not fit there
  never will and `fit` raises an error. That happens only for a frame 0 pixels across, or
  1 pixel across while the box spans tree position 0 in that direction (x0 < 0 ≤ x1, or
  y0 ≤ 0 < y1): no aligned block straddles it.
- `resized(view, (w, h), (w′, h′))` = `pan(view, w′ div 2 − w div 2, h′ div 2 − h div 2)`:
  the view for frames of a new size whose center pixel is still over the same point, so a
  resized window keeps its middle in place.
- `frame_map(frame, view)` = `(steps, dx, dy)`: where the pixels of a frame rendered at the
  view `frame` lie in `view`, with `steps = view.mag − frame.mag`.
  - `steps ≥ 0` (the view is the finer): `dx = frame.x · 2^steps − view.x`, and `dy`
    likewise from the y's. Frame pixel (u, v) covers the 2^steps × 2^steps square of view
    pixels whose top-left is (u · 2^steps + dx, v · 2^steps + dy).
  - `steps < 0` (the frame is the finer; s = −steps): `dx = frame.x − view.x · 2^s`, and
    `dy` likewise. Frame pixel (u, v) lies in view pixel
    (⌊(u + dx) / 2^s⌋, ⌊(v + dy) / 2^s⌋).

  A frame can take seconds to render and a gesture should answer at once: a viewer asked
  for a new view draws the frame it already has through this map until the new one
  arrives. Both forms are integers, so the picture never drifts by a rounding.

## Parameters

```json
{
  "rule": "B3/S23",
  "max_memory_mb": 500
}
```

## Pattern I/O

- **[Macrocell](macrocell.md)** (`.mc`, `.mc.gz`) carries any state, of any size, and its
  canonical text is how vectors pin a state. Reading places the root by the tree
  coordinates above.
- **[RLE](patterns.md#rle-in-the-unbounded-universe)** carries patterns inside the editing
  box: `#CXRLE Pos=x,y Gen=n` places the pattern and sets the generation; writing puts that
  line before the canonical RLE of the bounding box.
- Loading by content: every two-state [pattern file](formats.md) format (RLE, Macrocell,
  plaintext, Life 1.05 and 1.06, PNG and BMP images, any of them gzip-compressed),
  recognized as [formats.md](formats.md#detection) says and placed as
  [formats.md](formats.md#reading-into-the-unbounded-universe) says. Saving by extension:
  `.rle`, `.mc`, `.mc.gz` (gzip of the canonical text; the compressed bytes are the
  compressor's and not pinned), with the pattern's metadata when given.
- [Timelines](macrocell.md#timelines): frames of one universe in one Macrocell file,
  read into snapshots and written from them. Loading by content gives a timeline's frames
  too.
- Into a universe that exists: `read_snapshot(source)` reads any file that loading by
  content reads into the universe's own store, as a snapshot of its cells and generation,
  with its format, rule, metadata and a timeline's frames. The universe and its earlier
  snapshots stay as they were ([formats.md](formats.md#reading-into-a-universe-that-exists)).

## Vector encoding

Each case under `vectors/hashlife/` has a `params.json` with `family: "hashlife"`,
`tier: "bit-exact"`, `spec_version`, and a `kind`. A state is pinned by
`generation`, `population`, and `bounding_box` (decimal strings, any size; the box is
`null` when empty) plus its canonical Macrocell text: the file named by `state`, or, past
4 KiB, its `state_sha256` and `state_lines` (the count of `\n`).

| kind | inputs | expected |
|---|---|---|
| `evolve` | `input` (an `.rle` or `.mc` file, loaded by content) | `checkpoints`: states in order; a runner steps by each difference |
| `macrocell` | `input.mc` | the state, and `rle` (the canonical RLE file) or `rle_error: true`; or `error: true` |
| `rle` | `input.rle` | the state and `rle` (the canonical RLE file); or `error: true` |
| `view` | `operations`: each names a view function and its inputs (views as `[x, y, mag]`, big integers as strings) | each operation's `expect`, or `error: true` where the function must raise |
| `render` | `input`, stepped to `generation`; each frame's `view`, `size` (`[width, height]`), and `mode` | each frame's 8-bit grayscale PNG (compared by decoded pixels; the PNG bytes are the encoder's) |
| `edit` | `rule`, then `ops` in order on an empty universe: `set_cell` (`x`, `y`, `alive`), `set_rect` (`x`, `y`, `mode`, `cells` as rows of `.`/`*`), `clear_rect` (`x0`…`y1`), `fill_random` (`x0`…`y1`, `density`, `seed`), `step` (`n`, a decimal string), `clear`; from spec 0.16.0 also `clear_outside` (`x0`…`y1`), `rotate_rect` (`x0`…`y1`, `clockwise`, and `expect`: the new rectangle), `flip_rect` (`x0`…`y1`, `horizontal`), `advance_selection` and `advance_outside` (`x0`…`y1`, `n`), `set_generation` (`n`), and the query `bounding_box_in` (`x0`…`y1` as decimal strings; `expect`: the box as four decimal strings, or null) | the final state; an op with `error: true` must raise and change nothing |
| `snapshots` (spec 0.16.0) | `rule`, then `ops` in order on an empty universe: every `edit` op, and `snapshot` (`name`), `release` (`name`), `restore` (`name`; `expect`: the state, pinned as above), `read` (`input`, a file of the case read with `read_snapshot`; `name` for its snapshot and `frames` for its frames' names; `expect`: `format`, `rule`, `metadata` and `step`, a decimal string or null) and `measure` (`names`; `expect`: `universe_nodes`, `added` and `nodes`, as integers) | the final state; an op with `error: true` must raise and change nothing, and a `read` never changes the universe's state or rule |

Runners are strict: an unknown key, kind, or `spec_version` fails the case.

## Oracles (implementation tests)

- Against the dense engine: a soup run here and on a [lifelike](lifelike.md) grid with
  `dead` boundary agree cell for cell for as long as the pattern stays clear of the grid's
  edge, for any rule without B0.
- The R-pentomino has population 116 from generation 1103 on (six gliders escape); acorn
  has 633 from generation 5206.
- A glider (`bo$2bo$3o!`) moves one cell right and one down every 4 generations, so after
  generation 4m it has moved (m, m) — past 64-bit coordinates at m = 2⁶².
- The same run under budgets of 10 MiB and 500 MiB ends in identical cells.
