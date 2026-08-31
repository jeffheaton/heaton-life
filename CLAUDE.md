# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

heaton-life is a spec-first, multi-language library of emergence algorithms — cellular automata (MergeLife, Life-like, Elementary, Cyclic, Wireworld), Lenia ×3, fractals (Mandelbrot/Julia/Burning Ship/Newton with perturbation deep zoom), Reynolds boids (one d-dimensional algorithm, 2D and 3D), and Gray-Scott reaction-diffusion — plus rendering, and the MergeLife genetic evolver. Monorepo components:

- **`spec/`** — language-neutral algorithm specifications; the source of truth all implementations conform to
- **`vectors/`** — golden conformance vectors (params + expected states) shared by every implementation
- **`python/`** — Python implementation (NumPy) + PyQt6 playground app; the reference implementation
- **`dotnet/`** — C#/.NET port (`HeatonLife.Core`, netstandard2.1, zero dependencies); full parity with Python

## The Determinism Contract (read before changing any algorithm)

This repo's identity is that Python and .NET produce **the same output** for the same `(params, seed)`:

- The **spec wins**; when an implementation and the spec disagree, the implementation is wrong (or the spec gets fixed deliberately).
- The **vectors decide** disputes between implementations. Bit-exact tiers must match byte-for-byte; ε tiers within the per-family tolerance in `params.json`.
- **All simulation randomness flows through PCG32** (`spec/rng.md`). Never numpy RNG, never `System.Random`; seeding and draw order are part of each family's spec.
- **Never regenerate existing vectors casually** — they are the cross-language contract. Regenerate only when a deliberate spec change justifies it. New families/cases are added additively: append their `write_case(...)` calls to `python/tools/gen_vectors.py`, run it, and confirm with `git status vectors/` that only the new case directories changed (the script has no section selector and regenerates every family except `png-io`, whose `write_png_io_cases()` is deliberately left out of `main()` because PNG bytes are encoder-specific and is run by hand; existing vectors must come back byte-identical). `vectors/mergelife-upstream/` tracks the upstream repo and is never regenerated here.

**Parity change protocol** — an algorithm/behavior change touches, in order:
1. `spec/` page + `python/` implementation (+ additive vectors if new surface),
2. `dotnet/` port (expression-for-expression where a bit-exact tier applies),
3. both suites green: Python pytest and `dotnet test`.

### Float-determinism gotchas (hard-won; do not "clean up")

