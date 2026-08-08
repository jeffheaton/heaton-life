"""Conformance-vector codecs: how each family's state maps to/from vector files,
and how a simulation is rebuilt from a vector's params.json.

This module is the Python side of the cross-language contract in ../../vectors/;
the .NET implementation mirrors it. Encodings are per-family and spec'd:

- lifelike:        PNG, pixel = state * 255                       (bit-exact)
- elementary:      PNG, 1 x width, pixel = tape * 255             (bit-exact)
- cyclic:          PNG, pixel = raw state                         (bit-exact)
- wireworld:       PNG, pixel = state * 85                        (bit-exact)
- mergelife:       RGB PNG, raw bytes                             (bit-exact)
- grayscott:       .f64 raw little-endian float64, shape (2,H,W)  (epsilon)
- lenia-classic:   .f64, shape (H,W)                              (epsilon)
- lenia-asymptotic:.f64, shape (H,W)                              (epsilon)
- lenia-flow:      .f64, shape (H,W)                              (epsilon)

Float checkpoints carry their shape in the checkpoint entry; ε-tier cases carry
an "epsilon" in params.json (max absolute deviation for cross-language replay —
same-language replay is exact).
"""

from __future__ import annotations

import io
from collections.abc import Callable, Sequence
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from heaton_life.boids import Boids, BoidsParams
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
from heaton_life.lenia import (
    AsymptoticLenia,
    ClassicLenia,
    FlowLenia,
    FlowLeniaParams,
    LeniaParams,
)
from heaton_life.rd import GrayScott, GrayScottParams

FloatArray = NDArray[np.float64]
StateArray = NDArray[Any]


class Codec(Protocol):
    ext: str

    def encode(self, state: StateArray) -> bytes: ...

    def decode(self, data: bytes, shape: Sequence[int] | None) -> StateArray: ...

    def build(self, params: dict[str, Any], initial: StateArray | None) -> Simulation: ...


def _png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


class _Binary:
    """0/1 grids stored as 0/255 grayscale PNG."""

    ext = "png"

    def __init__(self, family: str) -> None:
        self.family = family

    def encode(self, state: StateArray) -> bytes:
        arr = np.atleast_2d(state) * np.uint8(255)
        return _png_bytes(Image.fromarray(arr, mode="L"))

    def decode(self, data: bytes, shape: Sequence[int] | None) -> StateArray:
        with Image.open(io.BytesIO(data)) as img:
            arr = (np.asarray(img.convert("L")) > 0).astype(np.uint8)
        return arr[0] if self.family == "elementary" else arr

    def build(self, params: dict[str, Any], initial: StateArray | None) -> Simulation:
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
    """Small-integer state grids stored as grayscale PNG (optionally scaled)."""

    ext = "png"

    def __init__(self, family: str, scale: int) -> None:
        self.family = family
        self.scale = scale

    def encode(self, state: StateArray) -> bytes:
        return _png_bytes(Image.fromarray(state * np.uint8(self.scale), mode="L"))

    def decode(self, data: bytes, shape: Sequence[int] | None) -> StateArray:
        with Image.open(io.BytesIO(data)) as img:
            arr = np.asarray(img.convert("L"))
        return (arr // self.scale).astype(np.uint8)

    def build(self, params: dict[str, Any], initial: StateArray | None) -> Simulation:
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
    ext = "png"

    def encode(self, state: StateArray) -> bytes:
        return _png_bytes(Image.fromarray(state, mode="RGB"))

    def decode(self, data: bytes, shape: Sequence[int] | None) -> StateArray:
        with Image.open(io.BytesIO(data)) as img:
            return np.asarray(img.convert("RGB")).astype(np.uint8)

    def build(self, params: dict[str, Any], initial: StateArray | None) -> Simulation:
        p = MergeLifeParams.from_dict(params)
        if initial is not None:
            return MergeLife(p.genome, size=(p.width, p.height), init=initial, seed=p.seed)
        return MergeLife.from_params(p)


class _Float64:
    """Float fields stored as raw little-endian float64; shape lives in the checkpoint."""

    ext = "f64"

    def __init__(self, build_fn: Callable[[dict[str, Any]], Simulation]) -> None:
        self._build_fn = build_fn

    def encode(self, state: StateArray) -> bytes:
        return np.ascontiguousarray(state, dtype="<f8").tobytes()

    def decode(self, data: bytes, shape: Sequence[int] | None) -> StateArray:
        if shape is None:
            raise ValueError("f64 checkpoints require a 'shape' entry")
        return np.frombuffer(data, dtype="<f8").reshape(tuple(shape)).copy()

    def build(self, params: dict[str, Any], initial: StateArray | None) -> Simulation:
        if initial is not None:
            raise ValueError("float-family vectors rebuild from params; no array init")
        return self._build_fn(params)


CODECS: dict[str, Codec] = {
    "lifelike": _Binary("lifelike"),
    "elementary": _Binary("elementary"),
    "cyclic": _Indexed("cyclic", scale=1),
    "wireworld": _Indexed("wireworld", scale=85),
    "mergelife": _Rgb(),
    "grayscott": _Float64(lambda p: GrayScott.from_params(GrayScottParams.from_dict(p))),
    "lenia-classic": _Float64(lambda p: ClassicLenia.from_params(LeniaParams.from_dict(p))),
    "lenia-asymptotic": _Float64(
        lambda p: AsymptoticLenia.from_params(LeniaParams.from_dict(p))
    ),
    "lenia-flow": _Float64(lambda p: FlowLenia.from_params(FlowLeniaParams.from_dict(p))),
    "boids": _Float64(lambda p: Boids.from_params(BoidsParams.from_dict(p))),
}

# (tier, epsilon): epsilon is the max absolute deviation for cross-language replay.
TIERS: dict[str, tuple[str, float | None]] = {
    "lifelike": ("bit-exact", None),
    "elementary": ("bit-exact", None),
    "cyclic": ("bit-exact", None),
    "wireworld": ("bit-exact", None),
    "mergelife": ("bit-exact", None),
    "grayscott": ("epsilon", 1e-9),
    "lenia-classic": ("epsilon", 1e-6),
    "lenia-asymptotic": ("epsilon", 1e-6),
    "lenia-flow": ("epsilon", 1e-6),
    "boids": ("epsilon", 1e-6),
}


def state_to_bytes(family: str, state: StateArray) -> bytes:
    return CODECS[family].encode(state)


def bytes_to_state(family: str, data: bytes, shape: Sequence[int] | None = None) -> StateArray:
    return CODECS[family].decode(data, shape)


def build_sim(
    family: str, params: dict[str, Any], initial: StateArray | None = None
) -> Simulation:
    return CODECS[family].build(params, initial)
