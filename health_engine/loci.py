"""
Locus catalogue: the reference "genome" this simulator uses.
============================================================

Roadmap items #5 (facial morphology loci), #6 (hair morphology loci),
#7 (pleiotropy), #11 (organ-function loci), #29 (allele frequencies for
founder sampling).

Structure
---------
Two classes of locus, mirroring the omnigenic framing of Boyle, Li &
Pritchard 2017 (Cell 169:1177):

  CORE   ~50 named genes with real chromosomal positions and hand-curated
         trait weights taken from the GWAS literature. These are the
         "core genes" of the omnigenic model -- direct, mechanistic,
         relatively large effects.

  PERIPHERAL  ~450 anonymous biallelic SNPs at random genomic positions,
         each with a small effect on a random subset of traits. These
         stand in for the vast diffuse background that actually carries
         most of the heritability of complex traits.

Every locus is biallelic: allele 0 = reference, allele 1 = alternate.
`alt_freq` is the population frequency of allele 1, used to initialise
founders under Hardy-Weinberg proportions (item #29).

Pleiotropy is expressed simply by a gene naming more than one trait in
its `weights` dict. EDAR is the canonical case (roadmap #7).

CAVEATS (roadmap Section 5 -- these are load-bearing)
-----------------------------------------------------
* Effect sizes here are *plausible relative magnitudes*, not published
  betas. Real GWAS betas are trait-scale- and cohort-specific; we
  rescale everything during heritability calibration (traits.py) anyway,
  so only the relative ordering within a trait carries meaning.
* Allele frequencies are broadly "global average" values. They are NOT
  ancestry-specific. GWAS effect sizes and polygenic scores transfer
  poorly across ancestries (height PGS ~40% variance in Europeans vs
  ~10-20% elsewhere) -- see `ancestry.py` gap noted in REPORT.md.
* EDAR's pleiotropy is partly rodent knock-in evidence (Kamberov et al.
  2013, Cell 152:691). Human associations for hair thickness, incisor
  shovelling, ear morphology and chin protrusion are robust; sweat-gland
  density is strongly supported mechanistically but effect magnitudes
  vary by cohort.
* COMT / OXTR / NR3C1 carry deliberately TINY behavioural weights. The
  candidate-gene era of behaviour genetics (5-HTTLPR, COMT, MAOA)
  largely failed to replicate at scale (Border et al. 2019, Am. J.
  Psychiatry 176:376). They are included for narrative colour, weighted
  so they cannot dominate anything. Do not read them as causal switches.
* Gene-disease associations below (FTO, TCF7L2, GJB2, APOE, ...) are
  population-level statistical findings. They are not diagnostics and
  must never be presented as such.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from .genetic_map import AUTOSOMES, AUTOSOME_NUMBERS

# The catalogue is a fixed reference, not per-run randomness. Peripheral
# loci are generated once from this seed so that every run of the
# simulator sees the same "species".
CATALOG_SEED = 20240501

N_PERIPHERAL_LOCI = 450

# ----------------------------------------------------------------------
# Catalogue mode (session 16): synthetic (default) vs empirical
# ----------------------------------------------------------------------
# *** EMPIRICAL MODE IS EXPERIMENTAL AND NOT VALIDATED. DO NOT USE IT TO
# *** PRODUCE RESULTS. It fails 6 tests that the default passes, and at
# *** least one trait is genuinely miscalibrated under it -- see
# *** "KNOWN FAILURES" below. The DEFAULT (synthetic) catalogue is the
# *** validated one and is byte-identical to every committed figure.
#
# EXTNPC_CATALOGUE=empirical swaps the CORE genes' hand-set allele
# frequencies for measured 1000 Genomes phase 3 EUR values, fetched from
# Ensembl and VENDORED with retrieval date and per-allele provenance in
# data/empirical_core_frequencies.json. Read once at import, because the
# entire trait calibration (traits.py) is solved against these
# frequencies at import time -- a runtime switch would silently desync
# the calibrated architecture from the catalogue it was solved on.
#
# KNOWN FAILURES (measured 2026-08-07, full suite under the flag:
# 6 failed / 574 passed / 3 skipped, against 582 passed / 1 skipped on
# the default. It was 9 failed before three of my own tests were made
# mode-aware; those three assert the default catalogue and now skip):
#
#   * THE SHAPE OF THE GENOTYPIC DISTRIBUTION CHANGES QUALITATIVELY.
#     eye_color's genotypic kurtosis flips SIGN, -0.771 -> +0.978. At an
#     intermediate frequency a major locus splits the population into
#     comparable genotype classes and the distribution is bimodal
#     (platykurtic); at an extreme frequency the SAME locus with the SAME
#     effect leaves almost everyone in one class with a rare tail, and the
#     distribution becomes peaked (leptokurtic). This matters here because
#     the engine deliberately uses empirical quantiles rather than
#     norm.ppf for categorical thresholds precisely because of that
#     non-normality.
#   * Variance REDISTRIBUTES sharply for concentrated traits. Effect sizes
#     are untouched; only 2pq moves. SLC24A5 keeps its -1.80 weight and
#     loses 98.7% of its variance contribution (2pq 0.455 -> 0.006);
#     EDAR loses 95%, GJB2 88%. See catalogue_compare.py for the table.
#   * Three test_traits.py laws that assert the SYNTHETIC architecture's
#     shape (bimodality from a major locus, a dominant major gene making
#     selection response undershoot, GxE tails) fail as a direct and
#     CORRECT consequence -- the architecture really has changed.
#   * A neuroticism breeder's-equation overshoot at ~6.5 sigma
#     (predicted R = 0.557, observed 0.650, se 0.014). Neuroticism's own
#     additive variance is unchanged, so this one is NOT yet explained and
#     is the loose end most worth pulling.
#   * Two dashboard fixtures drift -- different genomes mean that world
#     has no consanguineous birth, so the stature-cost rows have nothing
#     to render. An artefact of the fixture, not an engine fault.
#
# NOT established, and previously overclaimed here: that any trait's
# HERITABILITY is miscalibrated. `analytic_heritability` returns its
# declared target under both catalogues -- but that is a closed form which
# returns the target by construction, so it is evidence of nothing either
# way. Whether the realised h2 still matches is an open question and needs
# a midparent-offspring regression run under the flag.
#
# The fix is NOT to widen a tolerance. A trait whose major locus is near
# fixation in the chosen population needs its architecture rethought for
# that population -- which is the real scientific content of grounding a
# catalogue in data, and is deliberately left as open work rather than
# papered over.
#
# Scope, stated honestly:
#   * 21 of 53 core genes carry empirical frequencies -- the ones whose
#     canonical GWAS SNP and effect-allele orientation are unambiguous
#     (each row's rationale is in the JSON). The rest keep their
#     synthetic values; coverage is queryable via EMPIRICAL_OVERRIDES.
#   * Peripheral loci are IDENTICAL in both modes. Their uniform-MAF
#     spectrum already models an ascertained common-variant panel (see
#     _sample_peripheral_allele_freq), and no real per-SNP identity
#     exists to ground them in.
#   * EUR was chosen over the global average because the engine is a
#     single panmictic population and the Mendelian disease panel
#     (diseases.py) is calibrated to N.-European carrier frequencies;
#     mixing reference populations across layers would be worse than
#     naming one.
#   * The two modes are DIFFERENT MODEL VERSIONS: every founder genome,
#     calibrated trait scale and committed figure belongs to the
#     synthetic catalogue unless stated. World saves record the mode and
#     refuse to load across it (worldsave.py).
#
# Notable consequences of the empirical values, all real biology:
#   SLC24A5 at 0.997 -- the light-skin allele is at fixation in EUR, so
#   the largest-effect pigmentation locus contributes almost no VARIANCE
#   (fixed differences are not polymorphisms). EDAR-370A at 0.011 -- the
#   catalogue's flagship pleiotropy is nearly invisible in an EUR-
#   frequency world, exactly as it is in real European cohorts. GJB2
#   35delG at 0.0089 -- carrier rate 1/56, matching the deafness
#   literature instead of the synthetic 0.08.
CATALOGUE_MODE: str = os.environ.get("EXTNPC_CATALOGUE", "synthetic").strip().lower()
if CATALOGUE_MODE not in ("synthetic", "empirical"):
    raise ValueError(
        f"EXTNPC_CATALOGUE={CATALOGUE_MODE!r}: must be 'synthetic' or 'empirical'")

_EMPIRICAL_PATH = os.path.join(os.path.dirname(__file__), "data",
                               "empirical_core_frequencies.json")


def _load_empirical() -> Dict[str, dict]:
    with open(_EMPIRICAL_PATH, encoding="utf-8") as fh:
        bundle = json.load(fh)
    return bundle["genes"]


# symbol -> vendored record, EMPTY in synthetic mode so that nothing
# downstream can accidentally read empirical values without the flag.
EMPIRICAL_OVERRIDES: Dict[str, dict] = (
    _load_empirical() if CATALOGUE_MODE == "empirical" else {})


@dataclass(frozen=True)
class Locus:
    """One biallelic site. allele 0 = reference, allele 1 = alternate."""
    index: int
    symbol: str
    chrom: int
    bp_mb: float
    cm: float
    alt_freq: float
    is_core: bool
    # trait -> raw additive weight, for the alternate allele
    weights: Dict[str, float] = field(default_factory=dict)
    # d/a ratio: 0 = purely additive, +1 = alt allele fully dominant,
    # -1 = alt allele fully recessive. Applied per trait uniformly.
    dominance_ratio: float = 0.0
    note: str = ""

    @property
    def ref_freq(self) -> float:
        return 1.0 - self.alt_freq

    @property
    def heterozygosity(self) -> float:
        """2pq -- the additive-genetic variance contributed per unit effect."""
        return 2.0 * self.alt_freq * (1.0 - self.alt_freq)


# ----------------------------------------------------------------------
# CORE GENES
# ----------------------------------------------------------------------
# (symbol, chrom, bp_Mb, alt_freq, dominance_ratio, {trait: weight}, note)
#
# Sign convention for ordered categorical traits: the label list runs
# low-liability -> high-liability, so a NEGATIVE weight pushes toward the
# first label. e.g. hearing_ability = ["reduced", "normal"], so the GJB2
# deafness allele has a negative weight.

_CORE_GENES = [
    # --- pigmentation -------------------------------------------------
    ("HERC2", 15, 28.1, 0.45, 0.95, {"eye_color": 2.2, "skin_tone": -0.30, "hair_pigment": -0.40},
     "rs12913832; regulates OCA2 expression. Near-Mendelian for blue eyes."),
    ("OCA2", 15, 28.2, 0.42, 0.60, {"eye_color": 1.0, "skin_tone": -0.40, "hair_pigment": -0.30},
     "Adjacent to HERC2 (~0.1 Mb) -> strong real LD; our map reproduces the linkage."),
    ("SLC24A5", 15, 48.1, 0.35, 0.20, {"skin_tone": -1.80},
     "rs1426654; one of the largest-effect pigmentation loci known."),
    ("SLC45A2", 5, 33.9, 0.30, 0.15, {"skin_tone": -1.20, "hair_pigment": -0.50}, ""),
    ("MC1R", 16, 89.9, 0.10, -0.80, {"hair_pigment": -1.00, "skin_tone": -0.50},
     "Loss-of-function variants are recessive -> red hair, fair skin."),
    ("ASIP", 20, 34.2, 0.25, 0.10, {"hair_pigment": -0.40, "skin_tone": -0.30}, ""),
    ("TYR", 11, 89.2, 0.28, 0.10, {"skin_tone": -0.40, "eye_color": 0.30}, ""),

    # --- EDAR: the roadmap's canonical pleiotropy example (#7) ---------
    ("EDAR", 2, 108.9, 0.35, 0.30,
     {"hair_thickness": 0.90, "incisor_shovelling": 1.10, "ear_protrusion": 0.45,
      "chin_protrusion": 0.40, "sweat_gland_density": 0.85},
     "rs3827760 (370A). ONE gene, FIVE traits spanning hair, dentition, "
     "craniofacial shape and an eccrine/thermoregulatory organ function. "
     "Kamberov 2013 (mouse knock-in) + Adhikari 2015/2016 (human GWAS). "
     "The sweat-gland arm is what lets EDAR reach behaviour: it feeds "
     "thermoregulatory capacity -> physiological state -> action bias, "
     "rather than a fictitious direct gene->behaviour weight."),

    # --- hair morphology (#6) -----------------------------------------
    ("TCHH", 1, 152.1, 0.25, 0.10, {"hair_curl": -1.10},
     "Trichohyalin; ~6% of hair-form variance in Europeans (Medland 2009)."),
    ("LCE3E", 1, 152.6, 0.30, 0.0, {"hair_curl": 0.20},
     "0.5 Mb from TCHH -> tightly linked; useful LD test case."),
    ("WNT10A", 2, 218.9, 0.35, 0.0, {"hair_curl": 0.30, "hair_thickness": 0.30}, ""),
    ("FRAS1", 4, 78.2, 0.40, 0.0, {"hair_curl": 0.25}, ""),
    ("GATA3", 10, 8.1, 0.45, 0.0, {"hair_curl": 0.20}, ""),
    ("PRSS53", 16, 31.1, 0.30, 0.0, {"hair_curl": 0.35, "hair_thickness": 0.20}, ""),

    # --- craniofacial morphology (#5) ---------------------------------
    ("RUNX2", 6, 45.3, 0.40, 0.0, {"nose_bridge_breadth": 0.80, "brow_ridge": 0.35, "height_cm": 0.15},
     "Adhikari 2016. Also an osteoblast master regulator -> height weight."),
    ("SUPT3H", 6, 44.8, 0.45, 0.0, {"nose_bridge_breadth": 0.35, "height_cm": 0.10},
     "0.5 Mb from RUNX2 -> real, strong LD (Claes 2018 hits this region)."),
    ("DCHS2", 4, 155.2, 0.38, 0.0, {"nose_pointiness": 0.90}, "Adhikari 2016."),
    ("GLI3", 7, 42.0, 0.42, 0.0, {"nose_width": 0.70}, "Adhikari 2016 (nostril breadth)."),
    ("PAX1", 20, 21.7, 0.35, 0.0, {"nose_width": 0.55}, "Adhikari 2016."),
    ("PAX3", 2, 222.2, 0.30, 0.0, {"nasion_position": 0.85, "nose_bridge_breadth": 0.30}, ""),
    ("SOX9", 17, 70.1, 0.33, 0.0,
     {"chin_protrusion": 0.40, "nose_pointiness": 0.30, "cheekbone_prominence": 0.30},
     "Claes 2018."),
    ("TBX15", 1, 119.4, 0.40, 0.0, {"cheekbone_prominence": 0.50, "adiposity": 0.25},
     "Pleiotropic: craniofacial shape AND body-fat distribution."),
    ("PKDCC", 2, 42.2, 0.36, 0.0, {"nose_width": 0.30, "height_cm": 0.12}, "Claes 2018."),

    # --- stature (#10 calibration anchors) -----------------------------
    ("HMGA2", 12, 65.8, 0.48, 0.0, {"height_cm": 0.50}, "One of the first replicated height loci."),
    ("GDF5", 20, 35.4, 0.30, 0.0, {"height_cm": 0.35}, ""),
    ("ACAN", 15, 88.8, 0.42, 0.0, {"height_cm": 0.40}, ""),
    ("ZBTB38", 3, 141.5, 0.45, 0.0, {"height_cm": 0.30}, ""),
    ("IGF1", 12, 102.4, 0.38, 0.0, {"height_cm": 0.25, "adiposity": 0.10}, ""),
    ("IGF2", 11, 2.1, 0.40, 0.0, {"height_cm": 0.20, "adiposity": 0.15},
     "IMPRINTED (paternally expressed; DeChiara 1991) -- roadmap #4, "
     "implemented in imprint.py: the maternal copy is silenced, so reciprocal "
     "heterozygotes differ by 2*s*a. Also the Dutch Hunger Winter methylation "
     "locus (Heijmans 2008), roadmap #19; famine exposure is a partial LOSS of "
     "imprinting, see imprint.relax_imprint()."),

    # --- metabolic / organ function (#11) ------------------------------
    ("FTO", 16, 53.8, 0.42, 0.0, {"adiposity": 0.60, "bmi": 0.60, "insulin_sensitivity": -0.20},
     "Frayling 2007. Largest common-variant adiposity locus."),
    ("MC4R", 18, 60.4, 0.25, 0.0, {"adiposity": 0.45, "bmi": 0.45}, "Loos 2008."),
    ("PPARG", 3, 12.3, 0.85, 0.0,
     {"insulin_sensitivity": 0.35, "adiposity": 0.20, "lipid_profile": 0.20}, ""),
    ("TCF7L2", 10, 112.9, 0.28, 0.0, {"insulin_sensitivity": -0.75},
     "Grant 2006. Strongest common T2D locus. Population-level statistic, "
     "NOT a diagnostic."),
    ("FADS1", 11, 61.8, 0.65, 0.0, {"lipid_profile": 0.50, "inflammation_tone": 0.15}, ""),
    ("APOE", 19, 44.9, 0.15, 0.0, {"lipid_profile": -0.80, "inflammation_tone": 0.20}, ""),
    ("LDLR", 19, 11.1, 0.22, 0.0, {"lipid_profile": -0.60}, ""),
    ("PCSK9", 1, 55.0, 0.18, 0.0, {"lipid_profile": -0.50}, ""),
    ("NOS3", 7, 150.9, 0.35, 0.0, {"bp_set_point": -0.50, "aerobic_capacity": 0.20}, ""),
    ("AGT", 1, 230.7, 0.40, 0.0, {"bp_set_point": 0.60}, "Evangelou 2018 BP GWAS region."),
    ("ADRB2", 5, 148.8, 0.45, 0.0,
     {"lung_capacity": 0.40, "aerobic_capacity": 0.30, "bp_set_point": -0.15}, ""),
    ("LCT", 2, 136.5, 0.30, 0.90, {"adiposity": 0.05},
     "Lactase persistence. Near-neutral here; kept as a low-weight locus "
     "under strong linkage for drift/selection tests."),

    # --- immune / inflammation -----------------------------------------
    ("HLA_DRB1", 6, 32.6, 0.30, 0.0,
     {"immune_reactivity": 0.90, "immune_resilience": 0.80, "inflammation_tone": 0.30}, ""),
    ("IL6", 7, 22.7, 0.40, 0.0,
     {"inflammation_tone": 0.70, "immune_reactivity": 0.30,
      "chronic_illness_predisposition": -0.30},
     "Pro-inflammatory cytokine; the sickness-behaviour pathway (#27) "
     "will read inflammation_tone."),
    ("CRP", 1, 159.7, 0.35, 0.0,
     {"inflammation_tone": 0.60, "chronic_illness_predisposition": -0.25}, ""),
    ("AHRR", 5, 0.4, 0.45, 0.0, {"inflammation_tone": 0.15, "lung_capacity": -0.10},
     "cg05575921 sits here: the most robust smoking-methylation signal "
     "known, partially reversible on cessation (Philibert 2016). "
     "Target locus for roadmap #18."),

    # --- sensory -------------------------------------------------------
    ("GJB2", 13, 20.2, 0.08, -1.00, {"hearing_ability": -1.40},
     "Connexin 26. Recessive (dominance_ratio -1): carriers hear normally."),
    ("MYO7A", 11, 77.1, 0.12, -0.70, {"hearing_ability": -0.70}, ""),
    ("GJD2", 15, 34.7, 0.45, 0.0, {"vision_acuity": -0.90}, "Replicated myopia locus."),
    ("RASGRF1", 15, 78.9, 0.40, 0.0, {"vision_acuity": -0.60}, ""),

    # --- circadian (#26) ------------------------------------------------
    ("CLOCK", 4, 55.4, 0.35, 0.0, {"chronotype": 0.40}, ""),
    ("PER3", 1, 7.8, 0.40, 0.0, {"chronotype": 0.60}, "Jones 2019: 351 chronotype loci."),
    ("ARNTL", 11, 13.3, 0.42, 0.0, {"chronotype": 0.45}, "BMAL1."),

    # --- behaviour: deliberately negligible weights ---------------------
    ("NR3C1", 5, 143.3, 0.30, 0.0, {"neuroticism": 0.10, "inflammation_tone": 0.10},
     "Glucocorticoid receptor. Weaver 2004 maternal-care GR-promoter "
     "methylation is RAT data -- suggestive, not proven in humans. "
     "Target locus for roadmap #18/#19."),
    ("COMT", 22, 19.9, 0.48, 0.0, {"conscientiousness": 0.05, "neuroticism": 0.05},
     "Val158Met. Candidate-gene claims did NOT replicate (Border 2019). "
     "Weight kept negligible on purpose."),
    ("OXTR", 3, 8.7, 0.40, 0.0, {"agreeableness": 0.06, "extraversion": 0.05},
     "Same caveat as COMT."),
]


# ----------------------------------------------------------------------
# PERIPHERAL LOCI
# ----------------------------------------------------------------------
# How many peripheral loci contribute to each trait, and how big their
# effects are relative to core genes. This is the single most important
# knob for reproducing the empirical fact that behavioural traits have
# substantial heritability but flat, diffuse genetic architecture, while
# pigmentation has a handful of large-effect genes.
#
# `PERIPHERAL_EFFECT_SD` is small (0.15) versus core weights (0.3-2.2):
# a typical peripheral locus is ~1/5th the effect of the weakest core gene.
#
# `PERIPHERAL_EFFECT_SHAPE` is the second, subtler knob: the *dispersion*
# of peripheral effect sizes, as the sigma of a lognormal magnitude.
#
#   shape ~ 0.8  heavy-tailed. Most loci are negligible, a few are 5-10x
#                the median. Realistic for stature, adiposity, lipids --
#                traits where GWAS finds a leading edge of larger hits.
#   shape ~ 0.25 nearly uniform magnitudes, random signs. This is what
#                behavioural-trait GWAS actually looks like: no locus
#                stands out, the largest effect explains <0.1% of
#                variance, and the signal is spread across the genome.
#
# Without this knob, drawing peripheral weights from N(0, 0.15) gives
# openness a locus explaining ~5% of its additive variance, which would
# be by far the largest personality-associated effect ever reported. The
# candidate-gene literature that claimed such effects did not replicate
# (Border et al. 2019). tests/test_traits.py enforces the <2% ceiling.

PERIPHERAL_EFFECT_SD = 0.15
DEFAULT_EFFECT_SHAPE = 0.80

PERIPHERAL_EFFECT_SHAPE: Dict[str, float] = {
    "openness": 0.25, "conscientiousness": 0.25, "extraversion": 0.25,
    "agreeableness": 0.25, "neuroticism": 0.25,
    "interoceptive_accuracy": 0.35,
    "handedness": 0.35,
    "chronotype": 0.40,
    "chronic_illness_predisposition": 0.50,
}

# trait -> number of peripheral loci contributing
PERIPHERAL_LOCUS_COUNT: Dict[str, int] = {
    # near-Mendelian pigmentation: very few background modifiers
    "eye_color": 15,
    "skin_tone": 25,
    "hair_pigment": 30,
    "hair_curl": 30,
    "hair_thickness": 40,
    # craniofacial: moderately polygenic
    "nose_width": 60, "nose_pointiness": 60, "nose_bridge_breadth": 60,
    "nasion_position": 60, "chin_protrusion": 70, "cheekbone_prominence": 70,
    "brow_ridge": 60, "lip_fullness": 80, "ear_protrusion": 60, "eye_size": 70,
    "incisor_shovelling": 40, "sweat_gland_density": 50,
    # stature & metabolism: highly polygenic
    "height_cm": 300, "bmi": 250, "adiposity": 200,
    "insulin_sensitivity": 150, "lipid_profile": 100, "bp_set_point": 180,
    "lung_capacity": 80, "aerobic_capacity": 100,
    "immune_reactivity": 100, "inflammation_tone": 100,
    "immune_resilience": 100, "vision_acuity": 120, "hearing_ability": 40,
    "chronic_illness_predisposition": 150,
    "chronotype": 200,
    "handedness": 120,
    "interoceptive_accuracy": 250,
    # behaviour: essentially omnigenic -- nearly every locus, all tiny
    "openness": 400, "conscientiousness": 400, "extraversion": 400,
    "agreeableness": 400, "neuroticism": 400,

    # --- APPENDED AFTER THE CATALOGUE WAS FROZEN ---------------------------
    # Must stay last, and must stay in the same order as the matching block at
    # the foot of `traits.TRAIT_TABLE`. This dict is walked in insertion order
    # with ONE generator, so a trait inserted above re-rolls which peripheral
    # loci every trait below it draws, and the symptom is every committed
    # figure changing for no reason anybody can name.
    #
    # 200, the same order as height_cm's 300 and bmi's 250: SHR is polygenic
    # and stature-like, but Chan 2015's point is that it is a NARROWER axis
    # than height, with a smaller share of the genome behind it.
    "sitting_height_ratio": 200,
    # 180, just under adiposity's 200. Body composition is polygenic in the
    # same way adiposity is, and deliberately not given MORE loci than the
    # trait it is splitting apart: `lean_mass_fraction` is a refinement of
    # what `bmi` and `adiposity` already describe, not a broader signal.
    "lean_mass_fraction": 180,
    # 220. Developmental stability is thought to be broadly polygenic rather
    # than to sit on a few named genes, which is consistent with how badly it
    # maps: no locus is a candidate here, so every contributing locus is a
    # peripheral one and there is no core gene to anchor it.
    "developmental_instability": 220,
}


def _sample_peripheral_allele_freq(rng: np.random.Generator, n: int) -> np.ndarray:
    """
    Common-variant frequency spectrum. Real GWAS arrays ascertain common
    SNPs, so MAF is roughly uniform on [0.05, 0.5]; we then randomly
    orient which allele is "alternate", giving alt_freq on
    [0.05, 0.5] U [0.5, 0.95].

    (The true site frequency spectrum under neutrality is ~1/x, i.e.
    dominated by rare variants. We deliberately model the *ascertained*
    common-variant set, not the full SFS.)
    """
    maf = rng.uniform(0.05, 0.5, size=n)
    flip = rng.random(n) < 0.5
    return np.where(flip, 1.0 - maf, maf)


def _build_catalog() -> List[Locus]:
    rng = np.random.default_rng(CATALOG_SEED)
    entries: List[Locus] = []

    # -- core genes ----------------------------------------------------
    for symbol, chrom, bp_mb, alt_freq, dom, weights, note in _CORE_GENES:
        # Empirical mode: replace the hand-set frequency with the vendored
        # 1000G EUR value where one exists. The override touches ONLY
        # alt_freq -- weights, dominance and position are the same model
        # in both modes -- and the peripheral rng stream below is never
        # consulted here, so peripheral loci are bit-identical across
        # modes.
        if symbol in EMPIRICAL_OVERRIDES:
            rec = EMPIRICAL_OVERRIDES[symbol]
            alt_freq = float(rec["eur_freq"])
            note = (note + " | " if note else "") + (
                f"empirical: {rec['rsid']} {rec['effect_allele']} "
                f"EUR {rec['eur_freq']:.4f} (1000G ph3 via Ensembl)")
        entries.append(Locus(
            index=-1, symbol=symbol, chrom=chrom, bp_mb=bp_mb,
            cm=AUTOSOMES[chrom].bp_to_cm(bp_mb),
            alt_freq=alt_freq, is_core=True, weights=dict(weights),
            dominance_ratio=dom, note=note,
        ))

    # -- peripheral loci -----------------------------------------------
    # Position them by sampling a chromosome in proportion to its
    # physical length, then a uniform position along it.
    chrom_weights = np.array([AUTOSOMES[c].bp_length_mb for c in AUTOSOME_NUMBERS])
    chrom_weights = chrom_weights / chrom_weights.sum()
    chroms = rng.choice(AUTOSOME_NUMBERS, size=N_PERIPHERAL_LOCI, p=chrom_weights)
    freqs = _sample_peripheral_allele_freq(rng, N_PERIPHERAL_LOCI)

    peripheral: List[Locus] = []
    for i in range(N_PERIPHERAL_LOCI):
        c = int(chroms[i])
        bp = float(rng.uniform(0.0, AUTOSOMES[c].bp_length_mb))
        peripheral.append(Locus(
            index=-1, symbol=f"bg{i:03d}", chrom=c, bp_mb=bp,
            cm=AUTOSOMES[c].bp_to_cm(bp), alt_freq=float(freqs[i]),
            is_core=False, weights={},
            # Mild, random directional dominance in the background.
            dominance_ratio=float(rng.normal(0.0, 0.15)),
        ))

    # Assign each trait its quota of peripheral loci. A locus picked by
    # several traits becomes pleiotropic "for free" -- which is exactly
    # what the omnigenic model predicts for the background.
    for trait, count in PERIPHERAL_LOCUS_COUNT.items():
        count = min(count, N_PERIPHERAL_LOCI)
        chosen = rng.choice(N_PERIPHERAL_LOCI, size=count, replace=False)
        shape = PERIPHERAL_EFFECT_SHAPE.get(trait, DEFAULT_EFFECT_SHAPE)
        # Lognormal magnitude, random sign. The -shape^2/2 recentring keeps
        # the mean magnitude at PERIPHERAL_EFFECT_SD whatever the shape, so
        # the two knobs stay independent.
        magnitude = PERIPHERAL_EFFECT_SD * rng.lognormal(-0.5 * shape ** 2, shape, count)
        sign = rng.choice([-1.0, 1.0], size=count)
        effects = magnitude * sign
        for k, j in enumerate(chosen):
            peripheral[int(j)].weights[trait] = float(effects[k])

    entries.extend(peripheral)

    # -- order the genome: by chromosome, then physical position --------
    entries.sort(key=lambda L: (L.chrom, L.bp_mb))
    return [
        Locus(index=i, symbol=L.symbol, chrom=L.chrom, bp_mb=L.bp_mb, cm=L.cm,
              alt_freq=L.alt_freq, is_core=L.is_core, weights=L.weights,
              dominance_ratio=L.dominance_ratio, note=L.note)
        for i, L in enumerate(entries)
    ]


LOCI: List[Locus] = _build_catalog()
N_LOCI: int = len(LOCI)

LOCUS_BY_SYMBOL: Dict[str, Locus] = {L.symbol: L for L in LOCI}
CORE_SYMBOLS: List[str] = [L.symbol for L in LOCI if L.is_core]

# Vectorised views used everywhere downstream.
ALT_FREQ: np.ndarray = np.array([L.alt_freq for L in LOCI])            # (L,)
HETEROZYGOSITY: np.ndarray = 2.0 * ALT_FREQ * (1.0 - ALT_FREQ)         # (L,) = 2pq
CHROM: np.ndarray = np.array([L.chrom for L in LOCI], dtype=np.int16)  # (L,)
CM_POS: np.ndarray = np.array([L.cm for L in LOCI])                    # (L,)
DOMINANCE_RATIO: np.ndarray = np.array([L.dominance_ratio for L in LOCI])

# Locus indices grouped by chromosome, each already sorted by cM.
LOCI_BY_CHROM: Dict[int, np.ndarray] = {
    c: np.flatnonzero(CHROM == c) for c in AUTOSOME_NUMBERS
}


def locus_index(symbol: str) -> int:
    return LOCUS_BY_SYMBOL[symbol].index


def describe(symbol: str) -> str:
    L = LOCUS_BY_SYMBOL[symbol]
    traits = ", ".join(f"{t}{w:+.2f}" for t, w in sorted(L.weights.items()))
    head = f"{L.symbol}  chr{L.chrom}:{L.bp_mb:.1f}Mb ({L.cm:.1f} cM)  alt_freq={L.alt_freq:.2f}"
    body = f"  -> {traits}" if traits else "  -> (no trait weights)"
    tail = f"\n  {L.note}" if L.note else ""
    return head + "\n" + body + tail


def pleiotropic_genes(min_traits: int = 3) -> List[Locus]:
    """Core genes touching >= min_traits traits. EDAR should top this list."""
    hits = [L for L in LOCI if L.is_core and len(L.weights) >= min_traits]
    return sorted(hits, key=lambda L: -len(L.weights))
