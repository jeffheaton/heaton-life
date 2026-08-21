"""Cellular automata family.

Rule parsers stay in their family modules (`heaton_life.ca.rulestring` for
Life-like, `heaton_life.ca.mergelife` for MergeLife) — both families call
theirs `parse_rule`/`canonical_rule`, so the module is the namespace.
"""

from heaton_life.ca.cyclic import Cyclic, CyclicParams
from heaton_life.ca.elementary import Elementary, ElementaryParams
from heaton_life.ca.lifelike import LifeLike, LifeLikeParams
from heaton_life.ca.mergelife import MergeLife, MergeLifeParams
from heaton_life.ca.mergelife_gallery import MERGELIFE_GALLERY, FeaturedRule
from heaton_life.ca.rulestring import RULE_PRESETS
from heaton_life.ca.wireworld import Wireworld, WireworldParams, clock_loop, wireworld_from_text

__all__ = [
    "MERGELIFE_GALLERY",
    "RULE_PRESETS",
    "Cyclic",
    "CyclicParams",
    "Elementary",
    "ElementaryParams",
    "FeaturedRule",
    "LifeLike",
    "LifeLikeParams",
    "MergeLife",
    "MergeLifeParams",
    "Wireworld",
    "WireworldParams",
    "clock_loop",
    "wireworld_from_text",
]
