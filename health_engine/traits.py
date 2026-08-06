"""
Genotype -> phenotype: quantitative-genetics decomposition + pleiotropy.
=======================================================================

Roadmap items #7 (pleiotropy as a gene x trait matrix), #9 (proper
additive / dominance / epistasis / environment / GxE decomposition),
#10 (calibrated heritabilities), #14 (reaction norm), plus the liability
-threshold treatment of discrete traits.

The model
---------
For an individual, each trait's standardised *liability* is

    z  =  G  +  I  +  GxE  +  E
          |     |     |       |
          |     |     |       +-- environmental residual, N(0, V_E)
          |     |     +---------- genotype x environment interaction
          |     +---------------- pairwise epistatic deviations
          +---------------------- genotypic value = additive + dominance

with G built locus-by-locus in Fisher/Falconer notation:

    genotype:   aa (0 alt)   Aa (1 alt)   AA (2 alt)
    value:        -a_j          d_j          +a_j

Under Hardy-Weinberg with alternate-allele frequency p (q = 1-p) the
variance of G decomposes *exactly* and orthogonally (Fisher 1918;
Falconer & Mackay 1996, ch. 7-8):

    alpha_j = a_j + d_j (q_j - p_j)            average effect of substitution
    V_A     = sum_j  2 p_j q_j alpha_j^2       additive genetic variance
    V_D     = sum_j (2 p_j q_j d_j)^2          dominance variance

Because these are closed forms, we do not tune effect sizes until a test
passes -- we *solve* for the scaling that puts V_A exactly at the target
narrow-sense heritability. See `_calibrate_trait`.

Directional dominance
---------------------
The d_j above have signs, and the signs are the whole difference between a
trait that shows inbreeding depression and one that does not. Falconer &
Mackay 1996 eq. 15.1:

    M_F  =  M_0  -  2F sum_j p_j q_j d_j

so depression is driven by the PLAIN sum of the 2pq d, while V_D is their
sum of SQUARES. Draw the signs at random -- which is what `loci.py` does
for peripheral loci, N(0, 0.15) -- and the plain sum cancels to a random
walk about zero while the sum of squares is whatever V_D was asked for.
The result, which this engine shipped for eleven sessions, is dominance
variance with no inbreeding depression on any trait.

Traits with a measured depression therefore set `depression_per_10F`
instead of `v_dom`: dominance is signed toward the trait-increasing allele
at every peripheral locus and scaled so the catalogue reproduces the
published slope, and **V_D becomes an output of calibration**. V_A is
still solved to h^2 exactly afterwards, and mean_g still absorbs
sum 2pq d, so the outbred founder mean does not move -- only inbred
individuals do. Which traits get a target is a claim about the
literature, not a modelling convenience: see height_cm and lung_capacity
for the positives and bmi, adiposity, bp_set_point and lipid_profile for
Joshi et al. 2015's nulls, reproduced deliberately.

Every trait is calibrated so that V_P = V_A + V_D + V_I + V_GxE + V_E = 1.
Liabilities are therefore standard normal in a random-mating founder
population, which makes two things trivial:

  * continuous traits:   value = mean + sd * z
  * categorical traits:  cut z at the normal quantiles of the target
                         prevalences (Falconer 1965 liability-threshold
                         model). "brown eyes" is not a Mendelian label
                         any more; it is a region of a polygenic
                         liability that HERC2 happens to dominate.

Why this replaces SBX
---------------------
Simulated Binary Crossover interpolates a child's *phenotype* between its
parents' phenotypes. Real inheritance transmits alleles; the phenotype
lands where the transmitted alleles and a fresh environmental draw put
it. SBX cannot produce regression to the mean, cannot produce sibling
variance from identical parents, and cannot be calibrated to a
heritability. All three now emerge. `legacy.py` keeps SBX for comparison.

CAVEATS
-------
* Heritabilities below are twin/pedigree h^2 estimates. They are NOT the
  variance explained by a polygenic score. Those are different numbers
  and the gap is the whole story of modern complex-trait genetics:
  height h^2 ~ 0.8 but the best PGS reaches ~0.4 (Yengo 2022, N=5.4M);
  neuroticism h^2 ~ 0.4 but its PGS reaches ~0.02-0.03 (Okbay 2022).
  `target_pgs_r2` records the literature PGS figure for documentation and
  for `validation.simulated_gwas_pgs_r2` to be interpreted against.
* Our genome has 500 loci. Real complex traits draw on an effective
  ~50,000 independent segments. Absolute PGS R^2 in this simulator is
  therefore NOT comparable to published values -- only the *ordering*
  (pigmentation >> stature >> personality) is meaningful.
* Behavioural h^2 is set to ~0.40 (twin-study consensus) but distributed
  across 400 tiny peripheral loci with no core gene. Do not build
  deterministic gene->personality pipelines on top of this.
* Epistasis is limited to pairwise products of centred dosages. Real
  epistasis is higher-order and largely unmapped. A side effect worth
  knowing: pairwise additive-by-additive variance V_AA inflates the
  midparent-offspring regression slope to h^2 + V_AA/(2 V_P). With the
  defaults below that bias is ~ +0.01, inside the roadmap's +/-0.05
  benchmark. `validation.py` accounts for it explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.stats import norm

if TYPE_CHECKING:                      # avoids an import cycle at runtime
    from .imprint import ImprintState

from .loci import ALT_FREQ, DOMINANCE_RATIO, LOCI, N_LOCI

# Seed for the epistatic-pair draw. Part of the fixed reference "species",
# like the locus catalogue, not per-run randomness.
GP_MAP_SEED = 20240502

EPISTATIC_PAIRS_PER_TRAIT = 8


class TraitKind(Enum):
    CONTINUOUS = "continuous"
    CATEGORICAL = "categorical"     # liability-threshold


@dataclass(frozen=True)
class TraitSpec:
    name: str
    kind: TraitKind
    h2: float                       # narrow-sense: V_A / V_P
    mean: float = 0.0               # phenotypic mean (continuous only)
    sd: float = 1.0                 # phenotypic sd (continuous only)
    unit: str = ""
    # Variance shares, all as fractions of V_P = 1.
    #
    # `v_dom` is the DECLARED dominance variance share. Set it to None and
    # give `depression_per_10F` instead to calibrate dominance against a
    # measured inbreeding depression, in which case V_D becomes an output of
    # calibration rather than an input. Exactly one of the two is required.
    v_dom: Optional[float] = 0.05
    v_epi: float = 0.02
    v_gxe: float = 0.03
    # Directional dominance (roadmap: the trait-scale counterpart of the
    # load layer's lethal equivalents). The measured drop in this trait per
    # 0.10 of F, in the trait's own `unit`. POSITIVE means inbreeding makes
    # the trait SMALLER. None -- the default -- means no directional
    # dominance, which for several traits below is a reproduced null result
    # rather than an omission; see their notes.
    depression_per_10F: Optional[float] = None
    depression_source: str = ""
    # Categorical only: labels ordered LOW liability -> HIGH liability,
    # with the population prevalence of each.
    labels: Optional[Tuple[str, ...]] = None
    prevalences: Optional[Tuple[float, ...]] = None
    clip: Optional[Tuple[float, float]] = None
    target_pgs_r2: Optional[float] = None   # literature value, documentation only
    note: str = ""

    @property
    def v_add(self) -> float:
        return self.h2

    def residual_variance(self, v_dom: float) -> float:
        """V_E given a dominance share, so that V_P = 1 exactly."""
        return 1.0 - (self.h2 + v_dom + self.v_epi + self.v_gxe)

    @property
    def v_env(self) -> float:
        """Residual share implied by the DECLARED v_dom. Undefined for a
        directional trait, whose V_D is not known until it is calibrated."""
        if self.v_dom is None:
            raise ValueError(
                f"trait {self.name}: v_env is undefined for a directional trait; "
                "use residual_variance(realised V_D)"
            )
        return self.residual_variance(self.v_dom)

    @property
    def is_directional(self) -> bool:
        return self.depression_per_10F is not None

    def target_dominance_sum(self) -> float:
        """
        sum_j 2 p_j q_j d_j required to reproduce `depression_per_10F`.

        Falconer & Mackay 1996 eq. 15.1: the mean of an inbred population is
        M_F = M_0 - 2F sum_j p_j q_j d_j, i.e. the depression is linear in F
        with slope sum_j 2 p_j q_j d_j on the LIABILITY scale. Dividing the
        measured drop by the trait's phenotypic sd converts it to that scale.
        """
        return (self.depression_per_10F / self.sd) / 0.10

    def validate(self) -> None:
        if self.is_directional:
            if self.v_dom is not None:
                raise ValueError(
                    f"trait {self.name}: declares both v_dom and "
                    "depression_per_10F. V_D is either an input or an output, "
                    "never both -- set v_dom=None."
                )
            if self.kind is not TraitKind.CONTINUOUS or self.sd <= 0.0:
                raise ValueError(
                    f"trait {self.name}: a depression target is expressed in the "
                    "trait's own units, so it needs a continuous scale with sd > 0"
                )
            if not self.depression_source:
                raise ValueError(
                    f"trait {self.name}: depression_per_10F without "
                    "depression_source is a tuned parameter, not a measurement"
                )
        elif self.v_dom is None:
            raise ValueError(f"trait {self.name}: needs v_dom or depression_per_10F")
        elif self.v_env <= 0.0:
            raise ValueError(
                f"trait {self.name}: variance shares exceed 1 "
                f"(h2={self.h2} + dom={self.v_dom} + epi={self.v_epi} + gxe={self.v_gxe})"
            )
        if self.kind is TraitKind.CATEGORICAL:
            if not self.labels or not self.prevalences:
                raise ValueError(f"trait {self.name}: categorical needs labels + prevalences")
            if len(self.labels) != len(self.prevalences):
                raise ValueError(f"trait {self.name}: labels/prevalences length mismatch")
            if abs(sum(self.prevalences) - 1.0) > 1e-9:
                raise ValueError(f"trait {self.name}: prevalences must sum to 1")


C = TraitKind.CONTINUOUS
K = TraitKind.CATEGORICAL

# ----------------------------------------------------------------------
# TRAIT TABLE
# ----------------------------------------------------------------------
# h^2 values are twin/pedigree consensus estimates. Sources noted inline.

TRAIT_TABLE: Dict[str, TraitSpec] = {t.name: t for t in [
    # --- stature & body -------------------------------------------------
    TraitSpec("height_cm", C, h2=0.80, mean=170.0, sd=9.0, unit="cm",
              target_pgs_r2=0.40, clip=(130.0, 215.0),
              v_dom=None, depression_per_10F=1.2,
              depression_source="Joshi et al. 2015, Nature 523:459",
              note="Twin h^2 ~0.8; Yengo 2022 PGS reaches ~40% in Europeans. "
                   "DIRECTIONAL DOMINANCE: stature is the best-measured human "
                   "inbreeding depression there is -- Joshi 2015 meta-analysed "
                   "35 cohorts (n~35,000) and found -1.2 cm per 10% F_ROH. V_D "
                   "is therefore an output here, and it comes out at ~1.4% of "
                   "V_P, which is an independent prediction: dominance variance "
                   "for height is estimated at essentially zero in family data "
                   "(Zhu et al. 2015, Nat. Genet. 47:1114). Nothing told the "
                   "model that."),
    TraitSpec("bmi", C, h2=0.75, mean=24.5, sd=4.0, unit="kg/m^2",
              target_pgs_r2=0.09, clip=(14.0, 45.0),
              note="NO directional dominance, on purpose. Joshi et al. 2015 "
                   "tested 16 traits and found inbreeding depression in only "
                   "four; BMI was among the nulls. Leaving it flat reproduces "
                   "the paper's negative result instead of assuming depression "
                   "wherever it sounds plausible."),
    TraitSpec("adiposity", C, h2=0.72, mean=0.0, sd=1.0, unit="z",
              note="Latent body-fat variable; feeds insulin sensitivity. "
                   "Non-directional for the same reason as bmi (Joshi 2015 "
                   "null on adiposity measures, incl. waist-hip ratio)."),

    # --- pigmentation ---------------------------------------------------
    TraitSpec("skin_tone", C, h2=0.85, v_dom=0.04, v_epi=0.01, v_gxe=0.02,
              mean=0.50, sd=0.18, unit="0=light..1=dark", clip=(0.0, 1.0),
              note="Few large-effect loci (SLC24A5, SLC45A2, HERC2/OCA2). "
                   "v_gxe is small but nonzero: UV exposure -> tanning."),
    TraitSpec("hair_pigment", C, h2=0.85, v_dom=0.05, v_epi=0.01, v_gxe=0.01,
              mean=0.60, sd=0.22, unit="0=light..1=dark", clip=(0.0, 1.0)),
    TraitSpec("hair_curl", C, h2=0.85, v_dom=0.04, v_epi=0.01, v_gxe=0.02,
              mean=0.40, sd=0.22, unit="0=straight..1=tight curl", clip=(0.0, 1.0),
              note="Medland 2009: TCHH ~6% of variance in Europeans."),
    TraitSpec("hair_thickness", C, h2=0.80, mean=0.50, sd=0.18, clip=(0.0, 1.0),
              note="EDAR 370A -> thick, straight shafts (Fujimoto 2008)."),

    # --- craniofacial (Adhikari 2016; Claes 2018) -------------------------
    TraitSpec("nose_width", C, h2=0.65, unit="z"),
    TraitSpec("nose_pointiness", C, h2=0.60, unit="z"),
    TraitSpec("nose_bridge_breadth", C, h2=0.65, unit="z"),
    TraitSpec("nasion_position", C, h2=0.60, unit="z"),
    TraitSpec("chin_protrusion", C, h2=0.55, unit="z"),
    TraitSpec("cheekbone_prominence", C, h2=0.60, unit="z"),
    TraitSpec("brow_ridge", C, h2=0.60, unit="z"),
    TraitSpec("lip_fullness", C, h2=0.60, unit="z"),
    TraitSpec("ear_protrusion", C, h2=0.60, unit="z"),
    TraitSpec("eye_size", C, h2=0.55, unit="z"),
    TraitSpec("incisor_shovelling", C, h2=0.70, unit="z",
              note="EDAR. A dental trait, in the same gene as hair and sweat."),

    # --- organ function (#11) --------------------------------------------
    TraitSpec("sweat_gland_density", C, h2=0.60, v_gxe=0.06, unit="z",
              note="EDAR. Thermoregulatory capacity; higher v_gxe because "
                   "eccrine gland recruitment is climate-acclimatised."),
    TraitSpec("insulin_sensitivity", C, h2=0.45, v_gxe=0.08, unit="z",
              note="TCF7L2 + omnigenic background. High GxE: diet/activity."),
    TraitSpec("bp_set_point", C, h2=0.35, v_gxe=0.08, mean=118.0, sd=12.0,
              unit="mmHg systolic", clip=(80.0, 190.0),
              note="Non-directional: blood pressure was a Joshi 2015 null."),
    TraitSpec("lipid_profile", C, h2=0.50, v_gxe=0.06, unit="z",
              note="Non-directional: LDL/HDL/total cholesterol were Joshi 2015 "
                   "nulls."),
    TraitSpec("lung_capacity", C, h2=0.55, v_gxe=0.06, mean=4.6, sd=0.8, unit="L",
              clip=(1.5, 8.0),
              v_dom=None, depression_per_10F=0.137,
              depression_source="Joshi et al. 2015, Nature 523:459 (FEV1)",
              note="DIRECTIONAL DOMINANCE, with a caveat that matters: Joshi's "
                   "-137 ml per 10% F_ROH is for FEV1, a timed expiratory "
                   "volume, while this trait is a generic spirometric capacity "
                   "with mean 4.6 L (closer to FVC). Applying the FEV1 slope to "
                   "it assumes the two depress proportionally, which is "
                   "plausible -- they correlate ~0.8 -- but is not what was "
                   "measured. TREAT THE MAGNITUDE AS INDICATIVE, THE SIGN AND "
                   "THE MECHANISM AS REAL. Reproducing it also costs V_D ~ 0.11, "
                   "high for a dominance share, because only 82 loci carry this "
                   "trait against 309 for height: the same total depression "
                   "spread over a quarter as many loci needs larger per-locus "
                   "deviations. That is an artefact of a 500-locus genome "
                   "standing in for ~50,000 independent segments, the caveat "
                   "already recorded at the top of this module."),
    TraitSpec("aerobic_capacity", C, h2=0.50, v_gxe=0.10, mean=42.0, sd=8.0,
              unit="mL/kg/min VO2max", clip=(15.0, 85.0),
              note="Large GxE: training response is itself heritable. "
                   "Mitochondrial (maternal) contribution is roadmap #3, absent."),
    TraitSpec("immune_reactivity", C, h2=0.50, v_gxe=0.06, unit="z"),
    TraitSpec("inflammation_tone", C, h2=0.40, v_gxe=0.10, unit="z",
              note="Feeds sickness behaviour (#27) and allostatic load (#24)."),

    # --- circadian (#26) ---------------------------------------------------
    TraitSpec("chronotype", C, h2=0.45, v_gxe=0.06, unit="z (neg=morning)",
              note="Jones 2019: 351 loci, Nat. Commun. 10:343."),

    # --- interoception (#22) ------------------------------------------------
    TraitSpec("interoceptive_accuracy", C, h2=0.35, v_gxe=0.05, unit="z",
              note="Heritable gain on the body->mind channel."),

    # --- personality: high h^2, flat architecture, near-zero PGS -------------
    TraitSpec("openness", C, h2=0.40, mean=0.5, sd=0.15, clip=(0.0, 1.0),
              target_pgs_r2=0.01),
    TraitSpec("conscientiousness", C, h2=0.40, mean=0.5, sd=0.15, clip=(0.0, 1.0),
              target_pgs_r2=0.01),
    TraitSpec("extraversion", C, h2=0.40, mean=0.5, sd=0.15, clip=(0.0, 1.0),
              target_pgs_r2=0.01),
    TraitSpec("agreeableness", C, h2=0.40, mean=0.5, sd=0.15, clip=(0.0, 1.0),
              target_pgs_r2=0.01),
    TraitSpec("neuroticism", C, h2=0.40, v_gxe=0.06, mean=0.5, sd=0.15, clip=(0.0, 1.0),
              target_pgs_r2=0.03,
              note="Okbay 2022 PGS ~2-3% out of sample. The gap between "
                   "h^2=0.40 and PGS=0.03 is the point, not a bug."),

    # --- categorical: liability-threshold (Falconer 1965) ---------------------
    TraitSpec("eye_color", K, h2=0.70, v_dom=0.20, v_epi=0.02, v_gxe=0.0,
              labels=("blue", "hazel", "brown"), prevalences=(0.25, 0.20, 0.55),
              note="Elevated v_dom so HERC2's near-complete dominance survives "
                   "calibration: het carriers of the brown allele express brown."),
    TraitSpec("handedness", K, h2=0.25, v_dom=0.03, v_epi=0.01, v_gxe=0.02,
              labels=("left", "right"), prevalences=(0.10, 0.90),
              note="h^2 really is only ~0.25 (McManus). Handedness is far less "
                   "heritable than intuition suggests."),
    TraitSpec("immune_resilience", K, h2=0.50, v_gxe=0.06,
              labels=("low", "moderate", "high"), prevalences=(0.25, 0.50, 0.25)),
    TraitSpec("vision_acuity", K, h2=0.70, v_gxe=0.08,
              labels=("myopic", "normal", "sharp"), prevalences=(0.30, 0.55, 0.15),
              note="High GxE: near-work / outdoor-light exposure is a real, "
                   "large environmental driver of myopia."),
    TraitSpec("hearing_ability", K, h2=0.50, v_dom=0.10, v_gxe=0.04,
              labels=("reduced", "normal"), prevalences=(0.12, 0.88),
              note="GJB2 is recessive -> elevated v_dom."),
    TraitSpec("chronic_illness_predisposition", K, h2=0.40, v_gxe=0.10,
              labels=("high_risk", "low_risk"), prevalences=(0.20, 0.80),
              note="POPULATION-LEVEL RISK, NOT A DIAGNOSIS."),
]}

for _t in TRAIT_TABLE.values():
    _t.validate()

TRAIT_NAMES: List[str] = list(TRAIT_TABLE)
CONTINUOUS_TRAITS: List[str] = [n for n, t in TRAIT_TABLE.items() if t.kind is C]
CATEGORICAL_TRAITS: List[str] = [n for n, t in TRAIT_TABLE.items() if t.kind is K]
OCEAN_TRAITS: List[str] = ["openness", "conscientiousness", "extraversion",
                           "agreeableness", "neuroticism"]

# Traits every locus catalogue entry is allowed to reference.
_declared = {t for L in LOCI for t in L.weights}
_unknown = _declared - set(TRAIT_NAMES)
if _unknown:
    raise ValueError(f"loci.py references undeclared traits: {sorted(_unknown)}")


# ======================================================================
# Calibration
# ======================================================================

# 2pq per locus: the additive-variance weight of a unit effect.
ALT_FREQ_HET: np.ndarray = 2.0 * ALT_FREQ * (1.0 - ALT_FREQ)


@dataclass
class TraitArchitecture:
    """Everything needed to evaluate one trait's liability, vectorised."""
    spec: TraitSpec
    idx: np.ndarray                 # (m,) locus indices with nonzero weight
    a: np.ndarray                   # (m,) additive genotypic values (Falconer a)
    d: np.ndarray                   # (m,) dominance deviations   (Falconer d)
    p: np.ndarray                   # (m,) alternate-allele frequencies
    mean_g: float                   # E[G] under HWE, subtracted to centre
    epi_i: np.ndarray               # (k,) locus indices, first of pair
    epi_j: np.ndarray               # (k,) locus indices, second of pair
    epi_w: np.ndarray               # (k,) epistatic coefficients
    gxe_w: np.ndarray               # (m,) GxE sensitivity weights
    sd_env: float                   # residual environmental sd
    # (n_labels-1,) cut points for categorical traits. `thresholds` are the
    # empirical quantiles actually used; `normal_thresholds` are what
    # Falconer's normality assumption would have given, kept for comparison.
    thresholds: Optional[np.ndarray] = None
    normal_thresholds: Optional[np.ndarray] = None

    # analytic variance components, for validation
    v_a: float = 0.0
    v_d: float = 0.0
    v_i: float = 0.0
    v_gxe: float = 0.0
    v_e: float = 0.0

    @property
    def n_loci(self) -> int:
        return int(self.idx.size)

    @property
    def realised_h2(self) -> float:
        vp = self.v_a + self.v_d + self.v_i + self.v_gxe + self.v_e
        return self.v_a / vp if vp > 0 else 0.0


