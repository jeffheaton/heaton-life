import pytest

from heaton_life.ca import LifeLikeParams


def test_json_roundtrip() -> None:
    p = LifeLikeParams(rule="B36/S23", width=128, height=64, density=0.5, seed=9, boundary="dead")
    assert LifeLikeParams.from_json(p.to_json()) == p


def test_defaults_fill_missing_fields() -> None:
    p = LifeLikeParams.from_dict({"width": 10, "height": 10})
    assert p.rule == "B3/S23"
    assert p.density == 0.35


def test_unknown_key_raises() -> None:
    with pytest.raises(ValueError, match="unknown parameter"):
        LifeLikeParams.from_dict({"width": 10, "heigth": 10})


def test_replace() -> None:
    p = LifeLikeParams()
    q = p.replace(seed=99)
    assert q.seed == 99
    assert p.seed == 0
