"""
Fluctuating asymmetry (item E6): the claims, and the ways it could be fake.
==========================================================================

FA is the one appearance channel here that is not about what the genome said.
It is about what development failed to control, which makes it the most
interesting item on the implementation line and also the easiest to fake: any
random per-vertex wobble produces asymmetric faces, and a picture cannot tell
that apart from a modelled one.

So what is tested is not "are the villagers asymmetric". It is the four things
that separate fluctuating asymmetry from a wobble:

  1. IT MUST FLUCTUATE. Van Valen 1962's distinction: fluctuating asymmetry is
     signed, unimodal and MEAN ZERO. A population mean that drifts off zero is
     DIRECTIONAL asymmetry -- a different phenomenon, developmentally
     programmed rather than a failure -- and nothing on screen would show the
     difference.
  2. IT MUST BE FIXED FOR LIFE. A face that changes between two reads of the
     same person is the v0.2 quirk `EnvironmentalDeviates` was built to kill.
  3. IT MUST RESPOND TO STRESS, through the same `canalize.k(stress)` that
     releases cryptic genetic variance, and be exactly inert at neutral
     stress. This is the citable prediction (Parsons 1992) and the reason E6
     is worth more than a cosmetic jitter.
  4. ITS OWN HERITABILITY MUST COME OUT LOW, and at two levels, because the
     literature has two results and a model worth anything reproduces both.
     A SINGLE feature's FA carries a realised heritability near 0.012 against
     the instability trait's declared 0.10, because one measurement is mostly
     the fresh draw -- which is why single-trait FA heritabilities cluster
     near zero and the higher meta-analytic figures are disputed. A COMPOSITE
     over all 31 features recovers much more, which is exactly why composite
     FA indices exist (Palmer & Strobeck 1986). Both fall out of drawing the
     asymmetry fresh and scaling it; neither is declared.
"""

from __future__ import annotations

import json
import math
import sys
import warnings
from pathlib import Path

import numpy as np
import pytest

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from health_engine.asymmetry import (BASE_SIGMA, FEATURES, MAX_WEIGHT,
                                     asymmetry_sigma, fa_index,
                                     instability_multiplier, scale_asymmetry,
                                     target_weights)
from health_engine.canalize import canalization_factor
from health_engine.npc import random_founder
from health_engine.traits import TRAIT_TABLE


def _people(n, seed=17):
    rng = np.random.default_rng(seed)
    return [random_founder(f"FA-{i}", rng) for i in range(n)]


def _signed(npc, k=1.0):
    z = float(npc.phenotype()["developmental_instability"])
    return scale_asymmetry(npc.deviates.asymmetry, z, k)


# ----------------------------------------------------------------------
# 1. it fluctuates: signed, mean zero, unimodal
# ----------------------------------------------------------------------

def test_the_population_mean_asymmetry_is_zero_per_feature():
    """The assertion that keeps this FLUCTUATING asymmetry.

    A feature whose signed mean drifts off zero is directional asymmetry, which
    is a developmental program rather than a failure to buffer, and the claim
    in the paper would silently become a different and much stronger one.
    """
    people = _people(400)
    for feature in FEATURES:
        values = np.array([_signed(p)[feature] for p in people])
        se = values.std(ddof=1) / math.sqrt(len(values))
        assert abs(values.mean()) < 4.0 * se, (
            f"{feature} has a signed mean of {values.mean():+.5f} against a "
            f"standard error of {se:.5f}; that is directional asymmetry, not "
            f"fluctuating asymmetry")


def test_both_sides_are_used_about_equally():
    """The same claim seen from the emitted targets: neither the l nor the r
    target may dominate, or the village leans one way."""
    people = _people(300)
    left = right = 0
    for person in people:
        for target, _weight in target_weights(_signed(person)):
            if target.endswith("-l"):
                left += 1
            else:
                right += 1
    total = left + right
    assert total > 0
    assert 0.45 < left / total < 0.55, f"left {left} vs right {right}"


def test_asymmetry_is_not_a_function_of_any_other_trait():
    """FA is noise. If it correlated with stature or mass it would be a
    phenotype in disguise and the claim would be wrong."""
    people = _people(300)
    fa = np.array([fa_index(_signed(p)) for p in people])
    for trait in ("height_cm", "bmi", "lean_mass_fraction"):
        other = np.array([float(p.phenotype()[trait]) for p in people])
        r = float(np.corrcoef(fa, other)[0, 1])
        assert abs(r) < 0.2, f"FA correlates with {trait}: r={r:.3f}"


# ----------------------------------------------------------------------
# 2. it is fixed for life
# ----------------------------------------------------------------------

def test_the_same_villager_has_the_same_face_every_time():
    person = _people(1)[0]
    first = _signed(person)
    for _ in range(20):
        assert _signed(person) == first


