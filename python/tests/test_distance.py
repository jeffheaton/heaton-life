"""Distance estimate (spec/fractals.md "Distance estimate"): the recurrence against a
high-precision oracle at T0 and T1 (rebased pixels included), the known limits, the
guards, and the domain."""

from __future__ import annotations

import numpy as np
import pytest

from heaton_life.core import decimal_text
from heaton_life.core.viewport import Viewport
from heaton_life.fractal import BurningShip, Julia, Mandelbrot
from heaton_life.fractal.engine import (
    distance_estimate,
    escape_time_distance,
    pixel_deltas,
    pixel_grid,
    pixel_scale,
)

gmpy2 = pytest.importorskip("gmpy2")  # the dev extra's high-precision oracle
mpc, mpfr = gmpy2.mpc, gmpy2.mpfr

SEAHORSE = ("-0.743643887037158704752191506114774", "0.131825904205311970493132056385139")
RABBIT = complex(-0.123, 0.745)


def _oracle(
    z0: mpc, c: mpc, julia: bool, max_iter: int, radius: float, ps: float
) -> tuple[int, float]:
    """(count, DE in pixels) by direct iteration at the context's precision."""
    z = z0
    d = mpc(1) if julia else mpc(0)
    r2 = mpfr(radius) ** 2
    for n in range(1, max_iter + 1):
        d = 2 * z * d if julia else 2 * z * d + 1
        z = z * z + c
        if z.real**2 + z.imag**2 > r2:
            size = abs(z)
            return n, float(size * gmpy2.log(size) / (abs(d) * ps))
        if abs(z) > 1e6:  # far past R: cannot happen before the test above fires
            break
    return -1, float("nan")


def _exact(text: str) -> mpfr:
    return mpfr(decimal_text.positional(text))


