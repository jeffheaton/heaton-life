# heaton-life — .NET implementation

The C# port, mirroring the Python implementation family by family against the
shared specs and conformance vectors. **No native plugins — pure C# only**, so
Unity IL2CPP/WebGL/mobile all work.

## Status

| Piece | State |
|---|---|
| `Pcg32` (spec/rng.md, known-answer tested) | ✅ |
| Life-like CA + soup init | ✅ bit-exact against `vectors/lifelike/` |
| Elementary, Cyclic, Wireworld, MergeLife | next (MergeLife can also replay `vectors/mergelife-upstream/`) |
| Gray-Scott, Lenia ×3, Boids (ε tier) | planned |
| Fractals (perturbation loop is plain doubles; orbits consumable from vectors) | planned |
| `HeatonLife.Unity` UPM adapter | planned |

## Layout

- `src/HeatonLife.Core/` — engine-agnostic class library, `netstandard2.1`
  (the profile Unity supports). Flat 1-D row-major arrays, zero-allocation
  step API; grids share the exact memory layout of the Python arrays and the
  vector files.
- `tests/HeatonLife.Core.Tests/` — xunit; includes a dependency-free reader
  for the vector PNGs (8-bit grayscale) and the conformance runner that replays
  `../vectors/` byte-for-byte.

## Running

```bash
dotnet test dotnet
```

## Porting order (mirrors the Python phases)

RNG → Life-like → remaining discrete CAs → continuous grids → fractals → boids,
each landing only with its conformance replay green. The spec (`../spec/`) is the
authority; when C# and Python disagree, the vectors decide.
