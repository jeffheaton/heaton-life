import numpy as np
import pytest

from heaton_life.core.bignum import reference_orbit
from heaton_life.core.viewport import Viewport
from heaton_life.fractal import (
    BurningShip,
    Julia,
    Mandelbrot,
    Newton,
    zoom_animation,
)

SEAHORSE_RE = "-0.743643887037158704752191506114774"
SEAHORSE_IM = "0.131825904205311970493132056385139"


def test_integer_backends_agree_exactly() -> None:
    """Python ints and gmpy2's mpz run the same exact integer arithmetic."""
    gmpy2 = pytest.importorskip("gmpy2")
    from heaton_life.core.bignum import _orbit_fixed, working_bits

    bits = working_bits(SEAHORSE_RE, SEAHORSE_IM, 30.0)
    for kind in ("mandelbrot", "julia", "burning_ship"):
        a = _orbit_fixed(kind, SEAHORSE_RE, SEAHORSE_IM, bits, 500, -0.7269, 0.1889, int)
        b = _orbit_fixed(kind, SEAHORSE_RE, SEAHORSE_IM, bits, 500, -0.7269, 0.1889, gmpy2.mpz)
        assert np.array_equal(a, b), f"{kind}: int and mpz orbits must be identical"


def test_working_bits_count_the_centers_digits() -> None:
    """spec/deep-zoom.md "Precision": max(zoom bits, center digit bits) + 64."""
    from heaton_life.core.bignum import decimal_places, working_bits

    assert [decimal_places(s) for s in ("0", "0.0", "-2", "2.5E1", "1e-295", ".5")] == [
        0, 1, 0, 0, 295, 1,
    ]
    # The shipped deep vectors: 10^33 has 110 bits, exactly zoom 14's 46 + 64.
    assert working_bits(SEAHORSE_RE, SEAHORSE_IM, 14.0) == 174
    assert working_bits("-2", "1e-295", 280.0) == 1060  # zoom term wins
    assert working_bits("-2", "1e-310", 280.0) == 1094  # digit term wins: 10^310 is 1030 bits

    # The digit term stops at MAX_DIGIT_PLACES: a string alone cannot set F.
    assert working_bits("-1.75", "1e-100000", 13.0) == working_bits("-1.75", "1e-340", 13.0)
    assert working_bits("-1.75", "1e-340", 13.0) == (10**340).bit_length() + 64

    # Without the digit term a subnormal component would keep ~30 bits at zoom 280.
    # With it, Z1 = C is the correctly rounded subnormal.
    tiny_im = "9.2012923132971335189e-309"
    orbit = reference_orbit("mandelbrot", "-2", tiny_im, 280.0, 40)
    assert orbit[1].imag == 9.201292313297136e-309


def test_long_center_orbit_is_pinned_across_languages() -> None:
    """The full 139,166-sample orbit of a 256-place center at zoom 160, by SHA-256.

    Too long to ship as a vector (2.2 MB), so both suites assert the same digest
    (C#: ReferenceOrbitTests). While Python iterated in floating point this orbit
    parted from the C# one at sample 67,941.
    """
    import hashlib
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from gen_vectors import ELEVEN_DIMENSIONS_IM, ELEVEN_DIMENSIONS_RE

    orbit = reference_orbit(
        "mandelbrot", ELEVEN_DIMENSIONS_RE, ELEVEN_DIMENSIONS_IM, 160.0, 200_000
    )
    assert len(orbit) == 139_166
    digest = hashlib.sha256(np.ascontiguousarray(orbit, dtype="<c16").tobytes()).hexdigest()
    assert digest == "7664f6f70b16eb1b8ac09bb5eb78f2f1999edf72c68919b7e3cfd501c35f9b4c"


def test_orbit_samples_past_the_float64_range_are_infinities() -> None:
    """spec/deep-zoom.md "Stopping rule": IEEE rounding, in both ports (C#: ReferenceOrbitTests)."""
    orbit = reference_orbit("mandelbrot", "1e309", "0", 13.0, 10)
    assert list(orbit) == [0.0, complex(float("inf"), 0.0)]
    jorbit = reference_orbit("julia", "-1e160", "0", 13.0, 10, c_re=-0.7269, c_im=0.745)
    assert list(jorbit) == [complex(-1e160, 0.0), complex(float("inf"), 0.745)]
    counts = Mandelbrot(max_iter=100).iterations((4, 4), Viewport("1e400", "0", 13.0))
    assert (counts == 1).all()


