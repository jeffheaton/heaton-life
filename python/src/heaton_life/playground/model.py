"""Derive form-field descriptors from a params dataclass. Qt-free and headless-testable.

This is the payoff of params-as-dataclasses: the UI introspects field types and the
spec'd ranges/choices in field metadata, so families never write widget code.
"""

from __future__ import annotations

import dataclasses
from typing import Literal, get_type_hints

from heaton_life.core.params import Params

Kind = Literal["int", "float", "str", "bool", "choice"]


@dataclasses.dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: Kind
    default: object
    label: str
    minimum: float
    maximum: float
    step: float
    choices: tuple[str, ...]
    role: str | None
    """"seed" fields get a randomize button; more roles later."""
    decimals: int = 3


def field_specs(params_cls: type[Params]) -> list[FieldSpec]:
    hints = get_type_hints(params_cls)
    specs: list[FieldSpec] = []
    for f in dataclasses.fields(params_cls):
        meta = f.metadata
        hint = hints.get(f.name, str)
        choices = tuple(str(c) for c in meta.get("choices", ()))
        kind: Kind
        if choices:
            kind = "choice"
        elif hint is bool:
            kind = "bool"
        elif hint is int:
            kind = "int"
        elif hint is float:
            kind = "float"
        else:
            kind = "str"
        if kind == "float":
            minimum, maximum, step = 0.0, 1.0, 0.01
        else:
            minimum, maximum, step = 0.0, 2_147_483_647.0, 1.0
        specs.append(
            FieldSpec(
                name=f.name,
                kind=kind,
                default=f.default,
                label=str(meta.get("label", f.name.replace("_", " ").title())),
                minimum=float(meta.get("min", minimum)),
                maximum=float(meta.get("max", maximum)),
                step=float(meta.get("step", step)),
                choices=choices,
                role=meta.get("role"),
                decimals=int(meta.get("decimals", 3)),
            )
        )
    return specs