def test_two_runs_from_one_seed_agree():
    a = [_signed(p) for p in _people(5, seed=99)]
    b = [_signed(p) for p in _people(5, seed=99)]
    assert a == b


def test_every_villager_gets_every_feature():
    for person in _people(20):
        assert set(person.deviates.asymmetry) == set(FEATURES)


# ----------------------------------------------------------------------
# 3. it responds to stress, and is inert without it
# ----------------------------------------------------------------------

def test_a_neutral_environment_leaves_asymmetry_untouched():
    """k is exactly 1.0 at or below the canalization threshold, so a
    calibrated run is bit-for-bit what it would have been."""
    assert canalization_factor(1.0) == 1.0
    person = _people(1)[0]
    assert _signed(person, k=canalization_factor(1.0)) == _signed(person, k=1.0)


def test_stress_widens_asymmetry_through_the_canalization_factor():
    """The citable prediction: a less well buffered population is a more
    asymmetric one (Parsons 1992), driven by the SAME k that releases cryptic
    genetic variance elsewhere in the engine."""
    people = _people(200)
    calm = np.mean([fa_index(_signed(p, k=canalization_factor(1.0)))
                    for p in people])
    stressed = np.mean([fa_index(_signed(p, k=canalization_factor(3.0)))
                        for p in people])
    assert stressed > calm

    # And by the factor the closed form says, not merely upward. The width is
    # EXACTLY proportional to k, so that half is asserted exactly.
    expected = canalization_factor(3.0) / canalization_factor(1.0)
    assert (asymmetry_sigma(0.4, canalization_factor(3.0))
            / asymmetry_sigma(0.4, canalization_factor(1.0))
            == pytest.approx(expected, rel=1e-12))

    # The REALISED mean falls a hair short of it, 1.5996 against 1.6, and the
    # shortfall is the clamp at MAX_WEIGHT catching the few most decanalized
    # features. That is a modelled behaviour rather than an error -- MPFB
    # targets are authored for [0, 1] and extrapolating past that is how a
    # face becomes a horror -- so the tolerance here admits it instead of
    # pretending the mean is unclamped.
    assert stressed / calm == pytest.approx(expected, rel=0.01)
    assert stressed / calm <= expected, (
        "clamping can only ever reduce the realised ratio")


def test_the_width_is_the_declared_closed_form():
    assert asymmetry_sigma(0.0, 1.0) == pytest.approx(BASE_SIGMA)
    assert instability_multiplier(0.0) == pytest.approx(1.0)
    assert asymmetry_sigma(1.0, 2.0) == pytest.approx(
        BASE_SIGMA * instability_multiplier(1.0) * 2.0)


def test_a_less_buffered_villager_is_more_asymmetric():
    assert asymmetry_sigma(2.0) > asymmetry_sigma(0.0) > asymmetry_sigma(-2.0)


# ----------------------------------------------------------------------
# 4. FA's own heritability comes out low, as an output
# ----------------------------------------------------------------------

def test_realised_fa_heritability_is_near_zero_for_a_single_feature():
    """The prediction that makes E6 more than a visual effect.

    THE TWO QUANTITIES MUST NOT BE CONFUSED, and the first version of this test
    confused them. `h2` is the share of the INSTABILITY trait's variance that
    is additive genetic. The realised heritability of an ASYMMETRY measurement
    is a different number: how much of ITS variance traces back to that genetic
    part. To a good approximation it is the product

        realised h2(FA)  ~  r2(FA, instability) * h2(instability)

    which is an upper bound, since it credits the whole FA-instability
    association to the genetic half of the trait.

    For a SINGLE feature that lands near 0.012, which is the empirical
    picture: single-trait FA heritabilities cluster near zero, and the higher
    published meta-analytic figures are disputed on exactly the grounds that a
    single trait is mostly measurement and developmental noise. The engine
    reproduces the near-zero as an OUTPUT of drawing the asymmetry fresh,
    rather than declaring it.
    """
    people = _people(500)
    signed = [_signed(p) for p in people]
    instability = np.array([float(p.phenotype()["developmental_instability"])
                            for p in people])
    declared = TRAIT_TABLE["developmental_instability"].h2

    per_feature = []
    for feature in FEATURES:
        single = np.array([abs(s[feature]) for s in signed])
        per_feature.append(float(np.corrcoef(single, instability)[0, 1]) ** 2
                           * declared)

    assert max(per_feature) < 0.05, (
        f"single-feature FA carries a realised heritability of "
        f"{max(per_feature):.3f}; it should be near zero")
    assert np.mean(per_feature) < 0.03


