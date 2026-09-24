# Discovery: the box period, Newton's nucleus and the atom size (Mandelbrot)

A deep view that shows a minibrot's surroundings also holds its **nucleus** `c₀`: the
center of its main cardioid, where the critical orbit is periodic, `z_p(c₀) = 0` for the
minibrot's **period** `p`. Finding it takes three steps:

1. The **box period test** finds `p` from the view: the first `n` at which the images of
   a square's corners surround 0.
2. **Newton's method** on `z_p(c) = 0` homes in on `c₀`.
3. The **atom size estimate** says how big the minibrot is, which frames it.

Python `heaton_life.fractal.nucleus` (`box_period`, `find_nucleus`), C#
`HeatonLife.NucleusFinder` (`BoxPeriod`, `FindNucleus`). Mandelbrot only: Burning Ship
is not holomorphic, and Julia's nuclei are a different problem.

**Tiers.** Every decision is an integer comparison, so everything the box test and
Newton return is **bit-exact** across ports: the verdict, the stop reason, the counts and
the printed center strings. The size estimate ends in one libm `log10`, so it is **ε**
(relative `1e-12`).

**Snapping to a minibrot** takes both calls. `box_period` runs on the view. If its corners
surrounded 0, `find_nucleus` runs with the box's period and the box's final `radius`.
`found` then means Newton reached a nucleus of that period inside the square the period
came from. It does not always: a nucleus's Newton basin can be much smaller than the
square that detects it.

## Fixed point

Discovery computes in the reference orbit's fixed point ([deep-zoom.md](deep-zoom.md)
"Reference orbit"). A real `x` is the integer `round(x · 2^F)`:

- `mul(a, b) = round(a·b / 2^F)`, ties away from zero; sums are exact.
- `rdiv(n, d) = round(n / d)`, ties away from zero (`d > 0`).
- `rshift(v, k) = round(v / 2^k)`, ties away from zero, symmetric in sign (`k ≥ 0`).
- One orbit step: `X' = mul(X, X) − mul(Y, Y) + Cᵣ`, `Y' = 2·mul(X, Y) + Cᵢ`.
- A center string is parsed exactly and rounded to `F` bits (`parse_fixed`). A double
  converts exactly, rounding ties away from zero if `F` is too small (`from_double`).
