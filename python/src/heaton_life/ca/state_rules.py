"""State rules: what the multi-state HashLife knows of a rule (spec/hashlife-multistate.md
"State rules").

A state rule is a number of states S (2 to 256), a canonical name, and a cell function from
the 3×3 block of states around a cell to its next state. The engine computes nothing else
from a rule, so a family plugs in by subclassing ``StateRule``: Wireworld today, and the
Generations, History and Super, and rule-table families as their pages add them. A rule is
named in files by its canonical name, which ``state_rule`` resolves.
"""

from __future__ import annotations

import abc
from typing import Final

from heaton_life.ca.rulestring import _SPACE

MAX_STATES: Final = 256
"""The most states a rule may have: a state is one byte."""

_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


class StateRule(abc.ABC):
    """A rule over cell states: ``states`` (S, from 2 to 256), ``canonical`` (the name a file
    gives it), and ``next_state``, the cell function. ``next_state(0, …, 0)`` must be 0: the
    background of the infinite plane never changes."""

    canonical: str
    """The rule's canonical name: printable ASCII, with no whitespace and no comma."""
    states: int
    """S: every state is from 0 to S − 1."""

    @abc.abstractmethod
    def next_state(
        self, nw: int, n: int, ne: int, w: int, c: int, e: int, sw: int, s: int, se: int
    ) -> int:
        """The next state of the center cell ``c`` from its 3×3 block, laid out as
        spec/rules.md lays it out: NW N NE / W C E / SW S SE."""

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.canonical!r}, states={self.states})"


def _ascii_lower(text: str) -> str:
    return text.translate(_LOWER)


def _trimmed(text: str) -> str:
    """``text`` without spec/rules.md's whitespace at its two ends."""
    start, end = 0, len(text)
    while start < end and text[start] in _SPACE:
        start += 1
    while end > start and text[end - 1] in _SPACE:
        end -= 1
    return text[start:end]


def check_state_rule(rule: StateRule) -> StateRule:
    """``rule`` itself, once it is known to be one the engine can run: 2 to 256 states, a
    canonical name a file can carry, and a background that stays 0. Raises ValueError (or
    TypeError for something that is no ``StateRule``)."""
    if not isinstance(rule, StateRule):
        raise TypeError(f"expected a StateRule, got {type(rule).__name__}")
    states = rule.states
    if not isinstance(states, int) or not 2 <= states <= MAX_STATES:
        raise ValueError(f"a state rule has 2 to {MAX_STATES} states, not {states!r}")
    name = rule.canonical
    if (
        not isinstance(name, str)
        or not name
        or not name.isascii()
        or not name.isprintable()
        or any(ch.isspace() or ch == "," for ch in name)
    ):
        raise ValueError(
            f"a state rule's canonical name is printable ASCII without spaces or commas, "
            f"not {name!r}"
        )
    if rule.next_state(0, 0, 0, 0, 0, 0, 0, 0, 0) != 0:
        raise ValueError(
            f"{name} turns an all-0 block into another state: the infinite background would "
            'change (spec/hashlife-multistate.md "State rules")'
        )
    return rule


def _known() -> tuple[StateRule, ...]:
    """Every rule that has a name (spec/hashlife-multistate.md "Names")."""
    # Imported here: the families import this module for StateRule.
    from heaton_life.ca.wireworld import WIREWORLD_RULE

    return (WIREWORLD_RULE,)


def state_rule(text: str) -> StateRule:
    """The state rule a text gives (spec/hashlife-multistate.md "Names"): a name, with
    whitespace at the two ends allowed and ASCII case ignored (WireWorld and the rule-table
    starter set, spec/ruletable.md), a History rule (spec/history.md), or a Generations rule
    in either spelling (spec/generations.md). Raises ValueError for any other text."""
    if not isinstance(text, str):
        raise TypeError(f"a rule name is text, not {type(text).__name__}")
    key = _ascii_lower(_trimmed(text))
    for rule in _known():
        if _ascii_lower(rule.canonical) == key:
            return rule
    # History rules, a family named by any Life-like rule's text (spec/history.md).
    from heaton_life.ca.history import history_rule

    history = history_rule(text)
    if history is not None:
        return history
    # Generations rules, in either spelling (spec/generations.md).
    from heaton_life.ca.generations import try_compile_generations_rule

    generations, _ = try_compile_generations_rule(text)
    if generations is not None:
        return generations
    # The rule-table starter set (spec/ruletable.md "The starter set"), read when named.
    from heaton_life.ca.ruletable import STARTER_RULES, starter_rule_or_none

    starter = starter_rule_or_none(_trimmed(text))
    if starter is not None:
        return starter
    from heaton_life.ca.ltl import ltl_refusal  # Larger than Life: grids only (spec/ltl.md)

    refusal = ltl_refusal(text)
    if refusal is not None:
        raise ValueError(refusal)
    names = ", ".join([*(rule.canonical for rule in _known()), *STARTER_RULES])
    raise ValueError(
        f"{text!r} is not a state rule (known: {names}, History rules such as B3/S23History, "
        "and Generations rules such as B2/S345/C4)"
    )


def names_rule(text: str, rule: StateRule) -> bool:
    """Whether ``text`` names ``rule``: its canonical name, ignoring whitespace at the ends
    and ASCII case."""
    return _ascii_lower(_trimmed(text)) == _ascii_lower(rule.canonical)


def resolve_rule(rule: str | StateRule) -> StateRule:
    """A rule given by name or as an object, checked."""
    return check_state_rule(state_rule(rule) if isinstance(rule, str) else rule)
