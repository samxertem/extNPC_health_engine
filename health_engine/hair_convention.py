"""
Which hairstyles lean which way, declared in one place as a convention.
======================================================================

Sex is modelled. Hairstyle is not. This module is what keeps those two facts
from being confused by a village full of people in a screenshot.

WHY A SEPARATE MODULE, when the clothes rule lives inside
`phenotype_to_mhm.py`. Because `test_no_asset_name_is_written_down_in_the_
emitting_module` forbids asset names as literals in the emitting module, and
it is right to: a stale literal THERE becomes a `.mhm` line, and MPFB responds
to a name it cannot resolve by substituting a different asset rather than by
failing, so the villager silently wears somebody else's hair.

A convention table has a different shape and a different risk. It never emits
a name; it looks a WEIGHT up by a name that came out of the catalogue in the
first place. A stale key here cannot put a wrong asset in a file. It can only
leave a style with no declared leaning, which is why the control for it is
`test_every_shipped_hairstyle_is_declared` rather than a rule against writing
the names down at all. Two different failures, two different guards, and
neither one weakened to make room for the other.

WHAT THE PACK ITSELF SAYS, checked rather than remembered. The CC0 clothes
carry sex in their author's own filenames, `female_casualsuit01` and
`male_worksuit01`, so `_clothing_for` reads metadata and asserts nothing. The
ten hairstyles are `Afro01`, `Bob01`, `Bob02`, `Braid01`, `Long01`,
`Ponytail01` and `Short01` to `Short04`. Every one of them names a style and
not one of them names a wearer. So there is no data here to read, and what
follows is invented.

THE CLAIM THIS MODULE IS ALLOWED TO SUPPORT, in full: villagers of different
sexes are drawn from different hairstyle distributions, and the distributions
were chosen by the author. It may never be read as a finding about human hair,
about this population, or about the genome. `cosmetic.CONVENTION_CHANNELS` is
where a consumer discovers that, and `describe()` is what puts it in a caption.

References
----------
None, and the absence is the point. If a citable source for hairstyle
frequency by sex in some named population is ever wanted, it would replace
WEIGHTS wholesale and this docstring with it.
"""

from __future__ import annotations

from typing import Dict, Sequence, Tuple

__all__ = ["WEIGHTS", "NO_LEANING", "hair_weights", "undeclared"]


# No leaning asserted. The lookup default, and it is the honest default: a
# style nobody has declared should carry the author's opinion about nobody,
# not an opinion inherited from whichever style happens to sort next to it.
NO_LEANING: Tuple[float, float] = (1.0, 1.0)

# `(female weight, male weight)` per installed hairstyle.
#
# THE RATIO IS 3 TO 1 AND NOTHING SUPPORTS THAT NUMBER. It is chosen to be
# legible in a village of a hundred without being absolute: at 3 to 1 about a
# quarter of the villagers wearing a leaning style are of the other sex, so a
# lineup reads as a tendency rather than as a uniform. A reader who disagrees
# with any row of this table can change that row and nothing else.
#
# NO WEIGHT IS ZERO, deliberately. `cosmetic.conventional_choice` refuses zero
# and argues the case there: a zero turns a declared leaning into a rule about
# who is permitted to wear what, which is a far stronger statement about a
# fictional culture than an invented table is entitled to make.
WEIGHTS: Dict[str, Tuple[float, float]] = {
    "Afro01": NO_LEANING,
    "Bob01": (3.0, 1.0),
    "Bob02": (3.0, 1.0),
    "Braid01": (3.0, 1.0),
    "Long01": (3.0, 1.0),
    "Ponytail01": (3.0, 1.0),
    "Short01": (1.0, 3.0),
    "Short02": (1.0, 3.0),
    "Short03": (1.0, 3.0),
    "Short04": (1.0, 3.0),
}


def hair_weights(styles: Sequence[str], sex: str) -> Tuple[float, ...]:
    """This villager's weight for each style in `styles`, in that order.

    An undeclared style falls back to `NO_LEANING` rather than raising. That
    is a deliberate reversal of the "refuse rather than guess" rule this
    project follows elsewhere, and it is worth saying why, because the rule is
    a good one.

    Refusing here would mean a pack with one extra hairstyle cannot bake at
    all, and the guarantee bought by that outage is weak: the thing being
    guarded is not a wrong asset, it is a missing OPINION. Meanwhile the real
    risk, the SHIPPED pack quietly acquiring a style with no declared leaning
    while a caption claims one, is caught at test time by
    `test_every_shipped_hairstyle_is_declared`, which fails loudly and long
    before a bake. So the guard moves from run time to test time and gets
    stronger on the way, instead of trading a real outage for a small one.
    """
    female = not str(sex).lower().startswith("m")
    index = 0 if female else 1
    return tuple(WEIGHTS.get(style, NO_LEANING)[index] for style in styles)


def undeclared(styles: Sequence[str]) -> Tuple[str, ...]:
    """Styles in `styles` carrying no declared leaning, in the given order.

    Exists so the completeness check can be a one-liner against the installed
    catalogue rather than a reimplementation of the lookup.
    """
    return tuple(s for s in styles if s not in WEIGHTS)
