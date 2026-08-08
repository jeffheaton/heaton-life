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
- `mergelife.py`: hex-genome parse/format, update rule specified in integer math, random-genome helper.
- Playground: paint-cells brush, per-family preset dropdowns.
- Spec pages + bit-exact vectors for all five CAs.

## Phase 4 — Continuous grids (ε tier)

- `core/`: Euler integrator + dt, FFT convolution utility, double-buffered grid container for in-place stencils.
- `rd/gray_scott.py` first (plain 5-point stencil — proves the continuous path without FFT), with named presets (mitosis, coral, worms…).
- `lenia/`: shared ring-kernel builder; `classic.py`, then `asymptotic.py` (same engine, different update), `flow.py` last (mass-conserving advection — the odd one out). Arrays shaped `(C, H, W)` from the start so multi-channel isn't a rewrite.
- Playground: stamp/seed tools, preset browser.

## Phase 5 — Fractals + deep zoom

Per `spec/deep-zoom.md` (contract already in core since Phase 1):

- Escape-time engine, T0 float64 direct path; smooth coloring.
- Perturbation + rebasing engine (T1): gmpy2/mpmath shim, cached reference orbits, NumPy lockstep iteration with fancy-indexed `Z[m]` gather; optional numba kernel.
- `mandelbrot.py`, `julia.py`, `burning_ship.py` (diffabs), `newton.py` (T0 only).
- Playground: click/scroll zoom + pan, progressive refinement with cancellation, "zoom movie" export.
- Vectors: iteration-count grids (bit-exact) incl. deep-zoom cases with exported reference orbits.

## Phase 6 — Boids

- `boids/reynolds.py`: vectorized separation/alignment/cohesion, perception radius, wrap/bounce boundaries; uniform spatial hash when N > ~2k.
- Rasterized `frame()` for the shared pipeline **plus** a playground vector overlay (oriented triangles, optional trails) — the first non-grid renderer, proving `state` ≠ `frame`.
- ε-tier vectors (momentum conservation with zero steering as the oracle).

## Phase 7 — Release polish & dotnet kickoff

- Docs + gallery notebooks, MP4 export, PyPI release, GUI entry point enabled.
- `evolve/` seam: GA over MergeLife genomes with the paper's objective functions.
- Spec completion pass (every family page finalized against vectors).
- .NET port begins in `dotnet/`: PCG32 → Life-like → conformance harness first, mirroring Phase 1.

## Cross-cutting rules

- Nothing merges without its spec page and vectors.
- The playground consumes only the public API — if the playground needs a hack, the API is wrong.
- Pure-NumPy stays the reference implementation; numba/GPU paths must match it within tier tolerance.
