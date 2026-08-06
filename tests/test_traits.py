"""
Trait-level tests: variance-component calibration, heritability recovery,
the breeder's equation, pleiotropy, and the determinism of phenotype().
"""

import numpy as np
import pytest

from health_engine import traits as T
from health_engine import validation as V
from health_engine.loci import LOCUS_BY_SYMBOL
from health_engine.npc import random_founder, reproduce


@pytest.fixture
def rng():
    return np.random.default_rng(20240504)


# ------------------------------------------------------- calibration

def test_every_trait_has_unit_phenotypic_variance():
    """V_A + V_D + V_I + V_GxE + V_E = 1 by construction, so liabilities are
    standard normal and categorical thresholds are plain normal quantiles."""
    for name, arch in T.ARCHITECTURE.items():
        vp = arch.v_a + arch.v_d + arch.v_i + arch.v_gxe + arch.v_e
        assert vp == pytest.approx(1.0, abs=1e-6), f"{name}: V_P = {vp}"


def test_additive_variance_hits_the_target_heritability():
    """The quadratic solve in _calibrate_trait must land V_A exactly on h^2,
    despite dominance leaking into V_A through the d(q-p) term."""
    for name, arch in T.ARCHITECTURE.items():
        assert arch.v_a == pytest.approx(arch.spec.h2, abs=1e-6), name
        assert arch.realised_h2 == pytest.approx(arch.spec.h2, abs=1e-6), name


def test_dominance_and_epistasis_hit_their_targets():
    """V_D is an input for most traits and an output for a directional one, so
    each is checked against whatever it was actually calibrated to."""
    for name, arch in T.ARCHITECTURE.items():
        if arch.spec.is_directional:
            # V_D was not requested; the depression slope was. Check that.
            twopq = 2.0 * arch.p * (1.0 - arch.p)
            assert float(np.sum(twopq * arch.d)) == pytest.approx(
                arch.spec.target_dominance_sum(), rel=1e-9), name
            # ... and that V_D nonetheless came out a legal variance share.
            assert 0.0 < arch.v_d < 1.0 - arch.spec.h2, name
        else:
            assert arch.v_d == pytest.approx(arch.spec.v_dom, abs=1e-6), name
        assert arch.v_i == pytest.approx(arch.spec.v_epi, abs=1e-6), name
        assert arch.v_gxe == pytest.approx(arch.spec.v_gxe, abs=1e-6), name


def test_directional_dominance_is_declared_only_with_a_citation():
    """A depression target without a source is a tuned parameter wearing a
    measurement's clothes. TraitSpec.validate refuses it; this pins that."""
    with pytest.raises(ValueError, match="tuned parameter"):
        T.TraitSpec("bogus", T.TraitKind.CONTINUOUS, h2=0.5, sd=1.0,
                    v_dom=None, depression_per_10F=1.0).validate()
    with pytest.raises(ValueError, match="never both"):
        T.TraitSpec("bogus", T.TraitKind.CONTINUOUS, h2=0.5, sd=1.0,
                    v_dom=0.05, depression_per_10F=1.0,
                    depression_source="x").validate()


def test_directional_dominance_preserves_curated_core_signs():
    """Only anonymous peripheral loci are re-signed. A core gene's dominance
    sign is a published claim (HERC2 +0.95, MC1R -0.80, GJB2 -1.00) and must
    survive the directional path unchanged."""
    from health_engine.loci import DOMINANCE_RATIO, LOCI
    for name, arch in T.ARCHITECTURE.items():
        if not arch.spec.is_directional:
            continue
        for k, i in enumerate(arch.idx):
            ratio = DOMINANCE_RATIO[i]
            if LOCI[i].is_core and ratio != 0.0:
                expected = np.sign(ratio * LOCI[i].weights[name])
                assert np.sign(arch.d[k]) == expected, f"{name}/{LOCI[i].symbol}"
            elif not LOCI[i].is_core and ratio != 0.0:
                assert arch.d[k] > 0.0, f"{name}/{LOCI[i].symbol}"


