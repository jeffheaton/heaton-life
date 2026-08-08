# heaton-life (Python)

NumPy implementation of the heaton-life emergence library, plus the PyQt6 playground.

## Install (development)

```bash
pip install -e ".[dev,playground]"
```

Extras: `playground` (PyQt6 app), `precision` (gmpy2 for fast deep zoom), `video` (MP4 export), `fast` (numba kernels).

## Quick start (working today)

```python
import heaton_life as hl

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

## Playground

```bash
pip install -e ".[playground]"
heaton-life                        # or: python -m heaton_life.playground
```

Space = play/pause, N = single step, R = reset, Ctrl+S = save PNG. The parameter
form is generated from each family's params dataclass — new families get a UI for free.

## Layout

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
