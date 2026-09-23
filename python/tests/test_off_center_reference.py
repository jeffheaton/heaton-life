"""The off-center reference (spec/deep-zoom.md "Off-center reference").

A T1 frame may iterate a reference R other than its center C, offsetting every pixel
by round64(C - R): a host pans on one cached orbit. Without a reference nothing
changes; T0 ignores it; and an off-center frame is as faithful to direct iteration as
the centered one. The vectors pin Python and C# to each other; these pin the parts
they cannot see.
"""

from __future__ import annotations

import decimal
import random
import struct
from collections.abc import Callable
from fractions import Fraction

import numpy as np
import pytest

from heaton_life.core import bignum, decimal_text
from heaton_life.core.bignum import from_double, parse_fixed, working_bits
from heaton_life.core.viewport import Viewport
from heaton_life.fractal import BurningShip, Julia, Mandelbrot
from heaton_life.fractal.engine import (
    pixel_deltas,
    pixel_offsets,
    pixel_scale,
    reference_offset,
    reference_on_screen,
)

SEAHORSE = ("-0.743643887037158704752191506114774", "0.131825904205311970493132056385139")
RABBIT = complex(-0.123, 0.745)
RABBIT_BETA = ("1.27658194945592591790467276337476", "-0.47966605489732779175475867397901")
SHIP = ("0.403269293475576420989278613990", "-0.595275727121703516488710194270")

# round64(minuend - subtrahend) as IEEE-754 bit patterns. C#'s OffCenterReferenceTests
# asserts the same table against DecimalText.Difference.
DIFFERENCES = [
    ("0.10", "0.1", 0x0000000000000000),  # an exact zero is +0.0 ...
    ("-0", "0", 0x0000000000000000),
    ("  -2.5e+3 ", "-2500.000", 0x0000000000000000),
    (SEAHORSE[0], "-0.743643887037146704752191506114774", 0xBD0B05876E5B0120),
    # Both round to the double 0.1; their difference does not.
    ("0.1000000000000000055511151231257827", "0.1", 0x3C5999999999999A),
    ("1." + "0" * 300 + "1", "1", 0x017124E63593F5E1),
    ("1.5e-14", "5E-15", 0x3D06849B86A12B9B),
    ("9007199254740993", "0", 0x4340000000000000),  # ties to even: down ...
    ("9007199254740995", "0", 0x4340000000000002),  # ... and up
    ("3e-324", "0", 0x0000000000000001),  # the least subnormal
    ("0", "2e-324", 0x8000000000000000),  # ... a nonzero underflow keeps its sign
    ("1e309", "0", 0x7FF0000000000000),
    ("-1e400", "1e400", 0xFFF0000000000000),
    ("1e-100000", "-1e-100000", 0x0000000000000000),
]


def _bits(value: float) -> int:
    return int(struct.unpack("<Q", struct.pack("<d", value))[0])


def _moved(center: str, frames: str, zoom: int) -> str:
    """A center component moved ``frames`` frame widths (4 * 10^-zoom), exactly."""
    value = Fraction(center) + Fraction(frames) * 4 * Fraction(10) ** -zoom
    with decimal.localcontext() as ctx:
        ctx.prec = 100
        exact = decimal.Decimal(value.numerator) / decimal.Decimal(value.denominator)
    assert Fraction(exact) == value
    return str(exact)


@pytest.mark.parametrize(("minuend", "subtrahend", "expected"), DIFFERENCES)
def test_difference_is_the_exact_difference_rounded_once(
    minuend: str, subtrahend: str, expected: int
) -> None:
    assert _bits(decimal_text.difference(minuend, subtrahend)) == expected


