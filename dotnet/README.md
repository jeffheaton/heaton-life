# heaton-life — .NET implementation

The C# port, mirroring the Python implementation family by family against the
shared specs and conformance vectors. **No native plugins — pure C# only**, so
Unity IL2CPP/WebGL/mobile all work.

## Status

| Piece | State |
|---|---|
| `Pcg32` (spec/rng.md, known-answer tested) | ✅ |
| Life-like CA + soup init | ✅ bit-exact against `vectors/lifelike/` |
| Elementary, Cyclic, Wireworld, MergeLife | ✅ bit-exact; MergeLife also replays `vectors/mergelife-upstream/` (byte-identical with the upstream engines) |
| Gray-Scott, Lenia ×3, Boids (ε tier) | ✅ within ε (pure-C# radix-2/Bluestein FFT for Lenia) |
| Fractals (T0 float64 + T1 perturbation consuming vector orbits) | ✅ bit-exact incl. the zoom-1e14 deep-zoom replay |
| Colormaps / render (spec/render.md) | ✅ byte-identical LUTs, frame indexing, per-family `WriteFrame` (incl. boids rasterizer + fractal smooth coloring), RGB/RGBA32 output |
| `ISimulation` + frame-source interfaces | ✅ the polymorphic surface a host (playground/Unity) drives |
| Evolve: paper objective + GA (spec/evolve.md) | ✅ bit-exact, incl. a replayed end-to-end mini evolution run |
| Patterns: RLE (both dialects), transforms, extract/stamp (spec/patterns.md) | ✅ bit-exact, Golly-compatible |
| Unity hand-off | ✅ `HeatonLife.Core.dll` built by `python/tools/build_unity_dll.py` for the heaton-life-unity repo, with `InternalsVisibleTo` for its conformance suite and self-check |

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

RNG → Life-like → remaining discrete CAs → continuous grids → fractals → boids →
render → evolve — **complete**; every stage landed with its conformance replay
green. The spec (`../spec/`) is the authority; when C# and Python disagree, the
vectors decide. Reference-orbit *generation* now runs on the C# side too
(`ReferenceOrbit`, fixed point over `System.Numerics.BigInteger` — the option
spec/deep-zoom.md sanctions), so the perturbation tier no longer depends on an
externally supplied orbit; it still accepts one, which is how the conformance
replay works. Pinned by regenerating the shipped `orbit.c128` byte for byte. The Unity app
(heaton-life-unity, its own repo) consumes this library as a compiled DLL.
