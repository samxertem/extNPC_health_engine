"""
Installing an exported bundle into the consuming Unity project.
===============================================================

The gap this closes made a whole session's work invisible. The consuming
project references the package by `file:` path, and **a package reference
carries CODE ONLY**: new C# is live after a refresh, but FBX bodies and world
bundles are assets and travel by nothing. In session 23 a pipeline was built,
verified in the throwaway `unity/test-project`, and reported as working while
the owner's editor showed no change at all.

WHAT IS TESTED. Not that `shutil.copytree` copies; that is the standard
library. The parts with logic in them are the REFUSALS and the ADDITIVE
default:

  * a bundle with no baked FBX must be refused with the command that bakes
    them, because the alternative is a silent install of nothing;
  * installing world B must not remove world A's bodies, because the FBX pool
    is shared and `--clean-bodies` is the opt-in that says otherwise;
  * and the FBX must NOT be copied into StreamingAssets as well, or every
    build carries a second copy of a payload measured at ~1.75 MB a body.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from install_to_unity import check_bundle, check_project, install


def make_project(tmp_path: Path) -> Path:
    project = tmp_path / "UnityProject"
    (project / "Assets").mkdir(parents=True)
    (project / "Packages").mkdir(parents=True)
    (project / "Packages" / "manifest.json").write_text("{}", encoding="utf-8")
    return project


def make_bundle(tmp_path: Path, name: str, people, staged=True,
                bake=True) -> Path:
    bundle = tmp_path / name
    (bundle / "bodies" / "fbx").mkdir(parents=True)
    (bundle / "manifest.json").write_text('{"schema":1}', encoding="utf-8")
    (bundle / "people.csv").write_text("name\n", encoding="utf-8")

    entries = []
    for person, stage in people:
        stem = f"{person}_{stage}" if staged else person
        entries.append({"name": person, "key": f"{person}@{stage}" if staged
                        else person, "life_stage": stage if staged else "",
                        "stem": stem, "mhm": f"{stem}.mhm", "age": 30.0})
        (bundle / "bodies" / f"{stem}.mhm").write_text("x", encoding="utf-8")
        if bake:
            (bundle / "bodies" / "fbx" / f"{stem}.fbx").write_bytes(b"FBX")
    (bundle / "bodies" / "bodies.json").write_text(json.dumps({
        "bodies_schema": 2, "staged": staged, "count": len(entries),
        "people": len({p for p, _ in people}), "never_rendered": [],
        "bodies": entries}), encoding="utf-8")
    return bundle


# ----------------------------------------------------------------------
# refusals
# ----------------------------------------------------------------------

def test_a_path_that_is_not_a_unity_project_is_refused(tmp_path):
    """A few hundred megabytes into a mistyped path is silent and slow to
    notice, so the shape of the target is checked before anything is written."""
    (tmp_path / "random").mkdir()
    with pytest.raises(SystemExit, match="not a Unity project"):
        check_project(tmp_path / "random")


def test_a_project_with_assets_but_no_package_manifest_is_refused(tmp_path):
    (tmp_path / "half" / "Assets").mkdir(parents=True)
    with pytest.raises(SystemExit, match="manifest.json"):
        check_project(tmp_path / "half")


def test_an_unbaked_bundle_is_refused_and_names_the_bake_command(tmp_path):
    """THE IMPORTANT REFUSAL. The `.mhm` files exist and the manifest is
    complete, so the bundle looks finished; only the FBX are missing. Copying
    it installs a world in which every villager falls back to the shared mesh,
    which reads as "the bodies do not work" rather than "the bake did not run".
    """
    bundle = make_bundle(tmp_path, "w", [("A", "adult")], bake=False)
    with pytest.raises(SystemExit) as exc:
        check_bundle(bundle)
    assert "bake_bodies.py" in str(exc.value), (
        "the refusal must say how to fix it, not just that it failed")


def test_a_bundle_with_no_bodies_at_all_names_the_export_command(tmp_path):
    bundle = tmp_path / "w"
    bundle.mkdir()
    (bundle / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="export_bodies.py|Export for Unity"):
        check_bundle(bundle)


def test_a_directory_that_is_not_a_bundle_is_refused(tmp_path):
    (tmp_path / "nope").mkdir()
    with pytest.raises(SystemExit, match="not an exported bundle"):
        check_bundle(tmp_path / "nope")


def test_a_partial_bake_is_allowed_but_reported(tmp_path, capsys):
    """Legitimate: `bodies.json` names every body whether or not its FBX
    exists, and a villager with no body draws on the shared mesh. Refusing
    would make a cancelled bake unrecoverable."""
    bundle = make_bundle(tmp_path, "w", [("A", "adult"), ("B", "child")])
    (bundle / "bodies" / "fbx" / "B_child.fbx").unlink()
    check_bundle(bundle)
    assert "1 of 2" in capsys.readouterr().out


# ----------------------------------------------------------------------
# the additive default
# ----------------------------------------------------------------------

def test_installing_a_second_world_keeps_the_first_worlds_bodies(tmp_path):
    """The FBX pool is SHARED and flat. Stems are unique per world, so two
    worlds coexist; quietly emptying the pool would break a bundle the caller
    was not thinking about."""
    project = make_project(tmp_path)
    a = make_bundle(tmp_path, "world-a", [("A", "adult")])
    b = make_bundle(tmp_path, "world-b", [("B", "child")])

    install(a, project)
    result = install(b, project)

    pool = project / "Assets" / "Resources" / "extnpc" / "bodies"
    assert (pool / "A_adult.fbx").exists(), "world A's body was removed"
    assert (pool / "B_child.fbx").exists()
    assert result["bodies_present"] == 2
    assert result["bodies_removed"] == 0


def test_clean_bodies_empties_the_pool_and_says_how_many(tmp_path):
    project = make_project(tmp_path)
    install(make_bundle(tmp_path, "world-a", [("A", "adult")]), project)
    result = install(make_bundle(tmp_path, "world-b", [("B", "child")]),
                     project, clean_bodies=True)

    pool = project / "Assets" / "Resources" / "extnpc" / "bodies"
    assert not (pool / "A_adult.fbx").exists()
    assert (pool / "B_child.fbx").exists()
    assert result["bodies_removed"] == 1


def test_each_world_keeps_its_own_manifest_in_its_own_bundle(tmp_path):
    """The loader reads the body manifest from THE BUNDLE, not from Resources.
    One shared manifest would mean installing world B silently repointed world
    A's names at world B's stems."""
    project = make_project(tmp_path)
    install(make_bundle(tmp_path, "world-a", [("A", "adult")]), project)
    install(make_bundle(tmp_path, "world-b", [("B", "child")]), project)

    sa = project / "Assets" / "StreamingAssets" / "extnpc"
    for world, person in (("world-a", "A"), ("world-b", "B")):
        manifest = json.loads(
            (sa / world / "bodies" / "bodies.json").read_text(encoding="utf-8"))
        assert [b["name"] for b in manifest["bodies"]] == [person]


# ----------------------------------------------------------------------
# what must NOT be copied
# ----------------------------------------------------------------------

def test_the_fbx_are_not_also_copied_into_streamingassets(tmp_path):
    """They live in Resources. A second copy here would double a payload of
    about 1.75 MB a body and ship it into every build."""
    project = make_project(tmp_path)
    bundle = make_bundle(tmp_path, "w", [("A", "adult"), ("A", "child")])
    install(bundle, project)

    dest = project / "Assets" / "StreamingAssets" / "extnpc" / "w"
    assert list(dest.rglob("*.fbx")) == []
    assert list(dest.rglob("*.mhm")) == [], "the .mhm sources are build input"
    assert (dest / "bodies" / "bodies.json").exists()
    assert (dest / "manifest.json").exists()


def test_reinstalling_the_same_world_replaces_rather_than_merges(tmp_path):
    """A rename between exports would otherwise leave a file no manifest names,
    which is invisible and inflates nothing but the next person's confusion."""
    project = make_project(tmp_path)
    install(make_bundle(tmp_path, "w", [("A", "adult")]), project)

    stale = (project / "Assets" / "StreamingAssets" / "extnpc" / "w"
             / "gone.csv")
    stale.write_text("x", encoding="utf-8")
    install(make_bundle(tmp_path / "second", "w", [("A", "adult")]), project)
    assert not stale.exists()


