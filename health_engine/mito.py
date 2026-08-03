"""
Mitochondrial (maternal) inheritance: heteroplasmy, threshold, bottleneck.
==========================================================================

Roadmap item #3. Nuclear inheritance (genome.py) is biparental and Mendelian.
Mitochondrial DNA is neither: it is transmitted almost exclusively through the
egg, it is present in many copies per cell that can carry a *mixture* of
variants (heteroplasmy), it expresses a phenotype only past a threshold mutant
load, and its transmission passes through a severe developmental bottleneck
that makes a mother's and her child's mutant load differ unpredictably. This
module models all four, in a layer parallel to the nuclear genome (the same
separation used for the sex chromosomes) so the calibrated autosomal core is
untouched.

The four facts modelled
-----------------------
1. STRICT MATERNAL INHERITANCE. A child's mtDNA comes entirely from its
   mother; sperm mitochondria are ubiquitin-tagged and destroyed after
   fertilisation. Paternal transmission in humans is essentially absent (the
   one widely-reported pedigree, Luo et al. 2018, is contested). So the
   maternal lineage is traced by mtDNA -- the basis of "mitochondrial Eve".
   (Giles et al. 1980, PNAS 77:6715.)

2. HETEROPLASMY. Each cell has hundreds-thousands of mtDNA molecules. A
   pathogenic variant can occupy a *fraction* h in [0, 1] of them
   (heteroplasmy); h = 0 or 1 is homoplasmy. Wild-type molecules
   biochemically complement mutant ones. (Wallace 1999, Science 283:1482.)

3. THRESHOLD EFFECT. Oxidative-phosphorylation output stays near normal until
   mutant load crosses a threshold (~60-80% for most pathogenic mtDNA
   mutations), then falls steeply; disease (MELAS m.3243A>G, LHON, MERRF)
   manifests above it. This nonlinearity is the defining feature of
   mitochondrial genetics. (Rossignol et al. 2003, Biochem. J. 370:751.)

4. THE mtDNA BOTTLENECK. During oogenesis only a small effective number of
   mtDNA segregating units is sampled into each egg, so offspring heteroplasmy
   scatters widely around the mother's -- a 50%-carrier mother can have
   children from ~near-0% to ~near-100%. This is why mitochondrial-disease
   inheritance is famously unpredictable. We model transmission as a binomial
   resample through an effective bottleneck of `MITO_BOTTLENECK_N` units, which
   gives the offspring the closed-form variance h(1-h)/N that
   `validation.mito_bottleneck` checks. (Cree et al. 2008, Nat. Genet. 40:249;
   Wai et al. 2008, Nat. Genet. 40:1484; Stewart & Chinnery 2015,
   Nat. Rev. Genet. 16:530.)

Phenotype coupling
------------------
OXPHOS capacity gates aerobic capacity / cellular stamina -- the arm
`traits.py` flags as "Mitochondrial (maternal) contribution is roadmap #3,
absent". `NPC.effective_aerobic_capacity()` multiplies the nuclear-genetic VO2
max by `oxphos_capacity()`, so a below-threshold carrier is near-normal and an
above-threshold one is impaired, without disturbing the calibrated nuclear
trait.

CAVEATS (roadmap Section 5 -- load-bearing)
-------------------------------------------
* The effective bottleneck size is genuinely uncertain: measured estimates
  range from ~30 to ~200 segregating units depending on method and definition
  (Cree 2008 ~185; other models far smaller). We take a value in that range
  and expose the variance formula so the mechanism is transparent, not tuned.
* One generic pathogenic locus is modelled (a MELAS/m.3243A>G-type variant).
  Real mtDNA carries many sites; tissue-specific thresholds and segregation,
  and somatic heteroplasmy drift with age, are not modelled.
* Haplogroup here is a NEUTRAL maternal-lineage marker with NO phenotype
  attached. Reported associations of common haplogroups with endurance or
  longevity are weak and inconsistent (cf. the candidate-gene caveat); we do
  not encode them.
* Frequencies for the haplogroup marker are illustrative and NOT
  ancestry-general (the values resemble a European distribution).
* LHON's male-biased, incomplete penetrance (nuclear/hormonal modifiers) is
  not modelled; only the generic heteroplasmy threshold is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------

# Effective number of mtDNA segregating units transmitted through the
# oogenesis bottleneck. Within the cited ~30-200 range; this value gives a
# realistically wide offspring spread (SD ~0.09 at h=0.5). See CAVEATS.
MITO_BOTTLENECK_N = 30

# Biochemical threshold: OXPHOS stays near normal until mutant load exceeds
# ~0.70, then drops steeply. `_OXPHOS_STEEPNESS` sets how sharp the knee is.
OXPHOS_THRESHOLD = 0.70
_OXPHOS_STEEPNESS = 16.0
# Residual OXPHOS floor at full mutant load (not literally zero -- residual
# complex activity and glycolytic compensation persist).
OXPHOS_FLOOR = 0.12

# Clinical manifestation threshold (disease expression), a little above the
# biochemical knee, per most pathogenic mtDNA mutations.
DISEASE_THRESHOLD = 0.80

# Illustrative maternal-haplogroup frequencies (European-like; NOT general).
HAPLOGROUP_FREQ: Dict[str, float] = {
    "H": 0.45, "U": 0.15, "J": 0.11, "T": 0.09, "K": 0.06,
    "V": 0.05, "X": 0.03, "W": 0.03, "I": 0.03,
}
_HAPLOGROUPS: List[str] = list(HAPLOGROUP_FREQ)
_HAPLO_P: np.ndarray = np.array(list(HAPLOGROUP_FREQ.values()))
_HAPLO_P = _HAPLO_P / _HAPLO_P.sum()


def oxphos_capacity(heteroplasmy: float) -> float:
    """
    Relative oxidative-phosphorylation capacity in [OXPHOS_FLOOR, 1.0] as a
    function of pathogenic-mtDNA heteroplasmy.

    A logistic knee centred on OXPHOS_THRESHOLD: near 1.0 while wild-type
    mitochondria complement the defect, falling steeply once mutant load
    passes the threshold (Rossignol et al. 2003). This is the biological
    reason a 60%-mutant carrier can be asymptomatic while an 85%-mutant
    sibling is not.
    """
    knee = 1.0 / (1.0 + np.exp(_OXPHOS_STEEPNESS * (heteroplasmy - OXPHOS_THRESHOLD)))
    # rescale the logistic (which is ~1 at h=0 and ~0 at h=1) onto [floor, 1]
    lo = 1.0 / (1.0 + np.exp(_OXPHOS_STEEPNESS * (1.0 - OXPHOS_THRESHOLD)))
    hi = 1.0 / (1.0 + np.exp(_OXPHOS_STEEPNESS * (0.0 - OXPHOS_THRESHOLD)))
    frac = (knee - lo) / (hi - lo)
    return float(OXPHOS_FLOOR + (1.0 - OXPHOS_FLOOR) * frac)


# ======================================================================
# Mitochondrial genome
# ======================================================================

@dataclass
class MitoGenome:
    """
    An individual's mitochondrial state.

    haplogroup: neutral maternal-lineage marker (no phenotype).
    heteroplasmy: fraction of mtDNA carrying the modelled pathogenic variant,
        in [0, 1]. 0 for the overwhelming majority; > 0 only in a maternal
        lineage that carries the variant.
    """
    haplogroup: str
    heteroplasmy: float = 0.0

    def copy(self) -> "MitoGenome":
        return MitoGenome(self.haplogroup, self.heteroplasmy)

    # ---- phenotype ---------------------------------------------------

    def oxphos_capacity(self) -> float:
        """Relative OXPHOS capacity (threshold function of heteroplasmy)."""
        return oxphos_capacity(self.heteroplasmy)

    def manifests_disease(self) -> bool:
        """Whether mitochondrial disease manifests (heteroplasmy above the
        clinical threshold). A population-level model outcome, not a
        diagnosis."""
        return self.heteroplasmy >= DISEASE_THRESHOLD

    def phenotype(self) -> Dict[str, object]:
        return {
            "haplogroup": self.haplogroup,
            "heteroplasmy": round(self.heteroplasmy, 3),
            "oxphos_capacity": round(self.oxphos_capacity(), 3),
            "mito_disease": self.manifests_disease(),
        }

    # ---- transmission (maternal only) --------------------------------

    def transmit(self, rng: np.random.Generator) -> "MitoGenome":
        """
        Produce a child's mtDNA from this (maternal) mtDNA.

        The haplogroup copies exactly (it is the lineage marker). The
        heteroplasmy is resampled through the oogenesis bottleneck: draw
        MITO_BOTTLENECK_N mtDNA units, each mutant with probability equal to
        the mother's heteroplasmy, and take the mutant fraction. This gives
        offspring heteroplasmy with mean = mother's and variance
        h(1-h)/N -- the wide, unpredictable scatter real mtDNA disease shows.
        """
        if self.heteroplasmy <= 0.0:
            child_h = 0.0
        elif self.heteroplasmy >= 1.0:
            child_h = 1.0
        else:
            n_mutant = rng.binomial(MITO_BOTTLENECK_N, self.heteroplasmy)
            child_h = n_mutant / MITO_BOTTLENECK_N
        return MitoGenome(self.haplogroup, float(child_h))


# ======================================================================
# Founder sampling
# ======================================================================

def sample_founder_mito(rng: np.random.Generator,
                        carrier_prob: float = 0.0,
                        carrier_heteroplasmy: float = 0.5) -> MitoGenome:
    """
    Draw a founder's mtDNA. Haplogroup from the (illustrative) marker
    frequencies; heteroplasmy 0 unless this founder seeds a carrier lineage
    (probability `carrier_prob`), in which case it starts at
    `carrier_heteroplasmy`. Founders default to homoplasmic wild-type.
    """
    hg = str(rng.choice(_HAPLOGROUPS, p=_HAPLO_P))
    h = carrier_heteroplasmy if (carrier_prob > 0 and rng.random() < carrier_prob) else 0.0
    return MitoGenome(hg, float(h))
