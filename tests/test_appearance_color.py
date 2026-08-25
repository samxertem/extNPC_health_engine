"""
Colour from modelled traits (item E2), and the claim underneath it.
===================================================================

The easy version of this feature maps `skin_tone` 0..1 onto a hand-picked
gradient. It renders identically to the real one and supports no claim at all,
because the gradient is the author's taste and the trait merely indexes it. So
the module turns the arrow around: the trait places a villager on a published
path through CIE L*a*b*, and ITA is then MEASURED from that point by Chardon's
formula rather than imposed on it.

THE TESTS THAT MATTER ARE THE ONES THAT WOULD CATCH THE EASY VERSION. Asserting
that dark skin comes out darker cannot fail against a ramp. What can fail:

  * the CIE conversion has to be the real one, checked against colours whose
    L*a*b* coordinates are published to four decimals -- a hand-tuned
    approximation passes every monotonicity test and lands the wrong colours;
  * the ITA of each anchor has to fall in the Del Bino class the anchor was
    chosen for, which is a check on the LOCUS, and would fail if someone
    nudged an L* to make a render look nicer;
  * and the channels have to be independent, or "colour from the genome" is
    one number driving four things.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from health_engine.appearance_color import (
    EYE_COLORS,
    SKIN_LOCUS,
    appearance_colors,
    clothing_color,
    eye_color,
    hair_color,
    ita_class,
    ita_degrees,
    lab_to_srgb,
    rgb_hex,
    skin_color,
    skin_lab,
)


# ----------------------------------------------------------------------
# the CIE conversion, against published coordinates
# ----------------------------------------------------------------------

@pytest.mark.parametrize("lab,expected,what", [
    ((100.0, 0.0, 0.0), (255, 255, 255), "D65 white"),
    ((0.0, 0.0, 0.0), (0, 0, 0), "black"),
    ((53.2408, 80.0925, 67.2032), (255, 0, 0), "sRGB red"),
    ((87.7347, -86.1827, 83.1793), (0, 255, 0), "sRGB green"),
    ((32.2970, 79.1875, -107.8602), (0, 0, 255), "sRGB blue"),
    ((53.5850, 0.0, 0.0), (128, 128, 128), "mid grey"),
])
def test_lab_to_srgb_matches_published_coordinates(lab, expected, what):
    """The conversion is the standard one or it is not evidence.

    These L*a*b* values are the published D65 coordinates of the sRGB
    primaries, so any hand-rolled approximation -- a linear ramp, a forgotten
    gamma, the wrong white point -- misses them while still producing colours
    that look like colours.
    """
    got = lab_to_srgb(*lab)
    for channel in range(3):
        assert abs(got[channel] - expected[channel]) <= 1, (
            f"{what}: got {got}, expected {expected}")


def test_the_gamma_transfer_function_is_not_a_plain_power():
    """sRGB is a linear segment near black and a power curve above it. Using
    the power curve everywhere is the classic shortcut and is wrong exactly
    where skin in shadow lives."""
    # L*=1 is inside the linear segment; a plain 1/2.4 power gives a much
    # lighter value than the piecewise definition.
    r, g, b = lab_to_srgb(1.0, 0.0, 0.0)
    assert 0 < r <= 5, f"near-black came out at {r}, the linear segment is missing"


# ----------------------------------------------------------------------
# ITA is measured, not looked up
# ----------------------------------------------------------------------

def test_ita_is_the_published_formula():
    """ITA = arctan((L* - 50) / b*) in degrees (Chardon et al. 1991)."""
    assert ita_degrees(50.0, 20.0) == pytest.approx(0.0)
    assert ita_degrees(70.0, 20.0) == pytest.approx(45.0)
    assert ita_degrees(30.0, 20.0) == pytest.approx(-45.0)
    # b* = 0 is off the skin locus but must not raise three frames away.
    assert ita_degrees(70.0, 0.0) == 90.0
    assert ita_degrees(30.0, 0.0) == -90.0


@pytest.mark.parametrize("ita,expected", [
    (60.0, "very light"), (55.1, "very light"),
    (50.0, "light"), (41.1, "light"),
    (35.0, "intermediate"), (28.1, "intermediate"),
    (20.0, "tan"), (10.1, "tan"),
    (0.0, "brown"), (-29.9, "brown"),
    (-30.0, "dark"), (-45.0, "dark"),
])
def test_ita_classes_are_del_binos_boundaries(ita, expected):
    """Pinned at the boundaries, where an off-by-one comparison hides."""
    assert ita_class(ita) == expected


def test_every_locus_anchor_lands_in_the_class_it_was_chosen_for():
    """A CHECK ON THE LOCUS ITSELF, and the reason ITA is measured rather than
    assigned. The six anchors were picked as representative of Del Bino's six
    classes; if someone nudges an L* to make a render look nicer, the anchor
    slides into a neighbouring class and this fails. An assigned ITA could not
    notice.
    """
    expected = ["very light", "light", "intermediate", "tan", "brown", "dark"]
    got = [skin_color(tone)["ita_class"] for tone, _, _, _ in SKIN_LOCUS]
    assert got == expected


def test_ita_falls_monotonically_as_skin_tone_rises():
    """`skin_tone` is 0=light..1=dark, and ITA runs the other way by
    definition. A locus that folded back would give two tones one colour."""
    itas = [skin_color(t / 20.0)["ita_degrees"] for t in range(21)]
    assert itas == sorted(itas, reverse=True)
    assert itas[0] > 50.0 and itas[-1] < -30.0


def test_skin_carries_the_evidence_and_not_just_a_hex():
    """A hex alone is the unfalsifiable ramp this module exists to avoid: a
    reader has to be able to recompute the ITA from the point."""
    s = skin_color(0.4)
    lightness, _, yellow = s["lab"]
    assert s["ita_degrees"] == pytest.approx(ita_degrees(lightness, yellow), abs=0.05)
    assert s["ita_class"] == ita_class(s["ita_degrees"])
    assert s["hex"].startswith("#") and len(s["hex"]) == 7


# ----------------------------------------------------------------------
# clamping, because a colour past the end of a locus is an invention
# ----------------------------------------------------------------------

@pytest.mark.parametrize("out_of_range", [-5.0, -0.001, 1.001, 99.0])
def test_values_outside_the_traits_range_clamp_rather_than_extrapolate(out_of_range):
    """Every trait here is clipped to 0..1 by its TraitSpec, so out of range
    means the caller passed something that is not that trait. Extrapolating
    past a published locus would be the module's one unforced claim."""
    got = skin_lab(out_of_range)
    ends = (skin_lab(0.0), skin_lab(1.0))
    assert got in ends


