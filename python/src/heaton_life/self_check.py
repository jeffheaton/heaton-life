"""Platform self-check -- spec/self-check.md.

A host running the library somewhere its test suites do not (an unusual NumPy build, a
process that has loaded a library built with -ffast-math, a frozen or embedded
interpreter) runs ``run()`` there to learn whether that runtime reproduces the bit-exact
contract. Every input and answer is embedded (``_self_check_data``, generated from the
vectors by tools/gen_self_check.py), so the check needs no files. It never raises: a
check that throws is a FAIL with the exception's type and message. Orbits are computed
outside the orbit cache, so a run leaves a host's cached orbits in place.

Each check names what its failure invalidates (``Scope``): a host gates a feature on
every check whose scope covers it -- ``passed(results, Scope.T1)`` before rendering any
frame whose tier (``fractal.tier_of``) is T1, say. ``fp-contract`` failing invalidates
every float bit-exact output.
"""

from __future__ import annotations

import dataclasses
import enum
import struct
import time
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from heaton_life import _self_check_data as data
from heaton_life.version import VERSION

__all__ = ["NAMES", "CheckResult", "Scope", "format_results", "passed", "run", "run_all"]


class Scope(enum.Flag):
    """What a check's failure invalidates."""

    SIMULATIONS = 1  # the cellular automata and the continuous families
    T0 = 2  # float64 fractal frames
    T1 = 4  # perturbation: zooms past T0_MAX_ZOOM (1e12)
    T2 = 8  # floatexp perturbation: past T1_MAX_ZOOM (1e290)
    COLOR = 16  # colormaps, the phase lookup, fractal color
    MOVIES = 32  # zoom movie plans
    ALL = 63


@dataclasses.dataclass(frozen=True)
class CheckResult:
    """One check's outcome: detail is "" when it passed."""

    name: str
    scope: Scope
    passed: bool
    detail: str
    milliseconds: float


# --- helpers --------------------------------------------------------------------------

FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 0x100000001B3
CANONICAL_NAN = 0x7FF8000000000000


class _Fail(Exception):
    """A check's mismatch, reported as its detail."""


def _fnv1a64(raw: bytes) -> int:
    value = FNV_OFFSET
    for byte in raw:
        value = ((value ^ byte) * FNV_PRIME) & 0xFFFFFFFFFFFFFFFF
    return value


def _i32_digest(values: NDArray[Any]) -> int:
    return _fnv1a64(np.ascontiguousarray(values, dtype="<i4").tobytes())


def _f64_digest(values: NDArray[Any], *, canonical_nan: bool = False) -> int:
    array = np.ascontiguousarray(values, dtype="<f8")
    words = array.view("<u8").copy()
    if canonical_nan:
        words[np.isnan(array)] = CANONICAL_NAN
    return _fnv1a64(words.tobytes())


def _bits(value: float) -> int:
    result: int = struct.unpack("<Q", struct.pack("<d", value))[0]
    return result


def _double(bits: int) -> float:
    result: float = struct.unpack("<d", struct.pack("<Q", bits))[0]
    return result


def _expect(got: object, want: object, what: str) -> None:
    if got != want:
        shown_got = f"0x{got:016X}" if isinstance(got, int) and got > 0xFFFF else repr(got)
        shown_want = f"0x{want:016X}" if isinstance(want, int) and want > 0xFFFF else repr(want)
        raise _Fail(f"{what}: {shown_got} != {shown_want}")


# --- the checks ----------------------------------------------------------------------


