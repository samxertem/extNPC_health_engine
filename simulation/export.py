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
from .worldsave import (SAVE_FORMAT_VERSION, build_world_save,  # noqa: F401
                        load_world_save, world_state)

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
            "hidden_load_alleles": _load_carried(npc),
            "expressed_load_homozygotes": _load_expressed(npc),
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

    return {
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note,
        "git_commit": git_commit(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "libraries": versions,
        "seed": int(world.seed),
        "tick": int(world.tick),
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
        ],
    }


# ---------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------

def _csv_bytes(rows: Iterable[dict]) -> str:
    rows = list(rows)
    if not rows:
        return ""
    # union of keys, first-seen order preserved, so a row that gained a field
    # late does not silently truncate the header
    fields: List[str] = []
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


def build_csv_bundle(world, note: str = "",
                     living_only: bool = False) -> bytes:
    """
    The whole run as a single .zip of CSVs plus a JSON manifest.

    Returned as bytes so the caller can hand it straight to `dcc.Download`,
    write it to disk, or ship it anywhere else.
    """
    files = {
        "people.csv": _csv_bytes(people_rows(world, living_only=living_only)),
        "history.csv": _csv_bytes(history_rows(world)),
        "pedigree.csv": _csv_bytes(pedigree_rows(world)),
        "manifest.json": json.dumps(manifest(world, note), indent=2),
        "README.txt": _readme(world),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


def _readme(world) -> str:
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
               `trait_*` are MATURE phenotypes. `height_at_age_cm` is the
               stature expressed at the current age (#13).

history.csv    one row per simulated year; the series behind every chart in
               the dashboard.

pedigree.csv   one row per parent-child edge (child, parent, role). Loads
               directly into kinship2 / pedigreemm / networkx.

manifest.json  seed, every parameter, git commit, library versions, summary
               statistics and the caveats that apply to these tables.

Note on F_ST: with a single deme there is no partition to estimate over, so
it is reported as null rather than 0 -- those are different claims.
"""
