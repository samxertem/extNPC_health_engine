"""
Canalization / cryptic genetic variation (roadmap #14b).

Waddington's claim: development is buffered, so genetic differences stay
hidden until stress overwhelms the buffer, at which point they appear.
Here that is a factor k on the genetic terms only, exactly 1.0 at or below
the buffering threshold -- so a calibrated world is untouched -- and the
released variance follows k^2.
"""

import numpy as np
import pytest

from health_engine import validation
from health_engine.canalize import (CANALIZATION_THRESHOLD, CAPACITY_BY_TRAIT,
                                    DEFAULT_CAPACITY, canalization_factor,
                                    expected_heritability,
                                    factors_for_environment, is_decanalizing)
from health_engine.npc import random_founder
from health_engine.traits import ARCHITECTURE, Environment, liability


@pytest.fixture
def rng():
    return np.random.default_rng(1414)


# ----------------------------------------------------------------------
# The buffer must be inert at baseline
# ----------------------------------------------------------------------

def test_factor_is_exactly_one_at_and_below_threshold():
    """The whole calibration rests on this: no drift in any normal world."""
    for s in (0.0, 0.25, 0.5, 0.9, CANALIZATION_THRESHOLD):
        assert canalization_factor(s, "height_cm") == 1.0
        assert canalization_factor(s) == 1.0


def test_neutral_environment_is_inert():
    env = Environment("neutral")
    assert env.stress == CANALIZATION_THRESHOLD
    assert not is_decanalizing(env)
    assert set(factors_for_environment(env).values()) == {1.0}


def test_neutral_born_npc_is_numerically_identical(rng):
    """An NPC developed in a neutral environment must evaluate exactly as it
    did before this layer existed."""
    npc = random_founder("x", rng)
    for trait in ("height_cm", "neuroticism", "bmi"):
        arch = ARCHITECTURE[trait]
        assert npc.canalization(trait) == 1.0
        with_c = liability(arch, npc.genome.dosage, npc.deviates,
                           npc.expression, npc.imprint_state(),
                           npc.canalization(trait))
        without = liability(arch, npc.genome.dosage, npc.deviates,
                            npc.expression, npc.imprint_state(), 1.0)
        assert with_c == without


# ----------------------------------------------------------------------
# Above threshold: release
# ----------------------------------------------------------------------

def test_factor_grows_only_above_threshold():
    assert canalization_factor(2.0, "height_cm") > 1.0
    assert canalization_factor(3.0, "height_cm") > canalization_factor(2.0, "height_cm")
    # linear in the excess
    k2 = canalization_factor(2.0, "height_cm") - 1.0
    k3 = canalization_factor(3.0, "height_cm") - 1.0
    assert k3 == pytest.approx(2.0 * k2)


def test_stress_releases_genetic_variance():
    """The benchmark: at IDENTICAL genotypes, a stressed cohort is more
    variable than an unstressed one. That is cryptic variation made visible."""
    r = validation.canalization_release(trait="height_cm", stress=2.0, n=3000)
    assert r.observed_var_stressed > r.v_genetic + r.v_environmental
    assert r.genetic_fraction_stressed > r.genetic_fraction_baseline


def test_released_variance_matches_the_closed_form():
    """Var(z(k)) = k^2 V_gen + V_env, measured against a prediction built
    from the BASELINE decomposition -- not circular."""
    for trait in ("height_cm", "neuroticism"):
        r = validation.canalization_release(trait=trait, stress=2.0, n=4000)
        assert r.passes()
        assert r.observed_var_stressed == pytest.approx(
            r.predicted_var_stressed, rel=0.02)


def test_heritability_release_matches_closed_form():
    """h2(k) = k^2 h2_0 / (k^2 h2_0 + 1 - h2_0)."""
    r = validation.canalization_release(trait="height_cm", stress=2.0, n=4000)
    assert r.genetic_fraction_stressed == pytest.approx(
        r.predicted_fraction_stressed, abs=0.02)


def test_expected_heritability_is_monotonic_and_bounded():
    h0 = 0.5
    assert expected_heritability(h0, 1.0) == pytest.approx(h0)
    assert expected_heritability(h0, 2.0) > h0
    assert expected_heritability(h0, 10.0) < 1.0
    assert expected_heritability(0.0, 5.0) == 0.0


# ----------------------------------------------------------------------
# What canalization must NOT do
# ----------------------------------------------------------------------

def test_the_population_mean_does_not_move():
    """G and I are mean-centred by construction, so scaling them changes
    variance only. Same lesson as the epigenome, GRN and imprinting layers."""
    for trait in ("height_cm", "neuroticism"):
        r = validation.canalization_release(trait=trait, stress=2.0, n=4000)
        assert abs(r.mean_shift) < 0.02


def test_environmental_variance_is_untouched():
    """Decanalization releases GENETIC variance. If V_env moved too, the
    mechanism would be indistinguishable from 'stress adds noise'."""
    r = validation.canalization_release(trait="height_cm", stress=2.0, n=4000)
    implied_env = r.observed_var_stressed - r.k ** 2 * r.v_genetic
    assert implied_env == pytest.approx(r.v_environmental, abs=0.03)


# ----------------------------------------------------------------------
# Per-trait buffering
# ----------------------------------------------------------------------

def test_more_canalized_traits_release_more():
    """A trait that hides more cryptic variation reveals more when the buffer
    breaks. Height is the textbook buffered trait (catch-up growth)."""
    assert CAPACITY_BY_TRAIT["height_cm"] > DEFAULT_CAPACITY
    k_height = canalization_factor(2.0, "height_cm")
    k_generic = canalization_factor(2.0, "neuroticism")
    assert k_height > k_generic


def test_unlisted_traits_fall_back_to_the_default():
    assert canalization_factor(2.0, "definitely_not_a_trait") == pytest.approx(
        1.0 + DEFAULT_CAPACITY)


def test_npc_uses_its_developmental_environment(rng):
    """Waddington's buffer acts DURING development, so it is birth_environment
    that decides expressivity -- not any later environment."""
    harsh = Environment("harsh", stress=2.0)
    calm = random_founder("calm", rng)
    stressed = random_founder("stressed", rng, environment=harsh)
    assert calm.canalization("height_cm") == 1.0
    assert stressed.canalization("height_cm") > 1.0
    assert stressed.canalization("height_cm") == canalization_factor(2.0, "height_cm")
