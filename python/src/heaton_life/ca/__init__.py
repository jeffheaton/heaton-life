"""Cellular automata family.

Rule parsers stay in their family modules (`heaton_life.ca.rulestring` for
Life-like, `heaton_life.ca.mergelife` for MergeLife) — both families call
theirs `parse_rule`/`canonical_rule`, so the module is the namespace.
"""

from heaton_life.ca.cyclic import Cyclic, CyclicParams
from heaton_life.ca.elementary import Elementary, ElementaryParams
from heaton_life.ca.generations import Generations, GenerationsParams
from heaton_life.ca.hashlife import HashLife, HashLifeParams
from heaton_life.ca.lifelike import LifeLike, LifeLikeParams
from heaton_life.ca.ltl import (
    LargerThanLife,
    LargerThanLifeParams,
    LtlRule,
    parse_ltl_rule,
    try_parse_ltl_rule,
)
from heaton_life.ca.mergelife import MergeLife, MergeLifeParams
from heaton_life.ca.mergelife_gallery import MERGELIFE_GALLERY, FeaturedRule
from heaton_life.ca.rulefile import RuleFileError, RuleTable, parse_rule_file
from heaton_life.ca.rulestring import RULE_PRESETS
from heaton_life.ca.ruletable import (
    STARTER_RULES,
    RuleTableCA,
    RuleTableParams,
    starter_pattern,
    starter_rule,
)
from heaton_life.ca.wireworld import Wireworld, WireworldParams, clock_loop, wireworld_from_text

__all__ = [
    "MERGELIFE_GALLERY",
    "RULE_PRESETS",
    "STARTER_RULES",
    "Cyclic",
    "CyclicParams",
    "Elementary",
    "ElementaryParams",
    "FeaturedRule",
    "Generations",
    "GenerationsParams",
    "HashLife",
    "HashLifeParams",
    "LargerThanLife",
    "LargerThanLifeParams",
    "LifeLike",
    "LifeLikeParams",
    "LtlRule",
    "MergeLife",
    "MergeLifeParams",
    "RuleFileError",
    "RuleTable",
    "RuleTableCA",
    "RuleTableParams",
    "Wireworld",
    "WireworldParams",
    "clock_loop",
    "parse_ltl_rule",
    "parse_rule_file",
    "starter_pattern",
    "starter_rule",
    "try_parse_ltl_rule",
    "wireworld_from_text",
]