def test_the_result_reports_bodies_and_people_separately(tmp_path):
    """They differ in staged mode, and a reader comparing either against the
    village headcount needs to know which one they are holding."""
    project = make_project(tmp_path)
    bundle = make_bundle(tmp_path, "w",
                         [("A", "infant"), ("A", "child"), ("A", "adult")])
    result = install(bundle, project)
    assert result["staged"] is True
    assert result["bodies_copied"] == 3
    assert result["people"] == 1


# ======================================================================
# Skin detail maps: the tone must stay the engine's
# ======================================================================
#
# The eye textures could be copied as they were, because the eye's colour IS
# the texture. Skin cannot: `skin` is a measured channel with an ITA in
# degrees, and the viewer's standing property is that what the inspector
# prints is what the screen shows. So the source texture is stripped of its
# tone before it ships, and what is tested here is that the stripping WORKED
# rather than that a file was copied.
#
# Every test below can fail. The neutralisation is arithmetic on a synthetic
# image whose right answer is known in advance, so a regression that changed
# the normalisation or dropped the clamp shows up as a number, not as a
# differently-coloured screenshot nobody is looking at.

def _linear_to_srgb8(value: float) -> int:
    """The installer's encoder, independently restated, so a test does not
    pass by calling the thing it is checking."""
    if value <= 0.0031308:
        srgb = value * 12.92
    else:
        srgb = 1.055 * (value ** (1 / 2.4)) - 0.055
    return int(srgb * 255.0 + 0.5)