def _solve_additive_scale(twopq: np.ndarray, a_hat: np.ndarray,
                          d: np.ndarray, p: np.ndarray, target_va: float) -> float:
    """
    Find s_a > 0 such that sum_j 2pq (s_a*a_hat_j + d_j (q_j - p_j))^2 = V_A.

    Expanding gives A2 s^2 + A1 s + A0 = V_A, a plain quadratic. The
    d(q-p) cross-term is exactly why we cannot just divide by a variance:
    dominance at loci with p != 0.5 leaks into the *additive* variance,
    because the average effect of an allele substitution depends on how
    often it lands in a heterozygote.
    """
    c = d * (1.0 - 2.0 * p)                       # d_j (q_j - p_j)
    A2 = float(np.sum(twopq * a_hat ** 2))
    A1 = float(2.0 * np.sum(twopq * a_hat * c))
    A0 = float(np.sum(twopq * c ** 2))

    if A2 <= 0.0:
        return 0.0
    disc = A1 * A1 - 4.0 * A2 * (A0 - target_va)
    if disc < 0.0:
        # Dominance alone already overshoots the additive-variance target.
        # Shrink dominance rather than emit a complex root; caller retries.
        raise ValueError("additive-scale solve has no real root")
    return (-A1 + float(np.sqrt(disc))) / (2.0 * A2)


