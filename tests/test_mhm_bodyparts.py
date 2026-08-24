"""
Bodypart and clothes lines: the dressed half of Stage 7 (items A2, A3, A4).

WHAT THESE TESTS ARE GUARDING AGAINST, because it is not the usual thing. The
danger in this layer is not a crash, it is a SUCCESS with the wrong asset.
MPFB's `HumanService._check_parse_mhm_bodypart_line` fails to match a name and
uuid pair, falls into a deep search, and its last resort compares each
candidate asset against its OWN internal name rather than against the one that
was requested. The first self-consistent candidate therefore wins whatever was
asked for. A stale name renders a person wearing someone else's hair, with an
empty console.

Nothing here can call into Blender, so these tests cannot prove what MPFB
does. What they CAN prove, and do, is that this side never hands MPFB a name
it did not read back out of the installed pack, including the source rule that
no asset name appears as a literal anywhere in the emitting module.
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest

from health_engine import cosmetic
from health_engine.mhm_assets import (AssetCatalogue, MissingAssetPack,
                                      load_catalogue)
from health_engine.phenotype_to_mhm import (CITED_BODYPARTS,
                                            COSMETIC_BODYPARTS,
                                            EYE_MESH_QUALITY, bodypart_lines,
                                            phenotype_to_mhm)

REPO = pathlib.Path(__file__).resolve().parent.parent

# A catalogue with known contents, so the assertions below are about the
# selection rules and not about whichever assets happen to be installed. The
# real one is exercised separately in `test_the_installed_catalogue_is_usable`.
FAKE = AssetCatalogue(
    {
        "eyes": [{"key": "Low-poly", "uuid": "u-eyes-low"},
                 {"key": "High-poly", "uuid": "u-eyes-high"}],
        "hair": [{"key": "Style%02d" % i, "uuid": "u-hair-%d" % i}
                 for i in range(6)],
        "eyebrows": [{"key": "Brow%02d" % i, "uuid": "u-brow-%d" % i}
                     for i in range(4)],
        "eyelashes": [{"key": "Lash%02d" % i, "uuid": "u-lash-%d" % i}
                      for i in range(3)],
        "teeth": [{"key": "Teeth%02d" % i, "uuid": "u-teeth-%d" % i}
                  for i in range(3)],
        "tongue": [{"key": "Tongue01", "uuid": "u-tongue-1"}],
        "clothes": [{"key": "Male suitA", "uuid": "u-m-a"},
                    {"key": "Male suitB", "uuid": "u-m-b"},
                    {"key": "Female suitA", "uuid": "u-f-a"},
                    {"key": "Female suitB", "uuid": "u-f-b"},
                    {"key": "Shoes01", "uuid": "u-shoe-1"},
                    {"key": "Shoes02", "uuid": "u-shoe-2"}],
        # Present, uuid-less, and therefore must never be reachable.
        "skins": [{"key": "young_caucasian", "uuid": None}],
    },
    source="fake",
)

HAIRY = {"bmi": 24.5, "pattern_baldness": False}
BALD = {"bmi": 24.5, "pattern_baldness": True}


def lines_for(name="Kaya-32", pheno=None, sex="male"):
    return bodypart_lines(name, HAIRY if pheno is None else pheno, sex, FAKE)


# ----------------------------------------------------------------------
# the substitution trap
# ----------------------------------------------------------------------

def test_no_asset_name_is_written_down_in_the_emitting_module():
    """The source rule, and the most important test in this file.

    A hardcoded name is not a style complaint here. It is the one mistake MPFB
    turns into a silently wrong render, and it survives every behavioural test
    in this file, because a hardcoded name that happens to be installed passes
    them all. So this reads the module instead.
    """
    source = (REPO / "health_engine" / "phenotype_to_mhm.py").read_text(
        encoding="utf-8")
    # Strip comments and docstrings: the reasoning legitimately NAMES assets
    # ("the eyes family ships High-poly and Low-poly"), and prose is not what
    # gets sent to MPFB.
    code = "\n".join(line.split("#")[0] for line in source.splitlines())
    for quoted in re.findall(r'"""(.*?)"""', code, flags=re.S):
        code = code.replace(quoted, "")

    installed = load_catalogue()
    offenders = []
    for family in installed.families():
        for key in installed.keys(family):
            if key == EYE_MESH_QUALITY:
                continue  # the one declared constant, argued at its definition
            if '"%s"' % key in code or "'%s'" % key in code:
                offenders.append("%s/%s" % (family, key))
    assert not offenders, (
        "asset names appear as literals in phenotype_to_mhm.py: %s. Every name "
        "must come from the catalogue, because MPFB substitutes a different "
        "asset rather than failing when a name goes stale." % offenders)


def test_every_emitted_uuid_belongs_to_its_emitted_name():
    """A line pairs a name with the catalogue's uuid FOR THAT NAME.

    Crossing the two, right family and wrong uuid, is the case MPFB resolves by
    deep search and can resolve wrongly, so it must be impossible to reach from
    here rather than merely unlikely.
    """
    for line in lines_for():
        family, name, uuid = line.split(" ")
        # Resolve through the uuid, because the line carries a space-free
        # TOKEN rather than the key. The token still has to point at the asset
        # the uuid names, which is what MPFB's first matcher requires.
        key = FAKE.key_for_uuid(family, uuid)
        assert name.lower() in key.lower(), line
        assert FAKE.uuid(family, key) == uuid, line


def test_no_emitted_name_contains_a_space():
    """MPFB reads a bodypart line with `line.split(" ", 2)`.

    So a name with a space in it lands half in the name and half in the uuid,
    the uuid matches nothing, and with deep search off the part silently never
    loads. The first dressed bake hit exactly this: every space-free asset
    bound and every spaced one vanished, leaving eighteen villagers with hair
    and shoes, no suits and no teeth, and an empty log.

    This runs over the REAL catalogue, because it is the real catalogue that
    contains `Male casualsuit02` and `Teeth shape02`.
    """
    installed = load_catalogue()
    for family in AssetCatalogue.EMITTABLE:
        for key in installed.keys(family):
            line = installed.line(family, key)
            emitted_family, name, uuid = line.split(" ")
            assert emitted_family == family
            assert " " not in name
            # Still has to identify the asset MPFB will look for.
            assert name.lower() in key.lower()
            assert uuid == installed.uuid(family, key)


def test_the_token_is_specific_enough_to_read():
    """`casualsuit02` rather than `Male`. The uuid does the identifying, but a
    person reading the `.mhm` should still be able to tell what is on the
    villager."""
    assert AssetCatalogue.token("Male casualsuit02") == "casualsuit02"
    assert AssetCatalogue.token("Teeth shape02") == "shape02"
    assert AssetCatalogue.token("Ponytail01") == "Ponytail01"
    assert AssetCatalogue.token("Low-poly") == "Low-poly"


def test_a_spaced_token_still_resolves_to_exactly_one_asset():
    """The substring is loose on its own; the uuid is what makes it exact.

    This asserts the property that makes the substring safe: no two assets in
    a family share a uuid, so substring AND uuid cannot land on two.
    """
    installed = load_catalogue()
    for family in AssetCatalogue.EMITTABLE:
        uuids = [u for _, u in installed.options(family)]
        assert len(uuids) == len(set(uuids)), family


def test_an_unknown_name_raises_rather_than_substitutes():
    with pytest.raises(MissingAssetPack) as excinfo:
        FAKE.line("hair", "Style99")
    assert "not installed" in str(excinfo.value)


def test_a_family_with_no_uuids_is_unreachable():
    """`skins` and `proxymeshes` ship with no uuid in the CC0 pack.

    A uuid-less asset can ONLY be matched by the self-comparing fallback, so
    the catalogue must refuse it at the door rather than let a caller ask.
    """
    with pytest.raises(MissingAssetPack):
        FAKE.options("skins")
    assert "skins" not in FAKE.families()


def test_the_installed_catalogue_is_usable():
    """The real pack rather than the fixture: every emittable family has assets
    and every one of them carries a uuid."""
    installed = load_catalogue()
    for family in AssetCatalogue.EMITTABLE:
        options = installed.options(family)
        assert options, family
        assert all(uuid for _, uuid in options), family


# ----------------------------------------------------------------------
# what is cited and what is invented
# ----------------------------------------------------------------------

def test_baldness_removes_hair_and_changes_nothing_else():
    """The one cited channel. `pattern_baldness` is the sex-limited
    androgenetic-alopecia phenotype from AR at Xq12, so it may remove the hair
    line, and it must leave every other line untouched, or the claim in the
    caption would be broader than the code."""
    hairy = lines_for(pheno=HAIRY)
    bald = lines_for(pheno=BALD)

    assert any(l.startswith("hair ") for l in hairy)
    assert not any(l.startswith("hair ") for l in bald)
    assert [l for l in hairy if not l.startswith("hair ")] == list(bald)


def test_eyebrows_survive_baldness():
    """Androgenetic alopecia is scalp-patterned. Taking the brows too would be
    the render asserting a phenotype the engine does not model."""
    assert any(l.startswith("eyebrows ") for l in lines_for(pheno=BALD))


def test_hair_style_is_not_a_function_of_any_trait():
    """Style is cosmetic, and this is the assertion that keeps it that way.

    Two villagers with the same NAME and wildly different phenotypes must get
    the same hairstyle. If a trait ever leaks into the style choice this fails,
    and the caption saying "style is cosmetic" stops being true.
    """
    a = lines_for(name="Same-Name",
                  pheno={"bmi": 17.0, "pattern_baldness": False})
    b = lines_for(name="Same-Name",
                  pheno={"bmi": 41.0, "pattern_baldness": False,
                         "skin_tone": 0.9, "hair_curl": 0.95})
    assert ([l for l in a if l.startswith("hair ")]
            == [l for l in b if l.startswith("hair ")])


def test_the_cited_channel_is_declared():
    assert CITED_BODYPARTS["hair_presence"] == "pattern_baldness"
    assert "hair" in COSMETIC_BODYPARTS


def test_a_missing_baldness_key_means_not_bald():
    """A phenotype with no X-linked layer must still dress. Defaulting to bald
    would make an absent layer look like a genetic finding."""
    assert any(l.startswith("hair ") for l in lines_for(pheno={"bmi": 24.5}))


# ----------------------------------------------------------------------
# clothing
# ----------------------------------------------------------------------

@pytest.mark.parametrize("sex,prefix", [("male", "Male "), ("female", "Female ")])
def test_the_suit_matches_the_packs_own_sex_label(sex, prefix):
    """Checked through the uuid, not the emitted name.

    The line says `clothes suitA <uuid>`, so the `Male ` prefix that decided
    the choice is not on it any more. Resolving the uuid back to the asset is
    what proves the villager is wearing the garment the pack labels for their
    sex, rather than proving a string still starts with a word.
    """
    worn = []
    for line in lines_for(sex=sex):
        if not line.startswith("clothes "):
            continue
        worn.append(FAKE.key_for_uuid("clothes", line.split(" ")[2]))

    suits = [k for k in worn if not k.startswith("Shoes")]
    assert len(suits) == 1
    assert suits[0].startswith(prefix)


def test_everyone_gets_shoes():
    worn = [FAKE.key_for_uuid("clothes", l.split(" ")[2])
            for l in lines_for(sex="female") if l.startswith("clothes ")]
    assert any(k.startswith("Shoes") for k in worn)


def test_clothes_may_repeat_the_family_on_separate_lines():
    """A `.mhm` carries one `clothes` line per garment, so the suit and the
    shoes are two lines rather than one merged one."""
    assert len([l for l in lines_for() if l.startswith("clothes ")]) == 2


# ----------------------------------------------------------------------
# reproducibility
# ----------------------------------------------------------------------

def test_choices_are_stable_across_processes():
    """`cosmetic` uses blake2b rather than `hash()` because CPython salts
    `hash()` per process. That is tested there; this asserts the property
    survives composition into a whole `.mhm`, which is the level at which
    someone would actually notice it breaking.
    """
    script = (
        "from health_engine.phenotype_to_mhm import phenotype_to_mhm;"
        "from health_engine.mhm_assets import load_catalogue;"
        "print(phenotype_to_mhm({'bmi':24.5,'pattern_baldness':False},"
        "'male',34.0,name='Kaya-32',catalogue=load_catalogue()))"
    )
    outs = []
    for seed in ("0", "1", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        proc = subprocess.run([sys.executable, "-c", script], cwd=str(REPO),
                              capture_output=True, text=True, env=env)
        assert proc.returncode == 0, proc.stderr
        outs.append(proc.stdout)
    assert outs[0] == outs[1] == outs[2]


def test_the_bare_path_is_untouched_by_this_feature():
    """No catalogue means the file the golden fixture pins, exactly. The
    dressed path must be additive rather than a rewrite of the old one."""
    bare = phenotype_to_mhm({"bmi": 24.5}, "female", 34.0, name="x")
    for family in ("eyes", "hair", "clothes", "teeth", "tongue"):
        assert ("\n%s " % family) not in bare


def test_cosmetic_seed_follows_the_person_not_the_file_label():
    """`villager_name` overrides `name`. Two exports of one villager under
    different file labels must dress identically."""
    a = phenotype_to_mhm(HAIRY, "male", 34.0, name="run_a_0007",
                         catalogue=FAKE, villager_name="Kaya-32")
    b = phenotype_to_mhm(HAIRY, "male", 34.0, name="run_b_0042",
                         catalogue=FAKE, villager_name="Kaya-32")

    def strip(text):
        return [l for l in text.splitlines() if not l.startswith("name ")]

    assert strip(a) == strip(b)


def test_channels_do_not_move_together():
    """Salting per channel is what stops two cosmetic choices from sharing an
    index. Without it, every villager with eyelashes 0 also has teeth 0, which
    looks like a bug and hides real variation.

    THE FAMILIES HERE ARE THE SAME SIZE ON PURPOSE, and the first version of
    this test was wrong for exactly that reason. It compared hair against
    eyebrows, six options against four, so `n mod 6` and `n mod 4` decorrelated
    on their own and it passed with the salt REMOVED. Equal sizes are what make
    an unsalted index show up as lockstep: `eyelashes` and `teeth` both have
    three, so a shared seed forces the same index every time.
    """
    seen = set()
    for i in range(60):
        got = lines_for(name="Villager-%d" % i)
        lash = next(l for l in got if l.startswith("eyelashes "))
        teeth = next(l for l in got if l.startswith("teeth "))
        seen.add((lash.split()[1], teeth.split()[1]))

    lashes = set(a for a, _ in seen)
    teeths = set(b for _, b in seen)
    assert len(lashes) > 1 and len(teeths) > 1, "no variation to compare"
    assert len(seen) > max(len(lashes), len(teeths)), (
        "eyelashes and teeth move in lockstep, so the per-channel salt is not "
        "reaching cosmetic_index: %s" % sorted(seen))


def test_describe_labels_the_cosmetic_channels():
    assert "cosmetic" in cosmetic.describe(["hair", "eyes", "eyebrows"])
