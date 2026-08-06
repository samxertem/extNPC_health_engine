"""
Tests for inbreeding: pedigree kinship and inbreeding depression (#31).

Three things are being asserted, in increasing order of interest:

  1. The Malecot recursion reproduces textbook coefficients exactly. Pure
     combinatorics, so the tolerance is floating-point, not statistical.
  2. The load layer transmits Mendelianly and costs the caller's RNG stream
     nothing -- the determinism discipline every layer in this engine keeps.
  3. Lethal equivalents are RECOVERABLE. B is a closed form of the load
     spectrum that nothing in the transmission or viability path ever
     evaluates, so regressing simulated survival on pedigree F and getting
     it back is a real measurement.
"""

import numpy as np
import pytest

from health_engine import validation as V
from health_engine.inbreeding import (SPECTRUM, DeleteriousLoad, Pedigree,
                                      build_spectrum, derived_rng,
                                      directional_dominance, excess_mortality,
                                      first_cousin_excess_mortality,
                                      lethal_equivalents, realised_inbreeding,
                                      sample_founder_load, transmit_load)
from health_engine.npc import random_founder, reproduce


# ======================================================================
# 1. Malecot kinship
# ======================================================================

def test_kinship_matches_textbook_coefficients():
    """Every relationship in the standard table, to machine precision."""
    for label, (observed, expected) in V.malecot_kinship_check().items():
        assert abs(observed - expected) < 1e-12, label


def test_self_kinship_carries_the_inbreeding_coefficient():
    """f(x, x) = 1/2 (1 + F_x), which is 1/2 only for an OUTBRED individual.
    Getting this wrong is the classic pedigree-code bug: it silently halves
    every downstream coefficient in an inbred pedigree."""
    ped = Pedigree()
    ped.add("A"), ped.add("B")
    ped.add("E", "A", "B")
    ped.add("F", "A", "B")
    ped.add("J", "E", "F")               # full-sib mating, F = 1/4
    assert ped.kinship("E", "E") == pytest.approx(0.5)
    assert ped.inbreeding("J") == pytest.approx(0.25)
    assert ped.kinship("J", "J") == pytest.approx(0.5 * (1 + 0.25))


def test_repeated_sib_mating_accumulates_inbreeding():
    """Wright's classic result: continued full-sib mating drives F up along
    F_t = 1/4 (1 + 2 F_{t-1} + F_{t-2}), reaching 0.375 in two rounds."""
    ped = Pedigree()
    ped.add("A"), ped.add("B")
    ped.add("m0", "A", "B")
    ped.add("f0", "A", "B")
    expected = [0.25, 0.375, 0.5]
    for t, exp in enumerate(expected):
        ped.add(f"m{t + 1}", f"m{t}", f"f{t}")
        ped.add(f"f{t + 1}", f"m{t}", f"f{t}")
        assert ped.inbreeding(f"m{t + 1}") == pytest.approx(exp, abs=1e-12)


def test_founders_are_unrelated_and_outbred():
    ped = Pedigree()
    ped.add("A"), ped.add("B")
    assert ped.kinship("A", "B") == 0.0
    assert ped.inbreeding("A") == 0.0
    assert ped.is_founder("A")


def test_untraceable_parent_is_treated_as_a_founder():
    """A parent outside the pedigree cannot be traced, so the individual is
    half-founder. This is what happens at the edge of any real family record
    and it must not raise."""
    ped = Pedigree()
    ped.add("A")
    ped.add("X", "A", "GHOST")
    assert ped.inbreeding("X") == 0.0
    assert ped.kinship("A", "X") == pytest.approx(0.25)


def test_deep_pedigree_does_not_overflow_the_stack():
    """The recursion is evaluated with an explicit stack precisely so a
    long-running world cannot crash it. 600 generations is well past
    Python's default recursion limit."""
    ped = Pedigree()
    ped.add("m0"), ped.add("f0")
    for t in range(600):
        ped.add(f"m{t + 1}", f"m{t}", f"f{t}")
        ped.add(f"f{t + 1}", f"m{t}", f"f{t}")
    assert ped.depth("m600") == 600
    assert 0.99 < ped.inbreeding("m600") <= 1.0     # sib mating -> fixation


def test_pedigree_from_npcs_reproduces_parentage():
    rng = np.random.default_rng(4)
    mother = random_founder("mum", rng, sex="female")
    father = random_founder("dad", rng, sex="male")
    kids = [reproduce(mother, father, f"k{i}", rng) for i in range(2)]
    ped = Pedigree.from_npcs([mother, father] + kids)
    assert ped.kinship("k0", "k1") == pytest.approx(0.25)      # full sibs
    assert ped.relationship("mum", "k0") == pytest.approx(0.5)


