"""Finite-difference stencils for the continuous-grid families."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def laplacian5(field: NDArray[np.float64]) -> NDArray[np.float64]:
    """5-point Laplacian on a torus.

    Spec'd operation order (cross-language determinism): ((N + S) + W) + E, minus 4*C.
    """
    acc = np.roll(field, 1, axis=0) + np.roll(field, -1, axis=0)
    acc += np.roll(field, 1, axis=1)
    acc += np.roll(field, -1, axis=1)
    acc -= 4.0 * field
    return acc


def gradient_torus(
    field: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Central-difference gradient (gy, gx) on a torus."""
    gy = (np.roll(field, -1, axis=0) - np.roll(field, 1, axis=0)) * 0.5
    gx = (np.roll(field, -1, axis=1) - np.roll(field, 1, axis=1)) * 0.5
    return gy, gx
