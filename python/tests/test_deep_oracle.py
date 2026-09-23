"""The deep-zoom oracle ladder: T1 against direct arbitrary-precision iteration.

Vectors pin Python and C# to each other; they cannot say whether both are wrong the
same way. These tests pin T1 to the truth, on fixtures chosen because they exercise
what shallow views never do -- reference orbits passing near 0 and pixels that
rebase -- and each asserts that premise before trusting its comparison (the lesson
of the Julia rebase bug, which survived because the only deep Julia test used a view
where no rebase fired).

The oracle iterates every pixel directly in fixed point, the pixel formed exactly as
T1 forms it (the decimal center plus the float64 offset of spec/fractals.md "Pixel
mapping"), and is run at two precisions to prove it has converged. T1 must match it
exactly on every stable pixel -- one whose true count survives moving its float64
offset 256 ulps along either axis. T1 rounds as it iterates, which amounts to a few
ulps of the offset; a pixel that flips inside 256 is chaotic at that scale, and no
float64 method can be held to it. (Heaton Fractal's compareStable excludes such pixels
by their 3x3 spread instead; on integer counts of small frames that heuristic excludes
nearly everything.)

Each frame is centered off a nucleus, so the reference is not the minibrot's -- where
classic perturbation glitches (the p998 minibrot lies inside its frame, p1959's just
past the left edge). The asserted premises, not the geometry, make each case: a test
double without rebasing must get at least a fifth of the stable pixels wrong.
Centered on the nucleus, the same frames render correctly with no rebasing at all.

Fixtures come from Heaton Fractal (github.com/jeffheaton, ~/projects/mandelbrot):
Dinkydau's "11 Dimensions" with its four fixed-point answers at 1e160, the period-998
nucleus (Tests/.../Fixtures/nucleus-period998.kfr), and the period-1,959 nucleus its
automated search found (hunts/r7-a.jsonl, round 0).
"""

from __future__ import annotations

import decimal
import math
import sys
from pathlib import Path

import numpy as np
import pytest

from heaton_life.core.bignum import from_double, parse_fixed, reference_orbit, working_bits
from heaton_life.core.viewport import Viewport
from heaton_life.fractal.engine import pixel_offsets
from heaton_life.fractal.perturbation import perturb_z2

gmpy2 = pytest.importorskip("gmpy2")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from gen_vectors import ELEVEN_DIMENSIONS_IM, ELEVEN_DIMENSIONS_RE

NUCLEUS_P998 = (
    "-0.7436438870371588707780645434936425750476",
    "0.1318259042053122928210973548747672652630",
)
NUCLEUS_P998_ZOOM = math.log10(1.59738e15)  # the .kfr's Zoom, a square frame
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


def _direct_counts(
    vp: Viewport, offsets: np.ndarray, max_iter: int, radius: float, extra_bits: int
) -> np.ndarray:
    """Escape counts by direct fixed-point iteration: no perturbation, no float64."""
    bits = working_bits(vp.center_re, vp.center_im, vp.zoom_log10) + extra_bits
    mpz = gmpy2.mpz
    center_re = mpz(parse_fixed(vp.center_re, bits))
    center_im = mpz(parse_fixed(vp.center_im, bits))
    half = mpz(1) << (bits - 1)
    bound = mpz(int(radius * radius)) << (2 * bits)
    counts = np.full(offsets.size, -1, dtype=np.int32)
    for k, offset in enumerate(offsets):
        cr = center_re + from_double(offset.real, bits)
        ci = center_im + from_double(offset.imag, bits)
        zr = zi = mpz(0)
        for it in range(1, max_iter + 1):
            zr, zi = ((zr * zr - zi * zi + half) >> bits) + cr, ((2 * zr * zi + half) >> bits) + ci
            if zr * zr + zi * zi > bound:
                counts[k] = it
                break
    return counts


def _truth(vp: Viewport, offsets: np.ndarray, max_iter: int, radius: float) -> np.ndarray:
    coarse = _direct_counts(vp, offsets, max_iter, radius, 64)
    fine = _direct_counts(vp, offsets, max_iter, radius, 192)
    assert np.array_equal(coarse, fine), "the oracle itself has not converged"
    return fine


def _t1_with_premise(
    vp: Viewport, offsets: np.ndarray, max_iter: int, radius: float, min_rebased: float
) -> np.ndarray:
    """T1 counts, after proving the frame exercises rebasing at all.

    Poisoning the rebase orbit with NaN sends every rebased pixel to -1, so the share
    of pixels it changes is the share that rebased.
    """
    orbit = reference_orbit("mandelbrot", vp.center_re, vp.center_im, vp.zoom_log10, max_iter)
    zeros = np.zeros_like(offsets)
    counts, _ = perturb_z2(orbit, zeros, offsets, max_iter, radius)
    # Poisoned pixels never escape, so stop at the last real escape: nothing past it
    # can change the comparison.
    cap = int(counts.max()) if (counts > 0).all() else max_iter
    poisoned, _ = perturb_z2(
        orbit, zeros, offsets, cap, radius, rebase_orbit=np.full_like(orbit, np.nan)
    )
    assert (poisoned != counts).mean() >= min_rebased, "premise: rebases must fire here"
    return counts