# ======================================================================
# 2. The load spectrum
# ======================================================================

def test_spectrum_hits_the_lethal_equivalent_target():
    """B is solved for, not asserted, so it should land on target exactly."""
    assert SPECTRUM.lethal_equivalents == pytest.approx(1.4, abs=1e-6)
    assert lethal_equivalents() == pytest.approx(SPECTRUM.lethal_equivalents)


def test_frequency_ceiling_never_binds_at_the_default_calibration():
    """The q ceiling is a safety rail, not a tuning knob: at the calibrated
    spectrum every frequency is set by mutation-selection balance alone. If
    this ever fails, the ceiling has started doing the calibration's job."""
    from health_engine.inbreeding import _Q_MAX
    assert int(np.count_nonzero(SPECTRUM.q >= _Q_MAX - 1e-15)) == 0


def test_implied_mutation_rate_is_biologically_plausible():
    """Solving for B pins the per-locus mutation rate. It has to survive two
    independent sanity checks it was never fitted to."""
    from health_engine.genome import LOCUS_MUTATION_RATE
    # same order as the engine's own Kong-2012-derived per-locus rate
    assert 0.1 < SPECTRUM.mutation_rate / LOCUS_MUTATION_RATE < 10.0
    # genome-wide deleterious rate in the right range (Eyre-Walker & Keightley
    # 1999 give ~1.6 for humans; ours is lower by construction)
    assert 0.1 < SPECTRUM.deleterious_mutation_rate < 1.6


def test_baseline_load_agrees_with_haldane():
    """Haldane 1937: the mutation load depends on the mutation rate, not on
    how severe each mutation is. A within-15% match is the real content --
    exact equality would require h > 0 at every locus and no q^2 term."""
    observed = 1.0 - np.exp(-SPECTRUM.baseline_load)
    assert observed == pytest.approx(SPECTRUM.haldane_load, rel=0.15)


def test_additive_load_produces_no_inbreeding_depression():
    """The mechanism check. Inbreeding depression is a DOMINANCE phenomenon:
    at h = 1/2 making an allele homozygous costs exactly what carrying two
    heterozygous copies did, so B must vanish however much load there is."""
    sp = build_spectrum(n_loci=200)
    additive = type(sp)(q=sp.q, s=sp.s, h=np.full_like(sp.h, 0.5),
                        mutation_rate=sp.mutation_rate)
    assert additive.lethal_equivalents == pytest.approx(0.0, abs=1e-12)
    assert additive.baseline_load > 0.0          # there is still load, just no F term


def test_predicted_excess_mortality_matches_the_consanguinity_literature():
    """First cousins, F = 1/16. 8.4% excess over the whole pre-adult window,
    against ~3.5% early-childhood excess in Bittles & Black 2010 -- the same
    number over a shorter window."""
    fc = first_cousin_excess_mortality()
    assert 0.05 < fc < 0.12
    assert excess_mortality(0.25) > excess_mortality(0.125) > fc > excess_mortality(0.0)
    assert excess_mortality(0.0) == pytest.approx(0.0, abs=1e-12)


# ======================================================================
# 3. Transmission and determinism
# ======================================================================

def test_founder_load_is_hardy_weinberg_at_the_balance_frequencies():
    rng = np.random.default_rng(1)
    loads = [sample_founder_load(rng) for _ in range(400)]
    dos = np.stack([l.dosage for l in loads])
    observed_q = dos.mean(axis=0).mean() / 2.0
    assert observed_q == pytest.approx(float(SPECTRUM.q.mean()), rel=0.05)


def test_transmission_is_mendelian():
    """Without mutation, every allele a child carries must be present in the
    corresponding parent's genotype -- nothing appears from nowhere."""
    rng = np.random.default_rng(2)
    mum, dad = sample_founder_load(rng), sample_founder_load(rng)
    for _ in range(20):
        kid = transmit_load(mum, dad, rng, mutation=False)
        # maternal haplotype must be one of the mother's two alleles per locus
        assert np.all((kid.haplotypes[0] == mum.haplotypes[0])
                      | (kid.haplotypes[0] == mum.haplotypes[1]))
        assert np.all((kid.haplotypes[1] == dad.haplotypes[0])
                      | (kid.haplotypes[1] == dad.haplotypes[1]))


def test_mutation_is_one_directional():
    """Deleterious alleles appear and never revert. Back-mutation would erode
    the load away within a few hundred generations and there would be no
    mutation-selection balance left to inbreed against."""
    rng = np.random.default_rng(3)
    clean = DeleteriousLoad(np.zeros((2, SPECTRUM.n_loci), dtype=np.int8))
    loaded = DeleteriousLoad(np.ones((2, SPECTRUM.n_loci), dtype=np.int8))
    for _ in range(30):
        assert transmit_load(loaded, loaded, rng).dosage.min() == 2
    total_new = sum(int(transmit_load(clean, clean, rng).dosage.sum())
                    for _ in range(30))
    assert total_new > 0


