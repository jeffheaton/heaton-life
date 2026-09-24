# Floatexp: a float64 mantissa with an unbounded exponent

T2 ([deep-zoom.md](deep-zoom.md) "T2") needs real numbers far below float64's range:
pixel deltas near `10^-9000`, orbit samples near `2^-1790`. A **floatexp** value is

```
x = m · 2^e        |m| in [1, 2), or x = 0 as exactly (0.0, 0)
```

where `m` is a float64 and `e` an integer. Python `heaton_life.core.floatexp` (scalars
as `(m, e)` tuples, and elementwise NumPy versions on a float64 mantissa array and an
int64 exponent array), C# `HeatonLife.FloatExp` (internal).

**Bit-exact.** Every operation is one IEEE-754 float64 operation on mantissas, plus
exact integer arithmetic on exponents. Every rescaling multiplies by an exact **normal**
power of two, `2^k` for `k` in `[−1022, 1023]`, built from the IEEE bits (no `ldexp`
into the subnormals, no `pow`, no libm). There is no fused multiply-add. Add and multiply
are **correctly rounded** (ties to even) with no exponent range limit, so both ports
compute the same bits.

## Zero

Zero is the single value `(0.0, 0)`: `normalize(±0, e)`, `neg` and `twice` of zero, a
product with a zero factor and an add that cancels exactly all return it. No rule reads
a zero's exponent. `to_double` and `scaled` test for zero before looking at `e`, and
`compare` tests signs first. A caller choosing an exponent from several values skips
their zero parts. There are no sentinel exponents.

## Exponent floor

A result whose exponent falls below `−2^31` is zero. An iterated square, such as a
Julia delta at an exact zero of the orbit, doubles its exponent each time and would
otherwise overflow a 64-bit exponent within about 60 steps. Past
`2^−(2^31)` a value is zero for every purpose here: T2's escape and rebase tests give
the same answer for it as for 0. With the floor, every exponent stays within
`±2^32`, so sums and doublings never overflow an int64 (C# `long`, NumPy int64).

Values that are not on their way to the floor stay far smaller: at T2's deepest zoom
(9000) a pixel scale is near `2^−29900`, and the landing tests' squares and the slow
step's products reach about twice that, so `|e| < 2^17` and exponent differences stay
below `2^18`.

## Operations

- **binade(d)**, for a finite nonzero double `d` (subnormals too): the `k` with
  `|d|` in `[2^k, 2^(k+1))`. It is exact: take it from the IEEE bits or `frexp`.
- **normalize(v, e)**, for a finite double `v`:
  - `v = 0` gives zero.
  - Otherwise `k = binade(v)`. If `e + k < −2^31`, the result is zero. Otherwise it is
    `(v · 2^−k, e + k)`.
  - The scaling is exact: the result lies in `[1, 2)`. A subnormal `v` needs
    `2^−k` with `−k > 1023`, done as two exact multiplies.
- **from_double(d)** = `normalize(d, 0)`, for a finite `d`.
- **from_fixed(V, F)**, for the integer `V` standing for `V / 2^F`:
  - Round `|V|` to 53 significant bits, ties to even, with a sticky bit.
  - `m` is that 53-bit integer times `2^−(its bit length − 1)`, with `V`'s sign.
  - `e` is the bit position accordingly. A rounding carry into a new binade makes the
    integer `2^53`, and `m` is then `1.0` at the next exponent.
- **neg(x)** = `(−m, e)`. **twice(x)** = `(m, e + 1)`. Both leave zero alone.
- **mul(a, b)**: zero if either is zero. Otherwise `normalize(a.m · b.m, a.e + b.e)`,
  one IEEE multiply.
- **add(a, b)**:
  - Either zero gives the other.
  - Order the operands so `a.e ≥ b.e`, and let `gap = a.e − b.e`.
  - `gap > 64` gives `a`. `|b| < 2^(a.e−63)` is below a quarter ulp of `a`, so
    correctly rounded, `a + b = a`.
  - Otherwise the result is `normalize(a.m + b.m · 2^−gap, a.e)`. The scaling is exact
    (`|b.m · 2^−gap| ≥ 2^−64`), and the IEEE add rounds once.
  - `sub(a, b) = add(a, neg(b))`.
- **compare(a, b)**: sign first (zero has none), then the exponent, then `|m|`, the
  order reversed for negatives. It is a total order on values.
- **to_double(x)**, the double nearest `x`, rounded once:
  - `x = 0` gives `+0.0`.
  - `e > 1023` gives `±∞`.
  - `e ≥ −1022` gives `m · 2^e`, exact.
  - `−2044 ≤ e < −1022` gives `(m · 2^(e+1022)) · 2^−1022`. The first product is exact
    and normal, and the second rounds once into the subnormals.
  - `e < −2044` gives a signed zero, since `|x| < 2^−2043` is below half the smallest
    subnormal.
- **scaled(x, E)** = `to_double((m, e − E))`, which is `x / 2^E` as a double (`0.0` for
  zero).

## NumPy notes

The elementwise versions follow the same rules. Powers of two come only from the IEEE
bits or from `np.ldexp(np.float64(1.0), k.astype(np.int32))` with `k` clipped to
`[−1022, 1023]`: NumPy picks `ldexp`'s loop from its first argument's type, so
`np.ldexp(1, k)` with a Python int would compute in float16. Neither `ldexp` nor
`scalbn` ever produces a result that may be subnormal; such a result comes from one
multiply, whose rounding is the one pinned above. `frexp` gives the binade of a
subnormal exactly while denormals-are-zero is off (deep-zoom.md "Platform contract").

## Known answers

`vectors/floatexp/` pins the operations at their boundaries: add at gaps 63, 64 and 65,
ties to even, cancellation to zero, `to_double` at `−1022`, `−1074` and `−2044`, the
`from_fixed` carry, the floor, and `compare` with zeros, signs and exponents. Each input and output is a mantissa bit pattern and
an exponent. [pow10.md](pow10.md) "Floatexp" pins `pow10x`.
