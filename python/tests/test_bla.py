"""BLA (spec/deep-zoom.md "BLA"): the magnitude, the table's invariants, the loop against
a scalar transcription of the spec, the same pixels from a longer orbit, BLA-off
equality where nothing engages, and the counts against direct iteration."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

from heaton_life.core.bignum import reference_orbit, reference_orbit_x
from heaton_life.core.viewport import Viewport
from heaton_life.fractal import Julia, Mandelbrot
from heaton_life.fractal.bla import (
    EPSILON,
    STRIDE,
    BlaTable,
    BlaTableX,
    build_table,
    build_table_t2,
    ceil_power_of_two,
    frame_dc_bound,
    frame_dc_bound_exponent,
    mag,
    perturb_z2_bla,
)
from heaton_life.fractal.engine import pixel_deltas, pixel_deltas_x, pixel_scale
from heaton_life.fractal.perturbation import perturb_z2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from gen_vectors import (
    ELEVEN_DIMENSIONS_IM,
    ELEVEN_DIMENSIONS_RE,
    NUCLEUS_P16,
    NUCLEUS_P1959,
    P830_CENTER,
    _shifted,
)

ELEVEN = (ELEVEN_DIMENSIONS_RE, ELEVEN_DIMENSIONS_IM)


def _scalar(
    orbit: np.ndarray,
    dc: np.ndarray,
    max_iter: int,
    radius: float,
    table: object,
    events: dict[str, int] | None = None,
) -> tuple[list[int], list[int]]:
    """The per-pixel loop exactly as spec/deep-zoom.md "BLA" writes it, one pixel at a
    time (the C# port's shape), for the vectorized one to match. ``events`` counts the
    rare branches: an escape or a rebase right after a skip, a span cut by max_iter."""
    levels = table.levels
    sizes = [level.r.size for level in levels]
    last = len(orbit) - 1
    tally = events if events is not None else {}
    for key in ("land_escape", "land_rebase", "blocked"):
        tally.setdefault(key, 0)
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
                    if m % span or m // span >= sizes[index]:
                        break
                    if n + span > max_iter:
                        tally["blocked"] += dm < level.r[m // span]
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
                tally["land_escape"] += chosen >= 0
                break
            if zabs2 < float(dz.real[0] * dz.real[0] + dz.imag[0] * dz.imag[0]):
                tally["land_rebase"] += chosen >= 0
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


def test_ceil_power_of_two() -> None:
    assert ceil_power_of_two(1.0) == 1.0 and ceil_power_of_two(math.nextafter(1.0, 2.0)) == 2.0
    assert ceil_power_of_two(0.3) == 0.5 and ceil_power_of_two(0.0) == 0.0
    tiny = 5e-324
    assert ceil_power_of_two(3 * tiny) == 4 * tiny
    assert ceil_power_of_two(math.ldexp(1.0, -1022) - tiny) == math.ldexp(1.0, -1022)
    assert ceil_power_of_two(1.7976931348623157e308) == math.inf


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


def test_bla_is_opt_in_and_off_at_t0() -> None:
    home = Viewport("-0.5", "0.0", 0.0)
    a = Mandelbrot(max_iter=300, bla=True).fields((16, 16), home, bla_applications=True)
    b = Mandelbrot(max_iter=300).fields((16, 16), home, bla_applications=True)
    assert np.array_equal(a.counts, b.counts)
    assert a.bla_applications is not None and not a.bla_applications.any()
    with pytest.raises(ValueError, match="no BLA"):
        Julia().fields((4, 4), home, bla_applications=True)
    assert Mandelbrot().bla is False


def test_the_distance_rides_through_skips() -> None:
    """d' = A d + B ps through a skip. Far from the set the pixel is well conditioned, so
    the estimate agrees with stepping to 1e-12; near the boundary conditioning amplifies
    the per-skip error like rounding, and only an oracle can compare the two."""
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


@pytest.mark.parametrize(
    ("case", "event"),
    [
        ("bla-landing-escape-8", "land_escape"),
        ("bla-landing-rebase-12", "land_rebase"),
        ("bla-blocked-8", "blocked"),
    ],
)
def test_the_rare_branches_stay_covered(case: str, event: str) -> None:
    """Each stored vector exercises the branch it exists for; a regeneration that loses
    it fails here rather than silently pinning less."""
    import json

    root = Path(__file__).resolve().parents[2] / "vectors" / "mandelbrot" / case
    meta = json.loads((root / "params.json").read_text())
    viewport = Viewport.from_dict(meta["viewport"])
    size = (meta["size"][0], meta["size"][1])
    max_iter = meta["params"]["max_iter"]
    orbit = np.frombuffer((root / "orbit.c128").read_bytes(), dtype="<c16")
    dc = pixel_deltas(size, viewport)
    table = build_table(orbit, 1000.0, frame_dc_bound(dc))
    events: dict[str, int] = {}
    counts, applied = _scalar(orbit, dc, max_iter, 1000.0, table, events)
    stored = np.frombuffer((root / "iterations.i32").read_bytes(), dtype="<i4")
    skips = np.frombuffer((root / "bla_applications.i32").read_bytes(), dtype="<i4")
    assert counts == stored.tolist() and applied == skips.tolist()
    assert events[event] > 0, events


def _t1_frame_tables(small_at: tuple[int, ...] = ()) -> tuple[BlaTable, BlaTableX]:
    """A zoom-100 frame near the p830 minibrot: T1's table and the T2 table of the same
    orbit and frame (``small_at``: indices to flag small)."""
    vp = Viewport(P830_CENTER[:120], "1e-100", 100.0)
    orbit = reference_orbit_x("mandelbrot", *vp.orbit_center, 100.0, 11620)
    small = np.zeros(len(orbit.samples), dtype=bool)
    small[orbit.small.index] = True
    small[list(small_at)] = True
    t1 = build_table(orbit.samples, 1000.0, frame_dc_bound(pixel_deltas((16, 16), vp)))
    dx = pixel_deltas_x((16, 16), vp)
    k = frame_dc_bound_exponent(dx.rm, dx.re, dx.im, dx.ie)
    assert k is not None and 2.0**k == frame_dc_bound(pixel_deltas((16, 16), vp))
    return t1, build_table_t2(orbit.samples, small, 1000.0, k)


def test_the_coefficients_are_correctly_rounded() -> None:
    """spec/deep-zoom.md "BLA", "Arithmetic": the recurrences carried in double-double, each
    entry storing the hi -- measured equal to the exactly computed coefficient rounded once,
    on every live entry of levels 0-3 of two complex stored orbits (the T2 table, whose
    coefficients are T1's: test_the_t2_table_stops_where_t1_does)."""
    from fractions import Fraction

    root = Path(__file__).resolve().parents[2] / "vectors" / "mandelbrot"
    for name in ("bla-p1959-zoom30-16", "bla-11dim-offref-zoom30-24"):
        case = root / name
        max_iter = json.loads((case / "params.json").read_text())["params"]["max_iter"]
        samples = np.frombuffer((case / "orbit.c128").read_bytes(), dtype="<c16")[: max_iter + 1]
        table = build_table_t2(samples, np.zeros(samples.size, dtype=bool), 1000.0, -100)
        exact_a: list[tuple[Fraction, Fraction]] = []
        exact_b: list[tuple[Fraction, Fraction]] = []
        for k in range(table.levels[0].rm.size):
            a, b = (Fraction(1), Fraction(0)), (Fraction(0), Fraction(0))
            for j in range(STRIDE):
                z = samples[k * STRIDE + j]
                sr, si = 2 * Fraction(z.real), 2 * Fraction(z.imag)
                b = (sr * b[0] - si * b[1] + 1, sr * b[1] + si * b[0])
                a = (sr * a[0] - si * a[1], sr * a[1] + si * a[0])
            exact_a.append(a)
            exact_b.append(b)
        checked = 0
        for level in table.levels[:4]:
            for k, (a, b) in enumerate(zip(exact_a, exact_b, strict=True)):
                if level.rm[k] > 0:
                    got = (level.ar[k], level.ai[k], level.br[k], level.bi[k])
                    assert got == (float(a[0]), float(a[1]), float(b[0]), float(b[1])), (name, k)
                    checked += 1
            pairs = range(len(exact_a) // 2)
            ya = [exact_a[2 * k + 1] for k in pairs]
            xa = [exact_a[2 * k] for k in pairs]
            xb = [exact_b[2 * k] for k in pairs]
            yb = [exact_b[2 * k + 1] for k in pairs]
            exact_a = [
                (y[0] * x[0] - y[1] * x[1], y[0] * x[1] + y[1] * x[0]) for y, x in zip(ya, xa)
            ]
            exact_b = [
                (y[0] * x[0] - y[1] * x[1] + c[0], y[0] * x[1] + y[1] * x[0] + c[1])
                for y, x, c in zip(ya, xb, yb)
            ]
        assert checked > 900


@pytest.mark.parametrize(
    ("mx", "my", "k"),
    [
        ((1.0, -100), (0.0, 0), -100),  # |dc| exactly 2^-100: its own power of two
        ((1.5, -100), (1.0, -100), -99),  # sqrt(1.5^2 + 1) = 1.80: up to 2^-99
        ((0.0, 0), (1.0, -5), -5),  # a zero real part (a one-column frame)
        ((1.0, -100), (1.0, -200), -100),  # the smaller part scales to 2^-100: m = 1
        ((1.25, -3000), (1.75, -3000), -2998),  # sqrt(1.25^2 + 1.75^2) = 2.15
        ((0.0, 0), (0.0, 0), None),  # every delta zero: no bound
        ((1.0, -100), (1.0, -1500), -100),  # E is the larger exponent (the other scales to 0)
    ],
)
def test_frame_dc_bound_exponent(
    mx: tuple[float, int], my: tuple[float, int], k: int | None
) -> None:
    """spec/deep-zoom.md "BLA at T2", the frame's bound: E the larger exponent of the
    nonzero maxima, m = mag of the pair scaled by 2^-E, k = E + the least j with 2^j >= m."""
    got = frame_dc_bound_exponent(
        np.array([mx[0]]), np.array([mx[1]]), np.array([my[0]]), np.array([my[1]])
    )
    assert got == k


def test_the_t2_table_never_spans_a_small_index() -> None:
    """A step at a small index has radius 0: every entry whose span contains it is dead,
    and no other entry changes."""
    _, clean = _t1_frame_tables()
    _, marked = _t1_frame_tables(small_at=(44,))
    for level_index, (a, b) in enumerate(zip(clean.levels, marked.levels, strict=True)):
        span = STRIDE << level_index
        covers = np.arange(a.rm.size) == 44 // span
        assert not b.rm[covers].any()
        assert np.array_equal(a.rm[~covers], b.rm[~covers])
        assert np.array_equal(a.re[~covers], b.re[~covers])
    assert clean.levels[0].rm[44 // STRIDE] > 0


def test_the_t2_table_stops_where_t1_does() -> None:
    """The T2 table's extent is T1's k*, and its coefficients are T1's bit for bit (one
    double-double build, spec/deep-zoom.md "BLA"); only the radii differ in kind."""
    root = Path(__file__).resolve().parents[2] / "vectors" / "mandelbrot"
    for name in ("bla-landing-escape-8", "bla-p1959-zoom30-16", "bla-11dim-zoom30-32"):
        case = root / name
        max_iter = json.loads((case / "params.json").read_text())["params"]["max_iter"]
        samples = np.frombuffer((case / "orbit.c128").read_bytes(), dtype="<c16")[: max_iter + 1]
        t1 = build_table(samples, 1000.0, 0.0)
        t2 = build_table_t2(samples, np.zeros(samples.size, dtype=bool), 1000.0, None)
        assert t2.extent == t1.extent
        assert [level.rm.size for level in t2.levels] == [level.r.size for level in t1.levels]
        for a, b in zip(t1.levels, t2.levels, strict=True):
            for name in ("ar", "ai", "br", "bi"):
                assert np.array_equal(getattr(a, name), getattr(b, name), equal_nan=True)