def _calibrate_trait(spec: TraitSpec, rng: np.random.Generator) -> TraitArchitecture:
    idx = np.array([L.index for L in LOCI if spec.name in L.weights], dtype=np.int64)
    if idx.size == 0:
        raise ValueError(f"trait {spec.name} has no contributing loci")

    a_hat = np.array([LOCI[i].weights[spec.name] for i in idx])
    p = ALT_FREQ[idx]
    q = 1.0 - p
    twopq = 2.0 * p * q

    # --- dominance ------------------------------------------------------
    # Two regimes, and the difference is which function of the SAME vector
    # is pinned. V_D = sum (2pq d)^2 is a sum of squares; inbreeding
    # depression is F * sum (2pq d), a plain sum. Pinning one does not pin
    # the other -- with signs drawn at random the plain sum cancels to
    # ~zero while the sum of squares is whatever we asked for, which is
    # exactly how this engine ended up with dominance variance but no
    # inbreeding depression on any trait.
    d_hat = DOMINANCE_RATIO[idx] * a_hat
    if not spec.is_directional:
        # V_D is an INPUT: scale the raw d/a ratios to hit it exactly.
        denom = float(np.sum((twopq * d_hat) ** 2))
        s_d = float(np.sqrt(spec.v_dom / denom)) if denom > 0 and spec.v_dom > 0 else 0.0
        d = s_d * d_hat
    else:
        # V_D is an OUTPUT: pin the plain sum to the measured depression.
        #
        # Directional dominance means the trait-INCREASING allele is the
        # dominant one, so every heterozygote sits above the midpoint of its
        # two homozygotes and d > 0 whatever the sign of a. Removing
        # heterozygotes then lowers the mean, which is the depression.
        #
        # Only anonymous peripheral loci are re-signed. A curated core gene's
        # dominance sign is a published claim about that gene (HERC2 +0.95,
        # MC1R -0.80, GJB2 -1.00) and is never overridden -- for the traits
        # below every core d/a ratio is 0.0 anyway, so this guard is
        # future-proofing rather than a live correction.
        is_core = np.array([LOCI[i].is_core for i in idx])
        d_hat = np.where(is_core, d_hat, np.abs(d_hat))
        denom = float(np.sum(twopq * d_hat))
        s_d = spec.target_dominance_sum() / denom if denom != 0.0 else 0.0
        d = s_d * d_hat

    # --- additive: solve the quadratic for V_A = h^2 ---------------------
    shrink = 1.0
    for _ in range(12):
        try:
            s_a = _solve_additive_scale(twopq, a_hat, d * shrink, p, spec.v_add)
            break
        except ValueError:
            shrink *= 0.5
    else:
        raise RuntimeError(f"trait {spec.name}: could not calibrate additive scale")
    if shrink != 1.0 and spec.is_directional:
        # Halving d to rescue the additive solve would silently halve the
        # depression this trait was calibrated to reproduce. Fail loudly
        # instead: the target and h^2 are jointly infeasible.
        raise ValueError(
            f"trait {spec.name}: dominance had to shrink by {shrink} to solve "
            f"V_A = {spec.v_add}, which would break the depression target"
        )
    d = d * shrink
    a = s_a * a_hat

    alpha = a + d * (q - p)
    v_a = float(np.sum(twopq * alpha ** 2))
    v_d = float(np.sum((twopq * d) ** 2))

    # E[G] under HWE:  p^2*a + 2pq*d + q^2*(-a)  =  a(p-q) + 2pq*d
    mean_g = float(np.sum(a * (p - q) + twopq * d))

    # --- epistasis: pairwise products of centred dosages ------------------
    # Var(x_i x_j) = 2p_i q_i * 2p_j q_j for unlinked, HWE loci, and the
    # product is orthogonal to both A and D, so V_I adds cleanly.
    k = min(EPISTATIC_PAIRS_PER_TRAIT, idx.size // 2)
    if k > 0 and spec.v_epi > 0:
        pick = rng.choice(idx.size, size=(k, 2), replace=True)
        # avoid self-pairs
        same = pick[:, 0] == pick[:, 1]
        pick[same, 1] = (pick[same, 1] + 1) % idx.size
        epi_i = idx[pick[:, 0]]
        epi_j = idx[pick[:, 1]]
        w_hat = rng.normal(0.0, 1.0, size=k)
        var_unit = float(np.sum(w_hat ** 2 * ALT_FREQ_HET[epi_i] * ALT_FREQ_HET[epi_j]))
        s_e = float(np.sqrt(spec.v_epi / var_unit)) if var_unit > 0 else 0.0
        epi_w = s_e * w_hat
        v_i = float(np.sum(epi_w ** 2 * ALT_FREQ_HET[epi_i] * ALT_FREQ_HET[epi_j]))
    else:
        epi_i = np.array([], dtype=np.int64)
        epi_j = np.array([], dtype=np.int64)
        epi_w = np.array([])
        v_i = 0.0

    # --- GxE: environmental sensitivity proportional to additive shape -----
    # GxE_t = s_g * (sum_j a_hat_j x_j) * env, env ~ N(0,1) independent of x.
    # Var = s_g^2 * sum_j 2pq a_hat^2 * Var(env) = s_g^2 * A2.
    A2 = float(np.sum(twopq * a_hat ** 2))
    s_g = float(np.sqrt(spec.v_gxe / A2)) if A2 > 0 and spec.v_gxe > 0 else 0.0
    gxe_w = s_g * a_hat
    v_gxe = s_g ** 2 * A2

    # A directional trait's residual is whatever is left once its V_D has
    # been *measured* rather than assumed, so V_P = 1 still holds exactly.
    # The non-directional path keeps reading `spec.v_env` verbatim: v_d and
    # spec.v_dom agree there only to float precision, and computing v_e from
    # the realised value instead would shift every other trait's residual in
    # its last bit.
    if spec.is_directional:
        v_e = spec.residual_variance(v_d)
        if v_e <= 0.0:
            raise ValueError(
                f"trait {spec.name}: reproducing a depression of "
                f"{spec.depression_per_10F} {spec.unit} per 10% F requires "
                f"V_D = {v_d:.4f}, which leaves no environmental variance "
                f"(h2={spec.h2} + epi={spec.v_epi} + gxe={spec.v_gxe})"
            )
    else:
        v_e = spec.v_env
    sd_env = float(np.sqrt(v_e))

    thresholds = None
    if spec.kind is TraitKind.CATEGORICAL:
        cum = np.cumsum(spec.prevalences)[:-1]
        thresholds = norm.ppf(cum)

    return TraitArchitecture(
        spec=spec, idx=idx, a=a, d=d, p=p, mean_g=mean_g,
        epi_i=epi_i, epi_j=epi_j, epi_w=epi_w, gxe_w=gxe_w,
        sd_env=sd_env, thresholds=thresholds,
        v_a=v_a, v_d=v_d, v_i=v_i, v_gxe=v_gxe, v_e=v_e,
    )


# ----------------------------------------------------------------------
# Threshold calibration for categorical traits
# ----------------------------------------------------------------------
# Falconer's 1965 liability-threshold model assumes the liability is
# normally distributed, which the central limit theorem delivers *only*
# when many loci contribute comparably. `eye_color` violates that
# assumption outright: HERC2 alone carries >40% of its additive variance,
# so its liability is visibly bimodal and the normal quantile for "hazel"
# lands inside the gap between the two modes. Using norm.ppf gave 10.8%
# hazel against a 20% target.
#
# So we do not assume. Thresholds are the EMPIRICAL quantiles of a large
# simulated founder cohort. Prevalences then match by construction, and
# the departure from normality is measured (see `liability_nonnormality`)
# rather than swept under the model.

THRESHOLD_CALIBRATION_SEED = 20240505
THRESHOLD_CALIBRATION_N = 40_000
_CALIBRATION_CHUNK = 8_000


def _simulate_founder_liabilities(archs: Sequence[TraitArchitecture],
                                  n: int, rng: np.random.Generator
                                  ) -> Dict[str, np.ndarray]:
    """Full-genome founder cohort, generated in chunks to bound memory."""
    out: Dict[str, List[np.ndarray]] = {a.spec.name: [] for a in archs}
    remaining = n
    while remaining > 0:
        k = min(_CALIBRATION_CHUNK, remaining)
        remaining -= k
        haps = (rng.random((k, 2, N_LOCI)) < ALT_FREQ).astype(np.int8)
        dose = haps.sum(axis=1).astype(np.int8)
        for a in archs:
            out[a.spec.name].append(population_liabilities(
                a, dose, rng.normal(0, 1, k), rng.normal(0, 1, k)))
    return {t: np.concatenate(v) for t, v in out.items()}


def _calibrate_thresholds(arch_map: Dict[str, TraitArchitecture]) -> None:
    cats = [a for a in arch_map.values() if a.spec.kind is TraitKind.CATEGORICAL]
    if not cats:
        return
    rng = np.random.default_rng(THRESHOLD_CALIBRATION_SEED)
    liab = _simulate_founder_liabilities(cats, THRESHOLD_CALIBRATION_N, rng)
    for a in cats:
        cum = np.cumsum(a.spec.prevalences)[:-1]
        a.thresholds = np.quantile(liab[a.spec.name], cum)
        a.normal_thresholds = norm.ppf(cum)


def liability_nonnormality(trait: str, n: int = 20_000) -> Dict[str, float]:
    """
    How far a trait departs from the normality Falconer's model assumes.

    Two different kurtoses, and the distinction matters:

      `genotypic_kurtosis`  excess kurtosis of G = A + D alone. This is
          where the central limit theorem applies: many comparable loci
          summed should give ~0. eye_color returns about -0.8 (bimodal,
          because HERC2 carries >40% of V_A); neuroticism returns ~0.02
          across its 402 tiny loci. THIS is the major-effect-locus test.

      `liability_kurtosis`  excess kurtosis of the full z = G + I + GxE + E.
          Always positive when V_GxE > 0, because GxE is a product of two
          independent normals and such products have excess kurtosis 6.
          A trait can have a perfectly normal genotypic value and a
          heavy-tailed liability. Do not confuse the two.

    `max_threshold_shift` is the largest gap between the empirical
    quantile we actually use and the normal quantile Falconer would have
    predicted -- the practical cost of assuming normality.
    """
    from scipy.stats import kurtosis, skew
    arch = ARCHITECTURE[trait]
    rng = np.random.default_rng(1234)

    haps = (rng.random((min(n, 20_000), 2, N_LOCI)) < ALT_FREQ).astype(np.int8)
    dose = haps.sum(axis=1).astype(np.int8)
    g = population_genotypic_values(arch, dose)

    z = _simulate_founder_liabilities([arch], n, np.random.default_rng(1234))[trait]

    res = {
        "genotypic_kurtosis": float(kurtosis(g)),
        "liability_kurtosis": float(kurtosis(z)),
        "skew": float(skew(z)),
    }
    if arch.thresholds is not None and arch.normal_thresholds is not None:
        res["max_threshold_shift"] = float(
            np.abs(arch.thresholds - arch.normal_thresholds).max())
    return res


def _build_map() -> Dict[str, TraitArchitecture]:
    rng = np.random.default_rng(GP_MAP_SEED)
    m = {name: _calibrate_trait(spec, rng) for name, spec in TRAIT_TABLE.items()}
    _calibrate_thresholds(m)
    return m


# NOTE: ARCHITECTURE is built at the BOTTOM of this module, because
# threshold calibration needs `population_liabilities`, which is defined
# further down. Everything between here and there refers to ARCHITECTURE
# only at call time.


# ======================================================================
# Environment (roadmap #14: reaction norms)
# ======================================================================

@dataclass
class Environment:
    """
    An environment is not a scalar "stress" number. It is (a) a shift in
    each trait's environmental mean -- the reaction norm's intercept --
    and (b) a shift in the mean of the GxE input, which changes how much
    *genotype* matters. Two genotypes can cross over as the environment
    moves; that crossing is what "norm of reaction" means.

    Values are in standard-deviation units of the residual, so
    trait_shifts["height_cm"] = -0.5 means "this environment costs half a
    residual SD of height" (childhood nutrition, roughly).
    """
    name: str = "neutral"
    trait_shifts: Dict[str, float] = field(default_factory=dict)
    gxe_means: Dict[str, float] = field(default_factory=dict)
    # generic stressor level in [0, inf); consumed by physiology/medical layers
    stress: float = 1.0
    # Named lifetime/developmental exposures consumed by the epigenome layer
    # (roadmap #18/#19). All in [0, 1]. Examples:
    #   "smoking"            ongoing, drives AHRR hypomethylation
    #   "psychosocial_stress" ongoing, drives pro-inflammatory hypomethylation
    #   "early_life_care"    developmental (0 = neglect .. 1 = high care), NR3C1
    #   "prenatal_nutrition" developmental (0 = famine .. 1 = plentiful), IGF2
    exposures: Dict[str, float] = field(default_factory=dict)

    def shift(self, trait: str) -> float:
        return self.trait_shifts.get(trait, 0.0)

    def gxe_mean(self, trait: str) -> float:
        return self.gxe_means.get(trait, 0.0)

    def exposure(self, name: str, default: float = 0.0) -> float:
        return self.exposures.get(name, default)


NEUTRAL_ENVIRONMENT = Environment("neutral")


@dataclass
class EnvironmentalDeviates:
    """
    The individual's *persistent* non-genetic draws, made once at birth.

    This is what fixes the v0.2 quirk where `phenotype()` re-rolled its
    epigenetic silencing check on every call, so the same NPC could have
    brown eyes and then blue eyes a millisecond later. Randomness belongs
    at conception, not at read time. `snapshot_phenotypes()` is no longer
    needed and no longer exists.
    """
    residual: Dict[str, float]      # standard-normal residual per trait
    gxe_input: Dict[str, float]     # standard-normal GxE input per trait

    @staticmethod
    def draw(rng: np.random.Generator, env: Environment = NEUTRAL_ENVIRONMENT
             ) -> "EnvironmentalDeviates":
        return EnvironmentalDeviates(
            residual={t: float(rng.normal(env.shift(t), 1.0)) for t in TRAIT_NAMES},
            gxe_input={t: float(rng.normal(env.gxe_mean(t), 1.0)) for t in TRAIT_NAMES},
        )


# ======================================================================
# Evaluation
# ======================================================================

def genotypic_value(arch: TraitArchitecture, dosage: np.ndarray,
                    expression: Optional[np.ndarray] = None,
                    imprint: Optional["ImprintState"] = None) -> float:
    """
    G = sum_j m_j * [ +a_j if AA, d_j if Aa, -a_j if aa ]  -  E[G]

    `expression` is an (L,) multiplier in [0, 1] supplied by the epigenome
    (roadmap #16). Default 1.0 everywhere. A silenced locus contributes
    nothing, which shifts the mean as well as the variance -- that is the
    biologically correct behaviour and we deliberately do not re-centre.

    `imprint` is the parent-of-origin layer (roadmap #4, imprint.py), None
    by default. At an imprinted locus only one parental copy is
    transcribed, so the genotype term is blended toward the value the
    individual would have if it were homozygous for the ACTIVE copy:

        val = (1 - s) * val_biallelic  +  s * val_monoallelic

    with s the silencing strength. At s = 0 this is exactly the line above
    it, which is why a world with no imprinted loci is untouched. At s = 1
    the heterozygote's dominance deviation `d` disappears entirely --
    correct, because monoallelic expression admits no heterozygote
    intermediate: you get the phenotype of whichever copy is on.

    Note the ORDER. Imprinting decides *which allele is transcribed*; the
    epigenome/GRN multiplier then scales the locus's total output. Applying
    imprinting first and expression second is the biologically meaningful
    composition, and it means a locus that is both imprinted and silenced
    still contributes nothing.
    """
    g = dosage[arch.idx]
    val = np.where(g == 2, arch.a, np.where(g == 1, arch.d, -arch.a))
    if imprint is not None:
        s = imprint.strength[arch.idx]
        if np.any(s > 0.0):
            gm = imprint.mono_dosage[arch.idx]
            val = (1.0 - s) * val + s * np.where(gm == 2, arch.a, -arch.a)
    if expression is not None:
        val = val * expression[arch.idx]
    return float(val.sum() - arch.mean_g)


def liability(arch: TraitArchitecture, dosage: np.ndarray,
              dev: EnvironmentalDeviates,
              expression: Optional[np.ndarray] = None,
              imprint: Optional["ImprintState"] = None,
              canalization: float = 1.0) -> float:
    """Standardised liability z = G + I + GxE + E.

    Imprinting (#4) enters through the genotypic value only. The epistatic
    and GxE terms are built from raw dosages on purpose: those components
    were calibrated against the biallelic dosage distribution, and routing
    a parent-of-origin effect through them would decalibrate V_I and V_GxE
    for a mechanism that acts on transcription, not on interaction.

    `canalization` is the developmental-buffering factor k (#14b,
    canalize.py), 1.0 by default and therefore inert. It multiplies the
    GENETIC terms only -- G and the epistatic I -- so that stress releases
    cryptic genetic variation while leaving the environmental residual
    alone. Both terms are mean-centred by construction (genotypic_value
    subtracts E[G]; the epistatic products use centred dosages), so scaling
    them changes variance without moving the population mean. V_GxE is
    deliberately not scaled: it already carries an environmental response,
    and scaling it too would confound two mechanisms the engine models
    separately."""
    t = arch.spec.name
    z = genotypic_value(arch, dosage, expression, imprint)

    if arch.epi_w.size:
        xi = dosage[arch.epi_i] - 2.0 * ALT_FREQ[arch.epi_i]
        xj = dosage[arch.epi_j] - 2.0 * ALT_FREQ[arch.epi_j]
        z += float(np.sum(arch.epi_w * xi * xj))

    if canalization != 1.0:
        z *= canalization          # G and I only; E and GxE are added below

    if arch.gxe_w.size and arch.spec.v_gxe > 0:
        x = dosage[arch.idx] - 2.0 * arch.p
        z += float(np.dot(arch.gxe_w, x)) * dev.gxe_input[t]

    z += arch.sd_env * dev.residual[t]
    return z


def express(arch: TraitArchitecture, z: float):
    """Map a liability onto the trait's observable scale."""
    spec = arch.spec
    if spec.kind is TraitKind.CONTINUOUS:
        v = spec.mean + spec.sd * z
        if spec.clip is not None:
            v = min(max(v, spec.clip[0]), spec.clip[1])
        return v
    i = int(np.searchsorted(arch.thresholds, z))
    return spec.labels[i]


def phenotype(dosage: np.ndarray, dev: EnvironmentalDeviates,
              expression: Optional[np.ndarray] = None,
              imprint: Optional["ImprintState"] = None,
              canalization: Optional[Dict[str, float]] = None
              ) -> Dict[str, object]:
    """Full genotype -> phenotype pass across every trait."""
    out: Dict[str, object] = {}
    for name, arch in ARCHITECTURE.items():
        k = 1.0 if canalization is None else canalization.get(name, 1.0)
        out[name] = express(arch, liability(arch, dosage, dev, expression,
                                            imprint, k))
    return out


def liabilities(dosage: np.ndarray, dev: EnvironmentalDeviates,
                expression: Optional[np.ndarray] = None,
                imprint: Optional["ImprintState"] = None,
                canalization: Optional[Dict[str, float]] = None
                ) -> Dict[str, float]:
    return {n: liability(a, dosage, dev, expression, imprint,
                         1.0 if canalization is None else canalization.get(n, 1.0))
            for n, a in ARCHITECTURE.items()}


# ----------------------------------------------------------------------
# Population-scale (vectorised) evaluation, used by validation.py
# ----------------------------------------------------------------------

def population_genotypic_values(arch: TraitArchitecture, dosages: np.ndarray) -> np.ndarray:
    """(N,) genotypic values G for an (N, L) dosage matrix."""
    g = dosages[:, arch.idx]
    val = np.where(g == 2, arch.a, np.where(g == 1, arch.d, -arch.a))
    return val.sum(axis=1) - arch.mean_g


def population_liabilities(arch: TraitArchitecture, dosages: np.ndarray,
                           residual: np.ndarray, gxe_input: np.ndarray) -> np.ndarray:
    """(N,) liabilities. `residual` and `gxe_input` are (N,) standard normals."""
    z = population_genotypic_values(arch, dosages)

    if arch.epi_w.size:
        xi = dosages[:, arch.epi_i] - 2.0 * ALT_FREQ[arch.epi_i]
        xj = dosages[:, arch.epi_j] - 2.0 * ALT_FREQ[arch.epi_j]
        z = z + (arch.epi_w * xi * xj).sum(axis=1)

    if arch.gxe_w.size and arch.spec.v_gxe > 0:
        x = dosages[:, arch.idx] - 2.0 * arch.p
        z = z + (x @ arch.gxe_w) * gxe_input

    return z + arch.sd_env * residual


def breeding_values(arch: TraitArchitecture, dosages: np.ndarray) -> np.ndarray:
    """
    (N,) additive genetic values (breeding values):
        A_i = sum_j alpha_j * (g_ij - 2 p_j)

    The quantity that is actually transmitted -- half of it -- to
    offspring. Used by `validation.breeders_equation`.
    """
    alpha = arch.a + arch.d * (1.0 - 2.0 * arch.p)
    x = dosages[:, arch.idx] - 2.0 * arch.p
    return x @ alpha


# ----------------------------------------------------------------------
# Build the map. Deferred to here so `_calibrate_thresholds` can call
# `population_liabilities`.
# ----------------------------------------------------------------------

ARCHITECTURE: Dict[str, TraitArchitecture] = _build_map()


# ----------------------------------------------------------------------
# Introspection: pleiotropy report (roadmap #7 benchmark)
# ----------------------------------------------------------------------

def traits_touched_by(symbol: str) -> Dict[str, float]:
    from .loci import LOCUS_BY_SYMBOL
    return dict(LOCUS_BY_SYMBOL[symbol].weights)


def loci_for_trait(trait: str, core_only: bool = False) -> List[str]:
    return [L.symbol for L in LOCI
            if trait in L.weights and (L.is_core or not core_only)]


def architecture_summary() -> str:
    lines = [
        f"{'trait':<32}{'kind':<12}{'h2':>6}{'loci':>7}{'core':>6}"
        f"{'V_A':>8}{'V_D':>8}{'V_I':>8}{'V_GxE':>8}{'V_E':>8}"
    ]
    for name, arch in ARCHITECTURE.items():
        core = sum(1 for i in arch.idx if LOCI[i].is_core)
        lines.append(
            f"{name:<32}{arch.spec.kind.value:<12}{arch.spec.h2:>6.2f}"
            f"{arch.n_loci:>7}{core:>6}"
            f"{arch.v_a:>8.3f}{arch.v_d:>8.3f}{arch.v_i:>8.3f}"
            f"{arch.v_gxe:>8.3f}{arch.v_e:>8.3f}"
        )
    return "\n".join(lines)
