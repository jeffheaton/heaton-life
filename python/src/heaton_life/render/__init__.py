"""Rendering: colormaps, state palettes, still images, and animations. Consumes frames from
any family."""

from heaton_life.render.animate import Animation, animate
from heaton_life.render.colormap import (
    apply_colormap,
    apply_phase,
    get_colormap,
    is_cyclic,
    list_colormaps,
    list_cyclic_colormaps,
)
from heaton_life.render.image import to_image
from heaton_life.render.palette import (
    HISTORY_COLORS,
    HISTORY_ZOOM_ORDER,
    colormap_palette,
    default_palette,
    default_zoom_order,
    frame_values,
    generations_palette,
    gradient_palette,
    history_palette,
    multistate_palette,
    shade_colormap,
)
from heaton_life.render.window import WINDOW_MODES, WindowMode, sample_window, zoom_ranks

__all__ = [
    "HISTORY_COLORS",
    "HISTORY_ZOOM_ORDER",
    "WINDOW_MODES",
    "Animation",
    "WindowMode",
    "animate",
    "apply_colormap",
    "apply_phase",
    "colormap_palette",
    "default_palette",
    "default_zoom_order",
    "frame_values",
    "generations_palette",
    "get_colormap",
    "gradient_palette",
    "history_palette",
    "is_cyclic",
    "list_colormaps",
    "list_cyclic_colormaps",
    "multistate_palette",
    "sample_window",
    "shade_colormap",
    "to_image",
    "zoom_ranks",
]
