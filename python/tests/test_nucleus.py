"""Discovery (spec/nucleus.md): what the vectors do not pin -- Heaton Fractal's own nuclei,
the ext conversion at the extremes, the framing, the rules at their edges, the errors."""

from __future__ import annotations

import dataclasses
import math
import sys
from fractions import Fraction
from pathlib import Path

import pytest

from heaton_life.core.pow10 import pow10
from heaton_life.fractal.navigation import _printed
from heaton_life.fractal.nucleus import (
    Nucleus,
    _Ext,
    _rdiv,
    _rshift,
    _split,
    _surrounds_origin,
    box_period,
    find_nucleus,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from gen_vectors import NUCLEUS_P1959, P6308_HF, _shifted

# Heaton Fractal's r7-a round 2 (hunts/r7-a.jsonl line 3): period 26699, depth 235.16.
P26699_HF = (
    (
        "-0.74179270142920012328415486246133486822181337292254710214402418375004664084945569585"
        "2460110781307259050374889143621212747957704746464876377399997985871941832944334843006854"
        "4905850759553614829455273237975670778079422269976500084891560131006960547143126545758797"
        "9988124418712944798709332720697771546765"
    ),
    (
        "0.123977941724695971711689620339223317838367247673535822857200096883849880494974599965"
        "1688630478961023679589271705082860693096576548295640826022779739317625587049454234774981"
        "4285195935908938228446358634882858469364497547178044866612817146768563458523416373733697"
        "179639200000597923217178028307370027088"
    ),
)


@pytest.mark.slow
@pytest.mark.parametrize(
    ("center", "period", "zoom", "depth"),
    [
        (NUCLEUS_P1959, 1959, 21.0, 42.7257864009331),
        (P6308_HF, 6308, 55.0, 106.17376130574708),
        (P26699_HF, 26699, 118.0, 235.16141613800227),
    ],
    ids=["p1959", "p6308", "p26699"],
)
def test_heaton_fractal_nuclei_refine_to_themselves(
    center: tuple[str, str], period: int, zoom: float, depth: float
) -> None:
    """HF's hunter printed these at depth + 64 places; refined from its digits at the zoom
    it navigated to, each is found where HF put it, at HF's size."""
    n = find_nucleus(center[0], center[1], period, zoom)
    assert n.found and n.stop == "floor"
    places = len(n.center_re.split(".")[1])
    assert places == max(math.ceil(n.depth_bits * math.log10(2)), math.ceil(zoom)) + 8
    assert n.center_re == _printed(Fraction(center[0]), places)
    assert n.center_im == _printed(Fraction(center[1]), places)
    assert abs(n.size_log10 + depth) <= 1e-12 * depth


def test_a_found_center_refines_to_itself() -> None:
    first = find_nucleus("-1.75", "0.001", 3, 1.0)
    again = find_nucleus(first.center_re, first.center_im, 3, 1.0)
    assert first.found and again.found
    assert (again.center_re, again.center_im) == (first.center_re, first.center_im)


# --- the ext conversion -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "bits"),
    [
        (1, 1200),  # 2^-1200: below the smallest subnormal
        (3 << 1500, 1024),  # 3 * 2^476 at F > 1024
        (-((1 << 60) + 3), 2000),  # 60 bits: rounded to 53, ties to even
        ((1 << 53) + 1, 100),  # a tie, to even (down)
        ((1 << 53) + 3, 100),  # a tie, to even (up)
        ((1 << 54) - 1, 10),  # rounds up across the binade
    ],
)
def test_split_rounds_the_integer_itself(value: int, bits: int) -> None:
    m, e = _split(value, bits)
    assert 1.0 <= abs(m) < 2.0 and (m < 0) == (value < 0)
    exact = Fraction(value, 1 << bits)
    got = Fraction(m) * (Fraction(2) ** e)
    # Round to 53 significant bits, ties to even, by hand.
    k = exact.numerator.bit_length() - exact.denominator.bit_length()
    scale = Fraction(2) ** (52 - k)
    if abs(exact) * scale >= 2**53:
        scale /= 2
    q = abs(exact) * scale
    whole = math.floor(q)
    rest = q - whole
    whole += 1 if rest > Fraction(1, 2) or (rest == Fraction(1, 2) and whole % 2) else 0
    assert abs(got) == whole / scale


def test_ext_keeps_parts_60_binades_apart_and_drops_farther() -> None:
    near = _Ext.from_fixed(1 << 100, 1 << 40, 100)  # 1 + 2^-60 i: exactly 60 down, kept
    assert near.im == 2.0**-60 and near.re == 1.0 and near.e == 0
    far = _Ext.from_fixed(1 << 100, 1 << 39, 100)  # 2^-61: more than 60 down, dropped
    assert far.im == 0.0 and far.re == 1.0


def test_rounding_ties_go_away_from_zero() -> None:
    assert [_rshift(v, k) for v, k in [(3, 1), (-3, 1), (-6, 2), (5, 1), (-5, 1)]] == [
        2,
        -2,
        -2,
        3,
        -3,
    ]
    assert [_rdiv(n, d) for n, d in [(3, 2), (-3, 2), (5, 2), (-7, 2), (7, 3)]] == [2, -2, 3, -4, 2]


