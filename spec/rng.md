# RNG: PCG32 (pinned)

All randomness that touches simulation state flows through this generator. Native RNGs
(numpy, `System.Random`) are forbidden for state so that runs replay identically across languages.

## Algorithm

PCG32, XSH-RR variant, matching the `pcg_basic` reference implementation. All arithmetic mod 2⁶⁴.

```
MULT = 6364136223846793005

seed(initstate, initseq):          # initseq defaults to 0
    state = 0
    inc   = (initseq << 1) | 1
    next_u32()
    state = state + initstate
    next_u32()

next_u32():
    old        = state
    state      = old * MULT + inc
    xorshifted = uint32(((old >> 18) XOR old) >> 27)
    rot        = old >> 59
    return (xorshifted >> rot) | (xorshifted << ((32 - rot) & 31))
```

## Known-answer test

Every implementation must assert: `seed(42, 54)` produces, in order:

```
0xA15C02B7  0x7B47F409  0xBA1D3330  0x83D2F293  0xBFA4784B  0xCBED606E
```

## Draw-order convention

Grid fills consume exactly `width * height` draws in row-major order (y outer, x inner),
regardless of any masks applied afterward — see each family's init spec.

## Presentation noise

Dithering a picture ([render.md](render.md) "Phase lookup") is not simulation
randomness, and does not use PCG32: it has no state and no draw order. Each value is a
pure function of the pixel's column `x`, row `y`, the frame index and the channel, so
rows can be colored in any order or in parallel with the same result. It is Chris
Wellons' `triple32` hash, as Heaton Fractal uses it:

```
triple32(x):                                    all arithmetic mod 2³²
    x ^= x >> 17;  x *= 0xED5AD4BB
    x ^= x >> 11;  x *= 0xAC4C1B51
    x ^= x >> 15;  x *= 0x31848BAB
    x ^= x >> 14
    return x

seed = (x·0x9E3779B9) ⊕ (y·0x85EBCA6B) ⊕ (frame·0xC2B2AE35) ⊕ (channel·0x27D4EB2F)   mod 2³²
D    = triple32(seed) − triple32(seed ⊕ 0x68BC21EB)          an exact integer in (−2³², 2³²)
```

`D·2⁻³²` is exact and triangularly distributed on `(−1, 1)`. Inputs: `0 ≤ x, y`,
`0 ≤ channel ≤ 2`, `0 ≤ frame < 2³²`. In Python the products are uint32 array
multiplies (or integers masked with `0xFFFFFFFF` before the XOR).

Known answers — every implementation must assert them:

```
triple32(0) = 0x00000000   triple32(1) = 0x042741D6   triple32(2) = 0xF1DFE8E9
triple32(0x68BC21EB) = 0xA5D6919E   triple32(0xDEADBEEF) = 0x0921725E
D(x=0, y=0, frame=0, channel=0) = −2782302622      D(0, 0, 0, 1) = −3302658959
D(0, 0, 0, 2) = 239395147     D(1, 0, 0, 0) = 964350720     D(0, 1, 0, 0) = 179844703
D(3, 5, 7, 1) = −3366029565
```
