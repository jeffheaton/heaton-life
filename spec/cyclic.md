# Cyclic cellular automata (Griffeath)

Conformance tier: **bit-exact**. Vectors: [`vectors/cyclic/`](../vectors/cyclic/).

## State

2-D grid, values in `[0, states)`, unsigned bytes, shape `(height, width)`, row-major.
Boundary is always toroidal.

## Gather / Respond / Integrate

Let `succ = (cell + 1) mod states`. Count the neighbors within the neighborhood whose
value equals `succ`; if the count is ≥ `threshold`, the cell becomes `succ`, else it is
unchanged. Synchronous replacement.

Neighborhoods (excluding the origin):
- `moore`: all offsets with `max(|dy|, |dx|) ≤ reach`
- `vonneumann`: all offsets with `|dy| + |dx| ≤ reach`

## Parameters

```json
{ "states": 14, "threshold": 1, "reach": 1, "neighborhood": "moore",
  "width": 256, "height": 256, "init": "soup", "seed": 0 }
```

Ranges: states 2–24, threshold 1–48, reach 1–3.

## Initialization

**soup**: PCG32 seq 0, `width*height` draws row-major, `cell = draw mod states`.
(The modulo bias is negligible and the definition is exact, which is what matters.)

## Vector encoding

Grayscale PNG, pixel = raw state value.

## Oracles

- A uniform grid is a fixed point.
- threshold 1: a single successor neighbor advances the cell; von Neumann excludes diagonals.
- Named presets: Demon spirals (14/1/1/moore), 313 (3/3/3/moore), Amoeba (2/10/3/vonneumann).