def _check_frame(
    field: Mandelbrot | Julia,
    viewport: Viewport,
    size: tuple[int, int],
    *,
    min_de: float,
    samples: int = 48,
) -> int:
    """Compare sampled escaped pixels whose counts match the oracle, and whose DE is at
    least ``min_de`` pixels (float64 error grows near the boundary as 1/DE)."""
    julia = isinstance(field, Julia)
    fields = field.fields(size, viewport, distance=True)
    assert fields.distance is not None
    ps = pixel_scale(size, viewport)
    t1 = viewport.zoom_log10 > 12.0
    bits = max(200, int(viewport.zoom_log10 * 3.33) + 200)
    checked = 0
    with gmpy2.context(gmpy2.get_context(), precision=bits):
        if t1:
            deltas = pixel_deltas(size, viewport)
            ref_re, ref_im = viewport.orbit_center
            base = mpc(_exact(ref_re), _exact(ref_im))
        else:
            grid = pixel_grid(size, viewport)
        flat = np.flatnonzero(fields.counts.ravel() > 0)
        for i in flat[:: max(1, flat.size // samples)]:
            point = (base + mpc(complex(deltas[i]))) if t1 else mpc(complex(grid[i]))
            if julia:
                count, de = _oracle(point, mpc(field.c), True, field.max_iter, 1000.0, ps)
            else:
                count, de = _oracle(mpc(0), point, False, field.max_iter, 1000.0, ps)
            got = float(fields.distance.ravel()[i])
            if count != fields.counts.ravel()[i] or de < min_de:
                continue
            assert abs(got - de) <= 1e-6 * de, (i, got, de)
            checked += 1
    return checked


def test_t0_distance_matches_the_oracle() -> None:
    assert (
        _check_frame(Mandelbrot(max_iter=500), Viewport("-0.5", "0.0", 0.0), (64, 64), min_de=1e-2)
        > 30
    )
    assert (
        _check_frame(
            Julia(c=RABBIT, max_iter=1000), Viewport("0.0", "0.0", 0.0), (64, 64), min_de=1e-2
        )
        > 30
    )


def test_t1_distance_matches_the_oracle_through_rebases() -> None:
    seahorse = Viewport(*SEAHORSE, 14.0)
    assert _check_frame(Mandelbrot(max_iter=5000), seahorse, (48, 48), min_de=1e-4) > 30
    offref = seahorse.with_reference(
        "-0.743643887037146704752191506114774", "0.131825904205303970493132056385139"
    )
    assert _check_frame(Mandelbrot(max_iter=5000), offref, (48, 48), min_de=1e-4) > 30
    # Julia at the rabbit's beta: most escaped pixels rebase onto the critical orbit.
    beta = Viewport(
        "1.27658194945592591790467276337476", "-0.47966605489732779175475867397901", 13.0
    )
    assert _check_frame(Julia(c=RABBIT, max_iter=600), beta, (32, 32), min_de=1e-4) > 30
    # Julia zoomed on its critical point: the first pre-square z is delta0 itself.
    critical = Viewport("0.0", "0.0", 13.0)
    assert _check_frame(Julia(c=1j, max_iter=600), critical, (32, 32), min_de=1e-4) > 30


def test_far_from_the_set_at_depth_is_not_a_boundary() -> None:
    """|d| ends near 1.4e-163 at zoom 170: plain squares would flush to 0 and read a false
    DE = +inf; the exponent-scaled magnitude reads 2.25e167."""
    field = Mandelbrot(max_iter=2000)
    viewport = Viewport("-0.75", "0.1", 170.0)
    fields = field.fields((16, 16), viewport, distance=True)
    assert fields.distance is not None
    assert np.all(fields.distance > 1e166) and np.all(np.isfinite(fields.distance))
    assert _check_frame(field, viewport, (16, 16), min_de=0.0, samples=8) >= 8


def test_the_tip_reads_twice_the_distance() -> None:
    """c = -2 - delta on the real axis, true distance delta: DE -> 2 delta (no factor 2)."""
    for delta in (1e-3, 1e-5, 1e-7):
        viewport = Viewport(repr(-2.0 - delta), "0.0", 3.0)
        fields = Mandelbrot(max_iter=200000).fields((1, 1), viewport, distance=True)
        assert fields.distance is not None
        ratio = fields.distance[0, 0] * pixel_scale((1, 1), viewport) / delta
        assert abs(ratio - 2.0) < 2e-3, (delta, ratio)


def test_the_pixel_scale_enters_linearly() -> None:
    """d carries ps: halving it halves every d exactly, so DE in pixels doubles exactly."""
    c = pixel_grid((32, 32), Viewport("-0.7435", "0.1314", 3.0))
    z0 = np.zeros_like(c)
    runs = [escape_time_distance(z0, c, 2000, 1000.0, (0.0, 0.0), ps) for ps in (1e-5, 5e-6)]
    (counts, final, _, (dr, di)), (counts2, final2, _, (dr2, di2)) = runs
    assert np.array_equal(counts, counts2) and np.array_equal(dr, 2.0 * dr2)
    de = distance_estimate(counts, final, dr, di)
    de2 = distance_estimate(counts2, final2, dr2, di2)
    escaped = counts > 0
    assert np.array_equal(de2[escaped], 2.0 * de[escaped])


def test_guards() -> None:
    counts = np.array([5, 5, 5, 5, 5, -1, 5, 5], dtype=np.int32)
    final = np.full(8, 1000.0 + 20.0j)
    dr = np.array([0.0, np.inf, np.nan, 1e-170, 3.0, 1.0, 1e200, 1e300])
    di = np.array([0.0, 1.0, 1.0, -2e-170, 4.0, 1.0, 0.0, -1e300])
    de = distance_estimate(counts, final, dr, di)
    m2 = 1000.0**2 + 20.0**2
    base = np.sqrt(m2) * (0.5 * np.log(m2))
    assert de[0] == np.inf  # a critical point
    assert de[1] == 0.0 and de[2] == 0.0  # overflowed or undefined: on the boundary
    assert de[3] == pytest.approx(base / (np.sqrt(5.0) * 1e-170), rel=1e-14)  # scaled, not 0
    assert de[4] == base / 5.0
    assert np.isnan(de[5])  # did not escape
    assert de[6] == base / 1e200  # scaled down past 2^400, not 0
    assert de[7] == pytest.approx(base / (np.sqrt(2.0) * 1e300), rel=1e-14)
    # An odd frame centered on 0 puts a pixel exactly on Julia's critical point.
    fields = Julia(c=0.3 + 0j, max_iter=200).fields(
        (65, 65), Viewport("0", "0", 0.0), distance=True
    )
    assert fields.distance is not None
    assert fields.distance[32, 32] == np.inf
    assert np.isfinite(np.delete(fields.distance.ravel(), 32 * 65 + 32)).all()


def test_not_escaped_is_nan_and_everything_else_agrees() -> None:
    field = Mandelbrot(max_iter=500)
    viewport = Viewport("-0.5", "0.0", 0.0)
    fields = field.fields((48, 40), viewport, smooth=True, status=True, distance=True)
    assert fields.distance is not None and fields.smooth is not None
    assert np.array_equal(np.isnan(fields.distance), fields.counts <= 0)
    counts, status = field.counts_and_status((48, 40), viewport)
    assert np.array_equal(fields.counts, counts) and np.array_equal(fields.status, status)
    assert np.array_equal(fields.smooth, field.counts_and_smooth((48, 40), viewport)[1])
    plain = field.fields((48, 40), viewport)
    assert plain.smooth is None and plain.status is None and plain.distance is None


def test_domain() -> None:
    viewport = Viewport("-0.5", "0.0", 0.0)
    for radius in (1.5, 1e65):
        with pytest.raises(ValueError, match="escape_radius"):
            Mandelbrot(escape_radius=radius).fields((4, 4), viewport, distance=True)
    with pytest.raises(ValueError, match="no distance estimate"):
        BurningShip().fields((4, 4), viewport, distance=True)
    assert not BurningShip.supports_distance and Mandelbrot.supports_distance
