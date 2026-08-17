"""Measure MPFB2's macro behaviour from inside Blender, and export a character.

RUN THIS THROUGH `run_mpfb_probe.py`, not by hand. It expects to be executed by
a Blender that has the MPFB extension installed:

    blender -b -P mpfb/blender_probe.py -- --out <dir>

WHY IT EXISTS. Phase B needs `height_cm` from the engine to become a real
stature in Unity. Every number that mapping rests on is a property of a
third-party add-on, so every one of them has to be measured rather than read
off documentation, and re-measured whenever MPFB is upgraded. This script is
that measurement. It writes `mpfb_probe.json` and exports FBX files that
`run_mpfb_probe.py` then measures on the Unity side.

THREE TRAPS THIS SCRIPT EXISTS TO NOT FALL INTO. Each produced a confidently
wrong number before being caught, and each is cheap to fall into again.

1. `mesh.vertices[i].co` is the BASIS mesh. MPFB applies every macro as a
   shape key, so reading the mesh datablock measures the mesh MPFB started
   from, not the character it produced. Two characters with different genders
   measured identically before this was noticed. Everything here goes through
   `evaluated_get(depsgraph)`.
2. An FBX exported WITHOUT the armature loses both the unit round-trip and
   Blender's Z-up -> Unity's Y-up conversion, and arrives in Unity 100x too
   small and lying down. With the `game_engine` rig both are correct.
3. Shape keys survive into the FBX as blendshapes, and Unity imports every
   blendshape weight at ZERO. The character therefore arrives as the neutral
   MakeHuman base mesh, which is a plausible-looking 1.67 m human, so
   nothing about it looks wrong. `bake_shape_keys` collapses the mix into the
   base mesh before export.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys

import bpy


# ---------------------------------------------------------------------
# reaching MPFB
# ---------------------------------------------------------------------

def dynamic_import(package_suffix: str, key: str):
    """MPFB's own quirk, copied from its script_samples.

    A Blender extension's absolute package name is not knowable at write time
    (`bl_ext.user_default.mpfb` here, but the repo id can differ), so the
    documented way in is to scan `sys.modules` for a suffix match.
    """
    for name in sys.modules:
        if name.endswith(package_suffix):
            module = importlib.import_module(name)
            if not hasattr(module, key):
                raise AttributeError(f"{name} has no attribute {key}")
            return getattr(module, key)
    raise ValueError(f"no loaded module ends with {package_suffix}")


def ensure_mpfb() -> str:
    """Enable the MPFB extension, whatever it is called here. Returns version."""
    if not any(n.endswith("mpfb.services.targetservice") for n in sys.modules):
        candidates = [m for m in ("bl_ext.user_default.mpfb", "mpfb")]
        for module in candidates:
            try:
                bpy.ops.preferences.addon_enable(module=module)
                break
            except Exception:  # noqa: BLE001; try the next spelling
                continue
    if not any(n.endswith("mpfb.services.targetservice") for n in sys.modules):
        raise SystemExit(
            "MPFB is not installed in this Blender. Install the extension "
            "first; run_mpfb_probe.py --install-mpfb does it for you.")
    for name in sys.modules:
        if name.endswith("bl_ext.user_default.mpfb") or name == "mpfb":
            return getattr(sys.modules[name], "VERSION", "unknown")
    return "unknown"


# ---------------------------------------------------------------------
# measuring
# ---------------------------------------------------------------------

def spans(obj) -> tuple[float, float, float]:
    """World-space X/Y/Z extents of the EVALUATED object.

    Evaluated, not raw: see trap 1 in the module docstring.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    matrix = evaluated.matrix_world
    coords = [matrix @ v.co for v in mesh.vertices]
    result = (
        max(c.x for c in coords) - min(c.x for c in coords),
        max(c.y for c in coords) - min(c.y for c in coords),
        max(c.z for c in coords) - min(c.z for c in coords),
    )
    evaluated.to_mesh_clear()
    return result


def stature(obj) -> float:
    """Sole-to-crown height in metres. Blender is Z-up, so this is the Z span."""
    return spans(obj)[2]


def _digest(points) -> str:
    """A short hash over a run of Blender vertex-like items, exact to the bit.

    `struct` on the raw doubles, not `round()`: the whole point is to separate
    "identical" from "identical to six decimals", and the difference being
    chased here is 1e-7 m.
    """
    import hashlib
    import struct
    hasher = hashlib.blake2b(digest_size=8)
    for point in points:
        hasher.update(struct.pack("<3d", point.co.x, point.co.y, point.co.z))
    return hasher.hexdigest()


