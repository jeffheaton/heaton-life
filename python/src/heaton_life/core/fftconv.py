"""FFT-based circular convolution for large kernels (Lenia's workhorse).

Kernels are built in wrapped (origin-at-[0,0]) coordinates, so no fftshift games:
`fft_convolve(field, kernel_fft(k))` is exact circular convolution on the torus.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def kernel_fft(kernel: NDArray[np.float64]) -> NDArray[np.complex128]:
    """Precompute the rFFT of a wrapped-coordinate kernel."""
    result: NDArray[np.complex128] = np.fft.rfft2(kernel)
    return result


def fft_convolve(
    field: NDArray[np.float64], kfft: NDArray[np.complex128]
) -> NDArray[np.float64]:
    """Circular convolution of a real field with a precomputed kernel spectrum."""
    result: NDArray[np.float64] = np.fft.irfft2(np.fft.rfft2(field) * kfft, s=field.shape)
    return result
