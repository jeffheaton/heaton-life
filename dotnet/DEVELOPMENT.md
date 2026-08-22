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
- The workflow also runs an advisory vulnerable-package report over the test
  project's dependencies, the only place a package could enter:
  `dotnet list tests/HeatonLife.Core.Tests/HeatonLife.Core.Tests.csproj package --vulnerable --include-transitive`.
- To try the package as a user would: `dotnet pack src/HeatonLife.Core -c Release -o nupkgs`,
  then `dotnet add package HeatonLife.Core --source ./nupkgs` in a fresh project.

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
- **NumPy 2.x fuses complex multiplies into FMAs.** The fractal engine mirrors that
  with a software fused multiply-add at exactly the sites where NumPy contracts, and
  only there (`netstandard2.1` has no FMA intrinsic). Do not restructure the complex
  arithmetic in `FractalEngine` or `Perturbation`.
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
| Fractals (T0 float64 + T1 perturbation) | ✅ bit-exact incl. the zoom-1e14 deep-zoom replay |
| Colormaps / render (`../spec/render.md`) | ✅ byte-identical LUTs, frame indexing, per-family `WriteFrame` (incl. boids rasterizer + fractal smooth coloring), RGB/RGBA32 output |
| `ISimulation` + frame-source interfaces | ✅ the C# side of Python's `Simulation` protocol; the polymorphic surface a host (e.g. a Unity adapter) drives |
| Evolve: paper objective + GA (`../spec/evolve.md`) | ✅ bit-exact, incl. a replayed end-to-end mini evolution run |
| Patterns: RLE (both dialects), transforms, extract/stamp (`../spec/patterns.md`) | ✅ bit-exact, Golly-compatible |

The port landed in the order RNG → Life-like → remaining discrete CAs → continuous
grids → fractals → boids → render → evolve, each stage with its conformance replay
green. Reference-orbit *generation* runs on the C# side too (`ReferenceOrbit`,
fixed point over `System.Numerics.BigInteger`, the option `../spec/deep-zoom.md`
sanctions), so the perturbation tier does not depend on an externally supplied
orbit; it still accepts one, which is how the conformance replay works. It is
pinned by regenerating the shipped `orbit.c128` byte for byte.

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
- Hosts build on the public API. The `InternalsVisibleTo` grants in the csproj
  (`HeatonLife.Core.Tests`, `HeatonLife.Core.EditorTests`, `HeatonLife.Unity`) exist
  so that the conformance and self-check code in those assemblies can replay the
  vectors against internals such as the fractal engine's FMA helper; they are not a
  license to depend on internals.
- Nothing merges without its spec page and vectors.

## Versioning

`<Version>` in `src/HeatonLife.Core/HeatonLife.Core.csproj` is the package version,
and it is bumped in step with `version` in `../python/pyproject.toml` and
`__version__` in the Python package.

`src/HeatonLife.Core/Version.cs` is the build stamp that ships inside the assembly
(`HeatonLifeVersion.Version`, `BuildDate`, and `Build`). The tracked file is a
baseline with `Build = 0`, meaning a local build, so the class always exists; the
workflow regenerates it with the run number and date before building.

## Releasing

One manually dispatched GitHub workflow, **Build Library (.NET)**
(`.github/workflows/build-lib-dotnet.yml`), the same shape as dynaface's. Nothing
runs on push. In order: restore, the `dotnet format` gate, the vulnerable-package
report (advisory), the regenerated `Version.cs`, the Release build, the xunit suite
(published as a test report), then `heaton-life-dotnet-<version>.zip` (DLL + XML
docs + PDB) as the `heaton-life-dotnet-dll` workflow artifact and a public copy on
`s3://data.heatonresearch.com/library/`, then `dotnet pack`, whose
`HeatonLife.Core.<version>.nupkg` is uploaded as the `heaton-life-nupkgs` artifact,
and finally the push of that package to NuGet.org. Pushes use `--skip-duplicate`, so
re-running at an already-published version is a no-op rather than an error.

The push uses **Trusted Publishing**, so there is no long-lived API key stored in
the repository: the `NuGet/login` action exchanges the job's short-lived GitHub OIDC
token (the workflow grants `id-token: write`) for a temporary NuGet.org API key.
Its `user:` input is the NuGet.org account that *created* the policy. One-time
setup on NuGet.org (Account → Trusted Publishing): add a policy bound to the GitHub
repository owner `jeffheaton`, the repository `heaton-life`, and the workflow file
`build-lib-dotnet.yml` (the file name, not the workflow's display name). Without a
matching policy the login step fails with
`No matching trust policy owned by user '…' was found`. If NuGet.org lists a newly
created policy as pending, running the workflow activates it.

Repository secrets for the S3 copy: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`AWS_DEFAULT_REGION`.

Release checklist:

1. Bump `<Version>` in the csproj (in step with the Python version) and the version
   in the `heaton-life-dotnet-<version>.zip` link under "Install" in `README.md`. The
   package README and icon are frozen into each version, so also update `README.md`
   first if the API or the sample changed.
2. Run the checks locally, commit, and push.
3. Dispatch the workflow:

   ```
   gh workflow run build-lib-dotnet.yml -R jeffheaton/heaton-life
   ```

   The same run builds, tests, and publishes. To try a package before it goes
   public, pack it locally (see "The checks") and install it from that folder into
   a fresh project.
4. Check the run; its `heaton-life-nupkgs` artifact is the exact package that was
   pushed. NuGet versions are immutable: anything that needs changing after the push
   becomes the next version.
