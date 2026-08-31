"""Property-based tests: statements that must hold for EVERY input.

The rest of the suite picks a seed, builds one family and asserts one number.
That checks one point in a very large space, and a bug at any other point ships
green. These say what must be true of all of them and let Hypothesis hunt for
the counterexample, then shrink it to the smallest input that still fails.

WHAT THIS ALREADY EARNED. The first version of `test_every_novel_allele_is_a
_mutation` asserted the obvious thing, that a child's alleles are alleles its
parents carried. Hypothesis falsified it in seconds, because de novo mutation
exists. The second version asserted that the count of novel alleles equals the
reported de novo count. Falsified again: alleles are binary, so a mutation at a
heterozygous locus lands on a value the parent already carried and leaves no
trace. The engine was right both times and the stated understanding was wrong,
which is the entire point of writing properties down.

Budgets are small on purpose. Each example here builds real genomes, so these
run in seconds rather than the milliseconds a pure-function property would.
"""
from __future__ import annotations

import numpy as np
import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from health_engine.body_metrics import body_composition, body_segments
from health_engine.genome import N_LOCI
from health_engine.npc import random_founder, reproduce
from health_engine.physiology import PhysiologicalState

# Building a founder genome is not free, so the default deadline (which is
# per-example and unforgiving on a cold import) is switched off deliberately
# rather than by accident.
SLOW = settings(max_examples=40, deadline=None,
                suppress_health_check=[HealthCheck.too_slow])

SEEDS = st.integers(min_value=0, max_value=2 ** 31 - 1)


def _family(ms, fs, cs):
    mum = random_founder("mum", np.random.default_rng(ms), sex="female")
    dad = random_founder("dad", np.random.default_rng(fs), sex="male")
    kid = reproduce(mum, dad, "kid", np.random.default_rng(cs))
    return mum, dad, kid


# ====================================================== transmission

@SLOW
@given(ms=SEEDS, fs=SEEDS, cs=SEEDS)
def test_every_novel_allele_is_a_mutation(ms, fs, cs):
    """No allele may appear from nowhere.

    A child's maternal haplotype must match one of the mother's two alleles at
    every locus, EXCEPT where a de novo mutation put something new there. So
    the count of unexplained loci can never exceed the mutation count. The
    inequality rather than equality is the part Hypothesis taught us: a
    mutation at a heterozygous locus is undetectable by this test.
    """
    mum, dad, kid = _family(ms, fs, cs)
    m, f, c = (mum.genome.haplotypes, dad.genome.haplotypes,
               kid.genome.haplotypes)
    novel = int((~((c[0] == m[0]) | (c[0] == m[1]))).sum()
                + (~((c[1] == f[0]) | (c[1] == f[1]))).sum())
    assert novel <= kid.de_novo_mutations, (
        "%d loci match no parental allele but only %d de novo mutations were "
        "reported" % (novel, kid.de_novo_mutations))


@SLOW
@given(ms=SEEDS, fs=SEEDS, cs=SEEDS)
def test_a_child_genome_is_well_formed(ms, fs, cs):
    """Shape and alphabet, for any parents. A corrupted crossover walk would
    show up here before it showed up as a wrong heritability."""
    _, _, kid = _family(ms, fs, cs)
    h = kid.genome.haplotypes
    assert h.shape == (2, N_LOCI)
    assert set(np.unique(h)).issubset({0, 1})


@SLOW
@given(ms=SEEDS, fs=SEEDS, cs=SEEDS)
def test_heterozygosity_is_a_fraction(ms, fs, cs):
    _, _, kid = _family(ms, fs, cs)
    assert 0.0 <= kid.genome.heterozygosity() <= 1.0


@SLOW
@given(ms=SEEDS, fs=SEEDS, cs=SEEDS)
def test_reproduction_is_deterministic_in_its_seed(ms, fs, cs):
    """The reproducibility claim, as a property rather than as one fixed seed.
    Two children built from identical inputs must be identical."""
    mum = random_founder("mum", np.random.default_rng(ms), sex="female")
    dad = random_founder("dad", np.random.default_rng(fs), sex="male")
    a = reproduce(mum, dad, "kid", np.random.default_rng(cs))
    b = reproduce(mum, dad, "kid", np.random.default_rng(cs))
    assert np.array_equal(a.genome.haplotypes, b.genome.haplotypes)
    assert a.de_novo_mutations == b.de_novo_mutations


