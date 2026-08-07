"""Family registry: everything the playground knows about a simulation family.

Deliberately Qt-free so it can be tested headlessly. New families appear in the UI
by registering here — there is no per-family widget code.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

import numpy as np

from heaton_life.ca import LifeLike, LifeLikeParams
from heaton_life.ca.rulestring import parse_rule
from heaton_life.core.neighbors import Boundary
from heaton_life.core.params import Params
from heaton_life.core.protocols import Simulation


@dataclasses.dataclass(frozen=True)
class Family:
    key: str
    label: str
    category: str
    params_cls: type[Params]
    build: Callable[[Params], Simulation]
    hot_fields: frozenset[str]
    """Params that can change without discarding the current state."""
    hot_apply: Callable[[Simulation, Params], Simulation]
    validate: Callable[[Params], tuple[str, str] | None]
    """Returns (field_name, message) for the first invalid field, or None."""
    default_cmap: str
    presets: dict[str, dict[str, object]]


FAMILIES: dict[str, Family] = {}


def register(family: Family) -> None:
    FAMILIES[family.key] = family


def _build_lifelike(params: Params) -> Simulation:
    assert isinstance(params, LifeLikeParams)
    return LifeLike.from_params(params)


def _hot_lifelike(sim: Simulation, params: Params) -> Simulation:
    assert isinstance(params, LifeLikeParams)
    boundary: Boundary = "dead" if params.boundary == "dead" else "torus"
    return LifeLike(
        params.rule,
        size=(params.width, params.height),
        init=np.asarray(sim.state, dtype=np.uint8),
        boundary=boundary,
    )


def _validate_lifelike(params: Params) -> tuple[str, str] | None:
    assert isinstance(params, LifeLikeParams)
    try:
        parse_rule(params.rule)
    except ValueError as exc:
        return ("rule", str(exc))
    return None


register(
    Family(
        key="lifelike",
        label="Life-like",
        category="Cellular Automata",
        params_cls=LifeLikeParams,
        build=_build_lifelike,
        hot_fields=frozenset({"rule", "boundary"}),
        hot_apply=_hot_lifelike,
        validate=_validate_lifelike,
        default_cmap="phosphor",
        presets={
            "Conway soup": {"rule": "B3/S23", "init": "soup", "density": 0.35},
            "HighLife": {"rule": "B36/S23", "init": "soup", "density": 0.4},
            "Seeds": {"rule": "B2/S", "init": "blob", "density": 0.15},
            "Day & Night": {"rule": "B3678/S34678", "init": "soup", "density": 0.5},
            "Maze": {"rule": "B3/S12345", "init": "blob", "density": 0.3},
            "Diamoeba": {"rule": "B35678/S5678", "init": "soup", "density": 0.48},
        },
    )
)
