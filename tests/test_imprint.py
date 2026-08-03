"""
Genomic imprinting (roadmap #4).

The headline is the reciprocal-heterozygote law: two individuals with the
SAME genotype at an imprinted locus, differing only in which parent supplied
the alternate allele, must differ in phenotype by exactly 2*s*a. Mendelian
inheritance says the gap is zero. Nothing in the trait layer computes 2*s*a.
"""

import numpy as np
import pytest

from health_engine import imprint, validation
from health_engine.genome import Genome
from health_engine.imprint import (IMPRINTED, MATERNAL, PATERNAL,
                                   ImprintedLocus, imprint_state,
                                   imprint_strength_vector,
                                   expressed_haplotype_vector, relax_imprint)
from health_engine.loci import LOCUS_BY_SYMBOL, N_LOCI
from health_engine.npc import NPC, random_founder, reproduce
from health_engine.traits import ARCHITECTURE, liability

IGF2_I = LOCUS_BY_SYMBOL["IGF2"].index


@pytest.fixture
def rng():
    return np.random.default_rng(4004)


def _pair(base: NPC, locus_i: int, expressed_hap: int):
    """Reciprocal heterozygotes at `locus_i`: identical genotype (dosage 1),
    opposite parent of origin. Returns (alt_from_expressed, alt_from_silenced)."""
    silenced = 1 - expressed_hap
    h_hi = base.genome.haplotypes.copy()
    h_hi[expressed_hap, locus_i] = 1
    h_hi[silenced, locus_i] = 0
    h_lo = base.genome.haplotypes.copy()
    h_lo[expressed_hap, locus_i] = 0
    h_lo[silenced, locus_i] = 1
    return (NPC(name="hi", genome=Genome(h_hi), deviates=base.deviates),
            NPC(name="lo", genome=Genome(h_lo), deviates=base.deviates))


# ----------------------------------------------------------------------
# Catalogue
# ----------------------------------------------------------------------

def test_igf2_is_imprinted_and_paternally_expressed():
    """DeChiara 1991: IGF2 is expressed from the paternal allele."""
    spec = IMPRINTED["IGF2"]
    assert spec.expressed_from == PATERNAL
    assert spec.silenced_parent == "maternal"
    assert 0.0 < spec.strength <= 1.0


def test_strength_vector_is_zero_off_the_imprinted_loci():
    s = imprint_strength_vector()
    assert s.shape == (N_LOCI,)
    assert s[IGF2_I] > 0.0
    assert np.count_nonzero(s) == len(IMPRINTED)


# ----------------------------------------------------------------------
# The benchmark: reciprocal heterozygotes
# ----------------------------------------------------------------------

def test_reciprocal_heterozygotes_differ(rng):
    """Roadmap #4's benchmark, verbatim: same genotype, opposite parent of
    origin, different phenotype."""
    base = random_founder("base", rng)
    hi, lo = _pair(base, IGF2_I, PATERNAL)
    assert hi.genome.dosage[IGF2_I] == lo.genome.dosage[IGF2_I] == 1
    assert hi.phenotype()["height_cm"] != lo.phenotype()["height_cm"]
    # paternal allele is the expressed one, so alt-from-father is the taller
    assert hi.phenotype()["height_cm"] > lo.phenotype()["height_cm"]


def test_reciprocal_gap_matches_the_closed_form():
    """gap == 2*s*a, to floating-point precision."""
    r = validation.imprinting_reciprocal_cross(trait="height_cm", n=400)
    assert r.passes()
    assert r.observed_gap == pytest.approx(r.expected_gap, abs=1e-12)
    assert r.expected_gap > 0.0


def test_gap_holds_for_a_second_trait():
    """IGF2 is pleiotropic here; the law is per-locus, so it must hold on
    every trait the locus touches."""
    r = validation.imprinting_reciprocal_cross(trait="adiposity", n=400)
    assert r.observed_gap == pytest.approx(r.expected_gap, abs=1e-12)


# ----------------------------------------------------------------------
# What imprinting must NOT do
# ----------------------------------------------------------------------

