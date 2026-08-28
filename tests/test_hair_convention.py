"""
The sex-conditioned hairstyle, and the line between modelled and invented.
==========================================================================

Hairstyle is the first channel in the project that is neither cited nor
cosmetic. Sex is modelled -- genetically determined in `sexchrom.py`, from
whether the father contributed an X or a Y -- so a village where men and women
wear different hair is showing something real. WHICH styles lean which way is
invented, because the CC0 pack labels its ten hairstyles `Afro01`, `Bob01`,
`Braid01`, `Long01`, `Ponytail01` and `Short01` to `Short04`, every one after
the style and not one after a wearer. The clothes are the contrast that makes
the point: their author named them `female_casualsuit01` and
`male_worksuit01`, so `_clothing_for` reads metadata while this reads nobody.

WHAT IS WORTH TESTING, given that a convention cannot be checked against
nature. Not the weights; they are an opinion and a test asserting an opinion
is a check that cannot fail. What can fail, and what would be expensive to
discover in a viva:

  * that the conditioning is REAL, so a caption claiming it is not decoration;
  * that it is a LEANING and not a partition, because a partition looks
    exactly like a finding to anyone reading the lineup;
  * that rule 1 survives, so the same villager wears the same hair for ever;
  * and that the shipped pack can never quietly gain a style carrying no
    declared leaning while a caption claims one for it.

That last one is the guard that replaced a runtime refusal, and
`hair_weights` argues for the trade at its definition.
"""

from __future__ import annotations

import sys
import warnings
from collections import Counter
from pathlib import Path

import pytest

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from health_engine.cosmetic import (CONVENTION_CHANNELS, conventional_choice,
                                    describe)
from health_engine.hair_convention import (NO_LEANING, WEIGHTS, hair_weights,
                                           undeclared)
from health_engine.mhm_assets import load_catalogue

STYLES = tuple(sorted(WEIGHTS))
NAMES = tuple(f"Villager-{i}" for i in range(4000))


def _distribution(sex):
    picks = [conventional_choice(n, STYLES, hair_weights(STYLES, sex),
                                 channel="hair") for n in NAMES]
    return Counter(picks)


# ----------------------------------------------------------------------
# the completeness guard, which is the one that protects a caption
# ----------------------------------------------------------------------

def test_every_shipped_hairstyle_is_declared():
    """The pack cannot gain a style with no declared leaning unnoticed.

    `hair_weights` deliberately falls back to NO_LEANING instead of raising,
    so that a pack with an extra style still bakes. That trade is only honest
    if the SHIPPED pack is checked somewhere, and this is somewhere.
    """
    installed = load_catalogue().keys("hair")
    assert installed, "no hair assets installed; this test proves nothing"
    missing = undeclared(installed)
    assert not missing, (
        f"hairstyles {list(missing)} are installed but carry no declared "
        f"leaning in hair_convention.WEIGHTS. They would silently be treated "
        f"as unisex while a caption claims a sex-conditioned distribution.")


def test_the_declared_table_does_not_invent_styles_the_pack_lacks():
    """The other direction. A weight for a style nobody ships is a convention
    about nothing, and usually the residue of a rename."""
    installed = set(load_catalogue().keys("hair"))
    stray = sorted(set(WEIGHTS) - installed)
    assert not stray, f"declared but not installed: {stray}"


# ----------------------------------------------------------------------
# the conditioning is real
# ----------------------------------------------------------------------

def test_men_and_women_draw_from_different_distributions():
    """The claim the third category exists to support. If this fails, the
    conditioning is decoration and the caption is wrong."""
    female, male = _distribution("female"), _distribution("male")
    assert female != male

    # And in the declared direction, not merely differently. Bob01 is declared
    # 3 to 1 toward women, Short01 3 to 1 toward men.
    assert female["Bob01"] > male["Bob01"]
    assert male["Short01"] > female["Short01"]


