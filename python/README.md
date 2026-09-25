<p align="center">
  <img src="https://raw.githubusercontent.com/jeffheaton/heaton-life/main/docs/heaton_life_icon.png" alt="Heaton Life" width="160">
</p>

# heaton-life

[![PyPI version](https://img.shields.io/pypi/v/heaton-life?style=flat-square)](https://pypi.org/project/heaton-life/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=flat-square)](https://github.com/jeffheaton/heaton-life/blob/main/LICENSE)
[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/jeffheaton/heaton-life/blob/main/python/examples/heaton_life_intro.ipynb)

heaton-life is a Python library for exploring emergence: simple rules that give rise to
complex, organic-looking behavior. It brings together cellular automata (MergeLife,
Life-like, Elementary, Cyclic, and Wireworld), three flavors of Lenia, fractals
(Newton's basins, and Mandelbrot, Julia, and Burning Ship with deep zoom, to 10⁹⁰⁰⁰ for
Mandelbrot and Julia), Reynolds boids, and Gray-Scott reaction-diffusion under one
consistent API. Every system steps and
renders the same way, so a few lines of NumPy-backed code give you a still image, an
animated GIF, or an MP4. A genetic evolver can search for new MergeLife rules, and an
optional PyQt6 playground lets you explore everything interactively.

Results are reproducible by design. Each system follows a written specification and a
set of conformance vectors, so the same parameters and seed always give the same run,
and the library's .NET implementation is held to the same vectors. The specifications,
the vectors, and the .NET port live in the
[heaton-life repository](https://github.com/jeffheaton/heaton-life).

Here is every system in the library, each rendered by the library itself. The
bottom-right tile is the Mandelbrot set at a zoom of 10¹⁴, far beyond what plain
floating point can resolve:

![heaton-life gallery: one tile per system](https://raw.githubusercontent.com/jeffheaton/heaton-life/main/docs/gallery.png)

# Install

Install from [PyPI](https://pypi.org/project/heaton-life/).

```
pip install heaton-life
```

heaton-life requires Python 3.11 or newer and depends only on NumPy (2.0.2 or newer)
and Pillow.
Extras: `heaton-life[playground]` (the PyQt6 app), `[precision]` (gmpy2 for faster
deep-zoom reference orbits; plain Python integers give the same orbit otherwise),
`[video]` (MP4 export).

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

# Zoom movie: each frame's iteration budget measured down the descent, colors that
# hold still, frames streamed to disk (an .mp4 needs the video extra; any other path
# is a folder of PNG frames):
hl.fractal.render_zoom_movie(
    lambda max_iter: hl.fractal.Mandelbrot(max_iter=max_iter),
    (640, 360),
    hl.Viewport(center_re="-0.7435", center_im="0.1314"),
    hl.fractal.ZoomPlan(start_zoom=0.0, end_zoom=4.0, frames=240, fps=30),
    "zoom.mp4",
)

# Evolve MergeLife rules with the paper's objective — reproducible from a seed
# (slow: a few minutes at these settings):
from heaton_life.evolve import Evolver
best = Evolver(size=(64, 64), population_size=20, seed=42).run(max_evals=200)
print(best.genome, best.score)
```

# Checking the runtime

The identical results rest on IEEE-754 double arithmetic with no fused multiply-add
contraction and no flush-to-zero, and on NumPy fusing its complex multiply the way the
specifications assume. To confirm that your own installation keeps that contract (an
unusual NumPy build, or a process that has loaded a library compiled with
`-ffast-math`), run the platform self-check: 21 checks against answers embedded in the
package, in well under a second.

```python
from heaton_life import self_check

ok, report = self_check.run()   # report: one PASS/FAIL line per check
print(report)
```

# Playground

```
pip install "heaton-life[playground]"
heaton-life                        # or: python -m heaton_life.playground
```

Space = play/pause, N = single step, R = reset, Ctrl+S = save PNG. The parameter
form is generated from each family's params dataclass — new families get a UI for free.

# Helpful Links

- [Intro notebook](https://colab.research.google.com/github/jeffheaton/heaton-life/blob/main/python/examples/heaton_life_intro.ipynb) — the capabilities above, runnable in Colab
- [.NET package](https://www.nuget.org/packages/HeatonLife.Core/) — `HeatonLife.Core`, the same systems for C#, .NET, and Unity, held to the same conformance vectors
- [Repository](https://github.com/jeffheaton/heaton-life) — specifications, conformance vectors, and the .NET implementation
- [Algorithm specifications](https://github.com/jeffheaton/heaton-life/tree/main/spec)
- [Release notes](https://github.com/jeffheaton/heaton-life/blob/main/CHANGELOG.md) — what changed in each version
- [Bug tracker](https://github.com/jeffheaton/heaton-life/issues)

# Development

Working on the library itself, from setting up the environment to cutting a
release, is covered in the
[development guide](https://github.com/jeffheaton/heaton-life/blob/main/python/DEVELOPMENT.md):
the lint, type, and test checks, how the specifications and conformance vectors
shape every change, adding a family, the tools, and the release workflows.
