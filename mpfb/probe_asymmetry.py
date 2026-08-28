"""
Do MPFB's asymmetry targets survive the `.mhm` boundary? (item E6)

    blender -b -P mpfb/probe_asymmetry.py -- --out outputs/mpfb/asymmetry.json

WHY THIS RUNS BEFORE THE ENGINE LAYER IS WRITTEN. E6 is fluctuating asymmetry,
and the whole design depends on one uncertain fact: that a signed asymmetry
computed in Python can reach the mesh through a text file. MPFB ships 62
asymmetry targets as 31 matched left/right pairs, but unlike the macros they
have NO modifier definition anywhere in MPFB's data, so it was not obvious
they could be addressed from a save file at all. If they cannot, E6 needs
Blender-side integration and the architecture that keeps this engine from
importing GPLv3 code has to be reopened.

Reading the loader suggested they can: `TargetService.
translate_mhm_target_line_to_target_fragment` takes a `modifier` line, strips a
directory prefix at the `/`, and hands the remainder to `target_full_path`.
So `modifier asym/asym-eye-1-l 0.8` should resolve to the shipped
`asym/asym-eye-1-l.target.gz`. Reading is not measuring, and this project has
been wrong about MPFB twice in one day, so it is measured.

WHAT IS MEASURED, all of it through `deserialize_from_mhm`, which is the exact
call the production bake makes:

  1. THAT IT RESOLVES AT ALL. A `.mhm` with an asymmetry line must produce a
     mesh that differs from the same `.mhm` without one. If it silently does
     nothing, every villager is symmetric and no test of the engine layer
     would ever notice, because the engine layer would be computing correct
     numbers that go nowhere.
  2. THAT LEFT AND RIGHT ARE MIRRORS. The engine maps a SIGNED asymmetry onto
     the l target for positive and the r target for negative, which is only
     coherent if the two are opposite deformations. Measured as the x centroid
     of the head: mirrored targets must give centroids of opposite sign and
     near-equal magnitude.
  3. THAT THE EFFECT SCALES. A weight of 0.5 should displace about half as far
     as 1.0, or the engine's continuous asymmetry lands on a switch.

The head centroid is used rather than a whole-mesh vertex comparison because
MPFB keeps a fixed topology but gives no left-to-right vertex mapping, so
"mirror" has to be measured on an aggregate rather than vertex by vertex.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import blender_probe as PROBE          # noqa: E402

# One facial pair, chosen because the eye targets are the largest family (8 of
# the 31) and a face is where a reader looks. The trunk and breast pairs are
# deliberately NOT probed here: they are the two that break the naming rule
# with a double-m `asymm-` prefix, and they are checked by the engine-side test
# that matches every declared feature against the install.
FEATURE = "asym-eye-1"

_MHM_HEAD = """# Written by extNPC probe_asymmetry
version v1.2.0
name extnpc
tags
camera 0.0 0.0 0.0 0.0 0.0 1.0
modifier macrodetails/Gender 0.500000
modifier macrodetails/Age 0.500000
modifier macrodetails/African 0.330000
modifier macrodetails/Asian 0.330000
modifier macrodetails/Caucasian 0.330000
modifier macrodetails-universal/Muscle 0.500000
modifier macrodetails-universal/Weight 0.500000
modifier macrodetails-height/Height 0.500000
modifier macrodetails-proportions/BodyProportions 0.500000
"""

_MHM_TAIL = """skeleton game_engine.mhskel
subdivide False
"""


def _write_mhm(path: str, asym_lines) -> str:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_MHM_HEAD)
        for name, weight in asym_lines:
            fh.write(f"modifier asym/{name} {weight:.6f}\n")
        fh.write(_MHM_TAIL)
    return path


def _load(mhm_path: str):
    """Through `deserialize_from_mhm`, the call the production bake makes."""
    human_service = PROBE.dynamic_import("mpfb.services.humanservice",
                                         "HumanService")
    settings = dict(human_service.get_default_deserialization_settings())
    settings.update({
        "clothes_deep_search": False,
        "bodypart_deep_search": False,
        "load_clothes": False,
        "subdiv_levels": 0,
    })
    return human_service.deserialize_from_mhm(mhm_path, settings)


def _measure(obj) -> dict:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    matrix = evaluated.matrix_world
    coords = [matrix @ v.co for v in mesh.vertices]
    evaluated.to_mesh_clear()

    zs = [c.z for c in coords]
    z_min, z_max = min(zs), max(zs)
    height = z_max - z_min
    head_floor = z_min + 0.85 * height
    head = [c for c in coords if c.z >= head_floor]
    if not head:
        raise RuntimeError("no head vertices found")

    return {
        "verts": len(coords),
        "stature_m": height,
        # In METRES. Sub-millimetre numbers are expected: an asymmetry target
        # is a small facial displacement, not a deformity.
        "head_centroid_x_m": sum(c.x for c in head) / len(head),
        "body_centroid_x_m": sum(c.x for c in coords) / len(coords),
    }


def _clear():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def main(argv) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    version = PROBE.ensure_mpfb()
    tmp = tempfile.mkdtemp(prefix="extnpc-asym-")

    cases = {
        "symmetric": [],
        "left_full": [(f"{FEATURE}-l", 1.0)],
        "right_full": [(f"{FEATURE}-r", 1.0)],
        "left_half": [(f"{FEATURE}-l", 0.5)],
    }

    rows = {}
    for label, lines in cases.items():
        _clear()
        path = _write_mhm(os.path.join(tmp, f"{label}.mhm"), lines)
        obj = _load(path)
        rows[label] = _measure(obj)
        print("[ASYM] %-11s head centroid x %+.8f m  body %+.8f m  verts %d"
              % (label, rows[label]["head_centroid_x_m"],
                 rows[label]["body_centroid_x_m"], rows[label]["verts"]))

    base = rows["symmetric"]["head_centroid_x_m"]
    left = rows["left_full"]["head_centroid_x_m"] - base
    right = rows["right_full"]["head_centroid_x_m"] - base
    half = rows["left_half"]["head_centroid_x_m"] - base

    verdict = {
        "mpfb": str(version),
        "blender": bpy.app.version_string,
        "feature": FEATURE,
        "rows": rows,
        "left_shift_m": left,
        "right_shift_m": right,
        "half_shift_m": half,
        # 1: does it reach the mesh at all
        "resolves_through_mhm": abs(left) > 1e-9,
        # 2: are l and r opposite deformations of similar size
        "left_and_right_are_mirrored": (
            left * right < 0
            and abs(abs(left) - abs(right)) <= 0.25 * max(abs(left), abs(right))
        ),
        # 3: is a half weight about half the displacement
        "scales_with_weight": (
            abs(left) > 1e-9 and 0.3 <= abs(half) / abs(left) <= 0.7
        ),
    }

    print("[ASYM] left shift %+.8f m, right shift %+.8f m, half %+.8f m"
          % (left, right, half))
    print("[ASYM] resolves through .mhm: %s" % verdict["resolves_through_mhm"])
    print("[ASYM] l and r are mirrored:  %s" % verdict["left_and_right_are_mirrored"])
    print("[ASYM] scales with weight:    %s" % verdict["scales_with_weight"])

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(verdict, fh, indent=2)
            fh.write("\n")
        print("[ASYM] wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    raise SystemExit(main(argv))
