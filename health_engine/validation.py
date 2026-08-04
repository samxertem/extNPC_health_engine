"""
Validation harness: does the simulator obey quantitative genetics?
==================================================================

Roadmap item #32. The point of this module is that none of the laws below
are implemented anywhere in the simulator. They are *consequences*. If
`reproduce()` composes meiosis, allele effects, dominance and the
environmental draw correctly, these numbers come out right; if it does
not, they do not. Nothing here reads a target heritability and hands it
back.

Five checks
-----------
1. Hardy-Weinberg proportions among founders     (Hardy 1908; Weinberg 1908)
       P(AA) = p^2,  P(Aa) = 2pq,  P(aa) = q^2

2. Haldane's map function for linked loci        (Haldane 1919)
       r = (1 - exp(-2d)) / 2,   d in Morgans

3. Midparent-offspring regression slope          (Falconer & Mackay 1996)
       b_{O.MP} = V_A / V_P = h^2
   because Cov(O, MP) = (1/2) V_A and Var(MP) = (1/2) V_P.

4. Breeder's equation                            (Lush 1937)
       R = h^2 * S

5. Polygenic-score accuracy                      (Daetwyler et al. 2008)
       R^2 ~= h^2 * N / (N + M)
   with N the training size and M the number of independent causal loci.

Where the model deviates on purpose
-----------------------------------
* Check 3 is inflated by additive-by-additive epistasis. Cov(O, MP) picks
  up (1/4) V_AA in addition to (1/2) V_A, so the expected slope is
      h^2 + V_AA / (2 V_P)
  With the default v_epi = 0.02 that is a +0.01 bias. We compute and
  report the corrected expectation rather than pretending it is absent.

* Check 4 uses narrow-sense h^2 only. Dominance and epistasis contribute
  nothing to the selection response in the infinitesimal limit, and the
  same +V_AA term makes the realised response mildly exceed h^2 * S.

* Check 5's absolute values are NOT comparable to published PGS R^2. Our
  genome has ~500 causal loci; a real trait draws on ~50,000 effectively
  independent segments and its PGS is additionally capped by h^2_SNP,
  which is well below twin-study h^2 (height: h^2 ~ 0.8, h^2_SNP ~ 0.5,
  best PGS ~ 0.4). Only the *ordering* across traits carries meaning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.stats import chi2

from .genetic_map import haldane_recombination_fraction
from .genome import (Genome, allele_frequencies, cross, dosage_matrix,
                     meiosis, sample_founder_genome)
from .loci import ALT_FREQ, CM_POS, CHROM, HETEROZYGOSITY, N_LOCI, locus_index
from .traits import (ARCHITECTURE, TRAIT_TABLE, TraitArchitecture, TraitKind,
                     breeding_values, population_liabilities)


# ======================================================================
# Cohort construction
# ======================================================================

def founder_dosages(n: int, rng: np.random.Generator) -> np.ndarray:
    """(n, L) dosage matrix drawn under Hardy-Weinberg + linkage equilibrium."""
    haps = (rng.random((n, 2, N_LOCI)) < ALT_FREQ).astype(np.int8)
    return haps.sum(axis=1).astype(np.int8)


def founder_genomes(n: int, rng: np.random.Generator) -> List[Genome]:
    return [sample_founder_genome(rng) for _ in range(n)]


@dataclass
class Trio:
    mother: Genome
    father: Genome
    child: Genome


def random_mating_trios(n_families: int, rng: np.random.Generator,
                        mutation: bool = False) -> List[Trio]:
    """
    n_families unrelated random-mating couples, one offspring each.

    Mutation is off by default: at ~0.09 de novo events per gamete it
    perturbs nothing measurable, but leaving it off keeps the analytic
    expectations exact.
    """
    trios: List[Trio] = []
    for _ in range(n_families):
        m = sample_founder_genome(rng)
        f = sample_founder_genome(rng)
        c, _ = cross(m, f, rng, mutation=mutation)
        trios.append(Trio(m, f, c))
    return trios


def _liabilities(arch: TraitArchitecture, dosages: np.ndarray,
                 rng: np.random.Generator,
                 gxe: Optional[float] = None) -> np.ndarray:
    """
    `gxe` controls the environmental input that multiplies each
    individual's genetic environmental-sensitivity, and the three settings
    mean genuinely different things:

      None  -- every individual draws e ~ N(0,1). A heterogeneous world.
               GxE behaves as noise: it inflates V_P, lowers h^2, and
               contributes nothing to parent-offspring covariance.

      0.0   -- GxE switched off entirely. V_P shrinks, so the trait's
               heritability RISES above its catalogued value.

      c     -- every individual experiences the same environment e = c.
               The GxE term becomes c * s_g * (x . a_hat): a deterministic
               function of genotype. What was noise is now additive
               genetic variance, and h^2 rises further still.

    Keeping these separable is the point. Heritability is not a property
    of a genotype; it is a property of a population measured in an
    environment, and this parameter is the knob that proves it.
    """
    n = dosages.shape[0]
    if gxe is None:
        gxe_input = rng.normal(0, 1, n)
    else:
        gxe_input = np.full(n, float(gxe))
    return population_liabilities(arch, dosages,
                                  residual=rng.normal(0, 1, n),
                                  gxe_input=gxe_input)


def analytic_heritability(trait: str, gxe: Optional[float] = None) -> float:
    """
    The h^2 the population actually has under a given environmental regime.

    With a constant environment e = c, the sensitivity term c*s_g*(x.a_hat)
    is a linear function of genotype and merges into the breeding value:

        alpha'_j = alpha_j + c * gxe_w_j
        V_A'     = sum_j 2 p q alpha'^2
        V_P'     = V_A' + V_D + V_I + V_E

    With e ~ N(0,1) the term averages to zero and stays in V_P as noise.
    """
    arch = ARCHITECTURE[trait]
    twopq = 2.0 * arch.p * (1.0 - arch.p)
    alpha = arch.a + arch.d * (1.0 - 2.0 * arch.p)

    if gxe is None:
        v_a = arch.v_a
        v_p = arch.v_a + arch.v_d + arch.v_i + arch.v_gxe + arch.v_e
    else:
        alpha = alpha + float(gxe) * arch.gxe_w
        v_a = float(np.sum(twopq * alpha ** 2))
        v_p = v_a + arch.v_d + arch.v_i + arch.v_e
    return v_a / v_p


# ======================================================================
# 1. Hardy-Weinberg
# ======================================================================

@dataclass
class HWEResult:
    n_loci_tested: int
    rejection_rate: float          # fraction of loci with p < alpha
    alpha: float
    mean_p_value: float

    def passes(self, tol: float = 0.03) -> bool:
        """Under the null we expect exactly `alpha` of loci to be rejected."""
        return abs(self.rejection_rate - self.alpha) <= tol


def hardy_weinberg_test(dosages: np.ndarray, alpha: float = 0.05) -> HWEResult:
    """
    Per-locus chi-square goodness of fit, 1 degree of freedom (three
    genotype classes minus one for the estimated allele frequency, minus
    one for the total).

    A correct founder sampler produces a rejection rate at alpha, not
    zero -- rejecting *nothing* would mean the genotypes were too regular
    to be random.
    """
    n = dosages.shape[0]
    n2 = (dosages == 2).sum(axis=0)
    n1 = (dosages == 1).sum(axis=0)
    n0 = (dosages == 0).sum(axis=0)

    p_hat = (2 * n2 + n1) / (2.0 * n)
    q_hat = 1.0 - p_hat

    exp2 = n * p_hat ** 2
    exp1 = n * 2.0 * p_hat * q_hat
    exp0 = n * q_hat ** 2

    keep = (exp0 >= 5) & (exp1 >= 5) & (exp2 >= 5)   # chi-square validity
    with np.errstate(divide="ignore", invalid="ignore"):
        stat = ((n2 - exp2) ** 2 / exp2
                + (n1 - exp1) ** 2 / exp1
                + (n0 - exp0) ** 2 / exp0)
    stat = stat[keep]
    pvals = chi2.sf(stat, df=1)

    return HWEResult(
        n_loci_tested=int(keep.sum()),
        rejection_rate=float((pvals < alpha).mean()),
        alpha=alpha,
        mean_p_value=float(pvals.mean()),
    )


# ======================================================================
# 2. Recombination / linkage
# ======================================================================

def empirical_recombination_fraction(locus_a: int, locus_b: int,
                                     n_meioses: int,
                                     rng: np.random.Generator) -> float:
    """
    Build a fully heterozygous "test-cross" individual whose maternal
    haplotype is all-0 and paternal haplotype is all-1, run n_meioses,
    and count gametes in which the two loci came from different parental
    haplotypes. That fraction is the recombination fraction r.

    Compare against `haldane_recombination_fraction(|cM_a - cM_b|)`.
    Loci on different chromosomes must give r = 0.5 exactly.
    """
    haps = np.zeros((2, N_LOCI), dtype=np.int8)
    haps[1, :] = 1
    g = Genome(haps)

    recombinant = 0
    for _ in range(n_meioses):
        gam = meiosis(g, rng, sex="average")
        if gam[locus_a] != gam[locus_b]:
            recombinant += 1
    return recombinant / n_meioses


def expected_recombination_fraction(locus_a: int, locus_b: int) -> float:
    if CHROM[locus_a] != CHROM[locus_b]:
        return 0.5
    return haldane_recombination_fraction(abs(CM_POS[locus_a] - CM_POS[locus_b]))


def ld_r2(dosages: np.ndarray, locus_a: int, locus_b: int) -> float:
    """
    Squared correlation of alternate-allele dosages -- the standard
    population-genetic measure of linkage disequilibrium.

    Founders are drawn independently, so r^2 ~ 0 at generation 0 even for
    adjacent loci. LD is not baked in; it *accumulates* under drift,
    assortative mating and selection in a finite population, and decays at
    rate (1 - r) per generation. That is the correct causal order.
    """
    a = dosages[:, locus_a].astype(np.float64)
    b = dosages[:, locus_b].astype(np.float64)
    if a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1] ** 2)


# ======================================================================
# 3. Parent-offspring regression  ->  h^2
# ======================================================================

@dataclass
class HeritabilityResult:
    trait: str
    target_h2: float
    expected_slope: float          # h^2 + V_AA/(2 V_P), the epistasis-corrected target
    observed_slope: float
    stderr: float
    n_families: int

    @property
    def error(self) -> float:
        return self.observed_slope - self.expected_slope

    def passes(self, tol: float = 0.05) -> bool:
        """
        The roadmap's +/-0.05 benchmark, but never tighter than the
        estimate's own two-sigma interval. At n_families = 400 the
        standard error of the slope is itself ~0.06, so a bare +/-0.05
        rule would report FAIL on a perfectly correct simulator roughly
        half the time. Declaring failure inside the noise floor is not
        rigour, it is a broken instrument.
        """
        return abs(self.error) <= max(tol, 2.0 * self.stderr)


def parent_offspring_regression(trait: str, n_families: int,
                                rng: np.random.Generator) -> HeritabilityResult:
    """
    Regress offspring liability on midparent liability.

        Cov(O, MP) = (1/2) V_A + (1/4) V_AA
        Var(MP)    = (1/2) V_P            (parents unrelated)
        slope      = h^2 + V_AA / (2 V_P)

    The environmental residual and the GxE input are drawn independently
    for parents and offspring, so neither contributes to the covariance --
    which is precisely why the slope isolates the *additive genetic*
    fraction and nothing else. Shared family environment would break this,
    and real twin/adoption designs spend all their effort on that problem.
    """
    arch = ARCHITECTURE[trait]
    trios = random_mating_trios(n_families, rng)

    mums = dosage_matrix([t.mother for t in trios])
    dads = dosage_matrix([t.father for t in trios])
    kids = dosage_matrix([t.child for t in trios])

    z_m = _liabilities(arch, mums, rng)
    z_f = _liabilities(arch, dads, rng)
    z_c = _liabilities(arch, kids, rng)

    mp = 0.5 * (z_m + z_f)
    slope, _ = np.polyfit(mp, z_c, 1)

    # OLS standard error of the slope
    resid = z_c - (slope * mp + (z_c.mean() - slope * mp.mean()))
    dof = n_families - 2
    se = float(np.sqrt((resid @ resid) / dof / ((mp - mp.mean()) @ (mp - mp.mean()))))

    v_p = arch.v_a + arch.v_d + arch.v_i + arch.v_gxe + arch.v_e
    expected = arch.v_a / v_p + arch.v_i / (2.0 * v_p)

    return HeritabilityResult(
        trait=trait, target_h2=arch.spec.h2, expected_slope=expected,
        observed_slope=float(slope), stderr=se, n_families=n_families,
    )


def sibling_correlation(trait: str, n_families: int,
                        rng: np.random.Generator) -> float:
    """
    Full-sib correlation. Expected (1/2)h^2 + (1/4)(V_D/V_P) with no
    shared environment. Sibs resemble each other slightly more than a
    parent-offspring pair does, because they share dominance deviations
    (they can inherit the same genotype, not merely the same allele) --
    an effect SBX blending could never produce.
    """
    arch = ARCHITECTURE[trait]
    z1, z2 = [], []
    for _ in range(n_families):
        m = sample_founder_genome(rng)
        f = sample_founder_genome(rng)
        c1, _ = cross(m, f, rng, mutation=False)
        c2, _ = cross(m, f, rng, mutation=False)
        z1.append(c1.dosage)
        z2.append(c2.dosage)
    a = _liabilities(arch, np.stack(z1), rng)
    b = _liabilities(arch, np.stack(z2), rng)
    return float(np.corrcoef(a, b)[0, 1])


# ======================================================================
# 4. Breeder's equation
# ======================================================================

@dataclass
class SelectionResult:
    trait: str
    h2: float
    selection_differential: float   # S
    predicted_response: float       # h^2 * S
    observed_response: float        # R
    n: int
    stderr: float = 0.0             # standard error of realised_h2

    @property
    def realised_h2(self) -> float:
        return self.observed_response / self.selection_differential

    def passes(self, tol: float = 0.06) -> bool:
        """As with HeritabilityResult: never tighter than two standard errors."""
        return abs(self.realised_h2 - self.h2) <= max(tol, 2.0 * self.stderr)


def breeders_equation(trait: str, n: int, top_fraction: float,
                      rng: np.random.Generator,
                      gxe: Optional[float] = 0.0) -> SelectionResult:
    """
    Lush 1937.  R = h^2 * S.

      S = mean(selected parents) - mean(base population)
      R = mean(their offspring)  - mean(base population)

    Only the *additive* half of a parent's superiority is transmitted: a
    parent that is tall because it is heterozygous at many loci passes on
    alleles, not genotypes, and its offspring reshuffle them. Selection
    therefore recovers h^2 of the differential, not all of it. This is the
    single most consequential fact in applied genetics, and the original
    prototype's SBX blending got it wrong by construction -- SBX children
    sit *between* their parents, so SBX reports a realised heritability
    near 1.0 (see legacy.sbx_vs_meiosis_report).

    `gxe=0.0` by default: the GxE channel is switched off so the law is
    tested clean. The comparison target `h2` is then recomputed for the
    trait we are ACTUALLY simulating (V_P shrinks when GxE is removed, so
    heritability rises) rather than read off the catalogue. Comparing a
    GxE-free simulation against the catalogued h^2 would be comparing
    against a different trait.

    A tempting but WRONG prediction, recorded because we checked it: that
    leaving GxE on (gxe=None) would inflate the response, since truncation
    selection would co-select environmentally-sensitive genotypes. It does
    not. The environmental input e is symmetric about zero, so a high
    liability is equally likely to come from (sensitivity > 0, e > 0) as
    from (sensitivity < 0, e < 0) -- and the second carries a NEGATIVE
    breeding value. The two cancel, E[A|P] stays linear, and R = h^2 S
    holds. Measured across seeds at n=2500, the inflation is zero.

    What is true is sharper. Pass a CONSTANT gxe=c and every individual
    experiences the same environment; the sensitivity term becomes
    c * s_g * (x . a_hat), a deterministic function of genotype, and folds
    into the breeding value. Heritability then rises, sometimes steeply.
    Same genotypes, same trait, different h^2. See
    `heritability_depends_on_environment`.

    Where the law genuinely bends: MAJOR-GENE TRAITS. Fisher's
    infinitesimal model assumes many loci of small effect, which is what
    makes E[A|P] linear. Traits with a large-effect locus violate it, and
    the deviation does not have a fixed sign -- DOMINANCE decides it:

      skin_tone   overshoots by ~+0.03. Its big loci (SLC24A5, SLC45A2)
                  are largely additive, so the selected tail is enriched
                  for true homozygotes whose offspring cannot regress as
                  far as the model expects.

      eye_color   UNDERSHOOTS by ~-0.07, four times further. HERC2 is
                  near-completely dominant, so a heterozygote is
                  phenotypically indistinguishable from the favourable
                  homozygote. Truncation selection therefore scoops up
                  heterozygotes whose breeding value is much lower than
                  their phenotype implies, and their offspring segregate
                  back toward the mean.

    Neither is a bug, and neither shrinks with sample size (both exceed
    four standard errors at n=2500). This is exactly why animal breeders
    treat identified major genes separately from the polygenic background
    rather than folding them into a single h^2.
    """
    arch = ARCHITECTURE[trait]
    parents = founder_genomes(n, rng)
    dose = dosage_matrix(parents)
    z = _liabilities(arch, dose, rng, gxe=gxe)
    base_mean = float(z.mean())

    k = max(4, int(n * top_fraction))
    chosen = np.argsort(z)[-k:]
    S = float(z[chosen].mean() - base_mean)

    # Random mating *within* the selected group.
    kids = []
    for _ in range(n):
        i, j = rng.choice(chosen, size=2, replace=False)
        c, _ = cross(parents[i], parents[j], rng, mutation=False)
        kids.append(c.dosage)
    z_kids = _liabilities(arch, np.stack(kids), rng, gxe=gxe)
    R = float(z_kids.mean() - base_mean)

    # R is a sample mean, so its standard error is sd/sqrt(n); the realised
    # heritability R/S inherits that, divided by S.
    se = float(z_kids.std(ddof=1) / np.sqrt(len(kids)) / abs(S))

    h2 = analytic_heritability(trait, gxe=gxe)
    return SelectionResult(trait=trait, h2=h2,
                           selection_differential=S,
                           predicted_response=h2 * S,
                           observed_response=R, n=n, stderr=se)


def heritability_depends_on_environment(trait: str) -> Dict[str, float]:
    """
    The same population, the same alleles, three environmental regimes:

        varying    e ~ N(0,1)   GxE sits in V_P as noise      -> lowest h^2
        absent     e = 0        no GxE channel at all         -> middling
        uniform    e = 1        GxE is a function of genotype -> highest h^2

    Heritability is a property of a population in an environment, not of a
    genome. Any claim of the form "trait X is 40% genetic" is silently
    conditioning on a population and an environment. This function is the
    smallest honest demonstration of that, and it is why the roadmap's
    caveat about PGS non-portability across ancestries is not pedantry.
    """
    return {
        "varying_environment": analytic_heritability(trait, gxe=None),
        "no_gxe": analytic_heritability(trait, gxe=0.0),
        "uniform_environment": analytic_heritability(trait, gxe=1.0),
    }


# ======================================================================
# 5. Drift
# ======================================================================

@dataclass
class DriftResult:
    n_individuals: int
    observed_var_delta_p: float
    expected_var_delta_p: float     # mean of p q / (2N)
    n_replicates: int

    @property
    def ratio(self) -> float:
        return self.observed_var_delta_p / self.expected_var_delta_p

    def passes(self, tol: float = 0.20) -> bool:
        return abs(self.ratio - 1.0) <= tol


def allele_frequency_drift(n_individuals: int, n_replicates: int,
                           rng: np.random.Generator) -> DriftResult:
    """
    Neutral Wright-Fisher expectation for one generation:

        E[Delta p] = 0        Var[Delta p] = p q / (2N)

    We do not simulate a Wright-Fisher binomial directly -- that would be
    testing numpy. We build N founders, mate them at random through the
    real meiosis machinery, and measure how far the offspring allele
    frequencies wandered. Passing means our meiosis is unbiased and our
    effective population size equals our census size (no hidden
    selection, no gamete-sampling bug).
    """
    obs, exp = [], []
    for _ in range(n_replicates):
        pop = founder_genomes(n_individuals, rng)
        p0 = allele_frequencies(pop)
        kids = []
        for _ in range(n_individuals):
            i, j = rng.choice(n_individuals, size=2, replace=False)
            c, _ = cross(pop[i], pop[j], rng, mutation=False)
            kids.append(c)
        p1 = allele_frequencies(kids)
        dp = p1 - p0
        segregating = (p0 > 0.02) & (p0 < 0.98)
        obs.append(np.mean(dp[segregating] ** 2))
        exp.append(np.mean(p0[segregating] * (1 - p0[segregating]) / (2.0 * n_individuals)))

    return DriftResult(n_individuals=n_individuals,
                       observed_var_delta_p=float(np.mean(obs)),
                       expected_var_delta_p=float(np.mean(exp)),
                       n_replicates=n_replicates)


# ======================================================================
# 6. Polygenic scores
# ======================================================================

@dataclass
class PGSResult:
    trait: str
    h2: float
    n_train: int
    n_causal_loci: int
    observed_r2: float
    daetwyler_r2: float             # h^2 * N / (N + M)
    literature_r2: Optional[float]  # published PGS R^2, for context only


def daetwyler_expected_r2(h2: float, n_train: int, m_loci: int) -> float:
    """Daetwyler, Villanueva & Woolliams 2008: R^2 = h^2 N / (N + M/h^2)."""
    return h2 * n_train / (n_train + m_loci / h2)


def simulated_gwas_pgs_r2(trait: str, n_train: int, n_test: int,
                          rng: np.random.Generator) -> PGSResult:
    """
    Run a miniature GWAS: estimate each locus's marginal effect by simple
    regression in a training cohort, then score an independent test
    cohort and measure out-of-sample R^2.

    This reproduces the *mechanism* behind the roadmap's item #10 -- why
    height's polygenic score works and neuroticism's barely does. It is
    not the number of loci alone, nor the heritability alone, but the
    ratio of training sample size to the number of independent loci
    carrying the signal. Neuroticism spreads h^2 = 0.40 across 402 loci
    with no core gene; skin tone concentrates h^2 = 0.85 into 32, seven of
    them large-effect. At the same N the second is far easier to learn.

    CAVEAT (roadmap Section 5). Absolute values here are optimistic by a
    wide margin, because every causal locus is directly genotyped and
    there are only ~500 of them. Real PGS must tag causal variants through
    LD and is capped by h^2_SNP, not h^2. Treat only the ordering as
    meaningful, and never treat any of it as ancestry-portable.
    """
    arch = ARCHITECTURE[trait]

    train = founder_dosages(n_train, rng).astype(np.float64)
    y_train = _liabilities(arch, train.astype(np.int8), rng)

    # Marginal OLS per locus: beta_j = cov(g_j, y) / var(g_j)
    gc = train - train.mean(axis=0)
    yc = y_train - y_train.mean()
    var_g = (gc ** 2).mean(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        beta = (gc * yc[:, None]).mean(axis=0) / var_g
    beta[~np.isfinite(beta)] = 0.0

    test = founder_dosages(n_test, rng)
    y_test = _liabilities(arch, test, rng)
    score = test.astype(np.float64) @ beta

    r = np.corrcoef(score, y_test)[0, 1]
    v_p = arch.v_a + arch.v_d + arch.v_i + arch.v_gxe + arch.v_e
    h2 = arch.v_a / v_p

    return PGSResult(
        trait=trait, h2=h2, n_train=n_train, n_causal_loci=arch.n_loci,
        observed_r2=float(r ** 2),
        daetwyler_r2=daetwyler_expected_r2(h2, n_train, arch.n_loci),
        literature_r2=arch.spec.target_pgs_r2,
    )


# ======================================================================
# Report
# ======================================================================

def full_report(rng: np.random.Generator,
                traits: Optional[List[str]] = None,
                n_families: int = 2500,
                fast: bool = False) -> str:
    """
    Run every check and format the results. Used by the demo script.

    `fast` shrinks sample sizes for a quick smoke run. It does NOT relax
    the physics -- the pass criterion widens only to two standard errors,
    which is what a smaller sample honestly buys you. The pytest suite is
    the rigorous version and uses fixed tolerances at large n.
    """
    traits = traits or ["height_cm", "skin_tone", "neuroticism", "vision_acuity"]
    if fast:
        n_families = 1000

    out: List[str] = []
    add = out.append

    add("=" * 78)
    add("VALIDATION HARNESS  (roadmap #32)")
    add("=" * 78)

    # 1. HWE
    hwe = hardy_weinberg_test(founder_dosages(2000, rng))
    add("\n[1] Hardy-Weinberg proportions among founders")
    add(f"    loci tested          : {hwe.n_loci_tested}")
    add(f"    rejection rate @0.05 : {hwe.rejection_rate:.3f}   (expect ~0.050)")
    add(f"    mean p-value         : {hwe.mean_p_value:.3f}   (expect ~0.500)")
    add(f"    -> {'PASS' if hwe.passes() else 'FAIL'}")

    # 2. Linkage
    add("\n[2] Haldane recombination fraction (linkage from the cM map)")
    add(f"    {'locus pair':<28}{'cM apart':>10}{'expected r':>12}{'observed r':>12}")
    pairs = [("HERC2", "OCA2"), ("RUNX2", "SUPT3H"), ("TCHH", "LCE3E"),
             ("FTO", "MC1R"), ("HERC2", "FTO")]
    n_mei = 3000 if fast else 12000
    for sa, sb in pairs:
        ia, ib = locus_index(sa), locus_index(sb)
        d = abs(CM_POS[ia] - CM_POS[ib]) if CHROM[ia] == CHROM[ib] else float("nan")
        exp = expected_recombination_fraction(ia, ib)
        obs = empirical_recombination_fraction(ia, ib, n_mei, rng)
        label = f"{sa} x {sb}"
        dtxt = f"{d:.1f}" if np.isfinite(d) else "diff chr"
        add(f"    {label:<28}{dtxt:>10}{exp:>12.4f}{obs:>12.4f}")

    # 3. h^2
    add("\n[3] Midparent-offspring regression slope  (= h^2 + V_AA/2V_P)")
    add("    PASS = |observed - expected| within max(0.05, 2 standard errors).")
    add(f"    {'trait':<32}{'target h2':>11}{'expected':>10}{'observed':>10}{'+/- se':>9}  ")
    for t in traits:
        r = parent_offspring_regression(t, n_families, rng)
        flag = "PASS" if r.passes() else "FAIL"
        add(f"    {t:<32}{r.target_h2:>11.2f}{r.expected_slope:>10.3f}"
            f"{r.observed_slope:>10.3f}{r.stderr:>9.3f}  {flag}")

    # 4. Breeder's equation
    add("\n[4] Breeder's equation   R = h^2 * S     (GxE channel off, so h2 rises)")
    add(f"    {'trait':<28}{'h2':>7}{'S':>9}{'pred R':>9}{'obs R':>9}"
        f"{'real. h2':>10}{'+/- se':>9}")
    for t in traits:
        s = breeders_equation(t, 600 if fast else 2000, 0.20, rng, gxe=0.0)
        flag = "PASS" if s.passes() else "FAIL"
        add(f"    {t:<28}{s.h2:>7.3f}{s.selection_differential:>9.3f}"
            f"{s.predicted_response:>9.3f}{s.observed_response:>9.3f}"
            f"{s.realised_h2:>10.3f}{s.stderr:>9.3f}  {flag}")

    # 4b. h^2 is not a property of the genome
    add("\n[4b] Heritability is a property of a POPULATION IN AN ENVIRONMENT")
    add(f"    {'trait':<32}{'e ~ N(0,1)':>13}{'e = 0':>10}{'e = 1':>10}")
    add(f"    {'':<32}{'(GxE = noise)':>13}{'(no GxE)':>10}{'(uniform)':>10}")
    for t in ["neuroticism", "insulin_sensitivity", "aerobic_capacity", "height_cm"]:
        h = heritability_depends_on_environment(t)
        add(f"    {t:<32}{h['varying_environment']:>13.3f}"
            f"{h['no_gxe']:>10.3f}{h['uniform_environment']:>10.3f}")
    add("    Same alleles, same trait. 'Neuroticism is 40% genetic' silently")
    add("    conditions on a heterogeneous environment. Make everyone's world")
    add("    identical and the same variance reappears as additive genetics.")

    # 5. Drift
    d = allele_frequency_drift(60, 15 if fast else 40, rng)
    add("\n[5] Neutral drift   Var(dp) = pq / 2N")
    add(f"    N={d.n_individuals}, replicates={d.n_replicates}")
    add(f"    observed Var(dp) : {d.observed_var_delta_p:.6f}")
    add(f"    expected pq/2N   : {d.expected_var_delta_p:.6f}")
    add(f"    ratio            : {d.ratio:.3f}   -> {'PASS' if d.passes() else 'FAIL'}")

    # 6. PGS
    add("\n[6] Polygenic-score accuracy   (Daetwyler 2008: R^2 = h2 N / (N + M/h2))")
    add("    Out-of-sample R^2 as the training size N grows. The ceiling is h^2;")
    add("    how fast you approach it is set by N/M, not by h^2. This is why")
    add("    neuroticism (h2=0.40 spread over 402 tiny loci) needs an order of")
    add("    magnitude more data than skin tone (h2=0.85 in 32 loci, 7 large).")
    add("    ABSOLUTE VALUES ARE NOT COMPARABLE TO PUBLISHED PGS -- see docstring.")
    sizes = [250, 1000] if fast else [250, 1000, 4000]
    header = "".join(f"{'N=' + str(s):>10}" for s in sizes)
    add(f"    {'trait':<22}{'h2':>6}{'loci':>6}{header}   lit. R2")
    for t in ["skin_tone", "eye_color", "height_cm", "chronotype", "neuroticism"]:
        cells, h2, m, lit = [], 0.0, 0, None
        for s in sizes:
            p = simulated_gwas_pgs_r2(t, s, 1500, rng)
            h2, m, lit = p.h2, p.n_causal_loci, p.literature_r2
            cells.append(f"{p.observed_r2:>10.3f}")
        littxt = f"{lit:.2f}" if lit is not None else "--"
        add(f"    {t:<22}{h2:>6.2f}{m:>6}{''.join(cells)}   {littxt}")
    add("\n    Observed falls below the Daetwyler prediction because the score is")
    add("    fitted on all 500 loci, not just the causal ones. That gap is the")
    add("    cost of not knowing in advance which variants matter -- the same")
    add("    cost real GWAS pays, and the reason PGS need clumping/thresholding.")

    # 7. Imprinting (roadmap #4)
    add("\n[7] Genomic imprinting   reciprocal-heterozygote gap = 2*s*a")
    add("    Two individuals, SAME genotype at an imprinted locus, differing only")
    add("    in which parent supplied the alternate allele. Mendel predicts they")
    add("    are identical. Under monoallelic expression the gap is closed-form,")
    add("    and the dominance term cancels out of it exactly.")
    add(f"    {'trait':<18}{'locus':>8}{'s':>6}{'a':>9}{'observed':>11}{'2*s*a':>11}")
    imp_pass = True
    for t in ("height_cm", "adiposity"):
        r = imprinting_reciprocal_cross(trait=t, n=400 if fast else 1500, rng=rng)
        imp_pass = imp_pass and r.passes()
        add(f"    {t:<18}{r.symbol:>8}{r.strength:>6.2f}{r.additive_effect:>9.4f}"
            f"{r.observed_gap:>11.5f}{r.expected_gap:>11.5f}")
    add(f"    population mean shift: {r.mean_shift:+.5f}  (predicted 0 at d=0, "
        f"d={r.dominance:.2f})")
    add(f"    -> {'PASS' if imp_pass else 'FAIL'}")

    # 8. Canalization (roadmap #14b)
    add("\n[8] Canalization   Var(z) = k^2 V_gen + V_env  (Waddington 1942)")
    add("    Development is buffered, so genetic variation stays cryptic until")
    add("    stress overwhelms the buffer. One cohort of genotypes read twice --")
    add("    neutral vs stressed -- with the stressed variance PREDICTED from the")
    add("    baseline decomposition. The mean must not move: only variance is")
    add("    released, and only the genetic part of it.")
    add(f"    {'trait':<20}{'k':>6}{'V_gen':>8}{'observed':>11}{'predicted':>11}"
        f"{'h2 base':>9}{'h2 stress':>11}")
    can_pass = True
    for t in ("height_cm", "neuroticism"):
        c = canalization_release(trait=t, stress=2.0,
                                 n=1200 if fast else 4000, rng=rng)
        can_pass = can_pass and c.passes()
        add(f"    {t:<20}{c.k:>6.2f}{c.v_genetic:>8.3f}"
            f"{c.observed_var_stressed:>11.4f}{c.predicted_var_stressed:>11.4f}"
            f"{c.genetic_fraction_baseline:>9.3f}{c.genetic_fraction_stressed:>11.3f}")
    add(f"    population mean shift: {c.mean_shift:+.5f}  (predicted 0)")
    add(f"    -> {'PASS' if can_pass else 'FAIL'}")
    add("\n    NOTE: the buffering CAPACITY is an uncalibrated engineering")
    add("    constant -- no human decanalization coefficient exists. What is")
    add("    tested is Waddington's qualitative claim plus internal k^2")
    add("    consistency, not the magnitude. See canalize.py.")

    # 9a. Malecot kinship (roadmap #31)
    add("\n[9a] Malecot kinship over the full pedigree")
    add("    Pure combinatorics -- no sampling. Any mismatch is a coding error.")
    kin = malecot_kinship_check()
    kin_pass = all(abs(o - e) < 1e-12 for o, e in kin.values())
    for label, (obs, exp) in kin.items():
        add(f"    {label:<32}{obs:>10.6f}  expect {exp:.6f}")
    add(f"    -> {'PASS' if kin_pass else 'FAIL'}")

    # 9b. Inbreeding depression (roadmap #31)
    add("\n[9b] Inbreeding depression   ln S(F) = ln S_0 - B F   (Morton 1956)")
    add("    B = lethal equivalents per gamete, recovered by regressing observed")
    add("    survival on PEDIGREE F over depth-matched pedigrees. Viability comes")
    add("    from the actual load genotypes; nothing in that path computes B.")
    ib = inbreeding_depression(n_per_level=1200 if fast else 4000, rng=rng)
    add(f"    {'F':>9}{'mean w':>10}{'ln S':>10}{'closed form':>13}{'realised F':>12}")
    for F, w, ls, ex, rf in zip(ib.levels, ib.mean_viability, ib.log_survival,
                                ib.exact_log_survival, ib.realised_F):
        add(f"    {F:>9.4f}{w:>10.4f}{ls:>10.4f}{ex:>13.4f}{rf:>12.4f}")
    add(f"    observed B  : {ib.observed_B:.4f} +/- {ib.stderr:.4f}"
        f"   (closed form {ib.expected_B:.4f}, R^2 {ib.r_squared:.4f})")
    add(f"    first-cousin excess mortality: {ib.first_cousin_excess * 100:.2f}%")
    add(f"    excess het from one-way mutation: observed {ib.mutation_het_offset:.5f}"
        f", predicted {ib.predicted_het_offset:.5f}")
    add(f"    -> {'PASS' if ib.passes() else 'FAIL'}")
    add("\n    B runs ~1% ABOVE the closed form on purpose-built pedigrees, and")
    add("    the cause is identified: a deleterious allele that arose in a")
    add("    GRANDPARENT can be made homozygous by the inbreeding loop, while")
    add("    the closed form is computed from founding allele frequencies.")
    add("    Rerunning with mutation=False shrinks the gap ~3x. Calibrated to")
    add("    1.4 lethal equivalents (Charlesworth & Willis 2009 give 1-2 for")
    add("    human survival to adulthood) -- unlike #14b, this one has real")
    add("    human magnitudes behind it. See inbreeding.py.")

    # 10. Copy-number dosage response (roadmap #12)
    add("\n[10] CNV gene dosage   shift = (copies/2 - 1) * sum_j E[val_j]")
    add("    One cohort of genomes read at three copy numbers -- same genotypes,")
    add("    same environmental draws, only dosage moves. Two predictions: the")
    add("    closed-form magnitude, and the MIRROR SYMMETRY between a deletion")
    add("    and its reciprocal duplication (Jacquemont et al. 2011).")
    add(f"    {'trait':<16}{'copies':>8}{'observed':>12}{'catalogue':>12}{'sample':>12}")
    cnv_pass = True
    for t in ("eye_color", "skin_tone"):
        d = cnv_dosage_response(trait=t, n=800 if fast else 3000, rng=rng)
        cnv_pass = cnv_pass and d.passes()
        for c, o, p, s in zip(d.copies, d.observed_shift,
                              d.predicted_shift, d.sample_shift):
            add(f"    {t if c == 1 else '':<16}{c:>8}{o:>12.6f}{p:>12.6f}{s:>12.6f}")
        add(f"    {'':<16}{'mirror |del+dup|':>8} = {d.mirror_asymmetry:.2e}")
    add(f"    -> {'PASS' if cnv_pass else 'FAIL'}")
    add("\n    The 'catalogue' column predicts from the catalogue's allele")
    add("    frequencies and differs by O(1/sqrt(n)); the 'sample' column uses")
    add("    the cohort's realised frequencies and matches to ~1e-16. The gap")
    add("    between the two columns IS the finite-sample error, and separating")
    add("    them keeps a statistical agreement from being read as an exact one.")
    add("    SCOPE: this scales a locus's genotypic DEVIATION, not its absolute")
    add("    gene product, so magnitude and mirror symmetry are exact while the")
    add("    direction of a loss-of-function phenotype is not modelled. See the")
    add("    OCA2 worked example in cnv.py.")

    # 11. Developmental trajectory (roadmap #13)
    add("\n[11] Developmental trajectory   identity at the calibration age")
    add("    The riskiest item on the roadmap: an age factor inside the")
    add("    genotype->phenotype path would change realised variance and")
    add("    silently decalibrate every heritability while the reported")
    add("    targets stayed put. It is applied to the OUTPUT of phenotype()")
    add("    instead, so the calibrated path never sees an age -- and the")
    add("    identity below is therefore EXACT rather than approximate.")
    dv = developmental_identity(n=60 if fast else 200, rng=rng)
    add(f"    max |phenotype_at_age(20) - phenotype()|  : {dv.max_identity_error:.1e}"
        f"   (must be exactly 0)")
    add(f"    max |growth factor - 1| across plateaus   : {dv.plateau_error:.1e}"
        f"   (must be exactly 0)")
    add(f"    stature landmarks, rms vs Tanner          : {dv.landmark_rms:.5f}"
        f"   ({dv.landmark_rms * 171:.2f} cm of adult stature)")
    add(f"    peak height velocity  female {dv.phv_female:.2f}"
        f"   male {dv.phv_male:.2f}   gap {dv.phv_sex_gap:.2f} yr")
    add(f"    growth monotone                           : {dv.monotone_growth}")
    add(f"    -> {'PASS' if dv.passes() else 'FAIL'}")
    add("\n    The sex difference in pubertal timing emerges from separately")
    add("    fitted curves rather than being imposed, and its DIRECTION is")
    add("    right. Its size is not: Tanner's longitudinal figures give ~2.0")
    add("    years and this gives 1.3, most likely because the fit targets")
    add("    median cross-sectional stature, which smears the spurt across")
    add("    individuals of differing pubertal tempo. Not tuned away.")

    return "\n".join(out)


# ======================================================================
# 6. X-linked epidemiology (roadmap #2)
# ======================================================================
# The hemizygosity signature: an X-linked recessive condition appears at
# frequency ~q in males (one X, allele expressed directly) but ~q^2 in
# females (two X's, both must carry it). This is not coded anywhere -- it
# falls out of `sexchrom.sample_founder_sex_chromosomes` sampling one X for
# males and two for females under Hardy-Weinberg. Red-green colour blindness
# (q ~ 0.08) is the textbook case: ~8% of males, <1% of females (Deeb 2005).

@dataclass
class SexLinkageResult:
    trait: str
    risk_allele_freq: float        # q
    male_prevalence: float         # observed, ~ q
    female_prevalence: float       # observed, ~ q^2 (+ rare manifesting carriers)
    male_expected: float           # q
    female_expected: float         # q^2
    sex_ratio_male: float          # observed male fraction, ~ 0.5

    def passes(self, tol_male: float = 0.01, tol_female: float = 0.005,
               tol_ratio: float = 0.02) -> bool:
        return (abs(self.male_prevalence - self.male_expected) <= tol_male
                and (self.female_expected - tol_female
                     <= self.female_prevalence
                     <= self.female_expected + tol_female)
                and abs(self.sex_ratio_male - 0.5) <= tol_ratio)


def x_linked_epidemiology(n: int, rng: np.random.Generator,
                          trait: str = "color_vision") -> SexLinkageResult:
    """
    Sample `n` founders (sex drawn 50:50) and measure the prevalence of an
    X-linked recessive condition in each sex against the q / q^2 expectation.

    The female prevalence sits marginally ABOVE q^2 because of manifesting
    heterozygotes -- carriers whose X-inactivation is skewed far enough
    toward the mutant X to express the trait (a real, rare phenomenon,
    Lyon 1961). This is a feature, not slack in the test; `passes` allows for
    it with a one-sided tolerance above q^2.
    """
    from .sexchrom import (X_LOCI, X_LOCUS_INDEX,
                           sample_founder_sex_chromosomes, x_linked_prevalence)

    locus = X_LOCI[X_LOCUS_INDEX[trait]]
    q = locus.risk_freq

    kar = [sample_founder_sex_chromosomes(rng, "male" if rng.random() < 0.5
                                          else "female") for _ in range(n)]
    mp, fp = x_linked_prevalence(kar, trait)
    male_fraction = float(np.mean([k.sex == "male" for k in kar]))

    return SexLinkageResult(
        trait=trait, risk_allele_freq=q,
        male_prevalence=mp, female_prevalence=fp,
        male_expected=q, female_expected=q * q,
        sex_ratio_male=male_fraction,
    )


# ======================================================================
# 7. Mitochondrial transmission (roadmap #3)
# ======================================================================
# Two closed-form checks on maternal mtDNA inheritance. (i) Strict maternal
# transmission: a child's mtDNA is its mother's, never its father's, so a
# father's heteroplasmy has zero influence. (ii) The bottleneck: offspring
# heteroplasmy has mean = the mother's but variance h(1-h)/N_e, where N_e is
# the effective number of segregating units (mito.MITO_BOTTLENECK_N). Neither
# is coded as a target -- both fall out of `MitoGenome.transmit` resampling
# through a binomial bottleneck. (Cree et al. 2008; Wai et al. 2008.)

@dataclass
class MitoBottleneckResult:
    mother_heteroplasmy: float
    n_offspring: int
    offspring_mean: float          # ~ mother's
    offspring_var: float           # observed
    predicted_var: float           # h(1-h)/N_e
    bottleneck_n: int

    def passes(self, tol_mean: float = 0.01, var_ratio_tol: float = 0.15) -> bool:
        mean_ok = abs(self.offspring_mean - self.mother_heteroplasmy) <= tol_mean
        # variance within +/- var_ratio_tol relative to the closed form
        var_ok = (abs(self.offspring_var - self.predicted_var)
                  <= var_ratio_tol * self.predicted_var)
        return mean_ok and var_ok


def mito_bottleneck(mother_heteroplasmy: float, n: int,
                    rng: np.random.Generator) -> MitoBottleneckResult:
    """Sample `n` offspring from one carrier mother and compare their
    heteroplasmy distribution to the bottleneck prediction."""
    from .mito import MITO_BOTTLENECK_N, MitoGenome

    mother = MitoGenome("H", mother_heteroplasmy)
    kids = np.array([mother.transmit(rng).heteroplasmy for _ in range(n)])
    h = mother_heteroplasmy
    return MitoBottleneckResult(
        mother_heteroplasmy=h,
        n_offspring=n,
        offspring_mean=float(kids.mean()),
        offspring_var=float(kids.var()),
        predicted_var=h * (1.0 - h) / MITO_BOTTLENECK_N,
        bottleneck_n=MITO_BOTTLENECK_N,
    )


def mito_is_strictly_maternal(n: int, rng: np.random.Generator) -> bool:
    """
    Cross carrier mothers with non-carrier fathers and vice versa; assert the
    child's heteroplasmy tracks the MOTHER only. Returns True iff paternal
    heteroplasmy never leaks into offspring.
    """
    from .mito import MitoGenome

    ok = True
    for _ in range(n):
        # carrier mother (h=0.6), clean father -> child near 0.6
        child_a = MitoGenome("H", 0.6).transmit(rng)
        # clean mother, "carrier father" -> father cannot transmit, child = 0
        child_b = MitoGenome("J", 0.0).transmit(rng)
        if child_b.heteroplasmy != 0.0:
            ok = False
        if not (0.2 <= child_a.heteroplasmy <= 1.0):
            ok = False
    return ok


# ======================================================================
# Genomic imprinting (roadmap #4)
# ======================================================================

@dataclass
class ImprintingResult:
    """
    The reciprocal-heterozygote law.

    Take two individuals who are heterozygous at an imprinted locus and
    identical everywhere else, differing ONLY in which parent supplied the
    alternate allele. Mendel says their genotypic values are identical.
    Under monoallelic expression they are not, and the gap is closed-form.

    With silencing strength s, additive effect a and dominance deviation d
    at that locus, the genotypic contribution is

        alt from the EXPRESSED parent:   (1-s)*d + s*(+a)
        alt from the SILENCED parent:    (1-s)*d + s*(-a)
        ------------------------------------------------------
        difference                    =  2 * s * a

    The dominance term cancels exactly, so the prediction is 2sa whatever
    d happens to be -- and it is a genuine prediction: nothing in the trait
    layer computes it. `expected_gap` is that formula; `observed_gap` is
    measured by building the two individuals and reading their liabilities.
    """
    trait: str
    symbol: str
    strength: float
    additive_effect: float         # a at this locus, in liability units
    observed_gap: float            # measured, in liability units
    expected_gap: float            # 2 * s * a
    mean_shift: float              # population mean with imprinting - without
    dominance: float               # d at this locus

    def passes(self, tol: float = 1e-9, mean_tol: float = 0.02) -> bool:
        gap_ok = abs(self.observed_gap - self.expected_gap) <= tol
        # With d = 0 the population mean is provably unchanged (see below);
        # with d != 0 it shifts by -s*2pq*d and this check does not apply.
        mean_ok = (abs(self.mean_shift) <= mean_tol) if self.dominance == 0.0 else True
        return gap_ok and mean_ok


def imprinting_reciprocal_cross(trait: str = "height_cm",
                                symbol: str = "IGF2",
                                n: int = 2000,
                                rng: Optional[np.random.Generator] = None
                                ) -> ImprintingResult:
    """
    Roadmap #4's benchmark, as a law rather than an anecdote.

    Builds a reciprocal heterozygote pair at `symbol` -- same genotype,
    opposite parent of origin -- and compares the measured liability gap to
    the closed form 2*s*a. Also measures the population-mean shift caused by
    imprinting, which is provably zero when the locus is purely additive:

        E[val_biallelic]  = a(p-q) + 2pq*d
        E[val_monoallelic] = p*(+a) + q*(-a) = a(p-q)

    so the difference is -s*2pq*d, which vanishes at d = 0. IGF2 is coded
    with dominance_ratio 0.0, so this predicts NO mean shift -- imprinting
    moves variance and individual values, not the population average.
    """
    from .genome import Genome
    from .imprint import IMPRINTED, MATERNAL, PATERNAL
    from .loci import LOCUS_BY_SYMBOL
    from .npc import NPC, random_founder
    from .traits import ARCHITECTURE, liability

    rng = np.random.default_rng(20260803) if rng is None else rng
    arch = ARCHITECTURE[trait]
    locus = LOCUS_BY_SYMBOL[symbol]
    spec = IMPRINTED[symbol]
    i = locus.index
    if i not in set(arch.idx.tolist()):
        raise ValueError(f"{symbol} carries no weight on {trait}")
    j = arch.idx.tolist().index(i)
    a_eff = float(arch.a[j])
    d_eff = float(arch.d[j])

    # --- the reciprocal pair --------------------------------------------
    base = random_founder("base", rng)
    expressed, silenced = spec.expressed_from, 1 - spec.expressed_from

    h_expr = base.genome.haplotypes.copy()
    h_expr[expressed, i] = 1          # alternate allele from the ACTIVE parent
    h_expr[silenced, i] = 0
    h_sil = base.genome.haplotypes.copy()
    h_sil[expressed, i] = 0
    h_sil[silenced, i] = 1            # alternate allele from the SILENCED parent

    lo = NPC(name="alt_from_silenced", genome=Genome(h_sil), deviates=base.deviates)
    hi = NPC(name="alt_from_expressed", genome=Genome(h_expr), deviates=base.deviates)
    assert lo.genome.dosage[i] == hi.genome.dosage[i] == 1, "must be reciprocal heterozygotes"

    observed = hi.liability(trait) - lo.liability(trait)

    # --- population mean shift -------------------------------------------
    pop = [random_founder(f"p{k}", rng) for k in range(n)]
    with_imp = np.array([liability(arch, p.genome.dosage, p.deviates,
                                   p.expression, p.imprint_state()) for p in pop])
    without = np.array([liability(arch, p.genome.dosage, p.deviates,
                                  p.expression, None) for p in pop])

    return ImprintingResult(
        trait=trait,
        symbol=symbol,
        strength=spec.strength,
        additive_effect=a_eff,
        observed_gap=float(observed),
        expected_gap=2.0 * spec.strength * a_eff,
        mean_shift=float(with_imp.mean() - without.mean()),
        dominance=d_eff,
    )


# ======================================================================
# Canalization / cryptic variation (roadmap #14b)
# ======================================================================

@dataclass
class CanalizationResult:
    """
    Waddington's claim, made quantitative.

    Below the buffering threshold, genetic variation is held cryptic. Above
    it the buffer fails and that variation becomes visible. Because the
    liability is LINEAR in the expressivity factor k,

        z(k) = k*(G + I) + GxE + E

    the genetic part can be recovered exactly from two evaluations of the
    same individuals:  G + I = (z(k) - z(1)) / (k - 1).  That makes the
    prediction non-circular: measure V_gen and V_env at baseline, then
    predict the stressed variance as

        Var(z(k)) = k^2 * V_gen + V_env

    and compare to what the stressed cohort actually shows. Nothing in the
    trait layer computes that expression.
    """
    trait: str
    stress: float
    k: float
    v_genetic: float               # V(G + I), recovered
    v_environmental: float         # everything else
    observed_var_stressed: float
    predicted_var_stressed: float  # k^2 V_gen + V_env
    genetic_fraction_baseline: float
    genetic_fraction_stressed: float
    predicted_fraction_stressed: float   # closed form from canalize.py
    mean_shift: float

    def passes(self, var_tol: float = 0.02, mean_tol: float = 0.02) -> bool:
        var_ok = (abs(self.observed_var_stressed - self.predicted_var_stressed)
                  <= var_tol * self.predicted_var_stressed)
        frac_ok = (abs(self.genetic_fraction_stressed
                       - self.predicted_fraction_stressed) <= 0.02)
        # buffering must RELEASE variance, not merely change it
        released = self.observed_var_stressed > 1.0
        return var_ok and frac_ok and released and abs(self.mean_shift) <= mean_tol


def canalization_release(trait: str = "height_cm",
                         stress: float = 2.0,
                         n: int = 4000,
                         rng: Optional[np.random.Generator] = None
                         ) -> CanalizationResult:
    """
    Take one cohort of genotypes and read it twice -- once as though it had
    developed in a neutral environment, once under `stress`. Identical
    genomes, identical environmental draws: the ONLY difference is whether
    the developmental buffer held.
    """
    from .canalize import canalization_factor, expected_heritability
    from .npc import random_founder
    from .traits import ARCHITECTURE, liability

    rng = np.random.default_rng(20260814) if rng is None else rng
    arch = ARCHITECTURE[trait]
    k = canalization_factor(stress, trait)
    if k <= 1.0:
        raise ValueError(f"stress={stress} does not exceed the buffering threshold")

    pop = [random_founder(f"c{i}", rng) for i in range(n)]
    z0 = np.array([liability(arch, p.genome.dosage, p.deviates, p.expression,
                             p.imprint_state(), 1.0) for p in pop])
    zk = np.array([liability(arch, p.genome.dosage, p.deviates, p.expression,
                             p.imprint_state(), k) for p in pop])

    genetic = (zk - z0) / (k - 1.0)          # exactly G + I
    v_gen = float(genetic.var())
    v_tot0 = float(z0.var())
    v_env = v_tot0 - v_gen

    h2_0 = v_gen / v_tot0
    return CanalizationResult(
        trait=trait,
        stress=stress,
        k=k,
        v_genetic=v_gen,
        v_environmental=v_env,
        observed_var_stressed=float(zk.var()),
        predicted_var_stressed=k * k * v_gen + v_env,
        genetic_fraction_baseline=h2_0,
        genetic_fraction_stressed=(k * k * v_gen) / float(zk.var()),
        predicted_fraction_stressed=expected_heritability(h2_0, k),
        mean_shift=float(zk.mean() - z0.mean()),
    )


# ======================================================================
# Inbreeding depression -- lethal equivalents (roadmap #31)
# ======================================================================
# Morton, Crow & Muller 1956 wrote survival against inbreeding as
#
#       ln S(F) = ln S_0 - B F
#
# and read B, the number of LETHAL EQUIVALENTS PER GAMETE, off the slope of
# a real consanguinity study. We run the same regression on simulated
# pedigrees. B is never used to make an individual: viability comes out of
# the actual genotypes at the load loci, so recovering B from the slope is a
# genuine measurement of an emergent quantity, not a readback.
#
# The pedigree template is IDENTICAL at every inbreeding level -- eight
# founder slots, four grandparents, two parents, one child, three meioses on
# every ancestral path. Only which founders are SHARED changes. That matters:
# `transmit_load` mutates, mutation is one-directional, and a deeper pedigree
# would therefore carry more new deleterious alleles. With depth held fixed,
# mutation load is a constant across levels and cannot leak into the slope.

@dataclass
class InbreedingResult:
    """The Morton/Crow/Muller regression, run on simulated pedigrees."""
    levels: List[float]                  # pedigree F at each level
    mean_viability: List[float]          # observed E[w] at each level
    log_survival: List[float]            # ln(E[w] / E[w at F=0])
    observed_B: float                    # regression slope, negated
    expected_B: float                    # closed form from the load spectrum
    stderr: float                        # se of the slope
    r_squared: float
    exact_log_survival: List[float]      # per-locus exact, no log-linearisation
    realised_F: List[float]              # excess homozygosity vs the outbred cohort
    mutation_het_offset: float           # observed excess het in the OUTBRED cohort
    predicted_het_offset: float          # 2*K*u*generations / sum(2pq)
    first_cousin_excess: float           # 1 - S(1/16)/S(0), observed
    n_per_level: int

    def passes(self, tol: float = 0.06) -> bool:
        """
        B recovered within a relative tolerance of the closed form, with
        survival falling monotonically in F.

        Deliberately NOT a pure standard-error test, and the reason is a
        real result rather than an excuse. The measured B sits about 0.8%
        ABOVE the spectrum's closed form, consistently and in an identifiable
        direction: `transmit_load` mutates, so a deleterious allele that
        arose in a grandparent can be made homozygous by the inbreeding loop,
        while Morton's B is computed from FOUNDING allele frequencies and
        knows nothing about it. Rerunning with `mutation=False` shrinks the
        gap by a factor of ~3, which is how that was pinned down. The bias is
        genuine and does not shrink with n, so a 3-standard-error test would
        reject a correct model as soon as the sample got large enough.
        """
        rel = abs(self.observed_B - self.expected_B) / self.expected_B
        monotone = all(b <= a + 1e-9 for a, b in zip(self.log_survival,
                                                     self.log_survival[1:]))
        return rel <= tol and monotone


# Pedigree templates. Every one produces a child three meioses deep; the
# label says which founder couples are shared between the two sides.
_INBREEDING_TEMPLATES: List[Tuple[str, float]] = [
    ("outbred", 0.0),
    ("half_first_cousin", 1.0 / 32.0),
    ("first_cousin", 1.0 / 16.0),
    ("double_first_cousin", 1.0 / 8.0),
    ("full_sib", 1.0 / 4.0),
]


def _inbred_child(level: str, rng: np.random.Generator, spectrum,
                  mutation: bool = True):
    """
    One child at the named pedigree structure, built entirely out of the load
    layer's own founder sampler and transmission code.

    Layout, with X = one cross:

        P = X(f0, f1)   Q = X(f2, f3)   ->  M = X(P, Q)
        R = X(?, ?)     S = X(?, ?)     ->  N = X(R, S)   ->  child = X(M, N)

    and the level decides how R and S relate to P and Q:

        outbred             R, S from four fresh founders     f(M,N) = 0
        half_first_cousin   R is a HALF sib of P              f(M,N) = 1/32
        first_cousin        R is a FULL sib of P              f(M,N) = 1/16
        double_first_cousin R full sib of P, S full sib of Q  f(M,N) = 1/8
        full_sib            R = P and S = Q, so M, N are sibs f(M,N) = 1/4
    """
    from .inbreeding import sample_founder_load, transmit_load

    f = [sample_founder_load(rng, spectrum) for _ in range(8)]

    def X(a, b):
        return transmit_load(a, b, rng, spectrum, mutation=mutation)

    P, Q = X(f[0], f[1]), X(f[2], f[3])
    if level == "full_sib":
        R, S = P, Q
    elif level == "double_first_cousin":
        R, S = X(f[0], f[1]), X(f[2], f[3])
    elif level == "first_cousin":
        R, S = X(f[0], f[1]), X(f[6], f[7])
    elif level == "half_first_cousin":
        R, S = X(f[0], f[5]), X(f[6], f[7])
    else:
        R, S = X(f[4], f[5]), X(f[6], f[7])
    return X(X(P, Q), X(R, S))


def inbreeding_depression(n_per_level: int = 4000,
                          rng: Optional[np.random.Generator] = None,
                          spectrum=None,
                          mutation: bool = True) -> InbreedingResult:
    """
    Regress ln(observed survival) on pedigree F and recover B.

    `ln E[w]` rather than `E[ln w]`: Morton's S is an observed survival
    PROPORTION, so the mean is taken on the viability scale and logged
    afterwards. The two differ by a Jensen term, and using the wrong one
    biases B upward.

    `mutation=False` switches off new mutation in the pedigree crosses. It
    is not a realism setting -- it isolates the small upward bias in the
    measured B caused by recent-ancestor mutations being made homozygous by
    the inbreeding loop, which the founding-frequency closed form omits.
    """
    from .inbreeding import SPECTRUM

    rng = np.random.default_rng(20260901) if rng is None else rng
    sp = SPECTRUM if spectrum is None else spectrum

    levels: List[float] = []
    mean_w: List[float] = []
    exact: List[float] = []
    realised: List[float] = []
    se_log: List[float] = []

    # Expected heterozygosity at the load loci, for the realised-F estimator.
    h_expected = float(np.mean(2.0 * sp.p * sp.q))

    for label, F in _INBREEDING_TEMPLATES:
        kids = [_inbred_child(label, rng, sp, mutation) for _ in range(n_per_level)]
        w = np.array([k.viability(sp) for k in kids])
        het = np.array([float(np.mean(k.dosage == 1)) for k in kids])
        levels.append(F)
        mean_w.append(float(w.mean()))
        exact.append(sp.exact_log_survival(F) - sp.exact_log_survival(0.0))
        realised.append(1.0 - float(het.mean()) / h_expected)
        # Delta-method se of ln(mean w). Taken from the ACTUAL spread of
        # viabilities at this level, not from the 5-point regression
        # residuals: viability under inbreeding has a long left tail (a
        # homozygous lethal takes an individual to ~0), so the residual-based
        # se badly understates how noisy the high-F levels are.
        se_log.append(float(w.std(ddof=1) / np.sqrt(w.size) / w.mean()))

    log_s = [float(np.log(m / mean_w[0])) for m in mean_w]

    # Realised F is measured against the CONTEMPORANEOUS OUTBRED COHORT, not
    # against the founding allele frequencies -- which is what a real study
    # does, and here it is also necessary. `transmit_load` mutates one way
    # only, so after three generations every cohort carries ~2*K*u*3 extra
    # deleterious alleles, essentially all heterozygous. That inflates
    # heterozygosity by a constant amount at EVERY level (the templates are
    # depth-matched), so it shifts the intercept and not the slope. The
    # offset is predicted in closed form and reported next to the observed
    # one, rather than being quietly subtracted.
    n_generations = 3
    predicted_offset = (2.0 * sp.n_loci * sp.mutation_rate * n_generations
                        / float(np.sum(2.0 * sp.p * sp.q)))
    raw_offset = -realised[0]
    realised = [r - realised[0] for r in realised]

    # Fit on ln(mean w) directly rather than on the differenced ln S: the
    # slope is identical, but every point then carries its own independent
    # sampling error instead of sharing the F=0 level's error, which is what
    # makes the propagated standard error below correct.
    x = np.array(levels)
    y = np.log(np.array(mean_w))
    slope, intercept = np.polyfit(x, y, 1)
    fit = slope * x + intercept
    ss_res = float(np.sum((y - fit) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))

    sxx = float(np.sum((x - x.mean()) ** 2))
    var_slope = float(np.sum(((x - x.mean()) ** 2) * np.array(se_log) ** 2)) / sxx ** 2
    se = float(np.sqrt(var_slope))

    i_fc = levels.index(1.0 / 16.0)
    return InbreedingResult(
        levels=levels,
        mean_viability=mean_w,
        log_survival=log_s,
        observed_B=float(-slope),
        expected_B=sp.lethal_equivalents,
        stderr=se,
        r_squared=1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0,
        exact_log_survival=exact,
        realised_F=realised,
        mutation_het_offset=raw_offset,
        predicted_het_offset=predicted_offset,
        first_cousin_excess=1.0 - mean_w[i_fc] / mean_w[0],
        n_per_level=n_per_level,
    )


def malecot_kinship_check() -> Dict[str, Tuple[float, float]]:
    """
    The pedigree recursion against textbook coefficients. Pure combinatorics
    -- no sampling, no RNG -- so any mismatch is a coding error, not noise.
    Returns {relationship: (observed, expected)}.
    """
    from .inbreeding import Pedigree

    ped = Pedigree()
    for founder in ("A", "B", "C", "D"):
        ped.add(founder)
    ped.add("E", "A", "B")          # full sibs E, F
    ped.add("F", "A", "B")
    ped.add("G", "E", "C")          # G and H are first cousins
    ped.add("H", "F", "D")
    ped.add("I", "G", "H")          # first-cousin offspring
    ped.add("J", "E", "F")          # full-sib offspring
    ped.add("K", "A", "E")          # parent-offspring mating

    return {
        "kinship full sibs":          (ped.kinship("E", "F"), 0.25),
        "kinship parent-offspring":   (ped.kinship("A", "E"), 0.25),
        "kinship unrelated founders": (ped.kinship("A", "C"), 0.0),
        "self-kinship, outbred":      (ped.kinship("E", "E"), 0.5),
        "relationship first cousins": (ped.relationship("G", "H"), 0.125),
        "F, first-cousin child":      (ped.inbreeding("I"), 0.0625),
        "F, full-sib child":          (ped.inbreeding("J"), 0.25),
        "F, parent-offspring child":  (ped.inbreeding("K"), 0.25),
        "self-kinship, inbred":       (ped.kinship("J", "J"), 0.625),
        "F, founder":                 (ped.inbreeding("A"), 0.0),
    }


# ======================================================================
# Copy-number dosage response (roadmap #12)
# ======================================================================
# A CNV changes gene dosage, and the trait layer scales a locus's
# contribution by copy_number/2. The population-mean consequence is then
# available in closed form, because `genotypic_value` subtracts
#
#       mean_g = sum_j [ a_j (p_j - q_j) + 2 p_j q_j d_j ]
#
# so scaling locus j by m shifts the mean by exactly (m - 1) times the j-th
# term. Nothing in the trait layer evaluates that expression.
#
# The second prediction is the interesting one and comes for free: a
# deletion (c=1) and its reciprocal duplication (c=3) give m-1 of -1/2 and
# +1/2, so the shifts must be EQUAL IN MAGNITUDE AND OPPOSITE IN SIGN. That
# mirror-image signature is what Jacquemont et al. 2011 used to argue BMI at
# 16p11.2 is dosage-driven, and it is the sharpest available test that a
# dosage model is behaving like one.

@dataclass
class DosageResult:
    """One trait's response to copy number at one CNV region."""
    trait: str
    region: str
    copies: List[int]
    observed_shift: List[float]        # measured mean liability shift
    predicted_shift: List[float]       # closed form from CATALOGUE frequencies
    sample_shift: List[float]          # same form at the cohort's REALISED freqs
    catalogue_stderr: float            # analytic se of the catalogue prediction
    mirror_asymmetry: float            # |shift(1) + shift(3)|, exactly 0 in theory
    n: int

    def passes(self, n_sigma: float = 4.0, mirror_tol: float = 1e-9) -> bool:
        """
        Three claims of very different strength, checked separately because
        conflating them would let a statistical agreement pass as an exact
        one.

        1. Against the SAMPLE closed form -- the same algebra evaluated at
           the cohort's own realised frequencies -- agreement must be exact
           to floating point. This is the claim that tests the mechanism.

        2. Mirror symmetry between deletion and duplication, also exact,
           because the multiplier is linear in copy number.

        3. Against the CATALOGUE closed form the agreement is only
           statistical, and the tolerance is DERIVED rather than chosen. The
           prediction uses catalogue frequencies p, the cohort realises
           p-hat, and the shift depends on p through a(p-q) + 2pq d. Note
           that (p - q) is a small difference of two large numbers -- at
           p = 0.42 it is -0.16 -- so a 2% error in p-hat becomes an ~11%
           error in the prediction. `catalogue_stderr` propagates that
           properly, and the test is against it rather than against a flat
           percentage that would silently depend on the trait.
        """
        for obs, samp in zip(self.observed_shift, self.sample_shift):
            if abs(obs - samp) > 1e-9:
                return False
        for obs, pred in zip(self.observed_shift, self.predicted_shift):
            if abs(obs - pred) > n_sigma * self.catalogue_stderr + 1e-9:
                return False
        return self.mirror_asymmetry <= mirror_tol


