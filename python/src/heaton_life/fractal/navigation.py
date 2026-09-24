"""Exact viewport arithmetic -- spec/navigation.md.

A host that pans, recenters or zooms about a point moves a viewport's decimal center
by a pixel offset. Doing that in float64 (or C# decimal) runs out of digits long
before the renderer does, and printing "enough digits" naively ratchets the orbit's
precision up with every step. These operations are exact instead: the offset is the
float64 a render computes for that pixel, added to the center's exact value, and the
sum is rounded ONCE to a number of decimal places set by the frame -- never by the
center's own digits or the orbit's bits -- so repeating a pan at one zoom never
changes the orbit's working precision.

Pixel offsets are in pixels of the given frame: ``dx`` to the right, ``dy`` DOWN
(the row direction of spec/fractals.md "Pixel mapping"), fractional allowed. A move
whose offsets are both exactly zero keeps the center strings, so a pan of (0, 0)
returns the viewport unchanged; any other move prints both components at the frame's
places. The viewport's off-center reference, if any, is kept: choosing it is the
host's job (spec/deep-zoom.md "Off-center reference").
"""

from __future__ import annotations

import dataclasses
import math
from fractions import Fraction

from heaton_life.core import decimal_text, floatexp
from heaton_life.core.viewport import Viewport
from heaton_life.fractal.engine import T1_MAX_ZOOM, T2_MAX_ZOOM, scale_at, scale_at_x

__all__ = ["center_places", "pan", "pixel_delta", "zoom_at"]


def center_places(zoom_log10: float, size: tuple[int, int]) -> int:
    """Decimal places a moved center is printed with: max(ceil(zoom), 0) plus the
    number of decimal digits of max(width, height), plus 2 -- a grid of at most 1/400
    pixel. It depends on the frame alone, never on the center or the orbit's bits."""
    width, height = _frame(size)
    return max(math.ceil(_zoom(zoom_log10)), 0) + len(str(max(width, height))) + 2


def pan(
    viewport: Viewport,
    dx: float,
    dy: float,
    size: tuple[int, int],
    zoom_log10: float | None = None,
) -> Viewport:
    """The viewport recentered on the point now (dx, dy) pixels from its center (dx
    right, dy down), optionally at a new zoom -- a click recenters with the clicked
    pixel's offset, a drag passes minus the drag. The offset is fl(dx * ps) and
    -fl(dy * ps) at the CURRENT zoom's pixel scale (exactly the offsets a render of
    this frame gives a pixel); the center is printed at the resulting zoom's places.
    """
    width, _ = _frame(size)
    zoom = viewport.zoom_log10 if zoom_log10 is None else _zoom(zoom_log10)
    current = _zoom(viewport.zoom_log10)
    return _moved(
        viewport,
        _offset(_finite(dx, "dx"), width, current),
        _offset(-_finite(dy, "dy"), width, current),
        zoom,
        center_places(zoom, size),
    )


def zoom_at(
    viewport: Viewport, dx: float, dy: float, size: tuple[int, int], zoom_log10: float
) -> Viewport:
    """The viewport at ``zoom_log10`` with the point at pixel offset (dx, dy) held fixed
    (a cursor-anchored wheel or pinch). The center moves by the exact difference of the
    anchor's offset in the two frames, fl(dx * ps0) - fl(dx * ps1), so the anchor pixel's
    rendered coordinate is the same before and after up to the one rounding to places.
    """
    width, _ = _frame(size)
    zoom = _zoom(zoom_log10)
    current = _zoom(viewport.zoom_log10)
    dx = _finite(dx, "dx")
    dy = _finite(dy, "dy")
    shift_re = _offset(dx, width, current) - _offset(dx, width, zoom)
    shift_im = _offset(-dy, width, current) - _offset(-dy, width, zoom)
    return _moved(viewport, shift_re, shift_im, zoom, center_places(zoom, size))


