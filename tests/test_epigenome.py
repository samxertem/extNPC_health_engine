"""
Epigenome tests (roadmap #15-#20).

The headline is `test_smoking_benchmark`, which is the roadmap's own
Stage-1 acceptance criterion: an NPC exposed to chronic smoking shows the
intended locus's methylation shift during life and partial recovery on
cessation, while offspring rarely inherit it.
"""

import numpy as np
import pytest

from health_engine import epigenome as EP
from health_engine.epigenome import (BASELINE_METHYLATION, Epigenome,
                                     germline_transmit)
from health_engine.medical import simulate_aging
from health_engine.npc import random_founder, reproduce
from health_engine.traits import Environment


@pytest.fixture
def rng():
    return np.random.default_rng(20240611)


def _smoky(intensity=1.0):
    return Environment("smoky", exposures={"smoking": intensity})


def _clean():
    return Environment("clean")


# ------------------------------------------------------- baseline invariance

def test_default_epigenome_gives_unit_expression():
    """
    The load-bearing invariant: a default epigenome must reproduce session
    1 exactly, so all the calibrated heritabilities survive. Epigenetic
    effects are deviations from a multiplier of 1.0, never a rescaling.
    """
    epi = Epigenome.default()
    assert np.allclose(epi.expression(), 1.0)


def test_newborn_has_unit_expression(rng):
    npc = random_founder("baby", rng)
    assert np.allclose(npc.expression, 1.0)
    assert npc.epigenetic_age == 0.0


# ------------------------------------------------------- lifetime dynamics

def test_smoking_hypomethylates_ahrr(rng):
    """Smoking drives AHRR methylation DOWN (Joehanes 2016), dose-dependently."""
    base = Epigenome.default().methylation_of("AHRR")

    light = random_founder("light", rng)
    simulate_aging(light, 20, rng, _smoky(0.4))
    heavy = random_founder("heavy", rng)
    simulate_aging(heavy, 20, rng, _smoky(1.0))

    assert light.epigenome.methylation_of("AHRR") < base
    assert heavy.epigenome.methylation_of("AHRR") < light.epigenome.methylation_of("AHRR")


def test_smoking_benchmark(rng):
    """
    ROADMAP STAGE-1 BENCHMARK.

    (1) chronic smoking shifts AHRR methylation during life,
    (2) it partially recovers on cessation, and
    (3) offspring almost never inherit the shift.
    """
    base = Epigenome.default().methylation_of("AHRR")

    smoker = random_founder("smoker", rng, sex="female")
    simulate_aging(smoker, 20, rng, _smoky(1.0))
    smoked = smoker.epigenome.methylation_of("AHRR")

    # (1) a clear lifetime shift
    assert base - smoked > 0.15, f"AHRR barely moved: {base} -> {smoked}"

    # (2) partial recovery after 10 years of cessation: back toward baseline,
    #     but not all the way (recovery is slower than onset).
    simulate_aging(smoker, 10, rng, _clean())
    recovered = smoker.epigenome.methylation_of("AHRR")
    assert recovered > smoked + 0.03, "no recovery on cessation"
    assert recovered < base - 0.02, "recovered fully — should be partial at 10y"

    # (3) offspring do not inherit it. AHRR is not a germline escaper, so at
    #     95% reset the mean transmitted deviation is tiny.
    father = random_founder("father", rng, sex="male")
    devs = []
    for i in range(60):
        child = reproduce(smoker, father, f"c{i}", rng, mutation=False)
        devs.append(child.epigenome.methylation_of("AHRR") - base)
    mean_abs_dev = float(np.mean(np.abs(devs)))
    parent_dev = abs(smoked - base)
    assert mean_abs_dev < 0.06 * parent_dev + 0.01, mean_abs_dev


def test_age_drift_is_monotonic_and_irreversible(rng):
    """The epigenetic clock's loci drift with age and do not relax back."""
    npc = random_founder("ager", rng)
    idx = EP.AGE_DRIFT_IDX
    m0 = npc.epigenome.methylation[idx].copy()

    simulate_aging(npc, 20, rng, _clean())
    m1 = npc.epigenome.methylation[idx].copy()

    # each locus moved in its fixed direction, cumulative displacement grew
    moved = np.abs(m1 - m0)
    assert moved.mean() > 0.03
    # direction matches the fixed per-locus drift sign (away from start)
    signed = (m1 - m0) * EP.AGE_DRIFT_DIR
    assert (signed >= -1e-9).mean() > 0.95   # nearly all moved the right way


def test_epigenetic_clock_accelerates_under_stress(rng):
    """Sustained stress makes epigenetic age outrun chronological age (#17)."""
    calm = random_founder("calm", rng)
    simulate_aging(calm, 30, rng, Environment("calm", stress=1.0))

    stressed = random_founder("stressed", rng)
    simulate_aging(stressed, 30, rng,
                   Environment("harsh", stress=2.0,
                               exposures={"psychosocial_stress": 1.0}))

    assert abs(calm.epigenetic_age - 30) < 3.0        # roughly 1:1 when calm
    assert stressed.epigenetic_age > calm.epigenetic_age + 5
    assert stressed.epigenetic_age_acceleration > 3.0


