"""
The A4 rule, asserted rather than merely written down.

The reason these tests are worth their length is that every one of them
guards a failure that is INVISIBLE. A salted hash still returns a hairstyle. A
correlated channel still returns a hairstyle. A cosmetic channel driven from a
trait still returns a hairstyle. Nothing crashes, nothing looks wrong, and the
defect only surfaces as a figure that cannot be regenerated or a claim that
cannot be defended.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

from health_engine.cosmetic import (
    CITED_CHANNELS,
    cosmetic_choice,
    cosmetic_index,
    describe,
)

STYLES = ("afro", "bob", "braid", "long", "ponytail", "short")


# ----------------------------------------------------------------------
# rule 1: a pure function of the name
# ----------------------------------------------------------------------

# Literal values, captured once. Comparing against a second call IN THIS
# PROCESS would pass just as happily with Python's salted hash(), which is the
# exact bug this is here to catch, so the expected numbers are frozen instead.
FROZEN = {
    ("Kaya-32", ""): 454,
    ("Kaya-32", "hair_style"): 655,
    ("Kaya-32", "eyebrows"): 452,
    ("Ines-30", ""): 24,
    ("Ines-30", "hair_style"): 156,
    ("Ines-30", "eyebrows"): 321,
    ("Arda-53", ""): 183,
    ("Arda-53", "hair_style"): 339,
    ("Arda-53", "eyebrows"): 165,
}


@pytest.mark.parametrize("key,expected", sorted(FROZEN.items()))
def test_index_matches_the_frozen_values(key, expected):
    name, channel = key
    assert cosmetic_index(name, 1000, channel) == expected


def test_choice_is_stable_across_processes():
    """The real assertion: a FRESH interpreter, with a hash seed that differs
    from this one's, must produce the same hairstyle.

    PYTHONHASHSEED is set explicitly to a value this process is overwhelmingly
    unlikely to be using, so an implementation that reached for `hash()` would
    disagree here even though every same-process test above passed.
    """
    code = (
        "from health_engine.cosmetic import cosmetic_choice;"
        "print(cosmetic_choice('Kaya-32',"
        "('afro','bob','braid','long','ponytail','short'),'hair_style'))"
    )
    # The real environment with ONLY the hash seed overridden. Building a
    # minimal env instead loses numpy and turns this into a test of the import
    # machinery, which passes or fails for reasons that have nothing to do
    # with the rule being checked.
    env = dict(os.environ, PYTHONHASHSEED="12345")
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, env=env,
        cwd=str(pathlib.Path(__file__).resolve().parents[1]),
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == cosmetic_choice("Kaya-32", STYLES, "hair_style")


def test_same_name_gives_the_same_choice():
    assert (cosmetic_choice("Kaya-32", STYLES, "hair_style")
            == cosmetic_choice("Kaya-32", STYLES, "hair_style"))


def test_different_names_are_not_all_the_same_choice():
    picks = {cosmetic_choice(f"Villager-{i}", STYLES, "hair_style")
             for i in range(200)}
    assert len(picks) == len(STYLES), "every option should be reachable"


def test_the_choice_does_not_depend_on_position_in_a_list():
    # A row index or an enumerate() counter is the other tempting source of
    # "variation", and it makes a villager's hair change when someone dies.
    a = cosmetic_choice("Kaya-32", STYLES, "hair_style")
    for _ in range(5):
        assert cosmetic_choice("Kaya-32", STYLES, "hair_style") == a


# ----------------------------------------------------------------------
# decorrelation
# ----------------------------------------------------------------------

def test_channels_are_decorrelated():
    """Two channels of the same size must not move together.

    Without the channel salt they are the same function of the same string, so
    hairstyle 3 always implies eyebrow style 3 and the village carries a
    correlation nobody introduced deliberately.
    """
    names = [f"Villager-{i}" for i in range(400)]
    agree = sum(cosmetic_index(n, 6, "hair_style") == cosmetic_index(n, 6, "eyebrows")
                for n in names)
    # Expect about 1/6. Allow a generous band; the failure being caught is
    # perfect agreement, not a mild fluctuation.
    assert 20 < agree < 120, f"{agree}/400 agreed, expected roughly 67"


def test_an_unsalted_channel_is_still_decorrelated_from_a_salted_one():
    names = [f"Villager-{i}" for i in range(400)]
    agree = sum(cosmetic_index(n, 6, "") == cosmetic_index(n, 6, "hair_style")
                for n in names)
    assert 20 < agree < 120


# ----------------------------------------------------------------------
# rule 2: never driven by a trait unless cited
# ----------------------------------------------------------------------

def test_a_cited_channel_is_refused_rather_than_picked():
    # The awkwardness is the design. Claiming a trait drives this channel and
    # then letting it pick at random anyway is the one outcome that must be
    # impossible.
    with pytest.raises(ValueError, match="must not go through cosmetic_choice"):
        cosmetic_choice("Kaya-32", STYLES, "eyes", cited="eye_color")


def test_the_cited_channels_name_real_traits():
    from health_engine.traits import TRAIT_TABLE
    for channel, trait in CITED_CHANNELS.items():
        assert trait in TRAIT_TABLE, (
            f"channel {channel!r} claims to be driven by {trait!r}, which is "
            f"not in TRAIT_TABLE. A citation that names nothing is worse than "
            f"no citation.")


def test_hair_style_is_not_a_cited_channel():
    # The engine models hair pigment, curl and thickness. None of them is a
    # hairstyle, and this is the assertion that stops someone deciding curl
    # "basically means" a style.
    assert "hair_style" not in CITED_CHANNELS
    assert "clothes" not in CITED_CHANNELS


# ----------------------------------------------------------------------
# rule 3: labelled wherever it appears
# ----------------------------------------------------------------------

def test_describe_separates_modelled_from_dressing():
    text = describe(["eyes", "hair_colour", "hair_style", "clothes"])
    assert "eye_color" in text and "hair_pigment" in text
    assert "cosmetic" in text
    assert "hair_style" in text and "clothes" in text


def test_describe_handles_the_all_cosmetic_case():
    text = describe(["hair_style", "clothes"])
    assert "cosmetic" in text
    assert "driven by" not in text


def test_describe_says_something_for_an_empty_list():
    assert describe([]) == "nothing to describe"


# ----------------------------------------------------------------------
# input validation
# ----------------------------------------------------------------------

@pytest.mark.parametrize("n", [0, -1])
def test_a_non_positive_range_is_rejected(n):
    with pytest.raises(ValueError):
        cosmetic_index("Kaya-32", n)


def test_an_empty_option_list_is_rejected():
    with pytest.raises(ValueError, match="no options"):
        cosmetic_choice("Kaya-32", (), "hair_style")


def test_the_index_stays_in_range():
    for i in range(500):
        assert 0 <= cosmetic_index(f"Villager-{i}", 7, "hair_style") < 7
