# Fractals: escape-time fields + Newton basins

Conformance tier: **bit-exact** on integer outputs (iteration counts, root indices).
Vectors: [`vectors/mandelbrot/`](../vectors/mandelbrot/), [`vectors/julia/`](../vectors/julia/),
[`vectors/burning-ship/`](../vectors/burning-ship/), [`vectors/newton/`](../vectors/newton/).
Deep-zoom architecture (tiers, perturbation, rebasing): [deep-zoom.md](deep-zoom.md).

## Pixel mapping (all families)

- `span_x = 4 / 10^zoom_log10`; pixel scale `ps = span_x / width`; square pixels.
- **Computed as** `ps = (4.0 / width) · pow10(−zoom_log10)` — one float64
  division, one deterministic power ([pow10.md](pow10.md)), one float64
  multiply. The historical expression `10^(log10(4/width) − zoom_log10)` is
  **forbidden**: its two libm calls made the bit-exact tier silently
  platform-dependent at fractional zooms (Windows UCRT vs macOS libm differ in
  the last ulp of `pow` — and numpy's vendored routines differ from both),
  which is a spec bug this formulation fixes (2026-08-21;
  `vectors/burning-ship/home-64` and `vectors/mandelbrot/deep-zoom14-48`
  iterations were regenerated to the deterministic values — the old chain
  wasn't even exact at integer zooms. `newton/z3-64` and the ε-tier renders
  survived the ulp shift unchanged).
- Pixel (row i, col j), row-major, origin top-left:
  `re = center_re + (j + 0.5 − width/2)·ps`, `im = center_im − (i + 0.5 − height/2)·ps`
  (imaginary axis points up).
- T0 computes absolute coordinates in float64, from the center's float64
  projection ([deep-zoom.md](deep-zoom.md#viewport-contract-lands-in-core-on-day-one));
  T1 computes only the offsets in float64 and keeps the center in the reference orbit
  — or an [off-center reference](deep-zoom.md#off-center-reference), whose orbit a pixel
  then follows from `δc = fl(round64(C − R) + offset)`.

## Counts convention

`counts[i] = n`, the 1-based iteration at which |z| first exceeds `escape_radius`
(default 1000); `−1` if it never does within `max_iter`. A field refuses an
`escape_radius` whose square is not a finite double (past about `1.34e154`, or NaN):
`|z|² > R²` could never fire, and every count would read `−1`. Smooth (presentation only):
`mu = n + 1 − log2(log|z| / log R)`, then per-frame contrast stretching between the
1st/99th escaped percentiles for display — deep frames cluster counts near
`max_iter`, and an absolute mapping would render monochrome. `counts` is the
conformance output, and, for escape-time families, the `status` of each count
(below). Per-frame stretching is one way to color; [fractal-color.md](fractal-color.md)
has the others, which hold still while a view moves.

## Interior shortcuts (T0)

Two ways a T0 pixel is shown to be interior without running out its budget. Both are
**output-neutral**: every count and smooth value is exactly what the plain loop gives
(`−1` and `0`), and every existing vector regenerates byte for byte. They only save
work — a lot of it where a frame is mostly interior. Measured in C# at 512², where the
software fma makes every iteration dear: the Mandelbrot home view 4.3×, a view inside
the cardioid 35×, a period-3 minibrot 2.6×, the rabbit Julia 19×, the Burning Ship
home view 1.8×, and an escape-heavy Seahorse frame unchanged.

- **Cardioid and bulb (Mandelbrot), when `escape_radius ≥ 2`.** Before iterating, a
  pixel whose float64 `c` (the value T0 iterates) satisfies, in plain float64 and this
  operation order,

  ```
  xq = x − 0.25;  q = xq·xq + y·y
  q·(q + xq) < 0.25·(y·y) − 1e-12      (main cardioid)
  (x + 1.0)·(x + 1.0) + y·y < 0.0625 − 1e-12      (period-2 bulb)
  ```

  is interior. The margin dwarfs the test's own rounding (terms of order 1, error of
  order 1e-16), so a flagged point is inside by the exact inequality, and an interior
  point's orbit converges and never leaves `|z| ≤ 2`. Under a smaller radius it can
  cross the escape test (the bulb's orbits pass `|z| ≈ 1.27`), so there the test is
  skipped and every pixel iterates.
- **Exact cycles (Mandelbrot, Julia, Burning Ship).** After the escape test at
  iteration `n` fails, a pixel whose `z_n` equals — IEEE `==` on both parts — the state
  saved at the last power-of-two iteration is interior: the iteration is a
  deterministic function of the float64 state, so a repeated state repeats forever. Then
  `z_n` is saved when `n` is a power of two (Brent's schedule: compare every iteration,
  save at `n = 1, 2, 4, …`). Value equality, not bit equality: states that differ only
  in the sign of a zero evolve identically in magnitude. The cost is one comparison per
  iteration: none measurable in C#; in NumPy, where the saved states are compacted
  with the live pixels, about a third on a frame where nearly every pixel escapes and a
  few percent on a mixed one.
- **T1 proves nothing** this way: a perturbed pixel's state includes its orbit index,
  which only grows unless the pixel rebases. Periodicity-bounded reference orbits are
  future work.

## Status

`status[i]` says how `counts[i]` was decided — an int8 in the ports, an `int32` in the
vectors:

| status | meaning | count |
|---|---|---|
| 0 | escaped | `n > 0` |
| 1 | exhausted: `max_iter` reached with nothing proved — more might escape | `−1` |
| 2 | inside the main cardioid or period-2 bulb (Mandelbrot, T0) | `−1` |
| 3 | an exact cycle (T0) | `−1` |

At T1 it is 0 or 1. A host tells "needs more iterations" (1) from "interior" (2, 3).
Python `counts_and_status`; C# `CountsAndStatus` (`PixelStatus`). Bit-exact: the
shortcuts are deterministic, so both ports prove the same pixels.

## Iteration policy

How many iterations a frame deserves is a host's choice, **versioned apart from the
counts** (policy version 1): changing it changes which `max_iter` a host asks for,
never what a given `max_iter` renders. Integer and pinned float arithmetic only, no
libm `pow`:

- `auto_max_iter(z) = min(400 + round(200 · max(0, z)), 2³¹ − 1)`, rounding half to
  even — the depth ramp. The product `200 · max(0, z)` is one float64 multiply; from
  `2³¹` up the result is `2³¹ − 1` without rounding (it saturates near `z ≈ 1.07e7`).
  A zoom that is not finite is an error.
- `need_from_counts(counts)` = the nearest-rank 99.9th percentile of the positive
  counts: sort them, take the one at 1-based rank `⌈999·n / 1000⌉` computed in
  integers; 0 when nothing escaped.
- `suggest_max_iter(z, counts) = min(max(auto_max_iter(z), 2 · need), 2³¹ − 1)`.

Python `heaton_life.fractal.policy`; C# `IterationPolicy`.

## Distance estimate

Mandelbrot and Julia can also report, for each escaped pixel, an estimate of its
distance to the set's boundary **in pixels of the frame** (Heaton Fractal's `DE_px`):

```
DE = |z|·ln|z| / |d|,    d = ps·dz/dc (Mandelbrot),  d = ps·dz/dz₀ (Julia)
```

where `ps` is the frame's pixel scale (Pixel mapping). There is no factor of 2: the true
distance lies between `DE/2` and `2·DE`. Carrying `ps` inside the derivative keeps it in
range at depth, where `dz/dc` itself would overflow.

**Derivative.** Each iteration updates `d` from the **pre-square** `z`, before `z` is
updated, in real component form — plain float64 operations in this order, no fma
(NumPy runs it on real arrays, which never contract):

```
t_r = 2.0·(zr·dr − zi·di) + ps        Mandelbrot;  Julia: 2.0·(zr·dr − zi·di), no addition
t_i = 2.0·(zr·di + zi·dr)
(dr, di) ← (t_r, t_i)
```

It starts at `(0, 0)` for Mandelbrot and `(ps, 0)` for Julia. At T0 the pre-square `z` is
the loop's own (`0` for Mandelbrot, the pixel for Julia). At T1 it is the
`z = fl(Z[m] + δ)` the previous iteration reconstructed — `fl(Z₀ + δ₀)` before the
first — and a rebase, which changes `δ`, `m` and the orbit followed, changes neither `z`
nor `d` (an [off-center reference](deep-zoom.md#off-center-reference) likewise).

**Estimate.** At escape (count `n > 0`, `z = zₙ`, `d = dₙ`):

```
m2 = zr·zr + zi·zi
a  = max(|dr|, |di|)
a = 0            → DE = +∞       a critical point: the estimate diverges
a not finite     → DE = 0        the derivative overflowed: on the boundary
otherwise:
    s  = 2^600 if a < 2^−400,  2^−600 if a > 2^400,  else 1
    sr = dr·s;  si = di·s
    DE = ((sqrt(m2) · (0.5·log(m2))) / sqrt(sr·sr + si·si)) · s
```

The scaling is exact (a power of two) and keeps the squares out of the subnormal range:
at T1 `|d|` falls below `1e-154` for pixels far from the set in pixel units (zooms past
about 155). There plain squares lose precision, and below about `1.6e-162` they read 0
and give `DE = +∞`, a false critical point. `DE` itself may round to `+∞`. A pixel that did not escape (exhausted, cardioid or bulb, cycle) has
`DE = NaN` — no value.

**Domain.** Only with `2 ≤ escape_radius ≤ 1e64` — `ln|z|` must be positive and `m2`
finite; asking outside it is an error. The estimate is asymptotic in `|z|` (a small
radius distorts it: at `R = 10` the tip below is off by about 1%). At the default
`R = 1000`, `c = −2 − δ` with `δ ≤ 1e-3` reads `DE·ps = 2δ` within 0.1%; `2δ` is itself
the tip's small-`δ` limit, so `δ = 0.01` reads 0.6% low.

**Tier.** ε, relative: `|got − want| ≤ ε·|want|` with ε = `1e-12`, and a `NaN`, `0` or
`±∞` must match exactly. The derivative and the scaling are plain IEEE operations in a
fixed order, so the ports agree on `d` bit for bit; only `log` may differ in its last
ulps. (Accuracy against the *true* distance is another matter: float64 error grows near
the boundary roughly as `1/DE`.)

Burning Ship (not analytic) and Newton (not escape time) have none; asking is an error.
Python `fields(size, viewport, distance=True)`; C# `Fields(…, distance: buffer)` and
`SupportsDistance`. The distance loop is a separate code path, taken only when a distance
buffer is asked for; its counts, statuses and smooth values are exactly the other paths'.
Coloring with it: [fractal-color.md](fractal-color.md).

## Family updates

- **Mandelbrot**: `z ← z² + c`, `z₀ = 0`, `c` = pixel.
- **Julia**: `z ← z² + c`, `c` fixed, `z₀` = pixel. Perturbation uses the center's
  orbit (or the off-center reference's) under the same `c`; `δ₀` = pixel offset (from
  that point), no `δc` term. Rebased pixels restart on the critical orbit (`z₀ = 0`),
  never on the reference orbit
  ([deep-zoom.md](deep-zoom.md#rebasing-single-reference-no-glitches)).
- **Burning Ship**: `x' = x² − y² + cx`, `y' = 2|x||y| + cy`. Perturbation in
  component form with `diffabs(X, d) = |X+d| − |X|` evaluated by case analysis
  (never by subtraction).
- **Newton** (float64 only, zoom ≤ 1e12): `z ← z − (z^d − 1)/(d·z^(d−1))`;
  converged when `|z^d − 1| < 1e-9`; outputs `roots` (nearest-root index, −1 if
  unconverged) and `iterations` (1-based, −1 if unconverged). Roots are
  `exp(2πik/d)`, k = 0..d−1.

## BLA (Mandelbrot, T1 and T2, opt-in)

`Mandelbrot(bla=True)` skips whole spans of the reference orbit where a pixel follows it
linearly: [deep-zoom.md](deep-zoom.md#bla-bivariate-linear-approximation-mandelbrot-opt-in),
and past zoom 290 [BLA at T2](deep-zoom.md#bla-at-t2). Counts differ from BLA-off only
on pixels the float64 orbit and arithmetic cannot resolve; BLA cases are bit-exact among
themselves.

## Tiering (automatic)

| Tier | zoom_log10 | Engine |
|---|---|---|
| T0 | ≤ 12 | direct float64 |
| T1 | ≤ 290 | perturbation + rebasing, reference index clamped to the last orbit sample |
| T2 | ≤ 9000 | perturbation in rescaled float64, floatexp at small reference samples ([deep-zoom.md](deep-zoom.md#t2-perturbation-past-1e290)); Mandelbrot and Julia |

A host can ask which tier a zoom selects before rendering (C# `FractalEngine.TierOf`,
Python `tier_of`; a zoom that is not finite raises), and how deep a family goes
(`MaxZoomLog10` / `max_zoom_log10`: 1e9000 for Mandelbrot and Julia, 1e290 for the
Burning Ship, 1e12 for Newton). At T2 statuses are escaped or exhausted, and the distance
estimate carries its derivative with its own exponent (deep-zoom.md "T2").

At T2 the iteration policy's `auto_max_iter` is a floor, not an estimate: frames there
need budgets near their minibrots' periods (hundreds of thousands to millions). A host
that sees a frame come back all exhausted raises the budget (doubling, say) until
something escapes.

Determinism note: T1 counts are bit-stable given the reference orbit, and the orbit
itself is pinned — both ports run one fixed-point arithmetic and produce
**identical** orbits at any length ([deep-zoom.md](deep-zoom.md#reference-orbit-the-only-high-precision-computation)). In chaotic boundary regions T0 and T1 legitimately disagree on
a few percent of pixels — by exactly as much as T0 disagrees with itself under a
1-ulp input perturbation. Conformance therefore always compares like against like:
the vector's tier is whatever the viewport's zoom selects.

## Parallel rendering

Implementations may split the per-pixel loops across worker threads, keyed by an
explicit `workers` knob (C#: the `workers` constructor argument, default 1 =
serial). The contract: **output is bit-identical for every worker count and
schedule.** This holds by construction — every pixel's computation is
independent, workers own disjoint rows of the output buffers, and no RNG is
drawn during rendering. Serial stages stay serial: the T1 reference orbit is
computed once before pixels fan out, and `NormalizeRender`'s percentile stretch
runs on the finished `mu` buffer. Conformance suites replay the same vectors at
`workers = 1` and `workers > 1`; both must match byte-for-byte. Python renders
whole-array through NumPy and takes no knob — parallelism is a host-side
performance detail, never an algorithm change.

### Other host knobs

The C# port has three more knobs of the same kind, for interactive hosts; each observes
or stops the work and **never changes a completed frame's output**:

- **Progress** (`RenderProgress`): rows completed, and — for a T1 frame whose orbit is
  not cached — a reference-orbit phase counting iterations first (Julia runs two, its
  reference orbit and then the critical orbit). Each render resets it, so one object can
  be reused frame after frame.
- **Cancellation** (`CancellationToken`): checked before each row, every 4,096 orbit
  iterations up to 1,024 bits of precision (proportionally more often above, down to
  every iteration of a T2 Julia orbit), and every 2^16 passes of a T2 pixel's loop (a
  plain iteration or a BLA skip is one pass). A canceled render throws `OperationCanceledException` with its output
  buffers partly written; a canceled orbit is never cached.
- **Caller buffers**: counts and raw smooth values `μ` (before normalization; 0 where
  interior) into the host's arrays, and the normalization into another pair — nothing
  allocated per pixel, per iteration, or in proportion to the frame or the orbit (a
  few small objects per call remain, more with `workers > 1`), and a host can recolor
  without re-rendering. Python's `counts_and_smooth` returns the same `μ`.

## Vector schema (one-shot renders; no time axis)

```json
{
  "spec_version": "0.2.0", "family": "mandelbrot", "tier": "bit-exact",
  "params": { "max_iter": 500, "escape_radius": 1000.0 },
  "viewport": { "center_re": "-0.5", "center_im": "0.0", "zoom_log10": 0.0 },
  "size": [64, 64],
  "outputs": [ { "kind": "iterations", "file": "iterations.i32", "shape": [64, 64] } ],
  "reference_orbit": { "file": "orbit.c128", "length": 5001 }
}
```

- `size` = `[width, height]` in pixels; each output's `shape` = `[height, width]`
  (rows, cols; C order) — `vectors/mandelbrot/seahorse-zoom6-48x32` is non-square.
- `.i32` = raw little-endian int32, C order.
- `.c128` = raw little-endian complex128 (re, im float64 pairs) — present on
  deep-zoom cases; regeneration must reproduce it bit-for-bit, and implementations
  without a bignum stack may consume it directly.
- Deep Julia cases also carry `"critical_orbit": { "file": "critical.c128", "length": N }`,
  the orbit rebased pixels restart on ([deep-zoom.md](deep-zoom.md#rebasing-single-reference-no-glitches)).
  A replay must use both stored orbits.
- `source` (optional string): attribution for a third-party location; runners accept
  and ignore it.
- The viewport may carry `reference_re` / `reference_im`, an
  [off-center reference](deep-zoom.md#off-center-reference); the stored reference orbit
  is then the reference's, and a replay must offset every pixel by `round64(C − R)`.
- An escape-time case may add a `status` output (`status.i32`, values 0–3, see
  [Status](#status)); such cases carry `"spec_version": "0.6.0"` or later.
- A Mandelbrot or Julia case may add a `distance` output (`distance.f64`, raw
  little-endian float64, see [Distance estimate](#distance-estimate)) carrying
  `"relative_epsilon": 1e-12`; such cases carry `"spec_version": "0.7.0"`. The case's
  `tier` describes its integer outputs; an output with `relative_epsilon` is compared as
  that section says. A runner computes the case's counts through the distance path too.
- A Mandelbrot case may set `"bla": true` in its params ([deep-zoom.md](deep-zoom.md#bla-bivariate-linear-approximation-mandelbrot-opt-in));
  it then carries a `bla_applications` output (`bla_applications.i32`, each pixel's
  number of skips), whose total must be positive — a BLA case that never engages pins
  nothing — and `"spec_version": "0.8.0"` or later. It may add a `bla_table` output
  (`bla_table.f64`, `"entries"`: the entries per level): the table built from the stored
  orbit and the frame's `dc_bound`, level by level `ar, ai, br, bi, r`, compared value for
  value with every NaN equal to every NaN — build differences flip table bits on every
  frame but counts only on rare pixels.
- A T2 BLA case ([deep-zoom.md](deep-zoom.md#bla-at-t2)) carries
  `"dc_bound_exponent"` at the top level: the integer `k` of the frame's dc bound `2^k`, or
  `null` when every pixel delta is zero. It is required exactly when `params.bla` is true
  and `zoom_log10` is past 290, and a runner computes it and compares. Such a case may add
  a `bla_table_x` output (`bla_table_x.f64`, `"entries"` per level): the T2 table built
  from the frame's own orbit, small samples and floatexp dc bound, level by level the
  coefficients' `ar, ai, br, bi` (each the `hi` of its double-double), the radii's
  mantissas, then their exponents (exact as float64), compared value for value with every
  NaN equal to every NaN (an overflowed dead entry stores NaN, whose sign varies by
  platform).
- A T2 case ([deep-zoom.md](deep-zoom.md#t2-perturbation-past-1e290), zoom past 290)
  ships no orbit file: its orbits run to tens of thousands of bits. It carries
  `"reference_small"` (and, for Julia, `"critical_small"`) =
  `{ "length": N, "sha256": "…", "rows": [[index, re mantissa bits, re exponent, im mantissa bits, im exponent], …] }`:
  the orbit's length, the SHA-256 of its samples as little-endian complex128, and its
  small samples in floatexp. A runner regenerates each orbit at the family's orbit zoom
  (twice the frame's for Julia) and checks all three, then renders the case itself.
  Such cases carry `"spec_version": "0.10.0"`, and a Julia case's stored orbits at any
  tier are its orbits at twice the frame's zoom.
- Cases written from 2026-09-23 carry `"spec_version": "0.3.0"`, those with a reference
  `"0.4.0"` or later, those with a status `"0.6.0"` or later, those with a distance
  `"0.7.0"` or later, those with BLA `"0.8.0"`, those at T2 `"0.10.0"` (earlier ones keep `0.2.0`; [vectors/README.md](../vectors/README.md) lists
  what each adds). Versions compare numerically, component by component. Runners are
  strict: a key, output kind, codec or version they do not know fails the case.
