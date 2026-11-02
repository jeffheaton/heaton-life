# HashLife — an unbounded Life universe

Conformance tier: **bit-exact**. Vectors: [`vectors/hashlife/`](../vectors/hashlife/).

The `hashlife` family runs two-state Life-like rules on an unbounded plane with Bill
Gosper's HashLife: a hash-consed quadtree whose nodes memoize their own future. Regular
patterns of trillions of cells fit in memory, and a generation count can be any
non-negative integer. The dense [`lifelike`](lifelike.md) family stays the bounded-grid
engine (torus or dead edges); this page is its unbounded counterpart.

## State

- **Cells.** Every point (x, y) of the integer plane is dead (0) or alive (1); finitely
  many are alive. x grows to the right and y grows downward, as in RLE and Golly.
- **Generation.** A non-negative integer.
- **Rule.** A Life-like rulestring in canonical form ([lifelike.md](lifelike.md),
  "Respond + Integrate"). A rule with `0 ∈ B` (B0) is rejected: births with no live
  neighbors would light the infinite background. (A B0 rule that also has S8 can be run
  as its complement rule; that is a possible later extension.)
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

This is Golly's placement. Golly keeps y pointing up internally and negates it at the
edge, which shifts rows by one: the upper-left cell of the root's SE child is (0, 1). A
[Macrocell](macrocell.md) file therefore lands on the same cells here as in Golly (the
Caterpillar's file puts its top-left cell at (0, 0) in both).

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
  the rule.

**Sub-steps.** Write n in binary. For each set bit j, advance 2^j generations:

1. Expand the root — wrap it in a node twice its size, centered, with empty margins —
   until its level k ≥ max(j + 3, 6) and every live cell lies in the centered square of
   side 2^(k−2) (the union of the root's four innermost great-grandchildren).
2. Replace the root by `result_j(root)`. The pattern grows at most 2^j ≤ 2^(k−3) cells on
   each side, so the result's centered 2^(k−1) square holds all of it.

Full-speed results are cached per node; fixed-step results per node for the current j,
cleared when j changes. Caches never change results. A port may decompose n another way;
only the cells after n generations are observable.

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
  cells, `xor` toggles each cell where `cells` is alive.
- `clear_rect(x0, y0, x1, y1)`: every cell of the inclusive rectangle dies.
- `fill_random(x0, y0, x1, y1, density, seed)`: `set_rect(x0, y0, soup, copy)` with the
  rectangle's soup: [PCG32](rng.md) with seq 0, one draw per cell in row-major order
  (y outer, x inner), alive iff `draw < floor(density · 2³²)`. These are the draws of
  lifelike's `soup` for the same width and height ([lifelike.md](lifelike.md),
  "Initialization"); `density` must lie in [0, 1].
- `clear()`: every cell dies.

Editing never changes the generation. A pattern larger than the box still loads, runs,
renders, and reports; it just can't be edited outside the box.

## Snapshots

`snapshot()` records the cells and the generation in O(1) time and space: it holds the
root node. `restore(snapshot)` returns the universe to it. A snapshot keeps its nodes
alive through garbage collection for as long as the snapshot object lives, and it survives
rule changes (it holds cells, not results). A snapshot belongs to the universe that made
it; restoring it into another is an error.

## Memory

`max_memory_mb` bounds the node store in MiB (2²⁰ bytes): default 500, minimum 10. The
accounting is each port's own estimate of its store (nodes and caches); the process's
whole footprint is larger.

- When the store is full the engine collects garbage, keeping what is reachable from the
  current root and the live snapshots (and, in a port that collects mid-step, work in
  flight). Cached results whose nodes are collected are dropped.
- A sub-step that cannot finish within the budget is retried after collection, then split
  into two half sub-steps, recursively, down to single generations. If one generation
  cannot fit, `step` raises `HashLifeMemoryError` and the universe is unchanged.
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

## Parameters

```json
{
  "rule": "B3/S23",
  "max_memory_mb": 500
}
```

## Pattern I/O

- **[Macrocell](macrocell.md)** (`.mc`, `.mc.gz`) carries any state, of any size, and its
  canonical text is how vectors pin a state. Reading places the root as Golly does.
- **[RLE](patterns.md#rle-in-the-unbounded-universe)** carries patterns inside the editing
  box: `#CXRLE Pos=x,y Gen=n` places the pattern and sets the generation; writing puts that
  line before the canonical RLE of the bounding box.
- Loading by content: gzip bytes or a first line starting with `[M2]` are Macrocell,
  anything else RLE. Saving by extension: `.rle`, `.mc`, `.mc.gz` (gzip of the canonical
  text; the compressed bytes are the compressor's and not pinned).

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
| `view` | `operations`: each names a view function and its inputs (views as `[x, y, mag]`, big integers as strings) | each operation's `expect` |
| `render` | `input`, stepped to `generation`; each frame's `view`, `size` (`[width, height]`), and `mode` | each frame's 8-bit grayscale PNG (compared by decoded pixels; the PNG bytes are the encoder's) |
| `edit` | `rule`, then `ops` in order on an empty universe: `set_cell` (`x`, `y`, `alive`), `set_rect` (`x`, `y`, `mode`, `cells` as rows of `.`/`*`), `clear_rect` (`x0`…`y1`), `fill_random` (`x0`…`y1`, `density`, `seed`), `step` (`n`, a decimal string), `clear` | the final state; an op with `error: true` must raise and change nothing |

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
