# Roadmap

Build order for the library — the Python reference implementation, the PyQt6 playground, and the .NET port — sequenced so each phase proves the layer the next one leans on. Phases 0–10 are complete: 1.0.0 of both packages shipped on 2026-08-22 with Phases 0–9, and 1.1.0 carries Phase 10 ([CHANGELOG.md](CHANGELOG.md)); what remains is under "Future work". Every phase also lands its spec pages and conformance vectors — the spec is written *with* the first implementation, not after it.

## Phase 0 — Scaffold ✅

Monorepo top-level (`spec/`, `vectors/`, `python/`, `dotnet/` placeholder), Python package skeleton, this roadmap.

## Phase 1 — Core contracts + first family end-to-end ✅

The goal is one complete vertical slice that exercises every core abstraction.

- `core/`: `Simulation` / `Field` protocols, params-dataclass base with snake_case JSON round-trip, pinned PCG32, neighbor-count helpers, **`Viewport` with decimal-string centers** (the deep-zoom contract lands here, before any fractal exists).
- `init/`: soup, blob, single-cell; RLE pattern import.
- `render/`: colormaps, `to_image`, GIF export, Jupyter display.
- `ca/lifelike.py`: `B3/S23` rulestring parsing, toroidal default.
- Tests: glider displaces (1,1) per 4 generations; RLE round-trip; PCG32 known-answer tests.
- First vectors committed (`vectors/lifelike/…`); CI (ruff + mypy + pytest) goes green.

**Done when:** `hl.render.animate(hl.ca.LifeLike("B3/S23", size=(256,256), seed=42), steps=500).save("life.gif")` works and the vector suite passes.

## Phase 2 — Playground skeleton (PyQt6) ✅

Built early on purpose: the playground is the library's first real consumer and will shake out API flaws while they're cheap to fix.

- Main window: taxonomy tree sidebar → canvas center → transport bar (play/pause/step/reset/speed) → params dock.
- **Param form auto-generated from the params dataclasses** (introspect fields → spinbox/slider/combo/seed widgets). This is the payoff of params-as-dataclasses; no per-family UI code.
- Simulation on a worker `QThread`, frames delivered by signal with latest-frame backpressure; canvas blits `frame()` → `QImage(Format_RGB888)`.
- PNG snapshot export; seed + reset reproducibility.
- Wired to Life-like only.

**Done when:** interactive Life at 512² runs at 60 fps with live-editable params.

## Phase 3 — Complete the discrete CAs (bit-exact tier) ✅

- `elementary.py` (Wolfram 0–255; 1-D tape state, space-time diagram as the frame).
- `cyclic.py` (states/threshold/range), `wireworld.py` (4-state machine + pattern files).
- `mergelife.py`: hex-rule parse/format, update rule specified in integer math, random-rule helper.
- Playground: paint-cells brush, per-family preset dropdowns.
- Spec pages + bit-exact vectors for all five CAs.

## Phase 4 — Continuous grids (ε tier) ✅

- `core/`: dt-scaled explicit Euler updates with spec'd operation order, 5-point Laplacian + torus gradient stencils, FFT convolution utility.
- `rd/gray_scott.py` first (plain 5-point stencil — proves the continuous path without FFT), with named presets (mitosis, coral, worms…) — all verified pattern-forming.
- `lenia/`: shared ring-kernel builder; `classic.py`, then `asymptotic.py` (same engine, different update), `flow.py` last (mass-conserving bilinear reintegration). Single-channel `(H, W)` state; the kernel/FFT utilities are channel-agnostic so multi-channel is a loop, not a rewrite.
- Playground: stamp/seed paint tools, per-family preset dropdowns.

## Phase 5 — Fractals + deep zoom ✅

Per `spec/deep-zoom.md` (contract already in core since Phase 1):