def test_difference_matches_exact_rationals() -> None:
    rng = random.Random(5)

    def digits(n: int) -> str:
        return "".join(rng.choice("0123456789") for _ in range(n))

    for _ in range(3000):
        mantissa = digits(rng.randint(1, 60))
        point = rng.randint(0, len(mantissa))
        exponent = rng.randint(-340, 320)
        if rng.random() < 0.5:  # near-cancellation: the same number with a new tail
            tail = rng.randint(0, len(mantissa))
            other = mantissa[:tail] + digits(len(mantissa) - tail)
            other_point, other_exponent = point, exponent
        else:
            other = digits(rng.randint(1, 60))
            other_point = rng.randint(0, len(other))
            other_exponent = rng.randint(-340, 320)
        a = f"{rng.choice(['', '-'])}{mantissa[:point]}.{mantissa[point:]}e{exponent}"
        b = f"{rng.choice(['', '-'])}{other[:other_point]}.{other[other_point:]}e{other_exponent}"
        exact = Fraction(a) - Fraction(b)
        got = decimal_text.difference(a, b)
        if exact == 0:
            assert _bits(got) == 0, (a, b)
            continue
        try:
            want = float(exact)  # int / int: rounded once, to even
        except OverflowError:
            want = np.inf if exact > 0 else -np.inf
        assert _bits(got) == _bits(want), (a, b)


def test_viewport_carries_a_reference_both_or_neither() -> None:
    centered = Viewport(*SEAHORSE, 14.0)
    assert not centered.has_reference
    assert centered.orbit_center == SEAHORSE
    assert "reference_re" not in centered.to_dict()

    vp = centered.with_reference("-0.7436438870371467", 0)  # ints coerce, as for centers
    assert vp.has_reference and vp.orbit_center == ("-0.7436438870371467", "0")
    assert Viewport.from_dict(vp.to_dict()) == vp
    assert Viewport.from_json(vp.to_json()) == vp
    assert vp.with_reference(None, None) == centered
    assert vp != centered

    with pytest.raises(ValueError, match="both"):
        Viewport(*SEAHORSE, 14.0, reference_re="0.1")
    with pytest.raises(ValueError, match="both"):
        Viewport.from_dict({**centered.to_dict(), "reference_im": "0.1"})
    with pytest.raises(ValueError):
        centered.with_reference("NaN", "0")
    with pytest.raises(TypeError, match="float"):
        centered.with_reference(-0.74, "0")  # type: ignore[arg-type]


def test_the_offset_is_exact_not_a_difference_of_doubles() -> None:
    # Centers that agree to 20 places: their float64 projections are the same double.
    reference = ("-0.74364388703715870475" + "3", "0.13182590420531197049" + "1")
    vp = Viewport(*SEAHORSE, 20.0, *reference)
    d = reference_offset(vp)
    assert d.real == float(Fraction(SEAHORSE[0]) - Fraction(reference[0]))
    assert d.imag == float(Fraction(SEAHORSE[1]) - Fraction(reference[1]))
    assert float(SEAHORSE[0]) - float(reference[0]) == 0.0  # premise: doubles lose it all
    assert reference_offset(Viewport(*SEAHORSE, 20.0)) == 0j


def test_pixel_deltas_are_the_offset_plus_the_centered_offsets() -> None:
    """fl(d + offset), one add per component, on a non-square frame."""
    vp = Viewport(*SEAHORSE, 14.0, "-0.743643887037146704752191506114774", "0.1318259042053")
    d = reference_offset(vp)
    assert d.real != 0.0 and d.imag != 0.0
    offsets = pixel_offsets((48, 32), vp)
    deltas = pixel_deltas((48, 32), vp)
    assert np.array_equal(deltas.real, d.real + offsets.real)
    assert np.array_equal(deltas.imag, d.imag + offsets.imag)
    centered = Viewport(*SEAHORSE, 14.0)
    assert np.array_equal(pixel_deltas((48, 32), centered), pixel_offsets((48, 32), centered))