def test_liabilities_are_standard_normal_in_founders(rng):
    """If V_P = 1, a founder cohort's liability has mean ~0 and sd ~1."""
    d = V.founder_dosages(4000, rng)
    for name in ["height_cm", "neuroticism", "eye_color", "skin_tone"]:
        z = V._liabilities(T.ARCHITECTURE[name], d, rng)
        assert abs(z.mean()) < 0.08, f"{name}: mean {z.mean()}"
        assert abs(z.std() - 1.0) < 0.06, f"{name}: sd {z.std()}"


def test_categorical_prevalences_match_targets(rng):
    """Liability-threshold traits must reproduce their target prevalences."""
    d = V.founder_dosages(8000, rng)
    for name in T.CATEGORICAL_TRAITS:
        arch = T.ARCHITECTURE[name]
        z = V._liabilities(arch, d, rng)
        labels = [arch.spec.labels[i] for i in np.searchsorted(arch.thresholds, z)]
        for label, target in zip(arch.spec.labels, arch.spec.prevalences):
            observed = labels.count(label) / len(labels)
            assert abs(observed - target) < 0.025, \
                f"{name}/{label}: {observed:.3f} vs target {target:.3f}"


def test_major_effect_locus_makes_genotypic_value_non_normal():
    """
    Falconer's liability-threshold model assumes normality, which the CLT
    supplies only when many loci contribute comparably. eye_color -- where
    HERC2 alone carries >40% of V_A -- has a bimodal (platykurtic)
    genotypic value; neuroticism's 402 tiny loci give a textbook normal
    one. This is exactly why our thresholds are empirical quantiles rather
    than norm.ppf: assuming normality put hazel at 10.8% against a 20%
    target.
    """
    # Both are categorical, so both have thresholds to compare.
    eye = T.liability_nonnormality("eye_color", n=16_000)     # HERC2 dominates
    hand = T.liability_nonnormality("handedness", n=16_000)   # 120 flat loci

    assert abs(hand["genotypic_kurtosis"]) < 0.10, hand
    assert hand["max_threshold_shift"] < 0.03, hand

    assert eye["genotypic_kurtosis"] < -0.4, eye              # bimodal
    assert eye["max_threshold_shift"] > 0.15, eye


def test_gxe_makes_the_liability_heavy_tailed_even_when_genotype_is_normal():
    """
    GxE is modelled as (x.w) * e, a product of two independent normals,
    whose excess kurtosis is 6. So a trait can have a perfectly normal
    genotypic value and a leptokurtic liability. This is not an artifact:
    it is what "genotype modulates environmental sensitivity" implies
    distributionally.
    """
    neuro = T.liability_nonnormality("neuroticism", n=16_000)
    assert abs(neuro["genotypic_kurtosis"]) < 0.12, neuro
    assert neuro["liability_kurtosis"] > 0.20, neuro

    # eye_color has v_gxe = 0, so its liability stays platykurtic.
    eye = T.liability_nonnormality("eye_color", n=16_000)
    assert eye["liability_kurtosis"] < 0.0, eye


# ------------------------------------------------------- the benchmark

@pytest.mark.parametrize("trait", ["height_cm", "skin_tone", "neuroticism",
                                   "vision_acuity", "bp_set_point"])
def test_parent_offspring_slope_recovers_h2(rng, trait):
    """
    Roadmap Stage-0 benchmark: parent-offspring regression reproduces the
    target h^2 within +/-0.05. Nothing in reproduce() knows h^2 exists.
    """
    res = V.parent_offspring_regression(trait, n_families=3000, rng=rng)
    assert res.passes(tol=0.05), res


@pytest.mark.parametrize("trait", ["height_cm", "neuroticism", "skin_tone"])
def test_breeders_equation(rng, trait):
    """
    R = h^2 * S (Lush 1937), with the GxE channel off so the law is clean.
    The realised heritability is compared against `analytic_heritability`
    for the regime actually simulated, not against the catalogued h^2 --
    removing V_GxE from V_P genuinely raises the trait's heritability.
    """
    res = V.breeders_equation(trait, n=2000, top_fraction=0.20, rng=rng, gxe=0.0)
    assert res.passes(tol=0.06), res