- Escape-time engine, T0 float64 direct path; smooth coloring.
- Perturbation + rebasing engine (T1): cached reference orbits, NumPy lockstep iteration with fancy-indexed `Z[m]` gather. (Orbits were a gmpy2/mpmath floating-point shim until 2026-09-23; they are now the spec's fixed-point arithmetic on Python ints, gmpy2 mpz optional, identical to the C# port.)
- Mandelbrot, Julia, Burning Ship (diffabs), Newton (T0 only) — T1 validated against T0 (exact for Julia/Ship; Mandelbrot agreement equals T0's own 1-ulp chaos bound).
- Playground: click recenters, Ctrl-click recenters and zooms ×4, the wheel zooms anchored at the cursor — exact decimal arithmetic through the library's `fractal.navigation` since 2026-09-23 ([spec/navigation.md](spec/navigation.md)); zoom movies via `fractal.zoom_animation`.
- Vectors: int32 iteration/root grids (bit-exact) incl. a deep-zoom case with its exported reference orbit.
- Past zoom 1e290 (2026-09-24): the T2 tier to 1e9000, floatexp deltas with float64 steps between small reference samples ([spec/floatexp.md](spec/floatexp.md)), and BLA iteration skipping at T1 and T2 with double-double coefficients (spec/deep-zoom.md "BLA", "BLA at T2").
- Deferred (see Future work): progressive refinement with cancellation (renders are single-pass), optional numba kernels.

## Phase 6 — Boids ✅

- `boids/reynolds.py`: vectorized separation/alignment/cohesion, perception radius, wrap/bounce boundaries. O(N²) neighbors spec'd and capped at 2k boids; a spatial hash is future work if bigger flocks are ever needed.
- Rasterized `frame()` for the shared pipeline **plus** a playground vector overlay (oriented triangles) — the first non-grid renderer, proving `state` ≠ `frame`. Trails skipped.
- ε-tier vectors; oracle suite includes bitwise momentum conservation with zero steering.
- Playground extras: scare/lure clicks (left shoves nearby boids away, right pulls them in).

## Phase 7 — Release polish & dotnet kickoff ✅

- `evolve/`: faithful port of the paper's objective statistics (Sec. 4: steps /
  foreground / active / largest-rect / mode-age, with the reference's exact scoring
  formula) and GA operators (Sec. 5: digit-swap mutation, sub-rule crossover,
  tournament selection) — with every random decision drawn from PCG32, so scoring
  and whole evolution runs replay from a seed. `PAPER_OBJECTIVE` included.
- MP4 export (`Animation.save("*.mp4")`, video extra); gallery generator
  (`tools/gen_gallery.py` → `docs/gallery.png`, embedded in the README).
- Packaging: classifiers/urls, wheel builds clean; publishing was deferred to Phase 9.
- Spec completion pass: every family page + rng, deep-zoom, fractals, evolve.
- **.NET port begun and green**: `HeatonLife.Core` (netstandard2.1) with PCG32
  (known-answer tested) and Life-like; the xunit suite replays the shared
  `vectors/lifelike/` byte-for-byte via a dependency-free PNG reader, and CI runs it.

## Phase 8 — .NET parity ✅

`HeatonLife.Core` replays every shared vector: all families, colormaps
(spec/render.md), patterns, PNG I/O, and the evolver (spec/evolve.md). Reference-orbit
generation (bignum) runs on the C# side too (`ReferenceOrbit`, the normative
fixed-point arithmetic of spec/deep-zoom.md, pinned by regenerating every shipped
orbit byte for byte). The package is a dependency-free `netstandard2.1` assembly with a symbols package.

## Phase 9 — First releases ✅

`heaton-life` 1.0.0 on PyPI and `HeatonLife.Core` 1.0.0 on NuGet, both on 2026-08-22,
published by the manually dispatched Build Library workflows (python/DEVELOPMENT.md and
dotnet/DEVELOPMENT.md, "Releasing"; NuGet through Trusted Publishing, no stored key).
Consumer-facing READMEs on both package pages, the intro notebook installing from PyPI.

## Phase 10 — Deep zoom to 1e9000, zoom movies, platform self-check ✅

Aligning the library with Heaton Fractal's deep zoom, in stages (spec_version 0.2.0 →
0.13.0, every vector 1.0.0 shipped byte-identical), released as 1.1.0 (see
[CHANGELOG.md](CHANGELOG.md)):

- One orbit arithmetic in both ports (fixed point on integers), Julia's critical-orbit
  rebasing, an exact software fma, and one decimal grammar for centers.
- Off-center references, exact navigation, location import (Kalles Fraktaler,
  Fraktaler-3, Heaton Fractal), and a nucleus finder.
- Pixel status, interior shortcuts, the distance estimate, an iteration policy, and
  fractal color (stretch, depth phase, distance shading, cyclic palettes).
- T2 floatexp perturbation to 1e9000 for Mandelbrot and Julia, and BLA at T1 and T2
  with double-double coefficients.
- Newton's roots from pinned integer turns instead of libm `cos`/`sin`.
- Zoom movies: schedules, plans and measured budgets in both ports, rendering in Python
  (`render_zoom_movie`, [spec/zoom.md](spec/zoom.md)).
- The platform self-check ([spec/self-check.md](spec/self-check.md)), which a host runs
  on its own runtime. The Heaton Life app runs it at launch from its next release, and
  it passed on every platform the app ships to (macOS, the Mac App Store sandbox,
  Windows, Android, and iOS).
- Python requires NumPy 2.0.2: before it, NumPy counted an output that merely touched an
  input's memory as overlapping (numpy#27077) and took a plain C loop, unfused in most
  builds.

## Future work

- Fractals: progressive refinement with cancellation in the playground; optional
  numba kernels; BLA for Julia and the Burning Ship; the Burning Ship past 1e290.
- Zoom movies: log-polar strips, rotation, and motion blur (spec/zoom.md, "Not yet");
  rendering movies in the .NET port, where the Unity app would use them.
- Boids spatial hash if flocks ever need >2k; Lenia multi-channel; Orbium and
  friends as stampable Lenia creatures; MP4/GIF export buttons in the playground.
- Python 3.13+ in the classifiers once the suite has run there; a project-scoped
  PyPI token in place of the account-scoped one used for the first upload.

## Cross-cutting rules

- Nothing merges without its spec page and vectors.
- The playground consumes only the public API — if the playground needs a hack, the API is wrong.
- Pure-NumPy stays the reference implementation; numba/GPU paths must match it within tier tolerance.