- **Powers of ten in the fractal pixel scale flow through `spec/pow10.md`'s
  integer algorithm** (`heaton_life.core.pow10` / C# `Pow10.Compute`), never
  libm `pow`/`log10` or numpy `10**`. Platform libms differ in the last ulp at
  fractional zooms (Windows UCRT vs macOS libm vs numpy's vendored routines —
  measured 2026-08-21 as flipped escape counts in a bit-exact vector), so the
  historical `10^(log10(4/width) − zoom)` expression is forbidden.
- NumPy 2.x contracts complex multiplies into FMAs: real = `fma(a,c,−bd)`, imag = `fma(a,d,bc)`. The C# side mirrors this exactly via `FractalEngine.ComplexMul`/`Fma` (software fma — netstandard2.1 has no intrinsic) at the sites where NumPy runs its multiply ufunc, and **only** there. Real-array NumPy ufunc chains never contract across calls, so expression-shape porting elsewhere is safe without fma.
- `np.round` and the colormap/interp rounding are **half-even** (banker's); C# `Math.Round` default matches.
- Operation order is spec'd where it matters (e.g. the Gray-Scott Laplacian `((N+S)+W)+E − 4C`); port expression shapes literally.
- MergeLife's numerics (stable sort by limit alone, mode-padded neighbor sum, 127/128 percent scaling, floor semantics) are the upstream cross-engine contract — byte-identical with github.com/jeffheaton/mergelife.

## Important: Always Use the venv

The Python component uses `python/.venv` (note: `.venv`, not `venv`). **Never install packages or run tools with system Python.** All commands below assume `cd python`.

## Commands

### python/ (reference implementation + playground)

```bash
cd python

# Lint, types, tests — what the Build Library workflow runs
.venv/bin/ruff check src tests tools
.venv/bin/ruff format --check src tests tools   # advisory in CI; format the files you touch
.venv/bin/mypy
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q

# Run the playground app
.venv/bin/heaton-life

# Regenerate the README gallery image
.venv/bin/python tools/gen_gallery.py

# Vector generation — see the regen policy above before running anything here
.venv/bin/python tools/gen_vectors.py
```

### dotnet/ (C# library)

Requires the .NET 10 SDK; no venv.

```bash
# Formatting gate (fatal in CI); `dotnet format dotnet/HeatonLife.slnx` fixes what it reports
dotnet format dotnet/HeatonLife.slnx --verify-no-changes

# Tests (replays the shared conformance vectors)
dotnet test dotnet --nologo

# Release build (single dependency-free netstandard2.1 assembly) and a local package to
# try as a user would (see dotnet/DEVELOPMENT.md, "The checks")
dotnet build dotnet/src/HeatonLife.Core -c Release
dotnet pack dotnet/src/HeatonLife.Core -c Release -o dotnet/nupkgs -p:Version=1.0.1-local   # a version not on NuGet.org, so the package cache cannot substitute the published one
```


## CI / releases (manually dispatched, the dynaface shape)

Nothing runs on push. Three `workflow_dispatch` workflows in `.github/workflows/`:

- **Build Library** (`build-lib.yml`, Python): ruff/mypy reports (advisory), pytest
  with JUnit + coverage (fatal; the 60% coverage-threshold step is advisory), a regenerated `src/heaton_life/version.py` build
  stamp, the wheel → `twine check` → artifact → `s3://data.heatonresearch.com/library/`.
- **Deploy Library to PyPI** (`deploy-lib.yml`): takes a wheel file name, pulls it
  from that S3 prefix, uploads to PyPI.
- **Build Library (.NET)** (`build-lib-dotnet.yml`): `dotnet format` gate, vulnerable
  package report (advisory), a regenerated `src/HeatonLife.Core/Version.cs`, Release
  build, xunit with TRX, the DLL zip → artifact → S3, and `dotnet pack` (package + `.snupkg` symbols) → NuGet.org via
  Trusted Publishing (OIDC; no stored API key).

Versions live in six places that move together: `python/pyproject.toml` ↔
`heaton_life.__version__` (the build fails if they disagree), the tracked
`src/heaton_life/version.py` baseline, `<Version>` in `HeatonLife.Core.csproj`, the tracked
`Version.cs` baseline, and the `heaton-life-dotnet-<version>.zip` link under "Install" in
`dotnet/README.md` (that README is packed into every NuGet package). The baselines (BUILD 0)
exist so the stamp always exists in local builds; CI overwrites them. The step-by-step
release checklists (`gh workflow run build-lib.yml` → `gh workflow run deploy-lib.yml -f
whl_file=…`; `gh workflow run build-lib-dotnet.yml`) are in `python/DEVELOPMENT.md` and
`dotnet/DEVELOPMENT.md`, "Releasing". Secrets on the repo: `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`, `PYPI_API_TOKEN` (should be scoped to
the `heaton-life` PyPI project; 1.0.0 was uploaded with an account-scoped token, see
python/DEVELOPMENT.md, "Releasing"). NuGet pushes through the existing Trusted Publishing policy
`heaton-life-dotnet` on the `jeffheaton` NuGet.org account (bound to `jeffheaton/heaton-life`
and the workflow file `build-lib-dotnet.yml`; policies are account-level, not per package;
used for 1.0.0) — if `NuGet/login` fails with `No matching trust policy`, check that policy
before creating another (see dotnet/DEVELOPMENT.md, "Releasing"). `python/LICENSE` is a
copy of the root `LICENSE` (hatchling cannot embed `../LICENSE` into the wheel); change both
together.

## Code Style

- **Python**: ruff (line length 100), mypy `strict`; params are frozen dataclasses with UI metadata; every family follows the `Simulation` protocol (`step/reset/state/frame`) in `core/protocols.py`.
- **C#**: Allman braces, XML doc comments that cite the spec page each class implements; `HeatonLife.Core` stays netstandard2.1 with **zero dependencies** (no Regex, no LINQ in Core, no JSON — parsing lives in test projects); zero-allocation step/frame APIs (`WriteFrame` into caller buffers).
- **American English everywhere** — identifiers, comments, docstrings, XML docs, spec pages, READMEs, commit messages, UI strings. `color`/`center`/`neighbor`/`behavior`/`gray`/`normalize`/`analyze`/`modeled`, never the `-our`/`-tre`/`-ise`/`-yse`/`-lled` British forms. The only exception is spelling dictated by an external API being called (none today).
- Cross-cutting: nothing merges without its spec page and vectors; the playground/app consumes only the public API — if it needs a hack, the API is wrong.