def _write_flat_png(path: Path, value: int, size: int = 8) -> None:
    Image = pytest.importorskip("PIL.Image", reason="Pillow is an authoring extra")
    np = pytest.importorskip("numpy")
    a = np.full((size, size, 3), value, dtype="uint8")
    Image.fromarray(a, mode="RGB").save(path)


def test_the_age_bands_are_the_ones_makehuman_ships(tmp_path):
    from install_to_unity import skin_band_for_age
    assert skin_band_for_age(0.0) == "young"
    assert skin_band_for_age(44.9) == "young"
    # The boundaries are inclusive at the bottom of each band.
    assert skin_band_for_age(45.0) == "middleage"
    assert skin_band_for_age(64.9) == "middleage"
    assert skin_band_for_age(65.0) == "old"
    assert skin_band_for_age(120.0) == "old"


def test_the_csharp_age_bands_agree_with_the_python_ones():
    """`SkinMaterials.BandForAge` restates these thresholds, because the
    viewer has to resolve a band with no Python in the process. Two
    implementations of one rule drift unless something holds them equal, and
    this is that something."""
    src = (Path(__file__).resolve().parents[1] / "unity" / "com.samal.extnpc" /
           "Runtime" / "View" / "SkinMaterials.cs").read_text(encoding="utf-8")
    from install_to_unity import SKIN_AGE_BANDS
    for threshold, band in SKIN_AGE_BANDS:
        if band == "young":
            continue  # the fall-through case, it has no comparison to find
        assert f"ageYears >= {threshold:g}f) return \"{band}\";" in src, (
            f"SkinMaterials.BandForAge has no branch for {band} at {threshold}")


