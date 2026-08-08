"""Cellular automata family."""

from heaton_life.ca.cyclic import Cyclic, CyclicParams
from heaton_life.ca.elementary import Elementary, ElementaryParams
from heaton_life.ca.lifelike import LifeLike, LifeLikeParams
from heaton_life.ca.mergelife import (
    MergeLife,
    MergeLifeParams,
    canonical_genome,
    parse_genome_error,
    random_genome,
)
from heaton_life.ca.rulestring import RULE_PRESETS, canonical_rule, parse_rule
from heaton_life.ca.wireworld import Wireworld, WireworldParams, clock_loop, wireworld_from_text

__all__ = [
    "RULE_PRESETS",
    "Cyclic",
    "CyclicParams",
    "Elementary",
    "ElementaryParams",
    "LifeLike",
    "LifeLikeParams",
    "MergeLife",
    "MergeLifeParams",
    "Wireworld",
    "WireworldParams",
    "canonical_genome",
    "canonical_rule",
    "clock_loop",
    "parse_genome_error",
    "parse_rule",
    "random_genome",
    "wireworld_from_text",
]
