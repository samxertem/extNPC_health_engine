"""
Population-simulation layer for the extNPC Health Engine.
=========================================================

A thin orchestration package that turns the single-individual health engine
into a living, multi-generational population with births, deaths, stable
pairing and founder-lineage tracking -- everything the Dash dashboard streams.

The tested `health_engine/` core is imported, never modified: all sim-only
state lives in `World` / `PersonMeta`.

    World         the population and its yearly step()
    Demography    Gale-Shapley pairing, Gompertz mortality, fertility (#30)
    Lineage       founder-ancestry -> "family" colour
    GenomePCA     stable 2-D genome embedding for the dot-cloud
    metrics       per-tick aggregates
    pedigree      family-tree graphs
"""

from .demography import DemographyParams
from .world import World, PersonMeta
from .events import Shock, Scenario, SCENARIOS, scenario_list, SHOCK_KINDS
from .community import fst, expected_fst, deme_label
from .chronicle import Chronicle, GLOSSARY

__all__ = [
    "World", "PersonMeta", "DemographyParams",
    "Shock", "Scenario", "SCENARIOS", "scenario_list", "SHOCK_KINDS",
    "fst", "expected_fst", "deme_label",
    "Chronicle", "GLOSSARY",
]