def test_a_flat_texture_neutralises_to_pure_white(tmp_path):
    """A texture with no detail in it has nothing to contribute, and must
    therefore come out as 1.0 everywhere: multiplying by it leaves the
    engine's colour exactly as it was. If this ever returns grey, every
    villager in the village is being darkened by a map that says nothing."""
    from install_to_unity import neutralise_skin
    src, dst = tmp_path / "flat.png", tmp_path / "flat_out.png"
    _write_flat_png(src, 137)
    report = neutralise_skin(src, dst)
    assert report["written"]
    assert report["residual"] == pytest.approx(1.0)

    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")
    out = np.asarray(Image.open(dst).convert("RGB"))
    assert out.min() == 255, "a detail-free texture must not darken anything"


def test_the_median_pixel_lands_on_white_and_the_dark_half_survives(tmp_path):
    """The whole design in one test: half the pixels dark, half light. The
    median maps to 1.0 so the commonest skin renders at the engine's colour,
    and the darker half keeps its RATIO to it rather than being flattened."""
    from install_to_unity import neutralise_skin, _srgb_to_linear
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")

    # DELIBERATELY UNEVEN, 24 dark against 40 light. An even split does not
    # test what it looks like it tests: numpy's median of an even count is
    # the MEAN of the two middle values, so a 32/32 image has its median
    # halfway between the two tones and neither tone maps to a round number.
    # Weighting the light side puts both middle values on it, so the median
    # IS the light tone and the dark tone's expected ratio is exact.
    a = np.zeros((8, 8, 3), dtype="uint8")
    a[:3, :, :] = 60     # the dark minority
    a[3:, :, :] = 180    # the light majority, and the median
    src, dst = tmp_path / "two.png", tmp_path / "two_out.png"
    Image.fromarray(a, mode="RGB").save(src)

    report = neutralise_skin(src, dst)
    out = np.asarray(Image.open(dst).convert("RGB"))

    # The light majority is at the median and clamps to white.
    assert out[3:, :, 0].min() == 255
    # The dark half keeps the linear-light ratio it had, which is what makes
    # this a detail map rather than a threshold.
    dark_lin = float(_srgb_to_linear(60 / 255.0))
    light_lin = float(_srgb_to_linear(180 / 255.0))
    expected = _linear_to_srgb8(dark_lin / light_lin)
    assert abs(int(out[0, 0, 0]) - expected) <= 1


def test_a_texture_too_dark_to_be_a_detail_map_is_refused(tmp_path, monkeypatch):
    """The gate, checked by making it fire. A map whose mean is below the
    floor would visibly shift a villager's measured skin colour, which is the
    one thing neutralising exists to prevent, so it must be refused rather
    than shipped with a note in a log nobody reads."""
    import install_to_unity as I
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")

    pack = tmp_path / "pack"
    (pack / "young_caucasian_female").mkdir(parents=True)
    # A LIGHT majority so the median is nonzero -- an all-but-black image
    # takes the "no light in it" branch instead and never reaches the gate --
    # and a dark minority far enough below it to drag the mean under the
    # floor. 40 light against 24 near-black gives a mean near 0.63.
    a = np.full((8, 8, 3), 250, dtype="uint8")
    a[:3, :, :] = 5
    Image.fromarray(a, mode="RGB").save(
        pack / "young_caucasian_female" / "d.png")

    monkeypatch.setattr(I, "mpfb_skin_dir", lambda: pack)
    monkeypatch.setattr(I, "SKIN_FOLDERS",
                        {("young", "female"): "young_caucasian_female"})

    project = make_project(tmp_path)
    result = I.install_skin_textures(project)
    assert result["copied"] == 0
    assert result["refused"], "a map below the floor must be refused"
    key, residual = result["refused"][0]
    assert key == "young_female" and residual < I.SKIN_RESIDUAL_FLOOR
    assert not (project / "Assets" / "Resources" / "extnpc" / "skin" /
                "young_female.png").exists(), "the refused map must not ship"


def test_a_missing_asset_pack_is_reported_and_not_an_error(tmp_path, monkeypatch):
    """Same contract as the eye textures: a machine without the CC0 pack gets
    flat skin, which is a worse picture and not a broken install."""
    import install_to_unity as I
    monkeypatch.setattr(I, "mpfb_skin_dir", lambda: None)
    result = I.install_skin_textures(make_project(tmp_path))
    assert result["copied"] == 0
    assert "reason" in result