def test_a_composite_index_recovers_more_than_a_single_feature():
    """And the other half of the same literature, which is WHY composite FA
    indices exist.

    Averaging over 31 features cancels most of the per-feature draw and leaves
    the individual's own width, so a composite is far more repeatable than any
    single measurement. That is the standard justification for FA1 over a
    one-trait score (Palmer & Strobeck 1986). The engine should show the same
    ordering, and if it ever stopped doing so the asymmetry would have stopped
    depending on the villager at all.
    """
    people = _people(500)
    signed = [_signed(p) for p in people]
    instability = np.array([float(p.phenotype()["developmental_instability"])
                            for p in people])
    declared = TRAIT_TABLE["developmental_instability"].h2

    composite = np.array([fa_index(s) for s in signed])
    composite_h2 = float(np.corrcoef(composite, instability)[0, 1]) ** 2 * declared

    single = np.array([abs(s[FEATURES[0]]) for s in signed])
    single_h2 = float(np.corrcoef(single, instability)[0, 1]) ** 2 * declared

    assert composite_h2 > single_h2
    # Still below the trait it derives from: the composite recovers the
    # individual's width, and the width is only 10% genetic.
    assert composite_h2 <= declared


def test_the_instability_trait_is_declared_low_and_appended():
    spec = TRAIT_TABLE["developmental_instability"]
    assert spec.appended is True
    assert spec.h2 == pytest.approx(0.10)
    assert spec.h2 < TRAIT_TABLE["height_cm"].h2


# ----------------------------------------------------------------------
# the emission, and the install it depends on
# ----------------------------------------------------------------------

def test_every_declared_feature_is_installed():
    """The feature list is written down, so it can go stale. Twenty-nine
    stems begin `asym-` and two begin `asymm-` with a double m, which is
    exactly the shape a prefix rule gets wrong."""
    root = Path("C:/Users/samal/AppData/Roaming/Blender Foundation/Blender/4.4"
                "/extensions/user_default/mpfb/data/targets/asym")
    if not root.is_dir():
        pytest.skip("MPFB targets not installed on this machine")
    for feature in FEATURES:
        for side in ("l", "r"):
            path = root / f"{feature}-{side}.target.gz"
            assert path.exists(), f"declared but not installed: {path.name}"


def test_a_positive_asymmetry_goes_left_and_a_negative_one_right():
    """Only coherent because the two targets are exact mirrors, which
    `mpfb/probe_asymmetry.py` measured rather than assumed."""
    weights = target_weights({FEATURES[0]: 0.3, FEATURES[1]: -0.4})
    assert (f"{FEATURES[0]}-l", 0.3) in weights
    assert (f"{FEATURES[1]}-r", 0.4) in weights


def test_negligible_asymmetries_are_not_emitted():
    """`.mhm` files travel in the export bundle and item G4 already flags its
    size. A weight too small to move a vertex is 31 lines of nothing."""
    assert target_weights({f: 1e-9 for f in FEATURES}) == ()


def test_weights_are_clamped_into_the_authored_range():
    """MPFB targets are authored for [0, 1]; beyond that a morph extrapolates
    outside anything anyone checked, which is how a face becomes a horror."""
    signed = scale_asymmetry({f: 50.0 for f in FEATURES}, instability_z=5.0,
                             k=10.0)
    assert all(abs(v) <= MAX_WEIGHT for v in signed.values())


def test_the_mhm_carries_the_asymmetry_lines():
    person = _people(1)[0]
    from health_engine.phenotype_to_mhm import phenotype_to_mhm
    text = phenotype_to_mhm(person.phenotype(), person.sex, 30.0,
                            asymmetry=person.deviates.asymmetry)
    lines = [l for l in text.splitlines() if l.startswith("modifier asym/")]
    assert lines
    for line in lines:
        _mod, target, weight = line.split(" ")
        assert target.startswith("asym/")
        assert 0.0 <= float(weight) <= MAX_WEIGHT


def test_a_villager_with_no_asymmetry_writes_the_old_file():
    """Omitting the vector must produce exactly what was produced before E6,
    so the golden fixture keeps pinning the path it was cut on."""
    person = _people(1)[0]
    from health_engine.phenotype_to_mhm import phenotype_to_mhm
    without = phenotype_to_mhm(person.phenotype(), person.sex, 30.0)
    assert "asym/" not in without


def test_the_probe_confirmed_the_targets_reach_the_mesh():
    """E6's whole design rests on a signed number in Python reaching a vertex
    in Blender through a text file. The targets carry no modifier definition,
    so that was not obvious, and it is held against the recorded measurement
    rather than against the reading of MPFB's loader that suggested it."""
    path = REPO / "outputs" / "mpfb" / "asymmetry.json"
    if not path.exists():
        pytest.skip("run mpfb/probe_asymmetry.py to record the measurement")
    measured = json.loads(path.read_text(encoding="utf-8"))
    assert measured["resolves_through_mhm"] is True
    assert measured["left_and_right_are_mirrored"] is True
    assert measured["scales_with_weight"] is True
