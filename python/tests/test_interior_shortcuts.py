"""Interior shortcuts and status (spec/fractals.md): the cardioid/bulb test and exact
cycle detection are output-neutral -- every count and smooth value is what the plain
loop gives -- and the status output says how each count was decided."""

from __future__ import annotations

import random
from fractions import Fraction

import numpy as np

from heaton_life.core.viewport import Viewport
from heaton_life.fractal import BurningShip, Julia, Mandelbrot
from heaton_life.fractal.engine import (
    CARDIOID_OR_BULB,
    CYCLE,
    ESCAPED,
    EXHAUSTED,
    cardioid_or_bulb,
    pixel_grid,
    smooth_iterations,
)


def _plain(
    z0: np.ndarray, c: np.ndarray, ship: bool, max_iter: int, r2: float = 1e6
) -> tuple[np.ndarray, np.ndarray]:
    """The escape loop with no shortcut at all: the definition the shortcuts must match."""
    counts = np.full(c.size, -1, dtype=np.int32)
    final = np.zeros(c.size, dtype=np.complex128)
    z = z0.copy()
    for it in range(1, max_iter + 1):
        if ship:
            folded = np.abs(z.real) + 1j * np.abs(z.imag)
            z = folded * folded + c
        else:
            z = z * z + c
        escaped = (z.real * z.real + z.imag * z.imag > r2) & (counts < 0)
        counts[escaped] = it
        final[escaped] = z[escaped]
        z[counts > 0] = 0  # frozen: never escapes again, never overflows
    return counts, final


def test_the_cardioid_test_only_flags_interior_points() -> None:
    """A dense sweep across both boundaries: every flagged point is inside by the exact
    inequality, and plain iteration of it never escapes."""
    rng = np.random.default_rng(4)
    t = rng.uniform(0, 2 * np.pi, 4000)
    # The main cardioid's boundary, c = e^{it}/2 - e^{2it}/4, and the bulb's circle.
    cardioid = np.exp(1j * t) / 2 - np.exp(2j * t) / 4
    bulb = -1 + np.exp(1j * t) / 4
    offsets = 10.0 ** rng.uniform(-16, -3, t.size) * rng.choice([-1, 1], t.size)
    points = np.concatenate([cardioid * (1 + offsets), -1 + (bulb + 1) * (1 + offsets)])
    flagged = cardioid_or_bulb(points)
    assert 0.2 < flagged.mean() < 0.7, "premise: the sweep straddles the boundaries"
    hits = np.flatnonzero(flagged)
    sample = np.concatenate([hits[hits < t.size][:400], hits[hits >= t.size][:400]])
    assert (sample >= t.size).sum() >= 300, "premise: bulb points are checked too"
    for c in points[sample]:
        x, y = Fraction(c.real), Fraction(c.imag)
        xq = x - Fraction(1, 4)
        q = xq * xq + y * y
        assert q * (q + xq) < y * y / 4 or (x + 1) ** 2 + y * y < Fraction(1, 16)
    counts, _ = _plain(np.zeros(int(flagged.sum())), points[flagged], False, 20_000)
    assert (counts == -1).all()


def test_a_small_escape_radius_turns_the_cardioid_test_off() -> None:
    """Orbits in the period-2 bulb reach |z| near 1.27, so below radius 2 a point of the
    cardioid or bulb can escape: the counts must stay the plain loop's."""
    vp = Viewport("-0.5", "0.0", 0.0)
    c = pixel_grid((64, 64), vp)
    for radius in (1.0, 1.2, 1.9, 2.0):
        field = Mandelbrot(max_iter=200, escape_radius=radius)
        counts, status = field.counts_and_status((64, 64), vp)
        want, _ = _plain(np.zeros_like(c), c, False, 200, radius * radius)
        assert np.array_equal(counts.ravel(), want), radius
        assert (status == CARDIOID_OR_BULB).any() == (radius >= 2.0)


def test_the_shortcuts_are_output_neutral() -> None:
    """Counts and smooth values equal the plain loop's on random frames of every family;
    statuses agree with the counts."""
    rng = random.Random(8)
    for _ in range(12):
        family = rng.choice(["mandelbrot", "julia", "ship"])
        zoom = rng.uniform(-0.3, 6.0)
        center = (repr(rng.uniform(-1.8, 0.4)), repr(rng.uniform(-0.8, 0.8)))
        vp = Viewport(*center, zoom)
        size = (48, 40)
        field: Mandelbrot | Julia | BurningShip
        if family == "mandelbrot":
            field = Mandelbrot(max_iter=1500)
        elif family == "julia":
            field = Julia(c=complex(-0.123, 0.745), max_iter=1500)
        else:
            field = BurningShip(max_iter=1500)
        c = pixel_grid(size, vp)
        if family == "julia":
            want, final = _plain(c, np.full_like(c, complex(-0.123, 0.745)), False, 1500)
        else:
            want, final = _plain(np.zeros_like(c), c, family == "ship", 1500)
        counts, status = field.counts_and_status(size, vp)
        assert np.array_equal(counts.ravel(), want), (family, center, zoom)
        _, mu = field.counts_and_smooth(size, vp)
        assert np.array_equal(mu.ravel(), smooth_iterations(want, final, 1000.0))
        assert ((status == ESCAPED) == (counts > 0)).all()
        assert set(np.unique(status)) <= {ESCAPED, EXHAUSTED, CARDIOID_OR_BULB, CYCLE}
        if family != "mandelbrot":
            assert not (status == CARDIOID_OR_BULB).any()


def test_cycles_are_found_and_deep_frames_report_only_escaped_or_exhausted() -> None:
    # The rabbit's interior is an attracting 3-cycle: every interior pixel is proved.
    _, status = Julia(c=complex(-0.123, 0.745), max_iter=1000).counts_and_status(
        (64, 64), Viewport("0", "0", 0.0)
    )
    assert (status == CYCLE).sum() > 300 and not (status == EXHAUSTED).any()
    # T1 proves nothing: its state includes the orbit index, which never repeats. Each
    # frame has exhausted pixels, which T0 would have proved.
    deep: list[tuple[Mandelbrot | Julia | BurningShip, Viewport]] = [
        (
            Mandelbrot(max_iter=5000),
            Viewport(
                "-0.743643887037158704752191506114774", "0.131825904205311970493132056385139", 14.0
            ),
        ),
        (
            Julia(c=complex(-0.123, 0.745), max_iter=600),
            Viewport(
                "1.27658194945592591790467276337476", "-0.47966605489732779175475867397901", 13.0
            ),
        ),
        (
            BurningShip(max_iter=1000),
            Viewport("0.403269293475576420989278613990", "-0.595275727121703516488710194270", 13.0),
        ),
    ]
    for field, vp in deep:
        counts, status = field.counts_and_status((32, 32), vp)
        assert set(np.unique(status)) == {ESCAPED, EXHAUSTED}, type(field).__name__
        assert ((status == ESCAPED) == (counts > 0)).all()
