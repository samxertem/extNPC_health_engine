"""
Fluctuating asymmetry: developmental noise made visible (item E6).
==================================================================

Every other appearance channel in this engine answers "what did the genome
say". This one answers something different and, for a thesis, more
interesting: **what did development fail to control**.

THE DISTINCTION THAT DEFINES THE ITEM. Van Valen 1962 separates three kinds of
left-right difference, and conflating them is the classic error:

  * **Directional asymmetry**: a consistent population-wide bias. The heart is
    on the left in almost everyone. Mean signed difference is non-zero, and it
    is developmentally PROGRAMMED, not a failure.
  * **Antisymmetry**: asymmetry is the rule but its direction is not, giving a
    bimodal distribution. The fiddler crab's large claw.
  * **Fluctuating asymmetry (FA)**: small, random departures from a symmetric
    ideal, **signed, mean zero, unimodal**. Both sides carry the same genome
    and grew in the same environment, so the difference between them is what
    developmental noise the organism could not buffer away.

Only the third is modelled here, and the distribution is mean-zero normal by
construction, which is what makes the claim honest rather than decorative:
`test_asymmetry.py` asserts the population mean signed asymmetry is
indistinguishable from zero per feature, because a drift away from zero would
have quietly turned FA into directional asymmetry and nobody would see it in
a picture.

WHY FA IS NOT A HERITABLE TRAIT, and why this module is not just another
entry in `TRAIT_TABLE`. FA is noise. What can be inherited is the CAPACITY TO
BUFFER it, so the engine models `developmental_instability` as a trait with a
low heritability and then draws the asymmetry itself fresh for each
individual, scaled by that trait. The consequence is a real, checkable
prediction rather than an assumption: **the realised heritability of FA comes
out far below the heritability of the instability trait**, because most of the
variance in any one measurement is the fresh draw. That matches a literature
where FA heritability estimates cluster near zero and the higher published
figures have been strongly criticised (Moller & Thornhill 1997 report about
0.19 in meta-analysis; Whitlock & Fowler 1997 and Leamy & Klingenberg 2005
dispute both the estimate and the method). The engine reproduces the low
number as an OUTPUT, which is a better position than declaring it.

WHY IT CONNECTS TO `canalize.py`, which is the other half of the value. FA is
the classic bioindicator of developmental stress (Parsons 1992): a stressed
population is a less well buffered one and shows more asymmetry. `canalize.py`
already models exactly that buffer, with k(stress) = 1 at or below the neutral
threshold and rising above it, so FA scales with the SAME k that releases
cryptic genetic variance. That is one mechanism producing two observable
consequences, which is worth considerably more than two mechanisms producing
one each. At neutral stress k is exactly 1.0 and this layer is inert by
default, in line with every layer since Stage 0.

WHAT IS MEASURED AND WHAT IS CHOSEN, since the module is useless if a reader
has to guess:

  * MEASURED (in Blender, `mpfb/probe_asymmetry.py`): that a signed asymmetry
    reaches the mesh through the `.mhm` boundary at all; that MPFB's `-l` and
    `-r` targets are exact mirrors, giving head-centroid shifts of
    +0.00085744 m and -0.00085744 m at full weight; and that the effect is
    linear in the weight, a half weight giving exactly half the shift. The
    neutral human measures exactly 0.0, so any asymmetry on screen is ours.
  * MEASURED, end to end on a real villager: exporting one with and without
    the asymmetry lines and diffing the two baked meshes vertex by vertex
    moves 8,584 of 13,380 vertices, mean 0.17 mm and max 1.16 mm, for a WELL
    BUFFERED individual at instability z = -1.39. A villager at the population
    mean is about 1.5 times that. Real facial fluctuating asymmetry is
    reported in landmark deviations of roughly half a millimetre to a couple
    of millimetres, so this lands inside the plausible range rather than being
    tuned to it -- which is the most that can be claimed while the scale is a
    choice.
  * MEASURED: that a villager's instability is a modelled, calibrated trait.
  * CHOSEN: `BASE_SIGMA`, the width of the asymmetry distribution in MPFB
    target units. There is no conversion from a published FA index to a
    MakeHuman target weight, because the targets are not calibrated to any
    named landmark. So the SHAPE of the distribution is the modelled claim and
    the SCALE is a rendering decision, declared here and nowhere else.
  * CHOSEN: that all 31 shipped feature pairs are driven with the same sigma.
    Real FA differs by trait, and no data here says by how much.

References
----------
Van Valen L (1962). A study of fluctuating asymmetry. Evolution 16:125-142.
  [the three-way distinction above]
Palmer AR, Strobeck C (1986). Fluctuating asymmetry: measurement, analysis,
  patterns. Annu Rev Ecol Syst 17:391-421.  [the FA indices, incl. FA1]
Parsons PA (1992). Fluctuating asymmetry: a biological monitor of environmental
  and genomic stress. Heredity 68:361-364.  [FA as a stress bioindicator]
Moller AP, Thornhill R (1997). A meta-analysis of the heritability of
  developmental stability. J Evol Biol 10:1-16.
Whitlock MC, Fowler K (1997); Leamy LJ, Klingenberg CP (2005). [the critiques]

VERIFY EVERY CITATION ABOVE AGAINST THE SOURCE before any of it goes in the
paper. They are recorded from knowledge, not from a fetched PDF, and this
project's standing rule is that an unverified reference is a liability.
"""