def test_dominant_major_gene_makes_selection_response_undershoot(rng):
    """
    Fisher's infinitesimal model assumes many loci of small effect, which is
    what makes E[A|P] linear. eye_color breaks that: HERC2 is near-completely
    dominant, so heterozygotes are phenotypically indistinguishable from the
    favourable homozygote. Truncation selection scoops them up, but their
    breeding value is far lower than their phenotype implies, and their
    offspring segregate back. The response falls BELOW h^2 * S, by four-plus
    standard errors, and no amount of sampling removes it.

    Pinned as a property of the model, not tolerated as noise. Contrast
    skin_tone, whose large loci are additive and which overshoots instead.
    """
    major = V.breeders_equation("eye_color", n=2500, top_fraction=0.20,
                                rng=rng, gxe=0.0)
    flat = V.breeders_equation("neuroticism", n=2500, top_fraction=0.20,
                               rng=rng, gxe=0.0)

    major_dev = major.realised_h2 - major.h2
    flat_dev = flat.realised_h2 - flat.h2

    assert major_dev < 0, major_dev                       # undershoot
    assert abs(major_dev) > 3 * major.stderr, (major_dev, major.stderr)
    assert abs(flat_dev) < 0.05, flat_dev                 # flat trait obeys the law
    assert abs(major_dev) > abs(flat_dev) + 0.02, (major_dev, flat_dev)


def test_heritability_depends_on_the_environment(rng):
    """
    Same alleles, same trait, three environments, three heritabilities.

      e ~ N(0,1)  GxE is noise            -> h^2 = 0.40
      e = 0       no GxE channel          -> h^2 = 0.43
      e = 1       GxE is a function of g  -> h^2 = 0.59

    The claim "neuroticism is 40% genetic" is silently conditioning on a
    heterogeneous environment. This is the same reason polygenic scores do
    not transfer across ancestries or across environments, and it is why
    the roadmap forbids treating h^2 as a property of a genome.
    """
    h = V.heritability_depends_on_environment("neuroticism")
    assert h["varying_environment"] < h["no_gxe"] < h["uniform_environment"]
    assert h["uniform_environment"] - h["varying_environment"] > 0.15, h

    # And the breeder's equation tracks the environment-specific h^2.
    res = V.breeders_equation("neuroticism", n=2000, top_fraction=0.20,
                              rng=rng, gxe=1.0)
    assert res.h2 == pytest.approx(h["uniform_environment"], abs=1e-9)
    assert res.passes(tol=0.07), res


def test_random_gxe_does_not_inflate_selection_response(rng):
    """
    The negative control for the above, and a prediction we got wrong once.

    It is tempting to think GxE inflates the selection response, because
    truncation selection ought to co-select environmentally-sensitive
    genotypes. It does not: the environmental input is symmetric about
    zero, so a high liability arises as often from (sensitivity<0, e<0),
    which carries a negative breeding value. E[A|P] stays linear.
    """
    res = V.breeders_equation("neuroticism", n=2500, top_fraction=0.20,
                              rng=rng, gxe=None)
    assert res.h2 == pytest.approx(0.40, abs=1e-6)
    assert res.passes(tol=0.06), res


def test_full_sib_correlation_matches_theory(rng):
    """
    Full sibs share (1/2)V_A + (1/4)V_D, plus (1/4)V_AA from additive-by-
    additive epistasis. Sibs resemble each other slightly MORE than a
    parent-offspring pair, because they can inherit the same *genotype*
    (hence the same dominance deviation), not merely the same allele.
    SBX blending cannot produce that asymmetry.
    """
    arch = T.ARCHITECTURE["height_cm"]
    expected = 0.5 * arch.v_a + 0.25 * arch.v_d + 0.25 * arch.v_i
    observed = V.sibling_correlation("height_cm", 3000, rng)
    assert abs(observed - expected) < 0.045, f"{observed} vs {expected}"


