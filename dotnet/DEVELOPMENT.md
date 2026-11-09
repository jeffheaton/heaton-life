# Developing heaton-life (.NET)

This guide is for working on the library itself. If you only want to use it, the
[README](README.md) covers installation and the API.

The .NET library is one part of a larger repository. The algorithm specifications
(`../spec/`), the golden conformance vectors (`../vectors/`), and the Python
implementation (`../python/`) sit beside it, and the tests here read the vectors
directly, so work from a full clone rather than from the NuGet package. The
[Python development guide](../python/DEVELOPMENT.md) describes the rules the two
implementations share; this one covers what is specific to the C# side.

## Prerequisites

- The .NET 10 SDK (the workflow uses `10.0.x`; there is no `global.json`).
- A clone of the repository:

  ```
  git clone https://github.com/jeffheaton/heaton-life.git
  cd heaton-life/dotnet
  ```

Nothing else. `HeatonLife.Core` has no package dependencies; the test project pulls
xunit from NuGet on its first restore.

## Layout

```
dotnet/
├── HeatonLife.slnx                  # the solution: the library and its tests
├── src/HeatonLife.Core/             # the library, netstandard2.1, zero dependencies
│   ├── HeatonLife.Core.csproj       # <Version> and the NuGet metadata; packs README.md and the icon
│   ├── Version.cs                   # build stamp (see Versioning)
│   └── *.cs                         # one file per family or engine, all in the HeatonLife namespace
└── tests/HeatonLife.Core.Tests/     # xunit, net10.0
    ├── ConformanceTests.cs          # replays the repo's vectors/: bit-exact tiers byte for byte, epsilon tiers within tolerance
    ├── Png.cs                       # dependency-free reader for the vector PNGs
    └── *Tests.cs                    # per-family unit tests and the remaining vector replays
```

Grids are flat, row-major arrays that share the exact memory layout of the Python
arrays and the vector files, so a state can move between the two implementations and
the vectors without reshaping.

## The checks

These commands are what the Build Library (.NET) workflow runs; keep them green
before committing.

```
dotnet restore HeatonLife.slnx
dotnet format HeatonLife.slnx --verify-no-changes
dotnet build HeatonLife.slnx -c Release --no-restore
dotnet test tests/HeatonLife.Core.Tests/HeatonLife.Core.Tests.csproj -c Release --no-build
```

- **`dotnet format`** is a fatal gate in CI. `dotnet format HeatonLife.slnx` (without
  `--verify-no-changes`) fixes what it reports.
- **The tests** take a few seconds and replay every conformance vector; from the
  repository root, `dotnet test dotnet --nologo` is the short form.
- **The HashLife giants** (the Caterpillar and Annelid; `HashLifeGiantTests.cs`) run only
  when `HEATON_LIFE_PATTERNS` names the cache that `../python/tools/fetch_patterns.py`
  fills, and report as skipped otherwise. Neither file has a stated license, so neither is
  committed. With the cache in place they take about half a minute (the test build is
  Debug; a Release build runs each period in about 5 s) and under 1 GB of memory.
- The workflow also runs an advisory vulnerable-package report over the test
  project's dependencies, the only place a package could enter:
  `dotnet list tests/HeatonLife.Core.Tests/HeatonLife.Core.Tests.csproj package --vulnerable --include-transitive`.
- To try the package as a user would, pack it at a version that is not on NuGet.org so
  the global package cache cannot substitute the published one, and that you have not
  packed before, since the cache keeps the first package it restores at a version:
  `dotnet pack src/HeatonLife.Core -c Release -o nupkgs -p:Version=1.1.1-local.1`, then
  `dotnet add package HeatonLife.Core --version 1.1.1-local.1 --source ./nupkgs` in a
  fresh project (`nupkgs/` is ignored by git). Count the last number up for each trial,
  or delete `~/.nuget/packages/heatonlife.core/*-local*` first.

## How the library is built: the spec decides

