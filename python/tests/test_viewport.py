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


def test_accepts_exact_integers_but_refuses_floats() -> None:
    """A float center is REFUSED, not coerced.

    This class exists so a deep-zoom center keeps its digits, and a float64
    argument has already lost them before __post_init__ can see it:
    Viewport(-0.743643887037158704752191506114774) used to store
    '-0.7436438870371587', silently dropping 17 digits at exactly the depth where
    they matter. Integers are exact, so they still coerce.
    """
    vp = Viewport(center_re=0, center_im=-2)  # type: ignore[arg-type]
    assert vp.center_re == "0"
    assert vp.center_im == "-2"

    with pytest.raises(TypeError, match="decimal string"):
        Viewport(center_re=-0.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="decimal string"):
        Viewport(center_im=0.0)  # type: ignore[arg-type]

    # The exact case the guard exists for: the digits are gone before we see them.
    deep = "-0.743643887037158704752191506114774"
    with pytest.raises(TypeError):
        Viewport(center_re=float(deep))  # type: ignore[arg-type]
    assert Viewport(center_re=deep).center_re == deep   # quoted, it survives whole

    # zoom_log10 is a float by contract and is unaffected.
    assert Viewport("-0.5", "0.0", 3.5).zoom_log10 == 3.5


def test_json_roundtrip() -> None:
    vp = Viewport(center_re="-1.25", center_im="0.02", zoom_log10=3.5)
    assert Viewport.from_json(vp.to_json()) == vp


def test_invalid_decimal_raises() -> None:
    with pytest.raises(ValueError):
        Viewport(center_re="not-a-number")


def test_invalid_type_raises() -> None:
    with pytest.raises(TypeError):
        Viewport(center_re=[1, 2])  # type: ignore[arg-type]