# --- the rules at their edges -------------------------------------------------------------


def test_surround_is_half_open_on_the_axis() -> None:
    assert _surrounds_origin([(-1, -1), (1, -1), (1, 1), (-1, 1)])
    # A vertex on the positive axis counts as above: the edge from below crosses once, the
    # edge to the other vertex above does not -- inside counts 1, outside counts 0 or 2.
    assert _surrounds_origin([(1, 0), (-1, 1), (-1, -1)])
    assert not _surrounds_origin([(1, 0), (2, 1), (2, -1)])
    # A corner exactly at 0, the rest above: nothing straddles, so it is outside.
    assert not _surrounds_origin([(0, 0), (2, 0), (2, 2), (0, 2)])
    # An edge through 0 itself (product 0) does not cross; the other edge does: inside.
    assert _surrounds_origin([(0, 0), (2, 0), (2, 2), (0, -1)])


def test_box_radius_is_the_last_square() -> None:
    box = box_period(*_shifted(NUCLEUS_P1959, 22.0, 0.2, 0.1), 22.0, 5000)
    assert box.halvings == 1 and box.radius == math.ldexp(2.0 * pow10(-22.0), -1)
    escaped = box_period("1", "1", 2.0, 1000)
    assert escaped.reason == "escaped" and escaped.halvings == 8
    assert escaped.radius == math.ldexp(0.02, -8)


def test_period_one_has_size_positive_zero() -> None:
    n = find_nucleus("-0.5", "0", 1, 0.0)
    assert n.found and n.size_log10 == 0.0 and math.copysign(1.0, n.size_log10) == 1.0


def test_location_frames_two_and_a_half_sizes_and_never_overflows_max_iter() -> None:
    n = find_nucleus("-1.75", "0.001", 3, 1.0)
    loc = n.location()
    assert loc.format == "nucleus" and loc.max_iter == 300
    assert loc.half_height_log10 == n.size_log10 + 0.4
    huge = dataclasses.replace(n, period=414_246_396)
    assert huge.location().max_iter == 2**31 - 1
    with pytest.raises(ValueError, match="no nucleus"):
        dataclasses.replace(n, found=False).location()


def test_found_needs_the_nucleus_inside_the_reach() -> None:
    # The walk from the zoom-21 frame on the p1959 nucleus leaves the view.
    n = find_nucleus(NUCLEUS_P1959[0], NUCLEUS_P1959[1], 1924, 21.0)
    assert not n.found and not n.inside and n.stop == "left-view"


def test_a_coarse_precision_is_not_converged() -> None:
    """Without escalation, F = 128 cannot place a depth-162 atom: a grid point billions of
    sizes from the nucleus passes the bar, and the gate says not converged."""
    coarse = find_nucleus("-2", "0", 42, 0.0, max_escalations=0)
    assert coarse.bits - coarse.depth_bits < 64
    assert not coarse.converged and not coarse.found and math.isnan(coarse.size_log10)
    fine = find_nucleus("-2", "0", 42, 0.0)
    assert fine.found and fine.bits - fine.depth_bits >= 64


def test_a_failed_search_prints_at_the_views_places() -> None:
    """A point that did not converge prints 8 places past the view, whatever its derivative
    says: this orbit's depth would ask for over 10,000 places."""
    n = find_nucleus("0", "1", 14000, 0.0, max_escalations=0)
    assert not n.converged and n.depth_bits > 33_000
    assert n.center_re == "0.00000000" and n.center_im == "1.00000000"


def test_the_reason_fields_agree() -> None:
    n = find_nucleus("-1.001", "0.0003", 4, 2.0)
    assert n.converged and n.lower_period == 2 and not n.found and math.isnan(n.size_log10)
    assert isinstance(n, Nucleus)


# --- errors ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda: box_period("0", "0", 0.0, 0),
        lambda: find_nucleus("0", "0", 0, 0.0),
        lambda: find_nucleus("0", "0", 2, 0.0, max_steps=0),
        lambda: find_nucleus("0", "0", 2, 0.0, max_evaluations=0),
        lambda: find_nucleus("0", "0", 2, 0.0, max_escalations=-1),
        lambda: find_nucleus("0", "0", 2, 0.0, radius=0.0),
        lambda: find_nucleus("0", "0", 2, 0.0, radius=-1.0),
        lambda: find_nucleus("0", "0", 2, 0.0, radius=math.inf),
        lambda: find_nucleus("0", "0", 2, 0.0, radius=math.nan),
        lambda: box_period("0", "0", math.nan, 10, radius=1.0),
        lambda: box_period("0", "0", 301.0, 10),  # the zoom lies in pow10's domain
        lambda: find_nucleus("0", "0", 2, -301.0, radius=1.0),  # with a radius too
    ],
)
def test_bad_arguments_raise(call: object) -> None:
    with pytest.raises(ValueError):
        call()  # type: ignore[operator]
