"""Base class for simulation parameter dataclasses.

Params are frozen dataclasses that round-trip to snake_case JSON — the same schema
the .NET implementation and the conformance vectors consume.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from typing import Any, Self, get_origin, get_type_hints


@dataclasses.dataclass(frozen=True)
class Params:
    """Inherit with ``@dataclass(frozen=True)``; use only JSON-representable field types."""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in dataclasses.fields(self):
            value = getattr(self, f.name)
            if isinstance(value, tuple):
                value = list(value)
            out[f.name] = value
        return out

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        field_names = {f.name for f in dataclasses.fields(cls)}
        unknown = set(data) - field_names
        if unknown:
            raise ValueError(f"{cls.__name__}: unknown parameter(s) {sorted(unknown)}")
        hints = get_type_hints(cls)
        kwargs: dict[str, Any] = {}
        for f in dataclasses.fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            if get_origin(hints.get(f.name)) is tuple and isinstance(value, list):
                value = tuple(value)
            kwargs[f.name] = value
        return cls(**kwargs)

    @classmethod
    def from_json(cls, text: str) -> Self:
        return cls.from_dict(json.loads(text))

    def replace(self, **changes: Any) -> Self:
        return dataclasses.replace(self, **changes)