from __future__ import annotations

import math
from typing import Dict, Mapping, Optional, Sequence, Tuple

__all__ = [
    "FEATURES",
    "BASE_SIGMA",
    "INSTABILITY_LOG_SLOPE",
    "MAX_WEIGHT",
    "instability_multiplier",
    "asymmetry_sigma",
    "scale_asymmetry",
    "target_weights",
    "fa_index",
]


# The 31 matched left/right feature pairs MPFB ships, as their target stems.
#
# DECLARED AS DATA, NOT DERIVED FROM A PREFIX RULE, and the last two rows are
# why: twenty-nine of them begin `asym-` and two begin `asymm-` with a double
# m. A rule that split the family name off the front would handle one shape
# and silently drop the other, which is exactly the failure
# `test_bake_channels.py` documents from the asset side, where a prefix rule
# and a suffix rule each passed on the villagers that happened to draw the
# other shape. `test_asymmetry.py` checks this list against the install.
FEATURES: Tuple[str, ...] = (
    "asym-brown-1", "asym-brown-2",
    "asym-cheek-1", "asym-cheek-2",
    "asym-ear-1", "asym-ear-2", "asym-ear-3", "asym-ear-4",
    "asym-eye-1", "asym-eye-2", "asym-eye-3", "asym-eye-4",
    "asym-eye-5", "asym-eye-6", "asym-eye-7", "asym-eye-8",
    "asym-jaw-1", "asym-jaw-2", "asym-jaw-3",
    "asym-mouth-1", "asym-mouth-2",
    "asym-nose-1", "asym-nose-2", "asym-nose-3", "asym-nose-4",
    "asym-temple-1", "asym-temple-2",
    "asym-top-1", "asym-top-2",
    "asymm-breast-1",           # note the double m: MPFB's own spelling
    "asymm-trunk-1",            # likewise
)

# The width of the signed asymmetry distribution, in MPFB target units, for a
# villager of average developmental instability in a neutral environment.
#
# A CHOICE, and the module docstring says why it has to be. MPFB target weights
# are not calibrated to any named anthropometric landmark, so no published FA
# index converts into them. 0.12 puts about 99.7% of features inside +/- 0.36
# of neutral, which is a visible-but-not-deformed face: full weight 1.0 on one
# eye feature displaces the head centroid by 0.86 mm, measured, so a typical
# feature here moves it by about a tenth of a millimetre and the 31 of them
# together read as a face that is not quite mirror-symmetric. Which is the
# target: real faces are not, and a perfectly symmetric village is the thing
# that looks wrong.
BASE_SIGMA: float = 0.12

