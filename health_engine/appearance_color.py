"""
Visible colour from modelled traits (item E2), and the line under it.
=====================================================================

Every villager has been beige since bodies existed, for a mechanical reason
covered in `HumanMesh.Bake`: the parts were merged into one submesh with one
material, so a person could only be one colour. This module is the other half
of the fix, the one that decides WHAT colour, and it exists so that the answer
is a derivation rather than a ramp somebody invented.

THE HONEST DIRECTION OF THE DERIVATION
--------------------------------------
The tempting shortcut is to map `skin_tone` 0..1 straight onto a hand-picked
gradient from pale to brown. That produces a plausible picture and supports no
claim at all, because the gradient is the author's taste and the trait merely
indexes it.

So the arrow is turned around. `skin_tone` places the villager on the **skin
locus**, a published path through CIE L*a*b* that real human skin occupies,
and the colour is that point converted to sRGB by the standard CIE transform.
**ITA is then MEASURED from the point, not imposed on it**, which means it can
be reported, classified and checked -- and would come out wrong if the locus
or the conversion were wrong.

    ITA = arctan((L* - 50) / b*) x 180/pi        (Chardon et al. 1991)

and the classification is Del Bino & Bernerd's:

    very light  ITA > 55      tan    10 < ITA <= 28
    light       41 < ITA <= 55   brown  -30 < ITA <= 10
    intermediate 28 < ITA <= 41  dark   ITA <= -30

WHAT IS MEASURED AND WHAT IS CHOSEN, because the distinction is the whole
point of the module and a reader must not have to guess:

  * MEASURED: that a villager's `skin_tone` is 0.35 -- that is a modelled,
    calibrated, heritable trait (h2=0.85, SLC24A5/SLC45A2/HERC2).
  * MEASURED: the ITA of the colour they get, since it is computed from the
    L*a*b* point by the published formula.
  * CHOSEN: the six anchor points of the locus, and the decision to walk it
    linearly in `skin_tone`. They are representative values for Del Bino's
    six classes, not a fit to a named dataset, and no claim rests on their
    exact position. Anchors are declared in `SKIN_LOCUS` where they can be
    replaced by a real fit without touching anything else.
  * CHOSEN, and it must never be read as anything else: clothing colour. It
    comes from the villager's NAME through `cosmetic.cosmetic_choice`, like
    the garment itself. A reader comparing two siblings' coats is comparing
    two hashes.

Eye colour is the one that is already categorical in the engine
(`blue`/`hazel`/`brown`, liability-threshold with HERC2's dominance), so it
needs no locus: it needs three colours, and they are declared as such.

References
----------
Chardon A, Cretois I, Hourseau C (1991). Skin colour typology and suntanning
  pathways. Int J Cosmet Sci 13:191-208.  [the ITA definition]
Del Bino S, Bernerd F (2013). Variations in skin colour and the biological
  consequences of ultraviolet radiation exposure. Br J Dermatol 169(s3):33-40.
  [the six classes and their ITA boundaries]
CIE 15:2004. Colorimetry.  [L*a*b* to XYZ, D65]
IEC 61966-2-1:1999. sRGB.  [XYZ to sRGB, and the transfer function]
"""

from __future__ import annotations

import math
from typing import Dict, Mapping, Sequence, Tuple

__all__ = [
    "SKIN_LOCUS",
    "EYE_COLORS",
    "ita_degrees",
    "ita_class",
    "lab_to_srgb",
    "rgb_hex",
    "skin_lab",
    "skin_color",
    "hair_color",
    "eye_color",
    "clothing_color",
    "appearance_colors",
]


# ----------------------------------------------------------------------
# the locus
# ----------------------------------------------------------------------

# `(skin_tone, L*, a*, b*)`. Representative points for Del Bino & Bernerd's six
# classes, lightest first, walked linearly in `skin_tone`.
#
# DECLARED HERE RATHER THAN BURIED so it can be replaced by a fit to measured
# spectrophotometry without touching the conversion, the ITA measurement or any
# consumer. Nothing in this file assumes six points or equal spacing.
#
# a* (the red axis) barely moves across the locus, which is a real property of
# skin rather than a simplification: melanin loads b* and L*, and the redness
# is haemoglobin, which every villager has.
SKIN_LOCUS: Tuple[Tuple[float, float, float, float], ...] = (
    (0.00, 72.0, 11.0, 15.0),   # very light   ITA ~ +55.7
    (0.20, 67.0, 12.0, 17.0),   # light        ITA ~ +45.0
    (0.40, 63.0, 13.0, 19.0),   # intermediate ITA ~ +34.4
    (0.60, 57.0, 14.0, 21.0),   # tan          ITA ~ +18.4
    (0.80, 48.0, 14.0, 21.0),   # brown        ITA ~  -5.4
    (1.00, 38.0, 12.0, 19.0),   # dark         ITA ~ -32.3
)

