"""Family registry: everything the playground knows about a simulation family.

Deliberately Qt-free so it can be tested headlessly. New families appear in the UI
by registering here — there is no per-family widget code.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

import numpy as np

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
from heaton_life.playground.fractal_sim import (
    BurningShipSimParams,
    FractalSim,
    JuliaSimParams,
    MandelbrotSimParams,
    NewtonSimParams,
    make_burning_ship,
    make_julia,
    make_mandelbrot,
    make_newton,
    zoom_paint,
)
from heaton_life.rd import GRAY_SCOTT_PRESETS, GrayScott, GrayScottParams

# Paint buttons: 1 = left, 2 = right, 3 = modifier+left, 4/5 = wheel in/out.
# A paint fn may mutate in place (return None) or return a replacement Simulation
# (fractal zoom); the engine swaps it in and echoes the new params to the form.
PaintFn = Callable[[Simulation, int, int, int], Simulation | None]


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
    wheel_zoom: bool = False
    """Route wheel events (buttons 4/5) to paint; only navigation-style families want this."""


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


# -- Boids --------------------------------------------------------------------------------


def _build_boids(params: Params) -> Simulation:
    assert isinstance(params, BoidsParams)
    return Boids.from_params(params)


def _hot_boids(sim: Simulation, params: Params) -> Simulation:
    assert isinstance(params, BoidsParams)
    return Boids(
        params.count,
        size=(params.width, params.height),
        perception=params.perception,
        separation_radius=params.separation_radius,
        w_separation=params.w_separation,
        w_alignment=params.w_alignment,
        w_cohesion=params.w_cohesion,
        max_speed=params.max_speed,
        min_speed=params.min_speed,
        max_force=params.max_force,
        boundary=params.boundary,
        init=np.asarray(sim.state, dtype=np.float64),
        seed=params.seed,
    )


def _paint_boids(sim: Simulation, x: int, y: int, button: int) -> None:
    """Left: scare boids away from the click; right: lure them toward it."""
    if button not in (1, 2, 3):
        return
    state = np.asarray(sim.state)
    p = sim.params  # type: ignore[attr-defined]
    offset = state[:, 0:2] - np.array([float(x), float(y)])
    size = np.array([float(p.width), float(p.height)])
    if p.boundary == "wrap":
        offset -= size * np.round(offset / size)
    dist = np.sqrt((offset**2).sum(axis=1, keepdims=True))
    nearby = (dist[:, 0] > 0.0) & (dist[:, 0] < 48.0)
    if not nearby.any():
        return
    direction = offset[nearby] / dist[nearby]
    if button == 2:
        direction = -direction
    state[nearby, 2:4] += direction * p.max_speed * 0.8


register(
    Family(
        key="boids",
        label="Reynolds",
        category="Boids",
        params_cls=BoidsParams,
        build=_build_boids,
        hot_fields=frozenset(
            {
                "perception",
                "separation_radius",
                "w_separation",
                "w_alignment",
                "w_cohesion",
                "max_speed",
                "min_speed",
                "max_force",
                "boundary",
            }
        ),
        hot_apply=_hot_boids,
        validate=_no_validate,
        default_cmap="phosphor",
        presets={
            "Flocking": {},
            "Murmuration": {
                "count": 700,
                "perception": 16.0,
                "w_alignment": 1.3,
                "w_cohesion": 0.7,
                "w_separation": 1.6,
                "max_speed": 3.5,
            },
            "Tight schools": {
                "count": 400,
                "perception": 10.0,
                "separation_radius": 4.0,
                "w_cohesion": 1.6,
                "max_speed": 2.5,
            },
            "Aviary (bounce)": {"count": 250, "boundary": "bounce"},
        },
        paint=_paint_boids,
    )
)


# -- Fractals -----------------------------------------------------------------------------


def _validate_fractal(params: Params) -> tuple[str, str] | None:
    import decimal

    for field in ("center_re", "center_im"):
        try:
            decimal.Decimal(getattr(params, field))
        except decimal.InvalidOperation:
            return (field, f"{field} must be a decimal number string")
    return None


def _register_fractal(
    key: str,
    label: str,
    params_cls: type[Params],
    make_field: Callable[[Params], object],
    default_cmap: str,
    presets: dict[str, dict[str, object]],
    zoom_max: float = 290.0,
) -> None:
    def build(params: Params) -> Simulation:
        return FractalSim(params, make_field, zoom_max=zoom_max)  # type: ignore[arg-type]

    def paint(sim: Simulation, x: int, y: int, button: int) -> Simulation | None:
        assert isinstance(sim, FractalSim)
        return zoom_paint(sim, x, y, button, build, zoom_max)  # type: ignore[arg-type]

    register(
        Family(
            key=key,
            label=label,
            category="Fractals",
            params_cls=params_cls,
            build=build,
            hot_fields=frozenset(),  # every change re-renders; build handles all
            hot_apply=lambda _sim, params: build(params),
            validate=_validate_fractal,
            default_cmap=default_cmap,
            presets=presets,
            paint=paint,
            wheel_zoom=True,
        )
    )


_register_fractal(
    "mandelbrot",
    "Mandelbrot",
    MandelbrotSimParams,
    make_mandelbrot,
    "fire",
    {
        "Home": {},
        "Seahorse valley": {
            "center_re": "-0.7435",
            "center_im": "0.1314",
            "zoom_log10": 2.5,
            "max_iter": 2000,
        },
        "Past float64 (1e14)": {
            "center_re": "-0.743643887037158704752191506114774",
            "center_im": "0.131825904205311970493132056385139",
            "zoom_log10": 14.0,
            "max_iter": 5000,
        },
    },
)

_register_fractal(
    "julia",
    "Julia",
    JuliaSimParams,
    make_julia,
    "ice",
    {
        "Classic": {},
        "Douady rabbit": {"c_re": -0.123, "c_im": 0.745},
        "Dendrite (c = i)": {"c_re": 0.0, "c_im": 1.0},
    },
)

_register_fractal(
    "burning-ship",
    "Burning Ship",
    BurningShipSimParams,
    make_burning_ship,
    "violet",
    {
        "Full ship": {},
        "Antenna armada": {
            "center_re": "-1.755",
            "center_im": "-0.03",
            "zoom_log10": 1.8,
            "max_iter": 1500,
        },
    },
)

_register_fractal(
    "newton",
    "Newton",
    NewtonSimParams,
    make_newton,
    "rainbow",
    {
        "z³ − 1": {},
        "z⁵ − 1": {"degree": 5},
    },
    zoom_max=12.0,
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
            "1c48-9004-8831-41be-2804-8f50-9901-db18": {
                "genome": "1c48-9004-8831-41be-2804-8f50-9901-db18"
            },
            "7e18-62ac-5c42-109e-45a1-9ff2-b7d8-64a1": {
                "genome": "7e18-62ac-5c42-109e-45a1-9ff2-b7d8-64a1"
            },
            "2152-9b71-abb7-162a-45ff-dd03-fe15-957e": {
                "genome": "2152-9b71-abb7-162a-45ff-dd03-fe15-957e"
            },
        },
        paint=_paint_mergelife,
    )
)