- **The radius** `r` is a double: the argument, or `2 · pow10(−zoom_log10)` by default
  (half the frame's width, [fractals.md](fractals.md) "Pixel mapping").
  - It must be finite and positive.
  - `zoom_log10` must lie in [pow10.md](pow10.md)'s domain, `[−300, 300]`, as
    [navigation.md](navigation.md)'s zooms do, whether or not a radius is given: it sets
    the precision, and past that range it would ask for millions of bits.
- **Precision.**
  `bits(center, z, r) = max(working_bits(center, z), 128 − binade(r))`, where
  `working_bits` is the orbit's rule and `binade(r)` is the `k` with `r` in `[2^k, 2^(k+1))`.
  The second term keeps any radius at `2^119` ulps or more, even after 8 halvings.
  With it, `from_double(r, F)` and every halving of it are exact.

## Box period

**`box_period(center_re, center_im, zoom_log10, max_period, radius = none)`** returns a
**`BoxResult`**:

| Field | Meaning |
|---|---|
| `period` | the period, or none |
| `reason` | `surrounded`, `budget` or `escaped` |
| `halvings` | how many times the last square tried was halved |
| `radius` | that square's half-side, `r · 2^−halvings`, as a double |

The box period test is Munafo's and Heiland-Allen's. The polygon a square's four corners
map to under `z_n` stands for the square's image. When it surrounds 0, `z_n` has a root
in the square: a nucleus whose period divides `n`. The first such `n` is the lowest
period in the square. A host passes its frame's iteration budget as `max_period`.

```
F  = bits(center, zoom_log10, r)
C  = the center at F bits
R₀ = from_double(r, F)
for h = 0 … 8:                                    -- the square's halvings
    R = rshift(R₀, h)
    corners c₀…c₃ = C + (−R − iR), (+R − iR), (+R + iR), (−R + iR), each iterated from 0
    for n = 1 … max_period:
        step every corner
        if the corners surround 0:  return (n, surrounded, h)
        if any corner has |X| ≥ 2^(F+16) or |Y| ≥ 2^(F+16):  next h   -- escaped
    return (none, budget, h)
return (none, escaped, 8)
```

**Surround** is crossing parity against the positive real axis, over the closed polygon
`c₀ → c₁ → c₂ → c₃ → c₀`, in integers:

- An edge `a → b` straddles the axis when `(a.y ≥ 0) ≠ (b.y ≥ 0)`. A vertex on the axis
  counts as above, which is the half-open rule.
- It crosses to the right of 0 when `(a.x·b.y − b.x·a.y)·(b.y − a.y) > 0`.
- The corners surround 0 when an odd number of edges cross.

**The halvings.** A corner past `2^16` has escaped, and the four corners no longer stand
for the square's image. The test starts again on a square half the size, about the same
center.

- The surround test runs before the escape test at the same `n`. A corner that has just
  passed 2 still takes part.
- Why halving: a view at zoom `z` shows the surroundings of minibrots near depth `2z` (the
  r² law). Its corners' images reach 2 right around the period. On the measured frames,
  the first square's corners escaped before a surround about half the time. One to three
  halvings found a period, and its nucleus was usually inside the halved square.
- A halving can drop the minibrot the view was built around. The test then returns the
  lowest period in the smaller square.

**Reading a result.**

- `budget`: the square holds no nucleus of period up to `max_period`, or its corners all
  sit in one component's interior.
- `escaped`: every square's corners escaped. The view is outside the set.
- `surrounded`: the four corners say a nucleus of that period is in the square. It is a
  heuristic, because a chord polygon is not the square's image: now and then the
  surround is an artifact, or it skips a lower period. The lowest period in a view is
  also often a nearby nucleus other than the one the view was centered on. Newton
  decides.

## Newton

**`find_nucleus(center_re, center_im, period, zoom_log10, radius = none, max_steps = 64,
max_evaluations = 200, max_escalations = 4)`** returns a **`Nucleus`**. The radius is
Newton's **reach**, and the center is the **origin**.

**Evaluation.** `evaluate(c, p, F)` returns `z_p`, `dz_p/dc` and whether the orbit escaped:

```
X = Y = dR = dI = 0
for n = 1 … p:
    dR, dI = 2·(mul(X, dR) − mul(Y, dI)) + 2^F,  2·(mul(X, dI) + mul(Y, dR))   -- from the pre-step z
    X, Y   = the orbit step
    if |X| > 2^(F+1) or |Y| > 2^(F+1):  escaped; stop        -- a component past 2
```

**One run** at `F`, from a point `c`, with `M = from_double(r, F)` and the origin `O` at
`F`:

```
evaluate(c); evaluations = 1; steps = 0; N = X² + Y²          -- N = |z_p|²·2^2F
loop:
    escaped                           → stop start-escaped
    steps = max_steps                 → stop max-steps
    den = dR² + dI²;  den = 0         → stop zero-derivative
    δR = rdiv((X·dR + Y·dI) << F, den),  δI = rdiv((Y·dR − X·dI) << F, den)   -- z_p / dz_p, rounded once
    s = the least s ≥ 0 with δR² + δI² ≤ M²·4^s;  δ' = (rshift(δR, s), rshift(δI, s))   -- the clamp
    for back = 0 … 24  (only back = 0 once N < 2^(F+8)):          -- the line search
        t = (rshift(δ'R, back), rshift(δ'I, back));  t = (0, 0) → end the search
        evaluations += 1;  evaluate(c − t)
        accept if that orbit did not escape and its N is strictly smaller
    none accepted  → stop floor if δR² + δI² < 2^64, else no-improvement
    c = c − t;  steps += 1
    |cR − OR| > 2M or |cI − OI| > 2M  → stop left-view
    steps ≡ 1 (mod 12):  first = tR² + tI²
    steps ≡ 0 (mod 12) and 4·(tR² + tI²) > first  → stop stagnated
    evaluations ≥ max_evaluations  → stop max-evaluations
```

- The clamp and the line search round twice: a candidate is `rshift(rshift(δ, s), back)`.
- Once `N < 2^(F+8)` (`|z_p| < 2^((8−F)/2)`), the line search tries the full step only.
- `stagnated` works in windows of 12 accepted steps: a window whose last step, squared and
  times 4, exceeds its first gained less than a bit.
- `floor` means Newton's own estimate of the distance to the root is under `2^32` ulps.
  The run went as far as `F` allows. It is the usual end of a run that converged: the
  step rounds to zero, or no longer shrinks `|z_p|`. `no-improvement` is the same failure
  far from a root.
- `left-view` means the walk left the square twice the reach around the view's center.
  This is Kalles Fraktaler's "fail fast if C leaves the target".
- The evaluation cap is checked only after an accepted step. The first line search starts
  at 1 evaluation and can add 25, so a run can use up to `max(max_evaluations, 2) + 24`
  evaluations (26 with a cap of 1).

**Precision.** A minibrot found from a view at zoom `z` lies near depth `2z`, so the first
run uses `F = bits(center, 2·zoom_log10, r)`. After a run that stopped with `floor`:

```
need = bitlen(dR² + dI²) − 2F + 128       -- the depth in bits, plus 128
```

If `need > F`, the last point and the origin are shifted left by `need − F` (exact),
`F = need`, and Newton runs again from that point. The new run starts fresh: 1
evaluation, 0 steps, a new window. This happens at most `max_escalations` times. A run
with any other stop is not a precision problem, and nothing escalates after it.

**Verdict.** At the final `F`, with `K = ⌊(6F + 32)/5⌋` and `depth_bits` as under
Printing:

- `converged`: the last run did not escape, `N < 2^K`, and `F − depth_bits ≥ 64`.
  - `N < 2^K` is `log₂|z_p| < 0.4·(8 − F)`, Heaton Fractal's bar.
  - The last condition asks that `F` place the atom. The bar is relative to `F` alone,
    and at a coarse `F` the grid point nearest the nucleus passes it from billions of
    sizes away (period 42 from −2 at `F = 128`, depth 162 bits). Escalation normally
    leaves 128 bits. A run cut short by a budget, or `max_escalations = 0`, can leave
    fewer.
  - Converged means Newton reached a nucleus of period `p` or of a divisor of it.
- `inside`: `|cR − OR| ≤ M` and `|cI − OI| ≤ M`, so the last point is within the reach of
  the view's center.
- `found = converged ∧ lower_period is none ∧ inside`.

**The final pass.** A converged point's orbit runs once more, `k = 1 … p−1`, in one pass:

- The lower-period screen: Newton on `z_p` also converges to nuclei whose period divides
  `p`. At the first divisor `k` of `p` with `X_k² + Y_k² < 2^K`, the pass stops.
  `lower_period = k`, and the printed center is that nucleus's, so a host can offer it.
- The atom size, below.

The final pass counts no evaluations.

**Printing.**

- `depth_bits = max(bitlen(dR² + dI²) − 2F, 0)`, about `log₂(1/size)`. It is 0 when the
  last run's orbit escaped, because a derivative cut short measures nothing.
- The number of places `P`:
  - A converged point takes the greater of two, plus 8:
    `⌊(depth_bits · 30103 + 99999) / 100000⌋`, the size's places, and
    `max(⌈zoom_log10⌉, 0)`, the view's. That is 8 places past whichever is finer, so a
    shallow nucleus found from a deeper view still prints where the view can see it.
  - Any other point takes the view's places plus 8. Its derivative says nothing about a
    size: an orbit that never escapes can ask for tens of thousands of places.
- The center is `v / 2^F` printed at `P` places: rounded half away from zero and written
  positionally ([navigation.md](navigation.md) "Printing"). `F` covers the digits:
  `F ≥ working_bits(center, 2·zoom_log10)`.

## Atom size

`size_log10` is `log10` of `1 / |b·l²|`, with `l = ∏_{k=1}^{p−1} 2z_k` and
`b = Σ_{k=0}^{p−1} 1/l_k` (`l₀ = 1`). This is the Hunt–Ott estimate, in Heiland-Allen's
form. It accumulates in the final pass:

```
l = 1, b = 1
for k = 1 … p−1:
    z = z_k as an ext;  z = 0 → the size is NaN
    l = (l · z) · 2
    b = b + 1/l
v = (b · l) · l;  v = 0 → the size is NaN
size_log10 = −(½ · log10(v.re² + v.im²) + v.e · 0.30102999566398120) + 0
```

- For `p = 1` the loop is empty and the size is `+0`. The `+ 0` turns `−0` into `+0`.
- The two NaN cases need a `z_k` that is exactly 0, which a nucleus of period `p` does
  not have.
- The size is NaN unless the point converged and the screen found no lower period.

An **ext** is `(re + i·im)·2^e`: two doubles and an integer exponent, with
`max(|re|, |im|)` in `[1, 2)`, or both 0. Every operation is IEEE `+ − × ÷` in the shapes
below. Every rescaling is by an exact power of two, and every rescaled value stays in the
normal range.

- **Normalize** `(re, im, e)`: with `k = binade(max(|re|, |im|))`, the result is
  `(re·2^−k, im·2^−k, e + k)`. Both 0 gives `(0, 0, 0)`.
- **From fixed** `(X, Y)`, never through a double of `X` (which overflows past `F = 1024`
  and underflows at deep orbits):
  - Each part is `m·2^q`: `|X|` is rounded to 53 significant bits, ties to even, and
    `m` has `|m|` in `[1, 2)` and `X`'s sign.
  - A zero part takes the other part's exponent.
  - Otherwise `e = max(q_X, q_Y)`, and each part is scaled by `2^(q − e)`. A part more
    than 60 binades down becomes 0.
- **Times**: `(a.re·b.re − a.im·b.im, a.re·b.im + a.im·b.re, a.e + b.e)`, normalized.
- **Doubled**: `e + 1`.
- **Reciprocal**: `d = re² + im²`, then `(re/d, −im/d, −e)`, normalized.
- **Plus**:
  - An operand that is 0 returns the other.
  - Otherwise `e = max(a.e, b.e)`, and each part is scaled by `2^(its e − e)`, or becomes
    0 when it is more than 60 binades down.
  - The parts are summed, and the result is normalized.

## The result

`Nucleus`:

| Field | Meaning |
|---|---|
| `found` | `converged`, no lower period, and `inside` |
| `converged` | `N` under the bar at the final `F`, with `F` 64 bits past the depth |
| `inside` | the last point is within the reach of the view's center |
| `stop` | the last run's stop: `floor`, `no-improvement`, `left-view`, `stagnated`, `max-evaluations`, `max-steps`, `zero-derivative`, `start-escaped` |
| `center_re`, `center_im` | the last point, printed at `P` places |
| `period` | as asked |
| `lower_period` | the divisor period the screen found, or none |
| `bits` | `F` at the end |
| `steps` | accepted steps, summed over the runs |
| `evaluations` | evaluations, summed over the runs; the final pass is not counted |
| `depth_bits` | as above |
| `size_log10` | ε; NaN unless converged on period `p` itself |

`location()` is the portable record of a found nucleus, a
[Location](locations.md#the-location-record):

- `format`: `nucleus`.
- `half_height_log10`: `size_log10 + 0.4`, about 2.5 times the size. The size estimate
  scales and turns the whole set, so a minibrot's spike tip lies 2 sizes from its
  nucleus, in whatever direction it faces. A half-height of 2.5 sizes keeps it in frame.
  - A Heaton Fractal hunt result frames at the size itself, which crops the spike.
    [locations.md](locations.md) imports it that way, so the same nucleus arriving both
    ways frames 0.4 decades apart.
- `max_iter`: `min(100·p, 2³¹ − 1)` (Kalles Fraktaler's rule for a minibrot target),
  computed without overflow. 16 periods leaves a quarter of a small minibrot's frame
  falsely interior.
- No reference and no warnings.

It is an error on a result that was not found. A location can be deeper than a renderer
can go (past T1's zoom 290, or a host's own cap). Clamping is the host's job.

**Cancellation** (C#: a `CancellationToken`) throws `OperationCanceledException` and
never returns a partial result.

- It is polled on entry to `BoxPeriod` and `FindNucleus`, at the start of every square,
  every evaluation and the final pass, and every 4096 iterations inside them. A canceled
  call stops within one evaluation's first 4096 iterations, whatever the period.
- Python takes no cancellation, like its renders.

## Errors

- `max_period < 1` or `period < 1`.
- `max_steps < 1`, `max_evaluations < 1` or `max_escalations < 0`.
- A radius that is not finite and positive.
- A `zoom_log10` outside `[−300, 300]` (or not finite).
- A converged center that needs 10,000 places or more (a nucleus deeper than about
  `10^−9990`). It could not be read back ([navigation.md](navigation.md) "Printing"), so
  printing it raises: Python `ValueError`, C# `ArgumentException`.

## Conformance

`vectors/nucleus/<case>/params.json` (spec 0.9.0), `params.json` only. Every key is
required for its operation, and `null` is written, never omitted:

- **`operation`**:
  - `box`: runs `box_period`.
  - `find`: runs `find_nucleus`.
  - `snap`: runs `box_period`, then, on `surrounded`, `find_nucleus` with the box's
    period and its `radius` at the same zoom.
- **`input`**: `center_re`, `center_im`, `zoom_log10`, and `radius` (an IEEE-754 bit
  pattern, or `null` for the default).
  - `box` and `snap` add `max_period`.
  - `find` adds `period`, `max_steps`, `max_evaluations` and `max_escalations`.
- **`expected`**:
  - `box` (`box` and `snap`): `period`, `reason`, `halvings`, and `radius` as a bit
    pattern.
  - `nucleus` (`find`, and `snap` when the box surrounded, else `null`): every field of
    the result. `size_log10` is a bit pattern, compared within the case's
    `relative_epsilon` (`1e-12`), with NaN equal to NaN.
  - `location` (with `nucleus`, `null` when not found): `half_height_log10` (a bit
    pattern, within ε) and `max_iter`.
  - Everything else is exact.

**What the vectors pin.** Most cases pin one rule each: a port that changes that rule
fails the case. The rules and their cases:

- The box's escape bound `2^(F+16)`, per component, and the crossing test's strict `> 0`.
- The evaluation's strict `> 2`, per component.
- The line search's 25 halvings, `no-improvement`, strictly smaller, and the two
  roundings.
- The clamp's `≤`, and `rshift`'s and `rdiv`'s ties.
- The stagnation window's start and factor.
- Escalation only after `floor`, with fresh budgets.
- The bar `K`, the precision gate's 64 bits, and the ceiling in the view's places.

Three rules have no known distinguishing input, so no vector pins them, and no test
does:

- the floor threshold `2^64`;
- the no-backtrack threshold `2^(F+8)`;
- the box's `≥` at `2^(F+16)`, as against `>`. It changes the outcome only if a corner
  sits exactly on the bound and a surround follows.

About 850,000 random finds turned up no input that tells these apart from nearby values.

**Cross-project checks** (unit tests, slow). Heaton Fractal's hunter printed three
nuclei in its r7-a run: periods 1959, 6308 and 26699. Each is refined from HF's printed
digits, at the zoom HF navigated to (21, 55 and 118). Each must be found. It must print
HF's digits rounded to `P` places, and its size must match HF's `depthLog10` within
`1e-12`.

## Notes

- **Not here.**
  - There is no ball period test. That one is Kalles Fraktaler's, and Heaton Fractal has
    none.
  - There is no atom-domain argmin period either. From a view center it returns the
    parent minibrot's period. It survives here only as the lower-period screen above,
    at the converged point.
- **Heaton Fractal's box** differs from this one:
  - Its square's half-side is the view's half-height.
  - Its multiplies truncate.
  - It keeps iterating past an escape: its fixed point wraps, and Newton decides. Here an
    escape halves the square instead, because the integers here do not wrap.
- **Heaton Fractal's Newton** divides with an iterated reciprocal. Here the division is
  exact: the step is rounded once.
- **Budgets.**
  - A box costs at most `9 · max_period · 4` orbit steps.
  - A run costs at most `max(max_evaluations, 2) + 24` evaluations of `p` steps, and
    there are at most `max_escalations + 1` runs.
  - The final pass is one more orbit.
- **Performance.** C# evaluates in `BigInteger`, as the orbit's slow path does: about
  6 µs and 7 KB of garbage per iteration at 1,000 bits. That is fine at the depths a host
  reaches interactively. A limb-based evaluator (like `FixedOrbit`) is future work for
  periods in the tens of thousands.
