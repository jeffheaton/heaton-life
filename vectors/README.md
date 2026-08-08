# Conformance vectors

Golden test data shared by every implementation. CI for each language runs its implementation against these files; discrete CAs must match bit-for-bit, float families within the ε declared in the family's spec page.

## Layout

```
vectors/<family>/<case-name>/
├── params.json      # full params + seed + steps + expected-state manifest
├── state_00000.png  # initial state (discrete families: lossless PNG, one byte/channel per cell)
├── state_00100.png  # expected state after 100 steps
└── state_00100.f64  # float families: raw little-endian float64, shape in params.json
```

- Discrete grids → PNG (lossless, human-viewable, both stacks read it).
- Float fields → raw little-endian f64 (C order); each checkpoint entry carries `"shape"`,
  and the case's `params.json` carries `"epsilon"` (max abs deviation for cross-language
  replay; same-language replay is exact).
- Fractal cases → viewport JSON + iteration-count grids (+ reference orbit as raw f64 pairs for deep-zoom cases).

Vectors are versioned with the spec: `params.json` carries `"spec_version"`. Regenerating a vector requires a spec-change justification in the PR.
