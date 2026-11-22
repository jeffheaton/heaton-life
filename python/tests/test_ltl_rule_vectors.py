"""Larger than Life conformance: replay vectors/ltl-rules/ — rule texts to their canonical
form and parts, or the reason a text is no rule, and each neighborhood's half-widths and
size at chosen ranges (spec/ltl.md). The .NET suite replays the same files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from heaton_life.ca.ltl import half_widths, parse_ltl_rule, try_parse_ltl_rule

VECTOR_ROOT = Path(__file__).resolve().parents[2] / "vectors" / "ltl-rules"
CASES = sorted(VECTOR_ROOT.glob("*/params.json"))
SPEC_VERSIONS = {"0.16.0"}
_KEYS = {"spec_version", "family", "tier", "kind", "cases"}
_RULE = {"input", "canonical", "range", "states", "middle", "survival", "birth"}
_RULE |= {"neighborhood", "size"}
_ERROR = {"input", "error", "reason"}
_HOOD = {"neighborhood", "range", "half_widths", "size"}


def test_ltl_rule_vectors_exist() -> None:
    kinds = {json.loads(c.read_text(encoding="utf-8"))["kind"] for c in CASES}
    assert kinds == {"rules", "neighborhoods"}


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.parent.name)
def test_ltl_rule_vector(case: Path) -> None:
    meta: dict[str, Any] = json.loads(case.read_text(encoding="utf-8"))
    assert set(meta) == _KEYS
    assert meta["spec_version"] in SPEC_VERSIONS
    assert (meta["family"], meta["tier"]) == ("ltl-rules", "bit-exact")
    for entry in meta["cases"]:
        if meta["kind"] == "neighborhoods":
            assert set(entry) == _HOOD
            widths = half_widths(entry["range"], entry["neighborhood"])
            assert list(widths) == entry["half_widths"]
            assert sum(2 * w + 1 for w in widths) == entry["size"]
            continue
        assert meta["kind"] == "rules"
        text = entry["input"]
        if entry.get("error"):
            assert set(entry) == _ERROR
            assert try_parse_ltl_rule(text) == (None, entry["reason"])
            with pytest.raises(ValueError) as error:
                parse_ltl_rule(text)
            reason = entry["reason"]
            assert (
                str(error.value)
                == f"invalid Larger than Life rule '{text}': {reason} (spec/ltl.md)"
            )
            continue
        assert set(entry) == _RULE
        rule = parse_ltl_rule(text)
        found = (rule.canonical, rule.range, rule.states, rule.middle, list(rule.survival))
        wanted = (
            entry["canonical"],
            entry["range"],
            entry["states"],
            entry["middle"],
            entry["survival"],
        )
        assert found == wanted, text
        assert list(rule.birth) == entry["birth"]
        assert (rule.neighborhood, rule.size) == (entry["neighborhood"], entry["size"])
        assert parse_ltl_rule(entry["canonical"]) == rule
