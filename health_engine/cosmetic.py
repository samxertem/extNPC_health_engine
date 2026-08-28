"""
Cosmetic variation, and the rule that keeps it out of the science (item A4).

WRITTEN BEFORE THE FIRST HAIRSTYLE EXISTS, on purpose. The moment a villager
can wear hair, the obvious thing to write is `random.choice(HAIRSTYLES)`, and
the obvious thing is a direct violation of invariant 5: the viewer must never
invent variance. A random hairstyle is variance that came from nowhere,
appearing in a picture next to variance that came from a genome, with nothing
on screen distinguishing the two. By the time anyone asks which is which, the
answer is in a random seed nobody kept.

THE RULE, in three parts. All three are enforced by tests.

  1. **Cosmetic variation is a pure function of the villager's name.** Not of
     an RNG, not of a row index, not of the position in a list. The same
     villager wears the same hair in every run, on every machine, for ever.

  2. **It is never a function of a trait, unless that trait is cited.** Eye
     colour may drive the eye asset, because `eye_color` is a modelled trait
     with h2=0.70 and a real predictive literature behind it. Hair STYLE may
     not be driven by anything, because the engine models hair pigment, curl
     and thickness, and not one of those is a hairstyle. If a future change
     wants to drive a cosmetic channel from a trait, it must name the trait
     in the call, and `cited=` is where it says so.

  3. **It is labelled cosmetic wherever it appears.** `describe()` exists so
     that a caption, an inspector row or a figure legend can say which parts
     of what you are looking at are modelled and which are dressing.

THE TRAP THIS AVOIDS, and it is not hypothetical. Python's built-in `hash()`
is salted per process (PYTHONHASHSEED), so `hash(name) % len(styles)` gives a
DIFFERENT hairstyle every time the interpreter restarts. Nothing fails,
nothing warns, and the only symptom is that a figure cannot be regenerated to
match the one already in the paper. This module uses blake2b for that reason
and `test_choice_is_stable_across_processes` asserts against literal expected
values rather than against a second call in the same process, because a second
call in the same process would agree with a salted hash too.
"""

from __future__ import annotations

import hashlib
from typing import Dict, Optional, Sequence, TypeVar

__all__ = ["cosmetic_index", "cosmetic_choice", "conventional_choice",
           "describe", "CITED_CHANNELS", "CONVENTION_CHANNELS"]

T = TypeVar("T")


# Channels that ARE allowed to be driven by a modelled trait, and the trait
# that drives each. Anything not in here is dressing and must fall through to
# the name-derived path. Kept as data rather than as scattered `if` statements
# so that the set of scientific claims a picture makes can be read off in one
# place, which is what P2's DNA-phenotyping guard needs.
CITED_CHANNELS: Dict[str, str] = {
    "eyes": "eye_color",
    "hair_colour": "hair_pigment",
    "skin": "skin_tone",
}

# THE THIRD CATEGORY, and the reason it had to exist.
#
# Until hairstyle was conditioned on sex there were exactly two kinds of
# channel: driven by a cited trait, or invented from the name. A sex-
# conditioned hairstyle is neither. The CONDITIONER is modelled -- sex is
# genetically determined in `sexchrom.py`, from the father's X or Y -- but
# WHICH styles lean which way is not in any data this project holds, so
# filing it under CITED_CHANNELS would let the village make a claim about
# human hair that nothing supports.
#
# WHAT THE PACK ACTUALLY SAYS, checked rather than assumed. The CC0 clothes
# carry sex in the asset author's OWN filenames: `female_casualsuit01`,
# `male_worksuit01`. Reading those is reading metadata. The ten hairstyles
# carry nothing of the kind -- `Afro01`, `Bob01`, `Braid01`, `Long01`,
# `Ponytail01`, `Short01` to `Short04` -- every one of them names the style
# and none of them names a wearer. So the split is a convention about a
# fictional culture, invented here, and it says so.
#
# Maps channel to the MODELLED variable it is conditioned on. The convention
# itself lives with the assets it is about, in `phenotype_to_mhm.py`.
CONVENTION_CHANNELS: Dict[str, str] = {
    "hair": "sex",
}

# Buckets a name hash is spread over before it is compared against cumulative
# weights. Large enough that the quantisation error in any one option's share
# is under a millionth, and a power of two so the division is exact.
_CONVENTION_RESOLUTION = 1 << 32


