"""Generate the platform self-check's embedded data (spec/self-check.md) for both ports.

Every input and known answer the self-check carries comes from here: the vectors (their
output files digested, their inputs copied), the spec pages' tables, and exact oracles
(fractions.Fraction, CPython's correctly rounded float()). The output files are never
edited by hand:

    python/src/heaton_life/_self_check_data.py
    dotnet/src/HeatonLife.Core/SelfCheckData.cs

Run from python/ with the venv:  .venv/bin/python tools/gen_self_check.py
A deliberate vector regeneration that touches a source case must be followed by a rerun;
tests/test_self_check.py fails until the files match.
"""

from __future__ import annotations

import io
import json
import struct
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
VECTORS = REPO_ROOT / "vectors"
PY_OUT = REPO_ROOT / "python" / "src" / "heaton_life" / "_self_check_data.py"
CS_OUT = REPO_ROOT / "dotnet" / "src" / "HeatonLife.Core" / "SelfCheckData.cs"

FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 0x100000001B3
CANONICAL_NAN = 0x7FF8000000000000


def fnv1a64(data: bytes) -> int:
    value = FNV_OFFSET
    for byte in data:
        value ^= byte
        value = (value * FNV_PRIME) & 0xFFFFFFFFFFFFFFFF
    return value


def bits_of(value: float) -> int:
    result: int = struct.unpack("<Q", struct.pack("<d", value))[0]
    return result


def double_of(bits: int | str) -> float:
    if isinstance(bits, str):
        bits = int(bits, 16)
    result: float = struct.unpack("<d", struct.pack("<Q", bits))[0]
    return result


def f64_digest(values: np.ndarray, *, canonical_nan: bool = False) -> int:
    """FNV-1a 64 of float64 values as little-endian bytes; with canonical_nan, every NaN
    as 0x7FF8000000000000 first (a NaN's sign bit is platform-dependent)."""
    words = np.ascontiguousarray(values, dtype="<f8").view("<u8").copy()
    if canonical_nan:
        words[np.isnan(np.asarray(values, dtype=np.float64))] = CANONICAL_NAN
    return fnv1a64(words.tobytes())


def file_digest(path: Path, dtype: str, *, canonical_nan: bool = False) -> int:
    data = np.frombuffer(path.read_bytes(), dtype=dtype)
    if dtype == "<f8":
        return f64_digest(data, canonical_nan=canonical_nan)
    return fnv1a64(data.tobytes())


def png_rgb_digest(path: Path) -> int:
    from PIL import Image

    with Image.open(io.BytesIO(path.read_bytes())) as image:
        return fnv1a64(np.asarray(image.convert("RGB"), dtype=np.uint8).tobytes())


def meta(case: str) -> dict[str, Any]:
    result: dict[str, Any] = json.loads((VECTORS / case / "params.json").read_text())
    return result


# --- the data -----------------------------------------------------------------------


def fma_triples() -> list[tuple[int, int, int, int]]:
    """Software fma known answers (C#): 22 triples across the Dekker path and the slow
    paths (tiny products, huge operands, overflow, an infinite addend), then exact
    residuals c = -round(a*b), where the fused result is the product's rounding error
    and any unfused path returns 0 -- the shape that shows whether the fma is fused at
    all. Every finite answer is checked here against the exactly rounded a*b + c
    (fractions.Fraction); the C# suite checks all of them against
    Math.FusedMultiplyAdd."""
    triples = [
        (0x436725D29FE900AF, 0x43A933F4FE267553, 0x3EE4DAB76ED67771, 0x47223B220CDAF0D0),
        (0x42D6A863330E0D79, 0x4098EE9D4DF90000, 0xC0FD6D71C92B5000, 0x4381A73E2972635C),
        (0x3C73B86DA6C9ED5A, 0xC2088E1D210482F0, 0x3F0C0492F9DB22D1, 0x3F0BE64F2CACD2FD),
        (0x4311816751B50896, 0x4144DE4B9B157000, 0xBF16F964F06F6945, 0x4466D4F757F156DC),
        (0x40885E87D54F0000, 0xC3B5FC6784E4DB7F, 0xBDCC29AAE306E4BB, 0xC450BE40672515B6),
        (0x41C7C159F9263168, 0xBF32E1B024DD2F1B, 0x40B3CA6EB2998000, 0xC10B6A46498EF85B),
        (0x42ABDEDFF5C20293, 0x3DB9AD034B118AE8, 0x3CF9D047A61A020A, 0x40765CCEC10ED635),
        (0x42F9D198C94E4C45, 0xC3F7CE470A6BFAB0, 0xC3A4E2C21C0A2E90, 0xC703351469B3CC5C),
        (0xBC630E1240324DFB, 0x3E8027BAF74CD317, 0xBE48839C80D4A6B6, 0xBE48839C80D4A6B7),
        (0x4392AD328315DAF5, 0xBFD94B0C8A000000, 0xC0F554309E0AE000, 0xC37D86396C9467E0),
        (0x3F63C5675999999A, 0xC0D2537E7851C000, 0xBD12C9ED68AFF6EA, 0xC046A540942906F2),
        (0xC17D1DC029FD4700, 0x3CE029CCEE7D4D7D, 0xBBFA0DE2F458A197, 0xBE6D69D153B9BB60),
        (0x3E370A60E1165AE0, 0xBDE5C4ABCFA8D488, 0x409D1BA48D928000, 0x409D1BA48D928000),
        (0xC3771E27707F922A, 0xC26D7154F653685A, 0x416AC7EC1F8CAF80, 0x45F545339A54770B),
        (0xC185156B037AFEC0, 0xC3E925A321861415, 0x42E09DE1EA1BEE46, 0x45809187D9A3A865),
        (0xBF517C900083126F, 0x3D7DBE3F7D2DD21A, 0x3EEC8DD0624DD2F2, 0x3EEC8DD0623D9219),
        (0x1EC0DEF50DDC92D7, 0x9EBD3E314B3A0F97, 0x00003739A252B281, 0x00003739A252A316),
        (0x1E354E8E18E10C76, 0x1ED04EFDF3CCB014, 0x0000000000000000, 0x0000000000000016),
        (0x8010000000000000, 0x3FE8000000000000, 0x0010000000000000, 0x0004000000000000),
        (0x7E37E43C8800759C, 0x3DF49DA7E361CE4C, 0xFC2485CE9E7A065F, 0x7C3485CE9E7A065F),
        (0x697F5AA543C31387, 0x697F5AA543C31387, 0xFFE1CCF385EBC8A0, 0x7FF0000000000000),
        (0x5FF7DDDF6B095FF1, 0x5FF7DDDF6B095FF1, 0xFFF0000000000000, 0xFFF0000000000000),
    ]
    for a, b in [
        (1 + 2.0**-30, 1 + 2.0**-31),
        (0.1, 0.7),
        (3.141592653589793, 2.718281828459045),
        (-1.4142135623730951, 1.7320508075688772),
    ]:
        residual = float(Fraction(a) * Fraction(b) - Fraction(a * b))
        assert residual != 0.0, (a, b)
        triples.append((bits_of(a), bits_of(b), bits_of(-(a * b)), bits_of(residual)))
    for a_bits, b_bits, c_bits, e_bits in triples:
        a, b, c, e = (double_of(x) for x in (a_bits, b_bits, c_bits, e_bits))
        if not (np.isfinite(c) and np.isfinite(e)):
            continue  # the overflow and infinite-addend triples: IEEE rules, not Fraction
        assert float(Fraction(a) * Fraction(b) + Fraction(c)) == e, hex(a_bits)
    return triples


