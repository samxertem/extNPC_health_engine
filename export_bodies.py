"""
Export one family's bodies as `.mhm` files (UNITY_PLAN Stage 8, engine half).

    python export_bodies.py                              # 20 villagers, seed 7
    python export_bodies.py --count 30 --seed 11
    python export_bodies.py --out outputs/unity/demo/bodies

Stage 8's question is not "can the engine emit a morph vector", which Stage 7
already answered. It is: **does genotype-driven variation alone read as a
family and a population, or does everyone look like a recolour of one person?**
That question can only be answered by looking, so this script's job is to
produce something worth looking at and to be honest about what it selected.

WHY A FAMILY AND NOT TWENTY RANDOM PEOPLE. Twenty unrelated villagers would
show variation and prove nothing, because variation is what an RNG gives you
for free. The claim under test is that *relatedness is visible*: that siblings
resemble each other more than cousins do, and cousins more than strangers. So
the selector walks the pedigree outward from a seed couple and REPORTS what it
found. If it cannot find siblings or a cousin pair it says so and exits
non-zero, because a Stage 8 picture without related people in it cannot answer
the Stage 8 question and would be worse than no picture at all.

THE ARGUMENT MATCHING TRAP, and how it is closed. This runs the world itself
rather than reading an exported bundle, because a `.mhm` needs
`phenotype_at_age()` and people.csv carries the mature phenotype with no
genome behind it. Run separately from `export_for_unity.py`, that means two
worlds built from two sets of flags, and if the flags differ at all the bodies
belong to different people than the ones on screen. Villager names would still
match often enough for the village to render, which is what makes it nasty.

So `--bundle` writes both from the SAME world object in one process, and that
is the intended way to use this script. `bodies.json` still records seed, tick
and git commit, and the Unity side compares them against the manifest it is
rendering and warns on a mismatch, because the two-command route remains
possible and someone will take it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from health_engine.phenotype_to_mhm import (
    CITED_BODYPARTS,
    COSMETIC_BODYPARTS,
    EYE_MESH_QUALITY,
    DEFAULT_ETHNICITY,
    ETHNICITY_PRESETS,
    phenotype_to_mhm,
    pigmentation,
)
from health_engine.mhm_assets import MissingAssetPack, load_catalogue
from simulation import DemographyParams, World
from simulation.export import git_commit


# ----------------------------------------------------------------------
# pedigree selection
# ----------------------------------------------------------------------

def _parents_of(world, name: str) -> Tuple[Optional[str], Optional[str]]:
    npc = world.people[name]
    pair = npc.parents or (None, None)
    return (pair[0] if len(pair) > 0 else None,
            pair[1] if len(pair) > 1 else None)


def _relations(world, names: Set[str]) -> Dict[str, List[Tuple[str, str]]]:
    """Which of the Stage 8 relationships are actually present in `names`.

    Returned as lists of pairs rather than counts so the caller can print an
    example of each. A verdict of "12 sibling pairs" that cannot name one is
    the kind of summary this project has a rule against.
    """
    children_of: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    for name in names:
        mother, father = _parents_of(world, name)
        if mother and father:
            children_of[(mother, father)].append(name)

    siblings: List[Tuple[str, str]] = []
    for kids in children_of.values():
        kids = sorted(kids)
        for i in range(len(kids)):
            for j in range(i + 1, len(kids)):
                siblings.append((kids[i], kids[j]))

    parent_child: List[Tuple[str, str]] = []
    for name in names:
        for parent in _parents_of(world, name):
            if parent and parent in names:
                parent_child.append((parent, name))

    # First cousins: their parents are siblings, and they are not siblings of
    # each other. Grandparents may be outside the selected set, which is fine
    # -- the relationship is a property of the pedigree, not of the picture.
    grandparents: Dict[str, Set[str]] = {}
    for name in names:
        gps: Set[str] = set()
        for parent in _parents_of(world, name):
            if parent and parent in world.people:
                for gp in _parents_of(world, parent):
                    if gp:
                        gps.add(gp)
        grandparents[name] = gps

    sibling_set = {frozenset(pair) for pair in siblings}
    cousins: List[Tuple[str, str]] = []
    ordered = sorted(names)
    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            a, b = ordered[i], ordered[j]
            if frozenset((a, b)) in sibling_set:
                continue
            if grandparents[a] & grandparents[b]:
                cousins.append((a, b))

    return {"siblings": siblings, "parent_child": parent_child, "cousins": cousins}


def select_family(world, count: int) -> List[str]:
    """`count` living villagers, chosen to maximise visible relatedness.

    Seeds on the living person with the most living first-degree relatives,
    then walks outward one relationship at a time: children, parents,
    partners, then their relatives in turn. Breadth-first on purpose, so the
    set fills with close relatives before distant ones and the picture is
    densest where the claim is strongest.
    """
    living = {n.name for n in world.living}
    if not living:
        raise SystemExit("the world has no living people; run more years")

    children_of: Dict[str, List[str]] = defaultdict(list)
    for name in world.people:
        for parent in _parents_of(world, name):
            if parent:
                children_of[parent].append(name)

    def neighbours(name: str) -> List[str]:
        out: List[str] = []
        out.extend(p for p in _parents_of(world, name) if p)
        out.extend(children_of.get(name, ()))
        meta = world.meta.get(name)
        partner = getattr(meta, "partner", "") if meta else ""
        if partner:
            out.append(partner)
        return [n for n in out if n in living]

    seed = max(living, key=lambda n: (len(neighbours(n)), n))

    chosen: List[str] = [seed]
    seen: Set[str] = {seed}
    frontier: List[str] = [seed]
    while frontier and len(chosen) < count:
        nxt: List[str] = []
        for name in frontier:
            for other in sorted(neighbours(name)):
                if other in seen:
                    continue
                seen.add(other)
                chosen.append(other)
                nxt.append(other)
                if len(chosen) >= count:
                    break
            if len(chosen) >= count:
                break
        frontier = nxt

    # The pedigree may simply be smaller than `count`. Topping up with
    # unrelated villagers is the right behaviour -- a village is not one
    # family -- but the caller is told, because it changes what the picture
    # can be used to argue.
    if len(chosen) < count:
        for name in sorted(living):
            if name not in seen:
                chosen.append(name)
                seen.add(name)
            if len(chosen) >= count:
                break

    return chosen[:count]


# ----------------------------------------------------------------------
# writing
# ----------------------------------------------------------------------

def _safe_stem(name: str) -> str:
    """A villager name to a filename stem that survives every filesystem.

    Villager names are generated, not typed, so this is defensive rather than
    load-bearing. It stays a pure function of the name (invariant 5, and the
    A4 cosmetic rule) so the same villager always lands on the same file.
    """
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in name)


def _channel_provenance(catalogue) -> dict:
    """What each visible channel is, in the manifest, in the file.

    Split three ways rather than two, because "cosmetic" and "constant" are
    different claims. A cosmetic channel varies between villagers and carries
    no biology; a constant does not vary at all and is a rendering decision.
    Blurring them would let `eyes`, which is a poly count, read as a phenotype.
    """
    if catalogue is None:
        return {"dressed": False,
                "note": "no asset pack installed; bodies carry morphs only"}

    return {
        "dressed": True,
        "cited": {channel: trait for channel, trait
                  in CITED_BODYPARTS.items()},
        "cosmetic": {channel: "blake2b of the villager's name, salted per "
                              "channel; carries no biology"
                     for channel in COSMETIC_BODYPARTS},
        "constant": {
            "eyes": f"{EYE_MESH_QUALITY}; a mesh resolution, not eye colour. "
                    f"Eye colour is a material and travels in `pigmentation`.",
        },
        "note": ("`cited` channels are driven by a modelled trait and may be "
                 "read as phenotype. `cosmetic` channels are invented, "
                 "reproducibly, from the name alone and must not be."),
    }


def write_bodies(world, names: List[str], out_dir: str,
                 ethnicity: str = DEFAULT_ETHNICITY,
                 catalogue=None) -> dict:
    """Write one `.mhm` per villager plus `bodies.json`. Returns the manifest.

    `catalogue` is an `mhm_assets.AssetCatalogue`, or None for bare bodies. It
    is threaded in rather than loaded here so that a caller with no asset pack
    installed still gets the Stage 8 bodies it always got, and so the choice
    between dressed and undressed is visible at the call site rather than
    decided by whether a file happens to exist.
    """
    os.makedirs(out_dir, exist_ok=True)

    entries = []
    for name in names:
        npc = world.people[name]
        stem = _safe_stem(name)
        # phenotype_at_age, never phenotype(): the mature phenotype is
        # age-blind by construction, so using it here is precisely the "a
        # child is a small adult" defect (item U6) that this stage fixes.
        pheno = npc.phenotype_at_age(npc.age)

        # The X-linked phenotypes are a SEPARATE dict on NPC and do not come
        # through `phenotype_at_age`, which returns TRAIT_TABLE traits only.
        # `pattern_baldness` is merged in because the bodypart layer cites it:
        # a bald villager gets no hair asset, and the reason he is bald is the
        # AR allele on the X he had from his mother. Merged rather than passed
        # separately so the value travels with the phenotype it belongs to and
        # cannot be forgotten by one of the two call sites.
        dressed = dict(pheno)
        dressed.update(npc.x_linked_phenotype())

        text = phenotype_to_mhm(dressed, npc.sex, npc.age,
                                name=stem, ethnicity=ethnicity,
                                catalogue=catalogue, villager_name=name)
        path = os.path.join(out_dir, f"{stem}.mhm")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

        mother, father = _parents_of(world, name)
        entries.append({
            "name": name,
            "stem": stem,
            "mhm": f"{stem}.mhm",
            "sex": npc.sex,
            "age": round(float(npc.age), 4),
            # The stature the baked mesh must be scaled TO on the Unity side.
            # It is not in the `.mhm` because the height macro is a shape
            # target, not a scale (see phenotype_to_mhm's docstring).
            "height_cm": round(float(pheno["height_cm"]), 4),
            "mother": mother or "",
            "father": father or "",
            "pedigree_f": round(float(world.inbreeding_of(name)), 6),
            "pigmentation": pigmentation(pheno),
            # Cited, so it belongs in the manifest beside the trait values
            # rather than only in the geometry: a reader looking at a bald
            # villager has to be able to check the claim against the pedigree.
            "pattern_baldness": bool(dressed.get("pattern_baldness", False)),
        })

    rel = _relations(world, set(names))
    manifest = {
        "bodies_schema": 1,
        "git_commit": git_commit(),
        "seed": int(world.seed),
        "tick": int(world.tick),
        "ethnicity_preset": ethnicity,
        "ethnicity_macros": ETHNICITY_PRESETS[ethnicity],
        "count": len(entries),
        # WHICH CHANNELS ARE A MEASUREMENT AND WHICH ARE DRESSING, recorded in
        # the file rather than left to a caption someone might not carry over.
        # A reader looking at these bodies has to be able to tell, without
        # reading the source, that a bald villager is bald because of the AR
        # allele on the X he had from his mother, and that his haircut is
        # nothing but a hash of his name.
        "appearance_channels": _channel_provenance(catalogue),
        "relationships": {
            "sibling_pairs": len(rel["siblings"]),
            "parent_child_pairs": len(rel["parent_child"]),
            "first_cousin_pairs": len(rel["cousins"]),
            "example_siblings": rel["siblings"][0] if rel["siblings"] else None,
            "example_cousins": rel["cousins"][0] if rel["cousins"] else None,
        },
        "bodies": entries,
    }
    with open(os.path.join(out_dir, "bodies.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    return manifest


# ----------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, default=60)
    ap.add_argument("--founders", type=int, default=12)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--demes", type=int, default=1)
    ap.add_argument("--migration", type=float, default=0.0)
    ap.add_argument("--count", type=int, default=20,
                    help="how many villagers to bake (default 20, Stage 8's number)")
    ap.add_argument("--ethnicity", default=DEFAULT_ETHNICITY,
                    choices=sorted(ETHNICITY_PRESETS),
                    help="the fixed ethnicity macro, item U5. Changing it "
                         "moves every stature by about 18 mm")
    ap.add_argument("--out", default=None,
                    help="where the .mhm files go "
                         "(default: <bundle>/bodies, or outputs/unity/demo/bodies)")
    ap.add_argument("--bundle", default=None, metavar="DIR",
                    help="also write the full Unity bundle here, from the SAME "
                         "world object. The recommended way to run this: it is "
                         "what guarantees the bodies and the villagers on screen "
                         "are the same people")
    ap.add_argument("--bare", action="store_true",
                    help="write bodies with no eyes, hair or clothes, the way "
                         "this script did before the CC0 asset pack existed. "
                         "Also the automatic behaviour when the pack is not "
                         "installed, in which case the reason is printed.")
    ap.add_argument("--allow-unrelated", action="store_true",
                    help="do not fail when the selection contains no siblings "
                         "or no cousin pair")
    args = ap.parse_args()

    params = DemographyParams(n_demes=args.demes, migration_rate=args.migration)
    print(f"  building world: {args.founders} founders, seed {args.seed}, "
          f"{args.years} years")
    t0 = time.perf_counter()
    world = World(n_founders=args.founders, seed=args.seed, params=params)
    for _ in range(args.years):
        world.step()
    print(f"    {len(world.living)} living after {time.perf_counter() - t0:.1f}s")

    out_dir = args.out or (os.path.join(args.bundle, "bodies") if args.bundle
                           else os.path.join("outputs", "unity", "demo", "bodies"))

    if args.bundle:
        # Written from the same `world` object, so the villagers in frames.csv
        # and the bodies in bodies/ cannot disagree about who exists.
        from simulation.export import export_world_dir
        bundle_path = export_world_dir(world, args.bundle,
                                       note="bodies exported alongside")
        print(f"    bundle -> {bundle_path}")

    names = select_family(world, args.count)
    catalogue = None
    if not args.bare:
        # Absent pack is a REPORTED fallback, never a silent one. An eyeless
        # mannequin is what item A2 existed to stop, and a run that quietly
        # produces one again is a regression nobody would attribute to this
        # line.
        try:
            catalogue = load_catalogue()
            print(f"  dressing from {len(catalogue.families())} asset families "
                  f"({catalogue.source})")
        except MissingAssetPack as exc:
            print(f"  NO ASSET PACK, bodies will be bare: {exc}")

    manifest = write_bodies(world, names, out_dir, ethnicity=args.ethnicity,
                            catalogue=catalogue)
    rel = manifest["relationships"]

    print(f"\n  wrote {manifest['count']} .mhm files -> {out_dir}")
    print(f"    ethnicity preset : {args.ethnicity} (item U5)")
    print(f"    sibling pairs    : {rel['sibling_pairs']}")
    print(f"    parent-child     : {rel['parent_child_pairs']}")
    print(f"    first cousins    : {rel['first_cousin_pairs']}")
    if rel["example_siblings"]:
        print(f"    e.g. siblings    : {' and '.join(rel['example_siblings'])}")
    if rel["example_cousins"]:
        print(f"    e.g. cousins     : {' and '.join(rel['example_cousins'])}")

    ages = sorted(b["age"] for b in manifest["bodies"])
    heights = sorted(b["height_cm"] for b in manifest["bodies"])
    print(f"    age range        : {ages[0]:.1f} to {ages[-1]:.1f} years")
    print(f"    stature range    : {heights[0]:.1f} to {heights[-1]:.1f} cm")

    if not args.allow_unrelated and not (rel["sibling_pairs"] and rel["first_cousin_pairs"]):
        print("\n  ! this selection cannot answer the Stage 8 question: it has "
              "no siblings or no cousin pair.\n    Run more years, or pass "
              "--allow-unrelated if a population picture is what you wanted.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
