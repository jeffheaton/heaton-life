# pow10: deterministic powers of ten (pinned)

`pow10(x)` returns a float64 approximation of `10^x` computed by the fixed
integer algorithm below. Every implementation must produce **bit-identical**
results — like PCG32 ([rng.md](rng.md)), this exists because the platform
alternative is not portable: `pow` is a libm call, and libms legitimately
disagree in the last ulp (measured: Windows UCRT rounds `pow(10, 0.2)` one ulp
below macOS libm, which flipped 12 escape counts in
`vectors/burning-ship/home-64`). The fractal pixel scale
([fractals.md](fractals.md)) is the one place a transcendental feeds a
bit-exact output, and this algorithm removes the libm from that path.

The contract is **sameness, not correct rounding**: the algorithm's error is
below 2⁻¹¹⁰ relative, so results are correctly rounded except within a
vanishing distance of rounding-boundary ties — and even there every
implementation agrees, because the bits fall out of the same integer
arithmetic. (`mpmath` ground-truth comparison belongs in each suite's tests.)

## Domain

Finite `x` with `|x| ≤ 300` (the tier ceiling in [deep-zoom.md](deep-zoom.md)
is zoom 290; results stay comfortably inside float64 normal range, so no
subnormal handling exists). Out-of-domain input is a caller error — raise.

## Algorithm

All arithmetic is arbitrary-precision integer ("bignum": Python `int`, C#
`System.Numerics.BigInteger`). `F = 128` is the fixed-point fraction width;
a value `v` is represented by the integer `v · 2^F`. `>>` on a negative
bignum must round toward −∞ (floor); both Python and BigInteger do. All
divisions below have non-negative operands, so `//`-style truncation and
floor agree — but implementations must not introduce negative-operand
divisions.

Pinned constants (128 fractional bits; derivation in the appendix):

```
LOG2_10_Q128 = 1130393554869435518674010122299176348979   # 0x35269E12F346E2BF924AFDBFD36BF6D33
LN2_Q128     = 235865763225513294137944142764154484399    # 0xB17217F7D1CF79ABC9E3B39803F2F6AF
```

Steps, given float64 `x`:

```
1. Decompose x exactly: x = m · 2^e with integer m (|m| ≤ 2^53), integer e,
   sign carried by m. (Read the IEEE bits; subnormal m is fine.)
   x == 0  →  return 1.0.

2. Y = (m · LOG2_10_Q128) shifted by e:              # Y ≈ x·log2(10) in Q128
       e ≥ 0:  Y = (m · LOG2_10_Q128) << e
       e < 0:  Y = (m · LOG2_10_Q128) >> (−e)        # floor shift

3. n = Y >> F        # floor; the result's binary exponent
   f = Y − (n << F)  # fractional part, in [0, 2^F)

4. t = (f · LN2_Q128) >> F                           # t ≈ frac·ln2, in [0, ln2)

5. exp(t) by Taylor series in Q128:
       sum = 2^F; term = 2^F
       for k = 1, 2, 3, …:
           term = ((term · t) >> F) / k              # truncating integer ops
           if term == 0: break
           sum = sum + term
   sum ∈ [2^F, 2^(F+1)) approximates e^t · 2^F.

6. Round sum to a 53-bit mantissa, ties-to-even:
       shift = F + 1 − 53                            # = 76
       mant = sum >> shift
       rem  = sum − (mant << shift)
       half = 2^(shift−1)
       if rem > half or (rem == half and mant is odd): mant += 1
       if mant == 2^53: mant = 2^52; n += 1

7. Assemble the float64 directly from bits (no ldexp, no pow):
       value = mant · 2^(n−52), i.e. IEEE fields
       exponent = n + 1023, fraction = mant − 2^52.
   (|x| ≤ 300 keeps n within ±997, so the result is always normal.)
```

## Use sites

The **only** sanctioned consumer in the conformance surface is the fractal
pixel scale ([fractals.md](fractals.md) "Pixel mapping"):

```
ps = (4.0 / width) · pow10(−zoom_log10)
```

where the division and the multiplication are each a single float64 rounding.
This replaces the historical `10^(log10(4/width) − zoom)` expression, whose
two libm calls were the non-portability. Presentation-layer code (speed
sliders, UI) may keep native `pow` — nothing bit-exact flows from it.

## Known-answer test

Every implementation must assert these exact IEEE-754 bit patterns:

```
pow10(  0.0)  = 0x3FF0000000000000   (exactly 1.0)
pow10(  1.0)  = 0x4024000000000000   (exactly 10.0)
pow10( 14.0)  = 0x42D6BCC41E900000   (exactly 10^14)
pow10( 22.0)  = 0x4480F0CF064DD592   (exactly 10^22 — largest exact power)
pow10(  0.2)  = 0x3FF95BB8F6D46053
pow10( -0.2)  = 0x3FE430CD74F6D478
pow10( -0.1)  = 0x3FE96B230BCDC434
pow10(-14.0)  = 0x3D06849B86A12B9B
pow10(290.0)  = 0x7C2485CE9E7A065F
pow10(-290.0) = 0x03B8F2B061AEA072
```

Integer inputs 0–22 must equal the exactly-representable `10^k` doubles. The
reference suite additionally sweeps the domain against `mpmath` at 200-bit
precision (40,000 points, zero mismatches at adoption) and re-runs the
algorithm at F = 256 to confirm the F = 128 roundings are stable (Ziv check).

## Appendix: constant derivation

The constants are `round(c · 2^128)` computed at ≥ 60 significant decimal
digits (Python `decimal` with `prec = 80`):

```python
from decimal import Decimal, getcontext
getcontext().prec = 80
ln2 = Decimal(2).ln()
log2_10 = Decimal(10).ln() / ln2
scale = Decimal(2) ** 128
LOG2_10_Q128 = int((log2_10 * scale).to_integral_value(rounding="ROUND_HALF_EVEN"))
LN2_Q128     = int((ln2     * scale).to_integral_value(rounding="ROUND_HALF_EVEN"))
```