def numpy_fma() -> dict[str, Any]:
    """spec/deep-zoom.md: NumPy's complex multiply fuses real = fma(a,c,-bd) and
    imag = fma(a,d,bc). Squaring shows the real part's orientation, distinct operands the
    imaginary part's; the answers are exact (fractions.Fraction), rounded once."""
    a, b = 1 + 2.0**-30, 1 + 2.0**-31
    c, d = -(1 + 2.0**-31), 1 + 2.0**-30
    square_re = float(Fraction(a) * Fraction(a) - Fraction(b * b))
    product_im = float(Fraction(a) * Fraction(d) + Fraction(b * c))
    return {
        "a": bits_of(a),
        "b": bits_of(b),
        "c": bits_of(c),
        "d": bits_of(d),
        "square_re": bits_of(square_re),
        "product_im": bits_of(product_im),
        "lengths": [1, 17, 1001],
    }


def pcg32() -> dict[str, Any]:
    """spec/rng.md's known-answer test."""
    return {
        "seed": 42,
        "seq": 54,
        "draws": [0xA15C02B7, 0x7B47F409, 0xBA1D3330, 0x83D2F293, 0xBFA4784B, 0xCBED606E],
    }


def pow10() -> dict[str, Any]:
    """spec/pow10.md's known-answer table and its floatexp answers (pow10x), read from the
    page and checked against the reference implementation."""
    import re

    from heaton_life.core.pow10 import pow10 as p10
    from heaton_life.core.pow10 import pow10x

    page = (REPO_ROOT / "spec" / "pow10.md").read_text()
    table = [
        (float(x), int(bits, 16))
        for x, bits in re.findall(
            r"^pow10\(\s*(-?[0-9.]+)\)\s*=\s*(0x[0-9A-F]{16})", page, re.MULTILINE
        )
    ]
    assert len(table) == 10, table
    for x, bits in table:
        assert bits_of(p10(x)) == bits, x
    x_spec = {  # spec/pow10.md "Floatexp", as both suites pin them
        -300.5: (0x3FFB1B75833790CA, -999),
        -320.0: (0x3FFFA01712E8F047, -1064),
        -996.5: (0x3FF9F7C393991048, -3311),
        -9000.0: (0x3FF90E9C5BFAC594, -29898),
        10000.0: (0x3FF3709D450AAD7E, 33219),
    }
    for x, answer in x_spec.items():
        m, n = pow10x(x)
        assert (bits_of(m), n) == answer, x
    return {
        "table": [(bits_of(x), bits) for x, bits in table],
        "floatexp": [(bits_of(x), *answer) for x, answer in x_spec.items()],
    }


ELEVEN_DIMENSIONS_RE = meta("mandelbrot/deep-zoom20-11dim-32")["viewport"]["center_re"]


