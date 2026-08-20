"""Bake a directory of `.mhm` files into one FBX each (UNITY_PLAN Stage 8, Blender half).

Runs INSIDE Blender, once, for the whole village:

    blender -b -P mpfb/bake_bodies.py -- --bodies outputs/unity/demo/bodies

One process for all of them is not an optimisation, it is the difference
between a usable loop and an unusable one: Blender's startup plus MPFB's
initialisation is 3 to 8 seconds, so twenty separate processes spend two
minutes doing nothing but starting up.

WHAT THIS DELIBERATELY REUSES. Everything about the export itself comes from
`blender_probe.export_body`, which is the path `run_mpfb_probe.py` verifies
end to end: the `game_engine` rig, `bake_modifiers_remove_helpers`, then
`bake_shape_keys`. Reimplementing any of it here would mean the bodies the
village uses travel a route nothing measures. The only thing that changes is
where the macro vector comes from -- MPFB's own `.mhm` loader instead of a
literal in the source.

THE NAME COLLISION, and why this file loads its neighbour so awkwardly. MPFB's
own Blender package is called `mpfb`, and so is this repository's build-time
bridge. Putting the repository root on `sys.path` inside Blender would make
`import mpfb` ambiguous, and the failure mode is not an ImportError but a
half-working MPFB. So `blender_probe.py` is loaded by FILE PATH under a name
that cannot collide.

THE SETTINGS TRAP, measured by reading MPFB's source rather than assumed.
`HumanService.get_default_deserialization_settings()` does NOT include the two
keys `deserialize_from_mhm` immediately reads, `clothes_deep_search` and
`bodypart_deep_search`, so passing the defaults straight through raises
KeyError. They are added explicitly below.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time

import bpy


def _load_probe():
    """Load `blender_probe.py` by path, under a non-colliding module name."""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "blender_probe.py")
    spec = importlib.util.spec_from_file_location("extnpc_blender_probe", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PROBE = _load_probe()


def deserialization_settings() -> dict:
    """MPFB's defaults, plus the two keys its own `.mhm` loader needs.

    `subdiv_levels` is forced to 0. MPFB defaults it to 1, and a subdivided
    body is several times the vertex count of the 14,517-vertex bodies the
    600-character performance budget was measured against. Accepting the
    default would quietly invalidate that measurement.

    `load_clothes` is False because a `.mhm` written by
    `health_engine.phenotype_to_mhm` carries no clothes lines. Saying so
    explicitly costs nothing and documents that naked villagers are item A3,
    not an accident here.
    """
    human_service = PROBE.dynamic_import("mpfb.services.humanservice", "HumanService")
    settings = dict(human_service.get_default_deserialization_settings())
    settings.update({
        "clothes_deep_search": False,
        "bodypart_deep_search": False,
        "subdiv_levels": 0,
        "load_clothes": False,
    })
    return settings


def _clear_scene() -> None:
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def bake_one(mhm_path: str, fbx_path: str, settings: dict) -> dict:
    """One `.mhm` to one FBX, on a scene cleared first. Returns measurements."""
    export_service = PROBE.dynamic_import("mpfb.services.exportservice", "ExportService")
    object_service = PROBE.dynamic_import("mpfb.services.objectservice", "ObjectService")
    human_service = PROBE.dynamic_import("mpfb.services.humanservice", "HumanService")

    _clear_scene()

    basemesh = human_service.deserialize_from_mhm(mhm_path, settings)
    authored = PROBE.stature(basemesh)

    root = export_service.create_character_copy(basemesh, name_suffix="_body")
    mesh = object_service.find_object_of_type_amongst_nearest_relatives(root, "Basemesh")
    export_service.bake_modifiers_remove_helpers(
        mesh, bake_masks=True, bake_subdiv=True, remove_helpers=True, also_proxy=True)
    dropped = PROBE.bake_shape_keys(mesh)

    bpy.ops.object.select_all(action="DESELECT")
    root.select_set(True)
    for child in object_service.get_list_of_children(root):
        child.select_set(True)
    bpy.context.view_layer.objects.active = root
    bpy.ops.export_scene.fbx(filepath=fbx_path, use_selection=True,
                             add_leaf_bones=False, bake_anim=False)

    return {
        "fbx": os.path.basename(fbx_path),
        "authored_stature_m": authored,
        "baked_stature_m": PROBE.stature(mesh),
        "shape_keys_baked": dropped,
        "verts": len(mesh.data.vertices),
    }


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bodies", required=True,
                        help="directory holding bodies.json and the .mhm files")
    parser.add_argument("--out", default=None,
                        help="where the FBX files go (default: <bodies>/fbx)")
    parser.add_argument("--limit", type=int, default=0,
                        help="bake only the first N, for a quick look")
    args = parser.parse_args(argv)

    version = PROBE.ensure_mpfb()
    bodies_dir = os.path.abspath(args.bodies)
    out_dir = os.path.abspath(args.out or os.path.join(bodies_dir, "fbx"))
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(bodies_dir, "bodies.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)

    entries = manifest["bodies"]
    if args.limit:
        entries = entries[:args.limit]

    settings = deserialization_settings()
    print(f"[BAKE] blender {bpy.app.version_string}, mpfb {version}, "
          f"{len(entries)} bodies, subdiv {settings['subdiv_levels']}")

    results = []
    t0 = time.perf_counter()
    for i, entry in enumerate(entries, 1):
        mhm = os.path.join(bodies_dir, entry["mhm"])
        fbx = os.path.join(out_dir, f"{entry['stem']}.fbx")
        t1 = time.perf_counter()
        measured = bake_one(mhm, fbx, settings)
        measured["name"] = entry["name"]
        measured["stem"] = entry["stem"]
        measured["seconds"] = round(time.perf_counter() - t1, 2)
        results.append(measured)
        print(f"[BAKE] {i:3d}/{len(entries)}  {entry['name']:18s} "
              f"{measured['baked_stature_m']:.4f} m  "
              f"{measured['verts']:6d} verts  {measured['seconds']:5.1f}s")

    elapsed = time.perf_counter() - t0
    report = {
        "blender": bpy.app.version_string,
        "mpfb": str(version),
        "subdiv_levels": settings["subdiv_levels"],
        "seconds_total": round(elapsed, 1),
        "bodies": results,
    }
    report_path = os.path.join(out_dir, "bake_report.json")
    with open(report_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")

    statures = sorted(r["baked_stature_m"] for r in results)
    verts = {r["verts"] for r in results}
    print(f"[BAKE] done in {elapsed:.0f}s, {elapsed / max(len(results), 1):.1f}s each")
    print(f"[BAKE] baked stature {statures[0]:.4f} to {statures[-1]:.4f} m")
    print(f"[BAKE] vertex counts: {sorted(verts)}")
    print(f"[BAKE] report -> {report_path}")

    # Every body sharing one vertex count is EXPECTED and not a defect: MPFB
    # morphs a fixed-topology base mesh, so the count is a property of the
    # mesh rather than of the character. It is printed because the day it
    # stops being true, something changed that the Unity side cares about.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