def test_derived_rng_costs_the_parent_stream_nothing():
    """The property the whole layer depends on: spawning advances the seed
    sequence, not the bit-generator state."""
    a = np.random.default_rng(99)
    b = np.random.default_rng(99)
    derived_rng(b)
    derived_rng(b)
    assert list(a.random(5)) == list(b.random(5))


def test_derived_rng_is_reproducible_and_independent():
    first = derived_rng(np.random.default_rng(5)).random(3)
    again = derived_rng(np.random.default_rng(5)).random(3)
    assert list(first) == list(again)
    parent = np.random.default_rng(5)
    assert list(derived_rng(parent).random(3)) != list(derived_rng(parent).random(3))


def test_load_layer_leaves_founder_sequences_bit_for_bit(monkeypatch):
    """
    Stronger than the #2/#3 layers manage. Those draw from the shared
    generator at the tail of `random_founder`, so founder #0 is unchanged but
    #1 onward shifts (the session-9 audit finding). This layer spawns, so an
    entire SEQUENCE of founders is byte-identical with the layer present and
    absent.
    """
    from health_engine import npc as npc_mod

    def genomes(n):
        rng = np.random.default_rng(1234)
        return [random_founder(f"f{i}", rng).genome.haplotypes.copy()
                for i in range(n)]

    with_layer = genomes(8)
    monkeypatch.setattr(npc_mod, "sample_founder_load", lambda rng, *a, **k: None)
    without_layer = genomes(8)
    for a, b in zip(with_layer, without_layer):
        assert np.array_equal(a, b)


def test_npcs_carry_the_layer_and_children_inherit_it():
    rng = np.random.default_rng(6)
    mother = random_founder("mum", rng, sex="female")
    father = random_founder("dad", rng, sex="male")
    child = reproduce(mother, father, "kid", rng)
    assert mother.load is not None and child.load is not None
    assert child.load.haplotypes.shape == (2, SPECTRUM.n_loci)
    assert 0.0 < child.viability() < 1.0
    # Inherited, not resampled. Allow the handful of loci where a de novo
    # mutation legitimately introduced an allele neither parental copy had.
    from_mother = ((child.load.haplotypes[0] == mother.load.haplotypes[0])
                   | (child.load.haplotypes[0] == mother.load.haplotypes[1]))
    assert from_mother.mean() > 0.99


def test_relative_viability_is_centred_on_one_for_outbred_individuals():
    rng = np.random.default_rng(7)
    pop = [random_founder(f"n{i}", rng) for i in range(300)]
    rv = np.array([p.relative_viability() for p in pop])
    assert rv.mean() == pytest.approx(1.0, abs=0.02)
    assert rv.min() < 1.0 < rv.max()          # real variation around the mean


def test_viability_falls_with_homozygous_load():
    k = SPECTRUM.n_loci
    none = DeleteriousLoad(np.zeros((2, k), dtype=np.int8))
    het = DeleteriousLoad(np.stack([np.ones(k, dtype=np.int8),
                                    np.zeros(k, dtype=np.int8)]))
    hom = DeleteriousLoad(np.ones((2, k), dtype=np.int8))
    assert none.viability() == pytest.approx(1.0)
    assert hom.viability() < het.viability() < none.viability()
    assert none.n_homozygous == 0 and hom.n_homozygous == k


# ======================================================================
# 4. The law
# ======================================================================

def test_lethal_equivalents_are_recoverable_by_regression():
    """
    Morton, Crow & Muller 1956 run on simulated pedigrees: regress ln(observed
    survival) on pedigree F and read B off the slope. Nothing in the pedigree,
    transmission or viability code computes B.
    """
    r = V.inbreeding_depression(n_per_level=2500,
                                rng=np.random.default_rng(20260901))
    assert r.passes()
    assert r.observed_B == pytest.approx(r.expected_B, rel=0.06)
    assert r.r_squared > 0.99
    # depression, not merely a fitted line: survival must actually fall
    assert r.log_survival[-1] < r.log_survival[0] - 0.2


def test_realised_inbreeding_tracks_pedigree_F():
    """Excess homozygosity, measured against the contemporaneous outbred
    cohort, recovers the pedigree coefficient it was never told."""
    r = V.inbreeding_depression(n_per_level=1500,
                                rng=np.random.default_rng(31))
    for pedigree_F, realised in zip(r.levels, r.realised_F):
        assert realised == pytest.approx(pedigree_F, abs=0.012)


