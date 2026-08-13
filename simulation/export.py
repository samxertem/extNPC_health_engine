"""
Exporting a run: tabular data for analysis, and a manifest for provenance.
==========================================================================

The dashboard is where you *watch* a run; this is how you get it out. The
target is a thesis workflow -- read the tables in R, pandas or a spreadsheet,
and be able to say exactly which code and which parameters produced them.

What is here
------------
* `people_table`  -- one row per individual who has EVER lived, with the
  phenotypes, the pedigree quantities (#31), the load and CNV counts (#12),
  the deme, the parents and the death record. Wide and flat, because that is
  what a statistics package wants.
* `history_table` -- one row per simulated year: every metric the dashboard
  charts, so any figure in the thesis can be re-drawn from the CSV rather
  than screenshotted.
* `pedigree_table` -- one edge per parent-child link. Enough to rebuild the
  pedigree in `kinship2`, `pedigreemm` or networkx.
* `manifest` -- seed, every parameter, the git commit, library versions and
  summary statistics. The provenance sidecar: a figure without one cannot be
  reproduced, and a thesis figure that cannot be reproduced is a liability.

Design notes
------------
Deliberately **no pandas dependency**. The project pins numpy/plotly/dash and
nothing else; `csv` from the standard library writes exactly the same file.

Every row is written for the individual as they are *now* (or as they were at
death). This is a cross-sectional dump, not a longitudinal one -- per-year
per-person state would need the snapshot ring, which is capped at 600 frames
and holds ~12 scalars rather than the full phenotype. `history_table` is the
longitudinal view, at population level.
"""

from __future__ import annotations

import csv
import io
import json
import platform
import subprocess
import zipfile
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

import numpy as np

# The engine-ready save lives next door; re-exported so callers have one
# import for "get this run out of the dashboard".
from .worldsave import (SAVE_FORMAT_VERSION, _catalogue_mode,  # noqa: F401
                        build_world_save, load_world_save, world_state)
from .snapshots import MAX_FRAMES as SNAPSHOT_MAX_FRAMES

# Version of the BUNDLE CONTRACT -- the set of files and the meaning of their
# columns. A consumer outside Python (the Unity viewer) has no way to notice a
# silently reshaped table, so it checks this and refuses what it cannot read.
# Bump on: a file added or removed, a column renamed or retyped, a unit change.
# Do NOT bump for: a new column appended to an existing table.
BUNDLE_SCHEMA: int = 1

# Phenotype fields worth a column each. The full dict is ~39 traits; these are
# the ones with an interpretation someone would actually model.
EXPORT_TRAITS: List[str] = [
    "height_cm", "bmi", "adiposity", "aerobic_capacity", "insulin_sensitivity",
    "bp_set_point", "lipid_profile", "lung_capacity", "immune_reactivity",
    "immune_resilience", "inflammation_tone", "chronic_illness_predisposition",
    "openness", "conscientiousness", "extraversion", "agreeableness",
    "neuroticism", "chronotype", "interoceptive_accuracy",
    "skin_tone", "hair_pigment", "eye_color", "vision_acuity",
    "hearing_ability", "handedness",
]


def _safe(value):
    """CSV-friendly scalar: numpy types out, plain Python in."""
    if value is None:
        return ""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def git_commit() -> str:
    """The commit the run came from, or a marker saying we could not tell.

    Never raises: an export must not fail because the project was copied out
    of its repository.
    """
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            sha = out.stdout.strip()
            dirty = subprocess.run(["git", "status", "--porcelain"],
                                   capture_output=True, text=True, timeout=5)
            suffix = "-dirty" if dirty.stdout.strip() else ""
            return sha + suffix
    except Exception:                                    # noqa: BLE001
        pass
    return "unknown"


# ---------------------------------------------------------------------
# people
# ---------------------------------------------------------------------