NEUTRAL = dict(gender=0.5, age=0.5, height=0.5, muscle=0.5, weight=0.5,
               proportions=0.5, african=0.33, asian=0.33, caucasian=0.33)


class Character:
    """One MPFB human, driven by its macro vector."""

    def __init__(self):
        human_service = dynamic_import("mpfb.services.humanservice", "HumanService")
        self.target_service = dynamic_import("mpfb.services.targetservice", "TargetService")
        self.props = dynamic_import("mpfb.entities.objectproperties", "HumanObjectProperties")
        self.obj = human_service.create_human()

    def apply(self, **overrides) -> None:
        macros = dict(NEUTRAL)
        macros.update(overrides)
        for key, value in macros.items():
            self.props.set_value(key, value, entity_reference=self.obj)
        self.target_service.reapply_macro_details(self.obj)

    def stature(self) -> float:
        return stature(self.obj)

    def measure(self, **overrides) -> float:
        self.apply(**overrides)
        return self.stature()


# ---------------------------------------------------------------------
# the four experiments
# ---------------------------------------------------------------------

def probe_path_independence(character: Character) -> dict:
    """Is stature a pure function of the macro vector, or of the history?

    §4.3 of MPFB_UNITY_INVESTIGATION.md makes "the visual layer is a pure
    function of the phenotype dict" a hard rule. That rule is worthless if the
    tool underneath it accumulates state, so this is checked rather than
    assumed. It is falsifiable, and it FAILED: the same macro vector gives
    1.5912298129405826 m on a freshly created human and 1.5912296985043213 m
    once the human has been through a male state, 1.1e-7 m apart.

    That is a tenth of a micrometre and physically meaningless, but "pure
    function" is either true or it is not, and it is not.

    WHERE IT LIVES, narrowed by the digests recorded below rather than
    guessed. Across the five histories the key-block NAMES, ORDER and WEIGHTS
    are all bit-identical, and so is the Basis mesh; the first hypothesis --
    that a differing key-block order changed the summation order, was
    recorded, tested here, and falsified (one order, two statures). What does
    differ is the DATA of the three race key blocks
    (`$md-$as/$ca/$af-$fe-$yn`) once the human has been through a male state.

    A likely cause, NOT proven: `TargetService` writes a target into an
    existing key block with `only_modified_verts=True` and
    `smaller_than_counts_as_unmodified=0.0001`, so vertices the incoming
    target does not consider modified keep whatever the previous occupant of
    that key block left there. Reuse, not reload.

    THE ACTIONABLE RULE. Build each exported character on a FRESHLY created
    human. Because the divergence is in mesh data and not only in the derived
    stature, two characters that reach the same macro vector by different
    routes bake to different FBX files.
    """
    final = dict(gender=0.0, height=0.5)
    histories = {
        "fresh": [],
        "after_height_1": [dict(gender=0.0, height=1.0)],
        "after_height_0": [dict(gender=0.0, height=0.0)],
        "after_male_tall": [dict(gender=1.0, height=0.9)],
        "after_three_states": [dict(gender=0.2, height=0.13),
                               dict(gender=0.9, height=0.77),
                               dict(gender=0.4, height=0.31)],
    }
    results = {}
    for label, preamble in histories.items():
        for state in preamble:
            character.apply(**state)
        stature_m = character.measure(**final)
        keys = character.obj.data.shape_keys
        results[label] = {
            "stature_m": stature_m,
            "key_block_order": [k.name for k in keys.key_blocks] if keys else [],
            "key_block_weights": {k.name: float(k.value) for k in keys.key_blocks} if keys else {},
            "key_block_digest": {k.name: _digest(k.data) for k in keys.key_blocks} if keys else {},
            "base_mesh_digest": _digest(character.obj.data.vertices),
        }
    values = {r["stature_m"] for r in results.values()}
    orders = {tuple(r["key_block_order"]) for r in results.values()}
    return {"histories": results,
            "bit_identical": len(values) == 1,
            "distinct_statures": len(values),
            "distinct_key_orders": len(orders),
            "spread_mm": (max(values) - min(values)) * 1000}