# The deltas of a 16x9 frame of the Seahorse at 1e14 with its reference (0.3, -0.2)
# frames away: row 0's real parts, column 0's imaginary parts. C#'s
# OffCenterReferenceTests asserts the same bits against FractalEngine.DeltaRe/DeltaIm.
# The offref vectors cannot see a last-bit change in a delta (their Julia and Burning
# Ship frames are well conditioned); this table can.
DELTA_REFERENCE = ("-0.743643887037146704752191506114774", "0.131825904205303970493132056385139")
DELTA_FRAME = Viewport(*SEAHORSE, 14.0, *DELTA_REFERENCE)
DELTAS_RE = [
    0xBD214F8AC2B24CB8, 0xBD1FCE82149073FE, 0xBD1CFDEEA3BC4E8A, 0xBD1A2D5B32E82917,
    0xBD175CC7C21403A4, 0xBD148C34513FDE30, 0xBD11BBA0E06BB8BD, 0xBD0DD61ADF2F2693,
    0xBD0834F3FD86DBAD, 0xBD0293CD1BDE90C6, 0xBCF9E54C746C8BBE, 0xBCED45FD6237EBE0,
    0xBCCB05876E5B0120, 0x3CDF86735614D6A8, 0x3CF323EA98D5CB78, 0x3CFE66385C266144,
]  # fmt: skip
DELTAS_IM = [
    0x3D14442592C440D8, 0x3D11739221F01B65, 0x3D0D45FD6237EBE4, 0x3D07A4D6808FA0FD,
    0x3D0203AF9EE75616, 0x3CF8C5117A7E165E, 0x3CEB05876E5B0122, 0x3CC203AF9EE75620,
    0xBCE203AF9EE75614,
]  # fmt: skip


def test_pixel_deltas_match_the_shared_table() -> None:
    deltas = pixel_deltas((16, 9), DELTA_FRAME).reshape(9, 16)
    assert [_bits(v) for v in deltas[0].real] == DELTAS_RE
    assert [_bits(v) for v in deltas[:, 0].imag] == DELTAS_IM
    assert (deltas.real == deltas[:1].real).all() and (deltas.imag == deltas[:, :1].imag).all()

    # Premise: the table tells plausible alternatives apart -- a rescaled form, one
    # rounding of the exact sum, and the difference of the rounded centers.
    ps = pixel_scale((16, 9), DELTA_FRAME)
    d = reference_offset(DELTA_FRAME)
    k = np.arange(16) + 0.5 - 8.0
    exact = Fraction(SEAHORSE[0]) - Fraction(DELTA_REFERENCE[0])
    assert [_bits(v) for v in (d.real / ps + k) * ps] != DELTAS_RE
    assert [_bits(float(exact + Fraction(float(v * ps)))) for v in k] != DELTAS_RE
    rounded = float(SEAHORSE[0]) - float(DELTA_REFERENCE[0])
    assert [_bits(rounded + v * ps) for v in k] != DELTAS_RE


# An overflowing offset is absurd but defined: d = +-inf enters each component apart
# and IEEE takes it from there (the reason pixel_deltas never forms xs + 1j * ys, and
# C#'s software fma returns an infinite addend). C# asserts the same counts.
NON_FINITE = [
    (("0", "1e400", "0", "0"), [1] * 6, [1, -1, 1, 1, -1, 1], [1] * 6),
    (("1e400", "0", "0", "0"), [1] * 6, [1] * 6, [1] * 6),
    (("0", "1e308", "0", "-1e308"), [1] * 6, [-1] * 6, [1] * 6),  # d = 2e308 overflows
    (("2e154", "2e154", "0", "0"), [1] * 6, [1] * 6, [1] * 6),  # 2*dz*dz overflows in the fma
]


@pytest.mark.parametrize(("frame", "mandelbrot", "julia", "burning_ship"), NON_FINITE)
def test_non_finite_offsets_follow_ieee(
    frame: tuple[str, str, str, str],
    mandelbrot: list[int],
    julia: list[int],
    burning_ship: list[int],
) -> None:
    vp = Viewport(frame[0], frame[1], 13.0, frame[2], frame[3])
    with np.errstate(all="ignore"):
        assert list(Mandelbrot(max_iter=50).iterations((3, 2), vp).ravel()) == mandelbrot
        assert list(Julia(c=RABBIT, max_iter=50).iterations((3, 2), vp).ravel()) == julia
        assert list(BurningShip(max_iter=50).iterations((3, 2), vp).ravel()) == burning_ship


