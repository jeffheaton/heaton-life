# Roadmap

Build order for the Python library + PyQt6 playground, sequenced so each phase proves the layer the next one leans on. Every phase also lands its spec pages and conformance vectors — the spec is written *with* the first implementation, not after it.

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
- Perturbation + rebasing engine (T1): gmpy2/mpmath shim (backends verified bit-identical), cached reference orbits, NumPy lockstep iteration with fancy-indexed `Z[m]` gather.
- Mandelbrot, Julia, Burning Ship (diffabs), Newton (T0 only) — T1 validated against T0 (exact for Julia/Ship; Mandelbrot agreement equals T0's own 1-ulp chaos bound).
- Playground: click/wheel zoom (cursor-anchored, Decimal-precise recentering), pan via Ctrl-click; zoom movies via `fractal.zoom_animation`.
- Vectors: int32 iteration/root grids (bit-exact) incl. a deep-zoom case with its exported reference orbit.
- Deferred to Phase 7: progressive refinement with cancellation (renders are single-pass), optional numba kernels.

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
- Packaging: classifiers/urls, wheel builds clean. Publishing to PyPI is a
  release decision (account + license choice) left to the maintainer.
- Spec completion pass: every family page + rng, deep-zoom, fractals, evolve.
- **.NET port begun and green**: `HeatonLife.Core` (netstandard2.1) with PCG32
  (known-answer tested) and Life-like; the xunit suite replays the shared
  `vectors/lifelike/` byte-for-byte via a dependency-free PNG reader, and CI runs it.

## Future work

- .NET: library parity is complete — all families, colormaps (spec/render.md),
  and the evolver (spec/evolve.md) conform to the shared vectors. Next: the
  `HeatonLife.Unity` UPM adapter. Reference-orbit generation (bignum) remains
  Python-side; C# consumes precomputed orbits.
- Fractals: progressive refinement with cancellation in the playground; optional
  numba kernels; floatexp tier beyond zoom 1e290; BLA iteration skipping.
- Boids spatial hash if flocks ever need >2k; Lenia multi-channel; Orbium and
  friends as stampable Lenia creatures; MP4/GIF export buttons in the playground.
- PyPI release (licensed Apache-2.0; publishing needs the maintainer's PyPI account).

## Cross-cutting rules

- Nothing merges without its spec page and vectors.
- The playground consumes only the public API — if the playground needs a hack, the API is wrong.
- Pure-NumPy stays the reference implementation; numba/GPU paths must match it within tier tolerance.
