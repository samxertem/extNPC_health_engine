"""
Epigenome — lifetime-dynamic methylation, histone marks, epigenetic clock.
==========================================================================

Roadmap Thrust 2, items #15–#20. This is the project owner's stated
top-priority gap: in v0.2 epigenetic marks updated ONLY at reproduction
and never during an individual's life. Here they update every year, from
accumulated exposure, stress, illness and age, and only a tiny fraction
ever reaches the next generation.

The three-layer molecular model (#16)
-------------------------------------
v0.2 had a single scalar "silencing probability" per locus. Real
epigenetic regulation is graded and combines several marks (Jaenisch &
Bird 2003; Bird 2002). We carry three per-locus layers:

    methylation   promoter CpG methylation, generally REPRESSIVE
    activating    H3K4me3-like activating histone mark
    repressive    H3K27me3 / H3K9me3-like repressive histone marks

They combine into one expression multiplier per locus, consumed by
`traits.genotypic_value`. At the baseline state the multiplier is exactly
1.0 at every locus, so a default epigenome reproduces the calibrated
genetics of session 1 bit for bit — epigenetic effects are deviations
from that baseline, never a re-scaling of it.

The three-CLASS reversibility split (#20, the key correction)
-------------------------------------------------------------
Marks are split by how they behave over a lifetime and a germline,
because the classes are mechanistically different:

    SOMATIC_REVERSIBLE   relaxes back toward baseline when the driving
                         exposure stops (AHRR on smoking cessation —
                         Philibert 2016; NR3C1 in rat cross-fostering —
                         Weaver 2004).
    AGE_DRIFT            accumulates monotonically with age and is
                         essentially irreversible; this is what the
                         Horvath 2013 clock reads (#17).
    GERMLINE_ESCAPER     the rare marks that survive germline
                         reprogramming (imprinted / metastable loci).

GERMLINE POLICY — a design decision, made explicitly
----------------------------------------------------
Mammalian germline reprogramming erases nearly everything between
generations (Seisenberger 2013); human transgenerational epigenetic
inheritance is limited and contested (Heard & Martienssen 2014). v0.2's
60%-fidelity / 30%-reset scheme was Lamarckian and wrong.

The scaffold offered three positions. This module takes the defensible
MIDDLE one:

    base_reset_prob     = 0.95   (was 0.30)
    escaper_reset_prob  = 0.50
    inheritance_fidelity= 0.40   (was 0.60; < 0.5 so even escaped marks
                                  fade rather than accumulate)
    escapers            = {IGF2} (imprinted AND the Dutch Hunger Winter
                                  famine-methylation locus, Heijmans 2008)

Consequence, and the roadmap's Stage-1 benchmark: an NPC's smoking-driven
AHRR hypomethylation is visible for life and partially recovers on
cessation, yet its children almost never inherit it (AHRR is not an
escaper → 95% reset, and the 5% that survive are diluted to 40%). IGF2,
by contrast, transmits a weak famine signal to the next generation.

CAVEATS that must survive any rewrite (roadmap §5)
--------------------------------------------------
* The NR3C1 maternal-care mechanism is RAT data (Weaver 2004),
  suggestive, not proven in humans.
* Even the IGF2 transmission modelled here is stronger and cleaner than
  the contested human evidence. It is a game-legible caricature of a real
  but small effect, not a claim about effect size.
* Do NOT let this become a route by which acquired traits are inherited
  in general. The 0.95 base reset is load-bearing; if cross-generational
  drift ever looks Lamarckian, raise it toward 0.99 (roadmap §4
  "Adjustable thresholds").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Tuple

import numpy as np

from .loci import LOCUS_BY_SYMBOL, N_LOCI, LOCI

# ----------------------------------------------------------------------
# Baselines. Chosen so that at the baseline state the expression
# multiplier is exactly 1.0 everywhere (see `expression_from_marks`).
# ----------------------------------------------------------------------
BASELINE_METHYLATION = 0.50
BASELINE_ACTIVATING = 0.50
BASELINE_REPRESSIVE = 0.10

# How the three layers combine into a silencing amount. Signs: more
# methylation and more repressive marks silence; more activating marks
# de-silence. Weights are relative; methylation dominates, as at real
# promoters.
W_METHYLATION = 1.20
W_REPRESSIVE = 1.00
W_ACTIVATING = 0.80

# Expression is allowed slightly above 1: demethylating an already-active
# promoter can raise expression above baseline. Capped to keep genotypic
# values bounded.
EXPRESSION_MIN = 0.0
EXPRESSION_MAX = 1.5

# ----------------------------------------------------------------------
# Epigenetic clock (#17). One "epigenetic year" per chronological year at
# baseline, accelerated by sustained stress and ACQUIRED inflammatory load
# (illness is booked separately, in medical.py). Horvath 2013's clock has
# ~3.6 yr MAE; acceleration predicts morbidity.
#
# Crucially the clock keys off ACQUIRED load, never off the genotypic
# inflammation_tone liability. A person born with a high-inflammation
# genotype is not thereby aging fast; a person whose chronic stress has
# hypomethylated their inflammatory promoters is. That is the difference
# between a genetic PREDISPOSITION and a physiological STATE, and it is
# the seam the physiological-state vector (#21) will build on.
# ----------------------------------------------------------------------
CLOCK_STRESS_COEF = 0.35        # per unit of (env.stress - 1)
CLOCK_INFLAMMATION_COEF = 1.6   # per unit of acquired inflammatory load [0, ~0.22]
CLOCK_MIN_RATE = 0.4            # a year of life never ages you < 0.4 epi-years

# Converts acquired inflammatory load (mean hypomethylation of pro-
# inflammatory promoters, 0..~0.22) into liability units for the
# inflammation STATE that feeds medical hazards and, later, the LLM.
LOAD_TO_LIABILITY = 2.5

# ----------------------------------------------------------------------
# Age-drift loci (#17). A fixed subset of loci whose methylation moves
# monotonically with epigenetic age. Direction is per-locus and fixed.
# ----------------------------------------------------------------------
N_AGE_DRIFT_LOCI = 60
AGE_DRIFT_RATE = 0.0045         # methylation units per epigenetic year
EPIGENOME_SEED = 20240610

# ----------------------------------------------------------------------
# Reversible-exposure loci (#18). Explicit rather than abstracted, so the
# mechanism and its direction are readable.
# ----------------------------------------------------------------------
# AHRR cg05575921: smoking -> robust HYPOmethylation (Joehanes 2016).
AHRR_MAX_SHIFT = 0.32           # full-intensity smoking drives m this far down
AHRR_ONSET_RATE = 0.16          # per year toward the exposure target
AHRR_RECOVERY_RATE = 0.09       # per year back toward baseline on cessation

# Pro-inflammatory loci (IL6/CRP...): chronic stress -> hypomethylation
# -> higher expression -> higher inflammatory tone (a compounding loop
# feeding the epigenetic clock and, later, allostatic load).
INFLAMM_MAX_SHIFT = 0.22
INFLAMM_ONSET_RATE = 0.13
INFLAMM_RECOVERY_RATE = 0.06

# ----------------------------------------------------------------------
# Developmental programming (#19). Set once, at conception/birth.
# ----------------------------------------------------------------------
# IGF2: periconceptional famine -> lower methylation, persisting decades
# (Heijmans 2008). Also our germline escaper.
IGF2_DEV_GAIN = 0.40            # per unit of (nutrition - 0.5)
# NR3C1 (glucocorticoid receptor): low early-life care -> hypermethylation
# -> blunted GR expression -> heightened lifelong HPA reactivity
# (Weaver 2004, RAT). Reversible in principle but slow.
NR3C1_DEV_GAIN = 0.30           # per unit of (0.5 - care)


class MarkClass(Enum):
    SOMATIC_REVERSIBLE = "somatic_reversible"
    AGE_DRIFT = "age_drift"
    GERMLINE_ESCAPER = "germline_escaper"


# ----------------------------------------------------------------------
# Build the fixed locus groupings once (part of the reference "species").
# ----------------------------------------------------------------------
def _symbol_idx(symbol: str) -> Optional[int]:
    L = LOCUS_BY_SYMBOL.get(symbol)
    return None if L is None else L.index


_rng = np.random.default_rng(EPIGENOME_SEED)

# Age-drift loci and their (fixed) drift direction.
AGE_DRIFT_IDX = np.sort(_rng.choice(N_LOCI, size=N_AGE_DRIFT_LOCI, replace=False))
AGE_DRIFT_DIR = _rng.choice(np.array([-1.0, 1.0]), size=N_AGE_DRIFT_LOCI)

AHRR_IDX = _symbol_idx("AHRR")
NR3C1_IDX = _symbol_idx("NR3C1")
IGF2_IDX = _symbol_idx("IGF2")

# Pro-inflammatory loci: any core gene with a positive inflammation_tone weight.
INFLAMM_IDX = np.array(
    [L.index for L in LOCI
     if L.is_core and L.weights.get("inflammation_tone", 0.0) > 0.0],
    dtype=np.int64,
)

# Escaper set: which loci can cross the germline.
ESCAPER_SYMBOLS: Tuple[str, ...] = ("IGF2",)
_ESCAPER_IDX = np.array([i for i in (_symbol_idx(s) for s in ESCAPER_SYMBOLS)
                         if i is not None], dtype=np.int64)
IS_ESCAPER = np.zeros(N_LOCI, dtype=bool)
IS_ESCAPER[_ESCAPER_IDX] = True


@dataclass(frozen=True)
class GermlineResetPolicy:
    """See module docstring. Governs what crosses the germline (#20)."""
    base_reset_prob: float = 0.95
    escaper_reset_prob: float = 0.50
    inheritance_fidelity: float = 0.40

    def reset_prob_vector(self) -> np.ndarray:
        return np.where(IS_ESCAPER, self.escaper_reset_prob, self.base_reset_prob)


DEFAULT_GERMLINE_POLICY = GermlineResetPolicy()


# ======================================================================
# Expression
# ======================================================================

def expression_from_marks(methylation: np.ndarray,
                          activating: np.ndarray,
                          repressive: np.ndarray) -> np.ndarray:
    """
    Combine the three molecular layers into an (L,) expression multiplier
    (roadmap #16). Baseline state -> exactly 1.0 at every locus.

        silencing  = W_meth (m - m0) + W_repr (r - r0) - W_act (a - a0)
        expression = clip(1 - silencing, EXPRESSION_MIN, EXPRESSION_MAX)
    """
    silencing = (W_METHYLATION * (methylation - BASELINE_METHYLATION)
                 + W_REPRESSIVE * (repressive - BASELINE_REPRESSIVE)
                 - W_ACTIVATING * (activating - BASELINE_ACTIVATING))
    return np.clip(1.0 - silencing, EXPRESSION_MIN, EXPRESSION_MAX)


# ======================================================================
# Epigenome
# ======================================================================

@dataclass
class Epigenome:
    """Per-individual epigenetic state. Dynamic across the lifespan."""
    methylation: np.ndarray             # (L,) in [0, 1]
    activating: np.ndarray              # (L,) in [0, 1]
    repressive: np.ndarray              # (L,) in [0, 1]
    epigenetic_age: float = 0.0

    # -------------------- construction --------------------

    @staticmethod
    def default() -> "Epigenome":
        """Baseline state: expression multiplier is 1.0 everywhere."""
        return Epigenome(
            methylation=np.full(N_LOCI, BASELINE_METHYLATION),
            activating=np.full(N_LOCI, BASELINE_ACTIVATING),
            repressive=np.full(N_LOCI, BASELINE_REPRESSIVE),
            epigenetic_age=0.0,
        )

    def copy(self) -> "Epigenome":
        return Epigenome(self.methylation.copy(), self.activating.copy(),
                         self.repressive.copy(), self.epigenetic_age)

    # -------------------- expression --------------------

    def expression(self) -> np.ndarray:
        return expression_from_marks(self.methylation, self.activating,
                                     self.repressive)

    def methylation_of(self, symbol: str) -> float:
        return float(self.methylation[LOCUS_BY_SYMBOL[symbol].index])

    def inflammatory_load(self) -> float:
        """
        Acquired inflammatory load: mean HYPOmethylation across the pro-
        inflammatory promoters, floored at zero. Genotype-free by
        construction — it is 0 for a newborn and rises only with lived
        exposure. This is the physiological STATE signal, distinct from
        the genotypic inflammation_tone predisposition.
        """
        if not INFLAMM_IDX.size:
            return 0.0
        hypo = np.maximum(BASELINE_METHYLATION - self.methylation[INFLAMM_IDX], 0.0)
        return float(hypo.mean())

    # -------------------- developmental programming (#19) --------------------

    def apply_developmental(self, env) -> None:
        """
        Set persistent baselines from the prenatal / early-life
        environment. Called once, at NPC creation. These do not relax back
        the way ordinary somatic marks do — a developmental window closes.
        """
        if IGF2_IDX is not None:
            nutrition = env.exposure("prenatal_nutrition", 0.5)
            self.methylation[IGF2_IDX] = _clip01(
                BASELINE_METHYLATION + IGF2_DEV_GAIN * (nutrition - 0.5))
        if NR3C1_IDX is not None:
            care = env.exposure("early_life_care", 0.5)
            self.methylation[NR3C1_IDX] = _clip01(
                BASELINE_METHYLATION + NR3C1_DEV_GAIN * (0.5 - care))

    # -------------------- lifetime dynamics (#15, #17, #18) --------------------

    def tick(self, env) -> None:
        """
        Advance the epigenome by one year.

        Order: (1) advance the epigenetic clock from stress and the
        CURRENT acquired inflammatory load; (2) irreversible age drift,
        itself accelerated by clock acceleration; (3) reversible exposure
        responses that relax toward an exposure-dependent target, giving
        dose-dependence and partial reversibility for free. Illness is
        booked onto the clock separately by the caller (medical.py), so
        the clock here depends on no genotype-derived quantity.
        """
        stress = env.stress

        # (1) epigenetic clock — acquired signals only
        accel = (CLOCK_STRESS_COEF * max(stress - 1.0, 0.0)
                 + CLOCK_INFLAMMATION_COEF * self.inflammatory_load())
        self.epigenetic_age += max(1.0 + accel, CLOCK_MIN_RATE)

        # (2) irreversible age drift, amplified by acceleration
        drift = AGE_DRIFT_RATE * (1.0 + 0.5 * accel)
        self.methylation[AGE_DRIFT_IDX] = _clip01(
            self.methylation[AGE_DRIFT_IDX] + drift * AGE_DRIFT_DIR)
        # a second molecular layer also drifts, so expression is genuinely
        # a combination of layers, not methylation alone
        self.repressive[AGE_DRIFT_IDX] = _clip01(
            self.repressive[AGE_DRIFT_IDX]
            + 0.4 * AGE_DRIFT_RATE * np.maximum(AGE_DRIFT_DIR, 0.0))

        # (3) reversible exposures
        if AHRR_IDX is not None:
            smoking = env.exposure("smoking", 0.0)
            self._relax_locus(AHRR_IDX,
                              target=BASELINE_METHYLATION - AHRR_MAX_SHIFT * smoking,
                              rate=AHRR_ONSET_RATE if smoking > 0 else AHRR_RECOVERY_RATE)

        if INFLAMM_IDX.size:
            stress_load = env.exposure("psychosocial_stress", max(stress - 1.0, 0.0))
            stress_load = min(stress_load, 1.0)
            self._relax_group(INFLAMM_IDX,
                              target=BASELINE_METHYLATION - INFLAMM_MAX_SHIFT * stress_load,
                              rate=INFLAMM_ONSET_RATE if stress_load > 0 else INFLAMM_RECOVERY_RATE)

    def _relax_locus(self, idx: int, target: float, rate: float) -> None:
        self.methylation[idx] += rate * (target - self.methylation[idx])
        self.methylation[idx] = _clip01(self.methylation[idx])

    def _relax_group(self, idx: np.ndarray, target: float, rate: float) -> None:
        self.methylation[idx] += rate * (target - self.methylation[idx])
        self.methylation[idx] = _clip01(self.methylation[idx])


def _clip01(x):
    return np.clip(x, 0.0, 1.0)


# ======================================================================
# Germline transmission (#20)
# ======================================================================

def _gamete_deviation(epi: Epigenome, rng: np.random.Generator,
                      policy: GermlineResetPolicy) -> np.ndarray:
    """
    One parent's surviving methylation deviation, after reprogramming.

    Per locus: with prob = reset_prob the mark is wiped (deviation 0);
    otherwise it survives, diluted to `inheritance_fidelity` of the
    parental deviation. Escaper loci reset far less often.
    """
    dev = epi.methylation - BASELINE_METHYLATION
    survives = rng.random(N_LOCI) >= policy.reset_prob_vector()
    return np.where(survives, policy.inheritance_fidelity * dev, 0.0)


def germline_transmit(mother_epi: Epigenome, father_epi: Epigenome,
                      rng: np.random.Generator,
                      policy: GermlineResetPolicy = DEFAULT_GERMLINE_POLICY
                      ) -> Epigenome:
    """
    Build a child's starting epigenome. It begins at baseline (a clean
    slate is the biological default) and receives only the rare marks that
    escaped reprogramming in BOTH gametes' averaged contribution. The
    child's epigenetic age is 0: age drift does not transmit.
    """
    child = Epigenome.default()
    dev = 0.5 * (_gamete_deviation(mother_epi, rng, policy)
                 + _gamete_deviation(father_epi, rng, policy))
    child.methylation = _clip01(BASELINE_METHYLATION + dev)
    return child


# ======================================================================
# Introspection / benchmark helpers
# ======================================================================

def locus_class(symbol: str) -> MarkClass:
    idx = _symbol_idx(symbol)
    if idx is not None and IS_ESCAPER[idx]:
        return MarkClass.GERMLINE_ESCAPER
    if idx is not None and idx in set(AGE_DRIFT_IDX.tolist()):
        return MarkClass.AGE_DRIFT
    return MarkClass.SOMATIC_REVERSIBLE


def summary() -> str:
    lines = [
        "Epigenome layer (roadmap #15-#20)",
        f"  loci                : {N_LOCI}",
        f"  age-drift loci      : {len(AGE_DRIFT_IDX)} (irreversible clock, #17)",
        f"  pro-inflammatory    : {INFLAMM_IDX.size} loci respond to chronic stress",
        f"  smoking target      : AHRR (idx {AHRR_IDX}, hypomethylation, reversible)",
        f"  early-life target   : NR3C1 (idx {NR3C1_IDX}, developmental)",
        f"  prenatal target     : IGF2 (idx {IGF2_IDX}, developmental + escaper)",
        f"  germline escapers   : {ESCAPER_SYMBOLS}",
        f"  reset policy        : base {DEFAULT_GERMLINE_POLICY.base_reset_prob}, "
        f"escaper {DEFAULT_GERMLINE_POLICY.escaper_reset_prob}, "
        f"fidelity {DEFAULT_GERMLINE_POLICY.inheritance_fidelity}",
    ]
    return "\n".join(lines)
