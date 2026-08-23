# Elementary cellular automata

Conformance tier: **bit-exact**. Vectors: [`vectors/elementary/`](../vectors/elementary/).

## State

1-D tape of `width` cells, values `0`/`1`, unsigned bytes. The 2-D space-time diagram is
presentation (the frame), not state; `height` only sizes that diagram.

A host that *persists a world* must keep the diagram with the tape, though: it is the
record of the steps already taken and cannot be rebuilt from the tape, so a world
restored from its tape alone reopens with a blank diagram. The .NET `StateCodec`
therefore stores `tape ‖ diagram` for elementary (and still loads tape-only saves);
conformance vectors compare tapes only, as below.

## Gather / Respond / Integrate

For each cell, form `index = left<<2 | center<<1 | right`; the next value is bit `index`
of the Wolfram rule number (0–255). Synchronous replacement.

Boundary: `torus` (wrap, default) or `dead` (outside = 0).

## Parameters

```json
{ "rule": 30, "width": 256, "height": 256, "init": "single",
  "density": 0.5, "seed": 0, "boundary": "torus" }
```

## Initialization

- **single**: one live cell at `width // 2`; consumes no RNG draws.
- **soup**: [PCG32](rng.md) seq 0, `width` draws left-to-right, alive ⟺
  `draw < floor(density * 2³²)`.

## Vector encoding

Tapes are stored as 1×width grayscale PNGs, pixel = `cell * 255`. Vectors compare tapes,
never diagrams.

## Oracles

- Rule 90 computes `left XOR right` exactly.
- Rule 110 from a single cell: after one step, cells `c-1` and `c` are alive, `c+1` is not.
- Rule 254 from a single cell with dead boundary fills the tape in `width//2` steps.
