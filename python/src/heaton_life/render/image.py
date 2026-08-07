"""Frame -> PIL image."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from heaton_life.render.colormap import apply_colormap


def to_image(
    frame: NDArray[np.generic], *, cmap: str | NDArray[np.uint8] = "gray", scale: int = 1
) -> Image.Image:
    """Colormap a frame and return a PIL RGB image; ``scale`` upsamples with hard pixels."""
    rgb = apply_colormap(frame, cmap)
    img = Image.fromarray(rgb, mode="RGB")
    if scale != 1:
        if scale < 1:
            raise ValueError("scale must be a positive integer")
        img = img.resize((img.width * scale, img.height * scale), Image.Resampling.NEAREST)
    return img