def pixel_delta(frm: Viewport, to: Viewport, size: tuple[int, int]) -> tuple[float, float]:
    """Where ``to``'s center lies from ``frm``'s, in pixels of ``frm``'s frame (x right,
    y down): each the exact difference of the decimal centers divided by frm's pixel
    scale, rounded once to float64 (ties to even; +-inf past the range; an exact zero,
    e.g. "0.1" against "0.10", is +0.0). ``to``'s zoom does not enter."""
    width, _ = _frame(size)
    ps = _scale(width, _zoom(frm.zoom_log10))
    across = (_exact(to.center_re) - _exact(frm.center_re)) / ps
    down = (_exact(frm.center_im) - _exact(to.center_im)) / ps
    return _to_float(across), _to_float(down)


def _frame(size: tuple[int, int]) -> tuple[int, int]:
    width, height = size
    if width < 1 or height < 1:
        raise ValueError(f"frame must be at least 1x1, got {width}x{height}")
    return width, height


def _zoom(value: float) -> float:
    """A zoom the pixel scale can take: finite, within [-300, T2_MAX_ZOOM]."""
    value = _finite(value, "zoom")
    if not -300.0 <= value <= T2_MAX_ZOOM:
        raise ValueError(f"zoom must lie within [-300, {T2_MAX_ZOOM:g}], got {value!r}")
    return value


def _scale(width: int, zoom: float) -> Fraction:
    """The exact pixel scale a render of this frame uses: the double at T0 and T1, the
    floatexp at T2."""
    if zoom <= T1_MAX_ZOOM:
        return Fraction(scale_at(width, zoom))
    return _fraction(scale_at_x(width, zoom))


def _offset(pixels: float, width: int, zoom: float) -> Fraction:
    """The exact offset a render gives a point ``pixels`` from the center: fl(pixels * ps)
    at T0 and T1, pixels * ps rounded once to floatexp at T2 (engine.pixel_deltas_x)."""
    if zoom <= T1_MAX_ZOOM:
        return _exact_offset(pixels * scale_at(width, zoom))
    ps_m, ps_e = scale_at_x(width, zoom)
    return _fraction(floatexp.normalize(pixels * ps_m, ps_e))


def _fraction(value: floatexp.X) -> Fraction:
    mantissa, exponent = value
    return Fraction(mantissa) * Fraction(2) ** exponent


def _finite(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return value


def _exact_offset(offset: float) -> Fraction:
    if not math.isfinite(offset):
        raise ValueError(f"offset overflows float64: {offset!r}")
    return Fraction(offset)


def _exact(text: str) -> Fraction:
    negative, digits, net_exponent = decimal_text.scan(text)
    value = (
        Fraction(digits * 10**net_exponent)
        if net_exponent >= 0
        else Fraction(digits, 10**-net_exponent)
    )
    return -value if negative else value


def _moved(
    viewport: Viewport, shift_re: Fraction, shift_im: Fraction, zoom: float, places: int
) -> Viewport:
    """The viewport at ``zoom`` with its center shifted exactly and printed at ``places``
    -- or with its center strings as they were when both shifts are exactly zero."""
    if shift_re == 0 and shift_im == 0:
        return dataclasses.replace(viewport, zoom_log10=zoom)
    return dataclasses.replace(
        viewport,
        center_re=_printed(_exact(viewport.center_re) + shift_re, places),
        center_im=_printed(_exact(viewport.center_im) + shift_im, places),
        zoom_log10=zoom,
    )


def _printed(value: Fraction, places: int) -> str:
    """``value`` rounded half away from zero to ``places`` fraction digits."""
    scaled = value * 10**places
    whole, remainder = divmod(abs(scaled.numerator), scaled.denominator)
    if 2 * remainder >= scaled.denominator:
        whole += 1
    return decimal_text.format_scaled(-whole if scaled < 0 else whole, places)


def _to_float(value: Fraction) -> float:
    """One correct rounding (int true division), +-inf on overflow."""
    try:
        return value.numerator / value.denominator
    except OverflowError:
        return math.inf if value > 0 else -math.inf