def probe_height_curve(character: Character) -> dict:
    """Stature against the height macro, per sex, on a 0.05 grid."""
    curve = {}
    for label, gender in (("female", 0.0), ("male", 1.0)):
        curve[label] = [
            {"macro": round(i / 20, 4),
             "stature_m": character.measure(gender=gender, height=i / 20)}
            for i in range(21)
        ]
    return curve


def probe_dead_band(character: Character, step: float = 0.001) -> dict:
    """The interval around height=0.5 over which stature does not move.

    There are TWO stacked causes and only the second depends on the other
    macros, which is why this is measured per configuration rather than once:

      * `TargetService._interpolate_macro_components` returns NO height
        component at all for height in [0.49, 0.51], a hard-coded flat zone,
        and `2*(0.49 - v)` outside it, a double-rate ramp.
      * `calculate_target_stack_from_macro_info_dict(..., cutoff=0.01)` then
        drops any target whose weight is <= 0.01, and that weight is the
        PRODUCT gender * age * muscle * weight * height. Halving any factor
        therefore widens the band.

    The edge is a genuine step discontinuity, not just a plateau, so the
    returned `step_mm` is the stature that cannot be requested.

    `MOVED` rather than `!=`: `probe_path_independence` shows that repeated
    application of the same macro vector can wobble the last bits by ~1e-7 m,
    and an exact comparison would let that wobble end the scan early and
    report a dead band narrower than the real one.
    """
    MOVED = 1e-6  # metres; a micrometre is 40x the observed float wobble
    bands = {}
    configs = {
        "female": dict(gender=0.0),
        "male": dict(gender=1.0),
        "androgynous": dict(gender=0.5),
        "male_muscle_0": dict(gender=1.0, muscle=0.0),
    }
    for label, config in configs.items():
        reference = character.measure(height=0.5, **config)
        low = high = 0.5
        while low > 0.0:
            candidate = round(low - step, 6)
            if abs(character.measure(height=candidate, **config) - reference) > MOVED:
                break
            low = candidate
        while high < 1.0:
            candidate = round(high + step, 6)
            if abs(character.measure(height=candidate, **config) - reference) > MOVED:
                break
            high = candidate
        below = character.measure(height=round(low - step, 6), **config)
        bands[label] = {
            "low": low,
            "high": high,
            "width": round(high - low, 6),
            "stature_m": reference,
            "step_mm": (reference - below) * 1000,
        }
    return bands


def probe_coupling(character: Character) -> dict:
    """How much does each OTHER macro move stature, at a fixed height macro?

    The useful result is the zeros: if muscle/weight/proportions do not move
    stature, the engine can drive BMI and adiposity through them without
    disturbing a stature calibration, and the height inverse only has to be
    conditioned on the macros that do move it.
    """
    base = dict(gender=1.0, african=0.0, asian=0.0, caucasian=1.0)
    reference = character.measure(**base)
    deltas = {}
    cases = [("muscle", 0.0), ("muscle", 1.0), ("weight", 0.0), ("weight", 1.0),
             ("proportions", 0.0), ("proportions", 1.0),
             ("age", 0.0), ("age", 0.1875), ("age", 0.25), ("age", 0.75), ("age", 1.0),
             ("gender", 0.0)]
    for macro, value in cases:
        config = dict(base)
        config[macro] = value
        deltas[f"{macro}={value}"] = {
            "stature_m": character.measure(**config),
            "delta_mm": (character.stature() - reference) * 1000,
        }
    for label, config in (("african=1", dict(african=1.0, asian=0.0, caucasian=0.0)),
                          ("asian=1", dict(african=0.0, asian=1.0, caucasian=0.0)),
                          ("even_thirds", dict(african=0.33, asian=0.33, caucasian=0.33))):
        merged = dict(base)
        merged.update(config)
        deltas[label] = {
            "stature_m": character.measure(**merged),
            "delta_mm": (character.stature() - reference) * 1000,
        }
    return {"reference_m": reference, "deltas": deltas}


# ---------------------------------------------------------------------
# export
# ---------------------------------------------------------------------

def bake_shape_keys(obj) -> int:
    """Collapse the live shape-key mix into the base mesh; drop the keys.

    Trap 3. Returns how many key blocks were removed.
    """
    if not obj.data.shape_keys:
        return 0
    count = len(obj.data.shape_keys.key_blocks)
    mixed = obj.shape_key_add(name="_baked", from_mix=True)
    coords = [v.co.copy() for v in mixed.data]
    obj.shape_key_clear()
    for index, vertex in enumerate(obj.data.vertices):
        vertex.co = coords[index]
    return count