def test_reference_orbit_starts_correctly() -> None:
    orbit = reference_orbit("mandelbrot", "-0.5", "0.25", 5.0, 50)
    assert orbit[0] == 0.0
    assert orbit[1] == complex(-0.5, 0.25)  # Z1 = C
    jorbit = reference_orbit("julia", "0.1", "0.2", 5.0, 50, c_re=-0.7269, c_im=0.1889)
    assert jorbit[0] == complex(0.1, 0.2)


def test_known_escape_count() -> None:
    # c=2: z = 2, 6, 38, 1446 -> escapes R=1000 at iteration 4
    counts = Mandelbrot(max_iter=100).iterations((1, 1), Viewport("2.0", "0.0", 3.0))
    assert counts[0, 0] == 4


def test_mandelbrot_conjugate_symmetry() -> None:
    counts = Mandelbrot(max_iter=300).iterations((64, 64), Viewport("-0.5", "0.0", 0.0))
    assert np.array_equal(counts, counts[::-1, :])  # exact: conjugation is bitwise


def test_interior_fraction_at_home() -> None:
    counts = Mandelbrot(max_iter=500).iterations((64, 64), Viewport("-0.5", "0.0", 0.0))
    interior = (counts < 0).mean()
    assert 0.05 < interior < 0.15  # M-set area ~1.5 in a span-4 square frame


def test_t1_matches_t0_where_both_valid() -> None:
    # Julia and Burning Ship in smooth regions: exact agreement.
    julia = Julia(max_iter=1500)
    vp = Viewport("0.05", "0.05", 7.0)
    assert np.array_equal(julia._compute_t0((64, 64), vp)[0], julia._compute_t1((64, 64), vp)[0])

    ship = BurningShip(max_iter=1500)
    vps = Viewport("-1.7443", "-0.0328", 6.0)
    assert np.array_equal(ship._compute_t0((64, 64), vps)[0], ship._compute_t1((64, 64), vps)[0])

    # Mandelbrot at a chaotic boundary point: agreement limited by float64 chaos
    # itself (T0 vs T0-nudged-1ulp differs just as much), so bound the fraction.
    m = Mandelbrot(max_iter=2000)
    vpm = Viewport(SEAHORSE_RE, SEAHORSE_IM, 8.0)
    t0 = m._compute_t0((64, 64), vpm)[0]
    t1 = m._compute_t1((64, 64), vpm)[0]
    assert (t0 == t1).mean() > 0.9


RABBIT = complex(-0.123, 0.745)
# The rabbit's repelling fixed point beta = (1 + sqrt(1 - 4c)) / 2, on the Julia set.
RABBIT_BETA_RE = "1.27658194945592591790467276337476"
RABBIT_BETA_IM = "-0.47966605489732779175475867397901"


def _direct_julia_counts(
    size: tuple[int, int], vp: Viewport, c: complex, max_iter: int, bits: int
) -> np.ndarray:
    """Ground truth: every pixel iterated directly in `bits`-bit binary floating point.

    Each pixel is the exact sum of the decimal center and its float64 offset
    (spec/fractals.md "Pixel mapping"), so this is the frame T1 approximates.
    """
    import gmpy2

    from heaton_life.fractal.engine import pixel_offsets

    offsets = pixel_offsets(size, vp)
    r2 = 1000.0 * 1000.0
    counts = np.full(offsets.size, -1, dtype=np.int32)
    with gmpy2.context(precision=bits):
        base_re, base_im = gmpy2.mpfr(vp.center_re), gmpy2.mpfr(vp.center_im)
        cr, ci = gmpy2.mpfr(c.real), gmpy2.mpfr(c.imag)
        for k, off in enumerate(offsets):
            zr = base_re + gmpy2.mpfr(off.real)
            zi = base_im + gmpy2.mpfr(off.imag)
            for it in range(1, max_iter + 1):
                zr, zi = zr * zr - zi * zi + cr, 2 * zr * zi + ci
                if zr * zr + zi * zi > r2:
                    counts[k] = it
                    break
    return counts.reshape(size[1], size[0])