def _fp_contract() -> None:
    """spec/README.md "Determinism contract": binary64 with no contraction of a*b +- c,
    gradual underflow and no extended range or precision -- on Python floats, and on NumPy
    arrays (lengths 1 and 17: the ufunc loops' tail and SIMD body). Inputs come from a
    list at run time, so nothing is folded ahead of time. NumPy's error state is fixed for
    the check: the canaries underflow on purpose, and error reporting changes no result."""
    inputs = [1 + 2**-30, 1 + 2**-31, 1.0, 2.0**-1022, 0.5, 0.75, 2.0**-60, 2.0**60, 1 + 2**-52]

    def canaries(
        kind: str,
        a: Any,
        b: Any,
        one: Any,
        tiny: Any,
        half: Any,
        three_quarters: Any,
        down: Any,
        up: Any,
        nxt: Any,
    ) -> None:
        def same(x: Any, want: float) -> bool:
            return bool(np.all(x == want))

        if not same((a * a - b * b) + 2.0**-40, 2.0**-30 + 2.0**-40):
            raise _Fail(f"{kind}: a*b - c*d is contracted into a fused multiply-add")
        if not same(a * a + -one, 2.0**-29):
            raise _Fail(f"{kind}: a*b + c is contracted into a fused multiply-add")
        if not same(nxt * tiny * half, 2.0**-1023):
            raise _Fail(f"{kind}: a subnormal product is flushed to zero or misrounded (FTZ)")
        if bool(np.any(tiny * three_quarters == 0.0)):
            raise _Fail(f"{kind}: a subnormal product is flushed to zero (FTZ)")
        if not same((tiny * half) * 2.0, 2.0**-1022):
            raise _Fail(f"{kind}: a subnormal operand is read as zero (DAZ)")
        if not same(tiny * down * up, 0.0):
            raise _Fail(f"{kind}: an intermediate keeps extended exponent range (x87)")
        if not same((nxt + 2.0**-53) - one, 2.0**-51):
            raise _Fail(f"{kind}: an intermediate keeps extended precision (x87)")

    canaries("float", *inputs)
    with np.errstate(all="ignore"):
        for n in (1, 17):
            canaries(f"numpy (length {n})", *(np.full(n, x) for x in inputs))


def _numpy_fma() -> None:
    """NumPy's complex multiply fuses exactly as the reference assumes (spec/deep-zoom.md):
    real = fma(a,c,-bd), imag = fma(a,d,bc), on array lengths across its SIMD body and
    tail. The C# port mirrors this with a software fma."""
    d = data.NUMPY_FMA
    a, b, c, dd = (_double(d[k]) for k in ("a", "b", "c", "d"))
    with np.errstate(all="ignore"):
        _numpy_products(d, a, b, c, dd)


def _numpy_products(d: dict[str, Any], a: float, b: float, c: float, dd: float) -> None:
    # Operands laid out inside one buffer, so the check does not depend on where the
    # allocator happens to put arrays. Before 2.0.2, NumPy's overlap test counted an
    # output that merely touched an input as overlapping (numpy#27077) and sent it to a
    # plain C loop, fused only where the wheel's compiler contracted it; consecutive large
    # allocations often touch. Every element is checked.
    for n in d["lengths"]:
        buf = np.empty(6 * n + 6, dtype=np.complex128)
        for layout, (zo, wo, oo) in _numpy_layouts(n).items():
            z, w, out = buf[zo : zo + n], buf[wo : wo + n], buf[oo : oo + n]
            where = f"length {n}, {layout}"
            z[:] = complex(a, b)
            w[:] = complex(c, dd)
            np.multiply(z, z, out=out)
            _expect_all(out.real, d["square_re"], f"{where}: (a+bi)^2 real")
            np.multiply(z, w, out=out)
            _expect_all(out.imag, d["product_im"], f"{where}: imaginary")


def _numpy_layouts(n: int) -> dict[str, tuple[int, int, int]]:
    """Element offsets of (z, w, out) in a buffer of 6n + 6: the operands apart, and the
    output touching each input from either side (it never overlaps one)."""
    far = 3 * n + 3
    return {
        "operands apart": (0, 2 * n + 2, 4 * n + 4),
        "output right after z": (0, far, n),
        "output right before z": (n, far, 0),
        "output right after w": (far, 0, n),
        "output right before w": (0, far, far - n),
    }


def _expect_all(values: NDArray[Any], want: int, what: str) -> None:
    bits = np.ascontiguousarray(values).view(np.uint64)
    wrong = np.flatnonzero(bits != np.uint64(want))
    if wrong.size:
        k = int(wrong[0])
        _expect(int(bits[k]), want, f"{what}, element {k} of {bits.size} ({wrong.size} wrong)")