def _srgb_to_linear1(v8: int) -> float:
    """sRGB decode for one 8-bit channel, restated so this test does not
    verify the installer by calling the installer."""
    c = v8 / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def test_the_reported_residual_is_the_clamped_mean_not_the_raw_one(tmp_path):
    """The clamp is not decoration, and this is the test that says so.

    Dropping `np.clip` leaves the WRITTEN PIXELS identical, because the sRGB
    encode below clips again on its way to 8 bits. What it changes is the
    REPORTED residual, which is the number `install_skin_textures` gates on.
    An unclamped mean is inflated by every pixel brighter than the median, so
    a texture dark enough to shift a villager's skin colour could pass the
    floor while looking fine in the log.

    Found by sabotage: removing the clamp passed the whole suite until this
    existed.
    """
    from install_to_unity import neutralise_skin
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")

    # Three tones, weighted so the MIDDLE one is the median: 24 dark, 32 mid,
    # 8 light. The light row is what the clamp acts on; without it there is
    # nothing above 1.0 anywhere and the bug is invisible.
    a = np.zeros((8, 8, 3), dtype="uint8")
    a[:3, :, :] = 40      # 24 px, below the median
    a[3:7, :, :] = 140    # 32 px, the median itself
    a[7:, :, :] = 250     # 8 px, above the median and therefore clamped
    src, dst = tmp_path / "three.png", tmp_path / "three_out.png"
    Image.fromarray(a, mode="RGB").save(src)

    report = neutralise_skin(src, dst)

    ratio_dark = _srgb_to_linear1(40) / _srgb_to_linear1(140)
    expected = (24 * ratio_dark + 32 * 1.0 + 8 * 1.0) / 64.0
    assert report["residual"] == pytest.approx(expected, abs=1e-6)
    # The invariant behind it: a detail map can only ever darken.
    assert report["residual"] <= 1.0


# ======================================================================
# Eyebrows and eyelashes: the shape is in the alpha
# ======================================================================
#
# Reported as "the villagers look like they are wearing mascara", and they
# did. A brow is a flat CARD whose hairs are cut out of it by the texture's
# alpha channel, so drawing it with a flat opaque colour draws the whole
# rectangle. Measured across the twelve brows and four lashes these bundles
# use, between 1.5 and 21.2 percent of a card should be drawn; the rest is
# the gaps between strands.
#
# What is tested is that the SHAPE survives and the COLOUR does not, because
# the source cards are black and a black texture multiplied by a villager's
# hair colour is black whatever their hair does.

def test_a_card_keeps_its_alpha_exactly_and_loses_its_colour(tmp_path):
    from install_to_unity import whiten_alpha_card
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")

    # Near-black strands on a transparent sheet, which is what MakeHuman
    # ships: the opaque pixels of the real cards average RGB (3, 1, 0).
    a = np.zeros((16, 16, 4), dtype="uint8")
    a[4:8, :, :3] = 12
    a[4:8, :, 3] = 255
    src, dst = tmp_path / "brow.png", tmp_path / "brow_out.png"
    Image.fromarray(a, mode="RGBA").save(src)

    report = whiten_alpha_card(src, dst)
    assert report["written"]

    out = np.asarray(Image.open(dst).convert("RGBA"))
    assert (out[..., :3] == 255).all(), (
        "the colour must be discarded: a black card tinted by hair_pigment "
        "is black whatever the villager's hair does")
    assert (out[..., 3] == a[..., 3]).all(), (
        "the alpha IS the shape and must survive untouched")


