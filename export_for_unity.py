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
from simulation.events import SHOCK_KINDS
from simulation.export import export_world_dir


def _parse_shocks(specs):
    """`["plague@30", "famine@55:0.8"]` -> `{year: (kind, magnitude)}`.

    WHY THIS EXISTS. `events.csv` is written from `world.event_log`, and the
    only thing that ever appends to that log is a shock draining out of
    `world.shock_queue` (world.py:224) -- which until now only the dashboard's
    buttons could fill. So every bundle this script produced had an empty
    events table, and the viewer's timeline markers were a feature nothing
    could exercise. A file that is always empty is indistinguishable from a
    file that is broken.

    Nothing new is simulated: this queues exactly what the dashboard queues,
    through the same `World.queue_shock`. A run without `--shock` is
    unchanged, which is what keeps the golden fixture and every other test
    looking at the same world they always did.
    """
    out = {}
    for spec in specs:
        try:
            kind, _, rest = spec.partition("@")
            year_s, _, mag_s = rest.partition(":")
            kind = kind.strip().lower()
            year = int(year_s)
            magnitude = float(mag_s) if mag_s else 0.6
        except ValueError:
            raise SystemExit(f"bad --shock '{spec}'; expected KIND@YEAR[:MAG]")
        if kind not in SHOCK_KINDS:
            raise SystemExit(f"unknown shock kind '{kind}'; "
                             f"known: {', '.join(sorted(SHOCK_KINDS))}")
        if year < 1:
            raise SystemExit(f"--shock year must be >= 1, got {year}")
        if year in out:
            # The queue is drained one per tick, so two shocks aimed at the
            # same year would silently land in different ones -- and the
            # timeline would mark a year nothing was asked to happen in.
            raise SystemExit(f"two shocks scheduled for year {year}; the "
                             f"engine drains one shock per tick")
        out[year] = (kind, magnitude)
    return out


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
    ap.add_argument("--shock", action="append", default=[], metavar="KIND@YEAR[:MAG]",
                    help="schedule a shock, e.g. plague@30 or famine@55:0.8. "
                         "Repeatable. Kinds: " + ", ".join(sorted(SHOCK_KINDS)))
    args = ap.parse_args()

    shocks = _parse_shocks(args.shock)

    params = DemographyParams(n_demes=args.demes,
                              migration_rate=args.migration)
    print(f"  building world: {args.founders} founders, seed {args.seed}, "
          f"{args.demes} deme(s), migration {args.migration}")

    t0 = time.perf_counter()
    world = World(n_founders=args.founders, seed=args.seed, params=params)
    for year in range(args.years):
        # Queued on the tick BEFORE the step that drains it, so the shock lands
        # in the year the caller named: World.step() increments tick first and
        # then pops the queue.
        scheduled = shocks.get(year + 1)
        if scheduled is not None:
            world.queue_shock(*scheduled)
        world.step()
        if scheduled is not None:
            print(f"    year {world.tick:4d}  {scheduled[0]} "
                  f"(magnitude {scheduled[1]:.2f})")
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
