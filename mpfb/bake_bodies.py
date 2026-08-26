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
import mathutils


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

    `load_clothes` is True as of item A3: a `.mhm` written by
    `health_engine.phenotype_to_mhm` now carries a suit line and a shoes line,
    both chosen from the probed catalogue.

    BOTH DEEP SEARCHES STAY OFF, and this is the important one. With deep
    search on, a name MPFB cannot match falls through to a last-resort loop
    that compares each candidate asset against its OWN internal name and
    returns the first self-consistent one, so a stale name silently dresses the
    villager in something else. Off, the same case simply fails to load the
    part, which is a difference we can see. The engine side never guesses a
    name anyway -- `health_engine/mhm_assets.py` reads them out of this very
    install -- so nothing legitimate needs the fallback.
    """
    human_service = PROBE.dynamic_import("mpfb.services.humanservice", "HumanService")
    settings = dict(human_service.get_default_deserialization_settings())
    settings.update({
        "clothes_deep_search": False,
        "bodypart_deep_search": False,
        "subdiv_levels": 0,
        "load_clothes": True,
    })
    return settings


def _clear_scene() -> None:
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def resolve_channels(child_names, parts: dict) -> dict:
    """Blender object names to appearance channels, or raise.

    WHY THIS RUNS HERE AND NOT IN C#. The viewer needs to know which mesh
    inside the FBX is hair and which is shoes, so it can colour them
    separately. It cannot work that out from the names: hairstyles, suits and
    shoes are all just strings from whatever asset pack is installed, and a
    renderer matching on `afro` or `Shoes` would hold a second copy of the
    rule that `phenotype_to_mhm.bodypart_channels` already owns.

    It cannot be a plain lookup either, because the name is transformed twice
    on the way here and neither transformation is reversible by guessing:

      * `AssetCatalogue.token` writes the LAST word of a spaced key, so
        `Female elegantsuit01` is written `elegantsuit01`, while MPFB names
        the object from the full key and Blender turns the space into an
        underscore: `female_elegantsuit01_body`.
      * Case is not preserved: the manifest says `Afro01`, the object is
        `afro01_body`.

    So the match is: strip `_body`, lowercase, and accept a token that equals
    the name or is its final underscore-separated segment.

    IT RAISES ON ANYTHING AMBIGUOUS OR UNMATCHED, and that is the point of
    doing it in Python. A part coloured as the wrong thing still renders, and
    a villager with brown hair on their shoes is not a crash -- it is a
    picture somebody has to notice. Failing the bake is the only moment this
    can be caught for free.
    """
    lookup = {}
    for token, channel in (parts or {}).items():
        lookup.setdefault(str(token).lower(), channel)

    out = {}
    for raw in child_names:
        # MPFB names every part after the character it belongs to, so the
        # object is `Ada-16_adult.afro01_body` and not `afro01_body`. Strip
        # the character prefix first; the same rule runs on the C# side, where
        # Unity adds the FBX root name back in the same shape.
        dot = raw.rfind(".")
        name = raw[dot + 1:] if dot >= 0 else raw
        name = name[:-5] if name.lower().endswith("_body") else name
        key = name.lower()
        # The object name is the asset KEY with its spaces turned into
        # underscores; the manifest holds the TOKEN, which `AssetCatalogue.
        # token` picks as the LONGEST word of that key. Longest, not first or
        # last: `Female elegantsuit01` gives `elegantsuit01` but `Teeth base`
        # gives `Teeth`, so the token can be any word and neither a prefix nor
        # a suffix rule covers both. Matching any whole segment does.
        hits = {lookup[key]} if key in lookup else set()
        if not hits:
            for segment in key.split("_"):
                if segment in lookup:
                    hits.add(lookup[segment])
        if len(hits) == 1:
            out[name.lower()] = hits.pop()
        elif not hits:
            raise SystemExit(
                f"[BAKE] cannot tell what '{raw}' is. Known parts: "
                f"{sorted(lookup)}. Colouring it as a guess would put a "
                f"hair colour on a shoe and log nothing.")
        else:
            raise SystemExit(
                f"[BAKE] '{raw}' matches more than one part ({sorted(hits)}).")
    return out


ARM_BONES = ("upperarm_l", "upperarm_r")


def relax_arms(scene_objects) -> bool:
    """Item A1: MPFB's rest pose stands with both arms out at roughly 40
    degrees (an A-pose); this swings each upper arm down to the side by
    rotating the SHOULDER joint only, then bakes the result as the new rest
    pose so it survives an FBX export with `bake_anim=False`.

    Returns False, and touches nothing, for a body with no `game_engine`
    armature (there is no such case in this pipeline today, but a silent
    no-op on an assumption this specific is worse than a body that is still
    A-posed and says so).

    THE ROTATION IS MEASURED PER BODY, NOT A FIXED CONSTANT. A child's
    humerus and an adult's are not the same proportions, and a hardcoded
    angle tuned on one sample would be a fresh, unmeasured claim on every
    other age. Instead each upper arm's CURRENT rest direction is read from
    the bone itself and rotated toward mostly-straight-down, keeping a
    fraction of the original outward and forward lean so the result still
    reads as a standing pose rather than a plank glued to the ribs. Verified
    2026-08-26 on a 9.6-year-old sample: both hands land within 3 mm of
    pelvis height (symmetric, +-0.163 m out from the spine) and the SKINNED
    MESH's own furthest-right vertex follows to the same height, i.e. the
    body deforms with the bone, not just the bone chain in isolation.

    ONLY THE SHOULDER ROTATES. The elbow's own bend is left exactly as MPFB
    authored it and swings down rigidly with the upper arm, which is the
    smallest change that fixes the outstretched-arms defect without
    inventing an elbow angle nothing measured.
    """
    armature = next((o for o in scene_objects if o.type == "ARMATURE"), None)
    if armature is None or not all(b in armature.pose.bones for b in ARM_BONES):
        return False

    for bone_name in ARM_BONES:
        pose_bone = armature.pose.bones[bone_name]
        bone = pose_bone.bone
        head = bone.head_local.copy()
        current = (bone.tail_local - head).normalized()
        target = mathutils.Vector(
            (current.x * 0.15, current.y * 0.6, -1.0)).normalized()
        axis = current.cross(target)
        if axis.length < 1e-6:
            continue  # already hanging straight down; nothing to rotate
        axis.normalize()
        rotation = mathutils.Quaternion(axis, current.angle(target)).to_matrix().to_4x4()
        delta = (mathutils.Matrix.Translation(head) @ rotation @
                 mathutils.Matrix.Translation(-head))
        pose_bone.matrix = delta @ pose_bone.bone.matrix_local
    bpy.context.view_layer.update()

    # Bake the pose into the rest bones themselves. Without this, the FBX
    # exporter's bind pose is the armature's ORIGINAL rest state -- the
    # arms-out A-pose -- regardless of what the pose bones are doing at
    # export time, because `bake_anim=False` exports rest, not the live pose.
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.select_all(action="SELECT")
    bpy.ops.pose.armature_apply(selected=False)
    bpy.ops.object.mode_set(mode="OBJECT")
    return True


def bake_one(mhm_path: str, fbx_path: str, settings: dict,
             parts: dict = None) -> dict:
    """One `.mhm` to one FBX, on a scene cleared first. Returns measurements."""
    export_service = PROBE.dynamic_import("mpfb.services.exportservice", "ExportService")
    object_service = PROBE.dynamic_import("mpfb.services.objectservice", "ObjectService")
    human_service = PROBE.dynamic_import("mpfb.services.humanservice", "HumanService")

    # STATURE IS MEASURED UNDRESSED, and that is not fastidiousness.
    # A garment's `.mhclo` DELETES the body vertices it covers, so a clothed
    # basemesh is not a whole body and its bounding box is the height of
    # whatever the clothes left behind. Measured on 2026-08-24: with
    # `Female casualsuit01` on her, Leyla-46 measured 0.7323 m instead of
    # 1.4182 m, because the suit takes the legs and the shoes take the feet,
    # so the box ran crown-to-hip. Four of eighteen villagers were affected and
    # the other fourteen were exactly right, which is the reason this needs
    # saying out loud: the failure depends on WHICH GARMENT the villager drew,
    # so a spot check of one body finds nothing.
    #
    # Unity divides by this number to stand the villager 1 m tall, so a body
    # measured at half height renders at twice the size. An undressed load
    # costs one extra deserialization per villager, about four seconds, and it
    # is the only measurement here that answers "how tall is this person".
    _clear_scene()
    bare_settings = dict(settings)
    bare_settings["load_clothes"] = False
    bare = human_service.deserialize_from_mhm(mhm_path, bare_settings)
    authored = PROBE.stature(bare)

    _clear_scene()

    basemesh = human_service.deserialize_from_mhm(mhm_path, settings)
    clothed = PROBE.stature(basemesh)

    # Item A1, before the copy: create_character_copy duplicates whatever
    # rest pose the armature has right now, so posing after the copy would
    # mean tracking down which of the two armatures survived it.
    relaxed = relax_arms(bpy.data.objects)

    root = export_service.create_character_copy(basemesh, name_suffix="_body")
    mesh = object_service.find_object_of_type_amongst_nearest_relatives(root, "Basemesh")
    export_service.bake_modifiers_remove_helpers(
        mesh, bake_masks=True, bake_subdiv=True, remove_helpers=True, also_proxy=True)
    dropped = PROBE.bake_shape_keys(mesh)

    bpy.ops.object.select_all(action="DESELECT")
    root.select_set(True)
    exported = []
    for child in object_service.get_list_of_children(root):
        child.select_set(True)
        if getattr(child, "type", None) == "MESH":
            exported.append(child.name)
    if getattr(mesh, "type", None) == "MESH" and mesh.name not in exported:
        exported.append(mesh.name)
    bpy.context.view_layer.objects.active = root
    bpy.ops.export_scene.fbx(filepath=fbx_path, use_selection=True,
                             add_leaf_bones=False, bake_anim=False)

    return {
        "fbx": os.path.basename(fbx_path),
        # The number Unity normalises by. Undressed, for the reason above.
        "authored_stature_m": authored,
        # The same body with its clothes on, and therefore with the covered
        # vertices deleted. Recorded rather than discarded because the gap
        # between the two IS the masking, and a silent gap is how this was
        # wrong for four villagers in the first place.
        "clothed_basemesh_stature_m": clothed,
        "baked_stature_m": PROBE.stature(mesh),
        "masked_away_m": round(authored - clothed, 6),
        "shape_keys_baked": dropped,
        "arms_relaxed": relaxed,
        "verts": len(mesh.data.vertices),
        # Which mesh in the FBX is which appearance channel, resolved HERE
        # where a mismatch can still fail the bake. See `resolve_channels`.
        "submeshes": resolve_channels(exported, parts),
    }


def _record_statures(bodies_dir: str, manifest: dict, results: list) -> None:
    """Write each baked body's own height back into `bodies.json`.

    WHY UNITY CANNOT WORK THIS OUT FOR ITSELF, which is the whole reason this
    function exists. `HumanMesh.Bake` flattens everything in the imported
    hierarchy into one mesh and, until now, divided by that mesh's height to
    stand the villager exactly 1 m tall so `VillagerView` could scale by
    `height_cm/100`. That is only the same number while the FBX contains
    nothing but a body. Add hair and it sits above the crown: the combined mesh
    is taller than the person, and dividing by it shrinks the BODY until
    hair-tip-to-sole measures 1 m. Every villager would lose height in
    proportion to their hairstyle, and `cosmetic.py` picks hairstyles from the
    villager's NAME, so a channel built to be non-genetic would be modulating
    stature, the best-predicted trait in the model at target_pgs_r2=0.40 after
    Yengo 2022. Nothing on screen would look wrong.

    This is the only stage that can tell the difference, because it holds the
    basemesh alone before the export selects its children, so it measures it
    here and Unity reads the answer.

    WHICH NUMBER, and this was got wrong once already. `authored_stature_m`,
    measured on an UNDRESSED load of the same `.mhm`. The obvious choice is
    `baked_stature_m`, on the grounds that it is the geometry the FBX actually
    receives, and it is wrong: a garment deletes the body vertices it covers,
    so the exported basemesh of a villager in a full suit measures crown to
    hip. Leyla-46 came out at 0.7323 m against a real 1.4182 m, which Unity
    would have rendered at twice life size. The number wanted here is the
    person's height, and only the undressed body has it.

    WRITING TO AN INPUT, said plainly rather than left to be discovered.
    `bodies.json` is produced by `export_bodies.py` and read by this script, so
    writing to it makes a later build stage amend an earlier one's file. That
    is deliberate: the bundle is a build artifact rather than a source, and the
    alternative, a second manifest beside the first, hands the Unity side two
    files that can disagree about which villagers exist. Re-running
    `export_bodies.py` regenerates the file without these keys, which is a
    downgrade and not a corruption: a missing key means "measure it yourself",
    which is the old behaviour and is correct for a body with nothing on it.
    """
    # `authored_stature_m`, the UNDRESSED measurement. Not `baked_stature_m`:
    # that is the exported basemesh, whose covered vertices the garments have
    # deleted, so for a villager in a full suit it is the height of their head
    # and arms rather than of them.
    by_stem = {r["stem"]: r["authored_stature_m"] for r in results}
    # Name-to-channel for each body, resolved during the bake. Written beside
    # the stature for the same reason the stature is: only this stage holds
    # both the manifest and the real Blender objects at once.
    submeshes = {r["stem"]: r.get("submeshes", {}) for r in results}
    touched = 0
    for entry in manifest["bodies"]:
        stature = by_stem.get(entry["stem"])
        if stature is None:
            # A --limit run leaves the rest of the manifest alone rather than
            # stamping a stale number over bodies it never looked at.
            continue
        entry["body_stature_m"] = round(float(stature), 6)
        mapping = submeshes.get(entry["stem"])
        if mapping:
            entry["submeshes"] = mapping
        touched += 1

    manifest_path = os.path.join(bodies_dir, "bodies.json")
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=1)
        fh.write("\n")
    print(f"[BAKE] recorded body_stature_m for {touched}/{len(manifest['bodies'])} "
          f"-> {manifest_path}")


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bodies", required=True,
                        help="directory holding bodies.json and the .mhm files")
    parser.add_argument("--out", default=None,
                        help="where the FBX files go (default: <bodies>/fbx)")
    parser.add_argument("--limit", type=int, default=0,
                        help="bake only the first N, for a quick look")
    parser.add_argument("--start", type=int, default=0,
                        help="skip the first N entries. One long-running "
                             "Blender process accumulates orphaned data "
                             "blocks across many sequential MPFB loads and "
                             "slows down as it goes (observed: 144 bodies "
                             "went from 2.5s/body to a crawl by #60) -- "
                             "resuming in smaller batches, each its own "
                             "process, avoids that.")
    args = parser.parse_args(argv)

    version = PROBE.ensure_mpfb()
    bodies_dir = os.path.abspath(args.bodies)
    out_dir = os.path.abspath(args.out or os.path.join(bodies_dir, "fbx"))
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(bodies_dir, "bodies.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)

    entries = manifest["bodies"]
    if args.start:
        entries = entries[args.start:]
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
        measured = bake_one(mhm, fbx, settings, entry.get("parts"))
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

    _record_statures(bodies_dir, manifest, results)

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