# ----------------------------------------------------------------------
# the channels are independent
# ----------------------------------------------------------------------

def test_skin_and_hair_move_independently():
    """Otherwise "colour from the genome" is one number driving everything,
    and every dark-haired villager would necessarily have dark skin."""
    pale_dark_haired = appearance_colors(
        {"skin_tone": 0.05, "hair_pigment": 0.95, "eye_color": "blue"}, "A-1")
    dark_pale_haired = appearance_colors(
        {"skin_tone": 0.95, "hair_pigment": 0.05, "eye_color": "blue"}, "A-1")
    assert pale_dark_haired["skin"] != dark_pale_haired["skin"]
    assert pale_dark_haired["hair"] != dark_pale_haired["hair"]
    # The pale-skinned one has the darker hair: the channels crossed over.
    assert pale_dark_haired["hair"] < dark_pale_haired["hair"]


def test_hair_darkens_monotonically():
    values = [hair_color(p / 10.0) for p in range(11)]
    assert values == sorted(values, reverse=True)
    assert len(set(values)) == len(values), "the ramp has a flat spot"


def test_each_eye_label_gets_its_own_colour():
    seen = {eye_color(label) for label in EYE_COLORS}
    assert len(seen) == len(EYE_COLORS)


def test_an_unknown_eye_label_falls_back_rather_than_raising():
    """`eye_color` is a calibrated categorical whose labels could grow. A
    villager with no eyes is a worse failure than one with a middle colour."""
    assert eye_color("amber") == rgb_hex(EYE_COLORS["hazel"])
    assert eye_color(None) == rgb_hex(EYE_COLORS["hazel"])
    assert eye_color("BROWN") == rgb_hex(EYE_COLORS["brown"]), "case must not matter"


# ----------------------------------------------------------------------
# what is cosmetic must stay cosmetic
# ----------------------------------------------------------------------

def test_clothing_colour_is_a_pure_function_of_the_name():
    """A cosmetic channel that drifted between runs would make two exports of
    one world disagree, and a reader would read the difference as change."""
    assert clothing_color("Ada-16") == clothing_color("Ada-16")
    assert clothing_color("Ada-16") != clothing_color("Ada-16", channel="shoes_color")


def test_clothing_colour_ignores_the_phenotype_entirely():
    """THE ASSERTION THAT KEEPS THE PICTURE HONEST. If a garment colour moved
    with a trait, a reader comparing two siblings' coats would be reading
    inheritance into a hash, and the manifest's provenance block would be
    lying."""
    pale = appearance_colors({"skin_tone": 0.0, "hair_pigment": 0.0,
                              "eye_color": "blue"}, "Ada-16")
    dark = appearance_colors({"skin_tone": 1.0, "hair_pigment": 1.0,
                              "eye_color": "brown"}, "Ada-16")
    assert pale["clothes"] == dark["clothes"]
    assert pale["shoes"] == dark["shoes"]
    assert pale["skin"] != dark["skin"]


def test_provenance_names_every_channel_it_returns():
    """A picture that does not say which channels are measured invites a
    reader to see inheritance in the coats."""
    out = appearance_colors({"skin_tone": 0.4, "hair_pigment": 0.5,
                             "eye_color": "hazel"}, "Ada-16")
    coloured = {k for k, v in out.items()
                if isinstance(v, str) and v.startswith("#")}
    assert coloured <= set(out["provenance"]), (
        f"channels with no provenance: {sorted(coloured - set(out['provenance']))}")
    assert "cosmetic" in out["provenance"]["clothes"]
    assert "measured" in out["provenance"]["skin"]


def test_a_phenotype_missing_pigmentation_still_yields_a_colour():
    """Bare-body exports and older phenotypes exist. A KeyError here would
    take down an export rather than lose a colour."""
    out = appearance_colors({}, "Ada-16")
    assert out["skin"].startswith("#")
    assert out["hair"].startswith("#")
    assert out["eyes"].startswith("#")