def cnv_dosage_response(trait: str = "eye_color",
                        region: str = "15q11-q13",
                        n: int = 4000,
                        rng: Optional[np.random.Generator] = None
                        ) -> DosageResult:
    """
    Take one cohort of genomes and read it at three copy numbers.

    Identical genotypes and identical environmental draws at every copy
    number, so the only thing that moves is gene dosage -- the same
    read-it-twice design `canalization_release` uses, for the same reason:
    it removes sampling noise from the comparison entirely and leaves the
    mechanism as the only possible explanation.
    """
    from .cnv import CopyNumber, DELETED, DUPLICATED, NORMAL
    from .cnv import predicted_mean_shift, region_index
    from .npc import random_founder
    from .traits import ARCHITECTURE, liability

    rng = np.random.default_rng(20261001) if rng is None else rng
    arch = ARCHITECTURE[trait]
    i = region_index(region)

    pop = [random_founder(f"d{k}", rng) for k in range(n)]
    imp = [p.imprint_state() for p in pop]

    def mean_liability(state: int) -> float:
        z = []
        for p, m in zip(pop, imp):
            cn = CopyNumber.normal()
            cn.haplotypes[0, i] = state
            expr = p.expression * cn.dosage_multiplier()
            z.append(liability(arch, p.genome.dosage, p.deviates, expr, m, 1.0))
        return float(np.mean(z))

    # The same closed form evaluated at the cohort's REALISED genotypes
    # instead of the catalogue's frequencies: the mean, over these actual
    # individuals, of the region's loci contributions. Removing the sampling
    # difference should leave agreement exact to floating point.
    from .cnv import REGIONS
    hits = [k for k, j in enumerate(arch.idx)
            if j in set(REGIONS[region].catalogue_indices)]
    if hits:
        vals = []
        for p, m in zip(pop, imp):
            g = p.genome.dosage[arch.idx[hits]]
            v = np.where(g == 2, arch.a[hits],
                         np.where(g == 1, arch.d[hits], -arch.a[hits]))
            vals.append(float(np.sum(v * p.expression[arch.idx[hits]])))
        sample_contribution = float(np.mean(vals))
    else:
        sample_contribution = 0.0

    # Analytic standard error of the CATALOGUE prediction, propagated from
    # sampling error in the cohort's allele frequencies:
    #
    #   d/dp [ a(p-q) + 2pq d ] = 2a + 2d(1 - 2p),   sd(p-hat) = sqrt(pq/2n)
    #
    # Summed as absolute values rather than in quadrature because the loci in
    # a CNV region are physically adjacent -- OCA2 and HERC2 are 0.1 Mb apart
    # and in strong LD -- so their frequency errors are correlated and an
    # independence assumption would understate the spread.
    se = 0.0
    for k in hits:
        p = float(arch.p[k])
        se += (abs(2.0 * arch.a[k] + 2.0 * arch.d[k] * (1.0 - 2.0 * p))
               * float(np.sqrt(p * (1.0 - p) / (2.0 * n))))
    se *= 0.5                                    # |copies/2 - 1| at c = 1 or 3

    base = mean_liability(NORMAL)
    observed, predicted, sample, copies = [], [], [], []
    for state, c in ((DELETED, 1), (NORMAL, 2), (DUPLICATED, 3)):
        copies.append(c)
        observed.append(mean_liability(state) - base)
        predicted.append(predicted_mean_shift(trait, region, c))
        sample.append((c / 2.0 - 1.0) * sample_contribution)

    return DosageResult(
        trait=trait,
        region=region,
        copies=copies,
        observed_shift=observed,
        predicted_shift=predicted,
        sample_shift=sample,
        catalogue_stderr=se,
        mirror_asymmetry=abs(observed[0] + observed[2]),
        n=n,
    )