def centers() -> list[tuple[str, int]]:
    """Decimal -> float64 projections, each the correctly rounded float() of the text."""
    texts = [
        "-0.743643887037158704752191506114774",
        "0.131825904205311970493132056385139",
        ELEVEN_DIMENSIONS_RE,
        "9007199254740993",
        "9007199254740995",
        "4.9406564584124654e-324",
        "-0",
    ]
    return [(text, bits_of(float(text))) for text in texts]


def turns() -> list[tuple[int, int, int, int]]:
    cases = meta("turns/known-answers")["cases"]
    return [(c["k"], c["n"], int(c["expected"][0], 16), int(c["expected"][1], 16)) for c in cases]


def floatexp_ops() -> list[tuple[str, int, int, int, int, str, int, int, int]]:
    """Every floatexp operation vector, uniformly: (op, a mantissa bits, a exponent,
    b mantissa bits, b exponent, integer text, bits, expected mantissa bits, expected
    exponent). compare's answer sits in the expected exponent; to_double's bits in the
    expected mantissa; normalize's value in a."""
    out = []
    for name in ("operations", "division"):
        for c in meta(f"floatexp/{name}")["cases"]:
            op = c["op"]
            am = ae = bm = be = bits = em = ee = 0
            text = ""
            if "a" in c:
                am, ae = int(c["a"][0], 16), c["a"][1]
            if "b" in c:
                bm, be = int(c["b"][0], 16), c["b"][1]
            if op == "normalize":
                am, ae = int(c["value"], 16), c["exponent"]
            if op == "from_fixed":
                text, bits = c["value"], c["bits"]
            if op == "compare":
                ee = c["expected"]
            elif op == "to_double":
                em = int(c["expected"], 16)
            else:
                em, ee = int(c["expected"][0], 16), c["expected"][1]
            out.append((op, am, ae, bm, be, text, bits, em, ee))
    return out


def orbit() -> dict[str, Any]:
    """Samples 1, 8 and 64 of vectors/mandelbrot/deep-zoom14-48's stored orbit, and two
    1-step orbits whose Z1 = C is a tie: 1 + 2^-53 (a fixed-width orbit) and 2^16 + 2^-37
    (|C| >= 2^16: the arbitrary-precision path), each ties to even."""
    m = meta("mandelbrot/deep-zoom14-48")
    stored = np.frombuffer(
        (VECTORS / "mandelbrot/deep-zoom14-48/orbit.c128").read_bytes(), dtype="<c16"
    )
    samples = [(i, bits_of(stored[i].real), bits_of(stored[i].imag)) for i in (1, 8, 64)]
    ties = [
        "1.00000000000000011102230246251565404236316680908203125",
        "65536.0000000000072759576141834259033203125",
    ]
    return {
        "center_re": m["viewport"]["center_re"],
        "center_im": m["viewport"]["center_im"],
        "zoom": 14.0,
        "max_iter": 64,
        "samples": samples,
        "ties": [(text, bits_of(float(text))) for text in ties],
    }


def navigation() -> list[dict[str, Any]]:
    out = []
    for name in ("pan-t2-zoom996", "zoom-at-deep"):
        m = meta(f"navigation/{name}")
        out.append(
            {
                "op": m["operation"],
                "center_re": m["viewport"]["center_re"],
                "center_im": m["viewport"]["center_im"],
                "zoom": m["viewport"]["zoom_log10"],
                "width": m["size"][0],
                "height": m["size"][1],
                "dx": m["dx"],
                "dy": m["dy"],
                "new_zoom": m.get("zoom_log10"),
                "expected_re": m["expected"]["center_re"],
                "expected_im": m["expected"]["center_im"],
                "expected_zoom": m["expected"]["zoom_log10"],
            }
        )
    return out


def mergelife() -> dict[str, Any]:
    """The first upstream cross-engine vector (vectors/mergelife-upstream/vectors.txt: rule,
    rows, cols, LCG seed, steps, FNV-1a 64 digest), checked against the reference."""
    from heaton_life.ca.mergelife import MergeLife

    lines = (VECTORS / "mergelife-upstream" / "vectors.txt").read_text().splitlines()
    first = next(line for line in lines if line and not line.startswith("#"))
    rule, rows_text, cols_text, seed_text, steps_text, digest_text = first.split()
    rows, cols, seed, steps = int(rows_text), int(cols_text), int(seed_text), int(steps_text)
    state = seed
    lattice = np.empty(rows * cols * 3, dtype=np.uint8)
    for i in range(lattice.size):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        lattice[i] = state >> 24
    sim = MergeLife(rule, size=(cols, rows), init=lattice.reshape(rows, cols, 3))
    sim.step(steps)
    digest = int(digest_text, 16)
    assert fnv1a64(np.ascontiguousarray(sim.state).tobytes()) == digest
    return {
        "rule": rule,
        "rows": rows,
        "cols": cols,
        "seed": seed,
        "steps": steps,
        "digest": digest,
    }


def grayscott() -> dict[str, Any]:
    m = meta("grayscott/mitosis-center-64")
    p = m["params"]
    assert p["init"] == "center", p
    return {
        "width": p["width"],
        "height": p["height"],
        "du": p["du"],
        "dv": p["dv"],
        "feed": p["feed"],
        "kill": p["kill"],
        "dt": p["dt"],
        "steps": 100,
        "digest": file_digest(VECTORS / "grayscott/mitosis-center-64/state_00100.f64", "<f8"),
    }