def _pcg32() -> None:
    from heaton_life.core.rng import Pcg32

    rng = Pcg32(data.PCG32["seed"], data.PCG32["seq"])
    for i, want in enumerate(data.PCG32["draws"]):
        _expect(rng.next_u32(), want, f"draw {i}")


def _pow10() -> None:
    from heaton_life.core.pow10 import pow10, pow10x

    for x_bits, want in data.POW10["table"]:
        x = _double(x_bits)
        _expect(_bits(pow10(x)), want, f"pow10({x})")
    for x_bits, mantissa, exponent in data.POW10["floatexp"]:
        x = _double(x_bits)
        m, n = pow10x(x)
        _expect((_bits(m), n), (mantissa, exponent), f"pow10x({x})")


def _center_projection() -> None:
    from heaton_life.core import decimal_text

    for i, (text, want) in enumerate(data.CENTERS):
        _expect(_bits(decimal_text.to_float(text)), want, f"case {i}")


def _turns() -> None:
    from heaton_life.core.turns import cis_turns

    for k, n, re, im in data.TURNS:
        got = cis_turns(k, n)
        _expect((_bits(got[0]), _bits(got[1])), (re, im), f"cis_turns({k}, {n})")


def _floatexp() -> None:
    from heaton_life.core import floatexp as fx

    for i, (op, am, ae, bm, be, text, bits, em, ee) in enumerate(data.FLOATEXP):
        a, b = (_double(am), ae), (_double(bm), be)
        what = f"{op} #{i}"
        if op == "add":
            got = fx.add(a, b)
        elif op == "mul":
            got = fx.mul(a, b)
        elif op == "div":
            got = fx.div(a, b)
        elif op == "compare":
            _expect(fx.compare(a, b), ee, what)
            continue
        elif op == "to_double":
            _expect(_bits(fx.to_double(a)), em, what)
            continue
        elif op == "from_fixed":
            got = fx.from_fixed(int(text), bits)
        elif op == "normalize":
            got = fx.normalize(_double(am), ae)
        else:
            raise _Fail(f"unknown operation {op}")
        _expect((_bits(got[0]), got[1]), (em, ee), what)


def _reference_orbit() -> None:
    from heaton_life.core.bignum import reference_orbit, uncached

    o = data.ORBIT
    with uncached():
        orbit = reference_orbit(
            "mandelbrot", o["center_re"], o["center_im"], o["zoom"], o["max_iter"]
        )
        _expect(len(orbit), o["max_iter"] + 1, "length")
        for index, re, im in o["samples"]:
            z = orbit[index]
            _expect((_bits(z.real), _bits(z.imag)), (re, im), f"Z[{index}]")
        for text, want in o["ties"]:
            tie = reference_orbit("mandelbrot", text, "0", o["zoom"], 1)
            _expect(_bits(tie[1].real), want, f"Z[1] at {text[:12]}...")


def _navigation() -> None:
    from heaton_life.core.viewport import Viewport
    from heaton_life.fractal.navigation import pan, zoom_at

    for n in data.NAVIGATION:
        viewport = Viewport(n["center_re"], n["center_im"], n["zoom"])
        size = (n["width"], n["height"])
        if n["op"] == "pan":
            got = pan(viewport, n["dx"], n["dy"], size, n["new_zoom"])
        else:
            got = zoom_at(viewport, n["dx"], n["dy"], size, n["new_zoom"])
        want = (n["expected_re"], n["expected_im"], n["expected_zoom"])
        if (got.center_re, got.center_im, got.zoom_log10) != want:
            raise _Fail(f"{n['op']}: the moved center differs")


def _mergelife() -> None:
    from heaton_life.ca.mergelife import MergeLife

    m = data.MERGELIFE
    state = m["seed"]
    lattice = np.empty(m["rows"] * m["cols"] * 3, dtype=np.uint8)
    for i in range(lattice.size):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        lattice[i] = state >> 24
    sim = MergeLife(
        m["rule"], size=(m["cols"], m["rows"]), init=lattice.reshape(m["rows"], m["cols"], 3)
    )
    sim.step(m["steps"])
    _expect(_fnv1a64(np.ascontiguousarray(sim.state).tobytes()), m["digest"], "digest")


