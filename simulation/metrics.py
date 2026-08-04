"""
Per-tick population metrics for the live charts.
================================================

`snapshot()` reduces the living population to a row of scalars appended to the
World's history each year; the dashboard plots these as streaming time series.
Everything here reads state the engine already computes -- no new biology, just
aggregation -- so it stays cheap enough to run every tick on ~150 NPCs.

Distributions that only matter for the *current* frame (the age pyramid, trait
histograms) are computed on demand by the panel builders from the live list,
not stored, to keep the history compact.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from health_engine.npc import NPC

# Traits surfaced as live population means. Kept short so the chart is legible
# and the per-tick cost stays low.
TRACKED_TRAITS = [
    "height_cm", "bmi", "aerobic_capacity", "insulin_sensitivity",
    "immune_reactivity", "neuroticism",
]


def gini(values: List[float]) -> float:
    """Gini coefficient of a non-negative list (0 = perfect equality, 1 = one
    individual holds everything). Used for reproductive skew and can be reused
    for resource inequality. Returns 0 for empty / all-zero input."""
    x = np.sort(np.asarray(values, dtype=float))
    n = x.size
    if n == 0 or x.sum() == 0:
        return 0.0
    # relative mean absolute difference form
    cum = np.cumsum(x)
    return float((n + 1 - 2 * np.sum(cum) / cum[-1]) / n)


def snapshot(tick: int, living: List[NPC], n_births: int, n_deaths: int,
             n_couples: int, mean_relatedness: float,
             fst: float = 0.0, reproductive_skew: float = 0.0,
             n_migrations: int = 0,
             inbreeding: Optional[List[float]] = None,
             n_infant_deaths: int = 0) -> Dict[str, float]:
    """
    One row of scalar metrics for the history buffer.

    `inbreeding` is the list of pedigree F for the living (#31), passed in
    rather than computed here because it needs the World's cached `Pedigree`
    and this module deliberately knows nothing about the World.
    """
    n = len(living)
    if n == 0:
        row = {"tick": tick, "n_alive": 0, "n_births": n_births,
               "n_deaths": n_deaths, "n_couples": n_couples,
               "mean_age": 0.0, "max_generation": 0, "heterozygosity": 0.0,
               "epi_accel": 0.0, "inflammation": 0.0, "mean_relatedness": 0.0,
               "fst": float(fst), "reproductive_skew": float(reproductive_skew),
               "n_migrations": int(n_migrations),
               "mean_inbreeding": 0.0, "max_inbreeding": 0.0,
               "pct_inbred": 0.0, "mean_viability": 1.0, "load_carried": 0.0,
               "n_cnv_carriers": 0, "n_infant_deaths": int(n_infant_deaths)}
        for t in TRACKED_TRAITS:
            row[f"trait_{t}"] = 0.0
        return row

    ages = np.array([p.age for p in living], dtype=float)
    het = np.array([p.heterozygosity() for p in living])
    accel = np.array([p.epigenetic_age_acceleration for p in living])
    infl = np.array([p.inflammation_state for p in living])
    gens = [p.generation for p in living]

    row: Dict[str, float] = {
        "tick": tick,
        "n_alive": n,
        "n_births": n_births,
        "n_deaths": n_deaths,
        "n_couples": n_couples,
        "mean_age": float(ages.mean()),
        "max_generation": int(max(gens)),
        "heterozygosity": float(het.mean()),
        "epi_accel": float(accel.mean()),
        "inflammation": float(infl.mean()),
        "mean_relatedness": float(mean_relatedness),
        "fst": float(fst),
        "reproductive_skew": float(reproductive_skew),
        "n_migrations": int(n_migrations),
    }

    # ---- inbreeding and genetic load (#31, #12) -------------------------
    F = np.asarray(inbreeding if inbreeding else [0.0] * n, dtype=float)
    row["mean_inbreeding"] = float(F.mean())
    row["max_inbreeding"] = float(F.max())
    # Share of the living whose parents were second cousins or closer.
    # 1/64 is the pedigree F of a second-cousin mating and is the usual
    # threshold at which consanguinity studies start counting.
    row["pct_inbred"] = float(np.mean(F >= 1.0 / 64.0))

    viab = np.array([p.relative_viability() for p in living])
    row["mean_viability"] = float(viab.mean())
    # Deleterious alleles carried heterozygous -- invisible in the phenotype,
    # and the reservoir inbreeding draws on.
    carried = [p.load.n_carried for p in living if p.load is not None]
    row["load_carried"] = float(np.mean(carried)) if carried else 0.0
    row["n_cnv_carriers"] = int(sum(1 for p in living if p.cnv_variants()))
    row["n_infant_deaths"] = int(n_infant_deaths)

    for t in TRACKED_TRAITS:
        vals = np.array([p.phenotype()[t] for p in living])
        row[f"trait_{t}"] = float(vals.mean())
    return row


def age_pyramid(living: List[NPC], bin_width: int = 5, max_age: int = 100):
    """(bin_labels, female_counts, male_counts) for a population pyramid."""
    edges = np.arange(0, max_age + bin_width, bin_width)
    labels = [f"{e}-{e+bin_width-1}" for e in edges[:-1]]
    f = np.zeros(len(labels), dtype=int)
    m = np.zeros(len(labels), dtype=int)
    for p in living:
        idx = min(int(p.age // bin_width), len(labels) - 1)
        if p.sex == "female":
            f[idx] += 1
        else:
            m[idx] += 1
    return labels, f, m