The rules in the Python guide's
["the spec decides"](../python/DEVELOPMENT.md#how-the-library-is-built-the-spec-decides)
section apply in full here: the specification wins, the vectors decide disputes,
all randomness flows through PCG32 (`Pcg32`, `../spec/rng.md`; never
`System.Random`), and existing vectors are never regenerated casually. Changes
travel in order, spec page, then the Python implementation (plus additive vectors
if there is new surface), then this port, with both test suites green.

What that means for C# specifically:

- **Port expression for expression** wherever a bit-exact tier applies, and keep the
  operation order the spec gives (for example the Gray-Scott Laplacian
  `((N + S) + W) + E - 4C`). Restructuring an expression that is algebraically
  equivalent can still change the last bit.
- **Powers of ten** in the fractal pixel scale go through `Pow10.Compute`
  (`../spec/pow10.md`), never `Math.Pow` or `Math.Log10`. Platform math libraries
  differ in the last bit at fractional zooms, and that flips escape counts.
- **NumPy (2.0.2 and later) fuses complex multiplies into FMAs.** The fractal engine mirrors that
  with a software fused multiply-add at exactly the sites where NumPy contracts, and
  only there (`netstandard2.1` has no FMA intrinsic). Do not restructure the complex
  arithmetic in `FractalEngine` or `Perturbation`. The software fma is a real one —
  Dekker's transforms where they are exact, an exact integer sum rounded once below
  `|a·b| = 2^-968` (deep Julia gets there) — and a test pins it bitwise against
  `Math.FusedMultiplyAdd` over every exponent.
- **The reference orbit is spec'd arithmetic**, not just a result: fixed point with
  the spec's working precision, ties-away products, one correct rounding per sample
  (`../spec/deep-zoom.md`, "Reference orbit"). Python runs the same integer operations.
- **A center's float64 projection** (T0) is the correctly rounded decimal-to-double
  conversion in `DecimalText` — never `double.Parse`, which Mono and IL2CPP do not
  guarantee, and never a rounding of the orbit's fixed point.
- **Rounding is half-even**, which is `Math.Round`'s default, matching `np.round`.
- **MergeLife's numerics** (stable sort by limit alone, mode-padded neighbor sums,
  the 127/128 percent scaling, floor semantics) are the cross-engine contract with
  the upstream MergeLife project and are replayed byte for byte from
  `../vectors/mergelife-upstream/`.
- **Curated content** (Gray-Scott presets, the MergeLife gallery, built-in patterns)
  is part of the cross-implementation contract: it is listed in the spec and pinned
  by tests in both ports.

## Parity with Python

Every family replays the shared vectors; the table records which tier each one
meets.

| Piece | State |
|---|---|
| `Pcg32` (`../spec/rng.md`, known-answer tested) | ✅ |
| Life-like CA + soup init | ✅ bit-exact against `../vectors/lifelike/` |
| Elementary, Cyclic, Wireworld, MergeLife | ✅ bit-exact; MergeLife also replays `../vectors/mergelife-upstream/` (byte-identical with the upstream engines) |
| Gray-Scott, Lenia ×3, Boids (ε tier) | ✅ within ε (pure-C# radix-2/Bluestein FFT for Lenia) |
| Fractals (T0 float64 + T1 perturbation) | ✅ bit-exact incl. the deep-zoom replays (Mandelbrot 1e14, 1e20 with a 256-place center, 1e280; Julia 1e13 with critical-orbit rebasing) and a deep Julia smooth render |
| Colormaps / render (`../spec/render.md`) | ✅ byte-identical LUTs, frame indexing, per-family `WriteFrame` (incl. boids rasterizer + fractal smooth coloring), RGB/RGBA32 output |
| `ISimulation` + frame-source interfaces | ✅ the C# side of Python's `Simulation` protocol; the polymorphic surface a host (e.g. a Unity adapter) drives |
| Evolve: paper objective + GA (`../spec/evolve.md`) | ✅ bit-exact, incl. a replayed end-to-end mini evolution run |
| Patterns: RLE (both dialects), transforms, extract/stamp (`../spec/patterns.md`) | ✅ bit-exact, Golly-compatible |
| HashLife: the unbounded universe, Macrocell, sparse `#CXRLE` RLE, views and frames (`../spec/hashlife.md`, `../spec/macrocell.md`) | ✅ bit-exact against `../vectors/hashlife/`; the giant patterns behind `HEATON_LIFE_PATTERNS` |

The port landed in the order RNG → Life-like → remaining discrete CAs → continuous
grids → fractals → boids → render → evolve, each stage with its conformance replay
green. Reference-orbit *generation* runs on the C# side too (`ReferenceOrbit`,
fixed point over `System.Numerics.BigInteger`, the normative arithmetic of
`../spec/deep-zoom.md` that the Python reference runs as well), so the perturbation
tier does not depend on an externally supplied orbit; it still accepts one, which is
how the conformance replay works. The tests regenerate every stored `orbit.c128` and
`critical.c128` byte for byte, and check the SHA-256 of a 139,166-sample orbit too
long to ship.

## Adding a family