def _grayscott() -> None:
    from heaton_life.rd.gray_scott import GrayScott

    g = data.GRAYSCOTT
    sim = GrayScott(
        size=(g["width"], g["height"]),
        du=g["du"],
        dv=g["dv"],
        feed=g["feed"],
        kill=g["kill"],
        dt=g["dt"],
        init="center",
    )
    sim.step(g["steps"])
    _expect(_f64_digest(np.asarray(sim.state)), g["digest"], "digest")


def _render(name: str) -> Callable[[], None]:
    def check() -> None:
        from heaton_life.core.bignum import reference_orbit, reference_orbit_x, uncached
        from heaton_life.core.viewport import Viewport
        from heaton_life.fractal import BurningShip, Julia, Mandelbrot
        from heaton_life.fractal.bla import (
            build_table,
            build_table_t2,
            frame_dc_bound,
            frame_dc_bound_exponent,
            table_words,
            table_words_x,
        )
        from heaton_life.fractal.engine import pixel_deltas, pixel_deltas_x

        r = next(case for case in data.RENDERS if case["name"] == name)
        field: Any
        if r["family"] == "mandelbrot":
            field = Mandelbrot(
                max_iter=r["max_iter"], escape_radius=r["escape_radius"], bla=r["bla"]
            )
        elif r["family"] == "julia":
            field = Julia(
                c=complex(r["c_re"], r["c_im"]),
                max_iter=r["max_iter"],
                escape_radius=r["escape_radius"],
            )
        else:
            field = BurningShip(max_iter=r["max_iter"], escape_radius=r["escape_radius"])
        viewport = Viewport(r["center_re"], r["center_im"], r["zoom"])
        size = (r["width"], r["height"])
        with uncached():
            fields = field.fields(size, viewport, bla_applications=r["bla"])
            _expect(_i32_digest(fields.counts), r["iterations"], "counts")
            if not r["bla"]:
                return
            _expect(_i32_digest(fields.bla_applications), r["applications"], "BLA applications")
            if r["zoom"] > 290.0:
                orbit_x = reference_orbit_x(
                    "mandelbrot", r["center_re"], r["center_im"], r["zoom"], r["max_iter"]
                )
                samples = orbit_x.samples[: r["max_iter"] + 1]
                small = np.zeros(samples.size, dtype=bool)
                small[orbit_x.small.index[orbit_x.small.index < samples.size]] = True
                deltas = pixel_deltas_x(size, viewport)
                k = frame_dc_bound_exponent(deltas.rm, deltas.re, deltas.im, deltas.ie)
                table_x = build_table_t2(samples, small, r["escape_radius"], k)
                entries = [int(level.rm.size) for level in table_x.levels]
                words = table_words_x(table_x)
            else:
                orbit = reference_orbit(
                    "mandelbrot", r["center_re"], r["center_im"], r["zoom"], r["max_iter"]
                )
                bound = frame_dc_bound(pixel_deltas(size, viewport))
                table = build_table(orbit, r["escape_radius"], bound)
                entries = [int(level.r.size) for level in table.levels]
                words = table_words(table)
            _expect(entries, r["entries"], "BLA table levels")
            _expect(_f64_digest(words, canonical_nan=True), r["table"], "BLA table")

    return check


