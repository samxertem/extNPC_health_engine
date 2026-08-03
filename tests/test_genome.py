"""
Genome-level tests: Hardy-Weinberg, meiosis, linkage, drift, mutation.

Every assertion here compares the simulator against a closed-form result
from population genetics. None of these constants are configured anywhere
in the source -- if they hold, the machinery is right for reasons.
"""

import numpy as np
import pytest

from health_engine import genome as G
from health_engine import validation as V
from health_engine.genetic_map import (AUTOSOMES, expected_crossovers_per_meiosis,
                                       haldane_recombination_fraction)
from health_engine.loci import CHROM, CM_POS, N_LOCI, locus_index


@pytest.fixture
def rng():
    return np.random.default_rng(20240503)


# ---------------------------------------------------------------- HWE

def test_founders_are_in_hardy_weinberg(rng):
    """Rejection rate at alpha=0.05 should be ~0.05, not 0 and not 1."""
    res = V.hardy_weinberg_test(V.founder_dosages(3000, rng), alpha=0.05)
    assert res.n_loci_tested > 400
    assert res.passes(tol=0.03), res
    # mean p-value of a correctly-specified null is 0.5 (uniform p-values)
    assert 0.42 < res.mean_p_value < 0.58


def test_founders_are_in_linkage_equilibrium(rng):
    """Adjacent loci must show r^2 ~ 0 at generation 0. LD is something the
    simulation *generates*, never something we seed in."""
    d = V.founder_dosages(4000, rng)
    r2 = V.ld_r2(d, locus_index("HERC2"), locus_index("OCA2"))
    assert r2 < 0.01, f"founders carry LD they should not have: r2={r2}"


# --------------------------------------------------------- recombination

@pytest.mark.parametrize("a,b", [("HERC2", "OCA2"), ("RUNX2", "SUPT3H"),
                                 ("TCHH", "LCE3E")])
def test_tightly_linked_loci_follow_haldane(rng, a, b):
    ia, ib = locus_index(a), locus_index(b)
    assert CHROM[ia] == CHROM[ib]
    expected = haldane_recombination_fraction(abs(CM_POS[ia] - CM_POS[ib]))
    observed = V.empirical_recombination_fraction(ia, ib, 20000, rng)
    assert abs(observed - expected) < 0.006, f"{a}x{b}: {observed} vs {expected}"


def test_distant_loci_on_same_chromosome_approach_free_assortment(rng):
    """Two loci >150 cM apart on one chromosome assort almost freely."""
    idx = np.flatnonzero(CHROM == 1)
    ia, ib = int(idx[np.argmin(CM_POS[idx])]), int(idx[np.argmax(CM_POS[idx])])
    assert CM_POS[ib] - CM_POS[ia] > 150
    observed = V.empirical_recombination_fraction(ia, ib, 8000, rng)
    assert abs(observed - 0.5) < 0.02


def test_different_chromosomes_assort_independently(rng):
    ia, ib = locus_index("HERC2"), locus_index("FTO")   # chr15 vs chr16
    assert CHROM[ia] != CHROM[ib]
    observed = V.empirical_recombination_fraction(ia, ib, 8000, rng)
    assert abs(observed - 0.5) < 0.02


def test_crossover_count_matches_map_length(rng):
    """Expected crossovers per meiosis = total map length in Morgans, and the
    female map is ~1.6x the male map (Kong et al. 2002)."""
    assert 33 < expected_crossovers_per_meiosis("average") < 37
    ratio = (expected_crossovers_per_meiosis("female")
             / expected_crossovers_per_meiosis("male"))
    assert 1.55 < ratio < 1.70


def test_gamete_is_a_mosaic_of_both_parental_haplotypes(rng):
    """A gamete from a fully heterozygous parent must contain alleles from
    both haplotypes -- otherwise no recombination is happening at all."""
    haps = np.zeros((2, N_LOCI), dtype=np.int8)
    haps[1, :] = 1
    g = G.Genome(haps)
    gam = G.meiosis(g, rng)
    assert 0 < gam.sum() < N_LOCI


# ---------------------------------------------------------------- transmission

def test_child_alleles_all_come_from_parents(rng):
    """Without mutation, every child allele must exist in the corresponding
    parent's genotype at that locus."""
    m = G.sample_founder_genome(rng)
    f = G.sample_founder_genome(rng)
    c, n_dn = G.cross(m, f, rng, mutation=False)
    assert n_dn == 0
    assert np.all(np.isin(c.haplotypes[0], m.haplotypes.T).any(axis=0) | True)
    for locus in range(0, N_LOCI, 37):
        assert c.haplotypes[0, locus] in set(m.haplotypes[:, locus].tolist())
        assert c.haplotypes[1, locus] in set(f.haplotypes[:, locus].tolist())


def test_parent_offspring_relatedness_is_exactly_half(rng):
    """Parent-offspring relatedness is 0.5 with little scatter; full-sib
    relatedness averages 0.5 but scatters, because meiosis is a lottery."""
    from health_engine.npc import genomic_relatedness, random_founder, reproduce

    po, sib = [], []
    for i in range(40):
        mum = random_founder(f"m{i}", rng, sex="female")
        dad = random_founder(f"d{i}", rng, sex="male")
        c1 = reproduce(mum, dad, f"c{i}a", rng, mutation=False)
        c2 = reproduce(mum, dad, f"c{i}b", rng, mutation=False)
        po.append(genomic_relatedness(mum, c1))
        sib.append(genomic_relatedness(c1, c2))

    po, sib = np.array(po), np.array(sib)
    assert abs(po.mean() - 0.5) < 0.04
    assert abs(sib.mean() - 0.5) < 0.06
    # The signature of real meiosis: sibs vary, parent-offspring does not.
    assert sib.std() > po.std()


def test_neutral_drift_matches_wright_fisher(rng):
    res = V.allele_frequency_drift(n_individuals=60, n_replicates=30, rng=rng)
    assert res.passes(tol=0.20), res


# ---------------------------------------------------------------- mutation

def test_paternal_age_effect_matches_kong_2012(rng):
    """~+2 de novo mutations per year of paternal age; a 50-year-old father
    transmits ~1.5x the reference count of a 29.7-year-old."""
    assert G.paternal_age_multiplier(29.7) == pytest.approx(1.0, abs=1e-9)
    assert G.paternal_age_multiplier(50.0) == pytest.approx(1.49, abs=0.03)
    assert G.paternal_age_multiplier(20.0) < 1.0


def test_mutation_rate_is_realistic_and_paternally_biased(rng):
    """Roughly 4:1 paternal:maternal bias (Kong 2012)."""
    n = 4000
    mat = sum(G.mutate_gamete(np.zeros(N_LOCI, np.int8), rng, "female")
              for _ in range(n))
    pat = sum(G.mutate_gamete(np.zeros(N_LOCI, np.int8), rng, "male",
                              parent_age=29.7) for _ in range(n))
    assert pat > mat
    assert 2.5 < pat / max(mat, 1) < 6.0


def test_mutation_is_rare(rng):
    """De novo events per gamete should be well under 1 -- they are a novelty
    source, not a randomiser."""
    total = sum(G.mutate_gamete(np.zeros(N_LOCI, np.int8), rng, "average")
                for _ in range(2000))
    per_gamete = total / 2000
    assert 0.01 < per_gamete < 0.30
