"""Exact viewport arithmetic (spec/navigation.md): the properties the vectors cannot
enumerate -- precision never ratchets, a zero move changes nothing, recenters and
anchored zooms land within the documented grid, pixel_delta inverts pan, and
positional is value- and places-exact."""

from __future__ import annotations

import dataclasses
import math
import random
from fractions import Fraction

import pytest

from heaton_life.core import decimal_text
from heaton_life.core.bignum import decimal_places, working_bits
from heaton_life.core.viewport import Viewport
from heaton_life.fractal import center_places, pan, pixel_delta, zoom_at
from heaton_life.fractal.engine import scale_at

SEAHORSE = ("-0.743643887037158704752191506114774", "0.131825904205311970493132056385139")


def _value(text: str) -> Fraction:
    return Fraction(decimal_text.positional(text))


def test_center_places_come_from_the_frame() -> None:
    assert center_places(14.0, (512, 384)) == 14 + 3 + 2
    assert center_places(14.2, (1920, 1080)) == 15 + 4 + 2  # the ceiling of the zoom
    assert center_places(-1.5, (64, 48)) == 0 + 2 + 2  # never below zero
    assert center_places(0.0, (1, 1)) == 3
    assert center_places(14.0, (720, 1280)) == 14 + 4 + 2  # the height's digits
    for bad in (9000.5, -301.0, math.nan):
        with pytest.raises(ValueError):
            center_places(bad, (64, 64))


def test_a_zero_move_changes_nothing() -> None:
    vp = Viewport("-2", "1e-295", 280.0, reference_re="-2", reference_im="0")
    assert pan(vp, 0.0, 0.0, (32, 32)) == vp
    assert pan(vp, -0.0, 0.0, (32, 32)) == vp
    assert zoom_at(vp, 5.0, 2.0, (32, 32), 280.0) == vp  # no zoom change, no shift
    about_center = zoom_at(vp, 0.0, 0.0, (32, 32), 281.0)  # only the zoom moves
    assert about_center == dataclasses.replace(vp, zoom_log10=281.0)
    # Any real move prints BOTH components at the frame's places.
    moved = pan(vp, 7.5, 0.0, (32, 32))
    assert moved.center_im == "0." + "0" * center_places(280.0, (32, 32))  # 1e-295 rounds away
    assert (moved.reference_re, moved.reference_im) == ("-2", "0")  # carried over


def test_the_first_move_sheds_digits_the_frame_cannot_show() -> None:
    """A long component the move does not shift is still printed at the frame's
    places, so the orbit's precision drops to the zoom's own after any real move."""
    vp = Viewport("-0.75", "0." + "3" * 256, 20.0)
    assert working_bits(vp.center_re, vp.center_im, 20.0) > working_bits("0", "0", 20.0)
    for dx in (10.0, -25.0, 3.0):
        vp = pan(vp, dx, 0.0, (640, 480))
        assert working_bits(vp.center_re, vp.center_im, 20.0) == working_bits("0", "0", 20.0)


def test_repeated_moves_never_change_the_working_bits() -> None:
    """The places come from the frame, so after its first move a center's orbit costs
    what its zoom alone asks -- at every depth, for pans and anchored zooms alike."""
    rng = random.Random(11)
    for _ in range(60):
        zoom = rng.uniform(-2.0, 289.0)
        size = (rng.randint(1, 4000), rng.randint(1, 4000))
        vp = pan(Viewport(*SEAHORSE, zoom), 1.25, -0.5, size)
        bits = working_bits(vp.center_re, vp.center_im, zoom)
        assert bits == working_bits("0", "0", zoom), "the digit term must never win"
        for _ in range(8):
            if rng.random() < 0.5:
                vp = pan(vp, rng.uniform(-3000, 3000), rng.uniform(-3000, 3000), size)
            else:
                vp = zoom_at(vp, rng.uniform(-900, 900), rng.uniform(-900, 900), size, zoom)
            assert working_bits(vp.center_re, vp.center_im, zoom) == bits
            assert decimal_places(vp.center_re) <= center_places(zoom, size)


def test_a_recenter_lands_within_the_grid() -> None:
    rng = random.Random(3)
    for zoom in (0.0, 6.3, 14.0, 40.0, 150.25, 289.0):
        for _ in range(20):
            size = (rng.randint(16, 2048), rng.randint(16, 2048))
            dx, dy = rng.uniform(-size[0], size[0]), rng.uniform(-size[1], size[1])
            vp = Viewport(*SEAHORSE, zoom)
            moved = pan(vp, dx, dy, size)
            ps = scale_at(size[0], zoom)
            places = center_places(zoom, size)
            half = Fraction(1, 2 * 10**places)
            assert abs(_value(moved.center_re) - (_value(vp.center_re) + Fraction(dx * ps))) <= half
            assert (
                abs(_value(moved.center_im) - (_value(vp.center_im) + Fraction(-dy * ps))) <= half
            )
            assert half <= Fraction(ps) / 800


