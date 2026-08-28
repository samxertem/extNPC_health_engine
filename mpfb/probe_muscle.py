"""
What does MPFB's `Muscle` macro actually do, and which way? (item E4)

    blender -b -P mpfb/probe_muscle.py -- --out outputs/mpfb/muscle.json

WHY PROBE SOMETHING THIS OBVIOUS. Because the last two macros this project
assumed it understood both turned out to be different from the label.
`Height` has a declared dead band where 1.75 m is unreachable, and
`BodyProportions` moves shoulder span by 14% while covering only one standard
deviation of the ratio it is named after (`probe_proportions.py`). `Muscle` is
almost certainly muscularity and almost certainly runs low to high, but
`lean_mass_fraction` is about to be wired to it, and "almost certainly" is how
a villager ends up rendered as the inverse of their genome with nothing on
screen looking wrong.

WHAT IS MEASURED, and why not circumference. A limb circumference needs the
limb identified, and naming body parts is how the bake acquired its worst bug
(see `test_bake_channels.py`). These are all whole-mesh or slab measurements
that need no anatomy:

  * `volume_m3`: signed-tetrahedron volume over the closed mesh. The single
    best summary of "how much body is there", and the number that should move
    most if the macro adds tissue.
  * `chest_depth_m` and `thigh_depth_m`: front-to-back spans in a slab. Depth
    rather than width because the arms hang beside the torso and ruin an x
    span, which the proportions probe learned by reporting a 0.96 m waist.
  * `stature_m`: session 22 measured muscle moving stature by 0.00 mm at a
    male caucasian base. Re-measured here at both bases, because the same
    claim about `proportions` turned out to be base-dependent.

WHAT COUNTS AS AN ANSWER. Volume rising monotonically from macro 0 to 1 means
the macro is muscularity and points the way the name suggests, and
`muscle_macro` may map a high `lean_mass_fraction` to a high macro value. A
flat or non-monotonic volume means it is doing something else and the trait
must not drive it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import blender_probe as PROBE          # noqa: E402


def _evaluated_mesh(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    return evaluated, evaluated.to_mesh()


def _geometry(obj) -> dict:
    evaluated, mesh = _evaluated_mesh(obj)
    matrix = evaluated.matrix_world
    coords = [matrix @ v.co for v in mesh.vertices]
    zs = [c.z for c in coords]
    z_min, z_max = min(zs), max(zs)
    height = z_max - z_min

    # Signed tetrahedron volume about the origin. Exact for a closed mesh and
    # sign-stable for a consistently wound one, so the absolute value is the
    # enclosed volume whichever way MPFB winds its faces.
    volume = 0.0
    for poly in mesh.polygons:
        idx = poly.vertices
        for k in range(1, len(idx) - 1):
            a, b, c = coords[idx[0]], coords[idx[k]], coords[idx[k + 1]]
            volume += a.dot(b.cross(c)) / 6.0
    evaluated.to_mesh_clear()

    def depth_at(fraction, half=0.03):
        lo = z_min + (fraction - half) * height
        hi = z_min + (fraction + half) * height
        ys = [c.y for c in coords if lo <= c.z <= hi]
        return (max(ys) - min(ys)) if ys else 0.0

    return {
        "stature_m": height,
        "volume_m3": abs(volume),
        "chest_depth_m": depth_at(0.75),
        "thigh_depth_m": depth_at(0.30),
    }


def main(argv) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    version = PROBE.ensure_mpfb()
    bases = {
        "neutral": {},
        "male_caucasian": dict(gender=1.0, african=0.0, asian=0.0,
                               caucasian=1.0),
    }
    verdict = {"mpfb": str(version), "blender": bpy.app.version_string,
               "bases": {}}

    for base_name, base in bases.items():
        rows = []
        for value in (0.0, 0.25, 0.5, 0.75, 1.0):
            # Fresh human per setting: MPFB is not a pure function of the
            # macro vector (session 22, finding 4).
            character = PROBE.Character()
            character.apply(muscle=value, **base)
            row = {"muscle": value}
            row.update(_geometry(character.obj))
            rows.append(row)
            print("[MUSCLE] %-15s muscle=%.2f  stature %.4f m  volume %.5f m3"
                  "  chest %.4f  thigh %.4f"
                  % (base_name, value, row["stature_m"], row["volume_m3"],
                     row["chest_depth_m"], row["thigh_depth_m"]))

        lo, hi = rows[0], rows[-1]
        volumes = [r["volume_m3"] for r in rows]
        verdict["bases"][base_name] = {
            "stature_delta_mm": (hi["stature_m"] - lo["stature_m"]) * 1000.0,
            "volume_delta_pct": (hi["volume_m3"] / lo["volume_m3"] - 1.0) * 100.0,
            # Direction-agnostic, because the answer turned out to be
            # "falling" and a flag named `rising` reporting False would leave
            # a reader unable to tell monotonic-falling from non-monotonic.
            "volume_monotonic_rising": all(
                b > a for a, b in zip(volumes, volumes[1:])),
            "volume_monotonic_falling": all(
                b < a for a, b in zip(volumes, volumes[1:])),
            "chest_delta_mm": (hi["chest_depth_m"] - lo["chest_depth_m"]) * 1000.0,
            "thigh_delta_mm": (hi["thigh_depth_m"] - lo["thigh_depth_m"]) * 1000.0,
            "rows": rows,
        }

    neutral = verdict["bases"]["neutral"]
    print("[MUSCLE] neutral: volume %+.2f%% across the range, monotonic rising: %s"
          % (neutral["volume_delta_pct"], neutral["volume_monotonic_rising"]))
    print("[MUSCLE] neutral: stature moved %.3f mm, chest %+.2f mm, thigh %+.2f mm"
          % (neutral["stature_delta_mm"], neutral["chest_delta_mm"],
             neutral["thigh_delta_mm"]))
    print("[MUSCLE] higher macro means more body: %s"
          % (neutral["volume_delta_pct"] > 0))

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(verdict, fh, indent=2)
            fh.write("\n")
        print("[MUSCLE] wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    raise SystemExit(main(argv))
