"""heaton-life: emergence algorithms — cellular automata, Lenia, fractals, boids, reaction-diffusion.

Spec-first, multi-language project; this is the Python implementation.
See the repository ROADMAP.md for build order and spec/ for the algorithm contracts.
"""

from heaton_life import boids, ca, core, evolve, fractal, init, lenia, rd, render
from heaton_life.core.params import Params
from heaton_life.core.protocols import Field, Simulation
from heaton_life.core.rng import Pcg32
from heaton_life.core.viewport import Viewport

__version__ = "1.0.0"

__all__ = [
    "Field",
    "Params",
    "Pcg32",
    "Simulation",
    "Viewport",
    "__version__",
    "boids",
    "ca",
    "core",
    "evolve",
    "fractal",
    "init",
    "lenia",
    "rd",
    "render",
]
