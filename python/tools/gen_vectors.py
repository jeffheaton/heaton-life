#!/usr/bin/env python3
"""Regenerate the golden conformance vectors in ../../vectors/.

Run only when a spec change justifies it; vectors are the cross-language contract.
(vectors/mergelife-upstream/ is NOT generated here — it tracks the upstream repo.)
Usage: .venv/bin/python tools/gen_vectors.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from heaton_life.ca import LifeLike, Wireworld, wireworld_from_text
from heaton_life.conformance import CODECS, TIERS, build_sim
from heaton_life.core.bignum import reference_orbit
from heaton_life.core.protocols import Simulation
from heaton_life.core.viewport import Viewport
from heaton_life.fractal import BurningShip, Julia, Mandelbrot, Newton
from heaton_life.init import place, rle_decode

SPEC_VERSION = "0.2.0"
REPO_ROOT = Path(__file__).resolve().parents[2]
VECTOR_ROOT = REPO_ROOT / "vectors"

GLIDER_RLE = "x = 3, y = 3, rule = B3/S23\nbob$2bo$3o!"


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
        "params": sim.params.to_dict(),  # type: ignore[attr-defined]
        "checkpoints": checkpoints,
    }
    if epsilon is not None:
        meta["epsilon"] = epsilon
    (case_dir / "params.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    print(f"wrote {case_dir.relative_to(REPO_ROOT)} (steps {steps})")


def main() -> None:
    # -- lifelike ------------------------------------------------------------------
    pattern, _ = rle_decode(GLIDER_RLE)
    glider = LifeLike("B3/S23", size=(16, 16), init=place(pattern, (16, 16), at=(0, 0)))
    write_case("lifelike", "glider-16-torus", glider, [0, 32, 64])

    lifelike_cases = [
        ("soup-64-torus", {"rule": "B3/S23", "density": 0.35, "seed": 42}),
        ("soup-64-dead", {"rule": "B3/S23", "density": 0.35, "seed": 7, "boundary": "dead"}),
        ("highlife-64-torus", {"rule": "B36/S23", "density": 0.4, "seed": 11}),
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
    junction = wireworld_from_text(
        "TH########.\n"
        "..........#\n"
        "TH########.\n"
    )
    grid = place(junction, (16, 8), at=(1, 2))
    write_case("wireworld", "junction-16", Wireworld(size=(16, 8), init=grid), [0, 1, 5, 20])

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

    # -- fractals (one-shot renders: params + viewport + int32 outputs) --------------
    write_fractal_case(
        "mandelbrot", "home-64",
        Mandelbrot(max_iter=500),
        {"max_iter": 500, "escape_radius": 1000.0},
        Viewport("-0.5", "0.0", 0.0), (64, 64),
    )
    write_fractal_case(
        "mandelbrot", "deep-zoom14-48",
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
    write_fractal_case(
        "julia", "classic-64",
        Julia(max_iter=500),
        {"c_re": -0.7269, "c_im": 0.1889, "max_iter": 500, "escape_radius": 1000.0},
        Viewport("0.0", "0.0", 0.0), (64, 64),
    )
    write_fractal_case(
        "burning-ship", "home-64",
        BurningShip(max_iter=500),
        {"max_iter": 500, "escape_radius": 1000.0},
        Viewport("-0.5", "-0.5", -0.2), (64, 64),
    )
    write_fractal_case(
        "newton", "z3-64",
        Newton(degree=3, max_iter=60),
        {"degree": 3, "max_iter": 60},
        Viewport("0.0", "0.0", -0.1), (64, 64),
    )

    # -- render (colormap LUTs + frame indexing, spec/render.md) ---------------------
    write_render_cases()
    write_frame_cases()

    # -- evolve (objective stats, GA operators, seeded mini-run, spec/evolve.md) -----
    write_evolve_cases()

    # -- patterns (RLE dialects, transforms, stamp semantics, spec/patterns.md) ------
    write_pattern_cases()

    print("done")


def write_fractal_case(
    family: str,
    name: str,
    field: Any,
    params: dict[str, Any],
    viewport: Viewport,
    size: tuple[int, int],
    orbit_kind: str | None = None,
) -> None:
    case_dir = VECTOR_ROOT / family / name
    case_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for kind, grid in field.outputs(size, viewport).items():
        file = f"{kind}.i32"
        (case_dir / file).write_bytes(np.ascontiguousarray(grid, dtype="<i4").tobytes())
        outputs.append({"kind": kind, "file": file, "shape": list(grid.shape)})
    meta: dict[str, Any] = {
        "spec_version": SPEC_VERSION,
        "family": family,
        "tier": "bit-exact",
        "params": params,
        "viewport": viewport.to_dict(),
        "size": list(size),
        "outputs": outputs,
    }
    if orbit_kind is not None:
        orbit = reference_orbit(
            orbit_kind, viewport.center_re, viewport.center_im,
            viewport.zoom_log10, params["max_iter"],
        )
        (case_dir / "orbit.c128").write_bytes(
            np.ascontiguousarray(orbit, dtype="<c16").tobytes()
        )
        meta["reference_orbit"] = {"file": "orbit.c128", "length": len(orbit)}
    (case_dir / "params.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    print(f"wrote {case_dir.relative_to(REPO_ROOT)}")


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
        (case_dir / "params.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
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
        (case_dir / "params.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
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
        (case_dir / "params.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
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
            (case_dir / "frame.f64").write_bytes(
                np.ascontiguousarray(frame, dtype="<f8").tobytes()
            )
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
            "states": 14, "threshold": 1, "reach": 1, "neighborhood": "moore",
            "width": 32, "height": 32,
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
            "du": 0.16, "dv": 0.08, "feed": 0.0367, "kill": 0.0649, "dt": 1.0,
            "width": 48, "height": 48,
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
            "count": 5, "width": 16, "height": 12, "perception": 12.0,
            "separation_radius": 6.0, "w_separation": 1.5, "w_alignment": 1.0,
            "w_cohesion": 1.0, "max_speed": 3.0, "min_speed": 1.0,
            "max_force": 0.08, "boundary": "wrap",
        },
        boids,
        float_frame=True,
    )

    fractal_cases = [
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
    ]
    for name, family, field, params, viewport in fractal_cases:
        case_dir = VECTOR_ROOT / "render" / name
        case_dir.mkdir(parents=True, exist_ok=True)
        render = field.render((64, 64), viewport)
        (case_dir / "render.f64").write_bytes(
            np.ascontiguousarray(render, dtype="<f8").tobytes()
        )
        write_meta(case_dir, {
            "spec_version": SPEC_VERSION,
            "family": "render",
            "tier": "epsilon",
            "epsilon": 1e-9,
            "kind": "fractal-render",
            "sim_family": family,
            "params": params,
            "viewport": viewport.to_dict(),
            "size": [64, 64],
            "output": {"file": "render.f64", "shape": [64, 64]},
        })


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
        (case_dir / "params.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
        print(f"wrote {case_dir.relative_to(REPO_ROOT)}")

    # RLE decode + canonical encode cases. Grids are stored raw-value grayscale.
    rle_cases = [
        (
            "rle-glider",
            ("#C the classic glider, comments and all\n"
            "x = 3, y = 3, rule = B3/S23\n"
            "bob$2bo$3o!\n"),
        ),
        (
            "rle-lwss-headerless",
            "b3o$o2bo$3bo$o2bo!\n",  # no header: size from extents
        ),
        (
            "rle-uppercase-two-state",
            ("x = 2, y = 2, rule = B3/S23\n"
            "OB$BO!\n"),  # uppercase B/O with a Life-like rule: two-state dialect
        ),
        (
            "rle-wireworld-diode",
            ("x = 4, y = 3, rule = WireWorld\n"
            ".2C$AC.C$.2CB!\n"),  # extended: B is state 2 here, not 'dead'
        ),
        (
            "rle-cyclic-bands",
            ("x = 5, y = 2, rule = cyclic-6\n"
            "ABCDE$EDCBA!\n"),
        ),
    ]
    for name, text in rle_cases:
        case_dir = VECTOR_ROOT / "patterns" / name
        case_dir.mkdir(parents=True, exist_ok=True)
        grid, rule = rle_decode(text)
        canonical = rle_encode(grid, rule=rule if rule is not None else "B3/S23")
        (case_dir / "input.rle").write_text(text)
        (case_dir / "grid.png").write_bytes(gray_png(grid))
        (case_dir / "canonical.rle").write_text(canonical)
        write_meta(case_dir, {
            "spec_version": SPEC_VERSION,
            "family": "patterns",
            "tier": "bit-exact",
            "kind": "rle",
            "rule": rule,
            "input": "input.rle",
            "grid": {"file": "grid.png", "shape": list(grid.shape)},
            "canonical": "canonical.rle",
        })

    # Transforms on an asymmetric multi-state grid (raw-value grayscale).
    base = np.array([[1, 2, 3, 0], [0, 4, 0, 5], [6, 0, 7, 8]], dtype=np.uint8)
    case_dir = VECTOR_ROOT / "patterns" / "transforms"
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "grid.png").write_bytes(gray_png(base))
    (case_dir / "rotate90.png").write_bytes(gray_png(rotate90(base)))
    (case_dir / "flip_h.png").write_bytes(gray_png(flip_h(base)))
    (case_dir / "flip_v.png").write_bytes(gray_png(flip_v(base)))
    write_meta(case_dir, {
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
    })

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
        write_meta(case_dir, {
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
        })

    # Extract semantics: the same wrap/zero-fill contract, round-tripped.
    grid16 = np.arange(16, dtype=np.uint8).reshape(4, 4)
    for name, torus in (("extract-torus", True), ("extract-dead", False)):
        case_dir = VECTOR_ROOT / "patterns" / name
        case_dir.mkdir(parents=True, exist_ok=True)
        region = extract(grid16, 3, 3, 2, 2, torus=torus)
        (case_dir / "grid.png").write_bytes(gray_png(grid16))
        (case_dir / "expected.png").write_bytes(gray_png(region))
        write_meta(case_dir, {
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
        })


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
        (case_dir / "params.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
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
                stats["steps"], stats["foreground"], stats["active"],
                stats["rect"], stats["mage"], _score_stats(stats, PAPER_OBJECTIVE),
            ]
        (case_dir / "runs.f64").write_bytes(np.ascontiguousarray(runs, dtype="<f8").tobytes())
        summary = np.array([runs[:, 5].max(), runs[:, 0].sum()], dtype=np.float64)
        (case_dir / "score.f64").write_bytes(np.ascontiguousarray(summary, dtype="<f8").tobytes())
        write_meta(case_dir, {
            "spec_version": SPEC_VERSION,
            "family": "evolve",
            "tier": "bit-exact",
            "kind": "objective",
            "params": {
                "genome": genome, "width": width, "height": height,
                "cycles": cycles, "seed": seed, "max_steps": max_steps,
                "objective": "paper",
            },
            "outputs": {
                "runs": {"file": "runs.f64", "shape": [cycles, 6],
                         "columns": ["steps", "foreground", "active", "rect", "mage", "score"]},
                "score": {"file": "score.f64", "shape": [2],
                          "columns": ["max_score", "total_steps"]},
            },
        })

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
    write_meta(VECTOR_ROOT / "evolve" / "operators-seeded", {
        "spec_version": SPEC_VERSION,
        "family": "evolve",
        "tier": "bit-exact",
        "kind": "operators",
        "params": {
            "genome": redworld, "parent2": parent2,
            "mutate_seed": 5, "crossover_seed": 6,
            "tournament_seed": 7, "tournament_rounds": 3, "tournament_scores": scores,
        },
        "expected": {
            "mutations": mutations,
            "crossovers": crossovers,
            "winners_best": winners_best,
            "winners_worst": winners_worst,
        },
    })

    # Mini evolution run: the integration pin — deterministic end to end.
    evolver = Evolver(
        size=(24, 24), population_size=8, tournament_rounds=3,
        eval_cycles=1, patience=1000, max_steps=120, seed=123,
    )
    best = evolver.run(max_evals=20)
    case_dir = VECTOR_ROOT / "evolve" / "mini-run-24"
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "best.f64").write_bytes(
        np.array([best.score], dtype="<f8").tobytes()
    )
    write_meta(case_dir, {
        "spec_version": SPEC_VERSION,
        "family": "evolve",
        "tier": "bit-exact",
        "kind": "run",
        "params": {
            "width": 24, "height": 24, "population_size": 8, "crossover_rate": 0.75,
            "tournament_rounds": 3, "eval_cycles": 1, "patience": 1000,
            "max_steps": 120, "seed": 123, "max_evals": 20, "objective": "paper",
        },
        "expected": {
            "best_genome": best.genome,
            "evals": evolver.evals,
            "population": [c.genome for c in evolver.population],
            "best_score": {"file": "best.f64", "shape": [1]},
        },
    })


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
        (case_dir / "params.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
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
