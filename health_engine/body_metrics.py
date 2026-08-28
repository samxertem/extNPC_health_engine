"""
Derived anthropometry: what the two appended traits mean in real units.
=======================================================================

`sitting_height_ratio` (item E5) and `lean_mass_fraction` (item E4) are both
SCALE-FREE by design, and that design decision is what this module exists to
pay off. A ratio cannot be read off a chart or compared against a measured
population; centimetres and kilograms can. So the traits stay dimensionless
where they are calibrated, and everything with a unit on it is DERIVED here,
in one place, by identities that hold exactly.

WHY SCALE-FREE IN THE FIRST PLACE, since it is the question a reader asks.
Both traits split a quantity the engine already models. Modelling the parts
directly instead would model the whole thing twice:

  * a leg LENGTH is mostly `height_cm` again, so a body-shape channel driven
    from it would apply stature twice over;
  * a fat-free mass INDEX is a second mass trait uncorrelated with `bmi`, and
    fat mass index = BMI - FFMI then goes NEGATIVE for 5.9% of villagers
    under this engine's own distributions. Computed, not feared; the note on
    `lean_mass_fraction` carries the arithmetic.

As fractions, both components are non-negative by construction and both
identities below close exactly, which is what makes them testable rather than
merely plausible.

THE TWO IDENTITIES, and both are exact rather than approximate:

    sitting_height + leg_length              == stature
    fat_free_mass_index + fat_mass_index     == bmi

The second is VanItallie et al. 1990, who introduced FFMI and FMI precisely so
that body composition could be expressed in BMI's own units and added back up.
That is why the composition is reported in indices as well as kilograms: the
index is the form that composes with the trait the engine already calibrates.

WHAT THIS MODULE IS NOT. It is not a body-composition MEASUREMENT model. There
is no hydration term, no bone mineral compartment, no age or sex adjustment,
and `lean_mass_fraction` itself carries no sex dimorphism -- a real and
declared limitation, since fat-free fraction differs between the sexes by far
more than the trait's own sd, and item E1 records that this engine has no
stature dimorphism either. Both want doing together or not at all. What this
module does is convert modelled fractions into the units a reader thinks in,
and it should never be cited as more than that.

References
----------
VanItallie TB, Yang MU, Heymsfield SB, Funk RC, Boileau RA (1990). Height-
  normalized indices of the body's fat-free mass and fat mass: potentially
  useful indicators of nutritional status. Am J Clin Nutr 52:953-959.
  [FFMI and FMI, and the identity FFMI + FMI = BMI]
"""

from __future__ import annotations

from typing import Dict, Mapping, Optional

__all__ = ["body_segments", "body_composition", "metrics_for"]


def body_segments(height_cm: float, sitting_height_ratio: float) -> Dict[str, float]:
    """Split stature into trunk and leg, in centimetres.

    `sitting_height` is crown to seat and `leg_length` is the subischial
    remainder, which is the standard decomposition and the reason the ratio is
    reported against stature rather than against leg length: the two parts add
    back to the whole with no residual.
    """
    stature = float(height_cm)
    ratio = float(sitting_height_ratio)
    sitting = stature * ratio
    return {
        "stature_cm": stature,
        "sitting_height_cm": sitting,
        "leg_length_cm": stature - sitting,
        "sitting_height_ratio": ratio,
    }


def body_composition(bmi: float, lean_mass_fraction: float,
                     height_cm: float) -> Dict[str, float]:
    """Split body mass into fat-free and fat, in kilograms and in BMI units.

    THE MASS COMES FROM BMI AND STATURE, not from a separate mass trait,
    because the engine does not have one: mass = bmi * height_m^2 is the
    definition of BMI rearranged, so this introduces no new assumption. It
    does mean every kilogram here inherits whatever `bmi` and `height_cm` are
    worth, which is the honest place for that uncertainty to sit.

    Both compartments are non-negative for any fraction in [0, 1], which is
    the whole reason the trait is a fraction, and the fraction is clipped to
    [0.50, 0.95] at the trait anyway.
    """
    height_m = float(height_cm) / 100.0
    if height_m <= 0.0:
        raise ValueError(f"height_cm must be positive, got {height_cm!r}")

    bmi = float(bmi)
    lean_fraction = float(lean_mass_fraction)
    mass = bmi * height_m * height_m
    lean = mass * lean_fraction
    fat = mass - lean

    return {
        "body_mass_kg": mass,
        "lean_mass_kg": lean,
        "fat_mass_kg": fat,
        # The indices, which are the forms that add up to BMI exactly.
        "fat_free_mass_index": lean / (height_m * height_m),
        "fat_mass_index": fat / (height_m * height_m),
        "body_fat_percent": 100.0 * (1.0 - lean_fraction),
        "lean_mass_fraction": lean_fraction,
    }


def metrics_for(phenotype: Mapping[str, object]) -> Optional[Dict[str, float]]:
    """Everything derivable from one villager's phenotype, or None.

    Returns None rather than raising when a trait is missing, because a
    phenotype from a bundle exported before these traits existed is a
    legitimate input and a viewer asking for a row it cannot have should get
    no row rather than an exception. A partial answer is not offered: half a
    composition next to a full one in the same table is worse than neither.
    """
    needed = ("height_cm", "bmi", "sitting_height_ratio", "lean_mass_fraction")
    if any(phenotype.get(key) is None for key in needed):
        return None

    out = body_segments(float(phenotype["height_cm"]),
                        float(phenotype["sitting_height_ratio"]))
    out.update(body_composition(float(phenotype["bmi"]),
                                float(phenotype["lean_mass_fraction"]),
                                float(phenotype["height_cm"])))
    return out