def people_rows(world, living_only: bool = False) -> List[dict]:
    """One dict per individual. Dead people are included by default -- a
    survival analysis needs them, and excluding them is the classic way to
    accidentally condition on survival."""
    alive = {n.name for n in world.living}
    rows: List[dict] = []
    for name, npc in world.people.items():
        if living_only and name not in alive:
            continue
        meta = world.meta.get(name)
        ph = npc.phenotype()
        mother, father = (npc.parents or (None, None))[:2] or (None, None)
        row = {
            "name": name,
            "given_name": name.rsplit("-", 1)[0],
            "sex": npc.sex,
            "age": npc.age,
            "alive": name in alive,
            "generation": npc.generation,
            "life_stage": npc.life_stage(),
            "mother": mother or "",
            "father": father or "",
            "deme": getattr(meta, "deme", 0),
            "deme_label": _deme_label(getattr(meta, "deme", 0)),
            "birth_tick": getattr(meta, "birth_tick", None),
            "death_tick": getattr(meta, "death_tick", None),
            "death_cause": getattr(meta, "death_cause", ""),
            "partner": getattr(meta, "partner", "") or "",
            "n_children": getattr(meta, "n_children", 0),
            "resource_access": getattr(meta, "resource_access", 1.0),
            "dominant_lineage": _dominant(getattr(meta, "ancestry", None)),
            "lineage_purity": _purity(getattr(meta, "ancestry", None)),
            # genetics
            "heterozygosity": npc.heterozygosity(),
            "de_novo_mutations": npc.de_novo_mutations,
            # roadmap #31 / #12
            "pedigree_f": world.inbreeding_of(name),
            "realised_f": npc.realised_inbreeding(),
            "relative_viability": npc.relative_viability(),
            # The engine's SECOND cost of inbreeding, and the reason it is a
            # column rather than something a consumer works out: recessive load
            # decides survival (relative_viability) while directional dominance
            # decides stature, they are independent mechanisms from different
            # literatures (Morton 1956 vs Joshi 2015), and a viewer that
            # recomputed this from F would be doing biology. Expectation at
            # this pedigree F, in cm; negative = shorter than the outbred mean.
            "stature_cost_cm": _stature_cost(world.inbreeding_of(name)),
            "hidden_load_alleles": _load_carried(npc),
            "expressed_load_homozygotes": _load_expressed(npc),
            # Named recessive disorders (diseases.py): affected = homozygous
            # at a labelled panel locus, carrier = heterozygous. Semicolon-
            # joined so the column stays one CSV field.
            "mendelian_diagnoses": ";".join(
                d.name for d in npc.mendelian_diagnoses()),
            "mendelian_carrier_of": ";".join(
                d.name for d in npc.mendelian_carrier_of()),
            "cnv_count": len(npc.cnv_variants() or []),
            # physiology / epigenetics
            "inflammation_state": npc.inflammation_state,
            "epigenetic_age_accel": npc.epigenetic_age_acceleration,
            "effective_aerobic_capacity": npc.effective_aerobic_capacity(),
            "n_medical_conditions": len(npc.medical_conditions),
            "medical_conditions": ";".join(
                sorted(getattr(c, "name", str(c)) for c in npc.medical_conditions)),
            # parallel inheritance layers
            "mito_haplogroup": getattr(npc.mito, "haplogroup", "") if npc.mito else "",
            "heteroplasmy": getattr(npc.mito, "heteroplasmy", "") if npc.mito else "",
            # age-expressed vs mature stature (#13)
            "height_at_age_cm": npc.height_at_age(),
        }
        for trait in EXPORT_TRAITS:
            if trait in ph:
                row[f"trait_{trait}"] = ph[trait]
        rows.append({k: _safe(v) for k, v in row.items()})
    return rows