def test_sbx_does_not_recover_h2(rng):
    """
    The negative control. If SBX could reproduce a target heritability,
    this whole rewrite was unnecessary. It cannot: its midparent-offspring
    slope sits near 1.0 regardless of h^2.
    """
    from health_engine.legacy import _sbx_children_liabilities
    arch = T.ARCHITECTURE["height_cm"]
    d = V.founder_dosages(2000, rng)
    zm = V._liabilities(arch, d[:1000], rng)
    zf = V._liabilities(arch, d[1000:], rng)
    kids = _sbx_children_liabilities(zm, zf, rng)
    slope = np.polyfit(0.5 * (zm + zf), kids, 1)[0]
    assert slope > 0.93, f"SBX slope {slope} -- expected ~1.0"
    assert abs(slope - arch.spec.h2) > 0.10


# ------------------------------------------------------- pleiotropy

def test_edar_is_pleiotropic_across_organ_systems():
    """Roadmap #7's headline: one gene, five traits, four organ systems."""
    w = T.traits_touched_by("EDAR")
    assert len(w) >= 5
    assert {"hair_thickness", "incisor_shovelling", "ear_protrusion",
            "chin_protrusion", "sweat_gland_density"} <= set(w)


def test_perturbing_one_core_gene_shifts_multiple_traits(rng):
    """
    Stage-1 benchmark, tested early: forcing EDAR from 0 to 2 alternate
    alleles must measurably move >= 3 unrelated phenotypes, holding
    everything else fixed.
    """
    from health_engine.loci import locus_index
    idx = locus_index("EDAR")
    npc = random_founder("probe", rng)

    npc.genome.haplotypes[:, idx] = 0
    npc.invalidate()
    before = npc.phenotype()

    npc.genome.haplotypes[:, idx] = 1
    npc.invalidate()
    after = npc.phenotype()

    moved = [t for t in T.traits_touched_by("EDAR")
             if abs(after[t] - before[t]) > 1e-9]
    assert len(moved) >= 3, moved
    # and it must NOT move a trait it has no weight on
    assert after["eye_color"] == before["eye_color"]


def test_personality_has_no_large_effect_core_gene():
    """
    Roadmap Section 5's first caveat, enforced structurally: no single
    locus may explain more than 2% of the additive variance of any Big
    Five trait. Candidate-gene behaviour genetics did not replicate
    (Border et al. 2019) and this model must not imply otherwise.
    """
    from health_engine.loci import ALT_FREQ
    for trait in T.OCEAN_TRAITS:
        arch = T.ARCHITECTURE[trait]
        p = arch.p
        alpha = arch.a + arch.d * (1 - 2 * p)
        per_locus_va = 2 * p * (1 - p) * alpha ** 2
        assert per_locus_va.max() / arch.v_a < 0.02, \
            f"{trait}: a single locus explains {per_locus_va.max()/arch.v_a:.1%} of V_A"


def test_pigmentation_does_have_a_large_effect_core_gene():
    """The contrast that makes the previous test meaningful."""
    arch = T.ARCHITECTURE["eye_color"]
    p = arch.p
    alpha = arch.a + arch.d * (1 - 2 * p)
    per_locus_va = 2 * p * (1 - p) * alpha ** 2
    assert per_locus_va.max() / arch.v_a > 0.40


# ------------------------------------------------------- determinism

def test_phenotype_is_deterministic(rng):
    """
    v0.2's `phenotype()` re-rolled its epigenetic silencing check on every
    call, so the same NPC could report brown eyes and then blue eyes.
    Randomness belongs at conception, not at read time.
    """
    npc = random_founder("stable", rng)
    first = npc.phenotype()
    for _ in range(20):
        assert npc.phenotype() == first


def test_expression_multiplier_changes_phenotype(rng):
    """The epigenome hook: silencing a locus must change what it expresses."""
    from health_engine.loci import locus_index
    npc = random_founder("silenced", rng)
    npc.genome.haplotypes[:, locus_index("HERC2")] = 1
    npc.invalidate()
    before = npc.liability("eye_color")

    npc.expression[locus_index("HERC2")] = 0.0
    npc.invalidate()
    after = npc.liability("eye_color")
    assert abs(after - before) > 0.5