def _t2_steps() -> None:
    from heaton_life.core.bignum import OrbitX, SmallSamples
    from heaton_life.fractal.bla import build_table_t2, table_words_x
    from heaton_life.fractal.perturbation_t2 import XPair, perturb_t2

    def orbit_of(samples: Sequence[tuple[int, int]], small: Sequence[Sequence[int]]) -> OrbitX:
        return OrbitX(
            np.array([complex(_double(r), _double(i)) for r, i in samples]),
            SmallSamples(
                np.array([row[0] for row in small], dtype=np.int64),
                np.array([_double(row[1]) for row in small], dtype=np.float64),
                np.array([row[2] for row in small], dtype=np.int64),
                np.array([_double(row[3]) for row in small], dtype=np.float64),
                np.array([row[4] for row in small], dtype=np.int64),
            ),
        )

    def pair(value: Sequence[int] | None) -> XPair | None:
        if value is None:
            return None
        rm, re, im, ie = value
        return XPair(
            np.array([_double(rm)]),
            np.array([re], dtype=np.int64),
            np.array([_double(im)]),
            np.array([ie], dtype=np.int64),
        )

    for c in data.T2_STEPS:
        orbit = orbit_of(c["samples"], c["small"])
        rebase = orbit_of(c["rebase_samples"], c["rebase_small"]) if c["has_rebase"] else None
        derivative = None
        if c["has_derivative"]:
            add = None if c["add"] is None else (_double(c["add"][0]), c["add"][1])
            derivative = (pair(c["d0"]), add)
        table = None
        if c["dc_exponent"] is not None:
            samples = orbit.samples[: c["max_iter"] + 1]
            small = np.zeros(samples.size, dtype=bool)
            small[orbit.small.index[orbit.small.index < samples.size]] = True
            table = build_table_t2(samples, small, c["escape_radius"], c["dc_exponent"])
        result = perturb_t2(
            orbit,
            pair(c["delta0"]),
            pair(c["delta_c"]),
            c["max_iter"],
            c["escape_radius"],
            rebase_orbit=rebase,
            derivative=derivative,  # type: ignore[arg-type]
            table=table,
        )
        name = c["name"]
        _expect(int(result.counts[0]), c["count"], f"{name}: count")
        final = (_bits(result.final[0].real), _bits(result.final[0].imag))
        _expect(final, tuple(c["final"]), f"{name}: final z")
        got_d = (_bits(float(result.dr[0])), _bits(float(result.di[0])), int(result.d_exponent[0]))
        _expect(got_d, tuple(c["derivative"]), f"{name}: derivative")
        if table is not None:
            _expect(int(result.applications[0]), c["applications"], f"{name}: applications")
            _expect(
                _f64_digest(table_words_x(table), canonical_nan=True), c["table"], f"{name}: table"
            )


def _zoom_plan() -> None:
    from heaton_life.fractal.movie import ZoomPlan, ZoomSchedule

    bits: list[int] = []
    for start, end, frames, fps, h0, e0, e1, h1 in data.ZOOM_PLANS["plans"]:
        schedule = ZoomSchedule(*(_double(v) for v in (h0, e0, e1, h1)))
        plan = ZoomPlan(_double(start), _double(end), frames, fps, schedule)
        bits.extend(_bits(z) for z in plan.zooms())
    _expect(_fnv1a64(np.array(bits, dtype="<u8").tobytes()), data.ZOOM_PLANS["digest"], "digest")


def _doubles(bits: Sequence[int]) -> NDArray[np.float64]:
    return np.array([_double(b) for b in bits], dtype=np.float64)


def _color() -> None:
    from heaton_life.fractal.coloring import PhaseParams, depth_phase
    from heaton_life.render.colormap import apply_colormap, apply_phase, get_colormap

    c = data.COLOR
    lut_name, lut_digest = c["lut"]
    _expect(_fnv1a64(get_colormap(lut_name).tobytes()), lut_digest, f"{lut_name} LUT")
    a = c["apply"]
    frame = _doubles(a["frame"]).reshape(a["height"], a["width"])
    _expect(_fnv1a64(apply_colormap(frame, a["cmap"]).tobytes()), a["digest"], "colormap")
    for lookup in c["lookups"]:
        t = _doubles(lookup["t"]).reshape(lookup["height"], lookup["width"])
        rgb = apply_phase(
            t,
            lookup["cmap"],
            wrap=lookup["wrap"],
            interior=tuple(lookup["interior"]),
            antialias=lookup["antialias"],
            dither=lookup["dither"],
            frame_index=lookup["frame_index"],
        )
        _expect(_fnv1a64(rgb.tobytes()), lookup["digest"], lookup["name"])
    p = c["phase"]
    params = PhaseParams(
        cycles_per_iteration=_double(p["cycles_per_iteration"]),
        cycles_per_octave=_double(p["cycles_per_octave"]),
        phase_offset=_double(p["phase_offset"]),
        anchor=_double(p["anchor"]),
    )
    t = depth_phase(_doubles(p["mu"]).reshape(1, -1), _double(p["zoom"]), params)
    _expect(_f64_digest(t, canonical_nan=True), p["digest"], "depth phase")