def test_homozygotes_are_unaffected(rng):
    """Parent of origin is meaningless when both copies carry the same
    allele -- imprinting must be a no-op there."""
    base = random_founder("base", rng)
    arch = ARCHITECTURE["height_cm"]
    for allele in (0, 1):
        h = base.genome.haplotypes.copy()
        h[:, IGF2_I] = allele
        npc = NPC(name="hom", genome=Genome(h), deviates=base.deviates)
        with_i = liability(arch, npc.genome.dosage, npc.deviates,
                           npc.expression, npc.imprint_state())
        without = liability(arch, npc.genome.dosage, npc.deviates,
                            npc.expression, None)
        assert with_i == pytest.approx(without, abs=1e-12)


def test_zero_strength_is_bit_for_bit_identical(rng):
    """The whole layer must vanish at strength 0 -- this is what keeps a
    world with no imprinted loci identical to the pre-#4 engine."""
    base = random_founder("base", rng)
    arch = ARCHITECTURE["height_cm"]
    off = imprint_state(base.genome,
                        strength=np.zeros(N_LOCI),
                        expressed_hap=expressed_haplotype_vector())
    a = liability(arch, base.genome.dosage, base.deviates, base.expression, off)
    b = liability(arch, base.genome.dosage, base.deviates, base.expression, None)
    assert a == b


def test_non_imprinted_traits_are_untouched(rng):
    """A trait IGF2 carries no weight on must be numerically identical."""
    base = random_founder("base", rng)
    for trait in ("neuroticism", "chronotype", "hearing_ability"):
        arch = ARCHITECTURE[trait]
        if IGF2_I in set(arch.idx.tolist()):
            continue
        with_i = liability(arch, base.genome.dosage, base.deviates,
                           base.expression, base.imprint_state())
        without = liability(arch, base.genome.dosage, base.deviates,
                            base.expression, None)
        assert with_i == without


def test_population_mean_is_preserved_at_zero_dominance():
    """IGF2 is purely additive (dominance_ratio 0.0), and the algebra then
    predicts NO mean shift: imprinting moves individual values and variance,
    not the population average. Same lesson as the epigenome and GRN layers."""
    r = validation.imprinting_reciprocal_cross(trait="height_cm", n=2000)
    assert r.dominance == 0.0
    assert abs(r.mean_shift) < 0.02


# ----------------------------------------------------------------------
# Germline erasure and re-establishment
# ----------------------------------------------------------------------

def test_the_same_allele_flips_expression_with_transmitting_parent(rng):
    """
    The core of imprinting: an allele's mark comes from the parent that
    transmitted it, not from its own history. Put the identical alternate
    allele on the maternal copy in one individual and the paternal copy in
    another -- it is silenced in the first and expressed in the second.
    """
    base = random_founder("base", rng)
    hi, lo = _pair(base, IGF2_I, PATERNAL)
    assert imprint.parent_of_origin_report(hi.genome)["expressed_allele"] == 1
    assert imprint.parent_of_origin_report(lo.genome)["expressed_allele"] == 0
    assert imprint.parent_of_origin_report(lo.genome)["silenced_allele"] == 1


def test_reproduce_preserves_parent_of_origin(rng):
    """
    Germline re-establishment is exact only if haplotype 0 is ALWAYS the
    mother's contribution and 1 always the father's. Assert it across many
    births: every allele on the child's paternal row must be one the father
    actually carries, and likewise for the mother.
    """
    mum = random_founder("mum", rng, sex="female")
    dad = random_founder("dad", rng, sex="male")
    for k in range(25):
        kid = reproduce(mum, dad, f"kid{k}", rng)
        mat, pat = kid.genome.haplotypes[MATERNAL], kid.genome.haplotypes[PATERNAL]
        in_mum = np.isin(mat, mum.genome.haplotypes[:, np.arange(N_LOCI)])
        # per-locus membership, ignoring the rare de novo mutation
        mum_ok = (mat == mum.genome.haplotypes[0]) | (mat == mum.genome.haplotypes[1])
        dad_ok = (pat == dad.genome.haplotypes[0]) | (pat == dad.genome.haplotypes[1])
        assert mum_ok.sum() >= N_LOCI - 3, "maternal row must come from the mother"
        assert dad_ok.sum() >= N_LOCI - 3, "paternal row must come from the father"
        assert in_mum.shape == (N_LOCI,)


# ----------------------------------------------------------------------
# The mechanism is general, not IGF2-specific
# ----------------------------------------------------------------------