RENDER_CASES = [
    ("mandelbrot-t0", "mandelbrot/home-64"),
    ("burning-ship-t0", "burning-ship/home-64"),
    ("julia-t1", "julia/t1-julia-i-precision-zoom100-12"),
    ("burning-ship-t1", "burning-ship/deep-zoom13-32"),
    ("mandelbrot-t1-bla", "mandelbrot/bla-p1959-zoom30-16"),
    ("mandelbrot-t2-bla", "mandelbrot/t2-bla-p830-escape-zoom300-9"),
    ("julia-t2", "julia/t2-julia-i-precision-zoom400-12"),
]


def renders() -> list[dict[str, Any]]:
    out = []
    for name, case in RENDER_CASES:
        m = meta(case)
        p, v = m["params"], m["viewport"]
        assert set(v) == {"center_re", "center_im", "zoom_log10"}, case
        entry: dict[str, Any] = {
            "name": name,
            "family": m["family"],
            "max_iter": p["max_iter"],
            "escape_radius": p["escape_radius"],
            "c_re": p.get("c_re", 0.0),
            "c_im": p.get("c_im", 0.0),
            "bla": bool(p.get("bla", False)),
            "width": m["size"][0],
            "height": m["size"][1],
            "center_re": v["center_re"],
            "center_im": v["center_im"],
            "zoom": v["zoom_log10"],
            "iterations": 0,
            "applications": 0,
            "table": 0,
            "entries": [],
        }
        for output in m["outputs"]:
            path = VECTORS / case / output["file"]
            if output["kind"] == "iterations":
                entry["iterations"] = file_digest(path, "<i4")
            elif output["kind"] == "bla_applications":
                entry["applications"] = file_digest(path, "<i4")
            elif output["kind"] in ("bla_table", "bla_table_x"):
                entry["table"] = file_digest(path, "<f8", canonical_nan=True)
                entry["entries"] = list(output["entries"])
        assert entry["iterations"] != 0, case
        assert entry["bla"] == (entry["applications"] != 0 and entry["table"] != 0), case
        out.append(entry)
    return out


def _x_pair(data: list[Any] | None) -> tuple[int, int, int, int] | None:
    if data is None:
        return None
    (rm, re), (im, ie) = data
    return (int(rm, 16), re, int(im, 16), ie)


def t2_steps() -> list[dict[str, Any]]:
    """Crafted T2 loops (vectors/t2-steps): a BLA skip over a complex table, a huge sample,
    and a delta gap, every output bit for bit."""
    out = []
    for name in ("bla-complex-skip", "huge-sample", "delta-gap"):
        m = meta(f"t2-steps/{name}")
        rebase = m["rebase_orbit"]
        derivative = m["derivative"]
        expected = m["expected"]
        table = expected.get("table")
        out.append(
            {
                "name": name,
                "samples": [(int(r, 16), int(i, 16)) for r, i in m["orbit"]["samples"]],
                "small": [
                    (row[0], int(row[1], 16), row[2], int(row[3], 16), row[4])
                    for row in m["orbit"]["small"]
                ],
                "has_rebase": rebase is not None,
                "rebase_samples": (
                    []
                    if rebase is None
                    else [(int(r, 16), int(i, 16)) for r, i in rebase["samples"]]
                ),
                "rebase_small": (
                    []
                    if rebase is None
                    else [
                        (row[0], int(row[1], 16), row[2], int(row[3], 16), row[4])
                        for row in rebase["small"]
                    ]
                ),
                "delta0": _x_pair(m["delta0"]),
                "delta_c": _x_pair(m["delta_c"]),
                "d0": None if derivative is None else _x_pair(derivative["d0"]),
                "add": (
                    None
                    if derivative is None or derivative["add"] is None
                    else (int(derivative["add"][0], 16), derivative["add"][1])
                ),
                "has_derivative": derivative is not None,
                "max_iter": m["max_iter"],
                "escape_radius": m["escape_radius"],
                "dc_exponent": m["bla"]["dc_exponent"] if "bla" in m else None,
                "count": expected["count"],
                "final": (int(expected["final"][0], 16), int(expected["final"][1], 16)),
                "derivative": (
                    int(expected["derivative"][0], 16),
                    int(expected["derivative"][1], 16),
                    expected["derivative"][2],
                ),
                "applications": expected.get("applications", 0),
                "table": (
                    0
                    if table is None
                    else f64_digest(np.array([double_of(w) for w in table]), canonical_nan=True)
                ),
            }
        )
    return out


def zoom_plans() -> dict[str, Any]:
    """Every plan of vectors/zoom/plans and one digest over all their frame zooms."""
    plans = meta("zoom/plans")["plans"]
    rows = []
    zoom_bits = []
    for plan in plans:
        rows.append(
            (
                int(plan["start_zoom"], 16),
                int(plan["end_zoom"], 16),
                plan["frames"],
                plan["fps"],
                *(int(v, 16) for v in plan["schedule"]),
            )
        )
        zoom_bits.extend(int(z, 16) for z in plan["zooms"])
    digest = fnv1a64(np.array(zoom_bits, dtype="<u8").tobytes())
    return {"plans": rows, "digest": digest}


def _f64_file(path: Path) -> list[int]:
    return [bits_of(float(x)) for x in np.frombuffer(path.read_bytes(), dtype="<f8")]