def test_julia_t1_rebases_onto_the_critical_orbit() -> None:
    """spec/deep-zoom.md "Rebasing": the Julia reference starts at the center, so a
    rebased pixel must restart on the critical orbit (W0 = 0, same c), not on Z[0]."""
    pytest.importorskip("gmpy2")
    from heaton_life.fractal.engine import pixel_offsets
    from heaton_life.fractal.perturbation import perturb_z2

    size, max_iter = (32, 32), 600  # the vectors/julia/deep-zoom13-32 frame
    vp = Viewport(RABBIT_BETA_RE, RABBIT_BETA_IM, 13.0)
    counts = Julia(c=RABBIT, max_iter=max_iter)._compute_t1(size, vp)[0].reshape(32, 32)

    # Premise: rebases fire in this frame. Restarting on the center's own orbit (the
    # pre-2026-09-23 behavior) must change it, or the comparison below proves nothing.
    orbit = reference_orbit(
        "julia",
        vp.center_re,
        vp.center_im,
        vp.zoom_log10,
        max_iter,
        c_re=RABBIT.real,
        c_im=RABBIT.imag,
    )
    dz0 = pixel_offsets(size, vp)
    wrong, _ = perturb_z2(orbit, dz0, np.zeros_like(dz0), max_iter, 1000.0)
    assert (wrong.reshape(32, 32) != counts).mean() > 0.2

    truth = _direct_julia_counts(size, vp, RABBIT, max_iter, bits=300)
    assert np.array_equal(counts, truth)


def test_deep_zoom_past_float64_produces_structure() -> None:
    counts = Mandelbrot(max_iter=5000).iterations(
        (32, 32), Viewport(SEAHORSE_RE, SEAHORSE_IM, 14.0)
    )
    escaped = counts[counts > 0]
    assert escaped.size > 100, "deep frame should mostly escape here"
    assert escaped.max() - escaped.min() > 100, "and with varied counts (structure)"


def test_zoom_beyond_t1_raises() -> None:
    with pytest.raises(ValueError, match="floatexp"):
        Mandelbrot(max_iter=50).iterations((8, 8), Viewport("-0.5", "0.0", 300.0))


def test_render_range_and_interior_black() -> None:
    field = Mandelbrot(max_iter=200)
    img = field.render((32, 32), Viewport("-0.5", "0.0", 0.0))
    assert img.shape == (32, 32)
    assert img.min() >= 0.0 and img.max() <= 1.0
    counts = field.iterations((32, 32), Viewport("-0.5", "0.0", 0.0))
    assert (img[counts < 0] == 0.0).all()


def test_newton_basins() -> None:
    newton = Newton(degree=3)
    roots, iters = newton.basins((64, 64), Viewport("0.0", "0.0", -0.1))
    assert (roots >= 0).all(), "every pixel should converge for z^3-1"
    assert set(np.unique(roots)) == {0, 1, 2}
    assert (iters[roots >= 0] >= 1).all()
    render = newton.render((32, 32), Viewport("0.0", "0.0", -0.1))
    assert render.min() >= 0.0 and render.max() <= 1.0

    # z^5-1 has more intricate basin boundaries: a few boundary pixels may not
    # converge in 60 iterations, and that's correct behavior.
    five = Newton(degree=5)
    roots5, _ = five.basins((64, 64), Viewport("0.0", "0.0", -0.1))
    assert (roots5 >= 0).mean() > 0.99
    assert set(np.unique(roots5[roots5 >= 0])) == {0, 1, 2, 3, 4}


def test_deep_render_keeps_contrast() -> None:
    # Counts cluster near max_iter at depth; per-frame stretching must keep the
    # palette in play rather than going monochrome.
    field = Mandelbrot(max_iter=5000)
    img = field.render((48, 48), Viewport(SEAHORSE_RE, SEAHORSE_IM, 14.0))
    escaped_values = img[img > 0]
    assert escaped_values.size > 100
    assert escaped_values.max() - escaped_values.min() > 0.5, "deep frame lost contrast"


def test_zoom_animation_frame_count() -> None:
    anim = zoom_animation(
        Mandelbrot(max_iter=100),
        (32, 32),
        Viewport("-0.75", "0.1", 2.0),
        steps=3,
    )
    assert len(anim) == 3


def test_newton_refuses_to_leave_the_direct_tier() -> None:
    """spec/fractals.md: "Newton (float64 only, zoom <= 1e12)"; spec/deep-zoom.md
    gives it no perturbation tier. Every other family here tiers or raises, but
    Newton had NO zoom check at all and silently produced a degenerate frame past
    1e13 — and kept going past the T1 ceiling, where the escape-time fields raise.
    The C# port enforced this all along.
    """
    field = Newton(degree=3, max_iter=60)
    field.basins((16, 16), Viewport("0.3", "0.5", 12.0))          # at the ceiling: fine

    for zoom in (12.5, 14.0, 300.0):
        with pytest.raises(ValueError, match="no perturbation tier"):
            field.basins((16, 16), Viewport("0.3", "0.5", zoom))

    # Every entry point routes through basins, so all of them are guarded.
    with pytest.raises(ValueError):
        field.render((16, 16), Viewport("0.3", "0.5", 20.0))
    with pytest.raises(ValueError):
        field.iterations((16, 16), Viewport("0.3", "0.5", 20.0))