def test_maternally_expressed_locus_reverses_the_direction(rng):
    """Flip which parent is expressed and the sign of the gap flips too."""
    base = random_founder("base", rng)
    arch = ARCHITECTURE["height_cm"]
    cat = {"IGF2": ImprintedLocus("IGF2", MATERNAL, 0.9, "test: maternally expressed")}
    s = imprint_strength_vector(cat)
    hap = expressed_haplotype_vector(cat)

    hi, lo = _pair(base, IGF2_I, MATERNAL)     # alt on the maternal (expressed) row
    def lia(n):
        return liability(arch, n.genome.dosage, n.deviates, n.expression,
                         imprint_state(n.genome, s, hap))
    assert lia(hi) > lia(lo)


def test_multiple_imprinted_loci_are_additive(rng):
    """Imprint a second locus and the gaps add -- the layer is per-locus."""
    base = random_founder("base", rng)
    arch = ARCHITECTURE["height_cm"]
    other = "HMGA2"
    j = LOCUS_BY_SYMBOL[other].index
    cat = {
        "IGF2": ImprintedLocus("IGF2", PATERNAL, 1.0, ""),
        other: ImprintedLocus(other, PATERNAL, 1.0, ""),
    }
    s = imprint_strength_vector(cat)
    hap = expressed_haplotype_vector(cat)
    assert np.count_nonzero(s) == 2

    h_hi = base.genome.haplotypes.copy()
    h_lo = base.genome.haplotypes.copy()
    for i in (IGF2_I, j):
        h_hi[PATERNAL, i], h_hi[MATERNAL, i] = 1, 0
        h_lo[PATERNAL, i], h_lo[MATERNAL, i] = 0, 1
    hi = NPC(name="hi", genome=Genome(h_hi), deviates=base.deviates)
    lo = NPC(name="lo", genome=Genome(h_lo), deviates=base.deviates)

    def lia(n):
        return liability(arch, n.genome.dosage, n.deviates, n.expression,
                         imprint_state(n.genome, s, hap))

    idx = arch.idx.tolist()
    expected = 2.0 * (float(arch.a[idx.index(IGF2_I)]) + float(arch.a[idx.index(j)]))
    assert lia(hi) - lia(lo) == pytest.approx(expected, abs=1e-10)


# ----------------------------------------------------------------------
# Loss of imprinting (the Dutch Hunger Winter axis)
# ----------------------------------------------------------------------

def test_relaxing_the_imprint_shrinks_the_gap_proportionally(rng):
    """
    Heijmans 2008: prenatal famine leaves IGF2 hypomethylated for life --
    a partial LOSS of imprinting. Because the gap is 2*s*a, halving s must
    halve the gap, and abolishing it must restore biallelic expression.
    """
    base = random_founder("base", rng)
    arch = ARCHITECTURE["height_cm"]
    hap = expressed_haplotype_vector()
    hi, lo = _pair(base, IGF2_I, PATERNAL)

    def gap(strength_vec):
        return (liability(arch, hi.genome.dosage, hi.deviates, hi.expression,
                          imprint_state(hi.genome, strength_vec, hap))
                - liability(arch, lo.genome.dosage, lo.deviates, lo.expression,
                            imprint_state(lo.genome, strength_vec, hap)))

    full = gap(relax_imprint(1.0))
    half = gap(relax_imprint(0.5))
    none = gap(relax_imprint(0.0))
    assert half == pytest.approx(0.5 * full, abs=1e-10)
    assert none == pytest.approx(0.0, abs=1e-12)


# ----------------------------------------------------------------------
# Plumbing
# ----------------------------------------------------------------------

def test_imprint_state_is_cached_and_deterministic(rng):
    npc = random_founder("x", rng)
    a, b = npc.imprint_state(), npc.imprint_state()
    assert a is b
    assert npc.phenotype() == npc.phenotype()


def test_mono_dosage_is_twice_the_expressed_allele(rng):
    npc = random_founder("x", rng)
    st = npc.imprint_state()
    expressed = int(npc.genome.haplotypes[PATERNAL, IGF2_I])
    assert st.mono_dosage[IGF2_I] == 2 * expressed
    assert set(np.unique(st.mono_dosage)).issubset({0, 2})
