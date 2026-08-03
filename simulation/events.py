"""
Shocks and scenario presets: one-off history and named starting worlds.
=======================================================================

Two things live here, both purely at the simulation layer (the tested engine
is never touched):

1. **Shocks** -- discrete historical events the operator fires on the next
   tick. Each is a small, biologically-motivated perturbation of state the
   engine already models, so the *consequences* are emergent, not scripted:

     * ``plague``     -- a one-year mortality multiplier spike (an epidemic).
     * ``famine``     -- one lean year: fertility collapses AND that year's
                         conceptions are marked by low prenatal nutrition, which
                         the epigenome layer turns into lasting IGF2
                         hypomethylation (DOHaD / Barker; Heijmans 2008). A
                         famine's fingerprint therefore outlives the famine.
     * ``bottleneck`` -- a random cull to a small survivor set (a founder
                         crash): heterozygosity drops and drift accelerates.

2. **Scenario presets** -- named `DemographyParams` (+ deme count + exposures)
   that set every knob to a documented, reproducible starting condition, so an
   examiner can load "Isolated islands" or "Assortative society" and see the
   predicted signature without hunting sliders.

None of these assert an outcome. A plague *should* dent the population and a
bottleneck *should* cut diversity, but by how much is left to the model.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Callable, Dict, List, Optional

import numpy as np

from .demography import DemographyParams


# ----------------------------------------------------------------------
# Shocks -- queued by the dashboard, drained by World.step()
# ----------------------------------------------------------------------

class Shock:
    """A one-tick perturbation. `kind` selects the mechanism; `magnitude` in
    [0,1] scales its severity. `apply` is called by the World at the right
    point in the step and returns a short human-readable chronicle line."""

    def __init__(self, kind: str, magnitude: float = 0.6):
        self.kind = kind
        self.magnitude = float(np.clip(magnitude, 0.0, 1.0))

    def __repr__(self) -> str:
        return f"Shock({self.kind!r}, {self.magnitude:.2f})"


SHOCK_KINDS = {
    "plague":     "Epidemic — a one-year surge in mortality.",
    "famine":     "Lean year — fertility collapses; this year's babies carry a "
                  "DOHaD prenatal-nutrition imprint for life.",
    "bottleneck": "Founder crash — the population is culled to a small remnant; "
                  "heterozygosity drops and drift speeds up.",
}


def plague_mortality_multiplier(magnitude: float) -> float:
    """Extra hazard multiplier applied to everyone for one tick."""
    return 1.0 + 8.0 * magnitude          # up to ~9x baseline hazard


def famine_fertility_multiplier(magnitude: float) -> float:
    """Fertility multiplier for the famine tick (approaches 0 at full force)."""
    return float(np.clip(1.0 - magnitude, 0.0, 1.0))


def famine_prenatal_nutrition(magnitude: float) -> float:
    """Prenatal-nutrition exposure in [0,1] for babies conceived this tick.
    Full-force famine -> 0 (severe) which the epigenome maps to IGF2
    hypomethylation."""
    return float(np.clip(1.0 - magnitude, 0.0, 1.0))


def bottleneck_survivor_fraction(magnitude: float) -> float:
    """Fraction of the population that survives a bottleneck cull."""
    return float(np.clip(1.0 - 0.85 * magnitude, 0.1, 1.0))


# ----------------------------------------------------------------------
# Scenario presets
# ----------------------------------------------------------------------

class Scenario:
    """A named starting world: demography params + community + exposures."""

    def __init__(self, key: str, title: str, blurb: str,
                 params: DemographyParams, n_founders: int = 12):
        self.key = key
        self.title = title
        self.blurb = blurb
        self.params = params
        self.n_founders = n_founders


def _base(**over) -> DemographyParams:
    return replace(DemographyParams(), **over)


SCENARIOS: Dict[str, Scenario] = {
    "baseline": Scenario(
        "baseline", "Baseline village",
        "One panmictic community at neutral settings — the reference world.",
        _base(carrying_capacity=150, n_demes=1, selection_pressure=0.4),
        n_founders=10),

    "isolated_islands": Scenario(
        "isolated_islands", "Isolated islands",
        "Four demes with almost no migration. Watch F_ST climb toward "
        "1/(4N_e m+1) as each island drifts to its own allele frequencies.",
        _base(carrying_capacity=200, n_demes=4, migration_rate=0.005,
              selection_pressure=0.2),
        n_founders=16),

    "melting_pot": Scenario(
        "melting_pot", "Melting pot",
        "Four demes with heavy migration — gene flow keeps F_ST near zero; the "
        "islands behave as one homogeneous population.",
        _base(carrying_capacity=200, n_demes=4, migration_rate=0.15,
              selection_pressure=0.2),
        n_founders=16),

    "assortative_society": Scenario(
        "assortative_society", "Assortative society",
        "Strong positive assortative mating on stature — inflates additive "
        "variance and builds cross-trait correlations (Fisher 1918).",
        _base(carrying_capacity=150, assortative_strength=2.5,
              selection_pressure=0.3),
        n_founders=12),

    "founder_crash": Scenario(
        "founder_crash", "Founder crash",
        "A small, closed population with strong selection — rapid drift, "
        "lineage extinction and diversity loss.",
        _base(carrying_capacity=60, birth_rate=0.5, selection_pressure=0.9,
              inbreeding_threshold=0.5),
        n_founders=8),

    "malthusian": Scenario(
        "malthusian", "Malthusian squeeze",
        "High fertility against a hard carrying capacity — births and deaths "
        "lock into a crowded, high-turnover equilibrium.",
        _base(carrying_capacity=120, birth_rate=0.85, mortality_scale=1.2,
              selection_pressure=0.5),
        n_founders=12),

    "harsh_world": Scenario(
        "harsh_world", "Harsh & unequal",
        "Heavy smoking/stress exposure and concentrated resources — differential "
        "survival by strata, fast epigenetic ageing, strong selection.",
        _base(carrying_capacity=150, selection_pressure=0.8,
              resource_equity=0.25, exposure_smoking=0.6, exposure_stress=0.6),
        n_founders=12),

    "hypermutant": Scenario(
        "hypermutant", "Accelerated evolution",
        "Experimental: mutation and recombination cranked up to watch novelty "
        "and LD-breakdown outrun drift (a knob, not a real rate).",
        _base(carrying_capacity=150, mutation_rate_scale=25.0,
              recombination_scale=2.0, selection_pressure=0.6),
        n_founders=12),
}


def scenario_list() -> List[Scenario]:
    return list(SCENARIOS.values())