def test_chronic_stress_raises_inflammation_via_methylation(rng):
    """
    The compounding loop: chronic stress hypomethylates pro-inflammatory
    loci, which raises the inflammation_tone liability during life. Same
    genome, measured before and after — only the epigenome changed.
    """
    npc = random_founder("stressed", rng)
    dosage = npc.genome.dosage.copy()
    before = npc.inflammation_state
    simulate_aging(npc, 25, rng,
                   Environment("harsh", stress=1.8,
                               exposures={"psychosocial_stress": 1.0}))
    after = npc.inflammation_state

    # The physiological state rises substantially, driven by acquired load.
    assert after > before + 0.2, (before, after)
    # The alleles never moved — this is acquired, not genetic (Weismann).
    assert np.array_equal(npc.genome.dosage, dosage)
    # Almost all of the rise is the acquired load term, not a change in the
    # expressed genotypic liability (hypomethylation nudges expression, but
    # the multiplier is symmetric so it barely shifts the mean).
    load_term = after - npc.liability("inflammation_tone")
    assert load_term > 0.2, load_term


# ------------------------------------------------------- developmental (#19)

def test_prenatal_famine_hypomethylates_igf2(rng):
    """Dutch Hunger Winter analogue: famine -> lower IGF2 methylation, set at birth."""
    base = Epigenome.default().methylation_of("IGF2")
    famine = Environment("famine", exposures={"prenatal_nutrition": 0.0})
    plenty = Environment("plenty", exposures={"prenatal_nutrition": 1.0})

    starved = random_founder("starved", rng, environment=famine)
    fed = random_founder("fed", rng, environment=plenty)

    assert starved.epigenome.methylation_of("IGF2") < base
    assert fed.epigenome.methylation_of("IGF2") > base


def test_low_early_life_care_hypermethylates_nr3c1(rng):
    """Weaver 2004 (RAT) analogue: low care -> NR3C1 hypermethylation."""
    base = Epigenome.default().methylation_of("NR3C1")
    neglect = Environment("neglect", exposures={"early_life_care": 0.0})
    npc = random_founder("neglected", rng, environment=neglect)
    assert npc.epigenome.methylation_of("NR3C1") > base + 0.05


# ------------------------------------------------------- germline (#20)

def test_escaper_transmits_more_than_non_escaper(rng):
    """
    IGF2 (escaper) crosses the germline far more readily than AHRR
    (non-escaper). Build a parent with a strong deviation at each locus,
    make many children, compare mean transmitted deviation.
    """
    igf2 = EP.IGF2_IDX
    ahrr = EP.AHRR_IDX

    igf2_dev, ahrr_dev = [], []
    for _ in range(400):
        parent = Epigenome.default()
        parent.methylation[igf2] = BASELINE_METHYLATION - 0.30
        parent.methylation[ahrr] = BASELINE_METHYLATION - 0.30
        partner = Epigenome.default()
        partner.methylation[igf2] = BASELINE_METHYLATION - 0.30
        partner.methylation[ahrr] = BASELINE_METHYLATION - 0.30
        child = germline_transmit(parent, partner, rng)
        igf2_dev.append(abs(child.methylation[igf2] - BASELINE_METHYLATION))
        ahrr_dev.append(abs(child.methylation[ahrr] - BASELINE_METHYLATION))

    assert np.mean(igf2_dev) > 5 * np.mean(ahrr_dev), (np.mean(igf2_dev), np.mean(ahrr_dev))


def test_germline_does_not_transmit_epigenetic_age(rng):
    """A child is born epigenetically young no matter how old its parents are."""
    mother = random_founder("mother", rng, sex="female")
    father = random_founder("father", rng, sex="male")
    simulate_aging(mother, 40, rng, Environment("harsh", stress=2.0))
    simulate_aging(father, 40, rng, Environment("harsh", stress=2.0))
    assert mother.epigenetic_age > 40
    child = reproduce(mother, father, "kid", rng, mutation=False)
    assert child.epigenetic_age == 0.0


def test_reset_policy_is_conservative():
    """Guard against a regression to v0.2's Lamarckian 30% reset."""
    p = EP.DEFAULT_GERMLINE_POLICY
    assert p.base_reset_prob >= 0.90
    assert p.inheritance_fidelity < 0.5
    assert EP.IS_ESCAPER.sum() < 5           # escapers are RARE


# ------------------------------------------------------- integration

def test_aging_does_not_touch_the_genotype(rng):
    """Epigenetics changes expression, never the alleles. The Weismann barrier."""
    npc = random_founder("subject", rng)
    dosage_before = npc.genome.dosage.copy()
    simulate_aging(npc, 30, rng, _smoky(1.0))
    assert np.array_equal(npc.genome.dosage, dosage_before)


def test_heritability_harness_is_unaffected_by_epigenome(rng):
    """
    The validation harness works on raw dosages, not NPCs, so lifetime
    epigenetics must not have perturbed the Stage-0 guarantees.
    """
    from health_engine import validation as V
    res = V.parent_offspring_regression("height_cm", 2000, rng)
    assert res.passes(tol=0.05), res
