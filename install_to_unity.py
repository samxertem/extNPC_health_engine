#!/usr/bin/env python3
"""
Install an exported bundle into the Unity project that consumes the package.
============================================================================

    python install_to_unity.py outputs/unity/dashboard-7
    python install_to_unity.py outputs/unity/dashboard-7 --project "D:/Games/MyGame"
    python install_to_unity.py outputs/unity/dashboard-7 --clean-bodies

WHY THIS EXISTS, and it is the gap that made a whole session's work invisible.
The consuming project references `com.samal.extnpc` by `file:` path, and **a
package reference carries CODE ONLY**. New C# is live after a refresh; FBX
bodies and world bundles are ASSETS and travel by nothing. In session 23 a
pipeline was built, verified in the throwaway `unity/test-project`, and
reported as working while the owner's editor showed no change at all, because
only the harness project ever received the assets. There was no command to
copy them; that is this file.

WHERE THE TWO HALVES GO, AND WHY THEY GO TO DIFFERENT PLACES
------------------------------------------------------------
* **The bundle** (manifest.json, people.csv, frames.csv, and `bodies/bodies
  .json`) goes to `Assets/StreamingAssets/extnpc/<worldName>/`. The loader
  reads the body manifest from THE BUNDLE, not from Resources, so each world
  carries its own name-to-stem map and two worlds cannot read each other's.
* **The FBX bodies** go to `Assets/Resources/extnpc/bodies/`, which is a flat
  shared pool keyed by stem.

That split is what makes this ADDITIVE BY DEFAULT and safe. Stems are unique
per world -- a staged bundle writes `Ada-16_child`, the older unstaged bake
wrote `Ada-16` -- so installing a new world leaves every previously installed
world still able to find its own bodies. `--clean-bodies` empties the pool
first, and it is opt-in precisely because the quiet version of it breaks
bundles the caller was not thinking about.

THE STEP THIS CANNOT DO FOR YOU. Installing a bundle changes nothing while the
scene's loader still points at the old `worldName`. That is a serialised field
on a GameObject in a scene file, and writing to a `.unity` file behind a
running editor is how you lose an editor's unsaved state. The name to set is
printed at the end.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

# The project the owner actually opens. Overridable, because a repo should not
# assume one machine's layout, and `--project` is how anyone else uses this.
DEFAULT_PROJECT = Path(
    os.environ.get("EXTNPC_UNITY_PROJECT",
                   str(Path.home() / "extNPC_healthEngine")))


def check_project(project: Path) -> None:
    """Refuse anything that is not a Unity project.

    Copying a few hundred megabytes into a mistyped path is silent, slow to
    notice and annoying to undo, so the shape of the target is checked before
    anything is written.
    """
    if not (project / "Assets").is_dir():
        raise SystemExit(f"not a Unity project (no Assets/): {project}")
    if not (project / "Packages" / "manifest.json").is_file():
        raise SystemExit(f"not a Unity project (no Packages/manifest.json): {project}")


def check_bundle(bundle: Path) -> dict:
    """Refuse a bundle that is not finished, and say which half is missing."""
    if not (bundle / "manifest.json").is_file():
        raise SystemExit(f"no manifest.json in {bundle}: not an exported bundle")

    bodies_json = bundle / "bodies" / "bodies.json"
    if not bodies_json.is_file():
        raise SystemExit(
            f"no bodies/bodies.json in {bundle}. Export the bodies too:\n"
            f"  the dashboard's 'Export for Unity' button, or\n"
            f"  python export_bodies.py --stages --bundle {bundle}")

    manifest = json.loads(bodies_json.read_text(encoding="utf-8"))
    fbx_dir = bundle / "bodies" / "fbx"
    n_fbx = len(list(fbx_dir.glob("*.fbx"))) if fbx_dir.is_dir() else 0
    if n_fbx == 0:
        raise SystemExit(
            f"no baked FBX in {fbx_dir}. The .mhm files are there but nothing "
            f"has baked them:\n"
            f"  blender -b -P mpfb/bake_bodies.py -- --bodies {bundle / 'bodies'}\n"
            f"  or tick 'bake in Blender' on the dashboard's export button.")

    # A PARTIAL bake is legitimate and must not be refused: bodies.json names
    # every body whether or not its FBX exists, and a villager with no body
    # draws on the shared mesh. But it is worth saying out loud, because the
    # symptom -- a few villagers looking generic -- is easy to read as the
    # bodies not working at all.
    declared = int(manifest.get("count", 0))
    if n_fbx < declared:
        print(f"  NOTE: {n_fbx} of {declared} bodies are baked. The rest will "
              f"draw on the shared mesh until the bake is finished.")
    return manifest


# The engine's three `eye_color` categories, to the CC0 MakeHuman texture
# that renders each. `blue` and `brown` are that texture's own name; `hazel`
# is a MAPPING DECISION and is the only one -- MakeHuman ships no hazel, and
# `brownlight` is the nearest of what it does ship. Recorded here rather than
# chosen silently in C#, because it is a cosmetic choice standing in for a
# calibrated categorical, which is exactly the kind of thing item A4 says
# must be labelled wherever it appears.
EYE_TEXTURES = {
    "blue": "blue_eye.png",
    "brown": "brown_eye.png",
    "hazel": "brownlight_eye.png",
}


def mpfb_eye_material_dir() -> Path | None:
    """Where the installed CC0 asset pack keeps its eye textures.

    Read from `mpfb_assets.json`, which the catalogue probe wrote with this
    machine's real MPFB data directory, rather than reconstructed from a
    guess about Blender's config layout -- that path moved between Blender
    4.x releases (`config/mpfb` vs `extensions/.user/.../mpfb`) and a
    hardcoded one silently finds nothing.
    """
    catalogue = Path(__file__).resolve().parent / "health_engine" / "data" / "mpfb_assets.json"
    if not catalogue.is_file():
        return None
    try:
        user_data = json.loads(catalogue.read_text(encoding="utf-8")).get("user_data")
    except (OSError, ValueError):
        return None
    if not user_data:
        return None
    directory = Path(user_data) / "eyes" / "materials"
    return directory if directory.is_dir() else None


def install_eye_textures(project: Path) -> dict:
    """Copy one eye texture per `eye_color` category into Resources.

    WHY THESE TRAVEL WITH THE BODIES. Eyes are the one part not drawn as a
    flat tone (see `EyeMaterials.cs`): an eyeball is not one colour, so
    painting the submesh with `eye_color` paints the sclera the colour of the
    iris. The viewer therefore needs the actual textures, and a `file:`
    package reference carries CODE ONLY -- the same gap that made a whole
    session's body work invisible in session 23.

    A MISSING PACK IS NOT AN ERROR. The textures come from the optional CC0
    asset pack (item A2), so a machine that never installed it simply gets no
    eye textures and the viewer falls back to the flat tone, which is what it
    did before. Failing the whole install over a cosmetic channel would be
    the wrong trade.
    """
    source = mpfb_eye_material_dir()
    if source is None:
        return {"copied": 0, "reason": "no installed MPFB asset pack found"}

    dest = project / "Assets" / "Resources" / "extnpc" / "eyes"
    dest.mkdir(parents=True, exist_ok=True)

    copied, missing = 0, []
    for label, filename in sorted(EYE_TEXTURES.items()):
        path = source / filename
        if not path.is_file():
            missing.append(filename)
            continue
        # Named for the LABEL, not for MakeHuman's filename: the C# side
        # looks a texture up by the engine's own category and must not carry
        # the hazel-to-brownlight mapping decided above.
        shutil.copy2(path, dest / f"{label}.png")
        copied += 1

    return {"copied": copied, "missing": missing, "dest": str(dest)}


# ----------------------------------------------------------------------
# Skin: the eye fix generalised, and the one thing that had to change
# ----------------------------------------------------------------------
#
# Eyes were the exception because an eyeball is not one colour. Skin is not
# one colour either, but it fails DIFFERENTLY: a flat tone is the right
# AVERAGE and the wrong SURFACE. Lips, nail beds, brow shading, the darkening
# where a limb folds -- all of it is missing, and a face rendered in one
# colour is the strongest remaining "not a person" signal on screen.
#
# THE CONSTRAINT THAT SHAPES THIS. `skin` is a MEASURED channel: it is the
# villager's `skin_tone` placed on the Del Bino skin locus with an ITA in
# degrees, and `bodies.json` records it as measured. The viewer's standing
# property is that what the inspector prints is what the screen shows. A
# MakeHuman skin has a tone baked into it, so using one as authored would
# silently replace the engine's measured colour with an artist's, which is
# the flat-colour bug arriving from the other direction.
#
# SO THE TEXTURE IS NEUTRALISED. It is reduced to its LUMINANCE, divided by
# the median of that luminance, and clamped. What survives is the RATIO of
# each pixel to flat skin: pure detail, no tone. URP's Lit shader multiplies
# `_BaseMap` by `_BaseColor`, so the engine's colour still decides the tone
# and the texture only darkens where real skin darkens.
#
# WHAT THAT COSTS, MEASURED RATHER THAN ASSUMED. Dividing by the median puts
# the median pixel at exactly 1.0, so the commonest patch of skin renders at
# the engine's colour to the bit. Every pixel above the median clamps to 1.0,
# which discards the texture's baked highlights -- correct rather than lossy,
# since a Lit shader computes its own specular. The MEAN lands below 1.0, so
# the average square centimetre of skin renders slightly darker than the flat
# tone. That residual is measured per texture at install time, written into
# `skins.json` beside the textures, and gated below: a texture that would
# darken a villager by more than 15 percent is refused rather than shipped.
SKIN_RESIDUAL_FLOOR = 0.85

# MakeHuman's own three age bands, and the ages at which it switches between
# them. Taken from the asset pack's own naming rather than invented: the pack
# ships `young_*`, `middleage_*` and `old_*` and nothing between.
SKIN_AGE_BANDS = ((65.0, "old"), (45.0, "middleage"), (0.0, "young"))

# (band, sex) to the source FOLDER. Two decisions are recorded here rather
# than made silently in C#, for the reason item A4 gives.
#
#   1. THE CAUCASIAN SET IS USED FOR EVERY VILLAGER. The pack ships african,
#      asian and caucasian variants of each band. After neutralisation they
#      differ almost only in the baked tone that neutralisation removes, and
#      the tone is the engine's to decide. Picking a texture by the villager's
#      simulated pigmentation would ALSO mean the viewer choosing an ancestry
#      label the engine never computes, which invariant 5 forbids.
#   2. THE FILE INSIDE THE FOLDER IS GLOBBED, NOT NAMED. MakeHuman's own
#      filenames are inconsistent across bands (`_diffuse`, `_diffuse2`,
#      `_diffuse3`) and each folder ships exactly one PNG, so globbing is
#      both shorter and more robust than six hardcoded names.
SKIN_FOLDERS = {
    ("young", "female"): "young_caucasian_female",
    ("young", "male"): "young_caucasian_male",
    ("middleage", "female"): "middleage_caucasian_female",
    ("middleage", "male"): "middleage_caucasian_male",
    ("old", "female"): "old_caucasian_female",
    ("old", "male"): "old_caucasian_male",
}


def skin_band_for_age(age_years: float) -> str:
    """Which MakeHuman age band a villager of this age is drawn with.

    Mirrored in `SkinMaterials.BandForAge`. Duplicated on purpose and pinned
    by a test rather than shared through a file: the C# side must resolve a
    band with no Python in the process, and two implementations that a test
    holds equal is the pattern the eye labels already use.
    """
    for threshold, band in SKIN_AGE_BANDS:
        if age_years >= threshold:
            return band
    return "young"


def mpfb_skin_dir() -> Path | None:
    """Where the installed CC0 asset pack keeps its skins.

    Same source of truth as `mpfb_eye_material_dir`, for the same reason: the
    path moved between Blender 4.x releases and a hardcoded guess silently
    finds nothing.
    """
    catalogue = Path(__file__).resolve().parent / "health_engine" / "data" / "mpfb_assets.json"
    if not catalogue.is_file():
        return None
    try:
        user_data = json.loads(catalogue.read_text(encoding="utf-8")).get("user_data")
    except (OSError, ValueError):
        return None
    if not user_data:
        return None
    directory = Path(user_data) / "skins"
    return directory if directory.is_dir() else None


def _srgb_to_linear(channel):
    """sRGB transfer function, inverted. The IEC 61966-2-1 curve, not the 2.2
    approximation: the whole point of this step is that the ratio between two
    pixels is preserved as the shader will actually compute it, and the
    approximation is wrong by up to 1.5 percent near black, which is exactly
    where skin detail lives."""
    import numpy as np
    channel = np.asarray(channel, dtype=np.float64)
    return np.where(channel <= 0.04045,
                    channel / 12.92,
                    ((channel + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(channel):
    import numpy as np
    channel = np.asarray(channel, dtype=np.float64)
    return np.where(channel <= 0.0031308,
                    channel * 12.92,
                    1.055 * np.clip(channel, 0.0, None) ** (1 / 2.4) - 0.055)


def neutralise_skin(source: Path, dest: Path) -> dict:
    """Write `source` out as a tone-free luminance detail map.

    Returns the measurement, so the caller can report and gate it rather than
    trust it. `residual` is the mean of the written map: the factor by which
    an average patch of skin renders darker than the engine's flat tone.
    """
    import numpy as np
    from PIL import Image

    with Image.open(source) as handle:
        rgb = np.asarray(handle.convert("RGB"), dtype=np.float64) / 255.0

    linear = _srgb_to_linear(rgb)
    # Rec. 709 luminance, in LINEAR light. Computing it on the sRGB values
    # instead would weight the dark detail wrongly for the multiply the
    # shader is about to do.
    luminance = (0.2126 * linear[..., 0] +
                 0.7152 * linear[..., 1] +
                 0.0722 * linear[..., 2])

    median = float(np.median(luminance))
    if median <= 0.0:
        return {"written": False, "reason": "texture has no light in it"}

    detail = np.clip(luminance / median, 0.0, 1.0)
    residual = float(detail.mean())
    clamped = float((luminance >= median).mean())

    encoded = np.clip(_linear_to_srgb(detail), 0.0, 1.0)
    grey = (encoded * 255.0 + 0.5).astype("uint8")
    Image.fromarray(np.stack([grey, grey, grey], axis=-1), mode="RGB").save(dest)

    return {"written": True, "residual": residual, "clamped": clamped,
            "median_luminance": median, "size": list(rgb.shape[:2])}


def install_skin_textures(project: Path) -> dict:
    """Neutralise and copy one skin detail map per (age band, sex).

    A MISSING PACK IS NOT AN ERROR, exactly as for the eyes: the viewer falls
    back to the flat tone it drew before, which is a worse picture and not a
    broken one. Nor is a missing Pillow: neutralising a texture is authoring
    work, so it lives behind the `authoring` extra rather than in the
    dependencies a consumer of the library installs.
    """
    source = mpfb_skin_dir()
    if source is None:
        return {"copied": 0, "reason": "no installed MPFB asset pack found"}
    try:
        import numpy  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return {"copied": 0,
                "reason": "Pillow is not installed; `pip install -e .[authoring]`"}

    dest = project / "Assets" / "Resources" / "extnpc" / "skin"
    dest.mkdir(parents=True, exist_ok=True)

    copied, missing, refused = 0, [], []
    measured = {}
    for (band, sex), folder in sorted(SKIN_FOLDERS.items()):
        pngs = sorted((source / folder).glob("*.png")) if (source / folder).is_dir() else []
        if not pngs:
            missing.append(folder)
            continue
        key = f"{band}_{sex}"
        report = neutralise_skin(pngs[0], dest / f"{key}.png")
        if not report.get("written"):
            missing.append(folder)
            continue
        # A texture dark enough to move the villager's tone is refused, not
        # shipped with a note. The whole reason for neutralising is that the
        # rendered tone stays the engine's, and a map that fails that test is
        # not a detail map, it is a second opinion about skin colour.
        if report["residual"] < SKIN_RESIDUAL_FLOOR:
            (dest / f"{key}.png").unlink(missing_ok=True)
            refused.append((key, report["residual"]))
            continue
        measured[key] = {"source": pngs[0].name,
                         "residual": round(report["residual"], 4),
                         "clamped": round(report["clamped"], 4)}
        copied += 1

    if measured:
        (dest / "skins.json").write_text(json.dumps({
            "note": ("Luminance detail maps, median-normalised, tone removed. "
                     "`residual` is the mean of each map: the factor by which "
                     "an average patch renders darker than the engine's flat "
                     "skin colour. Generated by install_to_unity.py."),
            "residual_floor": SKIN_RESIDUAL_FLOOR,
            "age_bands": [[t, b] for t, b in SKIN_AGE_BANDS],
            "textures": measured,
        }, indent=2), encoding="utf-8")

    return {"copied": copied, "missing": missing, "refused": refused,
            "measured": measured, "dest": str(dest)}


# ----------------------------------------------------------------------
# Eyebrows and eyelashes: the geometry is not the shape
# ----------------------------------------------------------------------
#
# THE DEFECT, REPORTED AS "THEY LOOK LIKE THEY ARE WEARING MASCARA". Giving
# eyebrows and eyelashes the villager's own `hair_pigment` was right, and it
# exposed something that had been true all along and invisible while they were
# painted skin-coloured: an eyebrow is not a solid shape. MakeHuman's brow and
# lash meshes are flat CARDS, and the individual hairs are carved out of them
# by the ALPHA CHANNEL of the texture. Drawing the card with a flat opaque
# colour draws the whole rectangle.
#
# MEASURED, over the assets these bundles actually use:
#
#     eyelashes02   18.0% of its UV island is opaque
#     eyebrow001     7.7%
#     eyebrow003    11.8%
#
# So between 82 and 92 percent of what was on screen should not have been
# there at all. Five to thirteen times too much dark area around each eye is
# eyeliner, and that is exactly what it looked like.
#
# THIS IS THE THIRD TIME THIS EXACT LESSON HAS COME UP. The eyes needed
# MakeHuman's own texture because an eyeball is not one colour; the skin
# needed one because skin is not one colour; the brows need one because a brow
# is not one SHAPE. In every case the mesh is a carrier and the texture is the
# content, and in every case the fix is to use the asset the pack already
# ships rather than to infer the missing information.
#
# WHY THE COLOUR IS THROWN AWAY AND ONLY THE ALPHA KEPT. The opaque pixels of
# these textures average RGB (3, 1, 0) and (14, 7, 6): they are black. There
# is no colour in them to preserve, and multiplying a black texture by the
# villager's hair colour would produce black whatever their hair does. So the
# RGB is replaced with white and the alpha is kept exactly, which leaves a
# pure SHAPE that `hair_pigment` then colours.
#
# SCALP HAIR IS DELIBERATELY NOT DONE THIS WAY. Measured at 38 to 100 percent
# coverage -- `braid01` is a solid mesh with no cutout at all -- so hair reads
# acceptably as a volume, and `bob02`'s texture is a light blonde (159, 151,
# 136) whose colour would be double-counted against the tint. Hair keeps its
# flat tint.
HAIR_CARD_FOLDERS = ("eyebrows", "eyelashes")

# A card this solid is not a strand sheet, and tinting it dark would produce
# the very block of colour this exists to remove. Refuse rather than ship it.
HAIR_CARD_MAX_COVERAGE = 0.50


def mpfb_asset_root() -> Path | None:
    """The installed CC0 pack's data directory. Same source of truth as
    `mpfb_eye_material_dir`, one level up."""
    catalogue = Path(__file__).resolve().parent / "health_engine" / "data" / "mpfb_assets.json"
    if not catalogue.is_file():
        return None
    try:
        user_data = json.loads(catalogue.read_text(encoding="utf-8")).get("user_data")
    except (OSError, ValueError):
        return None
    if not user_data:
        return None
    root = Path(user_data)
    return root if root.is_dir() else None


def whiten_alpha_card(source: Path, dest: Path) -> dict:
    """Write `source` out as a white card with its alpha untouched.

    Returns the measurement, so the caller can gate on it. `coverage` is the
    opaque fraction WITHIN the used UV island rather than within the whole
    sheet: a small island in a big sheet is a packing choice and says nothing
    about how solid the card is, and gating on the sheet fraction would
    refuse a perfectly good strand texture for being economically packed.
    """
    import numpy as np
    from PIL import Image

    with Image.open(source) as handle:
        rgba = np.asarray(handle.convert("RGBA"))

    alpha = rgba[..., 3]
    used = np.nonzero(alpha > 5)
    if len(used[0]) == 0:
        return {"written": False, "reason": "the card is entirely transparent"}

    y0, y1 = int(used[0].min()), int(used[0].max())
    x0, x1 = int(used[1].min()), int(used[1].max())
    island = alpha[y0:y1 + 1, x0:x1 + 1]
    coverage = float((island > 127).mean())

    out = np.empty_like(rgba)
    out[..., 0] = out[..., 1] = out[..., 2] = 255   # pure shape, no colour
    out[..., 3] = alpha
    Image.fromarray(out, mode="RGBA").save(dest)

    return {"written": True, "coverage": coverage,
            "island": [x1 - x0 + 1, y1 - y0 + 1]}


def install_hair_cards(project: Path) -> dict:
    """Copy every eyebrow and eyelash card into Resources as a white cutout.

    ALL OF THEM, not the ones this world happens to use. `cosmetic.py` picks
    a brow and a lash per villager from a hash of their NAME, so the set in
    use changes with the cast, and sixteen 512x512 cutouts is a smaller
    payload than one body. Installing the lot means a newly exported world
    never arrives wearing a card that was not copied.
    """
    root = mpfb_asset_root()
    if root is None:
        return {"copied": 0, "reason": "no installed MPFB asset pack found"}
    try:
        import numpy  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return {"copied": 0,
                "reason": "Pillow is not installed; `pip install -e .[authoring]`"}

    dest = project / "Assets" / "Resources" / "extnpc" / "haircards"
    dest.mkdir(parents=True, exist_ok=True)

    copied, refused, measured = 0, [], {}
    for folder in HAIR_CARD_FOLDERS:
        base = root / folder
        if not base.is_dir():
            continue
        for asset in sorted(p for p in base.iterdir() if p.is_dir()):
            pngs = sorted(asset.glob("*.png"))
            if not pngs:
                continue
            # Named for the ASSET, because that is what the bake writes into
            # `bodies.json` as the submesh's source mesh name and therefore
            # what the viewer has to look it up by.
            report = whiten_alpha_card(pngs[0], dest / f"{asset.name}.png")
            if not report.get("written"):
                continue
            if report["coverage"] > HAIR_CARD_MAX_COVERAGE:
                (dest / f"{asset.name}.png").unlink(missing_ok=True)
                refused.append((asset.name, report["coverage"]))
                continue
            measured[asset.name] = round(report["coverage"], 4)
            copied += 1

    return {"copied": copied, "refused": refused, "measured": measured,
            "dest": str(dest)}


def install(bundle: Path, project: Path, clean_bodies: bool = False) -> dict:
    world_name = bundle.name
    manifest = check_bundle(bundle)

    # -- the bundle ---------------------------------------------------
    dest_bundle = project / "Assets" / "StreamingAssets" / "extnpc" / world_name
    if dest_bundle.exists():
        shutil.rmtree(dest_bundle)
    # The FBX are copied separately into Resources; carrying a second copy
    # inside StreamingAssets would double a payload already measured at about
    # 1.75 MB a body and ship it into every build.
    shutil.copytree(bundle, dest_bundle,
                    ignore=shutil.ignore_patterns("fbx", "*.mhm"))
    n_bundle = sum(1 for _ in dest_bundle.rglob("*") if _.is_file())

    # -- the bodies ---------------------------------------------------
    dest_bodies = project / "Assets" / "Resources" / "extnpc" / "bodies"
    dest_bodies.mkdir(parents=True, exist_ok=True)

    removed = 0
    if clean_bodies:
        for stale in list(dest_bodies.glob("*.fbx")):
            stale.unlink()
            meta = stale.with_suffix(".fbx.meta")
            if meta.exists():
                meta.unlink()
            removed += 1

    copied = 0
    for path in sorted((bundle / "bodies" / "fbx").glob("*.fbx")):
        shutil.copy2(path, dest_bodies / path.name)
        copied += 1

    eyes = install_eye_textures(project)
    skin = install_skin_textures(project)
    cards = install_hair_cards(project)

    return {
        "world_name": world_name,
        "bundle_files": n_bundle,
        "bodies_copied": copied,
        "bodies_removed": removed,
        "eye_textures": eyes,
        "skin_textures": skin,
        "hair_cards": cards,
        "bodies_present": len(list(dest_bodies.glob("*.fbx"))),
        "staged": bool(manifest.get("staged")),
        "declared": int(manifest.get("count", 0)),
        "people": int(manifest.get("people", manifest.get("count", 0))),
        "never_rendered": manifest.get("never_rendered", []),
        "dest_bundle": str(dest_bundle),
        "dest_bodies": str(dest_bodies),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bundle", type=Path,
                    help="the exported bundle, e.g. outputs/unity/dashboard-7")
    ap.add_argument("--project", type=Path, default=DEFAULT_PROJECT,
                    help=f"the consuming Unity project (default {DEFAULT_PROJECT})")
    ap.add_argument("--clean-bodies", action="store_true",
                    help="empty Resources/extnpc/bodies first. Opt-in: the "
                         "pool is shared, so this also removes the bodies of "
                         "every OTHER world already installed.")
    args = ap.parse_args()

    bundle = args.bundle.resolve()
    project = args.project.resolve()
    check_project(project)

    print(f"  bundle  {bundle}")
    print(f"  project {project}")
    result = install(bundle, project, clean_bodies=args.clean_bodies)

    kind = "per life stage" if result["staged"] else "one per person"
    print(f"\n  installed '{result['world_name']}': "
          f"{result['bundle_files']} bundle files, "
          f"{result['bodies_copied']} bodies ({kind}) "
          f"for {result['people']} people")
    if result["bodies_removed"]:
        print(f"    removed {result['bodies_removed']} previously installed bodies")
    print(f"    {result['bodies_present']} FBX now in the shared pool")

    eyes = result["eye_textures"]
    if eyes["copied"]:
        print(f"    {eyes['copied']} eye textures (CC0) -> Resources/extnpc/eyes")
    else:
        # Said out loud rather than passed over: the symptom of a silent skip
        # is villagers whose eyes are one flat colour, which is precisely the
        # defect the textures exist to fix, so it must not look like success.
        print(f"    NO eye textures installed ({eyes.get('reason', 'not found')}); "
              f"eyes stay a flat tone. `python run_mpfb_probe.py "
              f"--install-assets` fetches the CC0 pack.")
    if eyes.get("missing"):
        print(f"    missing from the pack: {', '.join(eyes['missing'])}")

    skin = result["skin_textures"]
    if skin["copied"]:
        worst = min(skin["measured"].values(), key=lambda m: m["residual"])
        print(f"    {skin['copied']} skin detail maps (CC0, tone removed) "
              f"-> Resources/extnpc/skin")
        print(f"      darkest map renders {(1 - worst['residual']) * 100:.1f}% "
              f"below the flat tone; the median pixel is exact")
    else:
        # Same reasoning as the eyes: the symptom of a silent skip is a
        # village of flat-shaded mannequins, which looks like a bake that
        # worked.
        print(f"    NO skin textures installed ({skin.get('reason', 'not found')}); "
              f"skin stays a flat tone.")
    if skin.get("refused"):
        for key, residual in skin["refused"]:
            print(f"    REFUSED {key}: residual {residual:.3f} is below the "
                  f"{SKIN_RESIDUAL_FLOOR} floor, so it would have shifted the "
                  f"villager's measured skin colour.")
    if result["never_rendered"]:
        who = ", ".join(u["name"] for u in result["never_rendered"][:3])
        print(f"    {len(result['never_rendered'])} people have no body by "
              f"design ({who}): born and dead inside one tick, so they appear "
              f"in no frame.")

    print("\n  IN UNITY, two steps this cannot do for you:")
    print("    1. Assets > Refresh (Ctrl+R), and wait for the FBX to import.")
    print(f"    2. Select the 'extNPC World' object and set the loader's")
    print(f"       worldName to '{result['world_name']}'. Installing a bundle")
    print(f"       changes nothing while the scene points at the old one.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