def color() -> dict[str, Any]:
    """A LUT built from anchors; a float frame through a colormap (render/apply-half-rainbow:
    round-to-nearest indices); the phase lookup halfway between entries (half-even) and with
    its antialias and dither (render/phase-apply-halfway, -row-seam); and the depth phase on
    a strip of real smooth values (render/phase-flow). Every input and option is the
    vector's own."""
    apply = meta("render/apply-half-rainbow")
    lookups = []
    for name in ("phase-apply-halfway", "phase-apply-row-seam"):
        m = meta(f"render/{name}")
        lookups.append(
            {
                "name": name,
                "cmap": m["cmap"],
                "wrap": m["wrap"],
                "antialias": m["antialias"],
                "dither": double_of(m["dither"]),
                "frame_index": m["frame_index"],
                "interior": list(m["interior"]),
                "height": m["input"]["shape"][0],
                "width": m["input"]["shape"][1],
                "t": _f64_file(VECTORS / "render" / name / m["input"]["file"]),
                "digest": png_rgb_digest(VECTORS / "render" / name / m["output"]["file"]),
            }
        )
    flow = meta("render/phase-flow")
    mu = np.frombuffer((VECTORS / "render/phase-flow/mu.f64").read_bytes(), dtype="<f8")[:256]
    t = np.frombuffer((VECTORS / "render/phase-flow/t.f64").read_bytes(), dtype="<f8")[:256]
    phase = flow["phase"]
    return {
        "lut": ("rainbow", png_rgb_digest(VECTORS / "render/lut-rainbow/lut.png")),
        "apply": {
            "cmap": apply["cmap"],
            "height": apply["input"]["shape"][0],
            "width": apply["input"]["shape"][1],
            "frame": _f64_file(VECTORS / "render/apply-half-rainbow/frame.f64"),
            "digest": png_rgb_digest(VECTORS / "render/apply-half-rainbow/rgb.png"),
        },
        "lookups": lookups,
        "phase": {
            "mu": [bits_of(float(x)) for x in mu],
            "zoom": int(flow["zoom_log10"], 16),
            "cycles_per_iteration": int(phase["cycles_per_iteration"], 16),
            "cycles_per_octave": int(phase["cycles_per_octave"], 16),
            "phase_offset": int(phase["phase_offset"], 16),
            "anchor": int(phase["anchor"], 16),
            "digest": f64_digest(t, canonical_nan=True),
        },
    }


# The checks both ports run, in order after fp-contract and each port's own platform
# check (Python numpy-fma, C# fma): the names hosts gate on, append-only.
SHARED_NAMES = [
    "pcg32",
    "pow10",
    "center-projection",
    "turns",
    "floatexp",
    "reference-orbit",
    "navigation",
    "mergelife-upstream",
    "grayscott-100",
    "mandelbrot-t0",
    "burning-ship-t0",
    "julia-t1",
    "burning-ship-t1",
    "mandelbrot-t1-bla",
    "t2-steps",
    "mandelbrot-t2-bla",
    "julia-t2",
    "zoom-plan",
    "color",
]


def build() -> dict[str, Any]:
    return {
        "SHARED_NAMES": SHARED_NAMES,
        "FMA": fma_triples(),
        "NUMPY_FMA": numpy_fma(),
        "PCG32": pcg32(),
        "POW10": pow10(),
        "CENTERS": centers(),
        "TURNS": turns(),
        "FLOATEXP": floatexp_ops(),
        "ORBIT": orbit(),
        "NAVIGATION": navigation(),
        "MERGELIFE": mergelife(),
        "GRAYSCOTT": grayscott(),
        "RENDERS": renders(),
        "T2_STEPS": t2_steps(),
        "ZOOM_PLANS": zoom_plans(),
        "COLOR": color(),
    }


# --- Python output -------------------------------------------------------------------


def _py(value: Any, indent: int = 0) -> str:
    pad = "    " * indent
    inner = "    " * (indent + 1)
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = [f"{inner}{key!r}: {_py(v, indent + 1)}," for key, v in value.items()]
        return "{\n" + "\n".join(items) + f"\n{pad}}}"
    if isinstance(value, list):
        if not value:
            return "[]"
        items = [f"{inner}{_py(v, indent + 1)}," for v in value]
        return "[\n" + "\n".join(items) + f"\n{pad}]"
    if isinstance(value, tuple):
        return (
            "(" + ", ".join(_py(v, indent) for v in value) + ("," if len(value) == 1 else "") + ")"
        )
    if isinstance(value, bool) or value is None:
        return repr(value)
    if isinstance(value, int):
        return hex(value) if value > 0xFFFF else repr(value)
    if isinstance(value, float):
        return repr(value)
    return repr(value)


def render_python(data: dict[str, Any]) -> str:
    lines = [
        '"""Generated by tools/gen_self_check.py from the vectors and spec tables: do not edit.',
        "",
        "The platform self-check's inputs and known answers (spec/self-check.md).",
        '"""',
        "",
        "# fmt: off",
        "",
        "from typing import Any",
        "",
    ]
    for key, value in data.items():
        if key == "FMA":
            continue  # C# only: Python has no software fma
        lines.append(f"{key}: Any = {_py(value)}")
        lines.append("")
    return "\n".join(lines)


# --- C# output -----------------------------------------------------------------------