def _stature_cost(F: float) -> float:
    """
    Expected stature shift in cm at pedigree F; exactly 0.0 for an outbred
    individual. Delegates to the engine's own closed form -- this module does
    not own the model, it only serialises it.

    DELIBERATELY UNGUARDED. An earlier version wrapped the call in
    `except Exception: return 0.0`, which converts a broken model into the
    statement "this individual is outbred" -- a plausible wrong number in a
    column, which is worse than a loud failure and is the thing the manifest's
    caveats exist to avoid. `dashboard/inspector.py:157` calls
    `predicted_depression` unguarded too, and a guard here would have made the
    export quietly disagree with the drawer it is supposed to match.
    """
    if not F or F <= 1e-9:
        return 0.0
    from health_engine.inbreeding import predicted_depression
    return float(predicted_depression("height_cm", float(F)))


def _deme_label(d) -> str:
    from .community import deme_label
    try:
        return deme_label(int(d))
    except Exception:                                    # noqa: BLE001
        return ""


def _dominant(ancestry) -> str:
    if not ancestry:
        return ""
    return max(ancestry.items(), key=lambda kv: kv[1])[0]


def _purity(ancestry) -> float:
    if not ancestry:
        return 0.0
    return float(max(ancestry.values()))


def _load_carried(npc) -> int:
    load = getattr(npc, "load", None)
    if load is None:
        return 0
    dosage = getattr(load, "dosage", None)
    return int(np.count_nonzero(dosage)) if dosage is not None else 0


def _load_expressed(npc) -> int:
    load = getattr(npc, "load", None)
    if load is None:
        return 0
    dosage = getattr(load, "dosage", None)
    return int(np.count_nonzero(np.asarray(dosage) == 2)) if dosage is not None else 0


# ---------------------------------------------------------------------
# history and pedigree
# ---------------------------------------------------------------------

def history_rows(world) -> List[dict]:
    """One row per simulated year -- every metric the dashboard charts."""
    return [{k: _safe(v) for k, v in row.items()} for row in world.history]


# ---------------------------------------------------------------------
# longitudinal per-person tables (the world-viewer feed)
# ---------------------------------------------------------------------
# `people.csv` is cross-sectional and `history.csv` is population-level, so
# neither can answer "where was this person standing in year 40?". The
# snapshot ring already holds exactly that -- see simulation/snapshots.py --
# and these three functions flatten it to long-format CSV.
#
# Nothing here computes anything. Every value is copied out of a frame that
# `snapshots.capture()` built after the step had settled, so this cannot
# perturb the RNG stream any more than reading the buffer can.
#
# HONEST LIMITS, inherited from the ring and not fixable here:
#   * frames hold LIVING people only -- a death is a disappearance;
#   * the ring is capped at MAX_FRAMES, so a long run loses its earliest
#     years. `manifest()["frames"]["truncated"]` says so rather than letting
#     a reader assume the export starts at year 0;
#   * frames carry ~18 scalars, NOT genomes. Deep genetics for a past tick is
#     not recoverable, by design.

# The four new tables' schemas, declared rather than derived. Two jobs: an
# empty table still writes a header (see `_csv_bytes`), and a test can assert
# that snapshots.py has not quietly gained or lost a field behind the
# contract's back -- which is the failure a downstream consumer could not
# diagnose on its own.
FRAME_COLUMNS: List[str] = [
    "tick", "name", "x", "y", "color", "sex", "age", "deme", "lineage",
    "purity", "generation", "children", "stress", "epi_accel", "aerobic",
    "conditions", "pedigree_f", "viability", "cnv", "height", "life_stage",
]
DEME_COLUMNS: List[str] = [
    "tick", "deme", "x", "y", "r", "n", "mean_stress", "max_stress",
    "dominant", "dominance", "dominant_color",
    # The settlement's NAME. Derived here rather than in the consumer:
    # `community.deme_label` maps an id onto a fixed name table, and a viewer
    # that reimplemented that table would hold a second copy of it that goes
    # stale the moment a name is added. Cheap to carry, impossible to drift.
    "label",
]
FLOW_COLUMNS: List[str] = ["tick", "x0", "y0", "x1", "y1", "w"]
EVENT_COLUMNS: List[str] = ["tick", "kind", "label"]

