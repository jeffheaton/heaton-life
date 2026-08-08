"""Lenia kernel construction — spec/lenia.md.

The standard exponential ring core, built directly in wrapped (torus) coordinates
with the center at [0, 0], normalized to sum 1. `kernel_fft(ring_kernel(...))`
feeds `core.fftconv.fft_convolve`.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

ALPHA = 4.0  # steepness of the exponential core


def ring_kernel(size: tuple[int, int], radius: int) -> NDArray[np.float64]:
    """Normalized single-ring kernel on a (width, height) torus, origin at [0, 0].

    Core: K(r) = exp(ALPHA - ALPHA / (4 r (1 - r))) for 0 < r < 1, else 0,
    where r = distance / radius.
    """
    width, height = size
    if radius < 1 or 2 * radius + 1 > min(width, height):
        raise ValueError(f"radius {radius} does not fit a {width}x{height} torus")
    ys = np.arange(height, dtype=np.float64)
    xs = np.arange(width, dtype=np.float64)
    dy = np.minimum(ys, height - ys)[:, None]
    dx = np.minimum(xs, width - xs)[None, :]
    r = np.sqrt(dx * dx + dy * dy) / float(radius)
    with np.errstate(divide="ignore", over="ignore"):
        core = np.exp(ALPHA - ALPHA / (4.0 * r * (1.0 - r)))
    kernel = np.where((r > 0.0) & (r < 1.0), core, 0.0)
    total = kernel.sum()
    if total <= 0.0:
        raise ValueError(f"degenerate kernel for radius {radius}")
    result: NDArray[np.float64] = kernel / total
    return result
