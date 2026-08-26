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

    return {
        "world_name": world_name,
        "bundle_files": n_bundle,
        "bodies_copied": copied,
        "bodies_removed": removed,
        "eye_textures": eyes,
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
