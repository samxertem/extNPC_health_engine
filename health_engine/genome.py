"""
Diploid genome, meiosis with crossover, mutation, founder sampling.
==================================================================

Roadmap items #1 (chromosomes + recombination), #12 (realistic mutation
rate + paternal-age effect), #29 (sampled founders under Hardy-Weinberg).

Representation
--------------
A genome is a (2, L) int8 array of allele identities (0 = reference,
1 = alternate), where L = number of loci in the catalogue. Row 0 is the
maternally-inherited haplotype, row 1 the paternal one. Loci are ordered
by (chromosome, physical position), so a chromosome is a contiguous slice.

`dosage` = row0 + row1 in {0, 1, 2} = count of alternate alleles. This is
the quantity the genotype->phenotype map consumes.

What replaced what
------------------
The v0.2 prototype had:
    continuous_genes: Dict[str, float]        # blended by SBX
    discrete_genes:   Dict[str, (allele, allele)]

Both are gone. Continuous traits are no longer *blended between parents*
-- SBX interpolates phenotypes, which is not how inheritance works and
which structurally cannot reproduce a target heritability. Instead, both
continuous and discrete traits are now *computed* from transmitted
alleles (see traits.py). Regression to the mean, sibling variance, and
parent-offspring correlation all become emergent rather than stipulated.

`crossover.py`-style SBX is kept only in `legacy.py` as a comparison
baseline, exactly as the original file kept single/multi-point crossover.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from .genetic_map import AUTOSOMES, AUTOSOME_NUMBERS
from .loci import ALT_FREQ, CM_POS, LOCI_BY_CHROM, N_LOCI

# ----------------------------------------------------------------------
# Mutation constants (roadmap #12)
# ----------------------------------------------------------------------
# Kong et al. 2012 (Nature 488:471): the human de novo point-mutation
# rate is ~1.20e-8 per nucleotide per generation, giving ~63 de novo SNVs
# per genome at the average paternal age of 29.7 years, with a ~4:1
# paternal:maternal bias and ~+2 mutations per additional year of
# paternal age.
#
# Our loci are not nucleotides -- each stands for a functional gene
# region of order 10^4 bp. Multiplying through gives a per-locus,
# per-gamete rate of ~1e-4. At L=500 loci that is ~0.05 mutations per
# gamete: rare enough to be a genuine novelty source, frequent enough to
# be observable over hundreds of meioses.
PER_NUCLEOTIDE_MUTATION_RATE = 1.20e-8
ASSUMED_LOCUS_SPAN_BP = 1.5e4
LOCUS_MUTATION_RATE = PER_NUCLEOTIDE_MUTATION_RATE * ASSUMED_LOCUS_SPAN_BP  # ~1.8e-4

# Kong 2012 regression: de novo count ~= 25.6 + 2.01 * paternal age.
_KONG_INTERCEPT = 25.6
_KONG_SLOPE = 2.01
REFERENCE_PATERNAL_AGE = 29.7

# Fraction of de novo mutations arising in the paternal germline (~80%,
# the 4:1 bias). Maternal gametes mutate, but far less.
PATERNAL_MUTATION_FRACTION = 0.80


def paternal_age_multiplier(paternal_age: float) -> float:
    """
    Scale the paternal-gamete mutation rate by the father's age, relative
    to the population-average paternal age. Kong et al. 2012.

    A 50-year-old father transmits roughly (25.6 + 2.01*50) / (25.6 +
    2.01*29.7) ~= 1.5x the reference number of de novo mutations.
    """
    ref = _KONG_INTERCEPT + _KONG_SLOPE * REFERENCE_PATERNAL_AGE
    return (_KONG_INTERCEPT + _KONG_SLOPE * max(paternal_age, 0.0)) / ref


# ----------------------------------------------------------------------
# Genome
# ----------------------------------------------------------------------

@dataclass
class Genome:
    """Diploid autosomal genome. haplotypes[0] = maternal, [1] = paternal."""
    haplotypes: np.ndarray          # (2, L) int8, values in {0, 1}

    def __post_init__(self) -> None:
        if self.haplotypes.shape != (2, N_LOCI):
            raise ValueError(
                f"expected haplotypes of shape (2, {N_LOCI}), got {self.haplotypes.shape}"
            )

    @property
    def dosage(self) -> np.ndarray:
        """(L,) int8 count of alternate alleles per locus: 0, 1 or 2."""
        return self.haplotypes.sum(axis=0).astype(np.int8)

    @property
    def is_heterozygous(self) -> np.ndarray:
        return self.haplotypes[0] != self.haplotypes[1]

    def heterozygosity(self) -> float:
        """Observed fraction of heterozygous loci. Drops with inbreeding --
        the empirical counterpart of Wright's F (see mating.py, item #31)."""
        return float(self.is_heterozygous.mean())

    def copy(self) -> "Genome":
        return Genome(self.haplotypes.copy())


