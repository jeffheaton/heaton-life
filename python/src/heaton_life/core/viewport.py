"""Viewport: the arbitrary-precision fractal position contract (spec/deep-zoom.md).

Centers are decimal strings of unlimited length; zoom is log10 of magnification.
The public API never represents a viewport center as complex128 — that is the
whole point (float64 pixelates near zoom 1e13, and deep zoom must not be a retrofit).
"""

from __future__ import annotations

import dataclasses
import decimal
import json
from collections.abc import Mapping
from typing import Any


def _normalize(value: object, field_name: str) -> str:
    # A float center is REFUSED, not coerced. This class exists so a deep-zoom
    # center keeps its digits (spec/deep-zoom.md: "decimal strings of arbitrary
    # length"), and a float64 argument has already lost them before __post_init__
    # can see it -- Viewport(-0.743643887037158704752191506114774) used to store
    # '-0.7436438870371587', silently truncating 17 digits at exactly the depth
    # where they matter. Integers are exact, so they still coerce.
    if isinstance(value, float):
        raise TypeError(
            f"Viewport.{field_name} must be a decimal string, not a float: float64 "
            f"cannot hold a deep-zoom center, so {value!r} would silently lose its "
            f"tail. Quote it instead: \"{value!r}\"."
        )
    if isinstance(value, decimal.Decimal):
        value = str(value)
    if isinstance(value, int) and not isinstance(value, bool):
        value = repr(value)
    if not isinstance(value, str):
        raise TypeError(
            f"Viewport.{field_name} must be a decimal string (or an exact int), "
            f"got {type(value).__name__}"
        )
    try:
        decimal.Decimal(value)
    except decimal.InvalidOperation:
        raise ValueError(f"Viewport.{field_name} is not a valid decimal string: {value!r}") from None
    return value


@dataclasses.dataclass(frozen=True)
class Viewport:
    """A position on the complex plane: center as decimal strings, zoom as log10 magnification."""

    center_re: str = "-0.5"
    center_im: str = "0.0"
    zoom_log10: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "center_re", _normalize(self.center_re, "center_re"))
        object.__setattr__(self, "center_im", _normalize(self.center_im, "center_im"))
        object.__setattr__(self, "zoom_log10", float(self.zoom_log10))

    def to_dict(self) -> dict[str, Any]:
        return {
            "center_re": self.center_re,
            "center_im": self.center_im,
            "zoom_log10": self.zoom_log10,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Viewport:
        return cls(
            center_re=data["center_re"],
            center_im=data["center_im"],
            zoom_log10=float(data["zoom_log10"]),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> Viewport:
        return cls.from_dict(json.loads(text))