def export_body(out_dir: str, filename: str, ethnicity: str, **macros) -> dict:
    """One clean body for the Unity viewer, on a freshly created human.

    Fresh on purpose: `probe_path_independence` shows that a human driven
    through other macro vectors carries ~1e-7 m of that history in its race
    key-block data, so a body baked after the experiments would not be
    reproducible from its macro vector alone.

    The height macro is left at the NEUTRAL 0.5 rather than set to some target
    stature, because `HumanMesh` normalises the mesh to unit height on import
    and Unity scales it per villager. What the macro would still change is
    PROPORTION, because the min/max height targets are shape targets rather
    than a scale, so the neutral is the only value that adds no shape opinion.
    It is also the one value inside the dead band, where no height target
    applies at all.
    """
    export_service = dynamic_import("mpfb.services.exportservice", "ExportService")
    object_service = dynamic_import("mpfb.services.objectservice", "ObjectService")
    human_service = dynamic_import("mpfb.services.humanservice", "HumanService")

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    race = ETHNICITY_PRESETS[ethnicity]
    character = Character()
    character.apply(age=0.5, height=0.5, muscle=0.5, weight=0.5, proportions=0.5,
                    **race, **macros)
    authored = character.stature()

    human_service.add_builtin_rig(character.obj, "game_engine")
    root = export_service.create_character_copy(character.obj, name_suffix="_body")
    mesh = object_service.find_object_of_type_amongst_nearest_relatives(root, "Basemesh")
    export_service.bake_modifiers_remove_helpers(
        mesh, bake_masks=True, bake_subdiv=True, remove_helpers=True, also_proxy=True)
    dropped = bake_shape_keys(mesh)

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, filename)
    bpy.ops.object.select_all(action="DESELECT")
    root.select_set(True)
    for child in object_service.get_list_of_children(root):
        child.select_set(True)
    bpy.context.view_layer.objects.active = root
    bpy.ops.export_scene.fbx(filepath=path, use_selection=True,
                             add_leaf_bones=False, bake_anim=False)

    return {
        "path": path,
        "authored_stature_m": authored,
        "baked_stature_m": stature(mesh),
        "shape_keys_baked": dropped,
        "verts": len(mesh.data.vertices),
        "macros": {**{"age": 0.5, "height": 0.5, "muscle": 0.5, "weight": 0.5,
                      "proportions": 0.5}, **race, **macros},
    }


# The ethnicity macro is held FIXED (investigation memo §3.3: the engine has
# founder-lineage ancestry, not continental ancestry, so any value fed to
# these sliders would be invented at render time). Session 22 measured what
# the CHOICE costs: 18.18 mm of stature between these two. `even_thirds` is
# MPFB's own default and is the shipped one, because it implies nothing the
# engine does not model.
ETHNICITY_PRESETS = {
    "even_thirds": dict(african=0.33, asian=0.33, caucasian=0.33),
    "african": dict(african=1.0, asian=0.0, caucasian=0.0),
    "asian": dict(african=0.0, asian=1.0, caucasian=0.0),
    "caucasian": dict(african=0.0, asian=0.0, caucasian=1.0),
}


