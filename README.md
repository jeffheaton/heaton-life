# heaton-life

Emergence algorithms — cellular automata, Lenia, fractals, boids, and reaction-diffusion — as a spec-first, multi-language library with an interactive playground.

```
Emergence
├── Cellular Automata
│   ├── MergeLife
│   ├── Life-like
│   ├── Elementary
│   ├── Cyclic
│   └── Wireworld
├── Lenia
│   ├── Classic
│   ├── Asymptotic
│   └── Flow
├── Fractals
│   ├── Mandelbrot
│   ├── Julia
│   ├── Burning Ship
│   └── Newton
├── Boids
│   └── Reynolds
└── Reaction-Diffusion
    └── Gray-Scott
```

## Repository layout

| Path | Contents |
|---|---|
| [`spec/`](spec/) | Language-neutral algorithm specifications — the source of truth both implementations conform to |
| [`vectors/`](vectors/) | Golden conformance vectors (params + expected states) shared by all implementations |
| [`python/`](python/) | Python implementation (NumPy) + PyQt6 playground app |
| [`dotnet/`](dotnet/) | C#/.NET implementation (netstandard2.1 core + Unity adapter) — placeholder, coming after spec v0 |
| [`ROADMAP.md`](ROADMAP.md) | Phased implementation plan |

## Design principles

- **Spec first.** Each family is defined by its math (gather → respond → integrate), its parameters, and its conformance vectors — never by an implementation's idioms.
- **Deterministic replay.** `(params, seed)` fully determines a run. The RNG (PCG32) is pinned in the spec; discrete CAs are specified in integer math and must match bit-for-bit across languages.
- **Params in, frames out.** Every system produces NumPy/array frames; one rendering pipeline serves all families.
- **Precision is a contract, not a retrofit.** Fractal viewports carry arbitrary-precision centers from day one (see [`spec/deep-zoom.md`](spec/deep-zoom.md)).

## Status

Early scaffold — see [ROADMAP.md](ROADMAP.md) for the build order.
