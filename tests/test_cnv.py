"""
Tests for copy-number variation (roadmap #12).

The mechanism is a gene-dosage multiplier on the expression seam, so the
things worth asserting are: that it is exactly inert at two copies, that the
magnitude follows the closed form, that a deletion and its reciprocal
duplication are exact mirror images, and that the catalogue's de novo rates
reproduce the observed birth prevalence rather than stipulating it.

There is also a test that pins the KNOWN LIMITATION in place
(`test_dosage_scales_deviation_not_gene_product`). It asserts the engine
behaves the way the scoped model says it does, including where that
disagrees with the clinic. If someone later implements hemizygous unmasking,
that test should fail loudly rather than let the docstring quietly go stale.
"""

import numpy as np
import pytest

from health_engine import cnv
from health_engine import validation as V
from health_engine.cnv import (DELETED, DUPLICATED, NORMAL, CopyNumber,
                               REGIONS, birth_prevalence,
                               equilibrium_frequency,
                               expected_de_novo_fraction, induce,
                               locus_mean_contribution, predicted_mean_shift,
                               sample_founder_copy_number, transmit_copy_number)
from health_engine.npc import random_founder, reproduce


# ======================================================================
# Inertness -- the discipline every layer in this engine keeps
# ======================================================================

def test_normal_copy_number_is_exactly_inert():
    """Two copies must give a multiplier of exactly 1.0 at every locus, or
    the calibrated heritabilities move the moment this module is imported."""
    cn = CopyNumber.normal()
    assert cn.is_normal
    assert np.all(cn.dosage_multiplier() == 1.0)
    assert cn.fitness() == 1.0
    assert cn.variants() == []


def test_founders_are_diploid_normal():
    rng = np.random.default_rng(1)
    for i in range(50):
        assert sample_founder_copy_number(rng).is_normal


def test_expression_is_untouched_without_a_cnv():
    rng = np.random.default_rng(2)
    npc = random_founder("a", rng)
    before = npc.expression.copy()
    npc.refresh_expression()
    assert np.array_equal(before, npc.expression)
    assert npc.cnv_variants() == []


# ======================================================================
# The dosage multiplier
# ======================================================================

def test_deletion_halves_and_duplication_raises_by_half():
    from health_engine.loci import LOCUS_BY_SYMBOL
    j = LOCUS_BY_SYMBOL["OCA2"].index
    assert induce("15q11-q13", "deletion").dosage_multiplier()[j] == pytest.approx(0.5)
    assert induce("15q11-q13", "duplication").dosage_multiplier()[j] == pytest.approx(1.5)


def test_multiplier_touches_only_genes_inside_the_region():
    m = induce("22q11.2", "deletion").dosage_multiplier()
    from health_engine.loci import LOCUS_BY_SYMBOL
    assert m[LOCUS_BY_SYMBOL["COMT"].index] == pytest.approx(0.5)
    # a gene on another chromosome entirely must be untouched
    assert m[LOCUS_BY_SYMBOL["OCA2"].index] == 1.0
    assert int(np.count_nonzero(m != 1.0)) == len(REGIONS["22q11.2"].genes)


def test_region_membership_matches_physical_position():
    """The catalogue's claim that COMT is in 22q11.2 and OCA2 in 15q11-q13 is
    checked against the loci table's own coordinates, not asserted."""
    assert REGIONS["22q11.2"].contains("COMT")
    assert not REGIONS["22q11.2"].contains("OCA2")
    assert REGIONS["15q11-q13"].contains("OCA2")
    assert REGIONS["15q11-q13"].contains("HERC2")
    assert not REGIONS["15q11-q13"].contains("COMT")


# ======================================================================
# The law
# ======================================================================

