"""
What does MPFB's `BodyProportions` macro actually do? (item E5)

    blender -b -P mpfb/probe_proportions.py -- --out outputs/mpfb/proportions.json

WHY THIS EXISTS BEFORE THE MACRO IS DRIVEN. `sitting_height_ratio` is a real
anthropometric quantity: the scale-free split of stature into trunk and legs.
MakeHuman's macro is called `BodyProportions` and sits in a modifier group
called `macrodetails-proportions`, and the temptation is to assume those two
things are the same axis and wire them together.

They may not be. MakeHuman's own interface labels the two ends of this macro
"uncommon" and "ideal", which is the vocabulary of an AESTHETIC idealisation
rather than of a leg-to-torso ratio. If that is what it is, driving it from a
measured ratio would map an anthropometric variable onto a beauty axis and
call the result anthropometry, which is precisely the kind of claim this
project exists to not make.

This project has been wrong about MPFB's macros before, and it is documented:
session 22 found a declared dead band in `Height` where 1.75 m is literally
unreachable, and found that `muscle`, `weight` and `proportions` move stature
by exactly 0.00 mm when the obvious expectation was that they would. Both were
found by probing rather than by reading. So this probes.

WHAT IT MEASURES, and why these three numbers.

  * `stature`: sole to crown. Session 22 says proportions does not move it.
    Re-measured here because if that has changed, nothing else in this file
    can be interpreted.
  * `crotch_fraction`: the crotch height as a fraction of stature. The crotch
    is found geometrically and with no anatomical knowledge: among vertices
    near the mid-sagittal plane, it is the LOWEST one above the knees. Leg
    length is then crotch height and trunk is the rest, so
    `1 - crotch_fraction` is a direct mesh analogue of the sitting height
    ratio.
  * `waist_width` and `shoulder_width`: because if the macro turns out to be
    an aesthetic axis, this is where it will show, and reporting a null on
    the ratio without showing what DID move would be a finding with no
    alternative hypothesis in it.

WHAT COUNTS AS AN ANSWER. If `crotch_fraction` moves materially between
proportions 0.0 and 1.0 and stature does not, the macro is a trunk-to-leg
axis and `sitting_height_ratio` may drive it, with the direction read off the
sign. If it barely moves while the widths do, the macro is a shape
idealisation, the trait must NOT drive it, and E5 stays an engine-only item
until MakeHuman's own leg-length targets are wired up instead.
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


def _world_vertices(obj):
    """Evaluated world-space vertex coordinates.

    Evaluated, not raw: `Renderer.bounds` and raw `mesh.vertices` both lie
    once modifiers and shape keys are in play, which session 22 recorded after
    measuring a character as somebody else.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    matrix = evaluated.matrix_world
    coords = [matrix @ v.co for v in mesh.vertices]
    evaluated.to_mesh_clear()
    return coords


def _geometry(obj) -> dict:
    coords = _world_vertices(obj)
    zs = [c.z for c in coords]
    z_min, z_max = min(zs), max(zs)
    height = z_max - z_min
    if height <= 0:
        raise RuntimeError("degenerate mesh: zero stature")

    # The crotch, found without naming a single body part. Vertices within a
    # narrow slab of the mid-sagittal plane, above the knees so the ankles and
    # the gap between the feet cannot win, and then the lowest of them. On a
    # standing human that point is the crotch.
    slab = 0.01 * height
    knee = z_min + 0.35 * height
    midline = [c.z for c in coords if abs(c.x) < slab and c.z > knee]
    if not midline:
        raise RuntimeError("no mid-sagittal vertices found above the knee")
    crotch = min(midline)

    def band(fraction, half=0.03):
        lo = z_min + (fraction - half) * height
        hi = z_min + (fraction + half) * height
        return [c for c in coords if lo <= c.z <= hi]

    def extent_x(fraction):
        """LEFT-TO-RIGHT SPAN, ARMS INCLUDED, and the name says so because the
        first version of this called it `waist_width` and reported 0.96 m for
        a waist. At waist height the arms hang beside the body, so a naive x
        span there is most of an arm span. Kept because it is still a real
        measurement of how the macro reshapes the silhouette; just not a
        waist."""
        xs = [c.x for c in band(fraction)]
        return (max(xs) - min(xs)) if xs else 0.0

    def depth_y(fraction):
        """FRONT-TO-BACK depth. This one IS a torso measurement: the arms sit
        beside the trunk rather than in front of it, so they barely enter the
        y span, which is why the waist is measured on this axis and not the
        other."""
        ys = [c.y for c in band(fraction)]
        return (max(ys) - min(ys)) if ys else 0.0

    return {
        "stature_m": height,
        "crotch_fraction": (crotch - z_min) / height,
        "trunk_fraction": 1.0 - (crotch - z_min) / height,
        "span_x_at_waist_m": extent_x(0.62),
        "waist_depth_m": depth_y(0.62),
        "span_x_at_shoulder_m": extent_x(0.82),
        "verts": len(coords),
    }