Field = Mandelbrot | Julia | BurningShip
FAMILIES: list[tuple[str, Callable[[], Field], tuple[str, str], float]] = [
    ("mandelbrot", lambda: Mandelbrot(max_iter=5000), SEAHORSE, 14.0),
    ("julia", lambda: Julia(c=RABBIT, max_iter=600), RABBIT_BETA, 13.0),
    ("burning_ship", lambda: BurningShip(max_iter=1000), SHIP, 13.0),
]


@pytest.mark.parametrize(("name", "make", "center", "zoom"), FAMILIES, ids=[f[0] for f in FAMILIES])
def test_a_reference_at_the_center_changes_nothing(
    name: str, make: Callable[[], Field], center: tuple[str, str], zoom: float
) -> None:
    """R = C (even spelled differently) is the centered frame, counts and smooth values."""
    field = make()
    centered = Viewport(*center, zoom)
    for reference in (center, (center[0] + "000", center[1] + "0e0")):
        vp = centered.with_reference(*reference)
        assert reference_offset(vp) == 0j
        counts, mu = field.counts_and_smooth((24, 16), vp)
        want_counts, want_mu = field.counts_and_smooth((24, 16), centered)
        assert np.array_equal(counts, want_counts), name
        assert np.array_equal(mu, want_mu), name
    assert (want_counts > 0).any() and (want_counts < 0).any(), "premise: a real frame"


@pytest.mark.parametrize(("name", "make", "center", "zoom"), FAMILIES, ids=[f[0] for f in FAMILIES])
def test_t0_ignores_the_reference(
    name: str, make: Callable[[], Field], center: tuple[str, str], zoom: float
) -> None:
    field = make()
    shallow = Viewport(*center, 6.0)
    far = shallow.with_reference("0.25", "-0.5")
    assert np.array_equal(field.iterations((24, 16), far), field.iterations((24, 16), shallow))


def test_panning_with_a_kept_reference_reuses_the_orbit(monkeypatch: pytest.MonkeyPatch) -> None:
    """The orbit cache is keyed on the reference, so a pan that keeps it runs no orbit."""
    calls: list[str] = []
    fresh, resume = bignum._fresh, bignum._resume
    monkeypatch.setattr(bignum, "_fresh", lambda *a: calls.append("fresh") or fresh(*a))
    monkeypatch.setattr(bignum, "_resume", lambda *a: calls.append("resume") or resume(*a))
    field = Mandelbrot(max_iter=3000)
    bignum.clear_cache()
    for step in range(4):  # a tenth of a frame per step, the reference kept throughout
        vp = Viewport(_moved(SEAHORSE[0], f"{step}/10", 20), SEAHORSE[1], 20.0, *SEAHORSE)
        assert reference_on_screen((32, 32), vp)
        field.iterations((32, 32), vp)
    assert calls == ["fresh"]

    calls.clear()
    bignum.clear_cache()
    for step in range(2):  # premise: centered, every pan is a new orbit
        field.iterations(
            (32, 32), Viewport(_moved(SEAHORSE[0], f"{step}/10", 20), SEAHORSE[1], 20.0)
        )
    assert calls == ["fresh", "fresh"]
    bignum.clear_cache()


