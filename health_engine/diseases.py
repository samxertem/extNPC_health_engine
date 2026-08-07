"""
Named Mendelian recessive disorders on the deleterious-load layer.
=================================================================

The load spectrum (`inbreeding.py`) is 2000 anonymous loci: each carries a
deleterious allele frequency `q` from mutation-selection balance, a
homozygous selection coefficient `s` from a gamma DFE, and a dominance
coefficient `h`. Individuals really inherit these genotypes and homozygotes
really pay `s` through juvenile survival -- but until this module the layer
had no *identities*, so a consanguineous birth produced a viability number
and never a diagnosis. Real consanguinity studies report their findings the
other way around: as named autosomal recessive disorders (Bittles & Black
2010; Modell & Darr 2002). This module closes that gap.

Design: LABELS, NOT NEW LOCI
----------------------------
Each disease below is *assigned to an existing spectrum locus* whose
(q, s) pair sits closest to the literature's carrier frequency and
(pre-modern, untreated) fitness cost. Nothing is added, redrawn, or
recalibrated:

  * zero new RNG draws anywhere -- the assignment is a deterministic
    function of the fixed spectrum (seed 20260804) and the frozen
    catalogue order below;
  * the lethal-equivalent calibration (B = 1.4) is untouched, because the
    panel loci were already in it;
  * an "affected" child is simply one whose existing load genotype is
    homozygous at a labelled locus -- the selection coefficient that was
    always going to reduce its survival is now the named disease's `s`.

The cost of that honesty is that the engine's carrier frequency for a
disease is the matched locus's `q`, not the literature value. Both are
recorded on every assignment, and the deviation is REPORTED rather than
hidden (see `panel_summary` and validation section [9d]). Most match
within ~25%; the interesting exception is below.

Cystic fibrosis is the documented misfit, and the misfit is the science
------------------------------------------------------------------------
CF segregates at carrier frequency ~1/25 in Europeans despite being
lethal-in-childhood untreated. Under pure mutation-selection balance
q = u/(hs) cannot reach 0.02 with s ~ 1 at any plausible human mutation
rate -- which is exactly why the literature invokes heterozygote advantage
(resistance to typhoid/cholera toxin-mediated secretion; Gabriel et al.
1994) or founder effects to explain it. This spectrum is built from pure
MSB, so its best available locus for CF sits at q = 0.014 with s = 0.45:
the model *cannot* host CF faithfully, for the same reason MSB cannot,
and the deviation column says so. Treat the engine's "cystic fibrosis"
as CF-like in inheritance and epidemiological behaviour, not in magnitude.

Deliberate exclusions
---------------------
  * Sickle-cell anaemia (HBB): maintained by balancing selection under
    malaria, not MSB. The spectrum has no overdominant sites, so any
    assignment would misrepresent the mechanism that makes HbS famous.
  * Tay-Sachs at general-population frequency (q ~ 0.003) sits below the
    spectrum's frequency floor (~0.006, set by u/(h_max * s_min) at the
    solved mutation rate); the Ashkenazi founder-elevated frequency is a
    population-structure effect this single-population spectrum lacks.
  * Hereditary haemochromatosis (HFE C282Y, q ~ 0.07): above the
    spectrum's `_Q_MAX` guard, and with penetrance so low that "affected"
    would not mean what the other rows mean.

Fitness costs are PRE-TREATMENT by design
-----------------------------------------
`s_lit` is the untreated, historical fitness cost -- the world simulated
here has no newborn screening and no enzyme-replacement therapy, and the
load layer's `s` is what actually removes affected children through
juvenile survival. Modern treated prognoses (PKU on diet, SMA on
nusinersen) are radically better and deliberately not modelled.

References
----------
O'Sullivan & Freedman 2009 (*Lancet* 373:1891) -- CF; carrier ~1/25 N. Eur.
Gabriel et al. 1994 (*Science* 266:107) -- CFTR heterozygote advantage.
Sugarman et al. 2012 (*Eur. J. Hum. Genet.* 20:27) -- SMA carrier 1/54.
Kolb & Kissel 2015 (*Neurol. Clin.* 33:831) -- SMA natural history.
Williams, Mamotte & Burnett 2008 (*Clin. Biochem. Rev.* 29:31) -- PKU
    incidence ~1/10,000 in Europeans.
Penrose 1935 (*Lancet* 226:192) -- untreated PKU and reproduction.
Speiser & White 2003 (*NEJM* 349:776) -- classic CAH ~1/15,000, ~75%
    salt-wasting.
Berry 2012 (GeneReviews: Classic Galactosemia) -- incidence ~1/48,000.
Grosse et al. 2006 (*Genet. Med.* 8:205) -- MCAD ~1/15,000 N. Eur.
Iafolla et al. 1994 (*J. Pediatr.* 124:409) -- MCAD untreated mortality.
Ala et al. 2007 (*Lancet* 369:397) -- Wilson disease ~1/30,000.
Chan & Chang 2014 (*Laryngoscope* 124:E34) -- GJB2 carrier rates.
Blanco et al. 2006 (*Clin. Genet.* 70:96) -- PiZ allele frequencies.
Lazarin et al. 2013 (*Genet. Med.* 15:178) -- expanded carrier screening:
    ~24% of individuals carry >= 1 of 108 recessive disorders.
Bittles & Black 2010 (*PNAS* 107:1779) -- consanguinity and recessive risk.
Modell & Darr 2002 (*Nat. Rev. Genet.* 3:225) -- consanguinity multiplies
    rare-recessive incidence many-fold while common-disease risk barely moves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from .inbreeding import SPECTRUM, DeleteriousLoad, LoadSpectrum


# ======================================================================
# 1. The catalogue (frozen order -- greedy assignment depends on it)
# ======================================================================

@dataclass(frozen=True)
class DiseaseSpec:
    """One real autosomal recessive disorder, as the literature gives it."""
    name: str                  # snake_case identifier
    label: str                 # display name
    gene: str
    omim: str                  # phenotype MIM number
    q_lit: float               # literature deleterious allele frequency
    s_lit: float               # untreated (pre-modern) homozygote fitness cost
    onset: str                 # 'infancy' | 'childhood' | 'adult'
    restricted_actions: Tuple[str, ...]
    citation: str
    note: str = ""

    @property
    def carrier_lit(self) -> str:
        """Literature carrier frequency as the familiar '1 in N'."""
        return f"1 in {round(1.0 / (2.0 * self.q_lit * (1.0 - self.q_lit)))}"


# The frozen catalogue. ORDER MATTERS: assignment is greedy in this order,
# so reordering silently reassigns loci. Append only.
CATALOGUE: Tuple[DiseaseSpec, ...] = (
    DiseaseSpec(
        name="cystic_fibrosis", label="cystic fibrosis", gene="CFTR",
        omim="219700", q_lit=0.020, s_lit=0.95, onset="infancy",
        restricted_actions=("run", "sprint", "carry_heavy_loads"),
        citation="O'Sullivan & Freedman 2009, Lancet 373:1891",
        note=("Known misfit, on purpose: q=0.02 with s~1 is impossible "
              "under pure mutation-selection balance, which is why the "
              "literature invokes heterozygote advantage (Gabriel 1994). "
              "See module docstring."),
    ),
    DiseaseSpec(
        name="spinal_muscular_atrophy", label="spinal muscular atrophy",
        gene="SMN1", omim="253300", q_lit=1.0 / 108.0, s_lit=0.90,
        onset="infancy",
        restricted_actions=("run", "climb", "carry_heavy_loads", "grab"),
        citation="Sugarman 2012, Eur J Hum Genet 20:27 (carrier 1/54)",
    ),
    DiseaseSpec(
        name="phenylketonuria", label="phenylketonuria", gene="PAH",
        omim="261600", q_lit=0.010, s_lit=0.75, onset="infancy",
        restricted_actions=("read", "negotiate_trade"),
        citation="Williams 2008, Clin Biochem Rev 29:31; Penrose 1935",
        note="s_lit is the UNTREATED cost; dietary treatment is not modelled.",
    ),
    DiseaseSpec(
        name="congenital_adrenal_hyperplasia",
        label="congenital adrenal hyperplasia (classic)", gene="CYP21A2",
        omim="201910", q_lit=1.0 / 122.0, s_lit=0.75, onset="infancy",
        restricted_actions=("fast_for_long_periods",),
        citation="Speiser & White 2003, NEJM 349:776",
        note="~75% of classic cases are salt-wasting, lethal untreated.",
    ),
    DiseaseSpec(
        name="galactosemia", label="classic galactosemia", gene="GALT",
        omim="230400", q_lit=1.0 / 220.0, s_lit=0.80, onset="infancy",
        restricted_actions=("fast_for_long_periods",),
        citation="Berry 2012, GeneReviews (incidence ~1/48,000)",
    ),
    DiseaseSpec(
        name="mcad_deficiency", label="MCAD deficiency", gene="ACADM",
        omim="201450", q_lit=1.0 / 122.0, s_lit=0.25, onset="childhood",
        restricted_actions=("fast_for_long_periods", "sprint"),
        citation="Grosse 2006, Genet Med 8:205; Iafolla 1994, J Pediatr 124:409",
        note="Episodic: ~20-25% mortality at first metabolic crisis untreated.",
    ),
    DiseaseSpec(
        name="wilson_disease", label="Wilson disease", gene="ATP7B",
        omim="277900", q_lit=1.0 / 180.0, s_lit=0.50, onset="adult",
        restricted_actions=("carry_heavy_loads", "negotiate_trade"),
        citation="Ala 2007, Lancet 369:397",
        note=("Fatal untreated but typically post-adolescent onset, hence "
              "the partial fitness cost."),
    ),
    DiseaseSpec(
        name="gjb2_deafness", label="GJB2 nonsyndromic deafness",
        gene="GJB2", omim="220290", q_lit=1.0 / 66.0, s_lit=0.20,
        onset="infancy",
        restricted_actions=("eavesdrop", "detect_approaching_threat_by_sound"),
        citation="Chan & Chang 2014, Laryngoscope 124:E34 (carrier ~1/33 Eur.)",
    ),
    DiseaseSpec(
        name="a1at_deficiency", label="alpha-1 antitrypsin deficiency (PiZZ)",
        gene="SERPINA1", omim="613490", q_lit=0.014, s_lit=0.05,
        onset="adult",
        restricted_actions=("sprint",),
        citation="Blanco 2006, Clin Genet 70:96 (PiZ q ~ 0.014 N. Eur.)",
        note="The mild end of the panel: adult-onset, small fitness cost.",
    ),
)


# ======================================================================
# 2. Assignment: each disease claims the nearest unclaimed spectrum locus
# ======================================================================

@dataclass(frozen=True)
class AssignedDisease:
    """A catalogue disease bound to the spectrum locus that hosts it."""
    spec: DiseaseSpec
    locus: int                 # index into SPECTRUM arrays
    q: float                   # the ENGINE's frequency for this disease
    s: float
    h: float

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def label(self) -> str:
        return self.spec.label

    @property
    def carrier_engine(self) -> str:
        return f"1 in {round(1.0 / (2.0 * self.q * (1.0 - self.q)))}"

    @property
    def q_ratio(self) -> float:
        """Engine q over literature q. 1.0 = perfect frequency match."""
        return self.q / self.spec.q_lit

    @property
    def s_ratio(self) -> float:
        return self.s / self.spec.s_lit


# Weight on severity relative to frequency in the matching distance.
# Frequency dominates because it is what drives the epidemiology the
# validation law checks (q^2 + Fpq); severity is secondary because every
# candidate locus is already deleterious and already selected against.
_S_WEIGHT: float = 0.5


def _assign(spectrum: LoadSpectrum = SPECTRUM,
            catalogue: Tuple[DiseaseSpec, ...] = CATALOGUE
            ) -> Tuple[AssignedDisease, ...]:
    """
    Greedy nearest-locus assignment in frozen catalogue order, in
    (log q, log s) space. Deterministic: the spectrum is a seeded constant
    and the catalogue order is frozen, so the same loci are chosen on every
    import, on every machine. A test pins the resulting indices.
    """
    used: set = set()
    out: List[AssignedDisease] = []
    for spec in catalogue:
        d = ((np.log(spectrum.q / spec.q_lit)) ** 2
             + _S_WEIGHT * (np.log(spectrum.s / spec.s_lit)) ** 2)
        for i in np.argsort(d):
            if int(i) not in used:
                used.add(int(i))
                out.append(AssignedDisease(
                    spec=spec, locus=int(i),
                    q=float(spectrum.q[i]), s=float(spectrum.s[i]),
                    h=float(spectrum.h[i])))
                break
    return tuple(out)


DISEASES: Tuple[AssignedDisease, ...] = _assign()

# The panel's locus indices, in catalogue order, for vectorised lookups.
PANEL_LOCI: np.ndarray = np.array([d.locus for d in DISEASES], dtype=np.intp)


# ======================================================================
# 3. Read-outs (pure functions of an existing genotype -- no RNG, ever)
# ======================================================================

def diagnoses(load: DeleteriousLoad) -> List[AssignedDisease]:
    """
    Diseases whose locus is homozygous deleterious in this individual.

    Nothing here changes the individual's fate: the homozygote was already
    paying this locus's `s` through `DeleteriousLoad.viability` before it
    had a name. This function only says WHICH disorder that cost is.
    """
    dosage = load.dosage[PANEL_LOCI]
    return [d for d, g in zip(DISEASES, dosage) if g == 2]


def carrier_of(load: DeleteriousLoad) -> List[AssignedDisease]:
    """Diseases carried heterozygous -- silent, but transmissible."""
    dosage = load.dosage[PANEL_LOCI]
    return [d for d, g in zip(DISEASES, dosage) if g == 1]


# ======================================================================
# 4. Closed forms the validation harness checks against
# ======================================================================

def expected_affected_count(F: float,
                            diseases: Optional[Tuple[AssignedDisease, ...]] = None
                            ) -> float:
    """
    E[number of panel diseases an individual with inbreeding F expresses]:

        sum_j (q_j^2 + F p_j q_j)

    from the inbred genotype frequencies P(aa) = q^2 + Fpq (Wright 1922;
    Crow & Kimura 1970 ch. 3). EXACTLY linear in F -- no approximation --
    which is what makes the regression in validation [9d] a clean test.
    Uses the ENGINE's frequencies (the matched loci), because those are
    what the simulated genotypes actually segregate at.
    """
    ds = DISEASES if diseases is None else diseases
    q = np.array([d.q for d in ds])
    return float(np.sum(q ** 2 + F * (1.0 - q) * q))


def expected_carrier_share(diseases: Optional[Tuple[AssignedDisease, ...]] = None
                           ) -> float:
    """
    P(an outbred individual carries >= 1 panel allele heterozygous):
    1 - prod_j (1 - 2 p_j q_j). About 1 in 6 for this nine-disease panel --
    the same order as expanded carrier screening finds per-disease
    (Lazarin 2013 reports ~24% carrying >= 1 of 108 disorders; a 9-disease
    panel of course catches fewer).
    """
    ds = DISEASES if diseases is None else diseases
    q = np.array([d.q for d in ds])
    return float(1.0 - np.prod(1.0 - 2.0 * (1.0 - q) * q))


def relative_risk(F: float) -> float:
    """
    Affected-rate ratio, inbred vs outbred:  1 + F * sum(pq) / sum(q^2).

    For rare recessives this is LARGE -- ~7 at first-cousin F for this
    panel -- which reproduces the epidemiological signature that
    consanguinity multiplies rare-recessive incidence many-fold while
    barely moving common-disease risk (Modell & Darr 2002). The engine's
    common-variant traits move by F * sum 2pq d (small); its rare
    recessives move by this factor (large). Same F, two very different
    responses, both now visible.
    """
    return expected_affected_count(F) / expected_affected_count(0.0)


def panel_summary() -> str:
    """One line per disease: engine vs literature, deviations in the open."""
    lines = [f"{'disease':<38}{'gene':<10}{'lit q':>8}{'engine q':>10}"
             f"{'x':>6}{'lit s':>7}{'engine s':>10}{'x':>6}"]
    for d in DISEASES:
        lines.append(
            f"{d.label:<38}{d.spec.gene:<10}{d.spec.q_lit:>8.4f}{d.q:>10.4f}"
            f"{d.q_ratio:>6.2f}{d.spec.s_lit:>7.2f}{d.s:>10.3f}"
            f"{d.s_ratio:>6.2f}")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Limitations
# ----------------------------------------------------------------------
# * A disease's engine frequency is its matched locus's q, not the
#   literature value. Deviations are printed by `panel_summary` and
#   asserted bounded by tests; CF is the documented outlier (see docstring).
# * One locus per disease. Real disorders are allelically heterogeneous
#   (>2000 CFTR alleles); here a disease is one biallelic site, which is
#   the same simplification the whole load layer makes.
# * No compound heterozygotes, no genotype-phenotype severity spectrum
#   within a disease: severity IS the locus's s, identical for every
#   affected individual.
# * `restricted_actions` mirrors medical.py's contract with the Action
#   Engine but is currently a read-out; nothing in the simulation layer
#   consumes it (the same status as medical.py's own action lists).
# * Carrier frequencies are single-population (broadly N. European where
#   the literature is); real carrier rates are strongly ancestry-dependent
#   and this engine has one panmictic founding population.
# * The panel is INDEPENDENT of EXTNPC_CATALOGUE. It is assigned from the
#   load spectrum, which carries its own mutation-selection-balance
#   frequencies and never reads loci.ALT_FREQ, so switching to the
#   empirical catalogue moves trait loci and leaves every disease exactly
#   where it was.
# * Named diagnoses are RARE by construction -- E[affected] ~ 1 in 1000
#   births at F = 0 -- so a village of ~60 usually contains none, and the
#   carrier read-out (~1 in 6) is the part that is visibly populated. That
#   is the correct epidemiology of rare recessives, not an empty panel.
