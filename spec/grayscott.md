# Gray-Scott reaction-diffusion

Conformance tier: **ε-tolerance** (ε = 1e-9). Vectors: [`vectors/grayscott/`](../vectors/grayscott/).
Same-language replay is exact; the ε absorbs cross-language summation differences. The
update is pure arithmetic (no transcendentals), so an implementation that follows the
spec'd operation order should in practice match bit-for-bit.

## State

Two float64 fields on a torus, shape `(2, height, width)`: `state[0] = U` (substrate),
`state[1] = V` (activator). Row-major.

## Update (explicit Euler, one step)

Operation order is part of the spec:

1. `lap_U`, `lap_V`: 5-point Laplacian, computed as `((N + S) + W) + E − 4·C`.
2. `uvv = U · V · V` (from the *old* fields).
3. `U += dt · (du · lap_U − uvv + feed · (1 − U))`
4. `V += dt · (dv · lap_V + uvv − (feed + kill) · V)`  — note V is still the old V here.

## Parameters

```json
{ "du": 0.16, "dv": 0.08, "feed": 0.0545, "kill": 0.062, "dt": 1.0,
  "width": 256, "height": 256, "init": "spots", "spots": 20, "seed": 0 }
```

The (feed, kill) plane is the phase diagram. Named presets (verified pattern-forming
with these du/dv/dt): Mitosis (.0367/.0649), Coral (.0545/.062), Worms (.046/.063),
Maze (.029/.057), Solitons (.03/.062), Chaos (.026/.051), U-Skate (.062/.0609).

## Initialization

Background `U = 1, V = 0` everywhere, then seed boxes with `U = 0.5, V = 0.25`:
7×7 squares clipped at grid edges (no wrap).

- **spots**: [PCG32](rng.md) seq 0; per spot two draws: `cx = draw % width`,
  `cy = draw % height`.
- **center**: one box at `(width//2, height//2)`; no draws.

## Vector encoding

Raw little-endian float64 (`.f64`), C order; the checkpoint entry carries `"shape"`.

## Oracles

- `U=1, V=0` is a bitwise-exact fixed point.
- A centered seed on an odd-sized grid evolves with 4-fold symmetry (to ~1e-12).
- Mitosis forms structure: `std(V) > 0.01` well before step 1000.
