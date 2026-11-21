"""Life-like rule conformance: replay vectors/rules/ — rule text to its canonical string,
neighborhood and table, or an error (spec/rules.md). The .NET suite replays the same
files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from heaton_life.ca.rulestring import compile_rule

VECTOR_ROOT = Path(__file__).resolve().parents[2] / "vectors" / "rules"
CASES = sorted(VECTOR_ROOT.glob("*/params.json"))
SPEC_VERSIONS = {"0.16.0"}
_KEYS = {"spec_version", "family", "tier", "cases"}
_RULE = {"input", "canonical", "neighborhood", "table"}
_ERROR = {"input", "error"}


def _hex(table: bytes) -> str:
    """spec/rules.md "Vector encoding": 128 hex digits, entry 0 in the first one's high bit."""
    return int("".join(map(str, table)), 2).to_bytes(64, "big").hex()


def test_rule_vectors_exist() -> None:
    names = {case.parent.name for case in CASES}
    expected = {"totalistic", "isotropic", "isotropic-classes", "map", "hexagonal"}
    assert expected | {"von-neumann", "errors"} <= names


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.parent.name)
def test_rule_vector(case: Path) -> None:
    meta: dict[str, Any] = json.loads(case.read_text())
    assert set(meta) == _KEYS
    assert meta["spec_version"] in SPEC_VERSIONS
    assert (meta["family"], meta["tier"]) == ("rules", "bit-exact")
    for entry in meta["cases"]:
        text = entry["input"]
        if entry.get("error"):
            assert set(entry) == _ERROR
            with pytest.raises(ValueError):
                compile_rule(text, presets=False)
            continue
        assert set(entry) == _RULE
        rule = compile_rule(text, presets=False)
        assert rule.canonical == entry["canonical"], text
        assert rule.neighborhood == entry["neighborhood"], text
        assert _hex(rule.table) == entry["table"], text
        # The canonical string compiles to the same rule (spec/rules.md "Canonical form").
        assert compile_rule(rule.canonical, presets=False) == rule, text