def test_dosage_response_matches_the_closed_form():
    r = V.cnv_dosage_response(trait="eye_color", n=1500,
                              rng=np.random.default_rng(77))
    assert r.passes()
    # Exact against the cohort's own realised frequencies -- this is the
    # claim that tests the mechanism.
    for obs, samp in zip(r.observed_shift, r.sample_shift):
        assert obs == pytest.approx(samp, abs=1e-9)
    # Statistical against the catalogue's frequencies, against a DERIVED
    # standard error rather than a chosen percentage. The shift depends on
    # (p - q), a small difference of large numbers, so the sampling error in
    # p is amplified roughly fivefold on its way into the prediction.
    assert r.catalogue_stderr > 0.0
    for obs, pred in zip(r.observed_shift, r.predicted_shift):
        assert abs(obs - pred) <= 4.0 * r.catalogue_stderr + 1e-9


def test_deletion_and_duplication_are_exact_mirror_images():
    """Jacquemont et al. 2011's signature. It is exact here rather than
    approximate because the multiplier is linear: (1/2 - 1) and (3/2 - 1)
    are equal and opposite by construction."""
    r = V.cnv_dosage_response(trait="skin_tone", n=1000,
                              rng=np.random.default_rng(78))
    assert r.mirror_asymmetry < 1e-12
    assert r.observed_shift[0] == pytest.approx(-r.observed_shift[2], abs=1e-12)
    assert r.observed_shift[1] == pytest.approx(0.0, abs=1e-12)


def test_predicted_shift_is_zero_for_a_trait_the_region_does_not_touch():
    assert predicted_mean_shift("height_cm", "15q11-q13", 1) == 0.0
    assert locus_mean_contribution("height_cm", "OCA2") == 0.0


def test_applying_a_cnv_to_an_npc_moves_its_phenotype():
    rng = np.random.default_rng(9)
    npc = random_founder("x", rng)
    before = npc.liability("eye_color")
    npc.apply_cnv("15q11-q13", "deletion")
    after = npc.liability("eye_color")
    assert after != before
    v = npc.cnv_variants()
    assert len(v) == 1 and v[0]["copies"] == 1 and v[0]["kind"] == "deletion"
    assert v[0]["parent_of_origin"] == "maternal"


def test_dosage_scales_deviation_not_gene_product():
    """
    PINS A KNOWN LIMITATION, deliberately.

    A deletion moves an individual TOWARD the reference configuration, not
    toward a null, because the expression seam scales a locus's genotypic
    deviation. For an individual homozygous for OCA2's derived (light)
    allele, halving the locus therefore makes them DARKER -- the opposite of
    the hypopigmentation seen in real 15q11-q13 deletion patients.

    The engine is allowed to be wrong here as long as it is wrong in the
    documented way. If hemizygous unmasking is ever implemented this test
    should fail, which is the point of it.
    """
    from health_engine.loci import LOCUS_BY_SYMBOL
    rng = np.random.default_rng(11)
    j = LOCUS_BY_SYMBOL["OCA2"].index
    k = LOCUS_BY_SYMBOL["HERC2"].index

    # find someone homozygous for the derived allele at both pigment loci
    subject = None
    for i in range(4000):
        n = random_founder(f"s{i}", rng)
        if n.genome.dosage[j] == 2 and n.genome.dosage[k] == 2:
            subject = n
            break
    assert subject is not None, "no double homozygote found"

    before = subject.liability("skin_tone")
    subject.apply_cnv("15q11-q13", "deletion")
    after = subject.liability("skin_tone")
    # skin_tone is 0 = light .. 1 = dark, so a rise is DARKER
    assert after > before


# ======================================================================
# Inheritance, de novo formation, selection
# ======================================================================

def test_transmission_is_mendelian_without_de_novo():
    rng = np.random.default_rng(3)
    mum = induce("22q11.2", "deletion")
    dad = CopyNumber.normal()
    seen = set()
    for _ in range(200):
        kid = transmit_copy_number(mum, dad, rng, de_novo=False)
        seen.add(kid.copies_of("22q11.2"))
    # a heterozygous carrier x normal gives 1 or 2 copies, ~50:50, never 3
    assert seen == {1, 2}