@pytest.mark.parametrize(("name", "make", "center", "zoom"), FAMILIES, ids=[f[0] for f in FAMILIES])
def test_each_family_iterates_the_references_orbit(
    name: str,
    make: Callable[[], Field],
    center: tuple[str, str],
    zoom: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The orbit a T1 frame computes is R's, at R's precision (and Julia's critical
    orbit): the Julia and Burning Ship offref vectors equal their centered frames, so
    only this catches a family that ignores the reference."""
    calls: list[tuple[object, ...]] = []
    fresh = bignum._fresh
    monkeypatch.setattr(bignum, "_fresh", lambda *a: calls.append(a[:4]) or fresh(*a))
    reference = (_moved(center[0], "0.3", int(zoom)), _moved(center[1], "-0.2", int(zoom)))
    bignum.clear_cache()
    make().iterations((16, 16), Viewport(*center, zoom, *reference))
    expected: list[tuple[object, ...]] = [(name, *reference, working_bits(*reference, zoom))]
    if name == "julia":
        expected.append(("julia", "0", "0", working_bits("0", "0", zoom)))
    assert calls == expected
    bignum.clear_cache()


def test_reference_on_screen_measures_width_and_height() -> None:
    vp = Viewport(*SEAHORSE, 14.0)
    assert reference_on_screen((48, 32), vp)  # no reference: the center is on screen

    def at(fx: str, fy: str) -> Viewport:  # fractions of the frame's width
        return vp.with_reference(_moved(SEAHORSE[0], fx, 14), _moved(SEAHORSE[1], fy, 14))

    assert reference_on_screen((48, 32), at("0.3", "-0.2"))
    assert reference_on_screen((48, 32), at("-0.49", "0.33"))
    assert not reference_on_screen((48, 32), at("0.51", "0"))
    assert not reference_on_screen((48, 32), at("0", "0.34"))  # height is 2/3 of the width
    assert reference_on_screen((32, 48), at("0", "0.34"))
    assert not reference_on_screen((48, 32), vp.with_reference("1e400", "0"))  # d = inf
    assert pixel_scale((48, 32), vp) == pixel_scale((48, 48), vp)  # framing is by width


def _direct(
    kind: str, vp: Viewport, size: tuple[int, int], max_iter: int, extra: int
) -> np.ndarray:
    """Escape counts by direct fixed-point iteration of each pixel as T1 forms it:
    the reference's exact value plus the pixel's float64 delta."""
    gmpy2 = pytest.importorskip("gmpy2")
    mpz = gmpy2.mpz
    bits = working_bits(*vp.orbit_center, vp.zoom_log10) + extra
    base_re, base_im = (mpz(parse_fixed(part, bits)) for part in vp.orbit_center)
    half = mpz(1) << (bits - 1)
    bound = mpz(1000 * 1000) << (2 * bits)
    c_re, c_im = mpz(from_double(RABBIT.real, bits)), mpz(from_double(RABBIT.imag, bits))
    counts = np.full(size[0] * size[1], -1, dtype=np.int32)
    for k, delta in enumerate(pixel_deltas(size, vp)):
        pr, pi = base_re + from_double(delta.real, bits), base_im + from_double(delta.imag, bits)
        if kind == "julia":
            zr, zi, cr, ci = pr, pi, c_re, c_im
        else:
            zr, zi, cr, ci = mpz(0), mpz(0), pr, pi
        for it in range(1, max_iter + 1):
            if kind == "burning_ship":
                cross = 2 * abs(zr) * abs(zi)
            else:
                cross = 2 * zr * zi
            zr, zi = ((zr * zr - zi * zi + half) >> bits) + cr, ((cross + half) >> bits) + ci
            if zr * zr + zi * zi > bound:
                counts[k] = it
                break
    return counts.reshape(size[1], size[0])


@pytest.mark.parametrize(
    ("kind", "field", "center", "reference", "zoom"),
    [
        (
            "julia",
            Julia(c=RABBIT, max_iter=600),
            RABBIT_BETA,
            ("1.27658194945578591790467276337476", "-0.47966605489722779175475867397901"),
            13.0,
        ),
        (
            "burning_ship",
            BurningShip(max_iter=1000),
            SHIP,
            ("0.403269293475696420989278613990", "-0.595275727121583516488710194270"),
            13.0,
        ),
    ],
    ids=["julia", "burning_ship"],
)
def test_off_center_frames_match_direct_iteration(
    kind: str,
    field: Julia | BurningShip,
    center: tuple[str, str],
    reference: tuple[str, str],
    zoom: float,
) -> None:
    """The julia and burning-ship offref vectors' frames, every pixel against the truth
    (the oracle run at two precisions to show it has converged). The oracle is sharp
    enough to matter: the truth of either frame moved half a pixel disagrees with
    these counts on 13% and 34% of pixels."""
    vp = Viewport(*center, zoom, *reference)
    size = (32, 32)
    truth = _direct(kind, vp, size, field.max_iter, 64)
    assert np.array_equal(truth, _direct(kind, vp, size, field.max_iter, 192))
    counts = field.iterations(size, vp)
    assert (counts > 0).any() and (counts < 0).any(), "premise: a real frame"
    assert np.array_equal(counts, truth)