_S = Scope
_CHECKS: list[tuple[str, Scope, Callable[[], None]]] = [
    ("fp-contract", _S.ALL, _fp_contract),
    ("numpy-fma", _S.T0 | _S.T1 | _S.T2, _numpy_fma),
    ("pcg32", _S.SIMULATIONS, _pcg32),
    ("pow10", _S.T0 | _S.T1 | _S.T2, _pow10),
    ("center-projection", _S.T0 | _S.T1 | _S.T2, _center_projection),
    ("turns", _S.T0, _turns),
    ("floatexp", _S.T2, _floatexp),
    ("reference-orbit", _S.T1 | _S.T2, _reference_orbit),
    ("navigation", _S.T0 | _S.T1 | _S.T2, _navigation),
    ("mergelife-upstream", _S.SIMULATIONS, _mergelife),
    ("grayscott-100", _S.SIMULATIONS, _grayscott),
    ("mandelbrot-t0", _S.T0, _render("mandelbrot-t0")),
    ("burning-ship-t0", _S.T0, _render("burning-ship-t0")),
    ("julia-t1", _S.T1, _render("julia-t1")),
    ("burning-ship-t1", _S.T1, _render("burning-ship-t1")),
    ("mandelbrot-t1-bla", _S.T1, _render("mandelbrot-t1-bla")),
    ("t2-steps", _S.T2, _t2_steps),
    ("mandelbrot-t2-bla", _S.T2, _render("mandelbrot-t2-bla")),
    ("julia-t2", _S.T2, _render("julia-t2")),
    ("zoom-plan", _S.MOVIES, _zoom_plan),
    ("color", _S.COLOR, _color),
]

NAMES: tuple[str, ...] = tuple(name for name, _, _ in _CHECKS)


def run_all() -> list[CheckResult]:
    """Every check, in order (fp-contract first, so the first FAIL is the root cause)."""
    results = []
    for name, scope, check in _CHECKS:
        start = time.perf_counter()
        try:
            check()
            ok, detail = True, ""
        except _Fail as fail:
            ok, detail = False, str(fail)
        except Exception as exc:  # noqa: BLE001 -- a check reports, it never raises
            cause = exc.__cause__ or exc
            ok, detail = False, f"{type(exc).__name__}: {cause}"
        milliseconds = (time.perf_counter() - start) * 1000.0
        results.append(CheckResult(name, scope, ok, detail, milliseconds))
    return results


def format_results(results: Sequence[CheckResult]) -> str:
    """A report: a header with the library version and total time, then a line per check."""
    total = sum(r.milliseconds for r in results)
    lines = [f"heaton-life {VERSION} self-check: {len(results)} checks, {total:.1f} ms"]
    for r in results:
        line = f"  {'PASS' if r.passed else 'FAIL'}  {r.name} ({r.milliseconds:.1f} ms)"
        lines.append(line if r.passed else f"{line} -- {r.detail}")
    return "\n".join(lines)


def passed(results: Sequence[CheckResult], scope: Scope) -> bool:
    """True when every check whose scope overlaps ``scope`` ran and passed: a check
    missing from ``results`` fails closed, and so does any FAIL for it (results from
    several runs may be passed together)."""
    for name, check_scope, _ in _CHECKS:
        if check_scope & scope:
            mine = [r for r in results if r.name == name]
            if not mine or not all(r.passed for r in mine):
                return False
    return True


def run() -> tuple[bool, str]:
    """Run every check: (all passed, the report)."""
    results = run_all()
    return all(r.passed for r in results), format_results(results)
