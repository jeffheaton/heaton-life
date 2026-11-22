"""Rule files conformance: replay vectors/ruletable-files/ — every file read and compiled to
its canonical tree with the data its other sections hold, and the reason each refused text
gets (spec/rule-files.md, bit-exact). The .NET suite replays the same files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from heaton_life.ca.rulefile import Gradient, RuleFileError, RuleTable, parse_rule_file

VECTOR_ROOT = Path(__file__).resolve().parents[2] / "vectors" / "ruletable-files"
CASES = sorted(VECTOR_ROOT.glob("*/params.json"))
SPEC_VERSIONS = {"0.16.0"}
_COMMON = {"spec_version", "family", "tier", "kind"}
_KEYS = {
    "compile": _COMMON
    | {"input", "tree", "name", "states", "neighbors", "neighborhood", "symmetries", "source"}
    | {"description", "colors", "names", "icons"},
    "reasons": _COMMON | {"cases"},
}


def test_cases_exist() -> None:
    kinds = {json.loads(p.read_text(encoding="utf-8"))["kind"] for p in CASES}
    assert kinds == set(_KEYS)


def _summary(rule: RuleTable) -> dict[str, Any]:
    colors: list[dict[str, Any]] = []
    for entry in rule.colors:
        if isinstance(entry, Gradient):
            colors.append({"from": list(entry.start), "to": list(entry.end)})
        else:
            colors.append({"state": entry.state, "rgb": list(entry.rgb)})
    icons: dict[str, Any] | None = None
    if rule.icons is not None:
        icons = (
            {"style": rule.icons.style}
            if rule.icons.style is not None
            else {
                "sets": [
                    {"width": s.width, "colors": [list(c) for c in s.colors], "rows": list(s.rows)}
                    for s in rule.icons.sets
                ]
            }
        )
    return {
        "name": rule.name,
        "states": rule.states,
        "neighbors": rule.neighbors,
        "neighborhood": rule.neighborhood,
        "symmetries": rule.symmetries,
        "source": rule.source,
        "description": rule.description,
        "colors": colors,
        "names": [{"state": n.state, "name": n.name} for n in rule.names],
        "icons": icons,
    }


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.parent.name)
def test_ruletable_files_vector(case: Path) -> None:
    d = case.parent
    meta = json.loads(case.read_text(encoding="utf-8"))
    kind = meta["kind"]
    assert meta["family"] == "ruletable-files" and meta["tier"] == "bit-exact"
    assert meta["spec_version"] in SPEC_VERSIONS
    assert set(meta) == _KEYS[kind], set(meta) ^ _KEYS[kind]
    if kind == "compile":
        text = (d / meta["input"]).read_bytes().decode("utf-8")
        rule = parse_rule_file(text)
        assert rule.tree_text() == (d / meta["tree"]).read_text(encoding="utf-8")
        expected = {key: meta[key] for key in _KEYS["compile"] - _COMMON - {"input", "tree"}}
        assert _summary(rule) == expected
    else:
        for entry in meta["cases"]:
            assert set(entry) == {"text", "reason", "line"}, entry
            with pytest.raises(RuleFileError) as caught:
                parse_rule_file(entry["text"])
            assert (caught.value.reason, caught.value.line) == (entry["reason"], entry["line"]), (
                entry["text"]
            )
            where = "" if entry["line"] is None else f"line {entry['line']}: "
            assert str(caught.value) == (
                f"invalid rule file: {where}{entry['reason']} (spec/rule-files.md)"
            )
