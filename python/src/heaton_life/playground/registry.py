"""Family registry: everything the playground knows about a simulation family.

Deliberately Qt-free so it can be tested headlessly. New families appear in the UI
by registering here — there is no per-family widget code.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

import numpy as np

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
    parse_genome_error,
)
from heaton_life.ca.rulestring import parse_rule
from heaton_life.core.neighbors import Boundary
from heaton_life.core.params import Params
from heaton_life.core.protocols import Simulation
from heaton_life.lenia import (
    AsymptoticLenia,
    ClassicLenia,
    FlowLenia,
    FlowLeniaParams,
    LeniaParams,
)
from heaton_life.rd import GRAY_SCOTT_PRESETS, GrayScott, GrayScottParams

# Paint buttons: 1 = left, 2 = right, 3 = modifier+left.
PaintFn = Callable[[Simulation, int, int, int], None]


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
    paint: PaintFn | None = None


FAMILIES: dict[str, Family] = {}


def register(family: Family) -> None:
    FAMILIES[family.key] = family


def _no_validate(_params: Params) -> tuple[str, str] | None:
    return None


def _no_hot(sim: Simulation, _params: Params) -> Simulation:
    return sim


# -- Life-like ---------------------------------------------------------------------------


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


def _paint_binary(sim: Simulation, x: int, y: int, button: int) -> None:
    sim.state[y, x] = 0 if button == 2 else 1


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
        paint=_paint_binary,
    )
)


# -- Elementary ---------------------------------------------------------------------------


def _build_elementary(params: Params) -> Simulation:
    assert isinstance(params, ElementaryParams)
    return Elementary.from_params(params)


def _hot_elementary(sim: Simulation, params: Params) -> Simulation:
    assert isinstance(params, ElementaryParams)
    return Elementary(
        params.rule,
        size=(params.width, params.height),
        init=np.asarray(sim.state, dtype=np.uint8),
        boundary=params.boundary,
    )


register(
    Family(
        key="elementary",
        label="Elementary",
        category="Cellular Automata",
        params_cls=ElementaryParams,
        build=_build_elementary,
        hot_fields=frozenset({"rule", "boundary"}),
        hot_apply=_hot_elementary,
        validate=_no_validate,
        default_cmap="gray",
        presets={
            "Rule 30": {"rule": 30, "init": "single"},
            "Rule 90 (Sierpinski)": {"rule": 90, "init": "single"},
            "Rule 110": {"rule": 110, "init": "single"},
            "Rule 110 soup": {"rule": 110, "init": "soup", "density": 0.5},
            "Rule 184 (traffic)": {"rule": 184, "init": "soup", "density": 0.5},
        },
        paint=None,  # painting a space-time diagram makes no sense
    )
)


# -- Cyclic -------------------------------------------------------------------------------


def _build_cyclic(params: Params) -> Simulation:
    assert isinstance(params, CyclicParams)
    return Cyclic.from_params(params)


def _hot_cyclic(sim: Simulation, params: Params) -> Simulation:
    assert isinstance(params, CyclicParams)
    return Cyclic(
        params.states,
        size=(params.width, params.height),
        threshold=params.threshold,
        reach=params.reach,
        neighborhood=params.neighborhood,
        init=np.asarray(sim.state, dtype=np.uint8),
    )


def _paint_cyclic(sim: Simulation, x: int, y: int, button: int) -> None:
    if button == 2:
        sim.state[y, x] = 0
    else:
        states = int(sim.params.states)  # type: ignore[attr-defined]
        sim.state[y, x] = (int(sim.state[y, x]) + 1) % states


register(
    Family(
        key="cyclic",
        label="Cyclic",
        category="Cellular Automata",
        params_cls=CyclicParams,
        build=_build_cyclic,
        hot_fields=frozenset({"threshold", "reach", "neighborhood"}),
        hot_apply=_hot_cyclic,
        validate=_no_validate,
        default_cmap="rainbow",
        presets={
            "Demon spirals": {"states": 14, "threshold": 1, "reach": 1, "neighborhood": "moore"},
            "313": {"states": 3, "threshold": 3, "reach": 3, "neighborhood": "moore"},
            "Amoeba": {"states": 2, "threshold": 10, "reach": 3, "neighborhood": "vonneumann"},
        },
        paint=_paint_cyclic,
    )
)


# -- Wireworld ----------------------------------------------------------------------------


def _build_wireworld(params: Params) -> Simulation:
    assert isinstance(params, WireworldParams)
    return Wireworld.from_params(params)


def _hot_wireworld(sim: Simulation, params: Params) -> Simulation:
    assert isinstance(params, WireworldParams)
    boundary: Boundary = "torus" if params.boundary == "torus" else "dead"
    return Wireworld(
        size=(params.width, params.height),
        init=np.asarray(sim.state, dtype=np.uint8),
        boundary=boundary,
    )


def _paint_wireworld(sim: Simulation, x: int, y: int, button: int) -> None:
    value = {1: 3, 2: 0, 3: 1}.get(button, 3)  # left: conductor, right: erase, mod: head
    sim.state[y, x] = value


register(
    Family(
        key="wireworld",
        label="Wireworld",
        category="Cellular Automata",
        params_cls=WireworldParams,
        build=_build_wireworld,
        hot_fields=frozenset({"boundary"}),
        hot_apply=_hot_wireworld,
        validate=_no_validate,
        default_cmap="wireworld",
        presets={
            "Clock loop": {"init": "clock", "width": 64, "height": 64},
        },
        paint=_paint_wireworld,
    )
)


# -- MergeLife ----------------------------------------------------------------------------


def _build_mergelife(params: Params) -> Simulation:
    assert isinstance(params, MergeLifeParams)
    return MergeLife.from_params(params)


def _hot_mergelife(sim: Simulation, params: Params) -> Simulation:
    assert isinstance(params, MergeLifeParams)
    return MergeLife(
        params.genome,
        size=(params.width, params.height),
        init=np.asarray(sim.state, dtype=np.uint8),
        seed=params.seed,
    )


def _validate_mergelife(params: Params) -> tuple[str, str] | None:
    assert isinstance(params, MergeLifeParams)
    message = parse_genome_error(params.genome)
    if message is not None:
        return ("genome", message)
    return None


def _paint_mergelife(sim: Simulation, x: int, y: int, button: int) -> None:
    sim.state[y, x] = (0, 0, 0) if button == 2 else (255, 255, 255)


# -- Gray-Scott ---------------------------------------------------------------------------


def _build_grayscott(params: Params) -> Simulation:
    assert isinstance(params, GrayScottParams)
    return GrayScott.from_params(params)


def _hot_grayscott(sim: Simulation, params: Params) -> Simulation:
    assert isinstance(params, GrayScottParams)
    return GrayScott(
        size=(params.width, params.height),
        du=params.du,
        dv=params.dv,
        feed=params.feed,
        kill=params.kill,
        dt=params.dt,
        init=np.asarray(sim.state, dtype=np.float64),
        spots=params.spots,
        seed=params.seed,
    )


def _paint_grayscott(sim: Simulation, x: int, y: int, button: int) -> None:
    u, v = sim.state[0], sim.state[1]
    half = 3
    ys = slice(max(0, y - half), y + half + 1)
    xs = slice(max(0, x - half), x + half + 1)
    if button == 2:
        u[ys, xs] = 1.0
        v[ys, xs] = 0.0
    else:
        u[ys, xs] = 0.5
        v[ys, xs] = 0.25


register(
    Family(
        key="grayscott",
        label="Gray-Scott",
        category="Reaction-Diffusion",
        params_cls=GrayScottParams,
        build=_build_grayscott,
        hot_fields=frozenset({"du", "dv", "feed", "kill", "dt"}),
        hot_apply=_hot_grayscott,
        validate=_no_validate,
        default_cmap="fire",
        presets={name: dict(fk) for name, fk in GRAY_SCOTT_PRESETS.items()},
        paint=_paint_grayscott,
    )
)


# -- Lenia (classic / asymptotic / flow) ---------------------------------------------------


def _paint_lenia(sim: Simulation, x: int, y: int, button: int) -> None:
    a = sim.state
    height, width = a.shape
    r = 6
    ys = slice(max(0, y - r), min(height, y + r + 1))
    xs = slice(max(0, x - r), min(width, x + r + 1))
    if button == 2:
        a[ys, xs] = 0.0
    else:
        yy, xx = np.mgrid[ys, xs]
        bump = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2.0 * (r / 2.0) ** 2))
        np.clip(a[ys, xs] + bump, 0.0, 1.0, out=a[ys, xs])


def _lenia_kwargs(params: LeniaParams, state: np.ndarray) -> dict[str, object]:
    return {
        "size": (params.width, params.height),
        "radius": params.radius,
        "mu": params.mu,
        "sigma": params.sigma,
        "dt": params.dt,
        "init": state,
        "blobs": params.blobs,
        "density": params.density,
        "seed": params.seed,
    }


def _build_lenia_classic(params: Params) -> Simulation:
    assert isinstance(params, LeniaParams)
    return ClassicLenia.from_params(params)


def _hot_lenia_classic(sim: Simulation, params: Params) -> Simulation:
    assert isinstance(params, LeniaParams)
    return ClassicLenia(**_lenia_kwargs(params, np.asarray(sim.state)))  # type: ignore[arg-type]


def _build_lenia_asymptotic(params: Params) -> Simulation:
    assert isinstance(params, LeniaParams)
    return AsymptoticLenia.from_params(params)


def _hot_lenia_asymptotic(sim: Simulation, params: Params) -> Simulation:
    assert isinstance(params, LeniaParams)
    return AsymptoticLenia(**_lenia_kwargs(params, np.asarray(sim.state)))  # type: ignore[arg-type]


def _build_lenia_flow(params: Params) -> Simulation:
    assert isinstance(params, FlowLeniaParams)
    return FlowLenia.from_params(params)


def _hot_lenia_flow(sim: Simulation, params: Params) -> Simulation:
    assert isinstance(params, FlowLeniaParams)
    kwargs = _lenia_kwargs(params, np.asarray(sim.state))
    kwargs["theta"] = params.theta
    return FlowLenia(**kwargs)  # type: ignore[arg-type]


_LENIA_HOT = frozenset({"radius", "mu", "sigma", "dt"})

register(
    Family(
        key="lenia-classic",
        label="Classic",
        category="Lenia",
        params_cls=LeniaParams,
        build=_build_lenia_classic,
        hot_fields=_LENIA_HOT,
        hot_apply=_hot_lenia_classic,
        validate=_no_validate,
        default_cmap="ice",
        presets={
            "Standard soup": {},
            "Sparse solitons": {"blobs": 20},
            "Cool spots": {"mu": 0.13, "sigma": 0.014},
        },
        paint=_paint_lenia,
    )
)

register(
    Family(
        key="lenia-asymptotic",
        label="Asymptotic",
        category="Lenia",
        params_cls=LeniaParams,
        build=_build_lenia_asymptotic,
        hot_fields=_LENIA_HOT,
        hot_apply=_hot_lenia_asymptotic,
        validate=_no_validate,
        default_cmap="violet",
        presets={
            "Standard": {},
            "Soft (wide sigma)": {"sigma": 0.02},
        },
        paint=_paint_lenia,
    )
)

register(
    Family(
        key="lenia-flow",
        label="Flow",
        category="Lenia",
        params_cls=FlowLeniaParams,
        build=_build_lenia_flow,
        hot_fields=_LENIA_HOT | {"theta"},
        hot_apply=_hot_lenia_flow,
        validate=_no_validate,
        default_cmap="phosphor",
        presets={
            "Clumping soup": {},
            "Fine grains": {"sigma": 0.05},
            "Sparse drift": {"density": 0.2, "mu": 0.15, "sigma": 0.05},
        },
        paint=_paint_lenia,
    )
)


register(
    Family(
        key="mergelife",
        label="MergeLife",
        category="Cellular Automata",
        params_cls=MergeLifeParams,
        build=_build_mergelife,
        hot_fields=frozenset({"genome"}),
        hot_apply=_hot_mergelife,
        validate=_validate_mergelife,
        default_cmap="gray",  # unused: MergeLife frames are RGB passthrough
        presets={
            "Red World (paper)": {"genome": "e542-5f79-9341-f31e-6c6b-7f08-8773-7068"},
            "1c48-9004…": {"genome": "1c48-9004-8831-41be-2804-8f50-9901-db18"},
            "7e18-62ac…": {"genome": "7e18-62ac-5c42-109e-45a1-9ff2-b7d8-64a1"},
            "2152-9b71…": {"genome": "2152-9b71-abb7-162a-45ff-dd03-fe15-957e"},
        },
        paint=_paint_mergelife,
    )
)