def test_the_leaning_is_close_to_the_declared_ratio():
    """3 to 1 declared, so about 3 to 1 delivered.

    Loose bounds on purpose. This is checking that the weights are USED, not
    that a hash is uniform, and a tight bound here would be a flaky test
    asserting a property nobody needs.
    """
    female, male = _distribution("female"), _distribution("male")
    ratio = female["Braid01"] / max(1, male["Braid01"])
    assert 2.0 < ratio < 4.5, f"declared 3 to 1, delivered {ratio:.2f} to 1"


def test_no_style_is_closed_to_either_sex():
    """A leaning, not a partition, and this is the assertion that says so.

    A village where no man has ever worn a braid is a much stronger statement
    than an invented table may make, and it is the reading a viewer would take
    from a lineup with no counter-examples in it.
    """
    female, male = _distribution("female"), _distribution("male")
    for style in STYLES:
        assert female[style] > 0, f"no woman ever wears {style}"
        assert male[style] > 0, f"no man ever wears {style}"


def test_a_zero_weight_is_refused():
    """The partition is refused at the mechanism, not left to reviewers."""
    with pytest.raises(ValueError, match="zero"):
        conventional_choice("Ada-16", ("A", "B"), (1.0, 0.0), channel="hair")


def test_mismatched_weights_are_refused():
    with pytest.raises(ValueError, match="one to one"):
        conventional_choice("Ada-16", ("A", "B", "C"), (1.0, 1.0),
                            channel="hair")


# ----------------------------------------------------------------------
# rule 1 still holds
# ----------------------------------------------------------------------

def test_the_same_villager_wears_the_same_hair_every_time():
    weights = hair_weights(STYLES, "female")
    first = conventional_choice("Ada-16", STYLES, weights, channel="hair")
    for _ in range(50):
        assert conventional_choice("Ada-16", STYLES, weights,
                                   channel="hair") == first


def test_the_choice_does_not_depend_on_a_salted_hash():
    """Literal expected values, not a second call in this process.

    A second call would agree with `hash()` too, which is the trap the
    cosmetic module was written around: PYTHONHASHSEED changes per process, so
    a figure could not be regenerated to match the one in the paper.

    These three are PINNED OBSERVATIONS, not derivations, and the distinction
    matters when one of them changes. They were read out of this
    implementation and confirmed identical under PYTHONHASHSEED 0, 1 and
    12345. So a failure here does not mean the answer is wrong; it means the
    mapping from names to styles MOVED, and every previously baked village
    disagrees with the next one. That is worth a deliberate decision and a
    re-bake rather than a quiet update of this line.
    """
    weights = hair_weights(STYLES, "female")
    got = [conventional_choice(n, STYLES, weights, channel="hair")
           for n in ("Ada-16", "Bran-10", "Zoe-41")]
    assert got == ["Short01", "Braid01", "Long01"], got


def test_an_undeclared_style_gets_no_leaning_rather_than_a_borrowed_one():
    """The fallback is neutral, not inherited from a neighbour in sort order."""
    styles = ("Afro01", "BrandNew99")
    assert hair_weights(styles, "female")[1] == NO_LEANING[0]
    assert hair_weights(styles, "male")[1] == NO_LEANING[1]


# ----------------------------------------------------------------------
# and it says so out loud
# ----------------------------------------------------------------------

def test_the_channel_is_registered_as_a_convention():
    assert CONVENTION_CHANNELS["hair"] == "sex"


def test_describe_calls_it_a_convention_in_front_of_a_reader():
    """The one line separating "the genome did this" from "we decided this"
    for a channel where the picture cannot show which."""
    line = describe(["hair", "eyes", "teeth"])
    assert "convention" in line
    assert "hair (sex)" in line
    # and it must not have been quietly filed under either neighbour
    assert "cosmetic, from the name only: teeth" in line
    assert "eyes (eye_color)" in line