def sample_founder_genome(rng: np.random.Generator,
                          alt_freq: Optional[np.ndarray] = None) -> Genome:
    """
    Roadmap #29. Draw each haplotype's allele independently as
    Bernoulli(p) at every locus.

    Two properties follow automatically and are asserted by
    `validation.hardy_weinberg_test` and `validation.linkage_disequilibrium`:

      * Hardy-Weinberg proportions: P(AA) = p^2, P(Aa) = 2pq, P(aa) = q^2
        (Hardy 1908; Weinberg 1908).
      * Linkage equilibrium: alleles at different loci are independent,
        so D = 0 at generation 0 and any LD later observed is generated
        by the simulation (drift, selection, assortative mating) rather
        than baked into the founders.

    LIMITATION: real founding populations carry ancestral LD from their
    demographic history (1000 Genomes Project Consortium 2015). Starting
    at linkage equilibrium is the conservative, testable choice, not a
    realistic one.
    """
    p = ALT_FREQ if alt_freq is None else alt_freq
    haps = (rng.random((2, N_LOCI)) < p).astype(np.int8)
    return Genome(haps)


# ----------------------------------------------------------------------
# Meiosis (roadmap #1)
# ----------------------------------------------------------------------

def meiosis(genome: Genome, rng: np.random.Generator, sex: str = "average",
            map_scale: float = 1.0) -> np.ndarray:
    """
    Produce one haploid gamete (L,) int8 from a diploid genome.

    For each chromosome:
      1. Draw a crossover count from Poisson(lambda = map length in
         Morgans). Under this model the expected number of crossovers on
         a 1-Morgan chromosome is exactly 1.
      2. Place the crossovers uniformly along the cM map.
      3. Pick a starting haplotype at random, then flip which haplotype
         we copy from at every crossover point.

    Because the crossovers are a homogeneous Poisson process, the number
    falling between two loci d Morgans apart is Poisson(d), and a
    recombinant gamete requires an ODD number of them:

        r = P(odd) = (1 - exp(-2d)) / 2      <- Haldane's map function

    This is checked directly in tests/test_genome.py.

    LIMITATION -- NO CROSSOVER INTERFERENCE. Real meiosis exhibits strong
    positive interference: one crossover suppresses others within tens of
    cM, so real crossover counts per chromosome are under-dispersed
    relative to Poisson (variance < mean) and at least one crossover per
    bivalent is obligate. Modelling that properly needs a chi-square /
    gamma renewal model (Broman & Weber 2000). Our Poisson draw therefore
    (a) occasionally produces zero-crossover chromosomes, which real
    meioses almost never do, and (b) slightly overstates long-range
    shuffling. Both are acceptable at this fidelity; neither affects the
    Haldane recombination fraction between any *pair* of loci.

    `sex`: "male" | "female" | "average". Female maps are ~1.6x longer
    (Kong et al. 2002), so mothers shuffle their chromosomes more.
    `map_scale`: debug/testing knob to inflate or suppress recombination.
    """
    from .genetic_map import FEMALE_MAP_RATIO, MALE_MAP_RATIO

    ratio = {"male": MALE_MAP_RATIO, "female": FEMALE_MAP_RATIO, "average": 1.0}[sex]
    ratio *= map_scale

    gamete = np.empty(N_LOCI, dtype=np.int8)

    for chrom in AUTOSOME_NUMBERS:
        idx = LOCI_BY_CHROM[chrom]
        if idx.size == 0:
            continue
        length_cm = AUTOSOMES[chrom].cm_length_avg * ratio
        n_xo = rng.poisson(length_cm / 100.0)

        start = int(rng.integers(0, 2))
        if n_xo == 0:
            gamete[idx] = genome.haplotypes[start, idx]
            continue

        xo = np.sort(rng.uniform(0.0, length_cm, size=n_xo))
        # cM positions were computed on the sex-averaged map; rescale so
        # crossover positions and locus positions live on the same axis.
        pos = CM_POS[idx] * ratio
        # How many crossovers lie to the left of each locus -> parity
        # decides which parental haplotype we are currently copying.
        crossings = np.searchsorted(xo, pos, side="right")
        which = (start + crossings) % 2
        gamete[idx] = genome.haplotypes[which, idx]

    return gamete


