"""Cellular automata family."""

from heaton_life.ca.lifelike import LifeLike, LifeLikeParams
from heaton_life.ca.rulestring import RULE_PRESETS, canonical_rule, parse_rule

__all__ = ["RULE_PRESETS", "LifeLike", "LifeLikeParams", "canonical_rule", "parse_rule"]
