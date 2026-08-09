# PNG grid I/O (MergeLife)

MergeLife worlds import from and export to PNG images at an integer scale
`k ≥ 1`: an export renders each cell as a solid `k×k` pixel block; an import
recovers one cell per block. This page defines **grid-level** semantics. PNG
*bytes* are not part of the cross-language contract — encoders differ — the
decoded grids are (bit-exact tier).

## Decode (import)

- Accepted input: 8-bit PNG, color type 2 (truecolor RGB) or 6 (truecolor with
  alpha — the alpha channel is discarded). Palette, grayscale, and 16-bit
  inputs are rejected with an error. Interlaced input MAY be rejected (the C#
  implementation rejects it; the Python reference's decoder happens to accept
  it; conformance vectors never use it).
- With scale `k`: the image's width and height must be exact multiples of `k`,
  else an error. The decoded grid is `(W/k) × (H/k)` and cell `(x, y)` takes
  the pixel at `(x·k, y·k)` — the **top-left of its block**. Exports write
  uniform blocks, so any in-block choice would agree on round trips; top-left
  is the normative rule for foreign images.
- `k = 1` is a plain pixel-per-cell import.

## Encode (export)

- Output: 8-bit truecolor RGB, non-interlaced; each cell becomes a solid
  `k×k` block. (The C# encoder writes scanline filter 0; encoders are
  otherwise free — see the bytes caveat above.)

## The round-trip law (normative)

For every grid `g` and every `k ≥ 1`:

```
decode(encode(g, k), k) == g     (bit-exact)
```

## Conformance

`vectors/png-io/` pins decodes: `input.png` + `scale` → the expected grid
(stored as a plain RGB `grid.png`, read by each suite's independent PNG
reader). The round-trip law is asserted per implementation in unit tests;
PNG bytes are never compared across implementations.