# The Mendelian panel as a REFERENCE table -- one row per modelled disorder,
# not per person. `people.csv` carries only the snake_case slug in
# `mendelian_diagnoses`, while every human-facing surface shows the gene and
# the disorder's display name ("dx GJB2" -> "GJB2 nonsyndromic deafness").
# Neither is derivable from the slug, so without this table a consumer either
# shows a slug or hardcodes a copy of an explicitly append-only catalogue.
#
# `q_lit` vs `q_engine` are BOTH here on purpose: the engine's frequency for a
# disorder is its assigned spectrum locus's, not the literature's, and cystic
# fibrosis is a documented misfit. Carrying both means a reader can see the
# discrepancy instead of assuming there is none.
DISEASE_COLUMNS: List[str] = [
    "name", "label", "gene", "omim", "onset",
    "q_lit", "q_engine", "s_lit", "s_engine", "citation",
]


def frame_rows(world) -> List[dict]:
    """One row per LIVING person per retained tick."""
    rows: List[dict] = []
    for frame in world.snapshots:
        tick = int(frame["tick"])
        for person in frame["people"]:
            row = {"tick": tick}
            row.update(person)
            rows.append({k: _safe(v) for k, v in row.items()})
    return rows


def deme_frame_rows(world) -> List[dict]:
    """One row per settlement per retained tick: centre, radius, headcount,
    stress and which bloodline dominates it."""
    rows: List[dict] = []
    for frame in world.snapshots:
        tick = int(frame["tick"])
        for deme in frame["demes"]:
            row = {"tick": tick}
            row.update(deme)
            # Added here rather than in snapshots.py: the ring stores one entry
            # per deme per tick, and the label is a pure function of the id, so
            # retaining ~600 copies of the same string per settlement would be
            # memory spent to avoid a lookup at export time.
            row["label"] = _deme_label(row.get("deme", 0))
            rows.append({k: _safe(v) for k, v in row.items()})
    return rows


def disease_rows(_world=None) -> List[dict]:
    """
    The Mendelian panel: one row per modelled disorder.

    Not per-person and not per-tick -- this is the vocabulary that
    `people.csv`'s `mendelian_diagnoses` and `mendelian_carrier_of` slugs point
    into. It is a property of the engine build and its catalogue, so it takes
    no world; the parameter exists only so it matches every other `*_rows`
    signature in this module.

    Nothing is computed. `q` and `s` are read off the assignment that
    `health_engine/diseases.py` already made at import.
    """
    from health_engine.diseases import DISEASES

    rows: List[dict] = []
    for d in DISEASES:
        spec = d.spec
        rows.append({k: _safe(v) for k, v in {
            "name": spec.name,
            "label": spec.label,
            "gene": spec.gene,
            "omim": spec.omim,
            "onset": spec.onset,
            "q_lit": spec.q_lit,
            "q_engine": d.q,
            "s_lit": spec.s_lit,
            "s_engine": d.s,
            "citation": spec.citation,
        }.items()})
    return rows


def flow_rows(world) -> List[dict]:
    """One row per active migration route per retained tick. Empty in a
    single-deme world, which is the default -- there is nowhere to migrate."""
    rows: List[dict] = []
    for frame in world.snapshots:
        tick = int(frame["tick"])
        for flow in frame["flows"]:
            row = {"tick": tick}
            row.update(flow)
            rows.append({k: _safe(v) for k, v in row.items()})
    return rows


def event_rows(world) -> List[dict]:
    """One row per notable moment -- the timeline scrubber's markers."""
    return [{k: _safe(v) for k, v in e.items()}
            for e in getattr(world, "event_log", [])]


