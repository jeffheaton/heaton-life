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
