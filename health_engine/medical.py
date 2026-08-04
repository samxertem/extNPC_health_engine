"""
Medical Issues: acquired, non-heritable health events.
=====================================================

extNPC Health Engine sub-component 1 of 3. Deliberately decoupled from
reproduction: nothing here ever reaches a gamete. Predisposition genes
raise the *probability* of an event; the event itself dies with the
individual.

Per the framework text: "If there is an amputation or another health
problem, the NPC cannot perform some actions in its action set." Each
condition therefore names the actions it removes from the Action Engine.

STATUS: ported near-verbatim from v0.2, now reading the liability-
threshold phenotypes instead of Mendelian labels. This module is where
sessions 2 and 3 land:

  * #15-#20  lifetime epigenetic drift must be updated inside the yearly
             loop below (methylation responding to stress, illness, age),
             writing into `npc.expression`.
  * #17      the epigenetic clock advances here.
  * #21-#24  the PhysiologicalState vector ticks here, and allostatic
             load accumulates from sustained cortisol.
  * #13      DONE, but deliberately not here. The growth / puberty /
             senescence schedule lives in `development.py` and is applied
             to the OUTPUT of phenotype() rather than inside the ageing
             loop, because an age factor on the calibrated genotype ->
             phenotype path would silently move every target heritability.
             See that module's docstring.
  * #27      chronic conditions and inflammation must feed back into
             cognition/behaviour, not merely into the action set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List

import numpy as np

if TYPE_CHECKING:                      # avoid a circular import at runtime
    from .npc import NPC
    from .traits import Environment


ACTION_IMPACT_MAP: Dict[str, List[str]] = {
    "chronic_illness_flare": ["run", "carry_heavy_loads"],
    "vision_loss": ["read", "aim_ranged_weapon", "spot_distant_npc"],
    "hearing_loss": ["eavesdrop", "detect_approaching_threat_by_sound"],
    "limb_injury": ["run", "climb", "grab"],
    "metabolic_disorder": ["sprint", "fast_for_long_periods"],
    "cardiovascular_event": ["run", "climb", "carry_heavy_loads", "sprint"],
}


@dataclass
class MedicalCondition:
    name: str
    onset_age: int
    severity: float                       # 0-1
    restricted_actions: List[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"{self.name}(age={self.onset_age}, severity={self.severity:.2f})"


# Annual baseline hazards, conditioned on the liability-threshold
# phenotype. These are game-design numbers chosen for legibility over a
# 60-year life, NOT epidemiological incidence rates.
_ILLNESS_BASE_HAZARD = {"low": 0.050, "moderate": 0.025, "high": 0.010}

# Extra epigenetic aging booked when an illness is actually acquired in a
# year (on top of the clock's prospective illness term). Small, so a
# single flare nudges rather than jumps the clock.
CLOCK_ILLNESS_LATE = 0.30


def simulate_aging(npc: "NPC", years: int, rng: np.random.Generator,
                   environment: "Environment | None" = None) -> None:
    """
    Advance an NPC's life by `years`, accumulating acquired conditions.

    Genotype is never touched. What the genotype does is set the hazard:
    an NPC whose `immune_resilience` liability fell in the bottom quartile
    carries five times the annual flare risk of one in the top quartile,
    and a high-risk `chronic_illness_predisposition` triples it again.

    Two organ-function traits now gate real events that v0.2 had no way to
    express, because it had no organ-function layer:
      * low insulin sensitivity  -> metabolic disorder (roadmap #11)
      * high systolic set point  -> cardiovascular event
    Both are population-level statistical relationships, not diagnoses.

    NEW in v0.3: the epigenome ticks every year (roadmap #15-#18). The
    NPC's methylation drifts with age, and its exposures (smoking, chronic
    stress in `environment.exposures`) shift specific loci. This feeds
    back: chronic stress hypomethylates pro-inflammatory loci, raising the
    `inflammation_tone` liability, which both increases illness hazard and
    accelerates the epigenetic clock -- a compounding loop that is a first
    approximation of allostatic load (roadmap #24, fuller version later).
    Because the epigenome moves, phenotype and hazards are recomputed each
    year rather than once up front.
    """
    from .traits import NEUTRAL_ENVIRONMENT
    env = environment or NEUTRAL_ENVIRONMENT
    stress = env.stress

    predisposition = (3.0 if npc.phenotype()["chronic_illness_predisposition"]
                      == "high_risk" else 1.0)

    for _ in range(years):
        npc.age += 1
        age = npc.age
        conditions_before = len(npc.medical_conditions)

        # Epigenome advances first, then we read the resulting phenotype
        # and physiological state.
        npc.epigenome.tick(env)
        npc.refresh_expression()

        ph = npc.phenotype()
        base = _ILLNESS_BASE_HAZARD[ph["immune_resilience"]]
        insulin_z = npc.liability("insulin_sensitivity")
        systolic = ph["bp_set_point"]
        # Inflammation STATE = genetic predisposition + acquired load. The
        # acquired part is what chronic stress has built up (sickness
        # pathway, #27).
        inflammation_state = npc.inflammation_state
        inflam_mult = 1.0 + 0.3 * max(inflammation_state, 0.0)

        if rng.random() < base * predisposition * stress * inflam_mult:
            _add(npc, "chronic_illness_flare", age, rng.uniform(0.2, 0.8))

        if ph["vision_acuity"] == "myopic" and age > 40 and rng.random() < 0.02:
            _add(npc, "vision_loss", age, rng.uniform(0.1, 0.5))

        if ph["hearing_ability"] == "reduced" and age > 50 and rng.random() < 0.02:
            _add(npc, "hearing_loss", age, rng.uniform(0.1, 0.5))

        # Metabolic risk rises with age and falls with insulin sensitivity.
        # Epigenetic age acceleration adds to the effective biological age.
        bio_age = age + 0.5 * npc.epigenetic_age_acceleration
        if bio_age > 35:
            hazard = 0.004 * np.exp(-0.8 * insulin_z) * ((bio_age - 35) / 20.0) * stress
            if rng.random() < hazard:
                _add(npc, "metabolic_disorder", age, rng.uniform(0.3, 0.7))

        # Cardiovascular hazard rises steeply above ~140 mmHg.
        if bio_age > 45:
            excess = max(0.0, (systolic - 130.0) / 30.0)
            hazard = 0.003 * (1.0 + 2.0 * excess) * ((bio_age - 45) / 20.0) * stress
            if rng.random() < hazard:
                _add(npc, "cardiovascular_event", age, rng.uniform(0.4, 1.0))

        # Genotype-independent accidents.
        if rng.random() < 0.003 * stress:
            _add(npc, "limb_injury", age, rng.uniform(0.3, 1.0))

        # An illness acquired this year accelerates the clock retroactively.
        n_new = len(npc.medical_conditions) - conditions_before
        if n_new:
            npc.epigenome.epigenetic_age += CLOCK_ILLNESS_LATE * n_new


def _add(npc: "NPC", name: str, age: int, severity: float) -> None:
    npc.medical_conditions.append(MedicalCondition(
        name=name, onset_age=age, severity=round(float(severity), 2),
        restricted_actions=ACTION_IMPACT_MAP[name],
    ))