The spec page and the Python implementation (with its vectors) come first; see
["Adding or changing a family"](../python/DEVELOPMENT.md#adding-or-changing-a-family).
On this side:

1. Add `src/HeatonLife.Core/<Family>.cs` in the `HeatonLife` namespace: a constructor
   taking the spec's parameters (with the Python defaults), `ISimulation` (`Width`,
   `Height`, `Generation`, `Step`, `Reset`), and exactly one of `IIndexedFrameSource`,
   `IFloatFrameSource`, or `IRgbFrameSource` with a zero-allocation `WriteFrame`
   (fractals are renderers instead: `Render(width, height, viewport)` returning
   doubles in `[0, 1]`). Seeding draws from `Pcg32` in the order the spec gives, and
   the class's XML doc comment cites the spec page.
2. Wire it into the conformance replay in `tests/HeatonLife.Core.Tests/ConformanceTests.cs`:
   its family name in `ByteFamilies` or `FloatFamilies`, a case in `BuildSim` or
   `BuildFloatSim` that constructs it from `params.json`, and (for byte families) the
   pixel decoding in `DecodeState`. Cases under `../vectors/<family>/` are then
   discovered automatically.
3. Add it to `AllFamilies()` in `ApiConsistencyTests.cs` (the host-facing contract:
   interfaces, constructor defaults, RGBA paths) and, if it has a frame-indexing rule
   in `../spec/render.md`, to `RenderConformanceTests.cs`.
4. Pin any curated content (presets, galleries, built-in patterns) with a test, as
   the Python side does; it is part of the contract but not a vector.
5. Run the checks; the port is done when the new vectors replay within their tier.

## Code style

- Allman braces, and `dotnet format` clean (the CI gate).
- XML doc comments cite the spec page a class implements, so readers can find the
  contract it honors. `CS1591` is off: undocumented public members are fine.
- `HeatonLife.Core` stays `netstandard2.1` with **zero dependencies**: no
  `Regex`, no LINQ, no JSON in the library (parsing lives in the test project), and
  C# 9 language features only.
- Zero-allocation step and frame APIs: `WriteFrame` writes into caller-owned
  buffers, and the `Colormaps.Apply*` overloads that take an output buffer do the
  same. Allocating `Frame()` conveniences exist beside them.
- Nullable reference types are enabled.
- Hosts build on the public API. The one `InternalsVisibleTo` grant in the csproj is
  this repo's own test project (`HeatonLife.Core.Tests`). A host proves its runtime with
  the public `SelfCheck` ([spec/self-check.md](../spec/self-check.md)) and replays
  vectors through public members; the Unity app's EditMode suite and on-device check
  have needed no grant since 2026-09-24.
- Nothing merges without its spec page and vectors.

## Versioning

`<Version>` in `src/HeatonLife.Core/HeatonLife.Core.csproj` is the package version.
The version lives in six places that move together: that one, the `Version` constant
in the `Version.cs` baseline, and the `heaton-life-dotnet-<version>.zip` link in
`README.md`; and in Python, `version` in `../python/pyproject.toml`, `__version__`,
and the `version.py` baseline. `../python/tests/test_release_version.py` fails unless
all six agree.

`src/HeatonLife.Core/Version.cs` is the build stamp that ships inside the assembly
(`HeatonLifeVersion.Version`, `BuildDate`, and `Build`). The tracked file is a
baseline with `Build = 0`, meaning a local build, so the class always exists; the
workflow regenerates it with the run number and date before building.

## Releasing

[`../RELEASING.md`](../RELEASING.md) is the whole sequence, for both packages: the
release convention's two manual steps, **Build Library (.NET)**
(`.github/workflows/build-lib-dotnet.yml`), which tests, stamps `Version.cs`, packs and
stages `heaton-life-dotnet-<version>.zip`, `HeatonLife.Core.<version>.nupkg` and
`.snupkg` and a build record on `s3://data.heatonresearch.com/library/`, then **Deploy
Library to NuGet (.NET)** (`.github/workflows/deploy-lib-dotnet.yml`), which pushes
what was staged to NuGet.org by Trusted Publishing and tags `v<version>` at the built
commit. **Test Library (.NET)** (`test-lib-dotnet.yml`) runs the suite on Linux, macOS
and Windows on every push that touches `dotnet/` or `vectors/`.

The build checks, before it builds anything, that the csproj `<Version>` agrees with
`pyproject.toml` and with the zip link under "Install" in `README.md`: that README is
frozen into the immutable package and this workflow runs no Python, so
`../python/tests/test_release_version.py` never sees a .NET-only build. The package's
README and icon are frozen into each version, so update `README.md` first if the API or
the sample changed.

The NuGet.org Trusted Publishing policy is `heaton-life-dotnet` on the `jeffheaton`
account (Account → Trusted Publishing). It published 1.0.0 and 1.1.0 from the old
`build-lib-dotnet.yml`; it must name `deploy-lib-dotnet.yml` now (RELEASING.md,
"One-time setup"). Without a matching policy the login step fails with
`No matching trust policy owned by user '…' was found`.