# ====================================================== anthropometry

@given(height=st.floats(min_value=40.0, max_value=230.0),
       ratio=st.floats(min_value=0.40, max_value=0.60))
@settings(max_examples=200, deadline=None)
def test_body_segments_close_exactly(height, ratio):
    """Sitting height plus leg length IS stature. Not approximately: the parts
    are derived from the whole, so the identity holds to float precision."""
    seg = body_segments(height, ratio)
    assert seg["sitting_height_cm"] + seg["leg_length_cm"] == pytest.approx(
        height, rel=0, abs=1e-9)
    assert all(v > 0 for v in seg.values())


@given(bmi=st.floats(min_value=10.0, max_value=60.0),
       lean=st.floats(min_value=0.30, max_value=0.95),
       height=st.floats(min_value=100.0, max_value=220.0))
@settings(max_examples=200, deadline=None)
def test_body_composition_closes_exactly(bmi, lean, height):
    """Lean mass plus fat mass IS body mass, for every body the model can
    describe rather than for the one the fixture happened to pick."""
    comp = body_composition(bmi, lean, height)
    assert comp["lean_mass_kg"] + comp["fat_mass_kg"] == pytest.approx(
        comp["body_mass_kg"], rel=0, abs=1e-9)
    assert comp["fat_mass_kg"] >= 0.0
    assert 0.0 <= comp["body_fat_percent"] <= 100.0


# ====================================================== body to mind

@given(glucose=st.floats(min_value=0.0, max_value=1.0),
       cortisol=st.floats(min_value=0.0, max_value=2.0),
       hydration=st.floats(min_value=0.0, max_value=1.0),
       phase=st.floats(min_value=0.0, max_value=23.999))
@settings(max_examples=150, deadline=None)
def test_action_distribution_is_a_distribution(glucose, cortisol, hydration,
                                               phase):
    """Whatever internal state the body reaches, the prior handed to an agent
    must still be a probability distribution. A softmax that overflows, or a
    weight that goes negative, breaks this before it breaks a downstream agent
    in a way nobody could trace."""
    rng = np.random.default_rng(20260817)
    params = random_founder("subject", rng).hormone_params()
    state = PhysiologicalState(glucose=glucose, cortisol=cortisol,
                               hydration=hydration, circadian_phase=phase)
    d = state.action_distribution(params)
    assert d, "no action classes returned"
    assert all(v >= 0.0 for v in d.values()), "a negative probability"
    assert all(np.isfinite(v) for v in d.values()), "a non-finite probability"
    assert sum(d.values()) == pytest.approx(1.0, abs=1e-9)


@given(glucose=st.floats(min_value=0.0, max_value=1.0),
       cortisol=st.floats(min_value=0.0, max_value=2.0))
@settings(max_examples=100, deadline=None)
def test_the_prompt_is_always_renderable(glucose, cortisol):
    """The sentence handed to a language model must exist for every state, not
    only for the two the benchmark uses."""
    rng = np.random.default_rng(20260817)
    params = random_founder("subject", rng).hormone_params()
    text = PhysiologicalState(glucose=glucose,
                              cortisol=cortisol).to_prompt(params)
    assert text.startswith("[body]")
    assert len(text) > len("[body]")


# ====================================================== kinship

@SLOW
@given(ms=SEEDS, fs=SEEDS, cs=SEEDS)
def test_relatedness_is_symmetric_and_bounded(ms, fs, cs):
    """Genomic relatedness is a property of a pair, so it cannot depend on the
    order the pair is written in."""
    from health_engine.npc import genomic_relatedness
    mum, dad, kid = _family(ms, fs, cs)
    assume(mum.name != kid.name)
    ab = genomic_relatedness(mum, kid)
    ba = genomic_relatedness(kid, mum)
    assert ab == pytest.approx(ba, abs=1e-12)
    assert -1.0 <= ab <= 2.0, "relatedness outside any meaningful range"
