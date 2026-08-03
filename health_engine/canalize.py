"""
Canalization: developmental buffering and cryptic variation (roadmap #14b).
==========================================================================

The reaction-norm half of roadmap #14 already exists: `traits.Environment`
shifts each trait's environmental mean AND the mean of its GxE input, so two
genotypes can cross over as the environment moves. That is the norm of
reaction. This module adds the half that was missing -- Waddington's
**canalization**.

The idea (Waddington 1942; Schmalhausen 1949, independently): development is
*buffered*. A wild-type organism produces much the same phenotype across a
range of genotypes and environments, because developmental pathways are
self-correcting. Genetic differences that would otherwise show up are held
below the surface -- **cryptic genetic variation**. Push the system hard
enough and the buffer fails, and that hidden variation becomes visible all
at once.

This is not just theory. HSP90 is the canonical molecular capacitor:
impairing it in *Drosophila* (Rutherford & Lindquist 1998) or *Arabidopsis*
(Queitsch et al. 2002) releases an array of morphological variants that were
present genetically all along, and were invisible until the buffer broke.

What is modelled
----------------
A single expressivity factor k on the **genetic** part of the liability:

    k(stress) = 1 + capacity * max(0, stress - THRESHOLD)

    G_expressed = k * G          (additive + dominance)
    I_expressed = k * I          (epistasis)

with the environmental residual and the GxE term left alone. Two properties
follow, and both are asserted by tests:

  * **The mean is untouched.** `genotypic_value` already returns a
    mean-centred G (it subtracts E[G]), and the epistatic term is built from
    centred dosages, so E[G] = E[I] = 0 and scaling them cannot move the
    population mean. Canalization moves *variance*, exactly as the epigenome
    (#16) and GRN (#8) layers turned out to.

  * **Genetic variance scales as k^2, so heritability rises under stress.**
    V_A and V_I scale by k^2 while V_E does not, giving the closed form

        h2(stress) = k^2 h2_0 / (k^2 h2_0 + 1 - h2_0)

    which `validation.canalization_release` checks against measurement.

THRESHOLD is 1.0, which is `Environment.stress` for the neutral environment.
So k = 1 exactly in every calibrated setting and this layer is bit-for-bit
inert by default -- the same discipline every layer since Stage 0 has used.
Note what that implies scientifically, because it is the honest reading:
**the engine's calibrated heritabilities ARE the canalized ones.** Published
human h2 estimates come from ordinary environments, so treating the baseline
as the buffered state is correct; stress then *de*canalizes upward from it,
rather than the baseline being some unbuffered ideal.

Which way does stress push h2?
------------------------------
Upward, here. That is a real and somewhat counter-intuitive prediction, and
it does have human support: the heritability of BMI is higher in obesogenic
environments than in restrictive ones, and gene-environment studies generally
find more genetic variance expressed under stressful conditions. It is not
universal -- some traits show the opposite -- so this is modelled as a
mechanism with a direction, not as a claim about all traits.

Calibration -- stated plainly
-----------------------------
`DEFAULT_CAPACITY` is **not calibrated against human data, because the data
to calibrate it does not exist.** The HSP90 experiments are qualitative
(variants appear) and are in flies and plants; nobody has a human
decanalization coefficient. The value here produces a visible but not
dominant effect (~1.6x genetic variance at stress 2.0), and the *testable*
claim is the qualitative one Waddington actually made -- variance is buffered
below threshold and released above it -- plus the internal k^2 consistency.
Do not read the magnitude as an empirical estimate.

References
----------
Waddington 1942 (*Nature* 150:563, "Canalization of development");
Schmalhausen 1949 (*Factors of Evolution*); Rutherford & Lindquist 1998
(*Nature* 396:336, HSP90 as a capacitor for morphological evolution);
Queitsch, Sangster & Lindquist 2002 (*Nature* 417:618); Gibson & Dworkin
2004 (*Nat. Rev. Genet.* 5:681, uncovering cryptic genetic variation).
"""

from __future__ import annotations

from typing import Dict, Optional

from .traits import ARCHITECTURE, Environment

