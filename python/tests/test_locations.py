"""Locations (spec/locations.md): the framing identities the conventions table states,
and the edges the vectors do not enumerate."""

from __future__ import annotations

import math

import pytest

from heaton_life.fractal import locations
from heaton_life.fractal.engine import scale_at


def test_kf_and_f3_frame_by_the_height() -> None:
    """KF's pixel spacing 4/(Zoom*H) is heaton-life's (4/W)*10^-z at z = log10 Zoom +
    log10(H/W); a square frame is log10 Zoom, a 16:9 one log10 Zoom - 0.2499."""
    loc = locations.parse_kfr("Re: -0.5\nIm: 0\nZoom: 1e10\n")
    assert loc.viewport((512, 512)).zoom_log10 == pytest.approx(10.0, abs=1e-12)
    assert loc.viewport((1920, 1080)).zoom_log10 == pytest.approx(10 - 0.249877, abs=1e-6)
    for size in ((1920, 1080), (1080, 1920), (333, 777)):
        width, height = size
        spacing = scale_at(width, loc.viewport(size).zoom_log10)
        assert spacing == pytest.approx(4 / (1e10 * height), rel=1e-12)


def test_heaton_fractal_frames_by_its_base_half_height() -> None:
    """HF's p = 2*h0/(10^d*H): the same view is z = d + log10(2H/(h0*W))."""
    loc = locations.hf_preset("-0.5", "0", "1.25", 30.0)
    width, height = 1920, 1080
    zoom = loc.viewport((width, height)).zoom_log10
    assert zoom == pytest.approx(30 + math.log10(2 * height / (1.25 * width)), abs=1e-12)
    assert scale_at(width, zoom) == pytest.approx(2 * 1.25 / (1e30 * height), rel=1e-12)


def test_heaton_fractal_imports_kf_an_octave_too_deep() -> None:
    """The documented HF discrepancy: it reads a KF zoom as d = log10 Zoom with h0 = 1,
    half the KF half-height. The same Zoom as an HF preset lands 0.30103 decades deeper."""
    kf = locations.parse_kfr("Re: 0\nIm: 0\nZoom: 4.2e100\n").viewport((512, 512)).zoom_log10
    hf = locations.hf_preset("0", "0", "1.0", math.log10(4.2e100)).viewport((512, 512))
    assert hf.zoom_log10 - kf == pytest.approx(math.log10(2), abs=1e-9)


def test_decimal_log10_reaches_past_the_float_range() -> None:
    assert locations.decimal_log10("2.15e2836") == pytest.approx(2836 + math.log10(2.15), abs=1e-9)
    assert locations.decimal_log10("1" + "0" * 5000) == 5000.0
    for bad in ("0", "-1", "0.000"):
        with pytest.raises(ValueError):
            locations.decimal_log10(bad)


def test_edges() -> None:
    with pytest.raises(ValueError):
        locations.hf_journal([])
    with pytest.raises(ValueError):
        locations.parse_hf_preset("[1, 2]")
    base = '{"location": {"centerReal": "0", "centerImag": "0", "baseHalfHeight": %s}%s}'
    for bad in (
        base % ('"1.0"', ', "zoom": {"targetDepthLog10": "30"}'),  # a string, not a number
        base % ('"1.0"', ', "zoom": {"targetDepthLog10": 1' + "0" * 400 + "}"),  # past a double
        base % ("1.0", ""),  # baseHalfHeight is a string
        base % ("null", ""),
    ):
        with pytest.raises(ValueError):
            locations.parse_hf_preset(bad)
    with pytest.raises(ValueError):
        locations.parse_kfr("Re: 0\nIm: 0\nIterations: 9223372036854775808\n")  # 2^63
    assert (
        locations.parse_kfr("Re: 0\nIm: 0\nIterations: 9223372036854775807\n").max_iter == 2**63 - 1
    )
    with pytest.raises(ValueError):
        locations.parse_kfr("Re: 0,5\nIm: 0\n")  # decimal commas are not decimals
    loc = locations.parse_kfr("Re: 1.5e-3\nIm: -2E1\nZoom: 1\n")
    assert (loc.center_re, loc.center_im) == ("0.0015", "-20")  # positional, places kept
    with pytest.raises(ValueError):
        loc.viewport((0, 10))
