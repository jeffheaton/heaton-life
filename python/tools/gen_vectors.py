#!/usr/bin/env python3
"""Regenerate the golden conformance vectors in ../../vectors/.

Run only when a spec change justifies it; vectors are the cross-language contract.
(vectors/mergelife-upstream/ is NOT generated here — it tracks the upstream repo.)
Usage: .venv/bin/python tools/gen_vectors.py
"""

from __future__ import annotations

import dataclasses
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
from heaton_life.core.bignum import reference_orbit, working_bits
from heaton_life.core.protocols import Field, Simulation
from heaton_life.core.viewport import Viewport
from heaton_life.fractal import BurningShip, Julia, Mandelbrot, Newton, pan, pixel_delta, zoom_at
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
    if orbit_kind is not None:
        c_re = params.get("c_re", 0.0)
        c_im = params.get("c_im", 0.0)
        orbit = reference_orbit(
            orbit_kind,
            *viewport.orbit_center,
            viewport.zoom_log10,
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
                viewport.zoom_log10,
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

    def write(name: str, meta: dict[str, Any]) -> None:
        case_dir = root / name
        case_dir.mkdir(parents=True, exist_ok=True)
        full = {"spec_version": "0.5.0", "family": "navigation", "tier": "bit-exact", **meta}
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
        write(name, meta)

    def zoom_case(
        name: str, vp: Viewport, dx: float, dy: float, size: tuple[int, int], zoom: float
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
        )

    def delta_case(name: str, frm: Viewport, to: Viewport, size: tuple[int, int]) -> None:
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
