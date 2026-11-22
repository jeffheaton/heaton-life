# Life-like cellular automata

Conformance tier: **bit-exact**. Vectors: [`vectors/lifelike/`](../vectors/lifelike/);
History rules [`vectors/lifelike-history/`](../vectors/lifelike-history/); Super rules
[`vectors/lifelike-super/`](../vectors/lifelike-super/).

## State

- 2-D grid of cells with values `0` (dead) or `1` (alive), stored as unsigned bytes. Under
  a [History rule](history.md) a cell is any of its seven states, 0–6, and under a
  [Super rule](super.md) any of its 26, 0–25.
- Shape `(height, width)`, row-major, origin top-left, index `i = y * width + x`.

## Gather

Each cell's neighborhood index ([rules.md](rules.md#the-transition-table)): the weights
of the live cells in its 3 × 3 block, the cell included, summed in integer arithmetic.

The block is read from the grid's [halo](topology.md#the-halo) of radius 1, so the
cells past an edge are the ones the grid's [topology](topology.md) puts there:

- `torus` (default): indices wrap in both axes, shifted along one if the torus has a
  `shift`.
- `dead` (the plane): cells outside the grid count as 0.
- `klein`, `cross` and `sphere`: the Klein bottle, the cross-surface and the sphere
  (square grids only).

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

B0 rules run as written: on a torus (or any topology but the plane) every dead cell
without live neighbors is born at once, and with `dead` boundaries the cells outside the
grid stay dead.

A [History rule](history.md) (`B3/S23History`, any rule with the `History` variant) runs
here too, on every topology: the halo copies the states, the base rule's table is read at
the index of the block's on cells (the odd states), and history.md's table gives each
cell's next state. Its `soup`, `blob` and `single` are the base rule's, states 0 and 1;
`array` and set states take 0–6. A [Super rule](super.md) (`B3/S23Super`) runs the same
way, super.md's evolution giving each cell's next state, and takes states 0–25.

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

`boundary` is any of the [topologies](topology.md#the-topologies): `torus`, `dead`,
`klein`, `cross` or `sphere`. A torus or a Klein bottle may also carry `shift` (an
integer) and `axis` (`x` or `y`); absent, they are 0 and `x`, and a vector's params leave
them out at those values.

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
A world saves with its topology as the rule's [bounded-grid
suffix](topology.md#the-bounded-grid-suffix) (`rule = B3/S23:K64*,48`), and a file with
one opens as that world ([formats.md](formats.md#bounded-grids)).

## Vector encoding

State PNGs are 8-bit grayscale, pixel = `state * 255`. Runs of History rules live in
`vectors/lifelike-history/`, whose PNGs hold the state itself ([history.md](history.md#vector-encoding)),
and runs of Super rules in `vectors/lifelike-super/`, likewise ([super.md](super.md#vector-encoding)).

## Oracles (implementation tests)

- Glider translates by exactly one diagonal cell every 4 generations; on a 16×16 torus it
  returns to its starting cells at generation 64.
- On a torus with a shift of `s` along x, a glider crossing the bottom edge comes back
  across the top one `s` columns over; on a Klein bottle twisted along x, a glider heading
  down and right comes back across the top mirrored, heading down and left.
- Blinker has period 2; block is a still life.
- An outer-totalistic rule's table and the count formula above give the same next state
  for all 512 indices.