def pedigree_rows(world) -> List[dict]:
    """One row per parent-child edge, for kinship2 / pedigreemm / networkx."""
    rows = []
    for name, npc in world.people.items():
        for role, parent in zip(("mother", "father"), (npc.parents or ())):
            if parent:
                rows.append({"child": name, "parent": parent, "role": role})
    return rows


# ---------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------

def manifest(world, note: str = "") -> dict:
    """
    Provenance for the run: what produced these numbers, exactly.

    Includes summary statistics as well as parameters, so a table can be
    sanity-checked against its own manifest without re-running anything.
    """
    from dataclasses import asdict
    last = world.history[-1] if world.history else {}
    alive = world.living
    try:
        import dash
        import plotly
        versions = {"numpy": np.__version__, "plotly": plotly.__version__,
                    "dash": dash.__version__}
    except Exception:                                    # noqa: BLE001
        versions = {"numpy": np.__version__}

    snaps = world.snapshots
    n_frames = len(snaps)

    return {
        # Bump when the FILE SET or a column's meaning changes, so a consumer
        # (the Unity viewer) can refuse a bundle it would misread rather than
        # parsing it into nonsense.
        "bundle_schema": BUNDLE_SCHEMA,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note,
        "git_commit": git_commit(),
        # What frames.csv actually covers. `truncated` is the one that matters:
        # the snapshot ring is capped, so a run longer than the cap silently
        # loses its earliest years, and a viewer that assumed year 0 would
        # mislabel its own timeline.
        "frames": {
            "n_frames": n_frames,
            "first_tick": int(snaps.first_tick) if n_frames else None,
            "last_tick": int(snaps.last_tick) if n_frames else None,
            "max_frames": int(SNAPSHOT_MAX_FRAMES),
            "truncated": bool(n_frames and snaps.first_tick > 0),
        },
        "python": platform.python_version(),
        "platform": platform.platform(),
        "libraries": versions,
        "seed": int(world.seed),
        "tick": int(world.tick),
        # Which locus catalogue these genotypes mean anything under. Two
        # exports with the same seed and different catalogues are different
        # model versions, and nothing in the numbers themselves says so.
        "catalogue": _catalogue_mode(),
        "params": {k: _safe(v) for k, v in asdict(world.params).items()},
        "summary": {
            "n_living": len(alive),
            "n_ever_lived": len(world.people),
            "max_generation": int(last.get("max_generation", 0)),
            "heterozygosity": float(last.get("heterozygosity", float("nan"))),
            "mean_pedigree_f": float(last.get("mean_inbreeding", float("nan"))),
            "pct_consanguineous": float(last.get("pct_inbred", float("nan"))),
            "mean_relative_viability": float(last.get("mean_viability", float("nan"))),
            "fst": (float(last.get("fst", float("nan")))
                    if world.params.n_demes > 1 else None),
        },
        "caveats": [
            "F_ST is undefined with a single deme and is reported as null.",
            "people.csv is CROSS-SECTIONAL: each row is the individual as they "
            "are now, or as they were at death. history.csv is the "
            "longitudinal view, at population level.",
            "Dead individuals are included in people.csv on purpose; dropping "
            "them conditions the sample on survival.",
            "trait_* columns are MATURE phenotypes. height_at_age_cm is the "
            "stature actually expressed at the individual's current age (#13); "
            "the two differ for anyone still growing, and after ~40 through "
            "modelled height loss.",
            "mendelian_diagnoses names the recessive disorders an individual "
            "expresses (homozygous at a labelled load locus). The engine's "
            "carrier frequency for each is its assigned locus's, not the "
            "literature's -- cystic fibrosis is a documented misfit, since "
            "mutation-selection balance cannot sustain q=0.02 at s~1. See "
            "health_engine/diseases.py before using these epidemiologically.",
            "frames.csv holds LIVING people only, is capped at "
            f"{SNAPSHOT_MAX_FRAMES} years (see frames.truncated above before "
            "assuming it starts at year 0), and carries ~18 scalars rather "
            "than genomes. You can see who was alive, where they stood and "
            "their headline stats; you cannot reconstruct a dead person's "
            "genetics from it, by design.",
            "lethal_equivalents in history.csv is Morton's B re-measured from "
            "the living each year (purging). In a population of ~70 its "
            "single-year noise is ~0.05; only multi-generation trends are "
            "interpretable.",
        ],
    }


