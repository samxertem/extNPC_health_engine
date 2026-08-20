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

__all__ = ["cosmetic_index", "cosmetic_choice", "describe", "CITED_CHANNELS"]

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


def describe(channels: Sequence[str]) -> str:
    """A one-line label saying which of `channels` are modelled and which are not.

    Meant for a figure caption or an inspector footer. Returns a sentence
    rather than a structure because the whole point is that it ends up in
    front of a reader.
    """
    cited = sorted(c for c in channels if c in CITED_CHANNELS)
    made_up = sorted(c for c in channels if c not in CITED_CHANNELS)

    parts = []
    if cited:
        parts.append("driven by " + ", ".join(
            f"{c} ({CITED_CHANNELS[c]})" for c in cited))
    if made_up:
        parts.append("cosmetic, from the name only: " + ", ".join(made_up))
    return "; ".join(parts) if parts else "nothing to describe"
