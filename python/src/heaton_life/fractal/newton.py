"""Newton fractal: basins of z^d - 1 under Newton's method. Float64 only (no deep tier).

Outputs: "roots" (nearest-root index at convergence, -1 if unconverged) and
"iterations" (1-based iteration of first convergence, -1 if unconverged).
Convergence: |z^d - 1| < 1e-9 (TOLERANCE, part of the spec).
"""

from __future__ import annotations

import dataclasses

import numpy as np

from heaton_life.core.params import Params
from heaton_life.core.viewport import Viewport
from heaton_life.fractal.engine import FloatArray, IntArray, pixel_grid

TOLERANCE = 1e-9


@dataclasses.dataclass(frozen=True)
class NewtonParams(Params):
    degree: int = 3
    max_iter: int = 60


class Newton:
    def __init__(self, degree: int = 3, max_iter: int = 60) -> None:
        if degree < 2:
            raise ValueError("degree must be >= 2")
        self.degree = degree
        self.max_iter = max_iter
        angles = 2.0 * np.pi * np.arange(degree) / degree
        self.roots = np.cos(angles) + 1j * np.sin(angles)

    def basins(
        self, size: tuple[int, int], viewport: Viewport
    ) -> tuple[IntArray, IntArray]:
        """(root_index, iterations), each shape (height, width), -1 where unconverged."""
        width, height = size
        z = pixel_grid(size, viewport)
        n = z.size
        d = self.degree
        root_idx = np.full(n, -1, dtype=np.int32)
        iters = np.full(n, -1, dtype=np.int32)
        idx = np.arange(n)
        tol2 = TOLERANCE * TOLERANCE
        for it in range(1, self.max_iter + 1):
            zd1 = z ** (d - 1)
            deriv = d * zd1
            # dead pixels (z=0 -> zero derivative) just never converge
            safe = deriv != 0
            z = np.where(safe, z - (zd1 * z - 1.0) / np.where(safe, deriv, 1.0), z)
            residual = z**d - 1.0
            done = (residual.real**2 + residual.imag**2) < tol2
            if done.any():
                hits = idx[done]
                iters[hits] = it
                zdone = z[done]
                distances = np.abs(zdone[:, None] - self.roots[None, :])
                root_idx[hits] = np.argmin(distances, axis=1).astype(np.int32)
                keep = ~done
                z, idx = z[keep], idx[keep]
                if idx.size == 0:
                    break
        return root_idx.reshape(height, width), iters.reshape(height, width)

    def iterations(self, size: tuple[int, int], viewport: Viewport) -> IntArray:
        return self.basins(size, viewport)[1]

    def outputs(self, size: tuple[int, int], viewport: Viewport) -> dict[str, IntArray]:
        roots, iters = self.basins(size, viewport)
        return {"roots": roots, "iterations": iters}

    def render_and_counts(
        self, size: tuple[int, int], viewport: Viewport
    ) -> tuple[FloatArray, IntArray]:
        roots, iters = self.basins(size, viewport)
        return self._shade(roots, iters), iters

    def render(self, size: tuple[int, int], viewport: Viewport) -> FloatArray:
        """Hue by basin, shaded by convergence speed; unconverged pixels are 0."""
        roots, iters = self.basins(size, viewport)
        return self._shade(roots, iters)

    def _shade(self, roots: IntArray, iters: IntArray) -> FloatArray:
        converged = roots >= 0
        shade = np.zeros(roots.shape, dtype=np.float64)
        shade[converged] = 1.0 - 0.7 * (iters[converged] / self.max_iter)
        value = np.zeros(roots.shape, dtype=np.float64)
        value[converged] = (roots[converged] + shade[converged]) / self.degree
        result: FloatArray = np.clip(value, 0.0, 1.0)
        return result