def test_mutation_offset_matches_its_closed_form():
    """The constant excess heterozygosity in every cohort is one-way mutation
    over three generations, 2*K*u*3 / sum(2pq) -- not a modelling artefact."""
    r = V.inbreeding_depression(n_per_level=1500,
                                rng=np.random.default_rng(32))
    assert r.mutation_het_offset == pytest.approx(r.predicted_het_offset, rel=0.20)


def test_directional_traits_reproduce_their_published_depression():
    """
    The closed form the calibration was solved against, read back out of the
    architecture. Joshi et al. 2015 (Nature 523:459): -1.2 cm of height and
    -137 ml of FEV1 per 10% F_ROH.

    This replaces `test_trait_layer_has_no_directional_dominance`, which
    asserted the ABSENCE of this mechanism and was written as a tripwire for
    the day it arrived.
    """
    from health_engine.inbreeding import predicted_depression
    for trait, drop in (("height_cm", 1.2), ("lung_capacity", 0.137)):
        assert predicted_depression(trait, 0.10) == pytest.approx(-drop, rel=1e-9), trait
        # linear in F, and zero at F = 0
        assert predicted_depression(trait, 0.0) == 0.0
        assert predicted_depression(trait, 0.20) == pytest.approx(-2 * drop, rel=1e-9)


def test_joshi_nulls_stay_within_their_own_noise():
    """
    Joshi 2015 tested 16 traits and found depression in four. BMI, adiposity,
    blood pressure and lipids were nulls, and this engine reproduces the null
    by leaving them non-directional.

    The assertion is deliberately NOT `== 0`: these traits are uncalibrated in
    this respect, not calibrated to zero, so what is left is the random walk
    of loci.py's N(0, 0.15) dominance ratios. The bar is that the residual is
    an order of magnitude below the smallest depression anyone has measured --
    scaled by the trait's own sd, since a mmHg and a kg/m^2 are not comparable.
    """
    from health_engine.inbreeding import predicted_depression
    from health_engine.traits import ARCHITECTURE
    for trait in ("bmi", "adiposity", "bp_set_point", "lipid_profile"):
        arch = ARCHITECTURE[trait]
        assert not arch.spec.is_directional, trait
        # height loses 1.2/9.0 = 0.133 sd per 10% F; require < 0.04 sd, i.e.
        # under a third of the weakest real signal, so a study of this
        # population would not call it significant either.
        shift_in_sd = abs(predicted_depression(trait, 0.10)) / arch.spec.sd
        assert shift_in_sd < 0.04, f"{trait}: {shift_in_sd:.4f} sd per 10% F"


def test_the_two_inbreeding_mechanisms_stay_separate():
    """Viability depression (this module) and trait depression (traits.py) are
    different literatures and different scales. A change to the load spectrum
    must not move stature, and vice versa."""
    from health_engine.inbreeding import predicted_depression
    before = predicted_depression("height_cm", 0.25)
    heavy = build_spectrum(target_B=4.0)
    assert heavy.lethal_equivalents > SPECTRUM.lethal_equivalents
    assert predicted_depression("height_cm", 0.25) == before


def test_realised_inbreeding_of_an_outbred_founder_is_near_zero():
    rng = np.random.default_rng(8)
    pop = [random_founder(f"n{i}", rng) for i in range(200)]
    F = np.array([realised_inbreeding(p) for p in pop])
    assert F.mean() == pytest.approx(0.0, abs=0.02)
    assert F.std() > 0.0            # it is a measurement, so it scatters


# ======================================================================
# 5. The world layer
# ======================================================================

def test_world_applies_depression_only_when_enabled():
    from simulation import DemographyParams, World

    def run(strength):
        w = World(n_founders=14, seed=21, params=DemographyParams(
            carrying_capacity=120, inbreeding_depression=strength))
        for _ in range(45):
            w.step()
        return sum(1 for m in w.meta.values() if m.death_cause == "inbreeding")

    assert run(0.0) == 0
    assert run(1.0) > 0


def test_inbreeding_avoidance_lowers_pedigree_F_in_a_live_world():
    """The mating guard and the depression layer meet here: forbidding first
    cousins should drive mean pedigree F down toward zero."""
    from simulation import DemographyParams, World

    def mean_F(threshold):
        w = World(n_founders=14, seed=7, params=DemographyParams(
            carrying_capacity=130, inbreeding_threshold=threshold))
        for _ in range(60):
            w.step()
        ped = Pedigree.from_world(w)
        return float(np.mean([ped.inbreeding(n.name) for n in w.living]))

    assert mean_F(0.0625) < mean_F(0.5) + 1e-9
