import numpy as np
import pytest

from heaton_life.core.bignum import precision_bits, reference_orbit
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


def test_bignum_backends_agree_exactly() -> None:
    gmpy2 = pytest.importorskip("gmpy2")
    from heaton_life.core.bignum import _orbit_gmpy2, _orbit_mpmath

    assert gmpy2 is not None
    bits = precision_bits(30.0)
    for kind in ("mandelbrot", "julia", "burning_ship"):
        a = _orbit_gmpy2(kind, SEAHORSE_RE, SEAHORSE_IM, bits, 500, -0.7269, 0.1889)
        b = _orbit_mpmath(kind, SEAHORSE_RE, SEAHORSE_IM, bits, 500, -0.7269, 0.1889)
        assert np.array_equal(a, b), f"{kind}: gmpy2 and mpmath orbits must be identical"


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