def export_variants(character: Character, out_dir: str) -> dict:
    """Three FBX files that differ only in how they were prepared.

    Exporting all three is the point: `baked` is the one that is correct, and
    the other two are kept so a regression can say WHICH rule was broken. They
    fail in different directions (trap 2 shrinks and rotates, trap 3 silently
    substitutes the neutral base mesh), and one global scale factor could never
    reconcile both.
    """
    export_service = dynamic_import("mpfb.services.exportservice", "ExportService")
    object_service = dynamic_import("mpfb.services.objectservice", "ObjectService")
    human_service = dynamic_import("mpfb.services.humanservice", "HumanService")

    os.makedirs(out_dir, exist_ok=True)
    results = {}

    def write(root, path):
        bpy.ops.object.select_all(action="DESELECT")
        root.select_set(True)
        for child in object_service.get_list_of_children(root):
            child.select_set(True)
        bpy.context.view_layer.objects.active = root
        bpy.ops.export_scene.fbx(filepath=path, use_selection=True,
                                 add_leaf_bones=False, bake_anim=False)

    def staged(suffix):
        root = export_service.create_character_copy(character.obj, name_suffix=suffix)
        mesh = object_service.find_object_of_type_amongst_nearest_relatives(root, "Basemesh")
        export_service.bake_modifiers_remove_helpers(
            mesh, bake_masks=True, bake_subdiv=True, remove_helpers=True, also_proxy=True)
        return root, mesh

    # A: no rig at all, which demonstrates trap 2.
    root, mesh = staged("_norig")
    path = os.path.join(out_dir, "mpfb_norig.fbx")
    write(root, path)
    results["norig"] = {"path": path, "blender_stature_m": stature(mesh),
                        "expect": "WRONG: 100x small, Z-up preserved"}

    character.obj = character.obj  # keep the original intact
    human_service.add_builtin_rig(character.obj, "game_engine")

    # B: sample 10's path: rig, but blendshapes left live. Demonstrates trap 3.
    root, mesh = staged("_rigged")
    path = os.path.join(out_dir, "mpfb_gamerig.fbx")
    write(root, path)
    results["gamerig"] = {"path": path, "blender_stature_m": stature(mesh),
                          "expect": "WRONG: neutral base mesh, blendshapes at 0"}

    # C: rig plus baked shape keys, the correct one.
    root, mesh = staged("_baked")
    dropped = bake_shape_keys(mesh)
    path = os.path.join(out_dir, "mpfb_baked.fbx")
    write(root, path)
    results["baked"] = {"path": path, "blender_stature_m": stature(mesh),
                        "shape_keys_baked": dropped,
                        "expect": "CORRECT: matches Blender exactly"}
    return results


# ---------------------------------------------------------------------

def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="directory for JSON and FBX")
    parser.add_argument("--export-macro", type=float, default=0.5151,
                        help="height macro for the exported character "
                             "(default 0.5151, the reachable stature nearest 1.75 m "
                             "for a mid-build adult male)")
    parser.add_argument("--mode", choices=("probe", "bodies"), default="probe",
                        help="probe = measure the macros; bodies = export the "
                             "two viewer bodies and nothing else")
    parser.add_argument("--ethnicity", choices=tuple(ETHNICITY_PRESETS),
                        default="even_thirds",
                        help="the FIXED ethnicity macro. See the note beside "
                             "ETHNICITY_PRESETS; the choice is worth 18.18 mm "
                             "of stature and is held constant by design.")
    args = parser.parse_args(argv)

    version = ensure_mpfb()

    if args.mode == "bodies":
        bodies = {
            "human_female.fbx": dict(gender=0.0),
            "human_male.fbx": dict(gender=1.0),
        }
        report = {
            "blender": bpy.app.version_string,
            "mpfb": str(version),
            "ethnicity": args.ethnicity,
            "bodies": {},
        }
        for filename, macros in bodies.items():
            result = export_body(args.out, filename, args.ethnicity, **macros)
            report["bodies"][filename] = result
            print(f"[BODY] {filename}: {result['baked_stature_m']:.6f} m, "
                  f"{result['verts']} verts, "
                  f"{result['shape_keys_baked']} shape keys baked out")
        out_path = os.path.join(args.out, "mpfb_bodies.json")
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
        print(f"[BODY] wrote {out_path}")
        return 0

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    character = Character()
    report = {
        "blender": bpy.app.version_string,
        "mpfb": str(version),
        "unit_system": bpy.context.scene.unit_settings.system,
        "scale_length": bpy.context.scene.unit_settings.scale_length,
        "path_independence": probe_path_independence(character),
        "height_curve": probe_height_curve(character),
        "dead_band": probe_dead_band(character),
        "coupling": probe_coupling(character),
    }

    # A FRESH human for the export, obeying the rule probe_path_independence
    # establishes: the one above has been driven through ~200 macro vectors,
    # and reused race key blocks carry ~1e-7 m of that history in their data.
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    subject = Character()
    subject.apply(gender=1.0, age=0.5, height=args.export_macro,
                  african=0.0, asian=0.0, caucasian=1.0)
    report["export_macro"] = args.export_macro
    report["export_stature_m"] = subject.stature()
    report["export_spans_xyz_m"] = list(spans(subject.obj))
    report["exports"] = export_variants(subject, args.out)

    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, "mpfb_probe.json")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(f"[PROBE] wrote {out_path}")
    print(f"[PROBE] authored stature {report['export_stature_m']:.6f} m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
