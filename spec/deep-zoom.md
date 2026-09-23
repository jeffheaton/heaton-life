# Deep-zoom fractal rendering: precision architecture

## Problem

At magnification 10^k, pixel spacing is roughly `4·10⁻ᵏ / width`. float64 carries ~15–16 significant digits, so around zoom **1e13** adjacent pixels collapse to the same float64 coordinate and the image pixelates. Naive arbitrary precision per pixel per iteration (mpmath everywhere) is correct but 100–1000× too slow to be interactive.

## Approach: perturbation theory + rebasing

One point pays the bignum bill; every other pixel rides on hardware floats.

### Reference orbit (the only high-precision computation)

Iterate the center once at high precision:

```
Z₀ = 0;  Zₙ₊₁ = Zₙ² + C        C = viewport center          (Mandelbrot, Burning Ship)
Z₀ = C;  Zₙ₊₁ = Zₙ² + c        c = the fixed Julia parameter (Julia)
```

Julia also needs its **critical orbit** `W₀ = 0; Wₙ₊₁ = Wₙ² + c`, the orbit rebased
pixels restart on ([Rebasing](#rebasing-single-reference-no-glitches)). It is computed
exactly like a reference orbit — the Julia recurrence from center `"0"`, so its
precision is the zoom term alone, with the same arithmetic and stopping rule — and
depends only on `(c, zoom_log10, max_iter)`.

- **Precision**: the orbit runs in binary fixed point with `F` fractional bits,

  ```
  zoom_bits  = trunc(3.33 · max(zoom_log10, 0)) + 64
  places     = max over center_re, center_im of (digits after the point − exponent), at least 0
  digit_bits = bit length of 10^min(places, 340)
  F          = max(zoom_bits, digit_bits) + 64
  ```

  `zoom_bits` truncates — the fractional part is **discarded**, not rounded up (46 + 64
  at zoom 14, not 47 + 64). That is a correction: the text once said `ceil` while every
  shipped orbit vector was produced by the truncating form, and the vectors are the
  contract. The **digit term** keeps a center's own digits: without it a component of
  `1e-310` at zoom 280 would keep ~30 significant bits. It left every vector shipped
  before it unchanged (Seahorse: `10³³` is 110 bits, exactly zoom 14's `46 + 64`). Its
  cost is paid at every T1 zoom — a 256-place center runs at 915 bits — but only T1
  computes an orbit at all. Trailing zeros count (`"0.0"` has one place). The term
  stops at 340 places: digits past `10⁻³⁴⁰` sit below half the smallest float64
  subnormal, cannot reach a sample, and would otherwise let a long string set `F`
  on its own.
- **Arithmetic (normative, both ports)**: a real `x` is held as the integer
  `round(x · 2^F)`, and every rounding is pinned.
  - A decimal center is parsed exactly (`digits · 10^e`, never through float64) and
    rounded to `F` bits, ties **away from zero**. Julia's `c` is a float64, converted
    exactly, rounding ties away from zero if `F` is too small to hold it.
  - A product is `round(a · b / 2^F)`, ties away from zero (truncation would bias
    every multiply toward zero and drift the orbit); sums are exact.
  - One step is `X' = mul(X, X) − mul(Y, Y) + Cᵣ`, `Y' = 2 · mul(X, Y) + Cᵢ` — this shape,
    `2 · mul(X, Y)` and not `mul(2X, Y)`. Burning Ship takes `2 · mul(|X|, |Y|)`.
  - Each sample component becomes float64 by the single rounding below.

  Both ports run exactly these integer operations, so orbits agree **bit for bit at any
  length** (Python: `core.bignum` on ints, with gmpy2's `mpz` as an optional speedup of
  the same integers; C#: `ReferenceOrbit` over `System.Numerics.BigInteger`).
  (Correction 2026-09-23: Python iterated in binary *floating* point (gmpy2/mpmath) and
  C# in fixed point, and this spec asked only that they agree after rounding each
  sample to float64. That held for well-behaved orbits and failed on chaotic ones —
  the deep Julia vector's orbits parted at sample 38, Dinkydau's 256-place "11
  Dimensions" center at sample 67,941 at zoom 160 — because the two roundings differ
  from the first multiply and a chaotic orbit amplifies any difference.)
- **Stopping rule**: the orbit ends early once `|Zₙ|² > 1e100`, tested on the
  float64-rounded sample. Past that magnitude every pixel referencing the sample has
  escaped at any sane radius. Every sample but the last is at most `1e50` in magnitude;
  the last is the one that tripped the rule, below ~`1e100` — or `±∞` when its bignum
  value is past the float64 range (a center near `1e155` for Julia, `1e308` for
  Mandelbrot), which the float64 conversion rounds to infinity like any IEEE overflow.
  A Julia `Z₀` is never tested.
  So `N = min(escape_iter, max_iter)`, and **`Z[0..N]` may be shorter than
  `max_iter + 1`** — which is why implementations clamp the reference index to the
  last sample. Vectors record the realized `length` rather than deriving it.
- The orbit is **stored as complex128** — the array `Z[0..N]` is plain doubles and is
  exportable (see cross-language notes). A *component* can be arbitrarily small: a
  center within `1e-300`
  of an axis puts one there from `Z₁ = C` on. So each bignum sample becomes float64
  by **one** round-to-nearest, ties-to-even, **subnormals included** — never a
  53-bit rounding followed by a scale into the subnormal range, which rounds twice.
  (Correction 2026-09-23: C# threw on components below ~`1e-292` once the working
  precision passed 1022 fractional bits, near zoom 268.8;
  `vectors/mandelbrot/deep-zoom280-tinyim-32` pins the case.)

### Per-pixel perturbation (hardware floats)

Each pixel is `c = C + δc`, its orbit `zₙ = Zₙ + δₙ`, and the recurrence for the small difference needs only float64:

```
δₙ₊₁ = 2·Zₙ·δₙ + δₙ² + δc          (Mandelbrot; algebra)
```

**Computed in this shape, and no other** — the expanded form rounds differently and
is not conforming:

```
t      = 2·Zₙ + δₙ                         (component-wise)
t·δₙ   = ( fma(tᵣ, δᵣ, −(tᵢ·δᵢ)),  fma(tᵣ, δᵢ, tᵢ·δᵣ) )
δₙ₊₁   = t·δₙ + δc                         (component-wise)
```

The product is FMA-contracted because that is what NumPy 2.x's complex multiply
does; the C# port mirrors it with `FractalEngine.ComplexMul` (see
[Float-determinism gotchas](#float-determinism-gotchas)).

Escape test and smooth coloring use the reconstructed `z = Z[m] + δ`:
`|z| > R` escapes; `μ = n + 1 − log₂(log|z| / log R)`.

### Rebasing (single reference, no glitches)

Classic perturbation suffers "glitches" where `|δ|` grows comparable to `|Zₙ|` and cancellation corrupts pixels; the old fix was glitch detection plus re-rendering with extra references. We use rebasing instead: each pixel tracks its reference index `m`, and

> when `|Z[m] + δ| < |δ|`, set `δ ← Z[m] + δ` and `m ← 0` on the **rebase orbit**.

The new `δ` is the pixel's full value `z`, so the orbit it restarts on must begin at
`0`: then `z = orbit[0] + δ` still holds. That fixes the rebase orbit per family:

- **Mandelbrot, Burning Ship**: the reference itself (`Z₀ = 0`).
- **Julia**: the critical orbit `W` (`W₀ = 0`), **not** the reference, which starts at
  the viewport center. A pixel follows `Z` until its first rebase and `W` from then
  on; every later rebase restarts `W` at `m = 0`. The pixel state is therefore
  `(δ, m, which orbit)`.

The escape test runs before the rebase test in each iteration, and the index is
clamped to the last sample of the orbit the pixel currently follows. Julia has no
`δc` term, so a `δ` that lands on exactly `0.0` stays there: the pixel then follows
`W` exactly, which is right for `z = 0` and loses only a sub-ulp remainder otherwise.

> Correction (2026-09-23): the Julia rule used to restart on the reference, which
> made a rebased pixel iterate `C + z` instead of `z`. No shipped vector caught it —
> the only Julia case was a T0 frame — and on the rabbit Julia at zoom 13 the old rule
> agreed with 300-bit direct iteration on 57% of pixels. `vectors/julia/deep-zoom13-32`
> pins the corrected rule, with both orbits stored.

**Squared magnitudes are safe at T1 for Mandelbrot and Burning Ship, and only at T1.**
Both tests compare plain float64 squares (`zr·zr + zi·zi` against `R²` or `dr·dr + di·di`),
which lose precision once a value falls below ~`1.5e-154` and flush to 0 below ~`1e-162`
— then a needed rebase would evaluate `0 < 0`. At T1 this has not changed a count, for
two reasons. First, the test compares the *pixel's* values, and those stayed clear of the
flush: rendering Heaton Fractal's hunted nuclei (periods 1,959 / 6,308 / 26,699 at their
own depths 1e43 / 1e106 / 1e235, and the period-26,699 center at 1e200), no pixel-iteration
had both `|z|²` and `|δ|²` below `2^-960` — although a reference centered on a nucleus
itself passes arbitrarily close to 0, limited only by the center's digits (`4.1e-182` at
iteration 26,699 of that center). Second, a rebase skipped in that zone would change the
next `δ` by at most `|δ|·|z| < 1e-308`, below the ulp of `δc ≥ ~1e-292`, after which the
reference and the pixel restart together as `C + δc`. Past T1 neither holds: **T2 and any
BLA radius test must compare exponent-scaled magnitudes** (scale every operand by one
exact `2^k` before squaring), never plain squares.

Julia has no `δc` floor, and that is a real T1 limit rather than a comparison problem:
a reference passing within ~`1e-154` of 0 (a center that close to a preimage of 0, deep
in T1) underflows `2·Zₙ·δₙ + δₙ²` itself, so `δ` becomes `0.0` and the pixel follows the
reference from then on. Rebasing onto `W` does not help, since the next `δ` is `δ²`. The
true pixel differs by less than `1e-300` at that point and needs ~1,000 more iterations
to separate; rendering that faithfully needs floatexp.

One reference orbit (plus Julia's critical orbit) suffices for the whole frame; no glitch passes. Vectorizes cleanly in NumPy: all pixels advance in lockstep, `Z[m]` is a fancy-indexed gather, escaped pixels are masked out. The NumPy version is the reference; an optional compiled (numba) kernel for the scalar loop is future work ([ROADMAP.md](../ROADMAP.md)) and, if added, must reproduce the NumPy path's iteration counts bit-for-bit (the bit-exact conformance tier, [fractals.md](fractals.md)) and its smooth values within the render ε ([render.md](render.md)).

### Per-family formulas

- **Mandelbrot**: recurrence above; `δc` = pixel offset, `δ₀ = 0`.
- **Julia**: `c` is a fixed global parameter; the reference orbit iterates the viewport center as `z₀`; pixels have `δ₀` = pixel offset and `δₙ₊₁ = 2·Zₙ·δₙ + δₙ²` (no `δc` term — the same computed shape with `δc = 0`). Rebased pixels continue on the critical orbit `W` with the same recurrence (`Wₙ` in place of `Zₙ`).
- **Burning Ship**: component form; the `|·|` folds use the stable piecewise `diffabs(X, x) = |X + x| − |X|` so cancellation never happens inside an abs. Computed as real-array operations (no FMA): `a = diffabs(X, δx)`, `b = diffabs(Y, δy)`, `δx' = (2X + δx)·δx − (2Y + δy)·δy + δcₓ`, `δy' = 2·(|X|·b + |Y|·a + a·b) + δc_y`.
- **Newton**: root-basin rendering, no self-similar deep zoom of the same kind — float64 direct only in v1; no perturbation tier.

## Precision tiers (auto-selected from zoom)

| Tier | Range (zoom = 10^k) | δ arithmetic | Status |
|---|---|---|---|
| T0 direct | k ≤ 12 | none — plain float64 escape-time | v1 |
| T1 perturbation | 12 < k ≲ 290 | float64 (δc underflows near 1e308; margin kept) | v1 |
| T2 perturbation | k > 290 | floatexp (float64 mantissa + int64 exponent) | reserved, future |

Tier selection is automatic and invisible to the caller; the API surface is identical across tiers.

## Viewport contract (lands in core on day one)

```json
{
  "center_re": "-0.743643887037158704752191506114774",
  "center_im": "0.131825904205311970493132056385139",
  "zoom_log10": 11.5,
  "max_iter": 50000
}
```

- `center_re` / `center_im` are **decimal strings** of arbitrary length — JSON-safe,
  language-neutral, parsed into the orbit's fixed point only where needed. One
  grammar serves every consumer (Python `core.decimal_text`, C# `DecimalText`):

  ```
  [ws] [+|-] digits-with-at-most-one-point [ (e|E) [+|-] digits ] [ws]
  ```

  At least one digit before the exponent (`.5` and `5.` are fine, `.` is not); at most
  10,000 digits before it; exponent magnitude at most 100,000; ASCII digits only; `ws`
  is ASCII space, tab, CR or LF. **No NaN, no infinities, no `_` separators.** The two
  bounds keep parsing and the orbit precision finite for any string a caller can hand
  in. (Correction 2026-09-23: the Python Viewport validated with `decimal.Decimal()`,
  and the C# one with `double.TryParse`, which accepted `NaN`, `Infinity`, `1_000` and
  non-ASCII digits that the orbit parse then refused.)
- The **float64 projection** of a center, which T0 renders from, is the double
  nearest the decimal's exact value: one rounding, ties to even, subnormals like
  everything else, infinities past the float64 range, and `-0` as `-0.0`. Python's
  `float()` is that conversion; C# computes it from the digits, because
  `double.Parse` is only guaranteed correctly rounded on .NET Core 3.0+ and the
  library also runs on Mono and IL2CPP. Never derive it from the orbit's fixed point
  — that would round twice. `vectors/mandelbrot/seahorse-zoom6-48x32` pins it (and,
  being the first non-square vector, the width-based framing of
  [fractals.md](fractals.md)).
- `zoom_log10` is a float; span derives from it. The public API never represents a viewport center as complex128 — retrofitting precision into a complex128 API breaks every downstream consumer, which is why this contract exists before the first fractal is implemented.

## Caching & interactivity

- The reference orbit depends on `(kind, C, F)`, plus `c` for Julia, where `F` comes
  from `zoom_log10` and the center's digits ([Precision](#reference-orbit-the-only-high-precision-computation)),
  and on `max_iter` only through where it stops. Cache on `(kind, C, F, c)`, keeping
  each orbit's samples **and** the exact fixed-point `Z` at its last sample. A request
  with `max_iter < length` (the cached orbit already holds `max_iter + 1` samples) — or
  any request, once the cached orbit has hit the stopping rule — is answered by the
  first `min(length, max_iter + 1)` samples; a longer one resumes from the kept state
  and appends. (A renderer may read a longer cached orbit in place: the perturbation
  index advances by at most one per iteration, so it never reads past `max_iter`.) Both are identical to computing
  afresh (the recurrence is deterministic; `max_iter` only says when to stop), which
  makes an auto-iteration ladder cost one orbit, not one per rung. Evict least recently
  used first, under an entry cap (8 in both ports) and a byte cap (64 MB of samples by
  default; C#'s `ReferenceOrbit.CacheByteLimit`, Python's `bignum.CACHE_BYTES`), always
  keeping the two most recent — a Julia frame uses two orbits, and a cap between one
  and two must not make them evict each other every frame. A computation that is
  canceled is never cached.
- The cache helps a fixed center only: zooming toward it reuses the orbit while `F` is
  unchanged (a deeper zoom raises `F` and needs a new orbit), and raising `max_iter`
  resumes it. Julia's critical orbit depends on `(c, F)` alone and is hit every frame.
  A pan moves the center, so v1 computes a new orbit (≈ `max_iter` bignum steps, ms to
  100s of ms); reusing an off-center reference is future work.
- C# steps the orbit on fixed-width 32-bit limbs in preallocated buffers
  (`FixedOrbit`), falling back to `System.Numerics.BigInteger` for centers or `c` of
  magnitude `2¹⁶` or more. Both run the same integer operations, so the choice cannot
  show in the orbit; the limbs exist because an immutable `BigInteger` step allocated
  1.5–4.7 KB per iteration, hundreds of megabytes per deep orbit for a garbage collector
  that stalls frames.
- Playground: renders are single-pass today; progressive refinement (iteration ladder, coarse-to-fine tiles) with cancellation on viewport change is future work ([ROADMAP.md](../ROADMAP.md)).

## Cross-language notes

- The perturbation loop is plain doubles — the same code shape in Python and C#; iteration counts are bit-comparable in T0/T1.
- Both ports compute the reference orbit in the fixed point above, so the orbit itself
  is part of the contract, not just its float64 rounding; a port may also consume the
  orbits a vector stores (the conformance replay does, and needs no bignum). Porting
  traps: .NET's `(double)BigInteger` truncates, so the float64 conversion is hand-rolled
  from the IEEE-754 bit pattern; a scale by a power of two into the subnormal range
  rounds a second time; and fixed point measures precision from the binary point, so
  values below 1 have fewer significant bits than `F` — the reason for the guard term.
- Vectors for fractals include: viewport JSON, iteration-count grids (bit-exact tier),
  and the reference orbit (plus Julia's critical orbit) as raw little-endian f64 pairs.
  An orbit too long to ship is pinned by digest in both suites instead (the 11
  Dimensions orbit at zoom 160: 139,166 samples, SHA-256 `7664f6f7…9b4c`).

## Float-determinism gotchas

Hard-won; each has broken, or would break, bit-exact agreement between the ports.

- **FMA shape.** A complex product that NumPy computes with its multiply ufunc (the
  perturbation step, and T0's `z²`) is FMA-contracted: real = `fma(a, c, −(b·d))`,
  imag = `fma(a, d, b·c)`. Real-array NumPy chains never contract, so everything else
  ports expression for expression with plain operations. netstandard2.1 has no fma,
  so C# carries a software one (`FractalEngine.Fma`), and it must be a *real* fma —
  one rounding, subnormals and signed zeros included — not just on well-scaled
  operands: Dekker's error-free transforms where they are exact (`|a·b| ≥ 2⁻⁹⁶⁸`,
  operands below `2⁹⁹⁵`), the exact integer sum rounded once everywhere else. That
  slow path is not hypothetical. Julia has no `δc` floor, so a rebase onto `W₀ = 0`
  squares a `δ` near `1e-155` and interior pixels contract `δ` down through the
  subnormals; with Dekker alone the product differed from the hardware in a third of
  those cases — the counts survived, but the smooth render of
  `vectors/render/fractal-render-julia-deep157` moved by `3e-7` (ε = `1e-9`). The fma
  is pinned bitwise against the hardware over every exponent. Its price: an all-interior deep Julia frame runs about 3× slower in
  C# than an escaping one.
- **Squared magnitudes** are exact enough at T1 and only at T1 (see
  [Rebasing](#rebasing-single-reference-no-glitches)).
- **Magnitude forms.** Smooth coloring's `|z|` is `np.abs` (hypot) in Python and
  `sqrt(re·re + im·im)` in C#. That is fine for `μ`, an ε-tier output; any new
  bit-exact output that needs a magnitude must pin one form (`sqrt(re·re + im·im)`).
- **Powers of ten** in the pixel scale go through [pow10.md](pow10.md), never libm.
- **The center's float64 projection** is one correct rounding of the decimal (see the
  Viewport contract) — never `double.Parse` on a runtime that does not guarantee it,
  and never a rounding of the orbit's fixed point.
- **Newton's roots** `exp(2πik/d)` come from libm `cos`/`sin`, whose last ulp varies by
  platform. They only classify converged pixels: `|zᵈ − 1| < 1e-9` puts `z` within
  ~`1e-9/d` of a root, and roots are `2·sin(π/d)` apart, so a last-ulp difference cannot
  change the `roots` output. Do not use them for anything finer.

## Future work (explicitly out of v1)

- **BLA** (bivariate linear approximation) for iteration skipping at extreme depth.
- T2 floatexp arithmetic.
- Interior detection, distance-estimation anti-aliasing.
