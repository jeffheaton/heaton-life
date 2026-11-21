# Life-like cellular automata

Conformance tier: **bit-exact**. Vectors: [`vectors/lifelike/`](../vectors/lifelike/).

## State

- 2-D grid of cells with values `0` (dead) or `1` (alive), stored as unsigned bytes.
- Shape `(height, width)`, row-major, origin top-left, index `i = y * width + x`.

## Gather

Each cell's neighborhood index ([rules.md](rules.md#the-transition-table)): the weights
of the live cells in its 3 × 3 block, the cell included, summed in integer arithmetic.

Boundary modes:
- `torus` (default): indices wrap in both axes.
- `dead`: cells outside the grid count as 0.

## Respond + Integrate

Synchronous replacement through the rule's table: `next = table[index]` for every cell
at once.

The rule is any Life-like rule ([rules.md](rules.md)): outer-totalistic `B…/S…`
(`B3/S23`, `B2/S` = Seeds), isotropic non-totalistic (`B3/S2-i34q`), any table as a `MAP`
string, and hexagonal (`H`) and von Neumann (`V`) rules. For an outer-totalistic rule the
table gives the familiar

```
next = 1  if state == 0 and count ∈ B
next = 1  if state == 1 and count ∈ S
next = 0  otherwise
```

where count is the number of live neighbors. Params always carry the canonical rule
string; preset names (life, highlife, seeds, daynight, replicator, maze, diamoeba) are
implementation conveniences, not part of the wire format.

B0 rules run as written: on a torus every dead cell without live neighbors is born at
once, and with `dead` boundaries the cells outside the grid stay dead.

## Parameters

```json
{
  "rule": "B3/S23",
  "width": 256,
  "height": 256,
  "init": "soup",
  "density": 0.35,
  "seed": 0,
  "boundary": "torus"
}
```

`init` ∈ `soup | blob | single | array` (`array` means the initial state is supplied
out-of-band; in vectors it is the step-0 PNG).

## Initialization

All strategies use [PCG32](rng.md) with `seq = 0` and consume exactly `width * height`
draws in row-major order (even for cells a mask later discards).

- **soup**: cell alive ⟺ `draw < floor(density * 2³²)`.
- **blob**: soup masked to a centered disk: alive ⟺ draw passes **and**
  `(x - width//2)² + (y - height//2)² ≤ (radius · min(width, height))²`, default `radius = 0.25`.
- **single**: one live cell at `(width//2, height//2)`; consumes no draws.

## Pattern I/O

Two-state RLE (`b`/`o`/`$`/`!`, run counts, `#` comments, `x = …, y = …, rule = …` header)
is the supported pattern interchange format; a header naming any Life-like rule marks the
file two-state ([patterns.md](patterns.md#rle-text-encoding-life-like-wireworld-cyclic)).

## Vector encoding

State PNGs are 8-bit grayscale, pixel = `state * 255`.

## Oracles (implementation tests)

- Glider translates by exactly one diagonal cell every 4 generations; on a 16×16 torus it
  returns to its starting cells at generation 64.
- Blinker has period 2; block is a still life.
- An outer-totalistic rule's table and the count formula above give the same next state
  for all 512 indices.
