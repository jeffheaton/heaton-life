"""Rendering: colormaps, still images, and animations. Consumes frames from any family."""

from heaton_life.render.animate import Animation, animate
from heaton_life.render.colormap import apply_colormap, get_colormap, list_colormaps
from heaton_life.render.image import to_image

__all__ = ["Animation", "animate", "apply_colormap", "get_colormap", "list_colormaps", "to_image"]