# Hair, walked in `hair_pigment` (0=light..1=dark). Eumelanin darkens and
# desaturates; these are sRGB directly rather than L*a*b* points, because
# there is no published hair locus of the same standing as the skin one and
# pretending otherwise by routing them through Lab would dress a choice up as
# a measurement. They are a CHOICE, and this comment is the label.
HAIR_RAMP: Tuple[Tuple[float, Tuple[int, int, int]], ...] = (
    (0.00, (235, 214, 159)),    # pale blond
    (0.25, (196, 158, 95)),     # blond
    (0.50, (139, 98, 55)),      # light brown
    (0.75, (73, 48, 30)),       # dark brown
    (1.00, (28, 22, 20)),       # near black
)

# The engine's three eye_color labels. Categorical in, categorical out: there
# is no continuum to walk, so there is no ramp to invent.
EYE_COLORS: Dict[str, Tuple[int, int, int]] = {
    "blue": (105, 145, 170),
    "hazel": (137, 110, 62),
    "brown": (77, 51, 32),
}

# Clothing. COSMETIC, and the only reason it is in this module at all is that
# a viewer needs one place to ask for a villager's colours.
CLOTHING_PALETTE: Tuple[Tuple[int, int, int], ...] = (
    (122, 96, 78), (94, 104, 88), (86, 92, 112), (128, 88, 88),
    (108, 108, 96), (78, 96, 104), (116, 104, 76), (92, 84, 100),
    (104, 76, 72), (84, 100, 84),
)


# ----------------------------------------------------------------------
# ITA: measured from the point, never imposed on it
# ----------------------------------------------------------------------

def ita_degrees(lightness: float, yellow: float) -> float:
    """Individual Typology Angle for one L*b* point (Chardon et al. 1991).

    `yellow` is b*. Real skin always has b* well above zero, so the
    singularity at b*=0 is outside the locus; it is guarded anyway, because a
    caller passing a non-skin colour should get a defined answer rather than a
    ZeroDivisionError three frames away.
    """
    if yellow == 0.0:
        return 90.0 if lightness >= 50.0 else -90.0
    return math.degrees(math.atan((lightness - 50.0) / yellow))


def ita_class(ita: float) -> str:
    """Del Bino & Bernerd's six classes. Boundaries are theirs, not ours."""
    if ita > 55.0:
        return "very light"
    if ita > 41.0:
        return "light"
    if ita > 28.0:
        return "intermediate"
    if ita > 10.0:
        return "tan"
    if ita > -30.0:
        return "brown"
    return "dark"


# ----------------------------------------------------------------------
# CIE L*a*b* (D65) to sRGB
# ----------------------------------------------------------------------

# D65, the sRGB reference white, in the CIE 1931 2-degree observer.
_WHITE = (95.047, 100.000, 108.883)


def _lab_f_inverse(t: float) -> float:
    return t ** 3 if t > 6.0 / 29.0 else 3.0 * (6.0 / 29.0) ** 2 * (t - 4.0 / 29.0)


def lab_to_srgb(lightness: float, red: float, yellow: float
                ) -> Tuple[int, int, int]:
    """CIE L*a*b* (D65) to 8-bit sRGB. The standard transform, nothing local.

    Written out rather than pulled from a colour library so the whole path
    from a modelled trait to a pixel is auditable in one file, and so the
    engine keeps its property of importing in a bare pytest process.
    """
    fy = (lightness + 16.0) / 116.0
    fx = fy + red / 500.0
    fz = fy - yellow / 200.0

    x = _WHITE[0] * _lab_f_inverse(fx) / 100.0
    y = _WHITE[1] * _lab_f_inverse(fy) / 100.0
    z = _WHITE[2] * _lab_f_inverse(fz) / 100.0

    r = x * 3.2406 + y * -1.5372 + z * -0.4986
    g = x * -0.9689 + y * 1.8758 + z * 0.0415
    b = x * 0.0557 + y * -0.2040 + z * 1.0570

    def gamma(c: float) -> int:
        c = max(0.0, min(1.0, c))
        c = 1.055 * (c ** (1.0 / 2.4)) - 0.055 if c > 0.0031308 else 12.92 * c
        return int(round(max(0.0, min(1.0, c)) * 255.0))

    return gamma(r), gamma(g), gamma(b)