def cosmetic_index(name: str, n: int, channel: str = "") -> int:
    """A stable index in `[0, n)` derived from a villager's name.

    `channel` decorrelates independent cosmetic choices. Without it, hairstyle
    and eyebrow style would be the same function of the same string, so every
    villager with hairstyle 3 would also have eyebrow style 3 and the village
    would carry a correlation nobody put there and nobody could explain.

    blake2b rather than `hash()`: see the module docstring. Little-endian,
    8 bytes, so the value does not depend on the platform's word size either.
    """
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    digest = hashlib.blake2b(
        f"{channel}\x00{name}".encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little") % n


def cosmetic_choice(name: str, options: Sequence[T], channel: str = "",
                    cited: Optional[str] = None) -> T:
    """Pick one of `options` for this villager, cosmetically.

    `cited` is the escape hatch, and it is deliberately awkward to use. Passing
    a trait name asserts that this channel is driven by that modelled trait and
    is therefore NOT cosmetic; the caller must then do the driving itself, and
    this function refuses rather than quietly picking at random. The awkwardness
    is the point: it makes "I drove this from a trait" and "I made this up" two
    visibly different lines of code.
    """
    if cited is not None:
        raise ValueError(
            f"channel {channel!r} claims to be driven by the trait {cited!r}, "
            f"so it must not go through cosmetic_choice. Drive it from the "
            f"phenotype directly, and record it in CITED_CHANNELS.")
    if not options:
        raise ValueError(f"no options for cosmetic channel {channel!r}")
    return options[cosmetic_index(name, len(options), channel)]


def conventional_choice(name: str, options: Sequence[T],
                        weights: Sequence[float], channel: str = "") -> T:
    """Pick one of `options`, leaning the way `weights` says, from the name.

    This is the sex-conditioned hairstyle path, and everything awkward about
    it is deliberate.

    STILL A PURE FUNCTION OF THE NAME. The villager wears the same hair in
    every run, on every machine, for ever, exactly as rule 1 requires. All
    that changes is which distribution the name is spread over, and the
    caller picked that using a modelled variable.

    NO WEIGHT MAY BE ZERO, and this is the design decision rather than a
    validation detail. A zero makes the conditioning a LAW -- no man in this
    village has ever worn a braid -- and that is a much stronger statement
    about a fictional culture than the evidence for it, which is none. A
    leaning can be described in a caption as a leaning. A partition looks,
    to anyone reading the lineup, exactly like a finding. So the function
    refuses the partition and the refusal says why.

    WHY NOT JUST SORT THE POOL AND HASH INTO IT. Because the resulting
    village would depend on the ORDER of the pool, and `AssetCatalogue`
    sorts by key, so inserting `Bob03` into the pack would silently re-style
    a third of the village. Cumulative weights have the same problem in
    principle; they have it much less in practice, because a name's position
    in [0, 1) does not move when a neighbour's weight changes, only the
    boundaries around it do.
    """
    if not options:
        raise ValueError(f"no options for conditioned channel {channel!r}")
    if len(weights) != len(options):
        raise ValueError(
            f"channel {channel!r} has {len(options)} options and "
            f"{len(weights)} weights; they must correspond one to one.")
    if any(w <= 0.0 for w in weights):
        raise ValueError(
            f"channel {channel!r} was given a weight of zero or less. A zero "
            f"weight makes an option unreachable for this group, which turns "
            f"a declared leaning into a rule about who may wear what. Use a "
            f"small positive weight instead, and see CONVENTION_CHANNELS.")

    total = float(sum(weights))
    u = cosmetic_index(name, _CONVENTION_RESOLUTION, channel) / _CONVENTION_RESOLUTION
    acc = 0.0
    for option, weight in zip(options, weights):
        acc += weight / total
        if u < acc:
            return option
    # Reached only when accumulated float error leaves `u` above the final
    # boundary. The last option is the right answer there, not an error.
    return options[-1]


def describe(channels: Sequence[str]) -> str:
    """A one-line label saying which of `channels` are modelled and which are not.

    Meant for a figure caption or an inspector footer. Returns a sentence
    rather than a structure because the whole point is that it ends up in
    front of a reader.
    """
    cited = sorted(c for c in channels if c in CITED_CHANNELS)
    conditioned = sorted(c for c in channels
                         if c in CONVENTION_CHANNELS and c not in CITED_CHANNELS)
    made_up = sorted(c for c in channels
                     if c not in CITED_CHANNELS and c not in CONVENTION_CHANNELS)

    parts = []
    if cited:
        parts.append("driven by " + ", ".join(
            f"{c} ({CITED_CHANNELS[c]})" for c in cited))
    if conditioned:
        # The word "convention" is not decoration. This is the one line in
        # front of a reader that separates "the genome did this" from "we
        # decided this", for a channel where the picture cannot show which.
        parts.append("conditioned by convention on " + ", ".join(
            f"{c} ({CONVENTION_CHANNELS[c]})" for c in conditioned))
    if made_up:
        parts.append("cosmetic, from the name only: " + ", ".join(made_up))
    return "; ".join(parts) if parts else "nothing to describe"
