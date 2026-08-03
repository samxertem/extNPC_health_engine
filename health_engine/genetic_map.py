"""
Genetic map: chromosomes, physical (bp) and genetic (centimorgan) lengths.
=========================================================================

Roadmap item #1 (chromosomes + recombination).

Why a genetic map at all
------------------------
The v0.2 prototype segregated every locus independently. That is a
Mendel-1866 model: it is correct only for loci on different chromosomes,
or far apart on the same one. Real genes sit at physical positions on 23
chromosome pairs, and nearby genes are *co-inherited* -- they travel in
haplotype blocks (linkage disequilibrium) broken only by meiotic
crossover.

Distances are therefore measured twice:

  * physical distance, in base pairs (bp). What a genome browser shows.
  * genetic distance, in centimorgans (cM). 1 cM = 1% expected chance
    that a crossover separates two loci in a single meiosis. 100 cM =
    1 Morgan.

These are NOT proportional. Recombination is concentrated in hotspots
and suppressed near centromeres, so cM/Mb varies ~orders of magnitude
along a chromosome. We use a *uniform* cM/Mb rate per chromosome. See
LIMITATIONS below.

Numbers
-------
Sex-averaged genetic lengths are approximated from the deCODE pedigree
maps (Kong et al. 2002, Nat. Genet. 31:241; Kong et al. 2010, Nature
467:1099). Genome-wide totals in those maps are roughly:

    male   ~2,600 cM     female ~4,200 cM     sex-averaged ~3,400 cM

i.e. the female map is ~1.6x longer -- women recombine more. We keep the
sex-averaged length per chromosome and derive the sex-specific maps with
a single global ratio.

Physical lengths are GRCh38 chromosome sizes rounded to the nearest Mb.

LIMITATIONS (do not lose these -- roadmap Section 5 honesty constraints)
------------------------------------------------------------------------
1. Uniform cM/Mb within a chromosome. Real maps have hotspots (PRDM9-
   directed) and centromeric coldspots. Consequence: our LD decay is
   smooth where real LD is blocky.
2. A single global male/female map-length ratio. Real ratios are
   chromosome- and position-specific (male recombination is telomere-
   biased, female is more uniform).
3. Haldane's map function, i.e. NO crossover interference. Real meioses
   show positive interference -- one crossover suppresses another
   nearby, so real crossover counts are under-dispersed relative to the
   Poisson we draw from. See `meiosis()` in genome.py.
4. This map covers the 22 autosomes only. The sex chromosomes (roadmap #2)
   are modelled in a parallel module, `sexchrom.py`, because they obey
   qualitatively different rules (hemizygosity, X-inactivation, no X-Y
   recombination outside the PAR) and assort independently of every
   autosome. The female X genetic map (~180 cM) lives there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import numpy as np

# Ratio of sex-specific total map length to the sex-averaged map length.
# Derived from the deCODE totals above (2600/3400, 4200/3400).
MALE_MAP_RATIO = 0.76
FEMALE_MAP_RATIO = 1.24


@dataclass(frozen=True)
class Chromosome:
    number: int
    bp_length_mb: float          # GRCh38 physical length, megabases
    cm_length_avg: float         # sex-averaged genetic length, centimorgans

    @property
    def cm_length_male(self) -> float:
        return self.cm_length_avg * MALE_MAP_RATIO

    @property
    def cm_length_female(self) -> float:
        return self.cm_length_avg * FEMALE_MAP_RATIO

    def bp_to_cm(self, bp_mb: float) -> float:
        """Uniform-rate physical -> genetic position. See LIMITATIONS #1."""
        frac = min(max(bp_mb / self.bp_length_mb, 0.0), 1.0)
        return frac * self.cm_length_avg


# 22 autosomes. (chrom, physical Mb, sex-averaged cM)
_AUTOSOME_SPECS = [
    (1, 248.0, 284.0), (2, 242.0, 269.0), (3, 198.0, 224.0), (4, 190.0, 214.0),
    (5, 181.0, 209.0), (6, 170.0, 194.0), (7, 159.0, 187.0), (8, 145.0, 169.0),
    (9, 138.0, 167.0), (10, 133.0, 174.0), (11, 135.0, 161.0), (12, 133.0, 175.0),
    (13, 114.0, 126.0), (14, 107.0, 121.0), (15, 101.0, 132.0), (16, 90.0, 131.0),
    (17, 83.0, 129.0), (18, 80.0, 124.0), (19, 58.0, 110.0), (20, 64.0, 108.0),
    (21, 46.0, 62.0), (22, 50.0, 74.0),
]

AUTOSOMES: Dict[int, Chromosome] = {
    n: Chromosome(n, bp, cm) for n, bp, cm in _AUTOSOME_SPECS
}

AUTOSOME_NUMBERS: List[int] = sorted(AUTOSOMES)

TOTAL_MAP_LENGTH_CM = sum(c.cm_length_avg for c in AUTOSOMES.values())


def expected_crossovers_per_meiosis(sex: str = "average") -> float:
    """Genome-wide expected crossover count. Under the Poisson (Haldane)
    model this equals the total map length in Morgans."""
    ratio = {"male": MALE_MAP_RATIO, "female": FEMALE_MAP_RATIO, "average": 1.0}[sex]
    return TOTAL_MAP_LENGTH_CM * ratio / 100.0


def haldane_recombination_fraction(distance_cm: float) -> float:
    """
    Haldane's map function: probability that an ODD number of crossovers
    falls between two loci `distance_cm` apart, given a Poisson crossover
    process with no interference.

        r = (1 - exp(-2d)) / 2,   d in Morgans

    Asymptotes to 0.5 (free assortment). This is the analytic target that
    `tests/test_genome.py` checks the simulated meiosis against.
    """
    d = distance_cm / 100.0
    return 0.5 * (1.0 - float(np.exp(-2.0 * d)))