def main(argv) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    version = PROBE.ensure_mpfb()

    # TWO BASE CHARACTERS, because the answer might depend on which one.
    # `blender_probe.probe_coupling` recorded proportions moving stature by
    # exactly 0.00 mm, and it measured a male caucasian while the obvious
    # thing to probe is MPFB's neutral. It also reused ONE character across
    # cases, which session 22's own finding 4 says is not safe: MPFB is not a
    # pure function of the macro vector. Running both bases here, on fresh
    # humans, is what turns a contradiction into a fact about which base.
    bases = {
        "neutral": {},
        "male_caucasian": dict(gender=1.0, african=0.0, asian=0.0,
                               caucasian=1.0),
    }

    verdict = {"mpfb": str(version), "blender": bpy.app.version_string,
               "bases": {}}

    for base_name, base in bases.items():
        rows = []
        # A FRESH human per setting, for finding 4 above.
        for value in (0.0, 0.25, 0.5, 0.75, 1.0):
            character = PROBE.Character()
            character.apply(proportions=value, **base)
            row = {"proportions": value}
            row.update(_geometry(character.obj))
            rows.append(row)
            print("[PROP] %-15s proportions=%.2f  stature %.4f m  "
                  "trunk %.4f  waist_depth %.4f  shoulder_span %.4f"
                  % (base_name, value, row["stature_m"], row["trunk_fraction"],
                     row["waist_depth_m"], row["span_x_at_shoulder_m"]))

        lo, hi = rows[0], rows[-1]
        summary = {
            "stature_delta_mm": (hi["stature_m"] - lo["stature_m"]) * 1000.0,
            "trunk_fraction_delta": hi["trunk_fraction"] - lo["trunk_fraction"],
            "waist_depth_delta_mm": (hi["waist_depth_m"] - lo["waist_depth_m"]) * 1000.0,
            "shoulder_span_delta_mm": (hi["span_x_at_shoulder_m"]
                                       - lo["span_x_at_shoulder_m"]) * 1000.0,
            "rows": rows,
        }
        verdict["bases"][base_name] = summary

    # The neutral base is the one the engine actually bakes at, so it is the
    # one the verdict is taken from.
    summary = verdict["bases"]["neutral"]
    verdict.update({
        "stature_delta_mm": summary["stature_delta_mm"],
        "trunk_fraction_delta": summary["trunk_fraction_delta"],
        "waist_delta_mm": summary["waist_depth_delta_mm"],
        "shoulder_delta_mm": summary["shoulder_span_delta_mm"],
    })

    # TWO NUMBERS DECIDE THIS, and a boolean would hide both.
    #
    # `expressible_sd` is how much of the real trait the macro can say at all:
    # the trunk fraction it moves across its whole 0-to-1 range, divided by
    # the population sd of sitting height ratio (0.021). A macro that cannot
    # cover a couple of sd cannot represent the trait even if it is the right
    # axis, because the trait's own tails are where the interesting villagers
    # are.
    #
    # `shoulder_coupling` is what comes along uninvited: the fractional change
    # in shoulder span over the same sweep. Anything large means the macro is
    # a composite shape idealisation rather than a proportions axis, and
    # driving it would put a shape change on screen that no modelled trait
    # authorises.
    SHR_POPULATION_SD = 0.021
    neutral_rows = verdict["bases"]["neutral"]["rows"]
    verdict["expressible_sd"] = abs(
        verdict["trunk_fraction_delta"]) / SHR_POPULATION_SD
    verdict["shoulder_coupling"] = (
        verdict["shoulder_delta_mm"] / 1000.0
        / neutral_rows[0]["span_x_at_shoulder_m"])
    print("[PROP] stature moved %.3f mm, trunk fraction moved %.4f"
          % (verdict["stature_delta_mm"], verdict["trunk_fraction_delta"]))
    print("[PROP] waist depth moved %.2f mm, shoulder span moved %.2f mm"
          % (verdict["waist_delta_mm"], verdict["shoulder_delta_mm"]))
    print("[PROP] the full macro range covers %.2f sd of sitting height ratio"
          % verdict["expressible_sd"])
    print("[PROP] and drags shoulder span %.1f%% with it"
          % (verdict["shoulder_coupling"] * 100.0))

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(verdict, fh, indent=2)
            fh.write("\n")
        print("[PROP] wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    raise SystemExit(main(argv))