def rgb_hex(rgb: Sequence[int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(int(rgb[0]), int(rgb[1]), int(rgb[2]))


# ----------------------------------------------------------------------
# interpolation along a declared ramp
# ----------------------------------------------------------------------

def _walk(anchors, position: float, width: int):
    """Piecewise-linear interpolation between anchor tuples.

    Clamps rather than extrapolates. Every trait here is already clipped to
    0..1 by its `TraitSpec`, so an out-of-range value means a caller passed
    something that is not that trait, and inventing a colour beyond the end of
    a published locus would be the module's one unforced claim.
    """
    position = max(0.0, min(1.0, float(position)))
    lo = anchors[0]
    for hi in anchors[1:]:
        if position <= hi[0]:
            span = hi[0] - lo[0]
            t = 0.0 if span <= 0 else (position - lo[0]) / span
            return tuple(lo[1 + i] + t * (hi[1 + i] - lo[1 + i])
                         for i in range(width))
        lo = hi
    return tuple(anchors[-1][1 + i] for i in range(width))


# ----------------------------------------------------------------------
# the four channels
# ----------------------------------------------------------------------

def skin_lab(skin_tone: float) -> Tuple[float, float, float]:
    """The villager's point on the skin locus, in CIE L*a*b*."""
    return _walk(SKIN_LOCUS, skin_tone, 3)  # type: ignore[return-value]


def skin_color(skin_tone: float) -> Dict[str, object]:
    """Skin, with the measurement that justifies it travelling alongside.

    Returns the hex a renderer wants AND the L*a*b* point and its ITA, because
    a reader has to be able to check the claim. A hex string alone would be
    exactly the unfalsifiable ramp this module exists to avoid.
    """
    lightness, red, yellow = skin_lab(skin_tone)
    ita = ita_degrees(lightness, yellow)
    return {
        "hex": rgb_hex(lab_to_srgb(lightness, red, yellow)),
        "lab": [round(lightness, 2), round(red, 2), round(yellow, 2)],
        "ita_degrees": round(ita, 1),
        "ita_class": ita_class(ita),
    }


def hair_color(hair_pigment: float) -> str:
    return rgb_hex([int(round(c)) for c in _walk(HAIR_RAMP_ANCHORS,
                                                 hair_pigment, 3)])


# `HAIR_RAMP` is authored as (position, (r, g, b)); `_walk` wants it flat.
HAIR_RAMP_ANCHORS: Tuple[Tuple[float, float, float, float], ...] = tuple(
    (pos, float(rgb[0]), float(rgb[1]), float(rgb[2])) for pos, rgb in HAIR_RAMP)


def eye_color(label: object) -> str:
    """One of the engine's three labels to a colour.

    An unknown label falls back to hazel rather than raising: `eye_color` is a
    calibrated categorical whose labels could grow, and a villager with no
    eyes is a worse failure than a villager with the middle colour.
    """
    key = str(label).lower() if label is not None else ""
    return rgb_hex(EYE_COLORS.get(key, EYE_COLORS["hazel"]))


def clothing_color(villager_name: str, channel: str = "coat") -> str:
    """A garment colour from the NAME. Cosmetic, and labelled as such.

    Routed through `cosmetic.cosmetic_choice` rather than hashed here, so
    every invented channel in the project goes through one function and shows
    up in one place when someone asks what is real.
    """
    from .cosmetic import cosmetic_choice
    keys = tuple(rgb_hex(c) for c in CLOTHING_PALETTE)
    return cosmetic_choice(villager_name, keys, channel=channel)


def appearance_colors(phenotype: Mapping[str, object],
                      villager_name: str) -> Dict[str, object]:
    """Every visible colour for one villager, with its provenance.

    `provenance` is not decoration. Three of these four channels are driven by
    a calibrated heritable trait and one is a hash of a name, and a picture
    that does not say which is which invites a reader to see inheritance in
    the coats.
    """
    tone = float(phenotype.get("skin_tone", 0.5))
    pigment = float(phenotype.get("hair_pigment", 0.5))
    skin = skin_color(tone)
    return {
        "skin": skin["hex"],
        "skin_lab": skin["lab"],
        "skin_ita_degrees": skin["ita_degrees"],
        "skin_ita_class": skin["ita_class"],
        "hair": hair_color(pigment),
        "eyes": eye_color(phenotype.get("eye_color")),
        "clothes": clothing_color(villager_name, channel="coat"),
        "shoes": clothing_color(villager_name, channel="shoes_color"),
        "provenance": {
            "skin": "measured: skin_tone on the Del Bino skin locus, "
                    "ITA per Chardon 1991",
            "hair": "measured: hair_pigment, on a CHOSEN ramp",
            "eyes": "measured: eye_color (categorical, HERC2 dominance)",
            "clothes": "cosmetic: hashed from the villager's name",
            "shoes": "cosmetic: hashed from the villager's name",
        },
    }
