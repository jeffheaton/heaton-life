#!/usr/bin/env python3
"""Regenerate the golden conformance vectors in ../../vectors/.

Run only when a spec change justifies it; vectors are the cross-language contract.
(vectors/mergelife-upstream/ is NOT generated here — it tracks the upstream repo.)
Usage: .venv/bin/python tools/gen_vectors.py
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from heaton_life.boids import BoidsParams
from heaton_life.ca import LifeLike, Wireworld, wireworld_from_text
from heaton_life.conformance import CODECS, TIERS, build_sim
from heaton_life.core import decimal_text
from heaton_life.core.bignum import reference_orbit, reference_orbit_x, working_bits
from heaton_life.core.protocols import Field, Simulation
from heaton_life.core.viewport import Viewport
from heaton_life.fractal import BurningShip, Julia, Mandelbrot, Newton, pan, pixel_delta, zoom_at
from heaton_life.fractal.engine import orbit_zoom
from heaton_life.init import place, rle_decode

SPEC_VERSION = "0.2.0"  # what existing cases were written under; new fractal cases pass theirs
REPO_ROOT = Path(__file__).resolve().parents[2]
VECTOR_ROOT = REPO_ROOT / "vectors"

GLIDER_RLE = "x = 3, y = 3, rule = B3/S23\nbob$2bo$3o!"

# Dinkydau's "11 Dimensions", 256 decimal places.
ELEVEN_DIMENSIONS_RE = (
    "-1.789169018604823106674468341188838763817361836815907015582201739718100615627027"
    "574914236924582039605440639575567531218327153412892304947143409769022231541920271"
    "538326405015913194702917367739501587876736286253331090293821032099999999999999999"
    "9999999999999998"
)
ELEVEN_DIMENSIONS_IM = (
    "-0.000000339368515767182566028230266146812728348218894593856901397469694238873656"
    "911013614721917617426684297223646854879514198904612245023079025046965906353413282"
    "632411984659927807440363593913324582126454730659527320203070323299999999999999999"
    "9999999999999998"
)


def _vector_params(family: str, params: dict[str, Any]) -> dict[str, Any]:
    """Spell ``params`` the way the committed vectors do (the frozen wire format)."""
    if family == "mergelife":
        # spec/mergelife.md: the JSON key "genome" is frozen; the API calls it the rule.
        # conformance.py's _Rgb.build maps it back.
        return {("genome" if k == "rule" else k): v for k, v in params.items()}
    if family == "boids":
        # 2D vectors predate the d-dimensional change and carry neither key; the
        # Python and C# runners default dimensions=2, depth=256 when they are absent.
        defaults = {f.name: f.default for f in dataclasses.fields(BoidsParams)}
        if all(params[k] == defaults[k] for k in ("dimensions", "depth")):
            return {k: v for k, v in params.items() if k not in ("dimensions", "depth")}
    return params


def write_case(family: str, name: str, sim: Simulation, steps: list[int]) -> None:
    codec = CODECS[family]
    tier, epsilon = TIERS[family]
    case_dir = VECTOR_ROOT / family / name
    case_dir.mkdir(parents=True, exist_ok=True)
    checkpoints: list[dict[str, Any]] = []
    current = 0
    for step in steps:
        sim.step(step - current)
        current = step
        state = np.asarray(sim.state)
        file = f"state_{step:05d}.{codec.ext}"
        (case_dir / file).write_bytes(codec.encode(state))
        entry: dict[str, Any] = {"step": step, "file": file}
        if codec.ext == "f64":
            entry["shape"] = list(state.shape)
        checkpoints.append(entry)
    meta: dict[str, Any] = {
        "spec_version": SPEC_VERSION,
        "family": family,
        "tier": tier,
        "params": _vector_params(family, sim.params.to_dict()),  # type: ignore[attr-defined]
        "checkpoints": checkpoints,
    }
    if epsilon is not None:
        meta["epsilon"] = epsilon
    (case_dir / "params.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", newline="\n"
    )
    print(f"wrote {case_dir.relative_to(REPO_ROOT)} (steps {steps})")


def gen_mergelife_decode() -> None:
    """spec/mergelife.md "Decoded rule table" — display-ready rows, bit-exact."""
    from heaton_life.ca.mergelife import decode_rule

    cases = [
        ("red-world", "e542-5f79-9341-f31e-6c6b-7f08-8773-7068"),
        ("promoted-and-negative", "ff40-00c0-8020-407f-2081-6001-a0ff-e080"),
        ("tied-limits", "1010-1020-1030-1040-1050-1060-1070-1080"),
    ]
    for name, rule in cases:
        rows = []
        for row in decode_rule(rule):
            entry = dataclasses.asdict(row)
            entry["target_rgb"] = list(entry["target_rgb"])
            rows.append(entry)
        case_dir = VECTOR_ROOT / "mergelife-decode" / name
        case_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "family": "mergelife-decode",
            "case": name,
            "tier": "bit-exact",
            "rule": rule,
            "expected_rows": rows,
        }
        (case_dir / "params.json").write_text(
            json.dumps(meta, indent=2, sort_keys=True) + "\n", newline="\n"
        )
        print(f"wrote {case_dir.relative_to(REPO_ROOT)}")


def main() -> None:
    # -- lifelike ------------------------------------------------------------------
    pattern, _ = rle_decode(GLIDER_RLE)
    glider = LifeLike("B3/S23", size=(16, 16), init=place(pattern, (16, 16), at=(0, 0)))
    write_case("lifelike", "glider-16-torus", glider, [0, 32, 64])

    lifelike_cases: list[tuple[str, dict[str, Any]]] = [
        ("soup-64-torus", {"rule": "B3/S23", "density": 0.35, "seed": 42}),
        ("soup-64-dead", {"rule": "B3/S23", "density": 0.35, "seed": 7, "boundary": "dead"}),
        ("highlife-64-torus", {"rule": "B36/S23", "density": 0.4, "seed": 11}),
        # `single` and `blob` close the init-coverage hole: until these, only
        # `soup` and `array` were vectored for this family, so the .NET port could
        # ship WITHOUT the spec's `single` strategy and no suite noticed. The
        # replicator is used for `single` so the case exercises real evolution out
        # of one cell rather than a lone cell dying on step 1 under B3/S23.
        ("replicator-single-64", {"rule": "B1357/S1357", "init": "single"}),
        ("blob-64-torus", {"rule": "B3/S23", "init": "blob", "density": 0.35, "seed": 5}),
    ]
    for name, overrides in lifelike_cases:
        params = {"width": 64, "height": 64, **overrides}
        write_case("lifelike", name, build_sim("lifelike", params), [0, 1, 10, 100])

    # -- elementary ----------------------------------------------------------------
    write_case(
        "elementary",
        "rule30-single-128",
        build_sim("elementary", {"rule": 30, "width": 128, "height": 64, "init": "single"}),
        [0, 1, 64, 127],
    )
    write_case(
        "elementary",
        "rule110-soup-128",
        build_sim(
            "elementary",
            {"rule": 110, "width": 128, "height": 64, "init": "soup", "seed": 42},
        ),
        [0, 1, 64, 127],
    )
    write_case(
        "elementary",
        "rule90-dead-128",
        build_sim(
            "elementary",
            {"rule": 90, "width": 128, "height": 64, "init": "single", "boundary": "dead"},
        ),
        [0, 1, 64, 127],
    )

    # -- cyclic --------------------------------------------------------------------
    write_case(
        "cyclic",
        "demons-64",
        build_sim("cyclic", {"states": 14, "width": 64, "height": 64, "seed": 42}),
        [0, 1, 10, 50],
    )
    write_case(
        "cyclic",
        "r2t5-vonneumann-64",
        build_sim(
            "cyclic",
            {
                "states": 6,
                "threshold": 2,
                "reach": 2,
                "neighborhood": "vonneumann",
                "width": 64,
                "height": 64,
                "seed": 9,
            },
        ),
        [0, 1, 10, 50],
    )

    # -- wireworld -----------------------------------------------------------------
    write_case(
        "wireworld",
        "clock-16",
        build_sim("wireworld", {"width": 16, "height": 16, "init": "clock"}),
        [0, 1, 10, 40],
    )
    # Two parallel wires converging on one cell: exercises the 1-or-2-heads rule.
    junction = wireworld_from_text("TH########.\n..........#\nTH########.\n")
    grid = place(junction, (16, 8), at=(1, 2))
    write_case("wireworld", "junction-16", Wireworld(size=(16, 8), init=grid), [0, 1, 5, 20])

    gen_mergelife_decode()

    # -- mergelife -----------------------------------------------------------------
    write_case(
        "mergelife",
        "redworld-48",
        build_sim(
            "mergelife",
            {
                "genome": "e542-5f79-9341-f31e-6c6b-7f08-8773-7068",
                "width": 48,
                "height": 48,
                "seed": 5,
            },
        ),
        [0, 1, 10, 50],
    )

    # -- grayscott -----------------------------------------------------------------
    write_case(
        "grayscott",
        "mitosis-center-64",
        build_sim(
            "grayscott",
            {"feed": 0.0367, "kill": 0.0649, "width": 64, "height": 64, "init": "center"},
        ),
        [0, 1, 100, 500],
    )
    write_case(
        "grayscott",
        "coral-spots-64",
        build_sim(
            "grayscott",
            {"feed": 0.0545, "kill": 0.062, "width": 64, "height": 64, "seed": 3},
        ),
        [0, 1, 100, 500],
    )

    # -- lenia ---------------------------------------------------------------------
    write_case(
        "lenia-classic",
        "blobs-64",
        build_sim("lenia-classic", {"width": 64, "height": 64, "seed": 7}),
        [0, 1, 10, 50],
    )
    write_case(
        "lenia-asymptotic",
        "blobs-64",
        build_sim("lenia-asymptotic", {"width": 64, "height": 64, "seed": 7}),
        [0, 1, 10, 50],
    )
    write_case(
        "lenia-flow",
        "blobs-64",
        build_sim("lenia-flow", {"width": 64, "height": 64, "seed": 7, "init": "blobs"}),
        [0, 1, 10, 50],
    )
    # Flow's real default. Until 2026-08-21 FlowLeniaParams inherited the base
    # class's `blobs`, so the params path (which this generator uses) disagreed
    # with the constructor and the case named "soup-64" was recorded from BLOBS.
    # The default is fixed in lenia/flow.py; the original bytes keep their true
    # name above, and the soup path is vectored here for the first time.
    write_case(
        "lenia-flow",
        "soup-64",
        build_sim("lenia-flow", {"width": 64, "height": 64, "seed": 7}),
        [0, 1, 10, 50],
    )

    # -- boids ---------------------------------------------------------------------
    write_case(
        "boids",
        "flock-64",
        build_sim("boids", {"count": 40, "width": 64, "height": 64, "seed": 3}),
        [0, 1, 10, 50],
    )
    write_case(
        "boids",
        "flock3d-64",
        build_sim(
            "boids",
            {
                "count": 40,
                "dimensions": 3,
                "width": 64,
                "height": 64,
                "depth": 64,
                "seed": 3,
            },
        ),
        [0, 1, 10, 50],
    )

    # -- fractals (one-shot renders: params + viewport + int32 outputs) --------------
    write_fractal_case(
        "mandelbrot",
        "home-64",
        Mandelbrot(max_iter=500),
        {"max_iter": 500, "escape_radius": 1000.0},
        Viewport("-0.5", "0.0", 0.0),
        (64, 64),
    )
    write_fractal_case(
        "mandelbrot",
        "deep-zoom14-48",
        Mandelbrot(max_iter=5000),
        {"max_iter": 5000, "escape_radius": 1000.0},
        Viewport(
            "-0.743643887037158704752191506114774",
            "0.131825904205311970493132056385139",
            14.0,
        ),
        (48, 48),
        orbit_kind="mandelbrot",
    )
    # T0 with a 33-place center, non-square: the float64 projection of the center must
    # be the one correctly rounded double on every platform (the C# port computes it
    # from the digits; double.Parse is only guaranteed on .NET Core), and a 48x32
    # frame pins width-based framing -- every earlier vector was square.
    write_fractal_case(
        "mandelbrot",
        "seahorse-zoom6-48x32",
        Mandelbrot(max_iter=2000),
        {"max_iter": 2000, "escape_radius": 1000.0},
        Viewport(
            "-0.743643887037158704752191506114774",
            "0.131825904205311970493132056385139",
            6.0,
        ),
        (48, 32),
        spec_version="0.3.0",
    )
    # Past zoom ~268.8 the working precision exceeds 1022 fractional bits; the C#
    # fixed point -> float64 conversion threw on any orbit component below ~1e-292,
    # which a center this close to the real axis produces from Z1 on. The frame is
    # the antenna tip c = -2 (orbit 0, -2, 2, 2, ... with the imaginary part growing
    # 4x per step); every pixel matches a 1200-bit direct iteration.
    write_fractal_case(
        "mandelbrot",
        "deep-zoom280-tinyim-32",
        Mandelbrot(max_iter=1000),
        {"max_iter": 1000, "escape_radius": 1000.0},
        Viewport("-2", "1e-295", 280.0),
        (32, 32),
        orbit_kind="mandelbrot",
        spec_version="0.3.0",
    )
    # A 256-place center at F = 915 bits (the digit term; zoom 20 alone would ask for
    # 194). It pins the fixed-point orbit arithmetic the two ports share, which the old
    # floating-point Python orbit fails; its 4,001 samples do not reach the depth where
    # the digit term itself changes a sample -- the zoom-160 orbit digest in both test
    # suites and the working-bits asserts pin that. Every pixel matches a 1200-bit
    # direct iteration.
    write_fractal_case(
        "mandelbrot",
        "deep-zoom20-11dim-32",
        Mandelbrot(max_iter=4000),
        {"max_iter": 4000, "escape_radius": 1000.0},
        Viewport(ELEVEN_DIMENSIONS_RE, ELEVEN_DIMENSIONS_IM, 20.0),
        (32, 32),
        orbit_kind="mandelbrot",
        source='Dinkydau, "11 Dimensions" (Kalles Fraktaler location; center only)',
        spec_version="0.3.0",
    )
    write_fractal_case(
        "julia",
        "classic-64",
        Julia(max_iter=500),
        {"c_re": -0.7269, "c_im": 0.1889, "max_iter": 500, "escape_radius": 1000.0},
        Viewport("0.0", "0.0", 0.0),
        (64, 64),
    )
    # Deep Julia at the rabbit's repelling fixed point beta = (1 + sqrt(1 - 4c)) / 2,
    # which lies on the Julia set: pixels separate from the reference within ~30
    # iterations, pass closer to 0 than to it, and rebase — onto the critical
    # orbit, the case this vector exists to pin. Every pixel matches a 300-bit
    # direct iteration (tests/test_fractal.py).
    write_fractal_case(
        "julia",
        "deep-zoom13-32",
        Julia(c=complex(-0.123, 0.745), max_iter=600),
        {"c_re": -0.123, "c_im": 0.745, "max_iter": 600, "escape_radius": 1000.0},
        Viewport(
            "1.27658194945592591790467276337476",
            "-0.47966605489732779175475867397901",
            13.0,
        ),
        (32, 32),
        orbit_kind="julia",
        spec_version="0.3.0",
    )
    write_fractal_case(
        "burning-ship",
        "home-64",
        BurningShip(max_iter=500),
        {"max_iter": 500, "escape_radius": 1000.0},
        Viewport("-0.5", "-0.5", -0.2),
        (64, 64),
    )
    # The first Burning Ship T1 case: a main-body boundary frame whose pixels rebase and
    # take every diffabs sign case. Every pixel matches a 400-bit direct iteration.
    write_fractal_case(
        "burning-ship",
        "deep-zoom13-32",
        BurningShip(max_iter=1000),
        {"max_iter": 1000, "escape_radius": 1000.0},
        Viewport("0.403269293475576420989278613990", "-0.595275727121703516488710194270", 13.0),
        (32, 32),
        orbit_kind="burning_ship",
        spec_version="0.3.0",
    )

    # -- off-center references (spec/deep-zoom.md "Off-center reference") ------------
    # Each deep frame above again, iterating a reference a fraction of a frame from the
    # center, so every pixel's delta is round64(center - reference) + its offset. They
    # match direct iteration of each pixel's exact coordinate as well as the centered
    # frames do: Julia and the Burning Ship on every pixel, the Seahorse on 2298 of 2304
    # (the centered frame: 2299; the rest are chaotic boundary pixels). Being well
    # conditioned, the Julia and Burning Ship counts equal their centered frames', so
    # test_off_center_reference.py's shared delta table and orbit-selection test (and
    # their C# twins) cover the rounding and orbit choice these two cannot see.
    write_fractal_case(
        "mandelbrot",
        "deep-zoom14-offref-48",
        Mandelbrot(max_iter=5000),
        {"max_iter": 5000, "escape_radius": 1000.0},
        Viewport(
            "-0.743643887037158704752191506114774",
            "0.131825904205311970493132056385139",
            14.0,
            reference_re="-0.743643887037146704752191506114774",  # (+0.3, -0.2) frames
            reference_im="0.131825904205303970493132056385139",
        ),
        (48, 48),
        orbit_kind="mandelbrot",
        spec_version="0.4.0",
    )
    write_fractal_case(
        "julia",
        "deep-zoom13-offref-32",
        Julia(c=complex(-0.123, 0.745), max_iter=600),
        {"c_re": -0.123, "c_im": 0.745, "max_iter": 600, "escape_radius": 1000.0},
        Viewport(
            "1.27658194945592591790467276337476",
            "-0.47966605489732779175475867397901",
            13.0,
            reference_re="1.27658194945578591790467276337476",  # (-0.35, +0.25) frames
            reference_im="-0.47966605489722779175475867397901",
        ),
        (32, 32),
        orbit_kind="julia",
        spec_version="0.4.0",
    )
    write_fractal_case(
        "burning-ship",
        "deep-zoom13-offref-32",
        BurningShip(max_iter=1000),
        {"max_iter": 1000, "escape_radius": 1000.0},
        Viewport(
            "0.403269293475576420989278613990",
            "-0.595275727121703516488710194270",
            13.0,
            reference_re="0.403269293475696420989278613990",  # (+0.3, +0.3) frames
            reference_im="-0.595275727121583516488710194270",
        ),
        (32, 32),
        orbit_kind="burning_ship",
        spec_version="0.4.0",
    )
    write_fractal_case(
        "newton",
        "z3-64",
        Newton(degree=3, max_iter=60),
        {"degree": 3, "max_iter": 60},
        Viewport("0.0", "0.0", -0.1),
        (64, 64),
    )

    # -- status (spec/fractals.md "Interior shortcuts", "Status") ---------------------
    # T0 frames with every way a count is decided: escaped, exhausted, inside the
    # cardioid or the period-2 bulb (Mandelbrot), and an exact float64 cycle. The
    # counts are what they always were; the status output says which were proved.
    write_fractal_case(
        "mandelbrot",
        "status-home-64",
        Mandelbrot(max_iter=500),
        {"max_iter": 500, "escape_radius": 1000.0},
        Viewport("-0.5", "0.0", 0.0),
        (64, 64),
        spec_version="0.6.0",
        status=True,
    )
    write_fractal_case(
        "mandelbrot",
        "status-minibrot-48x32",
        Mandelbrot(max_iter=3000),
        {"max_iter": 3000, "escape_radius": 1000.0},
        Viewport("-1.7549", "0.0", 2.0),
        (48, 32),
        spec_version="0.6.0",
        status=True,
    )
    write_fractal_case(
        "julia",
        "status-rabbit-64",
        Julia(c=complex(-0.123, 0.745), max_iter=1000),
        {"c_re": -0.123, "c_im": 0.745, "max_iter": 1000, "escape_radius": 1000.0},
        Viewport("0.0", "0.0", 0.0),
        (64, 64),
        spec_version="0.6.0",
        status=True,
    )
    # max_iter inside the detection window: which rabbit pixels are proved by iteration 40
    # depends on the exact save schedule (n = 1, 2, 4, ...); a schedule shifted by one,
    # saving at 2^k - 1, every iteration, or only at n = 1 each proves a different set.
    write_fractal_case(
        "julia",
        "status-rabbit-it40-64",
        Julia(c=complex(-0.123, 0.745), max_iter=40),
        {"c_re": -0.123, "c_im": 0.745, "max_iter": 40, "escape_radius": 1000.0},
        Viewport("0.0", "0.0", 0.0),
        (64, 64),
        spec_version="0.6.0",
        status=True,
    )
    write_fractal_case(
        "burning-ship",
        "status-home-64",
        BurningShip(max_iter=1000),
        {"max_iter": 1000, "escape_radius": 1000.0},
        Viewport("-0.5", "-0.5", -0.2),
        (64, 64),
        spec_version="0.6.0",
        status=True,
    )
    write_distance_cases()
    write_bla_cases()

    # -- iteration policy (spec/fractals.md "Iteration policy") -----------------------
    write_policy_cases()

    # -- render (colormap LUTs + frame indexing, spec/render.md) ---------------------
    write_render_cases()
    write_frame_cases()
    write_color_cases()

    # -- evolve (objective stats, GA operators, seeded mini-run, spec/evolve.md) -----
    write_evolve_cases()

    # -- patterns (RLE dialects, transforms, stamp semantics, spec/patterns.md) ------
    write_pattern_cases()

    # -- navigation (exact viewport arithmetic, spec/navigation.md) -------------------
    write_navigation_cases()

    # -- locations (framing conventions and importers, spec/locations.md) ------------
    write_location_cases()

    # -- discovery (box period, Newton's nucleus, atom size, spec/nucleus.md) ---------
    write_nucleus_cases()

    # -- T2: perturbation past 1e290 (spec/deep-zoom.md "T2") -------------------------
    write_floatexp_cases()
    write_t2_step_cases()
    write_t2_cases()
    write_t2_bla_cases()

    print("done")


def write_fractal_case(
    family: str,
    name: str,
    field: Any,
    params: dict[str, Any],
    viewport: Viewport,
    size: tuple[int, int],
    orbit_kind: str | None = None,
    source: str | None = None,
    spec_version: str = SPEC_VERSION,
    status: bool = False,
    distance: bool = False,
    bla: bool = False,
    bla_table: bool = False,
    small_orbits: bool = False,
    bla_table_x: bool = False,
) -> None:
    case_dir = VECTOR_ROOT / family / name
    case_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[dict[str, Any]] = []
    grids = dict(field.outputs(size, viewport))
    if status:  # spec/fractals.md "Status": how each count was decided
        grids["status"] = field.counts_and_status(size, viewport)[1]
    for kind, grid in grids.items():
        file = f"{kind}.i32"
        (case_dir / file).write_bytes(np.ascontiguousarray(grid, dtype="<i4").tobytes())
        outputs.append({"kind": kind, "file": file, "shape": list(grid.shape)})
    if bla:  # spec/deep-zoom.md "BLA": each pixel's skips, which must happen
        applied = field.fields(size, viewport, bla_applications=True).bla_applications
        assert int(applied.sum()) > 0, f"{family}/{name}: BLA never engaged"
        (case_dir / "bla_applications.i32").write_bytes(
            np.ascontiguousarray(applied, dtype="<i4").tobytes()
        )
        outputs.append(
            {
                "kind": "bla_applications",
                "file": "bla_applications.i32",
                "shape": list(applied.shape),
            }
        )
    if bla_table_x:  # the T2 table, bit for bit: coefficients and floatexp radii
        from heaton_life.fractal.bla import build_table_t2, frame_dc_bound_exponent, table_words_x
        from heaton_life.fractal.engine import pixel_deltas_x

        orbit_x = reference_orbit_x(
            "mandelbrot", *viewport.orbit_center, viewport.zoom_log10, params["max_iter"]
        )
        samples = orbit_x.samples[: params["max_iter"] + 1]
        small = np.zeros(samples.size, dtype=bool)
        small[orbit_x.small.index[orbit_x.small.index < samples.size]] = True
        deltas = pixel_deltas_x(size, viewport)
        k = frame_dc_bound_exponent(deltas.rm, deltas.re, deltas.im, deltas.ie)
        table_x = build_table_t2(samples, small, params["escape_radius"], k)
        words = np.where(
            np.isnan(table_words_x(table_x)), np.nan, table_words_x(table_x)
        )  # one NaN
        (case_dir / "bla_table_x.f64").write_bytes(
            np.ascontiguousarray(words, dtype="<f8").tobytes()
        )
        outputs.append(
            {
                "kind": "bla_table_x",
                "file": "bla_table_x.f64",
                "shape": [int(words.size)],
                "entries": [int(level.rm.size) for level in table_x.levels],
            }
        )
    if bla_table:  # the table itself, bit for bit, from this case's orbit and frame
        from heaton_life.fractal.bla import build_table, frame_dc_bound, table_words
        from heaton_life.fractal.engine import pixel_deltas

        orbit = reference_orbit(
            "mandelbrot", *viewport.orbit_center, viewport.zoom_log10, params["max_iter"]
        )
        table = build_table(
            orbit, params["escape_radius"], frame_dc_bound(pixel_deltas(size, viewport))
        )
        words = table_words(table)
        (case_dir / "bla_table.f64").write_bytes(np.ascontiguousarray(words, dtype="<f8").tobytes())
        outputs.append(
            {
                "kind": "bla_table",
                "file": "bla_table.f64",
                "shape": [int(words.size)],
                "entries": [int(level.r.size) for level in table.levels],
            }
        )
    if distance:  # spec/fractals.md "Distance estimate": relative epsilon
        fields = field.fields(size, viewport, distance=True)
        assert np.array_equal(fields.counts, grids["iterations"]), "the distance loop's counts"
        de = fields.distance
        (case_dir / "distance.f64").write_bytes(np.ascontiguousarray(de, dtype="<f8").tobytes())
        outputs.append(
            {
                "kind": "distance",
                "file": "distance.f64",
                "shape": list(de.shape),
                "relative_epsilon": 1e-12,
            }
        )
    meta: dict[str, Any] = {
        "spec_version": spec_version,
        "family": family,
        "tier": "bit-exact",
        "params": params,
        "viewport": viewport.to_dict(),
        "size": list(size),
        "outputs": outputs,
    }
    if source is not None:
        meta["source"] = source  # attribution for a third-party location
    if params.get("bla") and viewport.zoom_log10 > 290.0:
        # BLA at T2: the frame's dc bound 2^k (null: every delta zero), which no output can
        # show past zoom ~300 (spec/deep-zoom.md "BLA at T2").
        from heaton_life.fractal.bla import frame_dc_bound_exponent
        from heaton_life.fractal.engine import pixel_deltas_x

        deltas = pixel_deltas_x(size, viewport)
        meta["dc_bound_exponent"] = frame_dc_bound_exponent(
            deltas.rm, deltas.re, deltas.im, deltas.ie
        )
    if small_orbits:  # T2 (spec/deep-zoom.md "T2"): the orbits' length and small samples
        c_re = params.get("c_re", 0.0)
        c_im = params.get("c_im", 0.0)
        kind = "julia" if family == "julia" else "mandelbrot"
        pins = [("reference_small", viewport.orbit_center)]
        if family == "julia":
            pins.append(("critical_small", ("0", "0")))
        for key, (re_text, im_text) in pins:
            orbit_x = reference_orbit_x(
                kind,
                re_text,
                im_text,
                orbit_zoom(kind, viewport.zoom_log10),
                params["max_iter"],
                c_re=c_re,
                c_im=c_im,
            )
            small = orbit_x.small
            samples = np.ascontiguousarray(orbit_x.samples, dtype="<c16").tobytes()
            meta[key] = {
                "length": len(orbit_x.samples),
                "sha256": hashlib.sha256(samples).hexdigest(),
                "rows": [
                    [int(i), _bits(float(rm)), int(re), _bits(float(im)), int(ie)]
                    for i, rm, re, im, ie in zip(
                        small.index, small.re_m, small.re_e, small.im_m, small.im_e, strict=True
                    )
                ],
            }
    if orbit_kind is not None:
        c_re = params.get("c_re", 0.0)
        c_im = params.get("c_im", 0.0)
        orbit = reference_orbit(
            orbit_kind,
            *viewport.orbit_center,
            orbit_zoom(orbit_kind, viewport.zoom_log10),
            params["max_iter"],
            c_re=c_re,
            c_im=c_im,
        )
        (case_dir / "orbit.c128").write_bytes(np.ascontiguousarray(orbit, dtype="<c16").tobytes())
        meta["reference_orbit"] = {"file": "orbit.c128", "length": len(orbit)}
        if orbit_kind == "julia":
            # A Julia reference starts at the center; rebased pixels restart on the
            # critical orbit (z0 = 0, same c), which the vector pins too so a port
            # with no bignum stack can replay the case (spec/deep-zoom.md "Rebasing").
            critical = reference_orbit(
                "julia",
                "0",
                "0",
                orbit_zoom("julia", viewport.zoom_log10),
                params["max_iter"],
                c_re=c_re,
                c_im=c_im,
            )
            (case_dir / "critical.c128").write_bytes(
                np.ascontiguousarray(critical, dtype="<c16").tobytes()
            )
            meta["critical_orbit"] = {"file": "critical.c128", "length": len(critical)}
    (case_dir / "params.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", newline="\n"
    )
    print(f"wrote {case_dir.relative_to(REPO_ROOT)}")


def write_distance_cases() -> None:
    """Distance estimate (spec/fractals.md, 0.7.0): counts bit-exact, DE relative 1e-12."""
    seahorse = (
        "-0.743643887037158704752191506114774",
        "0.131825904205311970493132056385139",
    )
    rabbit = {"c_re": -0.123, "c_im": 0.745}
    write_fractal_case(
        "mandelbrot",
        "distance-home-64",
        Mandelbrot(max_iter=500),
        {"max_iter": 500, "escape_radius": 1000.0},
        Viewport("-0.5", "0.0", 0.0),
        (64, 64),
        spec_version="0.7.0",
        status=True,
        distance=True,
    )
    write_fractal_case(
        "mandelbrot",
        "distance-seahorse-zoom6-48x32",
        Mandelbrot(max_iter=2000),
        {"max_iter": 2000, "escape_radius": 1000.0},
        Viewport(*seahorse, 6.0),
        (48, 32),
        spec_version="0.7.0",
        distance=True,
    )
    write_fractal_case(
        "julia",
        "distance-rabbit-64",
        Julia(c=complex(-0.123, 0.745), max_iter=1000),
        {**rabbit, "max_iter": 1000, "escape_radius": 1000.0},
        Viewport("0.0", "0.0", 0.0),
        (64, 64),
        spec_version="0.7.0",
        distance=True,
    )
    # c outside the Mandelbrot set: every pixel escapes, and on an odd frame the center
    # pixel is z0 = 0 exactly, a critical point whose derivative stays 0 -- DE = +inf.
    write_fractal_case(
        "julia",
        "distance-dust-65",
        Julia(c=complex(0.3, 0.0), max_iter=200),
        {"c_re": 0.3, "c_im": 0.0, "max_iter": 200, "escape_radius": 1000.0},
        Viewport("0.0", "0.0", 0.0),
        (65, 65),
        spec_version="0.7.0",
        distance=True,
    )
    write_fractal_case(
        "mandelbrot",
        "distance-deep-zoom14-48",
        Mandelbrot(max_iter=5000),
        {"max_iter": 5000, "escape_radius": 1000.0},
        Viewport(*seahorse, 14.0),
        (48, 48),
        orbit_kind="mandelbrot",
        spec_version="0.7.0",
        distance=True,
    )
    write_fractal_case(
        "mandelbrot",
        "distance-offref-48",
        Mandelbrot(max_iter=5000),
        {"max_iter": 5000, "escape_radius": 1000.0},
        Viewport(
            *seahorse,
            14.0,
            reference_re="-0.743643887037146704752191506114774",
            reference_im="0.131825904205303970493132056385139",
        ),
        (48, 48),
        orbit_kind="mandelbrot",
        spec_version="0.7.0",
        distance=True,
    )
    # Rebased pixels: the derivative rides through every rebase onto the critical orbit.
    write_fractal_case(
        "julia",
        "distance-deep-zoom13-32",
        Julia(c=complex(-0.123, 0.745), max_iter=600),
        {**rabbit, "max_iter": 600, "escape_radius": 1000.0},
        Viewport(
            "1.27658194945592591790467276337476",
            "-0.47966605489732779175475867397901",
            13.0,
        ),
        (32, 32),
        orbit_kind="julia",
        spec_version="0.7.0",
        distance=True,
    )
    # The reference on Julia's critical point (Z0 = 0): the first pre-square z is
    # fl(Z0 + delta0) = delta0 itself -- dropping delta0 would leave d = 0 for good.
    write_fractal_case(
        "julia",
        "distance-critical-zoom13-32",
        Julia(c=complex(0.0, 1.0), max_iter=600),
        {"c_re": 0.0, "c_im": 1.0, "max_iter": 600, "escape_radius": 1000.0},
        Viewport("0.0", "0.0", 13.0),
        (32, 32),
        orbit_kind="julia",
        spec_version="0.7.0",
        distance=True,
    )
    # Far from the set at depth: |d| ends near 1.4e-163, where plain squares flush to 0
    # and would read DE = +inf (a false critical point); the scaled magnitude reads 2.25e167.
    write_fractal_case(
        "mandelbrot",
        "distance-far-zoom170-16",
        Mandelbrot(max_iter=2000),
        {"max_iter": 2000, "escape_radius": 1000.0},
        Viewport("-0.75", "0.1", 170.0),
        (16, 16),
        orbit_kind="mandelbrot",
        spec_version="0.7.0",
        distance=True,
    )
    write_fractal_case(
        "julia",
        "distance-far-zoom200-16",
        Julia(c=complex(0.3, 0.0), max_iter=2000),
        {"c_re": 0.3, "c_im": 0.0, "max_iter": 2000, "escape_radius": 1000.0},
        Viewport("0.001", "0.0", 200.0),
        (16, 16),
        orbit_kind="julia",
        spec_version="0.7.0",
        distance=True,
    )


# A period-24 nucleus on the real axis (|Z_24| < 4e-112).
NUCLEUS_P24 = ("-1.999969992922335067120936262876770995801628743210648088242038", "0")
# A period-16 nucleus (the reference passes within 5e-120 of 0 at Z_16, Z_32, ...).
NUCLEUS_P16 = (
    "-0.15290632811969396953419706326289366549612424542171",
    "1.03966209947138144375000734681034193201188490626331",
)
NUCLEUS_P1959 = (
    (
        "-0.74179270142920012328415486246133486546597975955966921338142290897793331586511"
        "46245001356794980988932282797"
    ),
    (
        "0.123977941724695971711689620339223320892796574416415373390553636985046660821372"
        "5129489699597506805010116194"
    ),
)


def _shifted(center: tuple[str, str], zoom: float, fx: float, fy: float) -> tuple[str, str]:
    """The center moved (fx, fy) frame widths, exactly in decimal (4 x 10^-zoom wide)."""
    import decimal

    with decimal.localcontext() as ctx:
        ctx.prec = 120
        span = decimal.Decimal(4) * decimal.Decimal(10) ** decimal.Decimal(repr(-zoom))
        return (
            str(decimal.Decimal(center[0]) + span * decimal.Decimal(repr(fx))),
            str(decimal.Decimal(center[1]) + span * decimal.Decimal(repr(fy))),
        )


def write_bla_cases() -> None:
    """BLA (spec/deep-zoom.md "BLA", 0.8.0): counts and per-pixel skips, bit-exact."""

    def case(
        name: str, max_iter: int, viewport: Viewport, size: tuple[int, int], **kw: Any
    ) -> None:
        write_fractal_case(
            "mandelbrot",
            name,
            Mandelbrot(max_iter=max_iter, bla=True),
            {"max_iter": max_iter, "escape_radius": 1000.0, "bla": True},
            viewport,
            size,
            orbit_kind="mandelbrot",
            spec_version="0.8.0",
            bla=True,
            **kw,
        )

    eleven = (ELEVEN_DIMENSIONS_RE, ELEVEN_DIMENSIONS_IM)
    # Multi-level skips on a non-escaping reference: 10 levels, 39 skips on some pixels.
    case("bla-11dim-zoom30-32", 8000, Viewport(*eleven, 30.0), (32, 32))
    # The same with an off-center reference: the dc bound includes the offset.
    case(
        "bla-11dim-offref-zoom30-24",
        8000,
        Viewport(*eleven, 30.0).with_reference(*_shifted(eleven, 30.0, 0.2, -0.1)),
        (24, 24),
        bla_table=True,
    )
    # A reference that escapes, pixels that rebase between skips (the oracle frame).
    case(
        "bla-p1959-zoom30-16",
        20000,
        Viewport(*_shifted(NUCLEUS_P1959, 30.0, 0.7, 0.0), 30.0),
        (16, 16),
        bla_table=True,
    )
    # Deltas near 1e-295: the dc bound and |dz| far below 1e-154, exponent-scaled.
    case("bla-tinyim-zoom280-32", 1000, Viewport("-2", "1e-295", 280.0), (32, 32))
    # The distance estimate through skips: d' = A d + B ps.
    case("bla-far-zoom170-16", 2000, Viewport("-0.75", "0.1", 170.0), (16, 16), distance=True)
    # Skips that land on a rebase: the reference passes near 0 at every multiple of 16.
    case(
        "bla-landing-rebase-12",
        3000,
        Viewport(*_shifted(NUCLEUS_P16, 25.0, 0.3, 0.1), 25.0),
        (12, 12),
    )
    # Skips that land on an escape: the reference escapes at Z_32, a multiple of the stride.
    case("bla-landing-escape-8", 2000, Viewport("-0.75", "0.10999", 30.0), (8, 8))
    # Skips cut short by max_iter: after rebases n > m, and near 2003 the longest live span
    # would overrun it (0.37 pixel off a period-24 nucleus).
    case(
        "bla-blocked-8",
        2003,
        Viewport(*_shifted(NUCLEUS_P24, 30.0, 0.37 / 8, 0.0), 30.0),
        (8, 8),
    )


def _bits(value: float) -> str:
    """A double as its IEEE-754 bit pattern, "0x" and 16 hex digits."""
    return f"0x{struct.unpack('<Q', struct.pack('<d', value))[0]:016X}"


def write_color_cases() -> None:
    """Fractal color (spec/fractal-color.md) and the phase lookup (spec/render.md), 0.7.0:
    explicit inputs -- real fields computed here -- and bit-exact outputs."""
    import io

    from PIL import Image

    from heaton_life.fractal.coloring import (
        PhaseParams,
        ShadeParams,
        apply_stretch,
        color_scale,
        depth_phase,
        measure_frequency,
        measure_stretch,
        shade_distance,
    )
    from heaton_life.render import apply_phase, get_colormap, list_cyclic_colormaps

    version = "0.7.0"

    def png_bytes(rgb: np.ndarray) -> bytes:
        buf = io.BytesIO()
        Image.fromarray(np.ascontiguousarray(rgb), mode="RGB").save(buf, format="PNG")
        return buf.getvalue()

    def f64(case_dir: Path, name: str, array: np.ndarray) -> dict[str, Any]:
        (case_dir / name).write_bytes(np.ascontiguousarray(array, dtype="<f8").tobytes())
        return {"file": name, "shape": list(array.shape)}

    def i32(case_dir: Path, name: str, array: np.ndarray) -> dict[str, Any]:
        (case_dir / name).write_bytes(np.ascontiguousarray(array, dtype="<i4").tobytes())
        return {"file": name, "shape": list(array.shape)}

    def png(case_dir: Path, name: str, rgb: np.ndarray) -> dict[str, Any]:
        (case_dir / name).write_bytes(png_bytes(rgb))
        return {"file": name, "shape": list(rgb.shape)}

    def start(name: str) -> Path:
        case_dir = VECTOR_ROOT / "render" / name
        case_dir.mkdir(parents=True, exist_ok=True)
        return case_dir

    def finish(case_dir: Path, meta: dict[str, Any]) -> None:
        meta = {"spec_version": version, "family": "render", "tier": "bit-exact", **meta}
        (case_dir / "params.json").write_text(
            json.dumps(meta, indent=2, sort_keys=True) + "\n", newline="\n"
        )
        print(f"wrote {case_dir.relative_to(REPO_ROOT)}")

    for name in list_cyclic_colormaps():
        case_dir = start(f"lut-{name}")
        (case_dir / "lut.png").write_bytes(png_bytes(get_colormap(name).reshape(1, 256, 3)))
        finish(
            case_dir,
            {"kind": "lut", "cmap": name, "output": {"file": "lut.png", "shape": [256, 3]}},
        )

    seahorse = ("-0.743643887037158704752191506114774", "0.131825904205311970493132056385139")
    home = Mandelbrot(max_iter=500).fields(
        (64, 64), Viewport("-0.5", "0.0", 0.0), smooth=True, distance=True
    )
    sea = Mandelbrot(max_iter=1600).fields(
        (96, 64), Viewport(*seahorse, 4.0), smooth=True, distance=True
    )
    deep = Mandelbrot(max_iter=3000).fields(
        (64, 48), Viewport(*seahorse, 7.0), smooth=True, distance=True
    )
    rabbit = Julia(c=complex(-0.123, 0.745), max_iter=1000).fields(
        (64, 64), Viewport("0.0", "0.0", 0.0), smooth=True, distance=True
    )
    assert home.smooth is not None and sea.smooth is not None and deep.smooth is not None
    assert rabbit.smooth is not None and home.distance is not None and sea.distance is not None

    # -- stretch: measured, applied from another frame (frozen), nothing escaped ------
    measured = measure_stretch(home.smooth)
    assert measured is not None
    for name, mu, given in [
        ("stretch-home", home.smooth, None),
        ("stretch-frozen", sea.smooth, measured),
        ("stretch-interior", np.zeros((8, 8)), None),
    ]:
        case_dir = start(name)
        meta: dict[str, Any] = {"kind": "stretch", "input": f64(case_dir, "mu.f64", mu)}
        if given is None:
            got = measure_stretch(mu)
            meta["measured"] = None if got is None else {"lo": _bits(got.lo), "hi": _bits(got.hi)}
            render = np.zeros(mu.shape) if got is None else apply_stretch(mu, got)
        else:
            meta["stretch"] = {"lo": _bits(given.lo), "hi": _bits(given.hi)}
            render = apply_stretch(mu, given)
        meta["output"] = f64(case_dir, "render.f64", render)
        finish(case_dir, meta)

    # -- depth phase -------------------------------------------------------------------
    flow = PhaseParams(
        cycles_per_iteration=0.02, cycles_per_octave=0.25, phase_offset=0.3, anchor=37.0
    )
    phases = {
        "phase-home": (home.smooth, 0.0, PhaseParams()),
        "phase-flow": (sea.smooth, 4.0, flow),
    }
    for name, (mu, zoom, params) in phases.items():
        case_dir = start(name)
        finish(
            case_dir,
            {
                "kind": "phase",
                "input": f64(case_dir, "mu.f64", mu),
                "zoom_log10": _bits(zoom),
                "phase": {k: _bits(v) for k, v in dataclasses.asdict(params).items()},
                "output": f64(case_dir, "t.f64", depth_phase(mu, zoom, params)),
            },
        )

    # -- frequency: capped, uncapped (a large maximum), too few steps ------------------
    sparse_counts = np.full((6, 6), -1, dtype=np.int32)
    sparse_counts[:, 0] = 5
    sparse_mu = np.where(sparse_counts > 0, 5.5, 0.0)

    def ramp(height: int, width: int) -> tuple[np.ndarray, np.ndarray]:
        counts = np.arange(1, height * width + 1, dtype=np.int32).reshape(height, width)
        return counts, 5.0 + 0.01 * np.arange(height * width, dtype=np.float64).reshape(
            height, width
        )

    # Exactly 64 steps, a median step under 1 (the clamp), an even count of positive
    # counts whose middle two differ (the upper median); and 63 steps (none).
    ramp64, ramp63 = ramp(2, 22), ramp(1, 64)
    frequencies = [
        ("frequency-home", home.counts, home.smooth, 0.03, 0.01),
        ("frequency-deep", deep.counts, deep.smooth, 0.03, 1.0),
        ("frequency-sparse", sparse_counts, sparse_mu, 0.03, 0.01),
        ("frequency-ramp-64", *ramp64, 0.03, 100.0),
        ("frequency-ramp-63", *ramp63, 0.03, 100.0),
    ]
    for name, counts, mu, target, cap in frequencies:
        case_dir = start(name)
        fit = measure_frequency(
            counts, mu, target_cycles_per_step=target, max_cycles_per_iteration=cap
        )
        finish(
            case_dir,
            {
                "kind": "frequency",
                "counts": i32(case_dir, "counts.i32", counts),
                "input": f64(case_dir, "mu.f64", mu),
                "target_cycles_per_step": _bits(target),
                "max_cycles_per_iteration": _bits(cap),
                "expected": None
                if fit is None
                else {
                    "cycles_per_iteration": _bits(fit.cycles_per_iteration),
                    "anchor": _bits(fit.anchor),
                },
            },
        )

    # -- the phase lookup: palettes, wraps, antialias, dither, interior, edge values ---
    edge = np.array(
        [
            np.nan,
            np.inf,
            -np.inf,
            1e300,
            -1e300,
            2.0**45,
            -(2.0**45),
            0.0,
            -0.0,
            1.0,
            -1.0,
            0.5 / 256,
            1.5 / 256,
            255.5 / 256,
            -0.3,
            1e-300,
            -1e-300,
            0.999999999999,
            3.25,
            -7.75,
            511.5 / 510,
            254.5 / 510,
            255.5 / 510,
            12345.678,
        ]
    ).reshape(4, 6)
    plain = np.concatenate([edge, (-4.0 + (np.arange(48) + 0.5) / 48.0).reshape(8, 6)])
    edge = np.tile(edge, (2, 2))
    t_home = depth_phase(home.smooth, 0.0, PhaseParams(cycles_per_iteration=0.05))
    t_sea = depth_phase(sea.smooth, 4.0, flow)
    t_rabbit = depth_phase(rabbit.smooth, 0.0, PhaseParams(cycles_per_iteration=0.03))
    lookups: list[tuple[str, np.ndarray, str, dict[str, Any]]] = [
        ("phase-apply-deep", t_home, "deep", {}),
        (
            "phase-apply-mirror-fire",
            t_sea,
            "fire",
            {"wrap": "mirror", "antialias": False, "dither": 0.0},
        ),
        (
            "phase-apply-classic-frame7",
            t_rabbit,
            "classic",
            {"interior": (20, 30, 40), "dither": 0.5, "frame_index": 7},
        ),
        ("phase-apply-edges-cyclic", edge, "glacier", {"frame_index": 4294967295}),
        ("phase-apply-edges-mirror", edge, "embers", {"wrap": "mirror", "dither": 2.0}),
        # The edge values straight through the lookup (no antialias to blend them to the
        # mean), with a fractional negative ramp: floor, not truncation, and the mod.
        ("phase-apply-plain-cyclic", plain, "glacier", {"antialias": False, "dither": 0.0}),
        (
            "phase-apply-plain-mirror",
            plain,
            "embers",
            {"wrap": "mirror", "antialias": False, "dither": 0.0},
        ),
        # A ramp whose rows each span 7/12 cycle: only a lookup that wraps its
        # neighbors across rows would antialias it.
        ("phase-apply-row-seam", np.tile(np.arange(8) / 12.0, (4, 1)), "deep", {}),
        # Every pixel halfway between two entries: the half-even rounding.
        (
            "phase-apply-halfway",
            ((np.arange(256) + 0.5) / 256.0).reshape(16, 16),
            "deep",
            {"antialias": False, "dither": 0.0},
        ),
    ]
    for name, t, cmap, options in lookups:
        case_dir = start(name)
        style = {
            "wrap": "cyclic",
            "interior": (0, 0, 0),
            "antialias": True,
            "dither": 1.0,
            "frame_index": 0,
            **options,
        }
        rgb = apply_phase(t, cmap, **style)
        finish(
            case_dir,
            {
                "kind": "phase-apply",
                "cmap": cmap,
                "wrap": style["wrap"],
                "interior": list(style["interior"]),
                "antialias": style["antialias"],
                "dither": _bits(style["dither"]),
                "frame_index": style["frame_index"],
                "input": f64(case_dir, "t.f64", t),
                "output": png(case_dir, "rgb.png", rgb),
            },
        )

    # -- distance shading ----------------------------------------------------------------
    edge_de = np.array([np.nan, 0.0, np.inf, 1e-300, 0.1, 0.25, 0.5, 1.0, 2.0, 1e300, 0.37, 0.0])
    edge_de = np.tile(edge_de, 20).reshape(12, 20)
    edge_de[5:8, 6:14] = 0.05  # a dense patch: nothing in reach clears a stroke width
    edge_rgb = (np.arange(12 * 20 * 3, dtype=np.int64) * 37 % 256).astype(np.uint8)
    halfway_de = np.full((8, 10), 1000.0)
    halfway_de[3:6, 3:7] = 0.0
    halfway_de[0, :3] = np.nan
    halfway_rgb = (np.arange(8 * 10 * 3, dtype=np.int64) * 2 + 1).astype(np.uint8).reshape(8, 10, 3)
    halfway_width = 1.6 / color_scale(10, 8)  # 1.6 pixels on this small frame
    shades = [
        ("shade-home", apply_phase(t_home, "deep"), home.distance, ShadeParams()),
        (
            "shade-seahorse-params",
            apply_phase(t_sea, "fire", wrap="mirror"),
            sea.distance,
            ShadeParams(width=3.0, strength=0.5, dense_release=0.25),
        ),
        ("shade-edges", edge_rgb.reshape(12, 20, 3), edge_de, ShadeParams()),
        # strength 0.75: g = sqrt(0.25) = 0.5 exactly, so odd bytes land on ties.
        ("shade-halfway", halfway_rgb, halfway_de, ShadeParams(width=halfway_width, strength=0.75)),
    ]
    for name, rgb, de, params in shades:
        case_dir = start(name)
        finish(
            case_dir,
            {
                "kind": "shade",
                "rgb": png(case_dir, "input.png", rgb),
                "input": f64(case_dir, "distance.f64", de),
                "shade": {k: _bits(v) for k, v in dataclasses.asdict(params).items()},
                "output": png(case_dir, "rgb.png", shade_distance(rgb, de, params)),
            },
        )


def write_render_cases() -> None:
    """Colormap conformance: every LUT byte-for-byte, plus float-frame indexing."""
    import io

    from PIL import Image

    from heaton_life.render import apply_colormap, get_colormap, list_colormaps

    def png_bytes(rgb: np.ndarray) -> bytes:
        buf = io.BytesIO()
        Image.fromarray(rgb, mode="RGB").save(buf, format="PNG")
        return buf.getvalue()

    for name in list_colormaps():
        case_dir = VECTOR_ROOT / "render" / f"lut-{name}"
        case_dir.mkdir(parents=True, exist_ok=True)
        lut = get_colormap(name)
        (case_dir / "lut.png").write_bytes(png_bytes(lut.reshape(1, 256, 3)))
        meta: dict[str, Any] = {
            "spec_version": SPEC_VERSION,
            "family": "render",
            "tier": "bit-exact",
            "kind": "lut",
            "cmap": name,
            "output": {"file": "lut.png", "shape": [256, 3]},
        }
        (case_dir / "params.json").write_text(
            json.dumps(meta, indent=2, sort_keys=True) + "\n", newline="\n"
        )
        print(f"wrote {case_dir.relative_to(REPO_ROOT)}")

    apply_cases = [
        # (name, cmap, height, width, denominator): frame[i] = i / denom, row-major.
        ("apply-ramp-fire", "fire", 16, 16, 255.0),
        # i/512 lands exact .5 index products: pins half-even rounding cross-language.
        ("apply-half-rainbow", "rainbow", 16, 32, 512.0),
    ]
    for case_name, cmap, height, width, denom in apply_cases:
        case_dir = VECTOR_ROOT / "render" / case_name
        case_dir.mkdir(parents=True, exist_ok=True)
        frame = (np.arange(height * width, dtype=np.float64) / denom).reshape(height, width)
        (case_dir / "frame.f64").write_bytes(np.ascontiguousarray(frame, dtype="<f8").tobytes())
        (case_dir / "rgb.png").write_bytes(png_bytes(apply_colormap(frame, cmap)))
        meta = {
            "spec_version": SPEC_VERSION,
            "family": "render",
            "tier": "bit-exact",
            "kind": "apply",
            "cmap": cmap,
            "input": {"file": "frame.f64", "shape": [height, width]},
            "output": {"file": "rgb.png", "shape": [height, width, 3]},
        }
        (case_dir / "params.json").write_text(
            json.dumps(meta, indent=2, sort_keys=True) + "\n", newline="\n"
        )
        print(f"wrote {case_dir.relative_to(REPO_ROOT)}")


def write_frame_cases() -> None:
    """Frame conformance (spec/render.md): explicit input state -> expected frame,
    plus ε-tier fractal renders rebuilt from params + viewport."""
    import io

    from PIL import Image

    from heaton_life.boids import Boids
    from heaton_life.ca import Cyclic, LifeLike
    from heaton_life.rd import GrayScott

    def gray_png(arr: np.ndarray) -> bytes:
        buf = io.BytesIO()
        Image.fromarray(arr.astype(np.uint8), mode="L").save(buf, format="PNG")
        return buf.getvalue()

    def write_meta(case_dir: Path, meta: dict[str, Any]) -> None:
        (case_dir / "params.json").write_text(
            json.dumps(meta, indent=2, sort_keys=True) + "\n", newline="\n"
        )
        print(f"wrote {case_dir.relative_to(REPO_ROOT)}")

    def frame_case(
        name: str,
        sim_family: str,
        params: dict[str, Any],
        sim: Any,
        float_frame: bool,
    ) -> None:
        case_dir = VECTOR_ROOT / "render" / name
        case_dir.mkdir(parents=True, exist_ok=True)
        state = np.asarray(sim.state)
        frame = np.asarray(sim.frame())
        meta: dict[str, Any] = {
            "spec_version": SPEC_VERSION,
            "family": "render",
            "tier": "bit-exact",
            "kind": "frame",
            "sim_family": sim_family,
            "params": params,
        }
        input_bytes = CODECS[sim_family].encode(state)
        ext = CODECS[sim_family].ext
        (case_dir / f"state.{ext}").write_bytes(input_bytes)
        meta["input"] = {"file": f"state.{ext}"}
        if ext == "f64":
            meta["input"]["shape"] = list(state.shape)
        if float_frame:
            (case_dir / "frame.f64").write_bytes(np.ascontiguousarray(frame, dtype="<f8").tobytes())
            meta["output"] = {"file": "frame.f64", "shape": list(frame.shape)}
        else:
            (case_dir / "frame.png").write_bytes(gray_png(frame))
            meta["output"] = {"file": "frame.png", "shape": list(frame.shape)}
        write_meta(case_dir, meta)

    lifelike = LifeLike("B3/S23", size=(32, 32), seed=3)
    lifelike.step(5)
    frame_case(
        "frame-lifelike",
        "lifelike",
        {"rule": "B3/S23", "width": 32, "height": 32, "boundary": "torus"},
        lifelike,
        float_frame=False,
    )

    cyclic = Cyclic(14, size=(32, 32), seed=42)
    cyclic.step(3)
    frame_case(
        "frame-cyclic",
        "cyclic",
        {
            "states": 14,
            "threshold": 1,
            "reach": 1,
            "neighborhood": "moore",
            "width": 32,
            "height": 32,
        },
        cyclic,
        float_frame=False,
    )

    wireworld = build_sim("wireworld", {"width": 16, "height": 16, "init": "clock"})
    wireworld.step(7)
    frame_case(
        "frame-wireworld",
        "wireworld",
        {"width": 16, "height": 16, "boundary": "dead"},
        wireworld,
        float_frame=False,
    )

    grayscott = GrayScott(size=(48, 48), feed=0.0367, kill=0.0649, init="center")
    grayscott.step(150)
    frame_case(
        "frame-grayscott",
        "grayscott",
        {
            "du": 0.16,
            "dv": 0.08,
            "feed": 0.0367,
            "kill": 0.0649,
            "dt": 1.0,
            "width": 48,
            "height": 48,
        },
        grayscott,
        float_frame=True,
    )

    # Handcrafted boid positions: corners, wrap edges, and an overlapping pair
    # that exercises accumulation + the clip.
    boid_state = np.array(
        [
            [0.0, 0.0, 1.0, 0.0],
            [15.9, 11.2, -1.0, 0.5],
            [7.5, 6.25, 0.0, 1.0],
            [8.2, 6.9, 0.5, -0.5],
            [0.4, 11.9, 2.0, 2.0],
        ],
        dtype=np.float64,
    )
    boids = Boids(5, size=(16, 12), init=boid_state)
    frame_case(
        "frame-boids",
        "boids",
        {
            "count": 5,
            "width": 16,
            "height": 12,
            "perception": 12.0,
            "separation_radius": 6.0,
            "w_separation": 1.5,
            "w_alignment": 1.0,
            "w_cohesion": 1.0,
            "max_speed": 3.0,
            "min_speed": 1.0,
            "max_force": 0.08,
            "boundary": "wrap",
        },
        boids,
        float_frame=True,
    )

    # 3D projection: handcrafted z values spanning the depth cue (z=0 full
    # brightness → z near depth dimmest), same overlap/wrap coverage.
    boid3d_state = np.array(
        [
            [0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            [15.9, 11.2, 47.0, -1.0, 0.5, 0.2],
            [7.5, 6.25, 24.0, 0.0, 1.0, -0.3],
            [8.2, 6.9, 12.0, 0.5, -0.5, 0.7],
            [0.4, 11.9, 36.0, 2.0, 2.0, 1.0],
        ],
        dtype=np.float64,
    )
    boids3d = Boids(5, dimensions=3, size=(16, 12), depth=48, init=boid3d_state)
    frame_case(
        "frame-boids3d",
        "boids",
        {
            "count": 5,
            "dimensions": 3,
            "width": 16,
            "height": 12,
            "depth": 48,
            "perception": 12.0,
            "separation_radius": 6.0,
            "w_separation": 1.5,
            "w_alignment": 1.0,
            "w_cohesion": 1.0,
            "max_speed": 3.0,
            "min_speed": 1.0,
            "max_force": 0.08,
            "boundary": "wrap",
        },
        boids3d,
        float_frame=True,
    )

    fractal_cases: list[tuple[str, str, Field, dict[str, Any], Viewport]] = [
        (
            "fractal-render-mandelbrot-home",
            "mandelbrot",
            Mandelbrot(max_iter=500),
            {"max_iter": 500, "escape_radius": 1000.0},
            Viewport("-0.5", "0.0", 0.0),
        ),
        (
            "fractal-render-newton-z3",
            "newton",
            Newton(degree=3, max_iter=60),
            {"degree": 3, "max_iter": 60},
            Viewport("0.0", "0.0", -0.1),
        ),
        # Deep Julia centered on sqrt(-c), a preimage of 0 (c = i): pixels rebase onto
        # the critical orbit W0 = 0, whose next step squares delta ~ 1e-158 -- a
        # subnormal product. C#'s software fma was inexact there before its exact slow
        # path; the counts still agreed, but final z and so this smooth render did not
        # (up to 4.5e-4 relative). spec/deep-zoom.md "Float-determinism gotchas".
        (
            "fractal-render-julia-deep157",
            "julia",
            Julia(c=1j, max_iter=2000),
            {"c_re": 0.0, "c_im": 1.0, "max_iter": 2000, "escape_radius": 1000.0},
            Viewport(
                "0.70710678118654752440084436210484903928483593768847403658833986899536623923105351942519376716382078636750692311545614851246241802792536860632206074854996791570661133296375279637789997525057639103028574",
                "-0.70710678118654752440084436210484903928483593768847403658833986899536623923105351942519376716382078636750692311545614851246241802792536860632206074854996791570661133296375279637789997525057639103028574",
                157.5,
            ),
        ),
    ]
    for name, family, field, params, viewport in fractal_cases:
        case_dir = VECTOR_ROOT / "render" / name
        case_dir.mkdir(parents=True, exist_ok=True)
        render = field.render((64, 64), viewport)
        (case_dir / "render.f64").write_bytes(np.ascontiguousarray(render, dtype="<f8").tobytes())
        write_meta(
            case_dir,
            {
                "spec_version": "0.3.0" if family == "julia" else SPEC_VERSION,
                "family": "render",
                "tier": "epsilon",
                "epsilon": 1e-9,
                "kind": "fractal-render",
                "sim_family": family,
                "params": params,
                "viewport": viewport.to_dict(),
                "size": [64, 64],
                "output": {"file": "render.f64", "shape": [64, 64]},
            },
        )


def write_pattern_cases() -> None:
    """Pattern conformance (spec/patterns.md): RLE decoding in both dialects with
    canonical re-encodes, transform results, and stamp semantics — all bit-exact."""
    import io

    from PIL import Image

    from heaton_life.init import extract, flip_h, flip_v, rle_decode, rle_encode, rotate90, stamp

    def gray_png(arr: np.ndarray) -> bytes:
        buf = io.BytesIO()
        Image.fromarray(arr.astype(np.uint8), mode="L").save(buf, format="PNG")
        return buf.getvalue()

    def write_meta(case_dir: Path, meta: dict[str, Any]) -> None:
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "params.json").write_text(
            json.dumps(meta, indent=2, sort_keys=True) + "\n", newline="\n"
        )
        print(f"wrote {case_dir.relative_to(REPO_ROOT)}")

    # RLE decode + canonical encode cases. Grids are stored raw-value grayscale.
    rle_cases = [
        (
            "rle-glider",
            ("#C the classic glider, comments and all\nx = 3, y = 3, rule = B3/S23\nbob$2bo$3o!\n"),
        ),
        (
            "rle-lwss-headerless",
            "b3o$o2bo$3bo$o2bo!\n",  # no header: size from extents
        ),
        (
            "rle-uppercase-two-state",
            (
                "x = 2, y = 2, rule = B3/S23\nOB$BO!\n"
            ),  # uppercase B/O with a Life-like rule: two-state dialect
        ),
        (
            "rle-wireworld-diode",
            (
                "x = 4, y = 3, rule = WireWorld\n.2C$AC.C$.2CB!\n"
            ),  # extended: B is state 2 here, not 'dead'
        ),
        (
            "rle-cyclic-bands",
            ("x = 5, y = 2, rule = cyclic-6\nABCDE$EDCBA!\n"),
        ),
    ]
    for name, text in rle_cases:
        case_dir = VECTOR_ROOT / "patterns" / name
        case_dir.mkdir(parents=True, exist_ok=True)
        grid, rule = rle_decode(text)
        canonical = rle_encode(grid, rule=rule if rule is not None else "B3/S23")
        (case_dir / "input.rle").write_text(text, newline="\n")
        (case_dir / "grid.png").write_bytes(gray_png(grid))
        (case_dir / "canonical.rle").write_text(canonical, newline="\n")
        write_meta(
            case_dir,
            {
                "spec_version": SPEC_VERSION,
                "family": "patterns",
                "tier": "bit-exact",
                "kind": "rle",
                "rule": rule,
                "input": "input.rle",
                "grid": {"file": "grid.png", "shape": list(grid.shape)},
                "canonical": "canonical.rle",
            },
        )

    # Transforms on an asymmetric multi-state grid (raw-value grayscale).
    base = np.array([[1, 2, 3, 0], [0, 4, 0, 5], [6, 0, 7, 8]], dtype=np.uint8)
    case_dir = VECTOR_ROOT / "patterns" / "transforms"
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "grid.png").write_bytes(gray_png(base))
    (case_dir / "rotate90.png").write_bytes(gray_png(rotate90(base)))
    (case_dir / "flip_h.png").write_bytes(gray_png(flip_h(base)))
    (case_dir / "flip_v.png").write_bytes(gray_png(flip_v(base)))
    write_meta(
        case_dir,
        {
            "spec_version": SPEC_VERSION,
            "family": "patterns",
            "tier": "bit-exact",
            "kind": "transform",
            "grid": {"file": "grid.png", "shape": list(base.shape)},
            "outputs": {
                "rotate90": "rotate90.png",
                "flip_h": "flip_h.png",
                "flip_v": "flip_v.png",
            },
        },
    )

    # Stamp semantics: wrap, clip, and transparency over a nonzero background.
    pattern = np.array([[0, 9, 0], [0, 0, 9], [9, 9, 9]], dtype=np.uint8)
    stamp_cases = [
        ("stamp-torus-wrap", 6, 5, 4, 3, True, False, 0),
        ("stamp-dead-clip", 6, 5, 4, 3, False, False, 0),
        ("stamp-transparent", 6, 5, 1, 1, True, True, 7),
        ("stamp-opaque", 6, 5, 1, 1, True, False, 7),
    ]
    for name, gw, gh, x, y, torus, transparent, background in stamp_cases:
        case_dir = VECTOR_ROOT / "patterns" / name
        case_dir.mkdir(parents=True, exist_ok=True)
        grid = np.full((gh, gw), background, dtype=np.uint8)
        stamp(grid, pattern, x, y, torus=torus, transparent=transparent)
        (case_dir / "pattern.png").write_bytes(gray_png(pattern))
        (case_dir / "expected.png").write_bytes(gray_png(grid))
        write_meta(
            case_dir,
            {
                "spec_version": SPEC_VERSION,
                "family": "patterns",
                "tier": "bit-exact",
                "kind": "stamp",
                "pattern": {"file": "pattern.png", "shape": list(pattern.shape)},
                "grid_width": gw,
                "grid_height": gh,
                "background": background,
                "x": x,
                "y": y,
                "torus": torus,
                "transparent": transparent,
                "expected": {"file": "expected.png", "shape": [gh, gw]},
            },
        )

    # Extract semantics: the same wrap/zero-fill contract, round-tripped.
    grid16 = np.arange(16, dtype=np.uint8).reshape(4, 4)
    for name, torus in (("extract-torus", True), ("extract-dead", False)):
        case_dir = VECTOR_ROOT / "patterns" / name
        case_dir.mkdir(parents=True, exist_ok=True)
        region = extract(grid16, 3, 3, 2, 2, torus=torus)
        (case_dir / "grid.png").write_bytes(gray_png(grid16))
        (case_dir / "expected.png").write_bytes(gray_png(region))
        write_meta(
            case_dir,
            {
                "spec_version": SPEC_VERSION,
                "family": "patterns",
                "tier": "bit-exact",
                "kind": "extract",
                "grid": {"file": "grid.png", "shape": [4, 4]},
                "x": 3,
                "y": 3,
                "width": 2,
                "height": 2,
                "torus": torus,
                "expected": {"file": "expected.png", "shape": [2, 2]},
            },
        )


def write_evolve_cases() -> None:
    """Evolve conformance: per-run objective stats, GA operator replays, one mini run.

    Everything is integer-driven or plain-double arithmetic, so all outputs are
    bit-exact; floats are stored raw (.f64), strings/ints in params.json.
    """
    from heaton_life.core.rng import Pcg32
    from heaton_life.evolve import Evolver, crossover, mutate, tournament_select
    from heaton_life.evolve.objective import PAPER_OBJECTIVE, _run_once, _score_stats

    redworld = "e542-5f79-9341-f31e-6c6b-7f08-8773-7068"

    def write_meta(case_dir: Path, meta: dict[str, Any]) -> None:
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "params.json").write_text(
            json.dumps(meta, indent=2, sort_keys=True) + "\n", newline="\n"
        )
        print(f"wrote {case_dir.relative_to(REPO_ROOT)}")

    # Objective scoring: per-run stats + score for each cycle, then the max.
    objective_cases = [
        ("objective-redworld-48", redworld, 48, 48, 3, 11, 500),
        ("objective-a07f-48", "a07f-c000-0000-0000-0000-0000-ff80-807f", 48, 48, 3, 21, 500),
    ]
    for name, genome, width, height, cycles, seed, max_steps in objective_cases:
        case_dir = VECTOR_ROOT / "evolve" / name
        case_dir.mkdir(parents=True, exist_ok=True)
        runs = np.empty((cycles, 6), dtype=np.float64)
        for i in range(cycles):
            stats = _run_once(genome, (width, height), seed + i, max_steps)
            runs[i] = [
                stats["steps"],
                stats["foreground"],
                stats["active"],
                stats["rect"],
                stats["mage"],
                _score_stats(stats, PAPER_OBJECTIVE),
            ]
        (case_dir / "runs.f64").write_bytes(np.ascontiguousarray(runs, dtype="<f8").tobytes())
        summary = np.array([runs[:, 5].max(), runs[:, 0].sum()], dtype=np.float64)
        (case_dir / "score.f64").write_bytes(np.ascontiguousarray(summary, dtype="<f8").tobytes())
        write_meta(
            case_dir,
            {
                "spec_version": SPEC_VERSION,
                "family": "evolve",
                "tier": "bit-exact",
                "kind": "objective",
                "params": {
                    "genome": genome,
                    "width": width,
                    "height": height,
                    "cycles": cycles,
                    "seed": seed,
                    "max_steps": max_steps,
                    "objective": "paper",
                },
                "outputs": {
                    "runs": {
                        "file": "runs.f64",
                        "shape": [cycles, 6],
                        "columns": ["steps", "foreground", "active", "rect", "mage", "score"],
                    },
                    "score": {
                        "file": "score.f64",
                        "shape": [2],
                        "columns": ["max_score", "total_steps"],
                    },
                },
            },
        )

    # GA operators: successive seeded applications, strings/ints only.
    rng = Pcg32(5)
    genome = redworld
    mutations = []
    for _ in range(8):
        genome = mutate(genome, rng)
        mutations.append(genome)
    rng = Pcg32(6)
    parent2 = "a07f-c000-0000-0000-0000-0000-ff80-807f"
    crossovers = [crossover(redworld, parent2, rng) for _ in range(4)]
    rng = Pcg32(7)
    scores = [0.5, -1.0, 2.25, 2.25, 0.0, 3.5, -0.25, 1.0]
    winners_best = [tournament_select(scores, 3, rng) for _ in range(8)]
    winners_worst = [tournament_select(scores, 3, rng, worst=True) for _ in range(8)]
    write_meta(
        VECTOR_ROOT / "evolve" / "operators-seeded",
        {
            "spec_version": SPEC_VERSION,
            "family": "evolve",
            "tier": "bit-exact",
            "kind": "operators",
            "params": {
                "genome": redworld,
                "parent2": parent2,
                "mutate_seed": 5,
                "crossover_seed": 6,
                "tournament_seed": 7,
                "tournament_rounds": 3,
                "tournament_scores": scores,
            },
            "expected": {
                "mutations": mutations,
                "crossovers": crossovers,
                "winners_best": winners_best,
                "winners_worst": winners_worst,
            },
        },
    )

    # Mini evolution run: the integration pin — deterministic end to end.
    evolver = Evolver(
        size=(24, 24),
        population_size=8,
        tournament_rounds=3,
        eval_cycles=1,
        patience=1000,
        max_steps=120,
        seed=123,
    )
    best = evolver.run(max_evals=20)
    case_dir = VECTOR_ROOT / "evolve" / "mini-run-24"
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "best.f64").write_bytes(np.array([best.score], dtype="<f8").tobytes())
    write_meta(
        case_dir,
        {
            "spec_version": SPEC_VERSION,
            "family": "evolve",
            "tier": "bit-exact",
            "kind": "run",
            "params": {
                "width": 24,
                "height": 24,
                "population_size": 8,
                "crossover_rate": 0.75,
                "tournament_rounds": 3,
                "eval_cycles": 1,
                "patience": 1000,
                "max_steps": 120,
                "seed": 123,
                "max_evals": 20,
                "objective": "paper",
            },
            "expected": {
                "best_genome": best.genome,
                "evals": evolver.evals,
                "population": [c.genome for c in evolver.population],
                "best_score": {"file": "best.f64", "shape": [1]},
            },
        },
    )


def write_policy_cases() -> None:
    """spec/fractals.md "Iteration policy" (policy version 1): the depth ramp at zooms
    that land on rounding ties and at the tiers' edges, and need/suggest for count sets
    (nearest-rank p99.9 in integers), including real frames' counts."""
    from heaton_life.fractal import auto_max_iter, need_from_counts, suggest_max_iter

    case_dir = VECTOR_ROOT / "iteration-policy" / "table"
    case_dir.mkdir(parents=True, exist_ok=True)
    zooms = [-3.0, -0.0, 0.0, 0.0025, 0.0075, 0.5, 1.0, 6.3, 12.0, 14.0, 20.5, 290.0]
    zooms += [1e7, 1.0737e7, 1.1e7, 1e300]  # the ramp saturates at the largest int32
    count_sets: list[tuple[float, list[int]]] = [
        (0.0, []),
        (0.0, [-1, -1, -1]),
        (0.0, [7]),
        (3.0, [-1, 5, 7, 7, 1000, -1, 3]),
        (1.5, list(range(1, 1001))),  # rank 999 of 1000
        (1.5, list(range(1, 1002))),  # rank 1000 of 1001
        (0.0, [2_000_000_000, 5]),  # the suggestion caps at the largest int32
    ]
    for size, zoom_log10, field in [
        ((64, 64), 0.0, Mandelbrot(max_iter=500)),
        ((48, 32), 6.0, Mandelbrot(max_iter=3000)),
    ]:
        vp = Viewport(
            "-0.743643887037158704752191506114774",
            "0.131825904205311970493132056385139",
            zoom_log10,
        )
        count_sets.append((zoom_log10, [int(v) for v in field.iterations(size, vp).ravel()]))
    meta = {
        "spec_version": "0.6.0",
        "family": "iteration-policy",
        "tier": "bit-exact",
        "policy_version": 1,
        "ramp": [{"zoom_log10": z, "max_iter": auto_max_iter(z)} for z in zooms],
        "frames": [
            {
                "zoom_log10": z,
                "counts": counts,
                "need": need_from_counts(np.array(counts, dtype=np.int64)),
                "suggest": suggest_max_iter(z, np.array(counts, dtype=np.int64)),
            }
            for z, counts in count_sets
        ],
    }
    (case_dir / "params.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    print("wrote vectors/iteration-policy/table")


def write_navigation_cases() -> None:
    """spec/navigation.md: pan, zoom_at, pixel_delta and positional, each case inputs plus
    the expected strings (or, for pixel_delta, the doubles' IEEE-754 bit patterns)."""
    root = VECTOR_ROOT / "navigation"

    def bits(value: float) -> str:
        return f"0x{int.from_bytes(np.float64(value).tobytes(), 'little'):016X}"

    def write(name: str, meta: dict[str, Any], spec_version: str = "0.5.0") -> None:
        case_dir = root / name
        case_dir.mkdir(parents=True, exist_ok=True)
        full = {
            "spec_version": spec_version,
            "family": "navigation",
            "tier": "bit-exact",
            **meta,
        }
        (case_dir / "params.json").write_text(json.dumps(full, indent=2, sort_keys=True) + "\n")
        print(f"wrote vectors/navigation/{name}")

    seahorse = Viewport(
        "-0.743643887037158704752191506114774", "0.131825904205311970493132056385139", 14.0
    )

    def pan_case(
        name: str,
        vp: Viewport,
        dx: float,
        dy: float,
        size: tuple[int, int],
        zoom: float | None = None,
        spec_version: str = "0.5.0",
    ) -> None:
        meta: dict[str, Any] = {
            "operation": "pan",
            "viewport": vp.to_dict(),
            "size": list(size),
            "dx": dx,
            "dy": dy,
        }
        if zoom is not None:
            meta["zoom_log10"] = zoom
        meta["expected"] = pan(vp, dx, dy, size, zoom).to_dict()
        write(name, meta, spec_version)

    def zoom_case(
        name: str,
        vp: Viewport,
        dx: float,
        dy: float,
        size: tuple[int, int],
        zoom: float,
        spec_version: str = "0.5.0",
    ) -> None:
        write(
            name,
            {
                "operation": "zoom_at",
                "viewport": vp.to_dict(),
                "size": list(size),
                "dx": dx,
                "dy": dy,
                "zoom_log10": zoom,
                "expected": zoom_at(vp, dx, dy, size, zoom).to_dict(),
            },
            spec_version,
        )

    def delta_case(
        name: str, frm: Viewport, to: Viewport, size: tuple[int, int], spec_version: str = "0.5.0"
    ) -> None:
        dx, dy = pixel_delta(frm, to, size)
        write(
            name,
            {
                "operation": "pixel_delta",
                "from": frm.to_dict(),
                "to": to.to_dict(),
                "size": list(size),
                "expected": {"dx_bits": bits(dx), "dy_bits": bits(dy)},
            },
            spec_version,
        )

    # A click on pixel (300, 17) of a 512x384 frame, and a fractional drag at a
    # fractional zoom (places use its ceiling).
    pan_case("pan-recenter-seahorse-512x384", seahorse, 300 + 0.5 - 256, 17 + 0.5 - 192, (512, 384))
    pan_case(
        "pan-drag-fractional-zoom6.3",
        dataclasses.replace(seahorse, zoom_log10=6.3),
        -3.75,
        12.125,
        (1920, 1080),
    )
    # A move of (0, 0) keeps the center strings, exponent notation and all; any other
    # move prints both components at the frame's places (1e-295 rounds to zero at 284).
    pan_case("pan-zero-keeps-strings", Viewport("-2", "1e-295", 280.0), 0.0, 0.0, (32, 32))
    pan_case("pan-horizontal-reprints-im", Viewport("-2", "1e-295", 280.0), 7.5, 0.0, (32, 32))
    # Portrait: the places come from the height's digits (1280 has four, 720 three).
    pan_case("pan-portrait-720x1280", seahorse, 10.5, -300.25, (720, 1280))
    # Recenter and zoom x4 in one step: offset at the old scale, places at the new zoom.
    pan_case("pan-and-zoom", seahorse, -100.5, 60.5, (640, 480), 14.60206)
    pan_case("pan-negative-zoom", Viewport("-0.5", "0.0", -1.5), 20.25, -8.0, (64, 48))
    # Rounding ties go away from zero: C + 0.25 = 0.0125 exactly at 3 places.
    pan_case("pan-tie-positive", Viewport("-0.2375", "0", 0.0), 0.0625, 0.0, (1, 1))
    pan_case("pan-tie-negative", Viewport("0.2375", "0", 0.0), -0.0625, 0.0, (1, 1))
    # A reference is carried over unchanged.
    pan_case(
        "pan-keeps-reference",
        seahorse.with_reference(
            "-0.743643887037146704752191506114774", "0.131825904205303970493132056385139"
        ),
        12.0,
        -3.0,
        (48, 48),
    )
    zoom_case("zoom-at-wheel-in", seahorse, 100.3, -50.2, (1920, 1080), 14.0375)
    zoom_case("zoom-at-pinch-out", seahorse, -255.5, 191.5, (512, 384), 13.2)
    zoom_case("zoom-at-vertical-anchor", seahorse, 0.0, 40.0, (512, 512), 20.0)
    zoom_case("zoom-at-deep", Viewport("-2", "1e-295", 280.0), 5.5, -2.25, (32, 32), 281.5)
    zoom_case("zoom-at-portrait-828x1792", seahorse, -200.25, 700.5, (828, 1792), 14.5)
    # Thirty decades in one step: fl(dx*ps0) - fl(dx*ps1) must be exact -- a difference
    # of doubles lands on the wrong grid point.
    zoom_case("zoom-at-big-jump", Viewport("-0.5", "0", 0.0), 100.0, -37.5, (512, 512), 30.0)
    # About the center: nothing moves, so the strings stay; only the zoom changes.
    zoom_case("zoom-at-about-center", seahorse, 0.0, 0.0, (512, 384), 16.0)
    zoom_case(
        "zoom-at-keeps-reference",
        seahorse.with_reference(
            "-0.743643887037146704752191506114774", "0.131825904205303970493132056385139"
        ),
        25.0,
        12.0,
        (48, 48),
        14.5,
    )
    delta_case("pixel-delta-pan", seahorse, pan(seahorse, 123.456, -78.9, (512, 384)), (512, 384))
    delta_case(
        "pixel-delta-equal-values",
        Viewport("0.1", "0", 3.0),
        Viewport("0.10", "0.0", 3.0),
        (64, 64),
    )
    delta_case(
        "pixel-delta-overflow",
        Viewport("0", "0", 280.0),
        Viewport("1e30", "-1e30", 280.0),
        (32, 32),
    )
    delta_case(
        "pixel-delta-other-zoom",
        seahorse,
        dataclasses.replace(pan(seahorse, 3.5, 4.5, (256, 256)), zoom_log10=20.0),
        (256, 256),
    )
    # T2 (0.10.0): past zoom 290 the offsets are pixels * ps rounded once to floatexp, the
    # render's own pixel deltas, and the strings print at the frame's places.
    deep = Viewport(P830_CENTER, "0", 996.5)
    pan_case("pan-t2-zoom996", deep, 7.25, -3.5, (64, 48), spec_version="0.10.0")
    pan_case("pan-t2-and-zoom", deep, -20.5, 11.0, (64, 48), 1200.25, spec_version="0.10.0")
    # Across the T1/T2 boundary: the old offset in doubles, the new one in floatexp.
    zoom_case(
        "zoom-at-t1-to-t2",
        Viewport("-2", "1e-295", 289.0),
        5.5,
        -2.25,
        (32, 32),
        291.5,
        spec_version="0.10.0",
    )
    zoom_case("zoom-at-t2-deep", deep, -13.0, 6.5, (64, 48), 4000.5, spec_version="0.10.0")
    delta_case(
        "pixel-delta-t2", deep, pan(deep, 123.25, -7.75, (64, 48)), (64, 48), spec_version="0.10.0"
    )
    positional_inputs = [
        "1e-5",
        "-1.2E-7",
        "2.5E1",
        "0.10",
        "-0.0",
        "007.50",
        ".5",
        "5.",
        "1.000e3",
        " +3.25e-2 ",
        "0e-10",
        "-123456789012345678901234567890.5e-40",
    ]
    write(
        "positional",
        {
            "operation": "positional",
            "inputs": positional_inputs,
            "expected": [decimal_text.positional(text) for text in positional_inputs],
        },
    )
    # Forty pans at zoom 40: every intermediate center pinned, and the orbit's working
    # bits never change (the places come from the frame, never from the center).
    vp = Viewport(
        "-0.743643887037158704752191506114774", "0.131825904205311970493132056385139", 40.0
    )
    steps: list[dict[str, Any]] = []
    expected: list[dict[str, Any]] = []
    for i in range(40):
        dx, dy = 3.25 - i * 0.375, -1.5 + i * 0.125
        vp = pan(vp, dx, dy, (1920, 1080))
        steps.append({"operation": "pan", "dx": dx, "dy": dy})
        expected.append(
            {**vp.to_dict(), "working_bits": working_bits(vp.center_re, vp.center_im, 40.0)}
        )
    write(
        "sequence-pans-zoom40",
        {
            "operation": "sequence",
            "size": [1920, 1080],
            "viewport": Viewport(
                "-0.743643887037158704752191506114774", "0.131825904205311970493132056385139", 40.0
            ).to_dict(),
            "steps": steps,
            "expected": expected,
        },
    )


# Heaton Fractal's hunt result for a period-998 nucleus (vectors/locations/hf-result).
NUCLEUS_P998 = (
    "-0.7436438870371588707780645434936425750476",
    "0.1318259042053122928210973548747672652630",
)
# Heaton Fractal's r7-a round-1 nucleus (period 6308, depth 106.17; hunts/r7-a.jsonl).
P6308_HF = (
    (
        "-0.74179270142920012328415486246133486822181337292254710214402418375004664084945569585"
        "246011078130725915411031437453364085735507047308210616986538010966660804513830391512170"
    ),
    (
        "0.123977941724695971711689620339223317838367247673535822857200096883849880494974599965"
        "16886304789610234791243018841746592856594306471080784322388395732723828262276304644199"
    ),
)


def write_nucleus_cases() -> None:
    """spec/nucleus.md (0.9.0): the box period, Newton's nucleus and a snap (the box, then
    Newton with its period and square), every field exact but the sizes (relative 1e-12)."""
    from heaton_life.fractal.nucleus import (
        MAX_ESCALATIONS,
        MAX_EVALUATIONS,
        MAX_STEPS,
        Nucleus,
        box_period,
        find_nucleus,
    )

    root = VECTOR_ROOT / "nucleus"

    def radius_bits(radius: float | None) -> str | None:
        return None if radius is None else _bits(radius)

    def nucleus_record(n: Nucleus) -> tuple[dict[str, Any], dict[str, Any] | None]:
        record = dataclasses.asdict(n)
        record["size_log10"] = _bits(n.size_log10)
        if not n.found:
            return record, None
        loc = n.location()
        assert loc.half_height_log10 is not None
        return record, {
            "half_height_log10": _bits(loc.half_height_log10),
            "max_iter": loc.max_iter,
        }

    def write(name: str, operation: str, inputs: dict[str, Any], expected: dict[str, Any]) -> None:
        meta = {
            "spec_version": "0.9.0",
            "family": "nucleus",
            "tier": "bit-exact",
            "relative_epsilon": 1e-12,
            "operation": operation,
            "input": inputs,
            "expected": expected,
        }
        case_dir = root / name
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "params.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
        print(f"wrote vectors/nucleus/{name}")

    def snap(
        name: str,
        center: tuple[str, str],
        zoom: float,
        max_period: int,
        radius: float | None = None,
        *,
        box_only: bool = False,
    ) -> None:
        box = box_period(center[0], center[1], zoom, max_period, radius)
        expected: dict[str, Any] = {
            "box": {
                "period": box.period,
                "reason": box.reason,
                "halvings": box.halvings,
                "radius": _bits(box.radius),
            }
        }
        inputs = {
            "center_re": center[0],
            "center_im": center[1],
            "zoom_log10": zoom,
            "radius": radius_bits(radius),
            "max_period": max_period,
        }
        if box_only:
            write(name, "box", inputs, expected)
            return
        expected["nucleus"] = expected["location"] = None
        if box.period is not None:
            n = find_nucleus(center[0], center[1], box.period, zoom, box.radius)
            expected["nucleus"], expected["location"] = nucleus_record(n)
        write(name, "snap", inputs, expected)

    def find(
        name: str,
        center: tuple[str, str],
        zoom: float,
        period: int,
        radius: float | None = None,
        max_steps: int = MAX_STEPS,
        max_evaluations: int = MAX_EVALUATIONS,
        max_escalations: int = MAX_ESCALATIONS,
    ) -> None:
        n = find_nucleus(
            center[0],
            center[1],
            period,
            zoom,
            radius,
            max_steps=max_steps,
            max_evaluations=max_evaluations,
            max_escalations=max_escalations,
        )
        record, location = nucleus_record(n)
        inputs = {
            "center_re": center[0],
            "center_im": center[1],
            "zoom_log10": zoom,
            "radius": radius_bits(radius),
            "period": period,
            "max_steps": max_steps,
            "max_evaluations": max_evaluations,
            "max_escalations": max_escalations,
        }
        write(name, "find", inputs, {"nucleus": record, "location": location})

    # Snaps. The textbook squares: a period-4 bulb's, and mandelbrot-numerics' period 48.
    snap("snap-p4", ("-0.158", "1.033"), 0.0, 100, 0.015)
    snap("snap-p48", ("-0.8691524744", "0.2556487868"), 0.0, 1000, 1.25e-5)
    # A frame's own square (half its width): the period-3 minibrot; the home view's p = 1.
    snap("snap-p3", ("-1.75", "0.001"), 1.0, 100)
    snap("snap-home-p1", ("-0.5", "0.0"), 0.0, 1000)
    # Shifted deep frames find the nucleus they were built around, printed at the view's
    # places when those are finer than the size's.
    snap("snap-p16-shifted", _shifted(NUCLEUS_P16, 25.0, 0.3, 0.1), 25.0, 1000)
    snap("snap-p24-shifted", _shifted(NUCLEUS_P24, 30.0, 0.04625, 0.0), 30.0, 1000)
    snap("snap-p1959", _shifted(NUCLEUS_P1959, 23.0, 0.2, 0.1), 23.0, 5000)
    # From the zoom-5 frame the box sees period 11, the square's lowest, and Newton finds
    # that nucleus.
    snap("snap-p24-zoom5", _shifted(NUCLEUS_P24, 5.0, 0.04625, 0.0), 5.0, 1000)
    # Halvings: the first square's corners escape just before the period.
    snap("snap-p998-halved", _shifted(NUCLEUS_P998, 8.5, 0.13, -0.21), 8.5, 5000)
    snap("snap-p1959-halved", _shifted(NUCLEUS_P1959, 22.0, 0.2, 0.1), 22.0, 5000)
    # A period whose nucleus Newton cannot reach from the center: the walk leaves the view.
    snap("snap-p1959-zoom21", NUCLEUS_P1959, 21.0, 5000)
    # The crossing rule's ties: a corner on the real axis (half-open), a corner at 0.
    snap("snap-tie-axis", ("-1.3", "0.015625"), 0.0, 500, 0.015625)
    snap("snap-tie-p18", ("-1.75", "0.00390625"), 0.0, 500, 2.0**-8)
    snap("snap-corner-at-origin", ("0.25", "0.25"), 0.0, 500, 0.25)
    # The surround and a corner's escape at the same n: the surround wins; the center's
    # own orbit then escapes before the period.
    snap("snap-surround-at-escape", ("0.1971666508", "-0.9661096566"), 1.0, 300)
    # Boxes with no period: every square escapes; the budget runs out; an interior square.
    snap("box-escaped", ("-1.8361778519", "-1.1683968203"), 2.0, 300, box_only=True)
    snap("box-escaped-exterior", ("1", "1"), 2.0, 1000, box_only=True)
    snap("box-budget", ("-0.8691524744", "0.2556487868"), 0.0, 40, 1.25e-5, box_only=True)
    snap("box-interior", ("-0.1", "0"), 3.0, 2000, box_only=True)
    # Finds. Newton on 24 from the zoom-5 frame lands on another period-24 nucleus.
    find("find-p24-zoom5", _shifted(NUCLEUS_P24, 5.0, 0.04625, 0.0), 5.0, 24)
    # Lower periods: 4 from beside the period-2 nucleus -1; 30 reaching a period-3 nucleus.
    find("find-lower-p2", ("-1.001", "0.0003"), 2.0, 4)
    find("find-lower-p3", ("-0.051864297299", "0.712433553581"), 1.0, 30)
    # Precision escalation: once (141 -> 149 bits), after a window reset (141 -> 184), and
    # from Heaton Fractal's p6308 cut to 60 places (264 -> 484), where the first F's
    # verdict would fail; with no escalation allowed.
    find("find-escalate-p53", ("-0.730396817344", "0.209723589240"), 2.0, 53)
    find("find-escalate-p379", ("-0.61692945555572", "0.44575892537665"), 2.0, 379)
    find("find-escalate-p6308", (P6308_HF[0][:63], P6308_HF[1][:62]), 20.0, 6308)
    find(
        "find-no-escalation", ("-0.61692945555572", "0.44575892537665"), 2.0, 379, max_escalations=0
    )
    # The other stops: zero derivative (c = -1/2 is z_2's critical point), an escaped
    # start, a walk out of the view, a walk that stagnates, and the two budgets.
    find("find-zero-derivative", ("-0.5", "0"), 1.0, 2)
    find("find-start-escaped", ("0.5", "0.5"), 0.0, 5)
    find("find-left-view", ("-0.869051116225", "0.143453726593"), 4.0, 30)
    find("find-stagnated", ("-1.260923117193", "0.051828001608"), 2.0, 28)
    find("find-max-evaluations", _shifted(NUCLEUS_P16, 3.0, 0.3, 0.1), 3.0, 16, max_evaluations=3)
    find("find-max-steps", _shifted(NUCLEUS_P16, 3.0, 0.3, 0.1), 3.0, 16, max_steps=2)

    # Cases that pin one rule each: a port that changes the rule named fails the case.
    # The box: its escape bound 2^(F+16) (not 15, not 17), per component (not |z|), and the
    # crossing test's strict > 0 (an edge through 0 does not cross).
    snap("box-escape-bound-not-15", ("-1.474862400191", "0.464302265200"), 1.0, 400, box_only=True)
    snap("box-escape-bound-not-17", ("-0.374787416731", "0.979283882032"), 1.0, 400, box_only=True)
    snap("box-escape-bound-halved", ("-1.835612984996", "0.441294964135"), 1.0, 300, box_only=True)
    snap("box-escape-per-component", ("0.463752545985", "0.384819085923"), 4.0, 400, box_only=True)
    snap("box-crossing-strict", ("0.25", "0"), 0.0, 10, 0.25, box_only=True)
    snap("snap-edge-through-origin", ("0.5", "0.5"), 0.0, 500, 0.5)
    # Evaluation: a component past 2 escapes (exactly 2 does not; |z| > 2 alone does not).
    find("find-escape-boundary", ("-2", "0"), 0.0, 3)
    find("find-escape-per-component", ("-0.319504188240", "0.663541825182"), 2.0, 13)
    # The line search: 25 halvings, failing far from a root (no-improvement), also on a
    # run's first pass with a cap of 1 (26 evaluations); strictly smaller only; two
    # roundings, clamp then halving; rshift's and rdiv's ties away from zero.
    find("find-no-improvement", ("-0.5", "0.00000001"), 0.0, 2)
    find("find-no-improvement-after-steps", ("-1.92595622146355", "0.00000000000020"), 1.0, 22)
    find(
        "find-no-improvement-cap-1",
        ("-1.91720887071420", "-0.00000000000047"),
        2.0,
        35,
        max_evaluations=1,
    )
    find("find-strictly-smaller", ("0.085874447262", "0.711017235052"), 0.0, 3)
    snap("snap-strictly-smaller", ("-0.755011260542", "0.418144241042"), 1.0, 400)
    find("find-rounded-twice", ("-0.552826135186", "0.584268606794"), 3.0, 23)
    # The clamp takes the least s with |step|^2 <= M^2 4^s: on period 1 the step is c
    # itself, so a start of 1/2 with a reach of 1/2 is the tie, taken whole.
    find("find-clamp-tie", ("0.5", "0"), 0.0, 1, 0.5)
    find("find-rshift-tie", ("-1.1503693135", "0.2135525983"), 4.0, 125)
    find("find-print-tie", ("0.5", "-0.001953125"), 0.0, 5)
    # The stagnation window: opens at step 1, 13, ...; the factor is 4.
    find("find-stagnated-factor", ("-0.6261115", "0.3935821"), 1.0, 56)
    find("find-stagnated-window-start", ("-1.0240235", "0.2517738"), 1.0, 56)
    find("find-not-stagnated", ("-0.517476061", "0.521148583"), 3.0, 153)
    # Escalation only after floor; each run with fresh budgets.
    find(
        "find-escalate-after-floor-only",
        ("0.349002577268", "0.431654293468"),
        0.0,
        22,
        max_evaluations=20,
    )
    find(
        "find-escalate-fresh-evaluations",
        ("-0.61692945555572", "0.44575892537665"),
        2.0,
        379,
        max_evaluations=99,
    )
    find(
        "find-escalate-fresh-steps",
        ("-0.61692945555572", "0.44575892537665"),
        2.0,
        379,
        max_steps=23,
    )
    # The verdict: the bar K exactly (neither K - 1 nor K + 1), and the precision gate: a
    # coarse F that does not place the atom is not converged (64 bits exactly).
    find("find-verdict-bar-k", ("-1.366370191192", "0.025274663134"), 1.0, 17, max_evaluations=20)
    find("find-verdict-not-k-minus-1", ("-1.579504579480", "0"), 2.0, 60, max_steps=5)
    find("find-verdict-not-k-plus-1", ("-1.899828024626", "0"), 3.0, 14, max_evaluations=6)
    find("find-coarse-precision", ("-2", "0"), 0.0, 42, max_escalations=0)
    find("find-coarse-precision-cut-short", ("-2", "0"), 0.0, 42, max_evaluations=6)
    find("find-resolve-not-56", ("-1.575722063958", "0"), 1.0, 65, max_escalations=0)
    find("find-resolve-not-72", ("-1.661640627101", "0.00000000000047"), 1.0, 55, max_escalations=0)
    # Printing: the view's places round the zoom up (ceil 0.5 = 1, ceil 5.5 = 6).
    find("find-view-places-failed", ("0.5", "0.5"), 0.5, 5)
    find("find-view-places-found", ("-1.75", "0.001"), 5.5, 3)


# Heaton Fractal's r7-a round-3 nucleus (period 135,310, atom depth 492.45;
# hunts/record-1e3800.jsonl line 4): at zoom 320 its frame needs T2 -- forcing T1's float64
# deltas there gets 40 of 60 stable pixels wrong (s7 fixtures, direct 1975-bit truth).
P135310_HF = (
    (
        "-0.741792701429200123284154862461334868221813372922547102144024183750046640849455695852"
        "4601107813072590503748891436212127479577047464648763773999979858719418329443348430068544"
        "9058507595536148294552732379756707780794222699765000849087600291978563682324493986718595"
        "0074262322834978538067718665583985329749868156199699220173492198401425704925527587600208"
        "6883505827441015045268093972948991086466072275902613945125569416888156206984766914435686"
        "1582557546076637830583086887713413883459538211440585525230757674650009424890308208066547"
        "43050976796919895706207901632403"
    ),
    (
        "0.1239779417246959717116896203392233178383672476735358228572000968838498804949745999651"
        "6886304789610236795892717050828606930965765482956408260227797393176255870494542347749814"
        "2851959359089382284463586348828584693644975471780448665825186148091004452908781981837840"
        "3581322809742899646252889654253178873102561988119958128682003235153307346440858028796081"
        "2841874729036553371370952360251901067221660828905627588552213162681623605300692082473681"
        "8462669846804509549922600511114219000705289709923573886959595161901670687125581755625183"
        "2292000295911024905860049683006"
    ),
)


# A period-830 real-axis nucleus near -2 (atom size 10^-997.65; Newton in 7560-bit gmpy2):
# every 830th reference sample passes near 2^-1790, so a T2 frame steps through floatexp
# there, and its pixels rebase there.
P830_CENTER = (
    "-1.9999999999999999999999999999999999999999999999999999999999999999999999999999999999999"
    "9999999999999999999999999999999999999999999999999999999999999999999999999999999999999999"
    "9999999999999999999999999999999999999999999999999999999999999999999999999999999999999999"
    "9999999999999999999999999999999999999999999999999999999999999999999999999999999999999999"
    "9999999999999999999999999999999999999999999999999999999999999999999999999999999999999999"
    "9999999999999999999999999999999999999999999999999999999999999711199326143338396279551682"
    "0158352667668421775474495910794967943422662000692646445990640234832212261092547632171691"
    "1321206646008861351575233246246034974193051472401988983501593597640242041012955178343453"
    "6108675383869370370816883089118385843279993102003044858160092623636776683936518329990836"
    "1962232240358567462087526404957637856826585234454529238776330196863889881090912330481327"
    "1126938382212835731785632066962134412208534377012860249416663023130075352372483535146902"
    "706382978665946410862147292130810713557667285759648870726772730621622048"
)
# The golden ratio (the basilica's beta fixed point), 400 places.
GOLDEN_RATIO = (
    "1.61803398874989484820458683436563811772030917980576286213544862270526046281890244970720"
    "7204189391137484754088075386891752126633862223536931793180060766726354433389086595939582"
    "9056383226613199282902678806752087668925017116962070322210432162695486262963136144381497"
    "5870122034080588795445474924618569536486444924104432077134494704956584678850987433944221"
    "2544877066478091588460749988712400765217057517978"
)
# Julia c = i: sqrt(-i) (a preimage of 0) plus 3e-322, 405 places.
JULIA_I_PREIMAGE = (
    (
        "0.7071067811865475244008443621048490392848359376884740365883398689953662392310535194"
        "251937671638207863675069231154561485124624180279253686063220607485499679157066113329"
        "637527963778999752505763910302857350547799858029851372672984310073642587093204445993"
        "047761646152421543571607254198813018139976257039948436266982731659044151203103076291"
        "7619752737287514387998086491778761016876592850567718730170424942358019"
    ),
    (
        "-0.707106781186547524400844362104849039284835937688474036588339868995366239231053519"
        "425193767163820786367506923115456148512462418027925368606322060748549967915706611332"
        "963752796377899975250576391030285735054779985802985137267298431007364258709320444599"
        "304776164615242154357160725419881301813997625703994843626698273165904414820310307629"
        "17619752737287514387998086491778761016876592850567718730170424942358019"
    ),
)


def write_floatexp_cases() -> None:
    """spec/floatexp.md (0.10.0): each operation at its boundaries; values as [mantissa
    bits, exponent], doubles as bits, fixed-point integers as decimal strings."""
    from heaton_life.core import floatexp as fx

    def x(value: tuple[float, int]) -> list[Any]:
        return [_bits(value[0]), int(value[1])]

    cases: list[dict[str, Any]] = []

    def add(a: tuple[float, int], b: tuple[float, int], note: str) -> None:
        cases.append({"op": "add", "a": x(a), "b": x(b), "expected": x(fx.add(a, b)), "note": note})

    def mul(a: tuple[float, int], b: tuple[float, int], note: str) -> None:
        cases.append({"op": "mul", "a": x(a), "b": x(b), "expected": x(fx.mul(a, b)), "note": note})

    def to_double(a: tuple[float, int], note: str) -> None:
        cases.append(
            {"op": "to_double", "a": x(a), "expected": _bits(fx.to_double(a)), "note": note}
        )

    def from_fixed(value: int, bits: int, note: str) -> None:
        cases.append(
            {
                "op": "from_fixed",
                "value": str(value),
                "bits": bits,
                "expected": x(fx.from_fixed(value, bits)),
                "note": note,
            }
        )

    def normalize(value: float, exponent: int, note: str) -> None:
        cases.append(
            {
                "op": "normalize",
                "value": _bits(value),
                "exponent": exponent,
                "expected": x(fx.normalize(value, exponent)),
                "note": note,
            }
        )

    division: list[dict[str, Any]] = []  # its own case: operations was shipped without it

    def div(a: tuple[float, int], b: tuple[float, int], note: str) -> None:
        division.append(
            {"op": "div", "a": x(a), "b": x(b), "expected": x(fx.div(a, b)), "note": note}
        )

    def compare(a: tuple[float, int], b: tuple[float, int], note: str) -> None:
        cases.append(
            {"op": "compare", "a": x(a), "b": x(b), "expected": fx.compare(a, b), "note": note}
        )

    one = (1.0, 0)
    add(one, (1.0, -63), "gap 63: below half an ulp, rounds to a")
    add(one, (1.0, -64), "gap 64: still aligned exactly, rounds to a")
    add(one, (1.0, -65), "gap 65: a, by the drop rule")
    add(one, (1.0, -53), "exactly half an ulp: ties to even, down")
    add((1.0000000000000002, 0), (1.0, -53), "exactly half an ulp: ties to even, up")
    add(one, (1.5, -53), "just over half an ulp: up")
    add((1.5, 3), (-1.5, 3), "cancellation to zero")
    add(one, (-1.9999999999999998, -1), "cancellation to 2^-53")
    add((1.75, -1000), (1.25, -1001), "a carry into the next binade")
    add((-1.5, 7), (1.5, 5), "mixed signs, renormalized down")
    add(fx.ZERO, (1.25, -5000), "zero plus b is b")
    mul((1.5, 1), (1.5, 1), "exact: 2.25 * 4 = 9")
    mul((1.0000000000000002, -3000), (1.9999999999999998, -4000), "one rounding")
    mul((1.0, -(2**30)), (1.0, -(2**30)), "exponent exactly -2^31: kept")
    mul((1.0, -(2**30)), (1.0, -(2**30) - 1), "below -2^31: zero (the floor)")
    mul((-1.25, 12), fx.ZERO, "times zero")
    to_double((1.0, -1022), "the smallest normal")
    to_double((1.5, -1023), "a subnormal, exact")
    to_double((1.0, -1074), "the smallest subnormal")
    to_double((1.0, -1075), "half the smallest subnormal: ties to even, zero")
    to_double((1.5, -1075), "over half: the smallest subnormal")
    to_double((-1.9999999999999998, -1060), "a subnormal, rounded once")
    to_double((1.0, -2044), "the two-step path's floor: zero")
    to_double((-1.0, -2045), "below it: a signed zero")
    to_double((1.9999999999999998, 1023), "the largest finite")
    to_double((1.0, 1024), "past the top: infinity")
    from_fixed((1 << 60) + 3, 7, "rounded to 53 bits")
    from_fixed((1 << 54) - 1, 0, "rounding carries into a new binade")
    from_fixed(-((1 << 53) + 1), 100, "a tie, to even (down), negative")
    from_fixed((1 << 53) + 3, 100, "a tie, to even (up)")
    from_fixed(3 << 1500, 1024, "far past the double range")
    from_fixed(1, 3000, "far below it")
    normalize(5e-324, 0, "the smallest subnormal, exact")
    normalize(-3.0, -(2**31) + 1, "exponent -2^31 + 2: kept")
    normalize(1.5, -(2**31) - 1, "below the floor: zero")
    compare((1.5, 3), (1.25, 3), "same exponent: by mantissa")
    compare((1.0, 11), (1.9999999999999998, 10), "the exponent first")
    compare((-1.0, 11), (-1.9999999999999998, 10), "negatives: the order reversed")
    compare((-1.0, 900), (1.0, -900), "the sign first")
    compare((1.0, -5000), fx.ZERO, "positive over zero")
    compare((-1.0, 5000), fx.ZERO, "negative under zero")
    compare(fx.ZERO, fx.ZERO, "zero equals zero")
    compare((-1.75, 10), (-1.75, 10), "equal values")
    div(one, (1.5, 0), "2/3: one rounding, renormalized up a binade")
    div((1.5, 3000), (1.25, -3000), "exponents subtract: no range limit")
    div((-1.9999999999999998, -5), (1.0000000000000002, 7), "mixed signs")
    div((1.25, 0), (1.25, 9), "an exact quotient")
    div(fx.ZERO, (1.5, -9000), "zero over b is zero")

    for name, ops in (("operations", cases), ("division", division)):
        case_dir = VECTOR_ROOT / "floatexp" / name
        case_dir.mkdir(parents=True, exist_ok=True)
        meta = {"spec_version": "0.10.0", "family": "floatexp", "tier": "bit-exact", "cases": ops}
        (case_dir / "params.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
        print(f"wrote vectors/floatexp/{name}")


def write_t2_bla_cases() -> None:
    """BLA at T2 (spec/deep-zoom.md "BLA at T2", 0.10.0): Mandelbrot(bla=True) past zoom
    290. Each frame was added for a rule a port could get wrong and was checked to fail
    under a one-rule change of the reference; the table itself on four frames, every
    frame's dc bound exponent. The table rules no natural frame reaches (the dc term, each
    dead-rule cap, radii below the double range, the merge's branch order) are pinned by
    the crafted t2-steps/bla-* cases."""

    def bla(name: str, viewport: Viewport, size: tuple[int, int], max_iter: int, **kw: Any) -> None:
        write_fractal_case(
            "mandelbrot",
            name,
            Mandelbrot(max_iter=max_iter, escape_radius=1000.0, bla=True),
            {"max_iter": max_iter, "escape_radius": 1000.0, "bla": True},
            viewport,
            size,
            spec_version="0.10.0",
            small_orbits=True,
            bla=True,
            **kw,
        )

    offaxis = Viewport(P830_CENTER, "3e-997", 996.5)
    # The p830 minibrot at 1e996.5, off its axis: skips of hundreds of steps between the small
    # returns every 830 (one small sample is normal as a float64: its spans are dead), and
    # the distance estimate carried through each skip.
    bla("t2-bla-p830-offaxis-zoom996-16", offaxis, (16, 16), 11620, distance=True, bla_table_x=True)
    # One column (every dc.re is 0) stopped at 1000 iterations: skips near the end must fit;
    # at 997 a cap one too loose takes a skip too many.
    bla("t2-bla-p830-cap1000-1x16", offaxis, (1, 16), 1000)
    bla("t2-bla-p830-cap997-1x16", offaxis, (1, 16), 997)
    # Just past T1, 9x9: the reference escapes at 504 = 63 * 8, so the center pixel (delta
    # and dc both 0) skips onto the escape; the zero column and row skip with a zero part.
    bla(
        "t2-bla-p830-escape-zoom300-9",
        Viewport(P830_CENTER, "3e-301", 300.0),
        (9, 9),
        11620,
        bla_table_x=True,
    )
    # The same place with a reference that escapes at 503 = 7 mod 8: the table stops at k*,
    # not at the orbit's end (507), or the center pixel skips over the escape.
    bla(
        "t2-bla-p830-escape7-zoom300-9",
        Viewport(P830_CENTER, "1e-300", 300.0),
        (9, 9),
        11620,
        bla_table_x=True,
    )
    # A reference that shrinks toward 0: A underflows to 0 on the spans that start there.
    bla("t2-bla-a0-zoom300-4", Viewport("1e-90", "0", 300.5), (4, 4), 250, bla_table_x=True)
    # A center 1e-812 from the p830 nucleus: Z_830 is small and subnormal as a float64.
    bla(
        "t2-bla-p830-subnormal-zoom835-8",
        Viewport(_decimal_sum(P830_CENTER, "1e-812"), "0", 835.0),
        (8, 8),
        6000,
    )
    # The needle's tip at 1e1000: spans whose |A|, |B| pass 2^960 are dead.
    bla("t2-bla-tip-zoom1000-8", Viewport(_decimal_sum("-2", "1e-600"), "0", 1000.0), (8, 8), 6000)
    # A 1x1 frame on the nucleus: every delta is 0, so there is no dc bound at all.
    bla("t2-bla-p830-1x1", Viewport(P830_CENTER, "0", 996.5), (1, 1), 11620)
    # An off-center reference whose offset lifts the bound an octave (2^-3307, not 2^-3308).
    bla(
        "t2-bla-offref-p830-zoom996-8",
        Viewport(
            _decimal_sum(P830_CENTER, "6e-997"),
            "-6e-997",
            996.5,
            reference_re=P830_CENTER,
            reference_im="0",
        ),
        (8, 8),
        11620,
    )
    # Heaton Fractal's p135310 nucleus at 1e320: 200,000 iterations, fifteen levels; and the
    # same frame about a truncated center, whose complex reference pins each skip's order of
    # operations (the frames above are near the real axis).
    bla("t2-bla-hf-p135310-zoom320-8", Viewport(*P135310_HF, 320.0), (8, 8), 200000)
    bla(
        "t2-bla-hf-p135310-complex-zoom320-8",
        Viewport(P135310_HF[0][:333], P135310_HF[1][:332], 320.0),
        (8, 8),
        200000,
    )


def write_t2_step_cases() -> None:
    """T2's rare branches on crafted orbits and pixels (spec/deep-zoom.md "T2", 0.10.0):
    the internal loop (perturbation_t2.perturb_t2 / PerturbationT2.Perturb) run on a
    stated orbit and small table, every output bit for bit -- the paths no natural frame
    reaches (the 960-binade gap guards, a sample past 2^900)."""
    from heaton_life.core import floatexp as fx
    from heaton_life.core.bignum import OrbitX, SmallSamples
    from heaton_life.fractal.bla import build_table_t2, table_words_x
    from heaton_life.fractal.perturbation_t2 import XPair, perturb_t2

    def x(value: tuple[float, int]) -> list[Any]:
        return [_bits(value[0]), int(value[1])]

    def orbit(
        samples: list[complex], small: list[tuple[int, tuple[float, int], tuple[float, int]]]
    ) -> OrbitX:
        return OrbitX(
            np.array(samples, dtype=np.complex128),
            SmallSamples(
                np.array([row[0] for row in small], dtype=np.int64),
                np.array([row[1][0] for row in small], dtype=np.float64),
                np.array([row[1][1] for row in small], dtype=np.int64),
                np.array([row[2][0] for row in small], dtype=np.float64),
                np.array([row[2][1] for row in small], dtype=np.int64),
            ),
        )

    def orbit_json(o: OrbitX) -> dict[str, Any]:
        return {
            "samples": [[_bits(z.real), _bits(z.imag)] for z in o.samples],
            "small": [
                [int(i), _bits(float(rm)), int(re), _bits(float(im)), int(ie)]
                for i, rm, re, im, ie in zip(
                    o.small.index,
                    o.small.re_m,
                    o.small.re_e,
                    o.small.im_m,
                    o.small.im_e,
                    strict=True,
                )
            ],
        }

    def pair(p: tuple[tuple[float, int], tuple[float, int]] | None) -> XPair | None:
        if p is None:
            return None
        return XPair(
            np.array([p[0][0]]),
            np.array([p[0][1]], dtype=np.int64),
            np.array([p[1][0]]),
            np.array([p[1][1]], dtype=np.int64),
        )

    def case(
        name: str,
        ref: OrbitX,
        rebase: OrbitX | None,
        delta0: tuple[tuple[float, int], tuple[float, int]] | None,
        delta_c: tuple[tuple[float, int], tuple[float, int]] | None,
        max_iter: int,
        radius: float,
        derivative: tuple[tuple[tuple[float, int], tuple[float, int]], tuple[float, int] | None]
        | None = None,
        expect_paths: tuple[str, ...] = (),
        bla_dc: int | None | bool = False,  # False: no table; else the dc bound exponent
    ) -> None:
        stats: dict[str, int] = {}
        der = None if derivative is None else (pair(derivative[0]), derivative[1])
        table = None
        if bla_dc is not False:
            samples = ref.samples[: max_iter + 1]
            small = np.zeros(samples.size, dtype=bool)
            small[ref.small.index[ref.small.index < samples.size]] = True
            table = build_table_t2(samples, small, radius, None if bla_dc is None else int(bla_dc))
        result = perturb_t2(
            ref,
            pair(delta0),
            pair(delta_c),
            max_iter,
            radius,
            rebase_orbit=rebase,
            derivative=der,
            stats=stats,  # type: ignore[arg-type]
            table=table,
        )
        for path in expect_paths:
            assert stats.get(path, 0) > 0, f"t2-steps/{name}: {path} never ran"
        meta = {
            "spec_version": "0.10.0",
            "family": "t2-steps",
            "tier": "bit-exact",
            "orbit": orbit_json(ref),
            "rebase_orbit": None if rebase is None else orbit_json(rebase),
            "delta0": None if delta0 is None else [x(delta0[0]), x(delta0[1])],
            "delta_c": None if delta_c is None else [x(delta_c[0]), x(delta_c[1])],
            "derivative": None
            if derivative is None
            else {
                "d0": [x(derivative[0][0]), x(derivative[0][1])],
                "add": None if derivative[1] is None else x(derivative[1]),
            },
            "max_iter": max_iter,
            "escape_radius": radius,
            "paths": list(expect_paths),
            "expected": {
                "count": int(result.counts[0]),
                "final": [_bits(float(result.final[0].real)), _bits(float(result.final[0].imag))],
                "derivative": [
                    _bits(float(result.dr[0])),
                    _bits(float(result.di[0])),
                    int(result.d_exponent[0]),
                ],
            },
        }
        if table is not None:
            # BLA at T2: the table (T1's layout plus the radii's exponents) and the skips.
            meta["bla"] = {"dc_exponent": None if bla_dc is None else int(bla_dc)}
            meta["expected"]["applications"] = int(result.applications[0])
            words = table_words_x(table)  # every NaN written as the one canonical quiet NaN
            meta["expected"]["table"] = [
                _bits(float(w)) for w in np.where(np.isnan(words), np.nan, words)
            ]
        case_dir = VECTOR_ROOT / "t2-steps" / name
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "params.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
        print(f"wrote vectors/t2-steps/{name}")

    zero = (0.0, 0)

    def fx_double(value: tuple[float, int]) -> float:
        return fx.to_double(value)

    # Samples near 2^40 under an escape radius of 2^60: a delta grows ~41 binades a step,
    # so a pixel started thousands of binades down escapes within a few dozen iterations
    # and its final z and derivative carry every step's bits. The rebase orbit starts at an
    # exact zero (a small index, as Mandelbrot's does).
    grow = [
        complex(3, 4) * 2.0**38,
        complex(-5, 12) * 2.0**36,
        complex(8, -15) * 2.0**36,
        complex(-7, -24) * 2.0**35,
        complex(20, 21) * 2.0**35,
    ] * 8
    ref = orbit(grow, [])
    rebase = orbit([0j, *grow], [(0, zero, zero)])
    radius = 2.0**60
    # A delta 2000 binades below its delta_c: a fast step would need delta_c / 2^E ~ 2^2000,
    # so the step runs in floatexp (the guard against dcS overflowing).
    case(
        "delta-gap",
        ref,
        rebase,
        ((1.0, -3000), (1.5, -3001)),
        ((1.0, -1000), (1.25, -1000)),
        60,
        radius,
        expect_paths=("slow_gap",),
    )
    # A derivative 3000 binades below the ps it adds: its update runs in floatexp.
    case(
        "derivative-gap",
        ref,
        rebase,
        ((1.0, -800), (-1.75, -801)),
        None,
        60,
        radius,
        derivative=(((1.0, -4000), zero), (1.0, -1000)),
        expect_paths=("d_slow_gap",),
    )
    # A sample past 2^900 (a huge Julia center) goes through the table like a small one:
    # the step, the derivative update, and the escape test there run in floatexp, which
    # cannot overflow. The huge sample at index 0 multiplies the delta up from 2^-1000.
    huge = orbit(
        [0j, *grow],
        [(0, (1.5, 950), (1.25, 949))],
    )
    case(
        "huge-sample",
        huge,
        rebase,
        ((1.0, -1000), (1.0, -1001)),
        None,
        60,
        radius,
        derivative=(((1.0, -1000), zero), (1.0, -1000)),
        expect_paths=("slow_small", "d_slow_small"),
    )
    # The final z is to_double of each component: a landing on a huge sample escapes with
    # an infinite part beside a part that underflows to -0.0, and both keep their bits.
    for name, re_x, im_x in (
        ("final-inf-imaginary", (-1.0, -2000), (1.25, 1100)),
        ("final-inf-real", (1.5, 1100), (-1.0, -2000)),
    ):
        landing = orbit(
            [complex(0.5, 0.5), complex(fx_double(re_x), fx_double(im_x))],
            [(1, re_x, im_x)],
        )
        case(
            name,
            landing,
            rebase,
            ((1.0, -3000), (1.0, -3001)),  # below the tiny part, which underflows to -0.0
            None,
            5,
            radius,
            derivative=(((1.0, -1000), zero), None),
            expect_paths=("escape_small",),
        )

    # BLA at T2 on crafted tables (spec/deep-zoom.md "BLA at T2"). Samples of 0.5 make every
    # A = 1 and B = the step count, so with dc bound 2^-60 the level radii are exactly 57,
    # 49, 33 and 1 (x 2^-60), then 0. A pixel starting at |delta| = 57 x 2^-60, level 0's
    # radius itself, must take no skip: the radius test is strict.
    tie = orbit([complex(0.5, 0.0)] * 128 + [complex(1e10, 0.0)], [])
    case(
        "bla-radius-tie",
        tie,
        None,
        ((1.78125, -55), zero),  # 57 x 2^-60
        ((1.0, -2000), zero),
        200,
        1000.0,
        bla_dc=-60,
    )
    # A complex orbit turning at |Z| = 0.6: skips with complex A and B, the distance
    # derivative through each (started at a nonzero d), then the 2^40 samples to an escape.
    # Every regrouping of a skip's delta' or d' sums changes the final z or (dw, dE) here.
    turning = [  # |Z| = 0.6 as decimal literals (no libm), around the circle
        complex(0.36, 0.48),
        complex(-0.48, 0.36),
        complex(0.6, 0.0),
        complex(-0.36, -0.48),
        complex(0.0, 0.6),
        complex(0.48, -0.36),
        complex(-0.6, 0.0),
        complex(0.0, -0.6),
    ] * 12
    case(
        "bla-complex-skip",
        orbit(turning + grow, []),
        None,
        None,
        ((1.25, -3000), (-1.5, -3001)),
        400,
        radius,
        derivative=(((1.5, -3000), (-1.25, -3001)), (1.5, -3000)),
        expect_paths=("bla_skip",),
        bla_dc=-2999,
    )
    # Each case below was checked to fail under a one-rule change of the reference.
    tiny = (1.0, -3000)
    # Radii below the double range: a span after 64 steps of |2Z| = 2^14 has radius near
    # eps 2^-399 / 2^927; float64 radii, or |delta| rounded to a double, take other skips.
    case(
        "bla-deep-radius",
        orbit(
            [2.0**13 + 0j] * 64
            + [1.0 + 0j] * 31
            + [2.0**-399 + 0j]
            + [1.0 + 0j] * 32
            + [1e30 + 0j],
            [],
        ),
        None,
        ((1.0, -1200), zero),
        (tiny, zero),
        200,
        radius,
        bla_dc=-3000,
    )
    # A small index (an exact 0) where |A_x| = 0 meets num <= 0: the merge tests num > 0
    # before |A_x| = 0, so no span crosses the small index.
    case(
        "bla-branch-order",
        orbit(
            [2.0**-300 + 0j] * 8 + [0j] + [2.0**-300 + 0j] * 7 + [1.0 + 0j] * 16 + [1e30 + 0j],
            [(8, zero, zero)],
        ),
        None,
        (tiny, zero),
        (tiny, zero),
        200,
        1000.0,
        bla_dc=None,
    )
    # The dead rule entry by entry: |A| exactly 2^960 (dead), |A| = 2^968 alone past the cap,
    # |A| = 2^952 (live), and |B| near 2^987 alone past it.
    case(
        "bla-dead-rules",
        orbit(
            [2.0**119 + 0j] * 8
            + [2.0**120 + 0j] * 8
            + [2.0**118 + 0j] * 8
            + [2.0**-399 + 0j]
            + [2.0**140 + 0j] * 7
            + [2.0**300 + 0j],
            [],
        ),
        None,
        (tiny, zero),
        (tiny, zero),
        100,
        2.0**200,
        bla_dc=None,
    )
    # A parent reads its children's radii after the dead rule.
    case(
        "bla-dead-before-merge",
        orbit([1.1 * 2.0**14 + 0j] * 64 + [2.0**-10 + 0j] * 64 + [1e30 + 0j], []),
        None,
        (tiny, zero),
        (tiny, zero),
        200,
        radius,
        bla_dc=-3000,
    )
    # The dc term is |B_x| 2^k with B_x the left child's: siblings here differ.
    case(
        "bla-dc-left-child",
        orbit(([0.5 + 0j] * 8 + [0.25 + 0j] * 8) * 8 + [1e10 + 0j], []),
        None,
        (tiny, zero),
        ((1.0, -2000), zero),
        200,
        1000.0,
        bla_dc=-60,
    )
    # A pixel that would escape at max_iter + 1 counts -1, with and without a table.
    ends = orbit([0.5 + 0j] * 128 + [1e30 + 0j], [])
    case("loop-end", ends, None, (tiny, zero), (tiny, zero), 127, 1000.0)
    case("bla-loop-end", ends, None, (tiny, zero), (tiny, zero), 127, 1000.0, bla_dc=-3000)
    # A skip from a gap-guard state (delta 2000 binades below delta_c, parts 2000 apart):
    # in floatexp, then (w, E) split afresh from delta'.
    case(
        "bla-dc-bad",
        orbit([4.0 + 0j] * 1100, []),
        None,
        ((1.0, -5000), zero),
        ((1.0, -5000), tiny),
        1060,
        1000.0,
        bla_dc=-3000,
    )


def write_t2_cases() -> None:
    """T2 (spec/deep-zoom.md "T2", 0.10.0): counts, statuses and distances past zoom 290,
    with the orbits' lengths and small samples pinned."""

    def mandelbrot(
        name: str, viewport: Viewport, size: tuple[int, int], max_iter: int, **kw: Any
    ) -> None:
        write_fractal_case(
            "mandelbrot",
            name,
            Mandelbrot(max_iter=max_iter, escape_radius=1000.0),
            {"max_iter": max_iter, "escape_radius": 1000.0},
            viewport,
            size,
            spec_version="0.10.0",
            small_orbits=True,
            **kw,
        )

    def julia(
        name: str, c: complex, viewport: Viewport, size: tuple[int, int], max_iter: int, **kw: Any
    ) -> None:
        write_fractal_case(
            "julia",
            name,
            Julia(c=c, max_iter=max_iter, escape_radius=1000.0),
            {"c_re": c.real, "c_im": c.imag, "max_iter": max_iter, "escape_radius": 1000.0},
            viewport,
            size,
            spec_version="0.10.0",
            small_orbits=True,
            **kw,
        )

    # HF's p135310 nucleus at zoom 320, where T1's float64 deltas fail.
    mandelbrot("t2-hf-p135310-zoom320-8", Viewport(*P135310_HF, 320.0), (8, 8), 200000, status=True)
    # A period-830 nucleus near -2 at zoom 996.5: floatexp steps and tests every 830
    # iterations, rebases there; on the axis, off it, and with the distance estimate.
    mandelbrot("t2-p830-zoom996-16", Viewport(P830_CENTER, "0", 996.5), (16, 16), 11620)
    mandelbrot(
        "t2-p830-offaxis-zoom996-16",
        Viewport(P830_CENTER, "3e-997", 996.5),
        (16, 16),
        11620,
        distance=True,
    )
    # An off-center reference at T2: the p830 nucleus iterates, the center sits a few
    # pixels away (the exact decimal difference, rounded once to floatexp).
    mandelbrot(
        "t2-offref-p830-zoom996-8",
        Viewport(
            _decimal_sum(P830_CENTER, "1.12e-997"),
            "-7.1e-998",
            996.5,
            reference_re=P830_CENTER,
            reference_im="0",
        ),
        (8, 8),
        11620,
    )
    # Julia c = i near a preimage of 0 (sqrt(-i) + 3e-322): the reference passes 1e-321
    # of 0 at index 1, the pixels' deltas square to 1e-642 and rebase onto the critical
    # orbit there -- T1's Julia limit, which T2 lifts.
    julia(
        "t2-julia-i-preimage-zoom320-16",
        1j,
        Viewport(*JULIA_I_PREIMAGE, 320.0),
        (16, 16),
        4000,
        distance=True,
    )
    # The basilica (c = -1), whose critical orbit is exactly 0 at every other index: inside,
    # a delta squares past 2^-(2^31) and meets the floor (every pixel interior, as direct
    # iteration says); on its boundary at the golden ratio (its beta fixed point), pixels
    # escape while landing on those exact zeros.
    julia(
        "t2-julia-basilica-interior-zoom300-4", -1 + 0j, Viewport("0.1", "0", 300.0), (4, 4), 3000
    )
    julia(
        "t2-julia-basilica-phi-zoom320-16",
        -1 + 0j,
        Viewport(GOLDEN_RATIO, "0", 320.0),
        (16, 16),
        3000,
        distance=True,
    )
    # Julia c = i at zoom 400, 2.3 and -1.7 pixels off a preimage of 0: pixel differences
    # square to ~ps^2 there, so the orbits run at twice the frame's precision (at the
    # frame's own precision 45 of these 144 counts come out wrong); and a frame centered at
    # 0 itself, with the distance estimate starting from a small index 0.
    julia(
        "t2-julia-i-precision-zoom400-12", 1j, Viewport(*_julia_i_offset(400.0, 12)), (12, 12), 5000
    )
    # The same rule at T1 (0.10.0 moved T1 Julia orbits to twice the zoom as well): at
    # zoom 100 the frame's own precision gets 51 of these 144 counts wrong. The orbits
    # ship with the case, as every T1 case's do.
    write_fractal_case(
        "julia",
        "t1-julia-i-precision-zoom100-12",
        Julia(c=1j, max_iter=5000, escape_radius=1000.0),
        {"c_re": 0.0, "c_im": 1.0, "max_iter": 5000, "escape_radius": 1000.0},
        Viewport(*_julia_i_offset(100.0, 12)),
        (12, 12),
        orbit_kind="julia",
        spec_version="0.10.0",
    )
    julia(
        "t2-julia-i-center0-zoom400-12",
        1j,
        Viewport("0", "0", 400.0),
        (12, 12),
        5000,
        distance=True,
    )
    # An odd frame: its center column's delta has a zero real part, which must not force
    # the slow step (only nonzero components meet the 960-binade gap rule).
    mandelbrot("t2-p830-offaxis-zoom996-9", Viewport(P830_CENTER, "3e-997", 996.5), (9, 9), 11620)


def _julia_i_offset(zoom: float, width: int) -> tuple[str, str, float]:
    """sqrt(-i) moved (2.3, -1.7) pixels of a ``width``-wide frame at ``zoom``, to zoom + 60
    places (decimal arithmetic, correctly rounded, the same everywhere)."""
    import decimal

    with decimal.localcontext() as ctx:
        ctx.prec = int(zoom) + 200
        half = decimal.Decimal(2).sqrt() / 2
        ps = decimal.Decimal(4) / width * decimal.Decimal(10) ** decimal.Decimal(repr(-zoom))
        re_text = str(half + decimal.Decimal("2.3") * ps)
        im_text = str(-half - decimal.Decimal("1.7") * ps)
    places = int(zoom) + 60
    return (
        re_text[: re_text.index(".") + 1 + places],
        im_text[: im_text.index(".") + 1 + places],
        zoom,
    )


def _decimal_sum(a: str, b: str) -> str:
    import decimal

    with decimal.localcontext() as ctx:
        ctx.prec = 2000
        return str(decimal.Decimal(a) + decimal.Decimal(b))


def write_location_cases() -> None:
    """spec/locations.md: one input file per case beside params.json, which holds the
    expected record (centers, budgets, references, formats and warnings exact;
    half_height_log10 within the relative epsilon) and the viewports of three frames --
    or ``"error": true`` for a file the importer must refuse."""
    from heaton_life.fractal import locations

    root = VECTOR_ROOT / "locations"
    parsers = {
        "kfr": locations.parse_kfr,
        "f3": locations.parse_fraktaler3,
        "hf-preset": locations.parse_hf_preset,
        "hf-result": locations.parse_hf_result,
        "hf-journal": locations.parse_hf_journal,
    }
    frames = [(512, 512), (1920, 1080), (1080, 1920)]

    def write(name: str, fmt: str, filename: str, text: str) -> None:
        case_dir = root / name
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / filename).write_bytes(text.encode("utf-8"))
        meta: dict[str, Any] = {
            "spec_version": "0.5.0",
            "family": "locations",
            "tier": "epsilon",
            "epsilon": 1e-12,
            "format": fmt,
            "input": filename,
        }
        try:
            loc = parsers[fmt](text)
        except ValueError:
            meta["error"] = True
        else:
            meta["expected"] = {
                "center_re": loc.center_re,
                "center_im": loc.center_im,
                "half_height_log10": loc.half_height_log10,
                "format": loc.format,
                "max_iter": loc.max_iter,
                "reference": list(loc.reference) if loc.reference else None,
                "warnings": list(loc.warnings),
            }
            meta["viewports"] = (
                []
                if loc.half_height_log10 is None
                else [
                    {"size": list(size), "zoom_log10": loc.viewport(size).zoom_log10}
                    for size in frames
                ]
            )
        (case_dir / "params.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
        print(f"wrote vectors/locations/{name}")

    crlf = "\r\n"
    write(
        "kfr-as-kf-writes",
        "kfr",
        "input.kfr",
        crlf.join(
            [
                "Re: -0.743643887037158704752191506114774",
                "Im: 0.131825904205311970493132056385139",
                "Zoom: 1.59738E15",
                "Iterations: 23832",
                "IterDiv: 0.010000",
                "SmoothMethod: 0",
                "ColorMethod: 7",
                "Differences: 3",
                "ColorOffset: 0",
                "RotateAngle: 0",
                "StretchAngle: 0",
                "StretchAmount: 0",
                "ImagPointsUp: 1",
                "Version: 2.15.5.2",
                "",
            ]
        ),
    )
    # A byte-order mark before the first key; '=' as well as ':'; a later duplicate
    # wins; no ImagPointsUp, so KF's axis points down and the view is mirrored here.
    write(
        "kfr-hand-edited",
        "kfr",
        "input.kfr",
        "﻿Re: -0.9\n; a hand-edited location\n# another comment\n\n"
        "  IM:  2.0E-2   \nre = -7.5e-1\nzoom: 2.5e6\niterations: 1e6\n"
        "Rotate: 0\nRatio: 360.0\nno separator here\n",
    )
    write(
        "kfr-transforms",
        "kfr",
        "input.kfr",
        "Re: -1.256640726\nIm: 0.382386261\nZoom: 2.5e6\nRotateAngle: 30\n"
        "StretchAmount: 0.5\nImagPointsUp: 0\n",
    )
    write(
        "kfr-legacy-rotate",
        "kfr",
        "input.kfr",
        "Re: 0.25\nIm: 0\nZoom: 100\nRotate: 12.5\nRatio: 360\nImagPointsUp: 1\n",
    )
    write(
        "kfr-legacy-ratio",
        "kfr",
        "input.kfr",
        "Re: 0.25\nIm: 0\nZoom: 100\nRotate: 0\nRatio: 177\nImagPointsUp: 1\n",
    )
    write("kfr-no-zoom", "kfr", "input.kfr", "Re: 0.25\rIm: -0.5\r")
    write("kfr-missing-im", "kfr", "input.kfr", "Re: 0.25\nZoom: 100\n")
    write("kfr-zero-zoom", "kfr", "input.kfr", "Re: 0.25\nIm: 0\nZoom: 0\n")
    write("kfr-fractional-iterations", "kfr", "input.kfr", "Re: 0.25\nIm: 0\nIterations: 12.5\n")
    write("kfr-iterations-too-large", "kfr", "input.kfr", "Re: 0.25\nIm: 0\nIterations: 1e19\n")

    # Fraktaler-3 1.x-3.0 as it saves: default-valued keys left out (location.imag = 0
    # here, and the reference's imaginary part, equal to the location's), and every
    # string of 68 or more characters streamed as toml11 v3 wraps it at F3's setw(70): a
    # triple quote, 69-character chunks each ending in a line-ending backslash, the last
    # (shorter) chunk, then a backslash line-end and the closer. F3 3.1 writes one line.
    def toml11(key: str, value: str) -> str:
        width = 70
        if len(value) + 2 < width:
            return f'{key} = "{value}"\n'
        chunks = []
        rest = value
        while rest:
            if len(rest) < width:
                chunks.append(rest)
                rest = ""
            else:
                take = width - 2 if rest[width - 2] == "\\" else width - 1
                chunks.append(rest[:take] + "\\\n")
                rest = rest[take:]
        return f'{key} = """\n' + "".join(chunks) + '\\\n"""\n'

    deep_real = (
        "-1.74729959900110572326271032446002389901129253352095659370780511065"
        "03972284717236823618219405542157081921765913744437023107"
    )
    write(
        "f3-as-f3-writes",
        "f3",
        "input.f3.toml",
        'program = "fraktaler-3"\nversion = "3"\n'
        + toml11("location.real", deep_real)
        + toml11("location.zoom", "2.15e2836")
        + toml11("reference.real", deep_real[:-3] + "123")
        + "bailout.iterations = 16777216\nbailout.escape_radius = 625.0\n",
    )
    write(
        "f3-3.1-single-line",
        "f3",
        "input.f3.toml",
        f'program = "fraktaler-3"\nversion = "3.1"\nlocation.real = "{deep_real}"\n'
        'location.imag = "-0.0000000000000000000001"\nlocation.zoom = "2.15e2836"\n',
    )
    # An escaped quote run inside a multi-line string in a skipped array table: the
    # string does not end there, so its "[location] real = 9" lines are text, not keys.
    write(
        "f3-escaped-quotes",
        "f3",
        "input.f3.toml",
        'program = "fraktaler-3"\nlocation.real = "-0.75"\n\n[[formula]]\n'
        'note = """see \\"""\n[location]\nreal = "9"\n"""\n',
    )
    write(
        "f3-sections",
        "f3",
        "input.f3.toml",
        '# a hand-written file\n[location]\nreal = "-7.5e-1"  # the neck, "quoted"\n'
        "imag = '0.1'\nzoom = 1_000.5\n[transform]\nreflect = true\nrotate = 15\n"
        "stretch_amount = 0.5\nexponential_map = true\n"
        '[[history]]\nreal = "9"\nnote = """\nreal = 5\n"""\n[image]\nwidth = 1920\ncolors = [1, 2]\n',
    )
    write("f3-defaults", "f3", "input.f3.toml", 'program = "fraktaler-3"\nlocation.imag = "0.5"\n')
    write("f3-not-a-location", "f3", "input.f3.toml", "[image]\nwidth = 1920\n")

    write(
        "hf-preset-envelope",
        "hf-preset",
        "input.json",
        json.dumps(
            {
                "formatVersion": 1,
                "id": "B2E1D0C9-8A76-4F54-B321-0E9D8C7B6A55",
                "name": "Seahorse Valley",
                "settings": {
                    "location": {
                        "baseHalfHeight": "1.0",
                        "centerImag": "1.31825904205311970493132056385139E-1",
                        "centerReal": "-0.743643887037158704752191506114774",
                        "name": "Seahorse Valley",
                    },
                    "quality": {"height": 1080, "maxIterationsOverride": 60000, "width": 1920},
                    "zoom": {"startDepthLog10": 0, "targetDepthLog10": 30},
                },
            },
            indent=2,
            sort_keys=True,
        ),
    )
    # A bare settings object with no zoom group: no scale (HF would use its app default).
    write(
        "hf-settings-bare",
        "hf-preset",
        "input.json",
        json.dumps(
            {
                "location": {"baseHalfHeight": "1.25", "centerImag": "0.0", "centerReal": "-0.5"},
                "quality": {},
            }
        ),
    )
    write(
        "hf-preset-no-half-height",
        "hf-preset",
        "input.json",
        json.dumps({"location": {"centerImag": "0.0", "centerReal": "-0.5"}}),
    )
    write(
        "hf-result",
        "hf-result",
        "input.txt",
        "# Heaton Fractal DeepZoomSearch result\n# period 998 minibrot nucleus, depth 1e15.2\n"
        "# verified: does not escape in 4,000 iterations at 2 limbs\n\n"
        "re = -7.436438870371588707780645434936425750476e-1\n"
        "im\t=\t0.1318259042053122928210973548747672652630",
    )
    write("hf-result-no-depth", "hf-result", "input.txt", "re = 0.25\r\nim = -0.5\r\n")
    # The deepest seed wins, the latest among equals -- not the last line; lines that are
    # not seeds (a numeric real, NaN, a torn write) are skipped.
    write(
        "hf-journal",
        "hf-journal",
        "input.jsonl",
        '{"depthLog10": 3.5, "elapsedSeconds": 1, "imaginary": "0.1", "period": 3, '
        '"real": "-0.1", "round": 0}\n'
        '{"depthLog10": 12.25, "elapsedSeconds": 9, "imaginary": "0.13182", "period": 58, '
        '"real": "-0.74364", "round": 1}\n'
        '{"depthLog10": 12.25, "elapsedSeconds": 11, "imaginary": "1.31825e-1", '
        '"navDepthLog10": 12.3, "period": 58, "real": "-0.743643", "round": 2}\n'
        '{"depthLog10": 11.0, "elapsedSeconds": 12, "imaginary": "0.2", "period": 7, '
        '"real": "-0.5", "round": 3}\n'
        '{"depthLog10": 99.0, "imaginary": "0.3", "real": -0.5}\n'
        '{"depthLog10": NaN, "imaginary": "0.3", "real": "-0.5"}\n'
        '{"depthLog10": 13.0, "imag',
    )


def write_png_io_cases() -> None:
    """PNG grid I/O (spec/png-io.md): decode pins. PNG bytes are per-encoder;
    the decoded grids are the cross-language contract — additive, run alone."""
    import io

    from PIL import Image

    from heaton_life.init import mergelife_to_png

    def rgb_png(arr: np.ndarray) -> bytes:
        buf = io.BytesIO()
        Image.fromarray(arr, mode="RGB").save(buf, format="PNG")
        return buf.getvalue()

    values = (np.arange(4 * 5 * 3, dtype=np.uint32) * 7 + 3) % 256
    grid = values.astype(np.uint8).reshape(4, 5, 3)

    def write(name: str, input_png: bytes, scale: int) -> None:
        case_dir = VECTOR_ROOT / "png-io" / name
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "input.png").write_bytes(input_png)
        (case_dir / "grid.png").write_bytes(rgb_png(grid))
        meta: dict[str, Any] = {
            "spec_version": SPEC_VERSION,
            "family": "png-io",
            "tier": "bit-exact",
            "kind": "decode",
            "scale": scale,
            "input": "input.png",
            "grid": {"file": "grid.png", "shape": [4, 5, 3]},
        }
        (case_dir / "params.json").write_text(
            json.dumps(meta, indent=2, sort_keys=True) + "\n", newline="\n"
        )
        print(f"wrote {case_dir.relative_to(REPO_ROOT)}")

    write("decode-scale1", mergelife_to_png(grid, 1), 1)
    write("decode-scale3", mergelife_to_png(grid, 3), 3)
    alpha = ((np.arange(4 * 5, dtype=np.uint32) * 13 + 1) % 256).astype(np.uint8)
    rgba = np.concatenate([grid, alpha.reshape(4, 5, 1)], axis=2)
    rgba_buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(rgba_buf, format="PNG")
    write("decode-rgba-dropped", rgba_buf.getvalue(), 1)


if __name__ == "__main__":
    main()