def test_coverage_is_measured_inside_the_uv_island_not_the_whole_sheet(tmp_path):
    """A small island on a big sheet is a texture-packing choice and says
    nothing about how solid the card is. Measuring over the whole sheet would
    refuse a perfectly good strand texture for being packed economically."""
    from install_to_unity import whiten_alpha_card
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")

    # One fully opaque 4x4 block in a 64x64 sheet. Over the sheet that is
    # 0.4% coverage; inside its own island it is 100%.
    a = np.zeros((64, 64, 4), dtype="uint8")
    a[10:14, 10:14, :] = 255
    src, dst = tmp_path / "block.png", tmp_path / "block_out.png"
    Image.fromarray(a, mode="RGBA").save(src)

    report = whiten_alpha_card(src, dst)
    assert report["coverage"] == pytest.approx(1.0)
    assert report["island"] == [4, 4]


def test_a_solid_card_is_refused_because_tinting_it_is_the_defect(tmp_path, monkeypatch):
    """The gate, checked by making it fire. A card with no cutout in it is not
    a strand sheet, and giving it a dark hair colour reproduces exactly the
    solid dark rectangle this whole change exists to remove."""
    import install_to_unity as I
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")

    pack = tmp_path / "pack"
    (pack / "eyebrows" / "solid01").mkdir(parents=True)
    a = np.full((16, 16, 4), 255, dtype="uint8")     # entirely opaque
    Image.fromarray(a, mode="RGBA").save(
        pack / "eyebrows" / "solid01" / "solid01.png")

    monkeypatch.setattr(I, "mpfb_asset_root", lambda: pack)
    monkeypatch.setattr(I, "HAIR_CARD_FOLDERS", ("eyebrows",))

    project = make_project(tmp_path)
    result = I.install_hair_cards(project)
    assert result["copied"] == 0
    assert result["refused"] and result["refused"][0][0] == "solid01"
    assert not (project / "Assets" / "Resources" / "extnpc" / "haircards" /
                "solid01.png").exists()


def test_a_strand_card_passes_the_same_gate(tmp_path, monkeypatch):
    """The other half of the gate: it must let a real card through, or the
    refusal above would pass for the wrong reason."""
    import install_to_unity as I
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")

    pack = tmp_path / "pack"
    (pack / "eyebrows" / "brow01").mkdir(parents=True)
    a = np.zeros((16, 16, 4), dtype="uint8")
    a[::4, :, :] = 255                                # ~25% strands
    Image.fromarray(a, mode="RGBA").save(
        pack / "eyebrows" / "brow01" / "brow01.png")

    monkeypatch.setattr(I, "mpfb_asset_root", lambda: pack)
    monkeypatch.setattr(I, "HAIR_CARD_FOLDERS", ("eyebrows",))

    result = I.install_hair_cards(make_project(tmp_path))
    assert result["copied"] == 1
    assert result["refused"] == []
    assert result["measured"]["brow01"] < I.HAIR_CARD_MAX_COVERAGE


def test_every_shipped_brow_and_lash_is_mostly_gaps():
    """Against the REAL asset pack, and skipped when it is not installed.

    This is the measurement the whole fix rests on: if these cards were
    mostly solid, drawing them solid would not have been the bug and tinting
    them dark would not be the fix.
    """
    import install_to_unity as I
    root = I.mpfb_asset_root()
    if root is None:
        pytest.skip("the CC0 asset pack is not installed on this machine")
    pytest.importorskip("PIL.Image")

    import tempfile
    checked = 0
    with tempfile.TemporaryDirectory() as tmp:
        for folder in I.HAIR_CARD_FOLDERS:
            base = root / folder
            if not base.is_dir():
                continue
            for asset in sorted(p for p in base.iterdir() if p.is_dir()):
                pngs = sorted(asset.glob("*.png"))
                if not pngs:
                    continue
                report = I.whiten_alpha_card(pngs[0], Path(tmp) / "out.png")
                if not report.get("written"):
                    continue
                checked += 1
                assert report["coverage"] < 0.5, (
                    f"{asset.name} is {report['coverage']:.1%} opaque, which "
                    f"is not a strand card")
    assert checked >= 8, "expected the pack to ship many brows and lashes"