# ======================================================================
# Developmental trajectory (roadmap #13)
# ======================================================================
# The roadmap item with the highest capacity to break the engine quietly.
# An age factor on the genotype -> phenotype path changes realised variance
# and therefore every calibrated heritability, while `TraitArchitecture`
# goes on reporting the target it no longer achieves. Nothing raises; the
# numbers just stop meaning what they say.
#
# So the schedule is applied to the OUTPUT of `phenotype()` rather than
# inside it, and this harness checks the two consequences:
#
#   1. IDENTITY. `phenotype_at_age(REFERENCE_AGE)` reproduces `phenotype()`
#      exactly, for every trait and both sexes. Exact, not close.
#   2. NO DECALIBRATION. Midparent-offspring regression on the mature
#      phenotype is bit-identical with the module imported and not, because
#      the calibrated path never sees an age at all.
#
# It also checks the growth curve against Tanner's landmarks, which is the
# part that could be wrong without being dangerous.

@dataclass
class DevelopmentResult:
    """The identity property, plus the growth curve against real landmarks."""
    max_identity_error: float          # over every trait x both sexes
    plateau_error: float               # max |factor - 1| across each plateau
    stature_landmarks: Dict[str, Tuple[float, float]]   # age -> (obs, target)
    landmark_rms: float
    phv_female: float
    phv_male: float
    phv_sex_gap: float
    monotone_growth: bool

    def passes(self) -> bool:
        return (self.max_identity_error == 0.0
                and self.plateau_error == 0.0
                and self.landmark_rms < 0.01
                and self.monotone_growth
                and self.phv_female < self.phv_male)