# How strongly the instability trait multiplies that width. Applied in the
# LOG, so the multiplier is always positive and its distribution is
# right-skewed, which is the shape FA distributions actually take: most
# individuals near the buffered baseline and a long tail of poorly buffered
# ones. At this slope a villager two sd above the mean is 1.8 times as
# asymmetric as the average, and one two sd below is 0.55 times.
#
# NOT AN EMPIRICAL ESTIMATE. It sets how much of the visible spread is
# heritable, and no measurement here constrains it.
INSTABILITY_LOG_SLOPE: float = 0.30

# Weights are clamped here. MPFB targets are authored for [0, 1] and a weight
# beyond that extrapolates a morph outside the range anyone checked, which is
# how a face becomes a horror rather than an asymmetric one. At BASE_SIGMA
# this clamps essentially nobody; it exists for the decanalized tail.
MAX_WEIGHT: float = 1.0


def instability_multiplier(instability_z: float) -> float:
    """The individual's own multiplier on the FA width.

    `developmental_instability` is a z-scored trait, so 0.0 is the population
    mean and the multiplier there is exactly 1.0. Exponential in z, for the
    positivity and skew argued at `INSTABILITY_LOG_SLOPE`.
    """
    return math.exp(INSTABILITY_LOG_SLOPE * float(instability_z))


def asymmetry_sigma(instability_z: float, k: float = 1.0) -> float:
    """The width of this villager's asymmetry distribution.

    `k` is `canalize.canalization_factor(stress)`, which is exactly 1.0 at or
    below the neutral threshold, so a calibrated run is untouched. Above it,
    the buffer is failing and asymmetry widens by the same factor that
    releases cryptic genetic variance elsewhere in the engine.
    """
    return BASE_SIGMA * instability_multiplier(instability_z) * float(k)


def scale_asymmetry(unit: Mapping[str, float], instability_z: float,
                    k: float = 1.0) -> Dict[str, float]:
    """Turn the individual's fixed unit normals into signed target weights.

    THE SPLIT BETWEEN DRAWING AND SCALING IS THE DESIGN, and it exists because
    of a circularity. The asymmetry has to be fixed at birth, or a villager's
    face changes between two reads of the same person -- the v0.2 quirk
    `EnvironmentalDeviates` was created to kill. But its WIDTH depends on
    `developmental_instability`, which is a phenotype, which depends on the
    deviates drawn at birth. So birth draws unit normals, and the width is
    applied at read time, exactly as every other trait's residual is a unit
    normal scaled by a calibrated variance later.
    """
    sigma = asymmetry_sigma(instability_z, k)
    out: Dict[str, float] = {}
    for feature in FEATURES:
        value = sigma * float(unit.get(feature, 0.0))
        out[feature] = max(-MAX_WEIGHT, min(MAX_WEIGHT, value))
    return out


def target_weights(signed: Mapping[str, float],
                   cutoff: float = 1e-4) -> Tuple[Tuple[str, float], ...]:
    """`(target name, weight)` pairs for a `.mhm`, from signed asymmetries.

    A positive value goes to the `-l` target and a negative one to `-r`, at
    the absolute weight. That mapping is only coherent because the two are
    exact mirrors, which `mpfb/probe_asymmetry.py` measured rather than
    assumed: +0.00085744 m against -0.00085744 m of head-centroid shift.

    `cutoff` drops weights too small to move a vertex. Emitting them would put
    31 lines in every `.mhm` for no visible difference, and `.mhm` files
    travel in the export bundle, which item G4 already flags for size.
    """
    lines = []
    for feature in FEATURES:
        value = float(signed.get(feature, 0.0))
        if abs(value) < cutoff:
            continue
        side = "l" if value > 0 else "r"
        lines.append((f"{feature}-{side}", abs(value)))
    return tuple(lines)


def fa_index(signed: Mapping[str, float]) -> float:
    """FA1 of Palmer & Strobeck 1986: the mean unsigned asymmetry.

    The standard summary because it is what survives the sign. The SIGNED mean
    is the quantity that must stay at zero -- a non-zero signed mean is
    directional asymmetry, a different phenomenon -- so the two are reported by
    different functions on purpose, and a caller reaching for "the asymmetry"
    gets the unsigned one.
    """
    if not FEATURES:
        return 0.0
    return sum(abs(float(signed.get(f, 0.0))) for f in FEATURES) / len(FEATURES)
