"""Catalogue the MPFB assets installed on this machine (item A2's prerequisite).

    blender -b -P mpfb/list_assets.py -- --out health_engine/data/mpfb_assets.json

WHY A CATALOGUE AND NOT A HARDCODED LIST. A `.mhm` refers to a bodypart by
name AND uuid:

    eyes  HighPolyEyes  1b6a7e4d-...

MPFB's loader matches both, and the fallback when it cannot is worse than an
error. Read `HumanService._check_parse_mhm_bodypart_line`: if the name-and-uuid
pass finds nothing and deep search is on, the last resort compares each
candidate asset's own key against its own internal name, `given_name ==
mhclo_name`, and never looks at the name the `.mhm` asked for at all. So a
typo, a renamed asset or a pack the user has not installed does not fail. It
silently fits SOME OTHER pair of eyes and renders happily.

That is why nothing in this project hardcodes an asset name. This script asks
the installed MPFB what it actually has, writes it down with uuids, and
`phenotype_to_mhm` chooses only from what the catalogue lists. A missing pack
then produces a villager with no eyes and a loud line in the manifest, which
is a visible failure rather than an invisible substitution.

The catalogue is committed so the choice is reproducible, and it records the
pack's own version so a re-run on a different machine can be compared rather
than merely trusted.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys

import bpy


def _load_probe():
    """Load `blender_probe.py` by path, under a non-colliding module name.

    Same reason as `bake_bodies.py`: MPFB's own Blender package is also called
    `mpfb`, so putting the repository root on sys.path inside Blender makes
    `import mpfb` ambiguous.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "blender_probe.py")
    spec = importlib.util.spec_from_file_location("extnpc_blender_probe", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PROBE = _load_probe()

# (subdir, asset_type). `proxymeshes` is the odd one out, which is why the
# type is carried alongside rather than assumed to be "mhclo".
FAMILIES = (
    ("eyes", "mhclo"),
    ("eyebrows", "mhclo"),
    ("eyelashes", "mhclo"),
    ("teeth", "mhclo"),
    ("tongue", "mhclo"),
    ("hair", "mhclo"),
    ("clothes", "mhclo"),
    ("proxymeshes", "proxy"),
    ("skins", "mhmat"),
)


def catalogue() -> dict:
    asset_service = PROBE.dynamic_import("mpfb.services.assetservice", "AssetService")
    location_service = PROBE.dynamic_import("mpfb.services.locationservice",
                                            "LocationService")
    out = {
        "blender": bpy.app.version_string,
        "user_data": location_service.get_user_data(),
        "families": {},
    }

    for subdir, asset_type in FAMILIES:
        try:
            assets = asset_service.get_asset_list(subdir, asset_type)
        except Exception as e:                                   # noqa: BLE001
            out["families"][subdir] = {"error": str(e), "assets": []}
            continue

        entries = []
        for key in sorted(assets):
            asset = assets[key]
            entry = {
                "key": key,
                "label": asset.get("label"),
                "fragment": asset.get("fragment"),
            }
            # The uuid lives inside the .mhclo, not in the listing, so it has
            # to be read out of the file. Materials have no uuid at all.
            path = asset.get("full_path")
            if path and asset_type == "mhclo":
                entry["uuid"] = _read_uuid(path)
                entry["name_in_file"] = _read_name(path)
            entries.append(entry)

        out["families"][subdir] = {"count": len(entries), "assets": entries}

    return out


def _read_field(path: str, field: str):
    """Pull one header field out of a .mhclo. Plain text, one `key value` per line."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith(field + " "):
                    return line.split(" ", 1)[1].strip()
                # The vertex data starts after the header; stop rather than
                # scanning a few megabytes of numbers for a field that is not
                # there.
                if line.startswith("verts"):
                    break
    except OSError:
        return None
    return None


def _read_uuid(path: str):
    return _read_field(path, "uuid")


def _read_name(path: str):
    return _read_field(path, "name")


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="where to write the JSON")
    args = parser.parse_args(argv)

    version = PROBE.ensure_mpfb()
    data = catalogue()
    data["mpfb"] = str(version)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print(f"[ASSETS] mpfb {version}, user_data {data['user_data']}")
    for subdir, info in sorted(data["families"].items()):
        if "error" in info:
            print(f"[ASSETS] {subdir:12s} ERROR {info['error']}")
        else:
            named = sum(1 for a in info["assets"] if a.get("uuid"))
            print(f"[ASSETS] {subdir:12s} {info['count']:4d} assets, "
                  f"{named} with a uuid")
    print(f"[ASSETS] wrote {args.out}")

    total = sum(i.get("count", 0) for i in data["families"].values())
    if total == 0:
        print("[ASSETS] nothing installed. The makehuman_system_assets pack "
              "goes in " + str(data["user_data"]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
