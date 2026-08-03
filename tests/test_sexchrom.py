"""
Sex-chromosome tests (roadmap #2).

The headline is `test_colorblindness_hemizygous_epidemiology`: the model must
reproduce the textbook X-linked signature -- red-green colour blindness at
~q in males but ~q^2 in females -- which is the sex-chromosome analogue of
the Hardy-Weinberg / Haldane / breeder's-equation checks the rest of the
engine is validated against. The other tests pin the classic pedigree
patterns a geneticist expects: no father-to-son transmission of an X-linked
trait, a carrier mother passing it to half her sons, X-inactivation giving
carrier females intermediate enzyme activity, and sex-limited expression.
"""

import numpy as np
import pytest

from health_engine.npc import random_founder, reproduce
from health_engine.sexchrom import (MANIFEST_FUNCTIONAL_FRACTION, N_X_LOCI,
                                    X_LOCI, X_LOCUS_INDEX, SexChromosomes,
                                    sample_founder_sex_chromosomes,
                                    transmit_sex_chromosomes)
from health_engine.validation import x_linked_epidemiology

CB = X_LOCUS_INDEX["color_vision"]
G6PD = X_LOCUS_INDEX["g6pd"]
AR = X_LOCUS_INDEX["ar"]


@pytest.fixture
def rng():
    return np.random.default_rng(20240720)


def _male(cb=0, g6pd=0, ar=0):
    x = np.zeros(N_X_LOCI, dtype=np.int8)
    x[CB], x[G6PD], x[AR] = cb, g6pd, ar
    return SexChromosomes("male", x_maternal=x)


def _female(cb=(0, 0), g6pd=(0, 0), ar=(0, 0), skew=0.5):
    xm = np.zeros(N_X_LOCI, dtype=np.int8)
    xp = np.zeros(N_X_LOCI, dtype=np.int8)
    xm[CB], xp[CB] = cb
    xm[G6PD], xp[G6PD] = g6pd
    xm[AR], xp[AR] = ar
    return SexChromosomes("female", x_maternal=xm, x_paternal=xp, xci_skew=skew)


# --------------------------------------------------- the headline validation

def test_colorblindness_hemizygous_epidemiology(rng):
    """Males ~ q (~8%), females ~ q^2 (~0.6%), sex ratio ~ 0.5. This is the
    quantitative payoff of modelling hemizygosity."""
    res = x_linked_epidemiology(40_000, rng, "color_vision")
    assert res.passes(), res
    # the male:female ratio of prevalence should be ~ 1/q, i.e. large
    assert res.male_prevalence > 8 * res.female_prevalence


# --------------------------------------------------------- hemizygosity

def test_hemizygous_male_expresses_single_allele():
    """One risk allele makes a male affected (no second X to mask it);
    the same single allele leaves a female an unaffected carrier."""
    assert _male(cb=1).color_vision() == "colorblind"
    assert _male(cb=0).color_vision() == "normal"
    assert _female(cb=(1, 0)).color_vision() == "normal"      # carrier
    assert _female(cb=(1, 1)).color_vision() == "colorblind"  # homozygous


# ------------------------------------------------------ pedigree patterns

def test_no_father_to_son_transmission(rng):
    """The defining X-linked pattern: an affected father cannot pass the
    trait to his sons (they get his Y), but ALL his daughters become
    carriers (they get his affected X)."""
    father = _male(cb=1)                          # colour-blind father
    mother = _female(cb=(0, 0))                   # non-carrier mother
    sons = daughters = 0
    son_affected = daughter_carriers = 0
    for _ in range(2000):
        child = transmit_sex_chromosomes(mother, father, rng)
        if child.sex == "male":
            sons += 1
            son_affected += child.color_vision() == "colorblind"
        else:
            daughters += 1
            # daughter is a carrier iff she received the father's mutant X
            daughter_carriers += child.x_paternal[CB] == 1
    assert son_affected == 0                       # never father -> son
    assert daughter_carriers == daughters          # every daughter a carrier


def test_carrier_mother_transmits_to_half_of_sons(rng):
    """A carrier mother (heterozygous) passes the mutant X to ~half her
    children; in sons that means ~50% affected, the classic recurrence risk."""
    mother = _female(cb=(1, 0))                    # carrier
    father = _male(cb=0)                           # unaffected
    sons, affected = 0, 0
    for _ in range(4000):
        child = transmit_sex_chromosomes(mother, father, rng)
        if child.sex == "male":
            sons += 1
            affected += child.color_vision() == "colorblind"
    frac = affected / sons
    assert 0.45 <= frac <= 0.55, frac


