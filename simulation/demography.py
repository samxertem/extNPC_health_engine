"""
Population demography: pairing, fertility, mortality, selection.
================================================================

The health engine models an *individual's* life (ageing, epigenetics,
physiology). It has no notion of a population turning over. This module adds
that missing scheduler, and it is where the honest modelling choices live --
so every knob here is exposed to the dashboard as a slider.

Pieces
------
* **Stable pairing (Gale-Shapley, roadmap #30).** Fertile singles are matched
  by deferred acceptance using the engine's own `mate_compatibility` as the
  preference relation. The result has zero blocking pairs, unlike the greedy
  `best_mate` the engine shipped with -- see `mating.count_blocking_pairs`.
  Couples are life-partners: once matched they stay paired.

* **Fertility.** A couple with both partners in their fertility window bears a
  child each year with probability `birth_rate`, damped by a logistic
  carrying-capacity term so the population self-limits instead of exploding.

* **Mortality.** A Gompertz-Makeham annual hazard (a constant background risk
  plus a term rising exponentially with age), multiplied up by acquired medical
  load, epigenetic age acceleration and inflammation -- the state the engine
  already computes -- and by a logistic overcrowding term.

* **Selection pressure.** A single knob that couples mortality to a frailty
  proxy (inflammation, biological-age acceleration, low aerobic capacity). At 0
  it is neutral drift; turned up, the less-fit die younger and you can watch
  the trait means move -- the breeder's equation playing out live.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from health_engine.mating import mate_compatibility
from health_engine.npc import NPC


# ----------------------------------------------------------------------
# Tunable parameters (each maps to a dashboard control)
# ----------------------------------------------------------------------

@dataclass
class DemographyParams:
    carrying_capacity: int = 150
    # fertility
    birth_rate: float = 0.42          # annual P(child) per eligible couple
    female_fertility: Tuple[int, int] = (18, 45)
    male_fertility: Tuple[int, int] = (18, 60)
    min_birth_spacing: int = 2        # years between a couple's children
    max_children: int = 6
    pairing_age: int = 18             # minimum age to enter the mating pool
    # mortality (Gompertz-Makeham annual hazard: A + B*exp(G*age))
    makeham_A: float = 0.002
    gompertz_B: float = 2.5e-5
    gompertz_G: float = 0.095
    mortality_scale: float = 1.0      # global multiplier on hazard
    max_age: int = 100
    # selection
    selection_pressure: float = 0.0   # 0 = neutral; >0 = frailer die younger

    # ---- session-8 additions (all default to the pre-existing behaviour) --

    # Social structure -----------------------------------------------------
    # Positive assortative mating: how strongly like pairs with like on a
    # heritable phenotype (standardized height as the visible proxy). 0 = the
    # engine's own mate_compatibility unchanged; >0 inflates additive variance
    # and builds cross-trait LD (Fisher 1918; Crow & Felsenstein 1968).
    assortative_strength: float = 0.0
    # Inbreeding avoidance: reject a pairing whose genomic relatedness exceeds
    # this. 0.5 = the engine default (only sibs/parents blocked by the kin
    # guard inside mate_compatibility). Lower it toward 0.0625 to forbid first
    # cousins as well (Wright's coefficient of relationship).
    inbreeding_threshold: float = 0.5

    # Genetic-process modulators (EXPERIMENTAL multipliers, 1.0 = calibrated) -
    mutation_rate_scale: float = 1.0      # x Kong 2012 de novo rate
    recombination_scale: float = 1.0      # x deCODE map length (crossover freq)

    # Inbreeding depression (roadmap #31) ----------------------------------
    # Strength of the juvenile-survival cost applied to a newborn's realised
    # recessive load, as an exponent on relative viability: 1.0 = the
    # calibrated 1.4 lethal equivalents per gamete, 0.0 = off entirely (the
    # pre-#31 world, for comparison runs). Values above 1 exaggerate the
    # cost; they are an experimental knob, not a claim about any population.
    inbreeding_depression: float = 1.0

    # Community / island model (Wright 1931) -------------------------------
    n_demes: int = 1                      # sub-populations; 1 = panmictic
    migration_rate: float = 0.0           # annual P(an individual changes deme)

    # Resource distribution -----------------------------------------------
    # 1.0 = every individual has equal resource access (neutral). Below 1.0,
    # access is concentrated in the currently-dominant lineages of each deme,
    # so poorer strata suffer higher mortality and lower fertility -- stylized
    # environmental fitness variance / gene-environment correlation (roadmap
    # #28), NOT a claim that any specific gene sets social status.
    resource_equity: float = 1.0

    # Population-wide lifetime exposures fed to the epigenome layer (#18/#19).
    # All in [0, 1]. These drive real loci: smoking -> AHRR hypomethylation,
    # stress -> pro-inflammatory hypomethylation + epigenetic-age accel.
    exposure_smoking: float = 0.0
    exposure_stress: float = 0.0
    exposure_prenatal_nutrition: float = 1.0   # 1 = plentiful, 0 = famine


# ----------------------------------------------------------------------
# Gale-Shapley stable matching  (roadmap #30)
# ----------------------------------------------------------------------

def stable_matching(proposers: List[NPC],
                    reviewers: List[NPC],
                    adjust: Optional[Callable[[NPC, NPC], float]] = None,
                    ) -> List[Tuple[NPC, NPC]]:
    """
    Deferred-acceptance stable matching (Gale & Shapley 1962).

    Preferences come from `mate_compatibility`; pairs it rates -inf (same sex
    or close kin) are simply absent from each side's preference list, so they
    can never match. Proposers propose in descending preference; a reviewer
    holds their best offer so far and rejects the rest. Terminates with a
    matching that has no blocking pair.

    `adjust(a, b)` is an optional symmetric preference modifier added to the
    base compatibility (returns a float, or -inf to forbid the pair). It is how
    the dashboard's assortative-mating strength and inbreeding-avoidance
    threshold reach the matcher without touching the tested engine. When None
    (the default) the behaviour is exactly the engine's -- bit-for-bit.
    """
    if not proposers or not reviewers:
        return []

    def score(a: NPC, b: NPC) -> float:
        s = mate_compatibility(a, b)
        if adjust is not None and np.isfinite(s):
            s += adjust(a, b)
        return s

    # Precompute preference orderings, dropping incompatible partners.
    prefs: Dict[str, List[NPC]] = {}
    for p in proposers:
        scored = [(score(p, r), r) for r in reviewers]
        scored = [(s, r) for s, r in scored if np.isfinite(s)]
        scored.sort(key=lambda sr: -sr[0])
        prefs[p.name] = [r for _, r in scored]

    rev_score: Dict[str, Dict[str, float]] = {}
    for r in reviewers:
        rev_score[r.name] = {
            p.name: score(r, p) for p in proposers
        }

    next_choice: Dict[str, int] = {p.name: 0 for p in proposers}
    held: Dict[str, NPC] = {}                 # reviewer.name -> current proposer
    free = [p for p in proposers if prefs[p.name]]

    while free:
        p = free.pop()
        plist = prefs[p.name]
        if next_choice[p.name] >= len(plist):
            continue                          # exhausted, stays single
        r = plist[next_choice[p.name]]
        next_choice[p.name] += 1

        s_new = rev_score[r.name].get(p.name, float("-inf"))
        if not np.isfinite(s_new):
            free.append(p)                    # reviewer won't accept; try next
            continue

        cur = held.get(r.name)
        if cur is None:
            held[r.name] = p
        else:
            s_cur = rev_score[r.name].get(cur.name, float("-inf"))
            if s_new > s_cur:
                held[r.name] = p
                free.append(cur)              # jilted proposer re-enters pool
            else:
                free.append(p)                # rejected, try next choice

    by_name = {r.name: r for r in reviewers}
    return [(p, by_name[r_name]) for r_name, p in held.items()]


# Reference moments used to standardize height for the assortative bonus.
_HEIGHT_MEAN, _HEIGHT_SD = 171.0, 9.0


def preference_adjuster(params: DemographyParams):
    """
    Build the `adjust(a, b)` callback for `stable_matching` from the tunable
    social-structure knobs. Returns None when both knobs sit at their neutral
    defaults, so the matcher stays bit-for-bit identical to the engine.

    * assortative_strength > 0  -> a bonus for phenotypic similarity on
      standardized height (positive assortative mating; Fisher 1918).
    * inbreeding_threshold < 0.5 -> forbid (score -inf) any pair whose realized
      genomic relatedness exceeds the threshold (Wright 1922).
    """
    from health_engine.npc import genomic_relatedness

    a_str = params.assortative_strength
    thr = params.inbreeding_threshold
    if a_str <= 0.0 and thr >= 0.5:
        return None

    def adjust(a: NPC, b: NPC) -> float:
        if thr < 0.5 and genomic_relatedness(a, b) > thr:
            return float("-inf")
        if a_str > 0.0:
            za = (a.phenotype()["height_cm"] - _HEIGHT_MEAN) / _HEIGHT_SD
            zb = (b.phenotype()["height_cm"] - _HEIGHT_MEAN) / _HEIGHT_SD
            return -a_str * abs(za - zb)
        return 0.0

    return adjust


# ----------------------------------------------------------------------
# Fertility
# ----------------------------------------------------------------------

def in_fertility_window(npc: NPC, params: DemographyParams) -> bool:
    lo, hi = (params.female_fertility if npc.sex == "female"
              else params.male_fertility)
    return lo <= npc.age <= hi


def carrying_factor(n_alive: int, params: DemographyParams) -> float:
    """Logistic damping in [0,1]: 1 when empty, 0 at/above capacity."""
    k = max(1, params.carrying_capacity)
    return float(np.clip(1.0 - n_alive / k, 0.0, 1.0))


def wants_child(mother: NPC, father: NPC, n_children: int, years_since_last: int,
                n_alive: int, params: DemographyParams,
                rng: np.random.Generator,
                resource_access: float = 1.0) -> bool:
    if n_children >= params.max_children:
        return False
    if years_since_last < params.min_birth_spacing:
        return False
    if not (in_fertility_window(mother, params) and in_fertility_window(father, params)):
        return False
    # female fecundity tapers toward the end of the window
    lo, hi = params.female_fertility
    frac = (mother.age - lo) / max(1, hi - lo)
    age_taper = float(np.clip(1.0 - 0.6 * frac, 0.25, 1.0))
    # resource access (in [0,1]) gates fertility: the resource-poor breed less.
    # 1.0 is neutral, so the default call is unchanged.
    p = params.birth_rate * age_taper * carrying_factor(n_alive, params)
    p *= float(np.clip(resource_access, 0.0, 1.0))
    return rng.random() < p


# ----------------------------------------------------------------------
# Mortality
# ----------------------------------------------------------------------

def frailty(npc: NPC) -> float:
    """
    A rough standardized frailty score (~0 mean, ~1 scale) built from state
    the engine already tracks. Higher = worse. Used by selection pressure.
    """
    infl = npc.inflammation_state                       # liability units, ~N(0,1)+load
    accel = npc.epigenetic_age_acceleration / 8.0       # ~ years / 8
    aerobic = -npc.liability("aerobic_capacity")        # low aerobic = frail
    conditions = 0.5 * len(npc.medical_conditions)
    return float(0.4 * infl + 0.4 * accel + 0.3 * aerobic + conditions)


def death_probability(npc: NPC, n_alive: int, params: DemographyParams,
                      resource_access: float = 1.0) -> float:
    if npc.age >= params.max_age:
        return 1.0
    hazard = params.makeham_A + params.gompertz_B * np.exp(params.gompertz_G * npc.age)
    hazard *= params.mortality_scale
    # acquired burden the engine tracks
    hazard *= 1.0 + 0.25 * len(npc.medical_conditions)
    hazard *= np.exp(0.03 * max(0.0, npc.epigenetic_age_acceleration))
    # selection: couple hazard to frailty
    if params.selection_pressure > 0:
        hazard *= np.exp(params.selection_pressure * frailty(npc))
    # resource scarcity: access in [0,1]; below 1 raises hazard for the poor.
    # deficit 0 (full access) leaves hazard untouched, so the default is neutral.
    deficit = 1.0 - float(np.clip(resource_access, 0.0, 1.0))
    if deficit > 0:
        hazard *= np.exp(1.2 * deficit)
    # overcrowding: extra deaths past carrying capacity
    if n_alive > params.carrying_capacity:
        hazard *= 1.0 + 1.5 * (n_alive - params.carrying_capacity) / params.carrying_capacity
    hazard = float(np.clip(hazard, 0.0, 5.0))
    return 1.0 - float(np.exp(-hazard))
