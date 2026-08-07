# Life-like cellular automata

Conformance tier: **bit-exact**. Vectors: [`vectors/lifelike/`](../vectors/lifelike/).

## State

- 2-D grid of cells with values `0` (dead) or `1` (alive), stored as unsigned bytes.
- Shape `(height, width)`, row-major, origin top-left, index `i = y * width + x`.

## Gather

Sum of the 8 Moore neighbors (integer arithmetic).

Boundary modes:
- `torus` (default): indices wrap in both axes.
- `dead`: cells outside the grid count as 0.

## Respond + Integrate

Synchronous replacement from the rulestring `B<digits>/S<digits>`:

```
next = 1  if state == 0 and count ∈ B
next = 1  if state == 1 and count ∈ S
next = 0  otherwise
```

Rulestrings are case/whitespace-insensitive; canonical form is uppercase with sorted digits
(`B3/S23`). An empty side is legal (`B2/S` = Seeds). Digits are 0–8. Named presets
(life, highlife, seeds, daynight, replicator, maze, diamoeba) are implementation conveniences,
not part of the wire format — params always carry the canonical rulestring.

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
is the supported pattern interchange format.

## Vector encoding

State PNGs are 8-bit grayscale, pixel = `state * 255`.

## Oracles (implementation tests)

- Glider translates by exactly one diagonal cell every 4 generations; on a 16×16 torus it
  returns to its starting cells at generation 64.
- Blinker has period 2; block is a still life.