def _u(value: int) -> str:
    return f"0x{value:016X}UL"


def _d(value: float) -> str:
    return f"D({_u(bits_of(value))})"


def _s(value: str) -> str:
    return '"' + value + '"'


def _l(value: int) -> str:
    return f"{value}L"


def _pair(value: tuple[int, int, int, int] | None) -> str:
    if value is None:
        return "null"
    return f"({_u(value[0])}, {_l(value[1])}, {_u(value[2])}, {_l(value[3])})"


def render_csharp(data: dict[str, Any]) -> str:
    out: list[str] = []
    w = out.append
    w(
        "// Generated by python/tools/gen_self_check.py from the vectors and spec tables: do not edit."
    )
    w("// The platform self-check's inputs and known answers (spec/self-check.md).")
    w("using System;")
    w("")
    w("namespace HeatonLife")
    w("{")
    w("    internal static class SelfCheckData")
    w("    {")
    w(
        "        private static double D(ulong bits) => BitConverter.Int64BitsToDouble(unchecked((long)bits));"
    )
    w("")
    w("        internal static readonly string[] SharedNames =")
    w("        {")
    for name in data["SHARED_NAMES"]:
        w(f"            {_s(name)},")
    w("        };")
    w("")

    w("        internal static readonly (ulong A, ulong B, ulong C, ulong Expected)[] Fma =")
    w("        {")
    for a, b, c, e in data["FMA"]:
        w(f"            ({_u(a)}, {_u(b)}, {_u(c)}, {_u(e)}),")
    w("        };")
    w("")

    pcg = data["PCG32"]
    w(f"        internal const ulong Pcg32Seed = {pcg['seed']};")
    w(f"        internal const ulong Pcg32Seq = {pcg['seq']};")
    w(
        "        internal static readonly uint[] Pcg32Draws = { "
        + ", ".join(f"0x{d:08X}" for d in pcg["draws"])
        + " };"
    )
    w("")

    w("        internal static readonly (ulong X, ulong Value)[] Pow10 =")
    w("        {")
    for x, v in data["POW10"]["table"]:
        w(f"            ({_u(x)}, {_u(v)}),")
    w("        };")
    w("")
    w("        internal static readonly (ulong X, ulong Mantissa, long Exponent)[] Pow10X =")
    w("        {")
    for x, m, e in data["POW10"]["floatexp"]:
        w(f"            ({_u(x)}, {_u(m)}, {_l(e)}),")
    w("        };")
    w("")

    w("        internal static readonly (string Text, ulong Bits)[] Centers =")
    w("        {")
    for text, b in data["CENTERS"]:
        w(f"            ({_s(text)}, {_u(b)}),")
    w("        };")
    w("")

    w("        internal static readonly (long K, long N, ulong Re, ulong Im)[] Turns =")
    w("        {")
    for k, n, re, im in data["TURNS"]:
        w(f"            ({_l(k)}, {_l(n)}, {_u(re)}, {_u(im)}),")
    w("        };")
    w("")

    w(
        "        internal static readonly (string Op, ulong AM, long AE, ulong BM, long BE, string Value, int Bits, ulong EM, long EE)[] FloatExp ="
    )
    w("        {")
    for op, am, ae, bm, be, text, bits, em, ee in data["FLOATEXP"]:
        w(
            f"            ({_s(op)}, {_u(am)}, {_l(ae)}, {_u(bm)}, {_l(be)}, {_s(text)}, {bits}, {_u(em)}, {_l(ee)}),"
        )
    w("        };")
    w("")

    orb = data["ORBIT"]
    w(f"        internal const string OrbitRe = {_s(orb['center_re'])};")
    w(f"        internal const string OrbitIm = {_s(orb['center_im'])};")
    w(f"        internal const double OrbitZoom = {orb['zoom']!r};")
    w(f"        internal const int OrbitMaxIter = {orb['max_iter']};")
    w("        internal static readonly (int Index, ulong Re, ulong Im)[] OrbitSamples =")
    w("        {")
    for i, re, im in orb["samples"]:
        w(f"            ({i}, {_u(re)}, {_u(im)}),")
    w("        };")
    w("        internal static readonly (string Re, ulong Bits)[] OrbitTies =")
    w("        {")
    for text, b in orb["ties"]:
        w(f"            ({_s(text)}, {_u(b)}),")
    w("        };")
    w("")

    w(
        "        internal static readonly (string Op, string Re, string Im, double Zoom, int Width, int Height, double Dx, double Dy, double NewZoom, string ExpectedRe, string ExpectedIm, double ExpectedZoom)[] Navigation ="
    )
    w("        {")
    for n in data["NAVIGATION"]:
        new_zoom = "double.NaN" if n["new_zoom"] is None else _d(n["new_zoom"])
        w(
            f"            ({_s(n['op'])}, {_s(n['center_re'])}, {_s(n['center_im'])}, {_d(n['zoom'])}, "
            f"{n['width']}, {n['height']}, {_d(n['dx'])}, {_d(n['dy'])}, {new_zoom}, "
            f"{_s(n['expected_re'])}, {_s(n['expected_im'])}, {_d(n['expected_zoom'])}),"
        )
    w("        };")
    w("")

    ml = data["MERGELIFE"]
    w(f"        internal const string MergeLifeRule = {_s(ml['rule'])};")
    w(f"        internal const int MergeLifeRows = {ml['rows']};")
    w(f"        internal const int MergeLifeCols = {ml['cols']};")
    w(f"        internal const uint MergeLifeSeed = {ml['seed']};")
    w(f"        internal const int MergeLifeSteps = {ml['steps']};")
    w(f"        internal const ulong MergeLifeDigest = {_u(ml['digest'])};")
    w("")

    gs = data["GRAYSCOTT"]
    w(f"        internal const int GrayScottWidth = {gs['width']};")
    w(f"        internal const int GrayScottHeight = {gs['height']};")
    w(f"        internal static readonly double GrayScottDu = {_d(gs['du'])};")
    w(f"        internal static readonly double GrayScottDv = {_d(gs['dv'])};")
    w(f"        internal static readonly double GrayScottFeed = {_d(gs['feed'])};")
    w(f"        internal static readonly double GrayScottKill = {_d(gs['kill'])};")
    w(f"        internal static readonly double GrayScottDt = {_d(gs['dt'])};")
    w(f"        internal const int GrayScottSteps = {gs['steps']};")
    w(f"        internal const ulong GrayScottDigest = {_u(gs['digest'])};")
    w("")

    w(
        "        internal static readonly (string Name, string Family, int MaxIter, double EscapeRadius, double CRe, double CIm, bool Bla, int Width, int Height, string Re, string Im, double Zoom, ulong Iterations, ulong Applications, ulong Table, int[] Entries)[] Renders ="
    )
    w("        {")
    for r in data["RENDERS"]:
        entries = (
            "new int[] { " + ", ".join(str(e) for e in r["entries"]) + " }"
            if r["entries"]
            else "new int[0]"
        )
        w(
            f"            ({_s(r['name'])}, {_s(r['family'])}, {r['max_iter']}, {_d(r['escape_radius'])}, "
            f"{_d(r['c_re'])}, {_d(r['c_im'])}, {'true' if r['bla'] else 'false'}, {r['width']}, {r['height']},"
        )
        w(f"                {_s(r['center_re'])},")
        w(f"                {_s(r['center_im'])},")
        w(
            f"                {_d(r['zoom'])}, {_u(r['iterations'])}, {_u(r['applications'])}, {_u(r['table'])}, {entries}),"
        )
    w("        };")
    w("")

    w("        internal static readonly T2StepCase[] T2Steps =")
    w("        {")
    for c in data["T2_STEPS"]:
        w("            new T2StepCase")
        w("            {")
        w(f"                Name = {_s(c['name'])},")
        w("                Samples = new ulong[]")
        w("                {")
        for re, im in c["samples"]:
            w(f"                    {_u(re)}, {_u(im)},")
        w("                },")
        w("                Small = new (int Index, ulong ReM, long ReE, ulong ImM, long ImE)[]")
        w("                {")
        for i, rm, re, im, ie in c["small"]:
            w(f"                    ({i}, {_u(rm)}, {_l(re)}, {_u(im)}, {_l(ie)}),")
        w("                },")
        w(f"                HasRebase = {'true' if c['has_rebase'] else 'false'},")
        w("                RebaseSamples = new ulong[]")
        w("                {")
        for re, im in c["rebase_samples"]:
            w(f"                    {_u(re)}, {_u(im)},")
        w("                },")
        w(
            "                RebaseSmall = new (int Index, ulong ReM, long ReE, ulong ImM, long ImE)[]"
        )
        w("                {")
        for i, rm, re, im, ie in c["rebase_small"]:
            w(f"                    ({i}, {_u(rm)}, {_l(re)}, {_u(im)}, {_l(ie)}),")
        w("                },")
        w(f"                Delta0 = {_pair(c['delta0'])},")
        w(f"                DeltaC = {_pair(c['delta_c'])},")
        w(f"                HasDerivative = {'true' if c['has_derivative'] else 'false'},")
        w(f"                D0 = {_pair(c['d0'])},")
        add = "null" if c["add"] is None else f"({_u(c['add'][0])}, {_l(c['add'][1])})"
        w(f"                Add = {add},")
        w(f"                MaxIter = {c['max_iter']},")
        w(f"                EscapeRadius = {_d(c['escape_radius'])},")
        dc = "null" if c["dc_exponent"] is None else str(c["dc_exponent"])
        w(f"                DcExponent = {dc},")
        w(f"                Count = {c['count']},")
        w(f"                Final = ({_u(c['final'][0])}, {_u(c['final'][1])}),")
        d = c["derivative"]
        w(f"                Derivative = ({_u(d[0])}, {_u(d[1])}, {_l(d[2])}),")
        w(f"                Applications = {c['applications']},")
        w(f"                Table = {_u(c['table'])},")
        w("            },")
    w("        };")
    w("")

    zp = data["ZOOM_PLANS"]
    w(
        "        internal static readonly (ulong Start, ulong End, int Frames, int Fps, ulong HoldStart, ulong EaseIn, ulong EaseOut, ulong HoldEnd)[] ZoomPlans ="
    )
    w("        {")
    for s, e, frames, fps, h0, e0, e1, h1 in zp["plans"]:
        w(
            f"            ({_u(s)}, {_u(e)}, {frames}, {fps}, {_u(h0)}, {_u(e0)}, {_u(e1)}, {_u(h1)}),"
        )
    w("        };")
    w(f"        internal const ulong ZoomPlansDigest = {_u(zp['digest'])};")
    w("")

    col = data["COLOR"]
    w(f"        internal const string LutName = {_s(col['lut'][0])};")
    w(f"        internal const ulong LutDigest = {_u(col['lut'][1])};")
    ap = col["apply"]
    w(f"        internal const string ApplyName = {_s(ap['cmap'])};")
    w(f"        internal const int ApplyWidth = {ap['width']};")
    w(f"        internal const ulong ApplyDigest = {_u(ap['digest'])};")
    w("        internal static readonly ulong[] ApplyFrame =")
    w("        {")
    for k in range(0, len(ap["frame"]), 4):
        w("            " + ", ".join(_u(b) for b in ap["frame"][k : k + 4]) + ",")
    w("        };")
    w("        internal static readonly PhaseLookupCase[] Lookups =")
    w("        {")
    for lk in col["lookups"]:
        w("            new PhaseLookupCase")
        w("            {")
        w(f"                Name = {_s(lk['name'])},")
        w(f"                Cmap = {_s(lk['cmap'])},")
        w(f"                Mirror = {'true' if lk['wrap'] == 'mirror' else 'false'},")
        w(f"                Antialias = {'true' if lk['antialias'] else 'false'},")
        w(f"                Dither = {_d(lk['dither'])},")
        w(f"                FrameIndex = {lk['frame_index']}u,")
        w(
            f"                Interior = new byte[] {{ {', '.join(str(v) for v in lk['interior'])} }},"
        )
        w(f"                Width = {lk['width']},")
        w("                T = new ulong[]")
        w("                {")
        for k in range(0, len(lk["t"]), 4):
            w("                    " + ", ".join(_u(b) for b in lk["t"][k : k + 4]) + ",")
        w("                },")
        w(f"                Digest = {_u(lk['digest'])},")
        w("            },")
    w("        };")
    ph = col["phase"]
    w("        internal static readonly ulong[] PhaseMu =")
    w("        {")
    for k in range(0, len(ph["mu"]), 4):
        w("            " + ", ".join(_u(b) for b in ph["mu"][k : k + 4]) + ",")
    w("        };")
    w(f"        internal const ulong PhaseZoom = {_u(ph['zoom'])};")
    w(f"        internal const ulong PhaseCyclesPerIteration = {_u(ph['cycles_per_iteration'])};")
    w(f"        internal const ulong PhaseCyclesPerOctave = {_u(ph['cycles_per_octave'])};")
    w(f"        internal const ulong PhaseOffset = {_u(ph['phase_offset'])};")
    w(f"        internal const ulong PhaseAnchor = {_u(ph['anchor'])};")
    w(f"        internal const ulong PhaseDigest = {_u(ph['digest'])};")
    w("    }")
    w("")
    w(
        "    /// <summary>One phase-lookup case of the self-check (vectors/render/phase-apply-*).</summary>"
    )
    w("    internal sealed class PhaseLookupCase")
    w("    {")
    w('        internal string Name = "";')
    w('        internal string Cmap = "";')
    w("        internal bool Mirror;")
    w("        internal bool Antialias;")
    w("        internal double Dither;")
    w("        internal uint FrameIndex;")
    w("        internal byte[] Interior = new byte[3];")
    w("        internal int Width;")
    w("        internal ulong[] T = new ulong[0];")
    w("        internal ulong Digest;")
    w("    }")
    w("")
    w("    /// <summary>One crafted T2 loop of the self-check (vectors/t2-steps).</summary>")
    w("    internal sealed class T2StepCase")
    w("    {")
    w('        internal string Name = "";')
    w("        internal ulong[] Samples = new ulong[0];")
    w(
        "        internal (int Index, ulong ReM, long ReE, ulong ImM, long ImE)[] Small = new (int, ulong, long, ulong, long)[0];"
    )
    w("        internal bool HasRebase;")
    w("        internal ulong[] RebaseSamples = new ulong[0];")
    w(
        "        internal (int Index, ulong ReM, long ReE, ulong ImM, long ImE)[] RebaseSmall = new (int, ulong, long, ulong, long)[0];"
    )
    w("        internal (ulong ReM, long ReE, ulong ImM, long ImE)? Delta0;")
    w("        internal (ulong ReM, long ReE, ulong ImM, long ImE)? DeltaC;")
    w("        internal bool HasDerivative;")
    w("        internal (ulong ReM, long ReE, ulong ImM, long ImE)? D0;")
    w("        internal (ulong M, long E)? Add;")
    w("        internal int MaxIter;")
    w("        internal double EscapeRadius;")
    w("        internal int? DcExponent;")
    w("        internal int Count;")
    w("        internal (ulong Re, ulong Im) Final;")
    w("        internal (ulong Re, ulong Im, long Exponent) Derivative;")
    w("        internal int Applications;")
    w("        internal ulong Table;")
    w("    }")
    w("}")
    return "\n".join(out) + "\n"


def main() -> int:
    data = build()
    PY_OUT.write_text(render_python(data), newline="\n")
    CS_OUT.write_text(render_csharp(data), newline="\n")
    print(f"wrote {PY_OUT.relative_to(REPO_ROOT)}")
    print(f"wrote {CS_OUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