# Stress at or below this is fully buffered. 1.0 is the neutral
# environment's `stress`, so every calibrated setting sits exactly here and
# the layer is inert by default.
CANALIZATION_THRESHOLD: float = 1.0

# Extra genetic expressivity per unit of stress above threshold.
# NOT an empirical estimate -- see the module docstring.
DEFAULT_CAPACITY: float = 0.30

# Per-trait buffering capacity. A more strongly canalized trait hides more
# cryptic variation, so it releases more when the buffer breaks.
#
# The ordering below is defensible from developmental biology even though the
# magnitudes are not calibrated: stature is famously buffered (catch-up growth
# after illness or famine returns a child to its trajectory -- Prader, Tanner
# & von Harnack 1963), and craniofacial and organ-level traits are the classic
# targets of stabilizing selection. Personality is left at the default: there
# is no evidence it is developmentally canalized in this sense, and inventing
# a number for it would be worse than using the generic one.
CAPACITY_BY_TRAIT: Dict[str, float] = {
    "height_cm": 0.45,              # catch-up growth is the textbook buffer
    "nose_width": 0.40,
    "nose_pointiness": 0.40,
    "chin_protrusion": 0.40,
    "cheekbone_prominence": 0.40,
    "nasion_position": 0.40,
    "insulin_sensitivity": 0.35,
    "bp_set_point": 0.35,
    "lung_capacity": 0.35,
    "immune_resilience": 0.35,
}


def canalization_factor(stress: float,
                        trait: Optional[str] = None,
                        capacity: Optional[float] = None) -> float:
    """
    The genetic-expressivity multiplier k for one trait at a given stress.

    Exactly 1.0 at or below `CANALIZATION_THRESHOLD`, so a neutral
    environment leaves the calibrated engine untouched. Above it, k grows
    linearly and the genetic variance it multiplies grows as k^2.
    """
    if capacity is None:
        capacity = (DEFAULT_CAPACITY if trait is None
                    else CAPACITY_BY_TRAIT.get(trait, DEFAULT_CAPACITY))
    excess = stress - CANALIZATION_THRESHOLD
    if excess <= 0.0:
        return 1.0
    return 1.0 + capacity * excess


def factors_for_environment(env: Environment) -> Dict[str, float]:
    """k for every trait in the architecture under one environment."""
    return {name: canalization_factor(env.stress, name)
            for name in ARCHITECTURE}


def is_decanalizing(env: Environment) -> bool:
    """True when this environment exceeds the buffering threshold at all."""
    return env.stress > CANALIZATION_THRESHOLD


def expected_heritability(h2_baseline: float, k: float) -> float:
    """
    Closed form for the heritability released by decanalization.

    Genetic variance scales by k^2, environmental variance does not:

        h2(k) = k^2 h2_0 / (k^2 h2_0 + (1 - h2_0))

    A reference curve for the validation harness and the figure. Nothing in
    the trait layer computes it -- it is measured from realised variances.
    """
    g = k * k * h2_baseline
    return g / (g + (1.0 - h2_baseline))


# ----------------------------------------------------------------------
# Limitations
# ----------------------------------------------------------------------
# * The capacity constants are uncalibrated engineering values. The
#   qualitative claim (buffered below threshold, released above) is what is
#   being modelled and tested; the magnitude is not an empirical estimate.
# * Buffering here is a function of the DEVELOPMENTAL environment
#   (`NPC.birth_environment`), which is the Waddington reading -- the buffer
#   operates during development. Chronic adult stress does not decanalize an
#   already-developed adult in this model.
# * Real decanalization can shift the mean too (genetic assimilation, where a
#   stress-induced phenotype becomes constitutive after selection). This model
#   is deliberately mean-preserving, so assimilation is out of scope.
# * There is no genetic variation IN canalization itself. Buffering capacity
#   is a per-trait constant, not a heritable modifier, so canalization cannot
#   evolve here -- which is precisely what Waddington's selection experiments
#   were about.
# * V_GxE is not scaled, to avoid confounding two environment-response
#   mechanisms that the engine models separately.
