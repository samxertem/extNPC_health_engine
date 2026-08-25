"""
Matching a Blender object to the appearance channel it should be coloured in.
=============================================================================

`resolve_channels` runs inside Blender during the bake and decides which mesh
in the FBX is hair, which is shoes and which is skin. Getting it wrong does not
crash: it puts a hair colour on a shoe, renders perfectly, and logs nothing. So
it refuses rather than guesses, and this file is the reason the refusal can be
trusted.

WHY IT IS NOT A DICTIONARY LOOKUP. The name is transformed twice between the
engine choosing an asset and Blender naming an object, and neither
transformation is reversible by guessing:

  * `AssetCatalogue.token` writes the LONGEST word of a spaced key, because
    that is the informative half for a human reading the `.mhm`. So
    `Female elegantsuit01` becomes `elegantsuit01` -- a suffix -- but
    `Teeth base` becomes `Teeth`, which is a PREFIX. Neither a prefix rule nor
    a suffix rule handles both, and each one passes on the villagers that
    happen to draw the other shape.
  * MPFB names the object after the character it belongs to and turns the
    key's spaces into underscores, so what arrives is
    `Darius-4_adult.teeth_base_body`.

Both shapes are in the shipped CC0 pack and both are drawn by real villagers,
so a rule covering only one fails partway through a bake. It did, twice, at
body 23 of 144.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _resolver():
    """Load `resolve_channels` out of a module that imports `bpy`.

    `mpfb/bake_bodies.py` runs inside Blender and cannot be imported in a bare
    pytest process. The function under test is pure, so it is executed out of
    the source rather than reimplemented here -- a copy would pass while the
    shipped rule was broken, which is the whole failure mode this file exists
    for.
    """
    src = (REPO / "mpfb" / "bake_bodies.py").read_text(encoding="utf-8")
    start = src.index("def resolve_channels")
    end = src.index("def bake_one")
    namespace = {}
    exec(compile(src[start:end], "bake_bodies.py", "exec"), namespace)
    return namespace["resolve_channels"]


resolve_channels = _resolver()


# A villager wearing `Teeth base`, whose token is a PREFIX of the object name.
PREFIX_PARTS = {
    "body": "skin", "Teeth": "teeth", "Tongue01": "tongue",
    "Low-poly": "eyes", "Afro01": "hair", "Eyebrow002": "eyebrows",
    "Eyelashes04": "eyelashes", "elegantsuit01": "suit", "Shoes06": "shoes",
}
PREFIX_NAMES = [
    "Darius-4_adult.body_body", "Darius-4_adult.teeth_base_body",
    "Darius-4_adult.tongue01_body", "Darius-4_adult.low-poly_body",
    "Darius-4_adult.afro01_body", "Darius-4_adult.eyebrow002_body",
    "Darius-4_adult.eyelashes04_body",
    "Darius-4_adult.female_elegantsuit01_body", "Darius-4_adult.shoes06_body",
]

# A villager wearing `Teeth shape04`, whose token is a SUFFIX.
SUFFIX_PARTS = {
    "body": "skin", "shape04": "teeth", "Tongue01": "tongue",
    "Low-poly": "eyes", "Afro01": "hair", "Eyebrow001": "eyebrows",
    "Eyelashes02": "eyelashes", "elegantsuit01": "suit", "Shoes05": "shoes",
}
SUFFIX_NAMES = [
    "Ada-16_adult.body_body", "Ada-16_adult.teeth_shape04_body",
    "Ada-16_adult.tongue01_body", "Ada-16_adult.low-poly_body",
    "Ada-16_adult.afro01_body", "Ada-16_adult.eyebrow001_body",
    "Ada-16_adult.eyelashes02_body",
    "Ada-16_adult.female_elegantsuit01_body", "Ada-16_adult.shoes05_body",
]

EXPECTED = {"skin", "teeth", "tongue", "eyes", "hair", "eyebrows",
            "eyelashes", "suit", "shoes"}


@pytest.mark.parametrize("parts,names,shape", [
    (PREFIX_PARTS, PREFIX_NAMES, "Teeth base -> token is a PREFIX"),
    (SUFFIX_PARTS, SUFFIX_NAMES, "Female elegantsuit01 -> token is a SUFFIX"),
])
def test_both_token_shapes_resolve_completely(parts, names, shape):
    """The pair that a prefix-only or suffix-only rule cannot both satisfy."""
    got = resolve_channels(names, parts)
    assert len(got) == len(names), f"{shape}: some part went unresolved"
    assert set(got.values()) == EXPECTED, f"{shape}: {sorted(set(got.values()))}"


def test_the_character_prefix_is_stripped_before_matching():
    """MPFB names every part after the character, so the object is
    `Ada-16_adult.afro01_body`. Matching the raw name finds nothing."""
    got = resolve_channels(["Ada-16_adult.afro01_body"], {"Afro01": "hair"})
    assert got == {"afro01": "hair"}


def test_keys_are_lowercased_so_the_viewer_can_look_them_up():
    """The manifest says `Afro01` and Blender says `afro01`. The written map
    is what C# indexes, so it has to be in one case."""
    got = resolve_channels(["A.Afro01_body"], {"Afro01": "hair"})
    assert list(got) == ["afro01"]


# ----------------------------------------------------------------------
# the refusals, which are the reason this is trustworthy
# ----------------------------------------------------------------------

def test_an_unrecognised_part_fails_the_bake_rather_than_guessing():
    """THE POINT OF DOING THIS IN PYTHON. A part coloured as the wrong thing
    still renders; a villager with hair colour on their shoes is not a crash,
    it is a picture somebody has to notice. Failing the bake is the only
    moment it can be caught for free -- and it did catch two real cases."""
    with pytest.raises(SystemExit) as exc:
        resolve_channels(["A.mystery_thing_body"], {"body": "skin"})
    assert "mystery_thing" in str(exc.value)
    assert "body" in str(exc.value), "the refusal must list what it did know"


def test_an_ambiguous_part_fails_rather_than_picking_one():
    """Two channels matching one object means the map cannot be trusted, and
    silently taking the first would be a coin toss rendered as evidence."""
    with pytest.raises(SystemExit, match="more than one"):
        resolve_channels(["A.teeth_base_body"],
                         {"teeth": "teeth", "base": "shoes"})


def test_no_parts_at_all_still_refuses_rather_than_returning_empty():
    """A bare-body bundle passes no parts. Returning `{}` would look like a
    successful resolution of nothing and ship an uncoloured village that the
    manifest claims is coloured."""
    with pytest.raises(SystemExit):
        resolve_channels(["A.afro01_body"], {})


def test_nothing_to_resolve_is_not_an_error():
    """A model with no meshes is a different failure, already handled upstream
    with its own message."""
    assert resolve_channels([], {"body": "skin"}) == {}