# Median fraction of adult stature, the anchors the curve was fitted to.
_STATURE_LANDMARKS: Dict[str, Dict[float, float]] = {
    "female": {2: 0.500, 5: 0.630, 8: 0.730, 10: 0.800,
               12: 0.900, 14: 0.980, 16: 0.995, 18: 0.999},
    "male": {2: 0.490, 5: 0.610, 8: 0.710, 10: 0.770,
             12: 0.840, 14: 0.930, 16: 0.980, 18: 0.998},
}


def developmental_identity(n: int = 200,
                           rng: Optional[np.random.Generator] = None
                           ) -> DevelopmentResult:
    """
    Assert that the age schedule is exactly identity where the engine is
    calibrated, and check the growth curve against Tanner's landmarks.
    """
    from .development import (GROWTH, REFERENCE_AGE, growth_factor,
                              peak_height_velocity_age, stature_fraction)
    from .npc import random_founder

    rng = np.random.default_rng(20261101) if rng is None else rng

    # 1. identity at the reference age, over real NPCs of both sexes
    worst = 0.0
    for i in range(n):
        npc = random_founder(f"dev{i}", rng)
        mature = npc.phenotype()
        at_ref = npc.phenotype_at_age(REFERENCE_AGE)
        for trait, value in mature.items():
            if isinstance(value, str):
                if value != at_ref[trait]:
                    worst = float("inf")
                continue
            worst = max(worst, abs(float(value) - float(at_ref[trait])))

    # 2. the plateaus themselves must be exactly 1.0, not merely close
    plateau_err = 0.0
    for trait, profile in GROWTH.items():
        span = np.linspace(profile.plateau_start, profile.plateau_end, 41)
        for sex in ("female", "male"):
            for a in span:
                plateau_err = max(plateau_err,
                                  abs(growth_factor(trait, float(a), sex) - 1.0))

    # 3. the growth curve against the landmarks it was fitted to
    landmarks: Dict[str, Tuple[float, float]] = {}
    errs = []
    for sex, table in _STATURE_LANDMARKS.items():
        for age, target in table.items():
            obs = stature_fraction(age, sex)
            landmarks[f"{sex} age {age:g}"] = (obs, target)
            errs.append(obs - target)

    # 4. growth must be monotone -- children do not shrink
    mono = True
    for sex in ("female", "male"):
        f = [stature_fraction(a, sex) for a in np.linspace(0, REFERENCE_AGE, 400)]
        mono = mono and all(b >= a - 1e-12 for a, b in zip(f, f[1:]))

    pf = peak_height_velocity_age("female")
    pm = peak_height_velocity_age("male")
    return DevelopmentResult(
        max_identity_error=worst,
        plateau_error=plateau_err,
        stature_landmarks=landmarks,
        landmark_rms=float(np.sqrt(np.mean(np.array(errs) ** 2))),
        phv_female=pf,
        phv_male=pm,
        phv_sex_gap=pm - pf,
        monotone_growth=mono,
    )