def mutate_gamete(gamete: np.ndarray, rng: np.random.Generator,
                  parent_sex: str = "average",
                  parent_age: Optional[float] = None,
                  rate: float = LOCUS_MUTATION_RATE) -> int:
    """
    Roadmap #12. Flip alleles in place at a realistic per-locus rate.
    Returns the number of de novo mutations introduced.

    The paternal germline divides continuously through life, so its
    mutation rate rises with age; the maternal germline arrests early and
    contributes ~4x fewer mutations with little age dependence (Kong
    2012). We reproduce both the 4:1 baseline bias and the paternal-age
    slope.

    LIMITATION: only point mutations. Copy-number and structural variants
    (Sebat et al. 2007) are not modelled -- a real CNV can delete or
    duplicate whole gene regions, which our fixed-length allele array
    cannot express.
    """
    if parent_sex == "male":
        eff = rate * 2.0 * PATERNAL_MUTATION_FRACTION
        if parent_age is not None:
            eff *= paternal_age_multiplier(parent_age)
    elif parent_sex == "female":
        eff = rate * 2.0 * (1.0 - PATERNAL_MUTATION_FRACTION)
    else:
        eff = rate

    hits = np.flatnonzero(rng.random(gamete.size) < eff)
    if hits.size:
        gamete[hits] = 1 - gamete[hits]
    return int(hits.size)


def fertilise(maternal_gamete: np.ndarray, paternal_gamete: np.ndarray) -> Genome:
    return Genome(np.stack([maternal_gamete, paternal_gamete]).astype(np.int8))


def cross(mother: Genome, father: Genome, rng: np.random.Generator,
          mother_age: Optional[float] = None,
          father_age: Optional[float] = None,
          mutation: bool = True,
          map_scale: float = 1.0,
          mutation_rate_scale: float = 1.0) -> tuple[Genome, int]:
    """One full sexual reproduction event. Returns (child genome, de novo count).

    `map_scale` and `mutation_rate_scale` are EXPERIMENTAL multipliers (both
    1.0 = the calibrated Kong 2012 / deCODE defaults, so the RNG stream and
    every existing test are bit-for-bit identical). They exist so a population
    simulation can ask counterfactual questions -- "what if recombination were
    doubled?", "what if the mutation rate were 5x?" -- to explore accelerated
    drift or Muller's ratchet. They are knobs for an experiment, NOT a claim
    that real per-nucleotide rates vary this way.
    """
    egg = meiosis(mother, rng, sex="female", map_scale=map_scale)
    sperm = meiosis(father, rng, sex="male", map_scale=map_scale)
    n_dn = 0
    if mutation:
        rate = LOCUS_MUTATION_RATE * mutation_rate_scale
        n_dn += mutate_gamete(egg, rng, parent_sex="female",
                              parent_age=mother_age, rate=rate)
        n_dn += mutate_gamete(sperm, rng, parent_sex="male",
                              parent_age=father_age, rate=rate)
    return fertilise(egg, sperm), n_dn


# ----------------------------------------------------------------------
# Population-level helpers
# ----------------------------------------------------------------------

def dosage_matrix(genomes: list[Genome]) -> np.ndarray:
    """(N, L) int8 matrix of alternate-allele dosages."""
    return np.stack([g.dosage for g in genomes]).astype(np.int8)


def allele_frequencies(genomes: list[Genome]) -> np.ndarray:
    """(L,) observed alternate-allele frequency in the sample."""
    d = dosage_matrix(genomes).astype(np.float64)
    return d.mean(axis=0) / 2.0