def test_an_anchored_zoom_holds_its_anchor() -> None:
    """Up to thirty decades in one step, both components: the shift is the exact
    difference of the two frames' offsets, so the anchor moves only by the rounding."""
    rng = random.Random(5)
    for _ in range(120):
        z0 = rng.uniform(0.0, 250.0)
        z1 = min(max(z0 + rng.uniform(-30.0, 30.0), -2.0), 290.0)
        size = (rng.randint(16, 2048), rng.randint(16, 2048))
        dx, dy = rng.uniform(-size[0], size[0]) / 2, rng.uniform(-size[1], size[1]) / 2
        vp = Viewport(*SEAHORSE, z0)
        moved = zoom_at(vp, dx, dy, size, z1)
        grid = Fraction(1, 2 * 10 ** center_places(z1, size))
        ps0, ps1 = scale_at(size[0], z0), scale_at(size[0], z1)
        before_re = _value(vp.center_re) + Fraction(dx * ps0)
        after_re = _value(moved.center_re) + Fraction(dx * ps1)
        before_im = _value(vp.center_im) + Fraction(-dy * ps0)
        after_im = _value(moved.center_im) + Fraction(-dy * ps1)
        assert abs(after_re - before_re) <= grid
        assert abs(after_im - before_im) <= grid
        assert moved.zoom_log10 == z1


def test_pixel_delta_inverts_pan() -> None:
    rng = random.Random(9)
    for _ in range(80):
        zoom = rng.uniform(-2.0, 289.0)
        size = (rng.randint(16, 2048), rng.randint(16, 2048))
        dx, dy = rng.uniform(-size[0], size[0]), rng.uniform(-size[1], size[1])
        vp = Viewport(*SEAHORSE, zoom)
        got = pixel_delta(vp, pan(vp, dx, dy, size), size)
        assert abs(got[0] - dx) <= 1 / 800 + 1e-9 * abs(dx)
        assert abs(got[1] - dy) <= 1 / 800 + 1e-9 * abs(dy)
    same = pixel_delta(Viewport(*SEAHORSE, 20.0), Viewport(*SEAHORSE, 3.0), (512, 512))
    assert same == (0.0, 0.0) and math.copysign(1, same[0]) == math.copysign(1, same[1]) == 1


def test_positional_keeps_the_value_and_the_places() -> None:
    rng = random.Random(7)
    for _ in range(2000):
        digits = "".join(rng.choice("0123456789") for _ in range(rng.randint(1, 40)))
        point = rng.randint(0, len(digits))
        text = (
            f"{rng.choice(['', '-', '+'])}{digits[:point]}.{digits[point:]}e{rng.randint(-60, 60)}"
        )
        out = decimal_text.positional(text)
        assert "e" not in out.lower() and not out.startswith("+")
        assert Fraction(out) == Fraction(text.replace("+", "", 1))
        assert decimal_places(out) == decimal_places(text)
        assert decimal_text.positional(out) == out  # a fixed point
    # The 10,000-digit limit, at its edge: the grammar reads back what positional writes.
    assert decimal_text.positional("9" * 10_000) == "9" * 10_000
    assert decimal_text.positional("0." + "9" * 9_999) == "0." + "9" * 9_999
    with pytest.raises(ValueError):
        decimal_text.positional("1" + "0" * 10_000)
    assert len(decimal_text.format_scaled(1, 9_999)) == 10_001  # "0." and 9,999 places
    with pytest.raises(ValueError):
        decimal_text.format_scaled(1, 10_000)
    with pytest.raises(ValueError):
        decimal_text.positional("1e-20000")  # 20,000 places cannot be read back
    with pytest.raises(ValueError):
        decimal_text.positional("1e20000")


def test_bad_inputs_are_refused() -> None:
    vp = Viewport(*SEAHORSE, 14.0)
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError):
            pan(vp, bad, 0.0, (64, 64))
        with pytest.raises(ValueError):
            zoom_at(vp, 0.0, 1.0, (64, 64), bad)
    with pytest.raises(ValueError):
        pan(vp, 1.0, 1.0, (0, 64))
    for bad_zoom in (9001.0, -300.5):  # outside the zoom domain, refused at once
        with pytest.raises(ValueError):
            pan(vp, 1.0, 0.0, (64, 64), bad_zoom)
        with pytest.raises(ValueError):
            zoom_at(vp, 1.0, 0.0, (64, 64), bad_zoom)
    with pytest.raises(ValueError):
        pan(Viewport("0", "0", -300.0), 1e300, 0.0, (1, 1))  # the offset overflows


def test_t2_pans_use_the_floatexp_offsets_a_render_gives() -> None:
    """Past zoom 290 a pan's offset is pixels * ps rounded once to floatexp -- the value
    engine.pixel_deltas_x gives that pixel -- so a click recenters exactly on the pixel a
    T2 render drew, and the center is printed at the frame's places."""
    from fractions import Fraction

    from heaton_life.core import decimal_text
    from heaton_life.fractal.engine import pixel_deltas_x

    size = (8, 6)
    vp = Viewport("-1.25", "0.0", 700.0)
    moved = pan(vp, 2.5, -1.5, size)  # the pixel at column 6.5 - 4 = 2.5, row 1 - 3 + 0.5
    dc = pixel_deltas_x(size, vp)
    k = 1 * 8 + 6  # row 1, column 6
    want_re = Fraction(dc.rm[k]) * Fraction(2) ** int(dc.re[k])
    want_im = Fraction(dc.im[k]) * Fraction(2) ** int(dc.ie[k])
    places = center_places(700.0, size)
    got_re = Fraction(decimal_text.positional(moved.center_re)) + Fraction(125, 100)
    got_im = Fraction(decimal_text.positional(moved.center_im))
    assert abs(got_re - want_re) <= Fraction(1, 2 * 10**places)
    assert abs(got_im - want_im) <= Fraction(1, 2 * 10**places)
    assert len(moved.center_re.split(".")[1]) == places
    back = pixel_delta(vp, moved, size)
    assert abs(back[0] - 2.5) < 1e-3 and abs(back[1] + 1.5) < 1e-3
