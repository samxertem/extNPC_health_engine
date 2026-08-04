"""
Tests for the developmental trajectory (roadmap #13).

The handoff flagged this as the highest-calibration-risk item left, so the
tests are weighted accordingly. The first block is not about growth at all
-- it is about proving the schedule CANNOT reach the calibrated path. Those
assertions use exact equality on purpose: "approximately identity at
adulthood" is the precise failure mode this item was flagged for, and a
tolerance would hide it.
"""

import numpy as np
import pytest

from health_engine import development as D
from health_engine import validation as V
from health_engine.development import (DRIFT_REFERENCE_AGE, GROWTH,
                                       MATURATION, REFERENCE_AGE,
                                       growth_factor, maturation_offset,
                                       peak_height_velocity_age,
                                       stature_fraction)
from health_engine.npc import random_founder


# ======================================================================
# 1. The calibration must be untouchable
# ======================================================================

def test_identity_at_the_reference_age_is_exact():
    """Not 'close'. Exactly equal, for every trait and both sexes."""
    rng = np.random.default_rng(1)
    for i in range(60):
        npc = random_founder(f"n{i}", rng)
        mature = npc.phenotype()
        at_ref = npc.phenotype_at_age(REFERENCE_AGE)
        assert set(mature) == set(at_ref)
        for trait, value in mature.items():
            assert value == at_ref[trait], trait


def test_plateaus_are_exactly_one():
    for trait, profile in GROWTH.items():
        for sex in ("female", "male"):
            for a in np.linspace(profile.plateau_start, profile.plateau_end, 41):
                assert growth_factor(trait, float(a), sex) == 1.0, (trait, a)


def test_maturation_offset_is_exactly_zero_at_its_reference():
    for trait in MATURATION:
        for sex in ("female", "male"):
            assert maturation_offset(trait, DRIFT_REFERENCE_AGE, sex) == 0.0


def test_phenotype_is_age_blind():
    """The calibrated accessor must not depend on age at all. If someone
    later wires the schedule into `phenotype()`, this fails immediately."""
    rng = np.random.default_rng(2)
    npc = random_founder("a", rng)
    baseline = dict(npc.phenotype())
    for age in (0, 5, 12, 20, 45, 90):
        npc.age = age
        npc._phenotype_cache = None          # force a genuine recompute
        assert npc.phenotype() == baseline


def test_heritability_is_undisturbed():
    """The end-to-end check: midparent-offspring regression still recovers
    the target h2 with the module present."""
    rng = np.random.default_rng(20260401)
    for trait in ("height_cm", "neuroticism"):
        r = V.parent_offspring_regression(trait, 2500, rng)
        assert r.passes(), (trait, r.observed_slope, r.expected_slope)


def test_validation_law_passes():
    r = V.developmental_identity(n=80, rng=np.random.default_rng(3))
    assert r.passes()
    assert r.max_identity_error == 0.0
    assert r.plateau_error == 0.0


# ======================================================================
# 2. The growth curve
# ======================================================================

def test_stature_matches_tanner_landmarks():
    """Fraction of adult stature at each landmark age, within 1%."""
    for sex, table in V._STATURE_LANDMARKS.items():
        for age, target in table.items():
            assert stature_fraction(age, sex) == pytest.approx(target, abs=0.01)


def test_birth_stature_is_pinned():
    """~50 cm at birth against a ~171 cm adult. Preece-Baines alone gives
    33% here, which is why an infancy segment is spliced on below age 2."""
    for sex in ("female", "male"):
        assert stature_fraction(0.0, sex) == pytest.approx(0.29, abs=1e-9)
        assert 48.0 < stature_fraction(0.0, sex) * 171 < 51.0


def test_half_adult_height_at_about_age_two():
    """The classic paediatric rule of thumb, and a good independent check
    that the infancy splice lands in the right place."""
    for sex in ("female", "male"):
        assert stature_fraction(2.0, sex) == pytest.approx(0.5, abs=0.02)


def test_growth_is_monotone_and_continuous():
    for sex in ("female", "male"):
        ages = np.linspace(0, REFERENCE_AGE, 800)
        f = np.array([stature_fraction(a, sex) for a in ages])
        assert np.all(np.diff(f) >= -1e-12)          # nobody shrinks
        assert np.max(np.abs(np.diff(f))) < 0.02     # no jump at the splice


def test_girls_reach_peak_height_velocity_before_boys():
    """Direction and ordering emerge from separately fitted curves. The
    MAGNITUDE is known to be short of Tanner's ~2 years -- asserted loosely
    here so the documented shortfall is pinned, not hidden."""
    pf, pm = peak_height_velocity_age("female"), peak_height_velocity_age("male")
    assert pf < pm
    assert 0.8 < (pm - pf) < 2.6
    assert 10.5 < pf < 12.5
    assert 12.0 < pm < 14.5


