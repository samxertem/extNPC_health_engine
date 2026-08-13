"""
Export a world for the Unity viewer.

    python export_for_unity.py                          # 60 years, 12 founders
    python export_for_unity.py --years 120 --demes 4 --migration 0.08
    python export_for_unity.py --out "D:/Unity/MyGame/Assets/StreamingAssets/extnpc/demo"

Writes the bundle described in `reads/UNITY_PLAN.md` Part 3 as plain files:
manifest.json, people.csv, history.csv, pedigree.csv, frames.csv, demes.csv,
flows.csv, events.csv, README.txt.

The Unity package (`unity/com.samal.extnpc`) reads such a directory from
`StreamingAssets/extnpc/<worldName>/`, or from any absolute path via the
loader's `absolutePathOverride` -- which is the convenient one while
iterating, because it needs no copying.

Nothing here is new science. This runs the engine exactly as the dashboard
does and serialises the result; every number in the bundle was produced by
the same code paths the validation harness covers.

TIMING, so a long run is not a surprise: roughly 1.7 ms per living person per
simulated year on a 2026 laptop. A 60-year, 12-founder world is a couple of
seconds; a 600-person village is nearer a second per year. Export is a batch
job, and that is the whole reason the viewer reads files instead of stepping
the engine live.
"""

from __future__ import annotations

import argparse
import os
import time

from simulation import DemographyParams, World
from simulation.export import export_world_dir


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, default=60,
                    help="simulated years to run (default 60)")
    ap.add_argument("--founders", type=int, default=12,
                    help="founding population (default 12)")
    ap.add_argument("--seed", type=int, default=7,
                    help="RNG seed; the same seed replays exactly (default 7)")
    ap.add_argument("--demes", type=int, default=1,
                    help="settlements. >1 gives migration flows and a "
                         "defined F_ST (default 1)")
    ap.add_argument("--migration", type=float, default=0.0,
                    help="per-person yearly migration probability (default 0)")
    ap.add_argument("--out", default=os.path.join("outputs", "unity", "demo"),
                    help="output directory (created if absent)")
    ap.add_argument("--note", default="",
                    help="free-text note recorded in manifest.json")
    ap.add_argument("--no-frames", action="store_true",
                    help="omit the longitudinal tables (analysis-only bundle)")
    args = ap.parse_args()

    params = DemographyParams(n_demes=args.demes,
                              migration_rate=args.migration)
    print(f"  building world: {args.founders} founders, seed {args.seed}, "
          f"{args.demes} deme(s), migration {args.migration}")

    t0 = time.perf_counter()
    world = World(n_founders=args.founders, seed=args.seed, params=params)
    for year in range(args.years):
        world.step()
        if (year + 1) % 20 == 0:
            print(f"    year {year + 1:4d}  living {len(world.living):4d}")
    t_sim = time.perf_counter() - t0

    t0 = time.perf_counter()
    out = export_world_dir(world, args.out, note=args.note,
                           include_frames=not args.no_frames)
    t_exp = time.perf_counter() - t0

    print(f"\n  simulated {args.years} years in {t_sim:.1f}s "
          f"({t_sim / max(args.years, 1) * 1000:.0f} ms/year)")
    print(f"  exported in {t_exp:.1f}s -> {out}\n")

    total = 0
    for name in sorted(os.listdir(out)):
        size = os.path.getsize(os.path.join(out, name))
        total += size
        print(f"    {name:16s} {size:>12,d} bytes")
    print(f"    {'TOTAL':16s} {total:>12,d} bytes")

    # The snapshot ring is capped; a run past the cap loses its earliest
    # years. Say so here as well as in the manifest, because the person
    # running the export is the one who can choose to run it shorter.
    if world.snapshots.first_tick > 0:
        print(f"\n  ! frames.csv is TRUNCATED: the engine retains at most "
              f"{world.snapshots._frames.maxlen} yearly frames, so this "
              f"bundle starts at year {world.snapshots.first_tick}, not 0.")

    print(f"\n  Unity: point ExtNpcWorldLoader.absolutePathOverride at")
    print(f"         {os.path.abspath(out)}")
    print(f"  or copy it to StreamingAssets/extnpc/<worldName>/\n")


if __name__ == "__main__":
    main()
