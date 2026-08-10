# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

heaton-life is a spec-first, multi-language library of emergence algorithms — cellular automata (MergeLife, Life-like, Elementary, Cyclic, Wireworld), Lenia ×3, fractals (Mandelbrot/Julia/Burning Ship/Newton with perturbation deep zoom), Reynolds boids (one d-dimensional algorithm, 2D and 3D), and Gray-Scott reaction-diffusion — plus rendering, and the MergeLife genetic evolver. Monorepo components:

- **`spec/`** — language-neutral algorithm specifications; the source of truth all implementations conform to
- **`vectors/`** — golden conformance vectors (params + expected states) shared by every implementation
- **`python/`** — Python implementation (NumPy) + PyQt6 playground app; the reference implementation
- **`dotnet/`** — C#/.NET port (`HeatonLife.Core`, netstandard2.1, zero dependencies); full parity with Python
- **`heaton-life-unity/`** — Unity 6 app (the deep user-facing app, successor to the playground); embeds the C# core as a source-synced package; see `heaton-life-unity/CLAUDE.md`

## The Determinism Contract (read before changing any algorithm)

This repo's identity is that Python, .NET, and Unity produce **the same output** for the same `(params, seed)`:

- The **spec wins**; when an implementation and the spec disagree, the implementation is wrong (or the spec gets fixed deliberately).
- The **vectors decide** disputes between implementations. Bit-exact tiers must match byte-for-byte; ε tiers within the per-family tolerance in `params.json`.
- **All simulation randomness flows through PCG32** (`spec/rng.md`). Never numpy RNG, never `System.Random`; seeding and draw order are part of each family's spec.
- **Never regenerate existing vectors casually** — they are the cross-language contract. Regenerate only when a deliberate spec change justifies it. New families/cases are added additively (`python/tools/gen_vectors.py`, run only the new section). `vectors/mergelife-upstream/` tracks the upstream repo and is never regenerated here.

**Parity change protocol** — an algorithm/behavior change touches, in order:
1. `spec/` page + `python/` implementation (+ additive vectors if new surface),
2. `dotnet/` port (expression-for-expression where a bit-exact tier applies),
3. Unity package sync (`python/tools/sync_unity_package.py`),
4. all three suites green: Python pytest, `dotnet test`, Unity EditMode conformance run.

### Float-determinism gotchas (hard-won; do not "clean up")

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

# Lint, types, tests — exactly what CI runs
.venv/bin/ruff check src tests tools
.venv/bin/mypy
QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q

# Run the playground app
.venv/bin/heaton-life

# Regenerate the README gallery image
.venv/bin/python tools/gen_gallery.py

# Vector generation — see the regen policy above before running anything here
.venv/bin/python tools/gen_vectors.py

# Sync the C# core into the Unity embedded package (after any dotnet/ change)
.venv/bin/python tools/sync_unity_package.py
```

### dotnet/ (C# library)

Requires the .NET 10 SDK; no venv.

```bash
# Tests (replays the shared conformance vectors)
dotnet test dotnet --nologo

# Release DLL for direct hand-off (single dependency-free netstandard2.1 assembly)
dotnet build dotnet/src/HeatonLife.Core -c Release
```

### heaton-life-unity/ (Unity app)

Opened through the Unity Editor (6000.5.0f1). Headless conformance gate (editor must be closed):

```bash
/Applications/Unity/Hub/Editor/6000.5.0f1/Unity.app/Contents/MacOS/Unity \
  -batchmode -projectPath heaton-life-unity -runTests -testPlatform EditMode \
  -testResults /tmp/heaton-life-unity-results.xml -logFile /tmp/heaton-life-unity.log
```

See `heaton-life-unity/CLAUDE.md` for the app architecture and the on-device self-check.

## Code Style

- **Python**: ruff (line length 100), mypy `strict`; params are frozen dataclasses with UI metadata; every family follows the `Simulation` protocol (`step/reset/state/frame`) in `core/protocols.py`.
- **C#**: Allman braces, XML doc comments that cite the spec page each class implements; `HeatonLife.Core` stays netstandard2.1 with **zero dependencies** (no Regex, no LINQ in Core, no JSON — parsing lives in test projects); zero-allocation step/frame APIs (`WriteFrame` into caller buffers).
- Cross-cutting: nothing merges without its spec page and vectors; the playground/app consumes only the public API — if it needs a hack, the API is wrong.