def _stable(
    vp: Viewport, offsets: np.ndarray, truth: np.ndarray, max_iter: int, radius: float
) -> np.ndarray:
    """Pixels whose true count survives moving the offset 256 ulps along either axis."""
    stable = np.ones(offsets.size, dtype=bool)
    for toward in (np.inf, -np.inf):
        re, im = offsets.real.copy(), offsets.imag.copy()
        for _ in range(256):
            re, im = np.nextafter(re, toward), np.nextafter(im, toward)
        stable &= _direct_counts(vp, re + 1j * offsets.imag, max_iter, radius, 64) == truth
        stable &= _direct_counts(vp, offsets.real + 1j * im, max_iter, radius, 64) == truth
    return stable


def _without_rebasing(
    orbit: np.ndarray, offsets: np.ndarray, max_iter: int, radius: float
) -> np.ndarray:
    """Test double: perturb_z2's Mandelbrot recurrence with rebasing removed."""
    counts = np.full(offsets.size, -1, dtype=np.int32)
    dz = np.zeros_like(offsets)
    dc = offsets.copy()
    m = np.zeros(offsets.size, dtype=np.int64)
    idx = np.arange(offsets.size)
    last = len(orbit) - 1
    for it in range(1, max_iter + 1):
        dz = (2.0 * orbit[m] + dz) * dz + dc
        m = np.minimum(m + 1, last)
        z = orbit[m] + dz
        escaped = z.real * z.real + z.imag * z.imag > radius * radius
        counts[idx[escaped]] = it
        keep = ~escaped
        dz, dc, m, idx = dz[keep], dc[keep], m[keep], idx[keep]
        if idx.size == 0:
            break
    return counts


def _shifted(center: tuple[str, str], zoom: float, fx: float, fy: float) -> tuple[str, str]:
    """The center moved (fx, fy) frame widths, exactly in decimal."""
    with decimal.localcontext() as ctx:
        ctx.prec = 80
        span = decimal.Decimal(4) * decimal.Decimal(10) ** decimal.Decimal(repr(-zoom))
        return (
            str(decimal.Decimal(center[0]) + span * decimal.Decimal(repr(fx))),
            str(decimal.Decimal(center[1]) + span * decimal.Decimal(repr(fy))),
        )


@pytest.mark.slow
def test_eleven_dimensions_matches_heaton_fractal_known_answers() -> None:
    """Four pixels at 1e160, where the reference passes within 1e-78 of the origin.

    Heaton Fractal frames by half-height 1.0, so its depth 160 on a 64x64 square is
    zoom 160 + log10(2) here; with its escape radius of 256 both projects must give
    the counts it computed in fixed point (DeepReferenceTests.swift).
    """
    vp = Viewport(ELEVEN_DIMENSIONS_RE, ELEVEN_DIMENSIONS_IM, 160.0 + math.log10(2.0))
    offsets = pixel_offsets((64, 64), vp)
    pixels = [(2, 2), (32, 32), (61, 61), (2, 61)]  # (row, col); theirs are (x, y)
    samples = np.array([offsets[row * 64 + col] for row, col in pixels])

    orbit = reference_orbit("mandelbrot", vp.center_re, vp.center_im, vp.zoom_log10, 1_100_000)
    assert np.min(np.abs(orbit[1:])) < 1e-70, "premise: a near-origin pass"
    counts = _t1_with_premise(vp, samples, 1_100_000, 256.0, min_rebased=1.0)

    expected = [72877, 73667, 72877, 73581]
    assert list(_truth(vp, samples, 1_100_000, 256.0)) == expected
    assert list(counts) == expected


@pytest.mark.slow
@pytest.mark.parametrize(
    ("name", "nucleus", "zoom", "shift", "max_iter"),
    [
        ("p998", NUCLEUS_P998, NUCLEUS_P998_ZOOM, (0.45, -0.2), 30_000),
        ("p1959", NUCLEUS_P1959, 42.7, (0.7, 0.0), 20_000),
    ],
)
def test_t1_matches_direct_iteration_off_nucleus(
    name: str,
    nucleus: tuple[str, str],
    zoom: float,
    shift: tuple[float, float],
    max_iter: int,
) -> None:
    size = 12
    vp = Viewport(*_shifted(nucleus, zoom, *shift), zoom)
    offsets = pixel_offsets((size, size), vp)
    orbit = reference_orbit("mandelbrot", vp.center_re, vp.center_im, vp.zoom_log10, max_iter)

    counts = _t1_with_premise(vp, offsets, max_iter, 1000.0, min_rebased=0.3)
    truth = _truth(vp, offsets, max_iter, 1000.0)
    stable = _stable(vp, offsets, truth, max_iter, 1000.0)
    assert stable.mean() >= 0.85, f"{name}: too few stable pixels to judge"

    glitched = _without_rebasing(orbit, offsets, max_iter, 1000.0)
    assert (glitched[stable] != truth[stable]).mean() >= 0.2, (
        f"{name}: premise: without rebasing this frame must glitch"
    )
    wrong = int((counts[stable] != truth[stable]).sum())
    assert wrong == 0, f"{name}: {wrong} of {int(stable.sum())} stable pixels disagree"
