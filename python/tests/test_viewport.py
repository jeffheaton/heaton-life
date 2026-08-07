import pytest

from heaton_life.core.viewport import Viewport


def test_defaults() -> None:
    vp = Viewport()
    assert vp.center_re == "-0.5"
    assert vp.center_im == "0.0"
    assert vp.zoom_log10 == 0.0


def test_accepts_long_decimal_strings() -> None:
    re50 = "-0.74364388703715870475219150611477400000000000000001"
    vp = Viewport(center_re=re50, center_im="0.13182590420531197", zoom_log10=45.0)
    assert vp.center_re == re50  # no precision loss, ever


def test_normalizes_numeric_input() -> None:
    vp = Viewport(center_re=-0.5, center_im=0)  # type: ignore[arg-type]
    assert vp.center_re == "-0.5"
    assert vp.center_im == "0"


def test_json_roundtrip() -> None:
    vp = Viewport(center_re="-1.25", center_im="0.02", zoom_log10=3.5)
    assert Viewport.from_json(vp.to_json()) == vp


def test_invalid_decimal_raises() -> None:
    with pytest.raises(ValueError):
        Viewport(center_re="not-a-number")


def test_invalid_type_raises() -> None:
    with pytest.raises(TypeError):
        Viewport(center_re=[1, 2])  # type: ignore[arg-type]
