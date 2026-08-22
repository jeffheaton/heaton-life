![heaton-life gallery: one tile per system](https://raw.githubusercontent.com/jeffheaton/heaton-life/main/docs/gallery.png)

# heaton-life

[![PyPI version](https://badge.fury.io/py/heaton-life.svg)](https://pypi.org/project/heaton-life/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=flat-square)](https://github.com/jeffheaton/heaton-life/blob/main/LICENSE)
[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/jeffheaton/heaton-life/blob/main/python/examples/heaton_life_intro.ipynb)

heaton-life is a Python library for exploring emergence: simple rules that give rise to
complex, organic-looking behavior. It brings together cellular automata (MergeLife,
Life-like, Elementary, Cyclic, and Wireworld), three flavors of Lenia, escape-time
fractals with deep zoom (Mandelbrot, Julia, Burning Ship, and Newton), Reynolds boids,
and Gray-Scott reaction-diffusion under one consistent API. Every system steps and
renders the same way, so a few lines of NumPy-backed code give you a still image, an
animated GIF, or an MP4. A genetic evolver can search for new MergeLife rules, and an
optional PyQt6 playground lets you explore everything interactively.

Results are reproducible by design. Each system follows a written specification and a
set of conformance vectors, so the same parameters and seed always give the same run,
and the library's .NET implementation is held to the same vectors. The specifications,
the vectors, and the .NET port live in the
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

Working on the library itself, from setting up the environment to cutting a
release, is covered in the
[development guide](https://github.com/jeffheaton/heaton-life/blob/main/python/DEVELOPMENT.md):
the lint, type, and test checks, how the specifications and conformance vectors
shape every change, adding a family, the tools, and the release workflows.
