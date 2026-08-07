"""Headless tests for the Qt-free playground pieces (registry + form model)."""

from heaton_life.ca import LifeLikeParams
from heaton_life.playground.model import field_specs
from heaton_life.playground.registry import FAMILIES


def test_field_specs_for_lifelike() -> None:
    specs = {s.name: s for s in field_specs(LifeLikeParams)}
    assert specs["rule"].kind == "str"
    assert specs["width"].kind == "int" and specs["width"].maximum == 2048
    assert specs["density"].kind == "float" and specs["density"].maximum == 1.0
    assert specs["init"].kind == "choice" and "soup" in specs["init"].choices
    assert "array" not in specs["init"].choices  # UI cannot produce out-of-band arrays
    assert specs["boundary"].choices == ("torus", "dead")
    assert specs["seed"].role == "seed"
    assert specs["rule"].label == "Rule (B/S)"


def test_registry_consistency() -> None:
    assert "lifelike" in FAMILIES
    for family in FAMILIES.values():
        names = {s.name for s in field_specs(family.params_cls)}
        assert family.hot_fields <= names, f"{family.key}: hot fields must be real params"
        defaults = family.params_cls().to_dict()
        for preset_name, overrides in family.presets.items():
            assert set(overrides) <= names, f"{family.key}/{preset_name}: unknown override"
            params = family.params_cls.from_dict(defaults | dict(overrides))
            assert family.validate(params) is None, f"{family.key}/{preset_name}: invalid preset"
            family.build(params)  # must construct


def test_validate_flags_bad_rule() -> None:
    family = FAMILIES["lifelike"]
    params = family.params_cls.from_dict({"rule": "garbage"})
    problem = family.validate(params)
    assert problem is not None
    assert problem[0] == "rule"