# ---------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------

def _csv_bytes(rows: Iterable[dict], fields: Optional[List[str]] = None) -> str:
    """
    Rows as CSV text.

    Pass `fields` for a table with a KNOWN schema. Without it an empty table
    writes an empty file -- no header, nothing to parse, indistinguishable
    from a truncated download. With it, an empty table still writes its
    header, so a consumer reads "zero rows" instead of guessing. This matters
    for flows.csv and events.csv, which are legitimately empty in the default
    single-deme, no-shock world.
    """
    rows = list(rows)
    if fields is None:
        if not rows:
            return ""
        # union of keys, first-seen order preserved, so a row that gained a
        # field late does not silently truncate the header
        fields = []
        for r in rows:
            for k in r:
                if k not in fields:
                    fields.append(k)
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore",
                            lineterminator="\n")
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return buf.getvalue()


def _bundle_files(world, note: str = "", living_only: bool = False,
                  include_frames: bool = True) -> Dict[str, str]:
    """
    The bundle as {filename: text}. ONE definition, shared by the .zip and the
    directory export, so the download and the on-disk world cannot drift apart
    -- which they would within a session if each built its own file list.
    """
    files = {
        "people.csv": _csv_bytes(people_rows(world, living_only=living_only)),
        "history.csv": _csv_bytes(history_rows(world)),
        "pedigree.csv": _csv_bytes(pedigree_rows(world)),
        # A reference table, so it belongs in every bundle -- including the
        # analysis-only one. people.csv names disorders by slug in either file
        # set, and a slug with nothing to resolve it against is a dead end.
        "diseases.csv": _csv_bytes(disease_rows(world), DISEASE_COLUMNS),
    }
    if include_frames:
        files["frames.csv"] = _csv_bytes(frame_rows(world), FRAME_COLUMNS)
        files["demes.csv"] = _csv_bytes(deme_frame_rows(world), DEME_COLUMNS)
        files["flows.csv"] = _csv_bytes(flow_rows(world), FLOW_COLUMNS)
        files["events.csv"] = _csv_bytes(event_rows(world), EVENT_COLUMNS)
    files["manifest.json"] = json.dumps(manifest(world, note), indent=2)
    files["README.txt"] = _readme(world)
    return files


def build_csv_bundle(world, note: str = "", living_only: bool = False,
                     include_frames: bool = True) -> bytes:
    """
    The whole run as a single .zip of CSVs plus a JSON manifest.

    Returned as bytes so the caller can hand it straight to `dcc.Download`,
    write it to disk, or ship it anywhere else.

    `include_frames=False` gives the pre-viewer file set (the three tables and
    the manifest). Frames are the longitudinal per-person tables and are much
    the largest part of a long run, so an analysis download that only wants
    the cross-section can say so.
    """
    files = _bundle_files(world, note, living_only, include_frames)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


def export_world_dir(world, path, note: str = "", living_only: bool = False,
                     include_frames: bool = True) -> "Path":
    """
    The same bundle, written as plain files into `path`.

    This is the world-viewer feed: Unity reads
    `StreamingAssets/extnpc/<world>/` and a zip would have to be unpacked at
    load time for no benefit. Identical in content to `build_csv_bundle` by
    construction -- both call `_bundle_files`.

    Files are written with `newline=""` so the `\\n` line terminator that
    `_csv_bytes` produced survives. Without it Python's text layer would
    translate to CRLF on Windows, and the same world exported on two machines
    would differ byte-for-byte for no reason anyone could see.
    """
    from pathlib import Path
    out = Path(path)
    out.mkdir(parents=True, exist_ok=True)
    for name, text in _bundle_files(world, note, living_only,
                                    include_frames).items():
        (out / name).write_text(text, encoding="utf-8", newline="")
    return out


