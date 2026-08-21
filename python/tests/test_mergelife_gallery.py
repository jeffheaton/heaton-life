"""Pins for the featured MergeLife rules (spec/mergelife.md "Featured rules").

The catalog is a cross-implementation contract with no vector files behind it
(like the built-in patterns), so the suite is what holds it: every rule must
parse, already be canonical, and actually run; the presentation text must be
present and unambiguous; and the order — which apps show — is part of the set.
"""

import numpy as np
import pytest

from heaton_life.ca import MERGELIFE_GALLERY, MergeLife
from heaton_life.ca.mergelife import canonical_rule, parse_rule_error

GALLERY_SIZE = 15


def test_gallery_matches_the_spec_table() -> None:
    """Size and the two anchored positions the spec calls out."""
    assert len(MERGELIFE_GALLERY) == GALLERY_SIZE
    # Entry 1 is the paper's rule and the family default; entry 2 is the
    # engineered sibling that must sit beside its parent.
    assert MERGELIFE_GALLERY[0].name == "Red World (paper)"
    assert MERGELIFE_GALLERY[0].rule == "e542-5f79-9341-f31e-6c6b-7f08-8773-7068"
    assert MERGELIFE_GALLERY[1].name == "Cobalt Reef"
    assert MERGELIFE_GALLERY[-1].name == "Mood Ring"


def test_the_default_rule_is_the_first_entry() -> None:
    """spec/mergelife.md: 'Entry 1 is the family's default rule.'"""
    assert MergeLife().params.rule == MERGELIFE_GALLERY[0].rule


@pytest.mark.parametrize("entry", MERGELIFE_GALLERY, ids=lambda e: e.name)
def test_every_rule_is_valid_and_already_canonical(entry) -> None:  # type: ignore[no-untyped-def]
    assert parse_rule_error(entry.rule) is None, entry.rule
    # The spec requires the stored form to be canonical, so a host can compare
    # a world's rule against the gallery without normalizing first.
    assert canonical_rule(entry.rule) == entry.rule


@pytest.mark.parametrize("entry", MERGELIFE_GALLERY, ids=lambda e: e.name)
def test_every_entry_carries_presentation_text(entry) -> None:  # type: ignore[no-untyped-def]
    assert entry.name.strip() == entry.name and entry.name
    assert entry.description.strip() == entry.description and entry.description
    assert entry.description.endswith(".")


def test_rules_and_names_are_unique() -> None:
    """A duplicate would show twice in every gallery that renders the set."""
    assert len({e.rule for e in MERGELIFE_GALLERY}) == GALLERY_SIZE
    assert len({e.name for e in MERGELIFE_GALLERY}) == GALLERY_SIZE


def test_cobalt_reef_is_a_permutation_of_red_world() -> None:
    """Its provenance claim in the spec: same octets, reordered."""
    red, cobalt = MERGELIFE_GALLERY[0].rule, MERGELIFE_GALLERY[1].rule
    assert sorted(red.split("-")) == sorted(cobalt.split("-"))
    assert red != cobalt


@pytest.mark.parametrize("entry", MERGELIFE_GALLERY, ids=lambda e: e.name)
def test_every_rule_actually_runs(entry) -> None:  # type: ignore[no-untyped-def]
    """A gallery entry that cannot drive a world is not a featured rule."""
    sim = MergeLife(entry.rule, size=(32, 32), seed=7)
    sim.step(8)
    frame = sim.frame()
    assert frame.shape == (32, 32, 3)
    assert frame.dtype == np.uint8
    assert sim.generation == 8
