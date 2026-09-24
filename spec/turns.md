# Turns: pinned cosine and sine of a rational angle

Some bit-exact outputs need `cos` and `sin` of an angle that is a rational number of
turns: Newton's roots of unity `e^(2πik/d)` ([fractals.md](fractals.md)). Platform libms differ in the last ulp of `cos` and `sin` (and
`2π·k/d` is not exact in float64), so these come from integer arithmetic alone, the same
way [pow10.md](pow10.md) pins `10^x`. Python `heaton_life.core.turns.cis_turns`, C#
`HeatonLife.Turns.Cis` (internal).

## cis_turns(k, n)

`(cos 2πk/n, sin 2πk/n)` as two float64, for integers `k` and `1 ≤ n ≤ 2^61` (an `n`
outside that range is a caller error: raise; C# takes `k` as a 64-bit integer):

1. `k ← k mod n` (non-negative). `4k = q·n + r` with `0 ≤ r < n`: the quadrant `q ∈ {0, 1, 2, 3}`
   and the angle within it, `φ = (π/2)·r/n`, exact so far.
2. `x = floor(HALF_PI · r / n)`: `φ` in fixed point with `F = 192` fraction bits, where
   ```
   HALF_PI = floor(π/2 · 2^192)
           = 0x1921FB54442D18469898CC51701B839A252049C1114CF98E8
   ```
3. `x2 = floor(x·x / 2^F)`. Then the Taylor series, term by term, each new term
   `floor(floor(prev·x2 / 2^F) / (m·(m + 1)))`, summed with alternating signs until a term
   is 0:
   - `sin`: starts at `x` with `m = 2, 4, 6, …`;
   - `cos`: starts at `2^F` with `m = 1, 3, 5, …`.
   Every term is non-negative, so floor and truncation agree.
4. The quadrant by symmetry: `q = 0 → (c, s)`, `1 → (−s, c)`, `2 → (−c, −s)`, `3 → (s, −c)`.
5. Each component `v/2^F` rounded once to float64, to nearest, ties to even (the orbit
   samples' rounding, [deep-zoom.md](deep-zoom.md)). A zero is `+0.0`.

Quarter turns are exact: `r = 0` gives `x = 0`, so `(1, 0)`, `(0, 1)`, `(−1, 0)` and
`(0, −1)`. The truncations leave each fixed-point value within a few units of `2^−192` of
the true one, so the result is the correctly rounded double unless the true value lies
within about `2^−130` (relative) of a rounding midpoint; measured correctly rounded on
every `k` for every `n ≤ 512` and on 50,000 random `(k, n)` with `n < 2^50`.

## Known answers

`vectors/turns/known-answers` pins `cis_turns` at quarter turns, thirds and sixths (where
the true value is exactly `±1/2`), `k` negative and past `n`, and large `n`.