def test_de_novo_produces_both_reciprocal_products():
    """One NAHR event makes a deletion and a duplication, so both must appear
    at similar rates. Rate is scaled up here purely to make them observable."""
    rng = np.random.default_rng(4)
    normal = CopyNumber.normal()
    counts = {1: 0, 2: 0, 3: 0}
    for _ in range(3000):
        kid = transmit_copy_number(normal, normal, rng, rate_scale=500.0)
        counts[kid.copies_of("22q11.2")] = counts.get(
            kid.copies_of("22q11.2"), 0) + 1
    assert counts[1] > 20 and counts[3] > 20
    ratio = counts[1] / counts[3]
    assert 0.5 < ratio < 2.0


def test_no_de_novo_at_the_default_rate_in_a_small_sample():
    """Sanity on the magnitude: at ~1e-4 per gamete, a few hundred births
    should almost never produce one. If this starts failing the rates have
    drifted by orders of magnitude."""
    rng = np.random.default_rng(5)
    normal = CopyNumber.normal()
    n_variant = sum(0 if transmit_copy_number(normal, normal, rng).is_normal
                    else 1 for _ in range(400))
    assert n_variant <= 2


def test_birth_prevalence_matches_the_clinical_figure():
    """The de novo rate was solved backwards from ~1/4000 for 22q11.2, so
    this checks the arithmetic closes rather than discovering anything."""
    assert 1 / birth_prevalence("22q11.2") == pytest.approx(4000, rel=0.10)
    assert 1 / birth_prevalence("15q11-q13") == pytest.approx(12000, rel=0.15)


def test_de_novo_fraction_equals_the_selection_coefficient():
    """At mutation-selection balance the inherited share of carriers is
    exactly the carrier fitness, so the sporadic share is exactly s. >90% of
    22q11.2 deletions are de novo in the clinic, which is what pins its
    fitness below 0.1."""
    for name, r in REGIONS.items():
        assert expected_de_novo_fraction(name) == pytest.approx(
            1.0 - r.deletion_fitness)
    assert expected_de_novo_fraction("22q11.2") > 0.90


def test_equilibrium_frequency_is_mutation_over_selection():
    r = REGIONS["22q11.2"]
    expected = 0.5 * r.de_novo_rate / (1.0 - r.deletion_fitness)
    assert equilibrium_frequency("22q11.2") == pytest.approx(expected)


def test_cnv_carries_a_fitness_cost():
    rng = np.random.default_rng(6)
    healthy = random_founder("h", rng)
    carrier = random_founder("c", np.random.default_rng(6))
    carrier.apply_cnv("22q11.2", "deletion")
    assert carrier.relative_viability() < 0.2 * healthy.relative_viability()
    # duplication is milder than deletion, as the catalogue says
    dup = random_founder("d", np.random.default_rng(6))
    dup.apply_cnv("22q11.2", "duplication")
    assert dup.relative_viability() > carrier.relative_viability()


def test_children_inherit_the_layer_and_expression_is_recomputed():
    rng = np.random.default_rng(7)
    mother = random_founder("mum", rng, sex="female")
    father = random_founder("dad", rng, sex="male")
    mother.apply_cnv("15q11-q13", "deletion")
    got_it = False
    for i in range(40):
        kid = reproduce(mother, father, f"k{i}", rng)
        assert kid.copy_number is not None
        if kid.copies_of_region("15q11-q13") == 1:
            got_it = True
            from health_engine.loci import LOCUS_BY_SYMBOL
            j = LOCUS_BY_SYMBOL["OCA2"].index
            # the multiplier must actually have reached `expression`
            assert kid.expression[j] == pytest.approx(0.5, abs=1e-9)
    assert got_it, "no child inherited the deletion in 40 births"


def test_cnv_layer_leaves_the_autosomal_stream_bit_for_bit(monkeypatch):
    """Same spawned-generator guarantee as the load layer: adding this to
    random_founder must not shift any founder in a shared-rng sequence."""
    from health_engine import npc as npc_mod

    def genomes():
        rng = np.random.default_rng(4321)
        return [random_founder(f"f{i}", rng).genome.haplotypes.copy()
                for i in range(6)]

    with_layer = genomes()
    monkeypatch.setattr(npc_mod, "sample_founder_copy_number",
                        lambda rng, *a, **k: None)
    without_layer = genomes()
    for a, b in zip(with_layer, without_layer):
        assert np.array_equal(a, b)
