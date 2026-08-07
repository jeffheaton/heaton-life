import pytest

from heaton_life.ca.rulestring import canonical_rule, parse_rule


def test_parse_life() -> None:
    assert parse_rule("B3/S23") == (frozenset({3}), frozenset({2, 3}))


def test_case_and_whitespace_insensitive() -> None:
    assert parse_rule("b36 / s23") == (frozenset({3, 6}), frozenset({2, 3}))


def test_presets() -> None:
    assert parse_rule("highlife") == (frozenset({3, 6}), frozenset({2, 3}))
    assert parse_rule("Life") == parse_rule("B3/S23")


def test_empty_survival() -> None:
    birth, survive = parse_rule("B2/S")
    assert birth == frozenset({2})
    assert survive == frozenset()


def test_canonical() -> None:
    assert canonical_rule("b3/s32") == "B3/S23"
    assert canonical_rule("seeds") == "B2/S"


@pytest.mark.parametrize("bad", ["", "garbage", "B9/S23", "23/3", "B3S23", "B3/S23/C4"])
def test_invalid_raises(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_rule(bad)
