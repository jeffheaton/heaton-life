"""Conformance-vector codecs: how each family's state maps to/from vector PNGs,
and how a simulation is rebuilt from a vector's params.json.

This module is the Python side of the cross-language contract in ../../vectors/;
the .NET implementation mirrors it. Encodings are per-family and spec'd:

- lifelike:   grayscale PNG, pixel = state * 255
- elementary: grayscale PNG, 1 x width, pixel = tape * 255
- cyclic:     grayscale PNG, pixel = raw state (0..states-1)
- wireworld:  grayscale PNG, pixel = state * 85 (0/85/170/255)
- mergelife:  RGB PNG, raw bytes
"""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from heaton_life.ca import (
    Cyclic,
    CyclicParams,
    Elementary,
    ElementaryParams,
    LifeLike,
    LifeLikeParams,
    MergeLife,
    MergeLifeParams,
    Wireworld,
    WireworldParams,
)
from heaton_life.core.protocols import Simulation


class _Codec(Protocol):
    def encode(self, state: NDArray[np.uint8]) -> Image.Image: ...

    def decode(self, image: Image.Image) -> NDArray[np.uint8]: ...

    def build(self, params: dict[str, Any], initial: NDArray[np.uint8] | None) -> Simulation: ...


class _Binary:
    """0/1 grids stored as 0/255 grayscale."""

    def __init__(self, family: str) -> None:
        self.family = family

    def encode(self, state: NDArray[np.uint8]) -> Image.Image:
        arr = np.atleast_2d(state) * np.uint8(255)
        return Image.fromarray(arr, mode="L")

    def decode(self, image: Image.Image) -> NDArray[np.uint8]:
        arr = (np.asarray(image.convert("L")) > 0).astype(np.uint8)
        return arr[0] if self.family == "elementary" else arr

    def build(self, params: dict[str, Any], initial: NDArray[np.uint8] | None) -> Simulation:
        if self.family == "elementary":
            if initial is not None:
                p = ElementaryParams.from_dict(params)
                return Elementary(
                    p.rule, size=(p.width, p.height), init=initial, boundary=p.boundary
                )
            return Elementary.from_params(ElementaryParams.from_dict(params))
        if initial is not None:
            p2 = LifeLikeParams.from_dict(params)
            return LifeLike(p2.rule, size=(p2.width, p2.height), init=initial, boundary=p2.boundary)  # type: ignore[arg-type]
        return LifeLike.from_params(LifeLikeParams.from_dict(params))


class _Indexed:
    """Small-integer state grids stored raw (optionally scaled for visibility)."""

    def __init__(self, family: str, scale: int) -> None:
        self.family = family
        self.scale = scale

    def encode(self, state: NDArray[np.uint8]) -> Image.Image:
        return Image.fromarray(state * np.uint8(self.scale), mode="L")

    def decode(self, image: Image.Image) -> NDArray[np.uint8]:
        arr = np.asarray(image.convert("L"))
        return (arr // self.scale).astype(np.uint8)

    def build(self, params: dict[str, Any], initial: NDArray[np.uint8] | None) -> Simulation:
        if self.family == "wireworld":
            if initial is not None:
                p = WireworldParams.from_dict(params)
                return Wireworld(size=(p.width, p.height), init=initial, boundary=p.boundary)  # type: ignore[arg-type]
            return Wireworld.from_params(WireworldParams.from_dict(params))
        if initial is not None:
            p2 = CyclicParams.from_dict(params)
            return Cyclic(
                p2.states,
                size=(p2.width, p2.height),
                threshold=p2.threshold,
                reach=p2.reach,
                neighborhood=p2.neighborhood,
                init=initial,
            )
        return Cyclic.from_params(CyclicParams.from_dict(params))


class _Rgb:
    def encode(self, state: NDArray[np.uint8]) -> Image.Image:
        return Image.fromarray(state, mode="RGB")

    def decode(self, image: Image.Image) -> NDArray[np.uint8]:
        return np.asarray(image.convert("RGB")).astype(np.uint8)

    def build(self, params: dict[str, Any], initial: NDArray[np.uint8] | None) -> Simulation:
        p = MergeLifeParams.from_dict(params)
        if initial is not None:
            return MergeLife(p.genome, size=(p.width, p.height), init=initial, seed=p.seed)
        return MergeLife.from_params(p)


CODECS: dict[str, _Codec] = {
    "lifelike": _Binary("lifelike"),
    "elementary": _Binary("elementary"),
    "cyclic": _Indexed("cyclic", scale=1),
    "wireworld": _Indexed("wireworld", scale=85),
    "mergelife": _Rgb(),
}


def state_to_image(family: str, state: NDArray[np.uint8]) -> Image.Image:
    return CODECS[family].encode(state)


def image_to_state(family: str, image: Image.Image) -> NDArray[np.uint8]:
    return CODECS[family].decode(image)


def build_sim(
    family: str, params: dict[str, Any], initial: NDArray[np.uint8] | None = None
) -> Simulation:
    return CODECS[family].build(params, initial)