def test_sex_ratio_is_emergent(rng):
    """~50:50 sex ratio emerges from Y-vs-X transmission, not a coin flip."""
    mother, father = _female(), _male()
    males = sum(transmit_sex_chromosomes(mother, father, rng).sex == "male"
                for _ in range(6000))
    assert 0.47 <= males / 6000 <= 0.53


# ---------------------------------------------------- X-inactivation mosaic

def test_xci_gives_carrier_females_intermediate_g6pd():
    """Lyon 1961: a heterozygous female is a mosaic, so her G6PD activity is
    INTERMEDIATE -- unlike a hemizygous male, who is all-or-nothing."""
    male_def = _male(g6pd=1).g6pd_activity()
    male_ok = _male(g6pd=0).g6pd_activity()
    carrier = _female(g6pd=(1, 0), skew=0.5).g6pd_activity()
    assert male_def < carrier < male_ok
    # and the activity tracks the inactivation skew (dosage of the good X)
    lo = _female(g6pd=(1, 0), skew=0.9).g6pd_activity()   # mostly mutant X active
    hi = _female(g6pd=(1, 0), skew=0.1).g6pd_activity()   # mostly good X active
    assert lo < hi


def test_extreme_skew_makes_manifesting_carrier():
    """A carrier whose XCI is skewed hard toward the mutant X can manifest a
    recessive trait -- the manifesting-heterozygote phenomenon."""
    # maternal X carries the mutant; skew ~1.0 means mostly the maternal
    # (mutant) X is active -> functional fraction below the manifest threshold
    hard = _female(cb=(1, 0), skew=0.97)
    assert hard._functional_fraction(CB) < MANIFEST_FUNCTIONAL_FRACTION
    assert hard.color_vision() == "colorblind"
    balanced = _female(cb=(1, 0), skew=0.5)
    assert balanced.color_vision() == "normal"


# -------------------------------------------------- sex-limited expression

def test_androgenetic_alopecia_is_sex_limited():
    """The same AR risk genotype manifests as patterned hair loss in a male
    but not a female -- the pathway is androgen-gated (Hillmer 2005)."""
    assert _male(ar=1).manifests_baldness() is True
    assert _female(ar=(1, 1)).manifests_baldness() is False


# ----------------------------------------------------- within-X linkage

def test_g6pd_and_colorblindness_are_linked(rng):
    """G6PD and the opsin cluster both sit at Xq28, ~3 cM apart, so a
    heterozygous mother co-transmits them far more often than the 50% of
    free assortment -- real human linkage the X map reproduces."""
    # mother heterozygous at both, in coupling (both mutants on maternal X)
    mother = _female(cb=(1, 0), g6pd=(1, 0))
    father = _male()
    recomb = 0
    n = 6000
    for _ in range(n):
        egg_source = transmit_sex_chromosomes(mother, father, rng)
        xm = egg_source.x_maternal
        # recombinant if the two loci no longer share parental origin
        if xm[CB] != xm[G6PD]:
            recomb += 1
    r = recomb / n
    # ~3 cM -> r ~ 0.03; assert well below free assortment
    assert r < 0.10, r


# ------------------------------------------------- integration / invariants

def test_founder_and_child_carry_consistent_sex(rng):
    """random_founder and reproduce attach a sex-chromosome layer whose sex
    matches the NPC's `sex` attribute."""
    mum = random_founder("mum", rng, sex="female")
    dad = random_founder("dad", rng, sex="male")
    assert mum.sex_chromosomes.sex == "female"
    assert dad.sex_chromosomes.sex == "male"
    for i in range(20):
        kid = reproduce(mum, dad, f"k{i}", rng)
        assert kid.sex_chromosomes.sex == kid.sex
        assert set(kid.x_linked_phenotype()) == {
            "color_vision", "g6pd_activity", "pattern_baldness"}


def test_sex_layer_does_not_touch_autosomal_phenotype(rng):
    """The sex-chromosome layer is parallel: an NPC's autosomal expression is
    still 1.0 everywhere at baseline (the calibrated core is untouched)."""
    npc = random_founder("f", rng)
    assert np.allclose(npc.expression, 1.0)