def _readme(world) -> str:
    # local import, matching _deme_label's pattern in this module
    from .community import MAP_SIZE
    return f"""extNPC Health Engine — run export
=================================

Seed {world.seed} · year {world.tick} · {len(world.living)} living ·
{len(world.people)} ever lived.

people.csv     one row per individual who has ever lived.
               `alive` distinguishes the living from the dead; dead rows are
               included deliberately, because excluding them conditions any
               analysis on survival.
               `pedigree_f` is Malecot kinship over the full pedigree (#31);
               `realised_f` is what this individual's genome actually got.
               They differ because meiosis is a lottery -- the first is an
               expectation, the second a realisation.
               `relative_viability` and `stature_cost_cm` are the engine's TWO
               costs of inbreeding and are independent: recessive load decides
               survival (Morton 1956), directional dominance decides height
               (Joshi 2015). They are not two views of one number.
               `trait_*` are MATURE phenotypes. `height_at_age_cm` is the
               stature expressed at the current age (#13).
               `mendelian_diagnoses` / `mendelian_carrier_of` are the named
               recessive disorders expressed (homozygous) and carried
               (heterozygous, silent) at the labelled load loci. Read
               diseases.py first: the engine's carrier frequencies are its
               assigned loci's, and CF is a documented misfit.

history.csv    one row per simulated year; the series behind every chart in
               the dashboard. `lethal_equivalents` is Morton's B re-measured
               from the living each year -- it FALLS as a closed population
               purges recessive load, but its single-year noise in a village
               of ~70 is ~0.05, so read the trend and not the wiggle.

pedigree.csv   one row per parent-child edge (child, parent, role). Loads
               directly into kinship2 / pedigreemm / networkx.

frames.csv     one row per LIVING person per retained year -- the
               longitudinal per-person view, and the world viewer's feed.
               `x`/`y` are map coordinates on a {int(MAP_SIZE)}x{int(MAP_SIZE)}
               square; `height` is the stature EXPRESSED AT THAT AGE, not the
               mature value, so a child is not drawn adult-sized.
               THREE LIMITS, none of them fixable downstream:
                 * living only -- a death is a disappearance, not a row;
                 * capped at {SNAPSHOT_MAX_FRAMES} years, oldest dropped
                   first. manifest.json -> frames.truncated says whether this
                   run lost its early years; do not assume it starts at 0;
                 * ~18 scalars, NOT genomes. You can see who was alive, where
                   they stood and their headline stats. You cannot open a
                   dead person's genetic character sheet, by design.

diseases.csv   the Mendelian panel as a REFERENCE table -- one row per
               modelled disorder, not per person. This is what people.csv's
               `mendelian_diagnoses` / `mendelian_carrier_of` slugs point
               into: slug -> gene, display name, OMIM number, onset, citation.
               `q_lit` is the literature allele frequency and `q_engine` the
               one this run actually used; they are both here because they
               DISAGREE, and cystic fibrosis disagrees the most. See
               health_engine/diseases.py before using any of it
               epidemiologically.

demes.csv      one row per settlement per retained year: centre, radius,
               headcount, mean/max stress, dominant bloodline and its share,
               and `label`, the settlement's name.

flows.csv      one row per active migration route per retained year. EMPTY in
               a single-deme world, which is the default -- with one
               settlement there is nowhere to migrate.

events.csv     notable moments (tick, kind, label): shocks, plagues,
               bottlenecks. The timeline's markers.

manifest.json  seed, every parameter, git commit, library versions, summary
               statistics, `bundle_schema`, what frames.csv covers, and the
               caveats that apply to these tables.

Note on F_ST: with a single deme there is no partition to estimate over, so
it is reported as null rather than 0 -- those are different claims.
"""
