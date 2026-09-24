"""BLA (spec/deep-zoom.md "BLA"): the magnitude, the table's invariants, the loop against
a scalar transcription of the spec, the same pixels from a longer orbit, BLA-off
equality where nothing engages, and the counts against direct iteration."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

from heaton_life.core.bignum import reference_orbit
from heaton_life.core.viewport import Viewport
from heaton_life.fractal import Julia, Mandelbrot
from heaton_life.fractal.bla import (
    EPSILON,
    STRIDE,
    build_table,
    frame_dc_bound,
    mag,
    perturb_z2_bla,
)
from heaton_life.fractal.engine import pixel_deltas, pixel_scale
from heaton_life.fractal.perturbation import perturb_z2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from gen_vectors import (
    ELEVEN_DIMENSIONS_IM,
    ELEVEN_DIMENSIONS_RE,
    NUCLEUS_P16,
    NUCLEUS_P1959,
    _shifted,
)

ELEVEN = (ELEVEN_DIMENSIONS_RE, ELEVEN_DIMENSIONS_IM)


def _scalar(
    orbit: np.ndarray, dc: np.ndarray, max_iter: int, radius: float, table: object
) -> tuple[list[int], list[int]]:
    """The per-pixel loop exactly as spec/deep-zoom.md "BLA" writes it, one pixel at a
    time (the C# port's shape), for the vectorized one to match."""
    levels = table.levels  # type: ignore[attr-defined]
    sizes = [level.r.size for level in levels]
    last = len(orbit) - 1
    counts, applied = [], []
    for c in dc:
        dz = np.zeros(1, dtype=np.complex128)
        cc = np.array([c])
        m = n = a = 0
        count = -1
        while n < max_iter:
            chosen = -1
            if sizes and m % STRIDE == 0 and m // STRIDE < sizes[0]:
                dm = float(mag(dz.real, dz.imag)[0])
                for index, level in enumerate(levels):
                    span = STRIDE << index
                    if m % span or m // span >= sizes[index] or n + span > max_iter:
                        break
                    if not dm < level.r[m // span]:
                        break
                    chosen = index
            if chosen >= 0:
                span = STRIDE << chosen
                e = m // span
                level = levels[chosen]
                ar, ai, br, bi = level.ar[e], level.ai[e], level.br[e], level.bi[e]
                zr, zi = float(dz.real[0]), float(dz.imag[0])
                new = complex((ar * zr - ai * zi) + (br * c.real - bi * c.imag), 0.0)
                dz = np.array([new])
                dz.imag[0] = (ar * zi + ai * zr) + (br * c.imag + bi * c.real)
                m += span
                n += span
                a += 1
            else:
                dz = (2.0 * orbit[m : m + 1] + dz) * dz + cc
                m = min(m + 1, last)
                n += 1
            z = orbit[m : m + 1] + dz
            zabs2 = float(z.real[0] * z.real[0] + z.imag[0] * z.imag[0])
            if zabs2 > radius * radius:
                count = n
                break
            if zabs2 < float(dz.real[0] * dz.real[0] + dz.imag[0] * dz.imag[0]):
                dz = z.copy()
                m = 0
        counts.append(count)
        applied.append(a)
    return counts, applied


def _frame(viewport: Viewport, size: tuple[int, int], max_iter: int) -> tuple[np.ndarray, ...]:
    orbit = reference_orbit("mandelbrot", *viewport.orbit_center, viewport.zoom_log10, max_iter)
    dc = pixel_deltas(size, viewport)
    return orbit, dc


def test_mag() -> None:
    x = np.array([0.0, 3.0, 3e-300, 3e300, np.inf, np.nan, -0.0, 1e-320, 5e-310])
    y = np.array([0.0, 4.0, 4e-300, 4e300, 1.0, 1.0, -0.0, 0.0, 5e-310])
    got = mag(x, y)
    assert got[0] == 0.0 and got[1] == 5.0 and got[6] == 0.0
    assert got[2] == pytest.approx(5e-300, rel=1e-15) and got[3] == pytest.approx(5e300, rel=1e-15)
    assert got[4] == np.inf and np.isnan(got[5])
    assert got[7] == 1e-320  # a subnormal scaled into range and back, exactly
    assert got[8] == pytest.approx(5e-310 * math.sqrt(2.0), rel=1e-15)


def test_table_invariants() -> None:
    viewport = Viewport(*ELEVEN, 30.0)
    orbit, dc = _frame(viewport, (32, 32), 8000)
    table = build_table(orbit, 1000.0, frame_dc_bound(dc))
    assert table.extent == len(orbit) - 1 and len(table.levels) >= 8
    for index, level in enumerate(table.levels):
        assert level.r[0] == 0.0, "every entry that starts at Z_0 = 0 is dead"
        assert np.all(np.isfinite(level.r)) and np.all(level.r >= 0.0)
        if index:
            below = table.levels[index - 1].r
            assert np.all(level.r <= below[0 : 2 * level.r.size : 2]), "radii never grow"
    live = sum(int((level.r > 0).sum()) for level in table.levels)
    assert live > 0
    # The first step's radius: eps |Z_j| with no dc term.
    one = build_table(orbit[:9], 1000.0, 0.0)
    expected = min(
        EPSILON * float(mag(orbit.real[j : j + 1], orbit.imag[j : j + 1])[0]) for j in range(1, 8)
    )
    assert one.levels[0].r[0] == 0.0 and expected > 0.0  # Z_0 kills block 0


def test_the_loop_is_the_spec_one_pixel_at_a_time() -> None:
    frames = [
        (Viewport(*ELEVEN, 30.0), (16, 16), 8000),
        (Viewport(*_shifted(NUCLEUS_P1959, 30.0, 0.7, 0.0), 30.0), (8, 8), 20000),
        (Viewport(*_shifted(NUCLEUS_P16, 25.0, 0.3, 0.1), 25.0), (6, 6), 3000),
        (Viewport("-0.75", "0.10999", 30.0), (6, 6), 2000),
        (Viewport("-2", "1e-295", 280.0), (8, 8), 1000),
    ]
    for viewport, size, max_iter in frames:
        orbit, dc = _frame(viewport, size, max_iter)
        table = build_table(orbit, 1000.0, frame_dc_bound(dc))
        counts, _, _, applied = perturb_z2_bla(orbit, dc, max_iter, 1000.0, table)
        want_counts, want_applied = _scalar(orbit, dc, max_iter, 1000.0, table)
        assert counts.tolist() == want_counts and applied.tolist() == want_applied
        assert applied.sum() > 0


def test_a_longer_orbit_gives_the_same_pixels() -> None:
    """C# may hand the loop a cached orbit longer than max_iter + 1: entries past max_iter
    must never be taken (m + span <= n + span <= max_iter), so the pixels agree."""
    viewport = Viewport(*_shifted(NUCLEUS_P1959, 30.0, 0.7, 0.0), 30.0)
    size = (12, 12)
    dc = pixel_deltas(size, viewport)
    long_orbit = reference_orbit("mandelbrot", *viewport.orbit_center, 30.0, 20000)
    for max_iter in (1500, 2003, 2500):
        short = long_orbit[: max_iter + 1]
        bound = frame_dc_bound(dc)
        long_table = build_table(long_orbit, 1000.0, bound)
        assert long_table.extent > max_iter, "premise: the long table reaches past max_iter"
        a = perturb_z2_bla(short, dc, max_iter, 1000.0, build_table(short, 1000.0, bound))
        b = perturb_z2_bla(long_orbit, dc, max_iter, 1000.0, long_table)
        assert np.array_equal(a[0], b[0]) and np.array_equal(a[3], b[3])
        assert np.array_equal(a[1], b[1])


def test_where_nothing_engages_bla_is_bla_off() -> None:
    """At zoom 14 no entry survives eps = 2^-53: the BLA loop must be the plain loop,
    bit for bit -- counts, final z, and the smooth values and statuses built on them."""
    viewport = Viewport(
        "-0.743643887037158704752191506114774", "0.131825904205311970493132056385139", 14.0
    )
    on = Mandelbrot(max_iter=5000, bla=True).fields(
        (32, 32), viewport, smooth=True, status=True, distance=True, bla_applications=True
    )
    off = Mandelbrot(max_iter=5000).fields(
        (32, 32), viewport, smooth=True, status=True, distance=True
    )
    assert on.bla_applications is not None and int(on.bla_applications.sum()) == 0
    assert np.array_equal(on.counts, off.counts) and np.array_equal(on.smooth, off.smooth)
    assert np.array_equal(on.status, off.status)
    assert np.array_equal(on.distance, off.distance, equal_nan=True)
    orbit, dc = _frame(viewport, (32, 32), 5000)
    counts, _ = perturb_z2(orbit, np.zeros_like(dc), dc, 5000, 1000.0)
    assert np.array_equal(counts.reshape(32, 32), on.counts)


def test_bla_is_opt_in_and_t1_only() -> None:
    home = Viewport("-0.5", "0.0", 0.0)
    a = Mandelbrot(max_iter=300, bla=True).fields((16, 16), home, bla_applications=True)
    b = Mandelbrot(max_iter=300).fields((16, 16), home, bla_applications=True)
    assert np.array_equal(a.counts, b.counts)
    assert a.bla_applications is not None and not a.bla_applications.any()
    assert not Julia().fields((4, 4), home, bla_applications=True).bla_applications.any()  # type: ignore[union-attr]
    assert Mandelbrot().bla is False


def test_the_distance_rides_through_skips() -> None:
    """d' = A d + B ps through a skip: the estimate stays within span * eps of stepping."""
    viewport = Viewport("-0.75", "0.1", 170.0)
    on = Mandelbrot(max_iter=2000, bla=True).fields(
        (16, 16), viewport, distance=True, bla_applications=True
    )
    off = Mandelbrot(max_iter=2000).fields((16, 16), viewport, distance=True)
    assert on.bla_applications is not None and on.bla_applications.all()
    assert np.array_equal(on.counts, off.counts)
    assert on.distance is not None and off.distance is not None
    assert np.all(np.abs(on.distance / off.distance - 1.0) < 1e-12)
    assert pixel_scale((16, 16), viewport) > 0.0


@pytest.mark.slow
def test_bla_counts_match_direct_iteration() -> None:
    """The p1959 frame of test_deep_oracle.py with BLA: every pixel whose true count is
    stable under a few ulps of dc matches 192-bit direct iteration."""
    import test_deep_oracle as oracle

    size = 12
    zoom = 42.7
    viewport = Viewport(*_shifted(NUCLEUS_P1959, zoom, 0.7, 0.0), zoom)
    offsets = oracle.pixel_offsets((size, size), viewport)
    orbit = reference_orbit("mandelbrot", viewport.center_re, viewport.center_im, zoom, 20000)
    table = build_table(orbit, 1000.0, frame_dc_bound(offsets))
    counts, _, _, applied = perturb_z2_bla(orbit, offsets, 20000, 1000.0, table)
    assert applied.sum() > 0
    truth = oracle._truth(viewport, offsets, 20000, 1000.0)
    stable = oracle._stable(viewport, offsets, truth, 20000, 1000.0)
    assert stable.mean() >= 0.85
    assert int((counts[stable] != truth[stable]).sum()) == 0
