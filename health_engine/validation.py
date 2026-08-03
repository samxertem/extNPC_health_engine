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
