![heaton-life gallery: one tile per system](https://raw.githubusercontent.com/jeffheaton/heaton-life/main/docs/gallery.png)

# heaton-life

[![PyPI version](https://badge.fury.io/py/heaton-life.svg)](https://pypi.org/project/heaton-life/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=flat-square)](https://github.com/jeffheaton/heaton-life/blob/main/LICENSE)
[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/jeffheaton/heaton-life/blob/main/python/examples/heaton_life_intro.ipynb)

Emergence algorithms — cellular automata (MergeLife, Life-like, Elementary, Cyclic,
Wireworld), Lenia (classic, asymptotic, flow), escape-time fractals with perturbation
deep zoom (Mandelbrot, Julia, Burning Ship, Newton), Reynolds boids, and Gray-Scott
reaction-diffusion — as a NumPy library with one rendering pipeline, a MergeLife
genetic evolver, and an optional PyQt6 playground.

Every system is defined by a language-neutral specification and pinned by golden
conformance vectors: `(params, seed)` fully determines a run, the random number
generator (PCG32) is part of the contract, and the discrete automata match the .NET
implementation bit for bit. The specifications and vectors live in the
[heaton-life repository](https://github.com/jeffheaton/heaton-life).

# Install

Install from [PyPI](https://pypi.org/project/heaton-life/).

```
pip install heaton-life
```

Extras: `heaton-life[playground]` (the PyQt6 app), `[precision]` (gmpy2 for fast
deep-zoom reference orbits; an mpmath fallback is built in), `[video]` (MP4 export),
`[fast]` (numba kernels).

# Sample Code

```python
import heaton_life as hl

# A Life-like automaton from a random soup, rendered to an animated GIF.
sim = hl.ca.LifeLike("B3/S23", size=(256, 256), init="soup", seed=42)
hl.render.animate(sim, steps=500, cmap="phosphor").save("life.gif")

# Deep zoom: float64 pixelates near 1e13; this renders via perturbation + rebasing.
frac = hl.fractal.Mandelbrot(max_iter=5000)
field = frac.render((1920, 1080), hl.Viewport(
    center_re="-0.743643887037158704752191506114774",
    center_im="0.131825904205311970493132056385139",
    zoom_log10=14.0,
))
hl.render.to_image(field, cmap="fire").save("deep.png")

# Zoom movie (also .mp4 with the video extra):
hl.fractal.zoom_animation(frac, (512, 512), hl.Viewport(
    center_re="-0.7435", center_im="0.1314", zoom_log10=4.0,
), steps=90, cmap="fire").save("zoom.gif")

# Evolve MergeLife rules with the paper's objective — reproducible from a seed:
from heaton_life.evolve import Evolver
best = Evolver(size=(64, 64), population_size=20, seed=42).run(max_evals=200)
print(best.genome, best.score)
```

# Playground

```
pip install "heaton-life[playground]"
heaton-life                        # or: python -m heaton_life.playground
```

Space = play/pause, N = single step, R = reset, Ctrl+S = save PNG. The parameter
form is generated from each family's params dataclass — new families get a UI for free.

# Helpful Links

- [Intro notebook](https://github.com/jeffheaton/heaton-life/blob/main/python/examples/heaton_life_intro.ipynb) — the capabilities above, runnable in Colab
- [Repository](https://github.com/jeffheaton/heaton-life) — specifications, conformance vectors, and the .NET implementation
- [Algorithm specifications](https://github.com/jeffheaton/heaton-life/tree/main/spec)
- [Bug tracker](https://github.com/jeffheaton/heaton-life/issues)

# Development

```
pip install -e ".[dev,playground]"
ruff check src tests tools
mypy
pytest -q
```

Layout:

```
src/heaton_life/
├── core/        # protocols, Viewport, params, PCG32, buffers, kernels, integrators
├── ca/          # lifelike, elementary, cyclic, wireworld, mergelife
├── lenia/       # kernels, classic, asymptotic, flow
├── fractal/     # escape-time engine, perturbation engine, mandelbrot, julia, burning_ship, newton
├── boids/       # reynolds + spatial hash
├── rd/          # gray_scott + presets
├── init/        # soup, blob, single, RLE import
├── render/      # colormaps, image, animate (GIF/MP4), notebook display
└── playground/  # PyQt6 app (optional extra)
```

## Releasing

Two manually dispatched GitHub workflows, the same shape as dynaface's:

1. **Build Library** (`.github/workflows/build-lib.yml`) — ruff/mypy reports, the test
   suite (conformance vectors + offscreen playground), a regenerated
   `src/heaton_life/version.py` (VERSION from `pyproject.toml`, BUILD_DATE, BUILD = the
   run number), then the wheel → `twine check` → workflow artifact →
   `s3://data.heatonresearch.com/library/`.
2. **Deploy Library to PyPI** (`deploy-lib.yml`) — takes the wheel file name (e.g.
   `heaton_life-1.0.0-py3-none-any.whl`), pulls it from S3, uploads it to PyPI.

To cut a release, bump `version` in `pyproject.toml` **and** `__version__` in
`src/heaton_life/__init__.py` (the build fails if they disagree), dispatch Build
Library, inspect the artifact, then dispatch Deploy with its file name. Repository
secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`,
`PYPI_API_TOKEN`.