def test_children_are_shorter_than_their_mature_selves():
    rng = np.random.default_rng(4)
    npc = random_founder("kid", rng)
    adult = npc.phenotype()["height_cm"]
    assert npc.height_at_age(0) < npc.height_at_age(5) < npc.height_at_age(12)
    assert npc.height_at_age(12) < adult
    assert npc.height_at_age(20) == pytest.approx(adult)


# ======================================================================
# 3. Senescence
# ======================================================================

def test_stature_declines_after_forty_at_about_a_centimetre_per_decade():
    """Sorkin, Muller & Andres 1999. Checked in cm on a 171 cm frame."""
    loss_per_decade = (1.0 - growth_factor("height_cm", 70.0)) * 171 / 3.0
    assert 0.7 < loss_per_decade < 2.0


def test_aerobic_capacity_falls_about_ten_percent_per_decade_from_thirty():
    """Fleg et al. 2005, including the acceleration -- a single exponential
    would give the same rate at 40 and at 70, and the data does not."""
    at40 = growth_factor("aerobic_capacity", 40.0)
    at70 = growth_factor("aerobic_capacity", 70.0)
    assert 0.87 < at40 < 0.93                       # ~10% lost by 40
    assert 0.40 < at70 < 0.60                       # ~half of peak by 70
    early = (1 - at40) / 1.0
    late = (growth_factor("aerobic_capacity", 60.0) - at70) / 1.0
    assert late > early                             # the rate accelerates


def test_mass_relative_vo2max_does_not_scale_with_body_size():
    """
    A unit check with teeth. `aerobic_capacity` is mL/kg/min, so a child's
    value is close to an adult's -- scaling it by stature would be a units
    error. A ten-year-old at 77-80% of adult height must NOT be at 77-80%
    of adult VO2max.
    """
    assert growth_factor("aerobic_capacity", 10.0) == pytest.approx(1.0)
    assert stature_fraction(10.0, "male") < 0.85     # ... while clearly small


def test_absolute_lung_volume_does_scale_steeply_with_stature():
    """The mirror of the test above. FEV1 is in litres, an absolute volume,
    so it follows a height power law -- a ten-year-old at 77% of adult
    height has roughly 0.77^2.7 ~ 50% of adult volume, not 77%."""
    f10 = growth_factor("lung_capacity", 10.0, "male")
    h10 = stature_fraction(10.0, "male")
    assert f10 < h10 * 0.8
    assert f10 == pytest.approx(h10 ** 2.7, rel=1e-6)


# ======================================================================
# 4. Maturation drift
# ======================================================================

def test_personality_follows_the_maturity_principle():
    """Roberts, Walton & Viechtbauer 2006: conscientiousness and
    agreeableness rise with age, neuroticism falls."""
    assert maturation_offset("conscientiousness", 50) > maturation_offset(
        "conscientiousness", 20)
    assert maturation_offset("agreeableness", 50) > maturation_offset(
        "agreeableness", 20)
    assert maturation_offset("neuroticism", 50) < maturation_offset(
        "neuroticism", 20)


def test_maturation_moves_the_expressed_phenotype_in_the_right_direction():
    rng = np.random.default_rng(5)
    npc = random_founder("p", rng)
    young = npc.phenotype_at_age(20)["conscientiousness"]
    old = npc.phenotype_at_age(50)["conscientiousness"]
    # unless the individual is clipped at the ceiling, older = more conscientious
    if young < 0.98:
        assert old > young


def test_unprofiled_traits_are_age_invariant():
    """A statement of scope: the engine does not model the development of
    eye colour, so it must not pretend to."""
    rng = np.random.default_rng(6)
    npc = random_founder("q", rng)
    for age in (0, 5, 30, 80):
        assert npc.phenotype_at_age(age)["eye_color"] == npc.phenotype()["eye_color"]
        assert npc.phenotype_at_age(age)["skin_tone"] == npc.phenotype()["skin_tone"]


def test_categorical_traits_are_never_scaled():
    """A growth factor applied to the string 'brown' would raise; a factor
    applied to a categorical liability would be meaningless. Neither happens."""
    rng = np.random.default_rng(7)
    npc = random_founder("r", rng)
    for age in (0, 10, 45):
        ph = npc.phenotype_at_age(age)
        assert isinstance(ph["eye_color"], str)
        assert isinstance(ph["vision_acuity"], str)


def test_life_stage_labels_are_ordered():
    rng = np.random.default_rng(8)
    npc = random_founder("s", rng, sex="female")
    stages = [npc.life_stage(a) for a in (1, 5, 14, 25, 50, 70)]
    assert stages == ["infant", "child", "adolescent", "adult",
                      "midlife", "senescent"]
