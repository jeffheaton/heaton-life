"""Generations rule conformance: replay vectors/generations-rules/ — rule texts in both
spellings to their canonical forms, numbers of states, Life-like rules and tables, and the
reasons a text is refused (spec/generations.md "Rules"). The .NET suite replays the same
files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from heaton_life.ca.generations import compile_generations_rule, try_compile_generations_rule

VECTOR_ROOT = Path(__file__).resolve().parents[2] / "vectors" / "generations-rules"
CASES = sorted(VECTOR_ROOT.glob("*/params.json"))
_TOP = {"spec_version", "family", "tier", "cases"}
_ENTRY = {"input", "canonical", "states", "life", "table", "error", "reason"}


def _table_hex(table: bytes) -> str:
    bits = 0
    for entry in table:
        bits = bits << 1 | entry
    return format(bits, "0128x")


def test_generations_rule_vectors_exist() -> None:
    assert {c.parent.name for c in CASES} == {"canonical", "reasons"}


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.parent.name)
def test_generations_rule_vector(case: Path) -> None:
    meta = json.loads(case.read_text(encoding="utf-8"))
    assert set(meta) == _TOP, set(meta) ^ _TOP
    assert meta["family"] == "generations-rules" and meta["tier"] == "bit-exact"
    assert meta["spec_version"] == "0.16.0"
    for entry in meta["cases"]:
        assert set(entry) <= _ENTRY, set(entry) - _ENTRY
        text = entry["input"]
        rule, reason = try_compile_generations_rule(text)
        if entry.get("error"):
            assert rule is None and reason == entry["reason"], (text, reason)
            with pytest.raises(ValueError, match="invalid Generations rule"):
                compile_generations_rule(text)
            continue
        assert rule is not None, (text, reason)
        assert rule.canonical == entry["canonical"], text
        assert rule.states == entry["states"], text
        assert rule.life.canonical == entry["life"], text
        assert _table_hex(rule.life.table) == entry["table"], text
        assert compile_generations_rule(rule.canonical) == rule  # canonical is a fixed point
