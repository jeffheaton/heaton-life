"""Life-like rulestrings: ``B<digits>/S<digits>`` (birth / survival neighbor counts)."""

from __future__ import annotations

import re

RULE_PRESETS = {
    "life": "B3/S23",
    "highlife": "B36/S23",
    "seeds": "B2/S",
    "daynight": "B3678/S34678",
    "replicator": "B1357/S1357",
    "maze": "B3/S12345",
    "diamoeba": "B35678/S5678",
}

_RULE = re.compile(r"\s*[Bb]([0-8]*)\s*/\s*[Ss]([0-8]*)\s*")


def parse_rule(rule: str) -> tuple[frozenset[int], frozenset[int]]:
    """Parse a rulestring or preset name into (birth, survive) neighbor-count sets."""
    text = RULE_PRESETS.get(rule.strip().lower(), rule)
    m = _RULE.fullmatch(text)
    if m is None:
        raise ValueError(
            f"invalid rulestring {rule!r} (expected 'B<digits>/S<digits>' or one of {sorted(RULE_PRESETS)})"
        )
    birth = frozenset(int(c) for c in m.group(1))
    survive = frozenset(int(c) for c in m.group(2))
    return birth, survive


def canonical_rule(rule: str) -> str:
    """Normalize to sorted uppercase form, e.g. 'b3 / s32' -> 'B3/S23'."""
    birth, survive = parse_rule(rule)
    return f"B{''.join(map(str, sorted(birth)))}/S{''.join(map(str, sorted(survive)))}"
