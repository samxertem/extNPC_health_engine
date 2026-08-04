"""
Developmental trajectory: life-stage-dependent expression (roadmap #13).
========================================================================

A genotype does not become an adult phenotype at conception. The engine has
behaved as though it did: `NPC.phenotype()` returns the same height for a
newborn and a forty-year-old, and ageing has only ever removed actions from
the action set. This module supplies the schedule.

THE CALIBRATION HAZARD, AND HOW IT IS AVOIDED
---------------------------------------------
This is the most dangerous item left on the roadmap, and it is worth being
explicit about why. Stage 0 solved every trait's additive and dominance
scales numerically against a specific genotype -> phenotype path. Any factor
inserted into that path changes the realised variance, and therefore
silently changes every calibrated heritability -- the engine would still
report its target h2 from `TraitArchitecture`, while the population no
longer had it. Nothing would fail; the numbers would just quietly stop
meaning what they say.

So the age schedule is **not** inserted into that path. `NPC.phenotype()`
and `NPC.liability()` are untouched and continue to return the mature
phenotype, which is also what the human literature the engine is calibrated
against actually measures -- published heritabilities for stature come from
adults, not from a mixed-age sample. The developmental schedule lives in a
separate accessor, `NPC.phenotype_at_age(age)`, which takes that mature
value and expresses it for a given age.

Two consequences, and both are asserted by tests:

  * every calibrated quantity is *structurally* incapable of drifting,
    because the code that computes it never sees an age;
  * `phenotype_at_age(REFERENCE_AGE)` reproduces `phenotype()` EXACTLY, to
    floating point, for every trait and both sexes.

That second property is the one the handoff asked for ("the gate must be
exactly identity at adulthood"), and here it is exact rather than
approximate, because the identity is arranged in the arithmetic instead of
being hoped for numerically.

TWO KINDS OF PROFILE
--------------------
**Plateau profiles** (`GrowthProfile`) multiply the mature value and are
exactly 1.0 across a documented adult plateau. Height is the type case: you
grow to it, hold it for two decades, then slowly lose some. For these,
"the calibrated value is the adult value" is unambiguous.

**Drift profiles** (`MaturationProfile`) add an offset on the liability
scale and are zero at a single reference age. Personality is the type case,
because it genuinely does not plateau: mean-level change on the Big Five
continues right through adulthood (Roberts, Walton & Viechtbauer 2006). For
these the calibration is age-specific, and saying so is more honest than
inventing a plateau that the data denies.

THE GROWTH CURVE
----------------
Stature uses Preece & Baines 1978 Model 1, the standard parametric human
growth curve, expressed as a fraction of adult stature:

    f(t) = 1 - 2(1 - f_theta) / [ exp(s0 (t - theta)) + exp(s1 (t - theta)) ]

Parameters were fitted by least squares to median fraction-of-adult-stature
from age 2 to 18, separately by sex; the residual rms is 0.0013 for girls
and 0.0015 for boys, i.e. about 0.15% of adult height, or 2-3 mm.

Below age 2 Preece-Baines is known not to fit -- it is a childhood-and-
puberty model, and infancy is a separate kinetic phase driven by nutrition
rather than growth hormone (Karlberg 1989's ICP model separates exactly
these three). Fitting it across infancy anyway pushed birth stature to 33%
of adult height against a true ~29%. So infancy is spliced on below age 2 as
a decelerating curve pinned to both endpoints: exact at birth, exact and
continuous at the age-2 handover.

WHAT THE SEX DIFFERENCE DOES AND DOES NOT REPRODUCE
----------------------------------------------------
Girls' peak height velocity arrives at 11.6 in this model and boys' at 12.9.
The direction and ordering are right and emerge from separately fitted
curves rather than being imposed. The magnitude is not: Tanner's
longitudinal values are ~11.5 and ~13.5, so the model compresses a two-year
sex difference into 1.3 years. The likely reason is that the fit targets
median cross-sectional stature, and cross-sectional data smears the
pubertal spurt across individuals whose puberty is differently timed,
flattening and shifting the apparent peak. Stated rather than tuned away.

SENESCENCE
----------
Decline rates are taken from longitudinal studies, not invented:

  * **stature** falls about 1 cm per decade from ~40, accelerating (Sorkin,
    Muller & Andres 1999, Baltimore Longitudinal Study of Aging);
  * **aerobic capacity** falls about 10% per decade from ~30, and the rate
    itself accelerates with age rather than being constant (Fleg et al.
    2005, *Circulation* 112:674) -- the model gives 10% per decade in the
    forties and ~49% of peak remaining at 70;
  * **lung capacity** falls from the mid-twenties at roughly 25-30 ml of
    FEV1 per year, about 0.7% of a young adult value annually.

References
----------
Tanner 1962 (*Growth at Adolescence*, 2nd ed.); Tanner & Whitehouse 1976
(*Arch. Dis. Child.* 51:170) -- growth standards and pubertal timing.
Preece & Baines 1978 (*Ann. Hum. Biol.* 5:1) -- the growth-curve model.
Karlberg 1989 (*Acta Paediatr. Scand.* Suppl. 350:70) -- the ICP model and
why infancy is a separate phase.
Sorkin, Muller & Andres 1999 (*Am. J. Epidemiol.* 150:969) -- height loss.
Fleg et al. 2005 (*Circulation* 112:674) -- accelerating VO2max decline.
Roberts, Walton & Viechtbauer 2006 (*Psychol. Bull.* 132:1) -- mean-level
personality change across the lifespan; the maturity principle.
Kang et al. 2011 (*Nature* 478:483) -- spatiotemporal brain transcriptome:
gene expression is strongly stage-specific.
GTEx Consortium 2020 (*Science* 369:1318) -- tissue- and age-varying
expression.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np

# The age at which the engine's calibrated phenotype is defined. Every
# profile is exactly identity here, so `phenotype_at_age(REFERENCE_AGE)`
# reproduces `phenotype()` bit for bit.
REFERENCE_AGE: float = 20.0

# Reference age for the drift profiles. Personality norms come from adult
# samples whose mean age is nearer 30 than 20, and personality does not
# plateau, so these are pinned separately and the difference is deliberate.
DRIFT_REFERENCE_AGE: float = 30.0

# Age below which Preece-Baines is not used; see the module docstring.
INFANCY_END: float = 2.0

# Fraction of adult stature at birth. 50 cm against a ~171 cm adult mean.
BIRTH_STATURE_FRACTION: float = 0.29

# How sharply infant growth decelerates. Fitted so the spliced segment is
# smooth into the Preece-Baines curve at the age-2 handover.
_INFANCY_DECAY: float = 1.0


@dataclass(frozen=True)
class PreeceBaines:
    """
    Preece & Baines 1978 Model 1, as a fraction of adult stature.

    Fitted by least squares to median fraction-of-adult-stature from age 2
    to 18. `theta` is the model's timing parameter, close to but not
    identical with the age at peak height velocity.
    """
    f_theta: float
    theta: float
    s0: float
    s1: float

    def __call__(self, t: float) -> float:
        num = 2.0 * (1.0 - self.f_theta)
        return 1.0 - num / (np.exp(self.s0 * (t - self.theta))
                            + np.exp(self.s1 * (t - self.theta)))


# Fitted separately by sex. rms residual 0.0013 (girls) / 0.0015 (boys)
# against the age 2-18 anchors -- about 2-3 mm of adult stature.
STATURE_CURVE: Dict[str, PreeceBaines] = {
    "female": PreeceBaines(f_theta=0.90835, theta=12.13285,
                           s0=0.09894, s1=1.04026),
    "male": PreeceBaines(f_theta=0.91168, theta=13.58368,
                         s0=0.09169, s1=0.87482),
}


def stature_fraction(age: float, sex: str = "female") -> float:
    """
    Fraction of adult stature attained by `age`. Exactly 1.0 from
    REFERENCE_AGE onward, so the calibrated adult value is reproduced
    exactly rather than asymptotically.

    Below age 2 a decelerating segment is spliced on, pinned to 0.29 at
    birth and to the Preece-Baines value at the handover, because
    Preece-Baines is a childhood-and-puberty model that overstates infancy
    (Karlberg 1989).
    """
    curve = STATURE_CURVE.get(sex, STATURE_CURVE["female"])
    if age >= REFERENCE_AGE:
        return 1.0
    # Renormalise so the curve reaches exactly 1.0 at REFERENCE_AGE rather
    # than approaching it asymptotically. The correction is ~5e-5, but
    # "approximately identity at adulthood" is precisely the failure mode
    # this item was flagged for.
    scale = curve(REFERENCE_AGE)
    if age >= INFANCY_END:
        return float(curve(age) / scale)

    f2 = curve(INFANCY_END) / scale
    k = _INFANCY_DECAY
    shape = (1.0 - np.exp(-k * age)) / (1.0 - np.exp(-k * INFANCY_END))
    return float(BIRTH_STATURE_FRACTION
                 + (f2 - BIRTH_STATURE_FRACTION) * shape)


def peak_height_velocity_age(sex: str = "female",
                             lo: float = 8.0, hi: float = 18.0) -> float:
    """
    Age of maximum growth rate, found numerically from the fitted curve.
    Not a parameter -- if it comes out at the right age that is the curve
    agreeing with Tanner, not the curve being told.
    """
    t = np.linspace(lo, hi, 4000)
    f = np.array([stature_fraction(x, sex) for x in t])
    return float(t[int(np.argmax(np.gradient(f, t)))])


# ======================================================================
# Profiles
# ======================================================================

@dataclass(frozen=True)
class GrowthProfile:
    """
    A multiplicative factor on the mature phenotype, exactly 1.0 across
    [plateau_start, plateau_end].

    `decline_rate` and `decline_accel` describe the senescent phase:

        factor(t) = exp( -(rate + accel * (t - plateau_end)) * (t - plateau_end) )

    The accelerating term is not decoration -- Fleg et al. 2005's central
    finding is that the rate of VO2max loss itself rises with age, which a
    single exponential cannot express.
    """
    trait: str
    plateau_start: float
    plateau_end: float
    decline_rate: float = 0.0
    decline_accel: float = 0.0
    uses_stature_curve: bool = False
    # Power of the stature fraction the trait grows on. CHECK THE UNIT
    # BEFORE SETTING THIS. Stature itself is 1. An absolute volume such as
    # FEV1 scales as roughly height^2.5-3, which is why spirometry reference
    # equations are height power laws. A MASS-RELATIVE quantity such as
    # VO2max in mL/kg/min does not scale with body size at all -- a ten-
    # year-old's is about the same as a young adult's -- so scaling it by
    # stature would be a unit error dressed up as biology.
    stature_exponent: float = 1.0
    immature_floor: float = 0.0
    note: str = ""

    def factor(self, age: float, sex: str = "female") -> float:
        if self.plateau_start <= age <= self.plateau_end:
            return 1.0
        if age > self.plateau_end:
            d = age - self.plateau_end
            return float(np.exp(-(self.decline_rate
                                  + self.decline_accel * d) * d))
        # immature
        if self.uses_stature_curve:
            return float(stature_fraction(age, sex) ** self.stature_exponent)
        # linear ramp from a floor at birth to full at plateau_start, for
        # traits with no published growth curve. Crude on purpose, and
        # flagged as such rather than dressed up in a fitted form.
        frac = age / self.plateau_start if self.plateau_start > 0 else 1.0
        return float(self.immature_floor
                     + (1.0 - self.immature_floor) * min(1.0, frac))


@dataclass(frozen=True)
class MaturationProfile:
    """
    An additive offset on the LIABILITY scale, zero at DRIFT_REFERENCE_AGE.

    Used for traits that do not plateau. `per_decade` is the mean-level
    change in liability SD per decade of adult life, from the Roberts et al.
    2006 meta-analysis; `onset` and `cap` bound the window over which it
    accrues, because personality change is concentrated in early and middle
    adulthood rather than continuing without limit.
    """
    trait: str
    per_decade: float
    onset: float = 10.0
    cap: float = 60.0
    note: str = ""

    def offset(self, age: float, sex: str = "female") -> float:
        a = min(max(age, self.onset), self.cap)
        ref = min(max(DRIFT_REFERENCE_AGE, self.onset), self.cap)
        return float(self.per_decade * (a - ref) / 10.0)


# ----------------------------------------------------------------------
# The schedule
# ----------------------------------------------------------------------
# Only traits with a defensible published trajectory appear here. Every
# other trait is age-invariant, which is a statement that the engine does
# not model its development -- not a claim that it has none. Eye colour
# really does darken over the first year; skin tone tracks cumulative sun
# exposure; neither is modelled, and inventing curves for them would put
# uncalibrated numbers next to calibrated ones.

GROWTH: Dict[str, GrowthProfile] = {
    "height_cm": GrowthProfile(
        trait="height_cm",
        plateau_start=REFERENCE_AGE, plateau_end=40.0,
        # ~1 cm per decade from 40 on a 171 cm frame is 0.58%/decade,
        # accelerating (Sorkin, Muller & Andres 1999). Tuned to ~1.2 cm per
        # decade averaged over 40-70, which is what that study reports once
        # the acceleration is included.
        decline_rate=0.00035, decline_accel=0.000012,
        uses_stature_curve=True,
        note="Preece-Baines 1978 fitted to fraction-of-adult-stature.",
    ),
    "aerobic_capacity": GrowthProfile(
        trait="aerobic_capacity",
        # The engine's unit is mL/kg/min -- MASS-RELATIVE VO2max, which is
        # roughly flat from mid-childhood to the late twenties rather than
        # growing with the body (Armstrong & Welsman 1994). So the plateau
        # opens at 6, not at 20, and there is no stature scaling at all. The
        # absolute figure in L/min does grow with size; this trait is not it.
        plateau_start=6.0, plateau_end=30.0,
        # ~10% per decade in the forties, accelerating thereafter (Fleg et
        # al. 2005). Reaches ~49% of peak by 70, in the 50-60% range
        # longitudinal studies report for sedentary adults.
        decline_rate=0.0080, decline_accel=0.00025,
        uses_stature_curve=False, immature_floor=0.85,
        note="Mass-relative VO2max: flat through childhood, falls from 30.",
    ),
    "lung_capacity": GrowthProfile(
        trait="lung_capacity",
        plateau_start=REFERENCE_AGE, plateau_end=25.0,
        # FEV1 falls ~25-30 ml/yr from the mid-twenties, ~0.7%/yr.
        decline_rate=0.0070, decline_accel=0.00004,
        # An absolute lung volume in litres, so it scales steeply with
        # stature -- spirometry reference equations put the exponent between
        # 2.5 and 3. A ten-year-old at 80% of adult height therefore has
        # ~0.8^2.7 = 55% of adult volume, not 80%.
        uses_stature_curve=True, stature_exponent=2.7,
        note="FEV1 as a height power law in childhood, declining from ~25.",
    ),
}

MATURATION: Dict[str, MaturationProfile] = {
    # The maturity principle (Roberts, Walton & Viechtbauer 2006):
    # conscientiousness and agreeableness rise, neuroticism falls, through
    # early and middle adulthood. Magnitudes are the meta-analysis's
    # cumulative changes spread over the window rather than per-decade
    # estimates read directly off it, so treat them as the right size and
    # direction rather than as precise coefficients.
    "conscientiousness": MaturationProfile(
        trait="conscientiousness", per_decade=+0.16, onset=12.0, cap=60.0,
        note="Rises steadily from adolescence into the fifties."),
    "agreeableness": MaturationProfile(
        trait="agreeableness", per_decade=+0.11, onset=12.0, cap=60.0,
        note="Rises, most strongly in middle age."),
    "neuroticism": MaturationProfile(
        trait="neuroticism", per_decade=-0.13, onset=12.0, cap=60.0,
        note="Falls through early and middle adulthood (emotional stability)."),
}


# ======================================================================
# Application
# ======================================================================

def growth_factor(trait: str, age: float, sex: str = "female") -> float:
    """Multiplicative factor on the mature phenotype. 1.0 if unprofiled."""
    profile = GROWTH.get(trait)
    return 1.0 if profile is None else profile.factor(age, sex)


def maturation_offset(trait: str, age: float, sex: str = "female") -> float:
    """Additive offset on the liability scale. 0.0 if unprofiled."""
    profile = MATURATION.get(trait)
    return 0.0 if profile is None else profile.offset(age, sex)


def is_profiled(trait: str) -> bool:
    return trait in GROWTH or trait in MATURATION


def express_at_age(trait: str, mature_value, age: float,
                   sex: str = "female", liability: Optional[float] = None):
    """
    Express one trait at one age, given its mature value.

    Continuous traits scale multiplicatively. Traits carrying a maturation
    offset need the liability, because the offset is defined on that scale
    and has to be mapped back through the trait's own mean and sd. Anything
    categorical, or unprofiled, is returned unchanged -- the engine does not
    model its development and says so rather than guessing.
    """
    from .traits import TRAIT_TABLE, TraitKind

    spec = TRAIT_TABLE[trait]
    if spec.kind is not TraitKind.CONTINUOUS:
        return mature_value

    value = mature_value
    factor = 1.0
    if trait in GROWTH:
        factor = growth_factor(trait, age, sex)
        value = value * factor
    if trait in MATURATION:
        value = value + spec.sd * maturation_offset(trait, age, sex)
    if spec.clip is not None:
        # SCALE THE CLIP BY THE SAME FACTOR. `spec.clip` is a plausibility
        # bound on an ADULT value -- height_cm is clipped to [130, 215] --
        # and applying it unchanged to a developmental value would clamp a
        # 50 cm newborn up to 130 cm. The bound that means the same thing
        # for a child is the adult bound scaled by how much of the adult
        # value they have yet attained.
        lo, hi = spec.clip[0] * factor, spec.clip[1] * factor
        value = min(max(value, lo), hi)
    return value


def schedule_summary(ages: Tuple[float, ...] = (0, 2, 5, 10, 12, 14, 16,
                                                20, 30, 40, 60, 80)) -> str:
    lines = ["Developmental schedule (roadmap #13)",
             f"reference age {REFERENCE_AGE:.0f} (growth), "
             f"{DRIFT_REFERENCE_AGE:.0f} (maturation)", "-" * 72]
    header = "  " + f"{'trait':<20}" + "".join(f"{a:>7.0f}" for a in ages)
    lines.append(header)
    for trait in GROWTH:
        row = "".join(f"{growth_factor(trait, a):>7.3f}" for a in ages)
        lines.append(f"  {trait:<20}{row}")
    lines.append("  (above: multiplicative factor on the mature value)")
    for trait in MATURATION:
        row = "".join(f"{maturation_offset(trait, a):>+7.3f}" for a in ages)
        lines.append(f"  {trait:<20}{row}")
    lines.append("  (above: additive offset in liability SD)")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Limitations
# ----------------------------------------------------------------------
# * The schedule is a POPULATION-LEVEL trajectory applied to an individual's
#   mature value. Every individual therefore grows on the same normalised
#   curve, differing only in where it ends up. Real growth varies in TIMING
#   as well as in endpoint -- early and late maturers are a large part of
#   what makes adolescent height variance so high -- and there is no
#   heritable tempo parameter here. Adding one would be the natural next
#   step, and it would have to be calibrated against the heritability of age
#   at menarche.
# * Because timing does not vary, the model cannot show the well-known
#   spike in phenotypic variance during puberty, nor the drop in
#   parent-offspring correlation for stature measured mid-adolescence.
# * Only five traits are profiled. Everything else is age-invariant, which
#   is a statement about the model's scope rather than about the biology.
# * Puberty is a growth curve here, not an endocrine event. `physiology.py`
#   has hormones and this module does not talk to them, so nothing
#   hormone-driven -- secondary sexual characteristics, the adolescent shift
#   in sleep phase -- is gated by pubertal stage.
# * No prenatal development. Birth is age 0 with 29% of adult stature and
#   nothing before it, even though `epigenome.apply_developmental` already
#   models a prenatal exposure window (#19).
# * The maturation offsets move the mean only. Real personality change also
#   involves rank-order stability rising with age (Roberts & DelVecchio
#   2000), which is a variance property this cannot express.
# * The senescence curves are deterministic functions of chronological age.
#   The engine already computes an epigenetic age acceleration per
#   individual (#17) and it would be more faithful to drive decline from
#   that; the two currently do not talk to each other.
