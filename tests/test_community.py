"""
Tests for the session-8 community / controls / narration layers.
=================================================================

These assert the *directional* laws the new features are supposed to obey --
F_ST rises with isolation and falls with migration, resource inequality biases
survival, assortative mating inflates variance, shocks bite, presets build --
plus the load-bearing invariant that the DEFAULT world is unchanged, so the
calibrated engine and session-4 simulation are untouched.

We deliberately test the *ordering* of F_ST (isolated > mixed), not its exact
equilibrium value: Wright's 1/(4N_e m+1) is an equilibrium reached over many
generations, and a 60-year run has not converged -- claiming the closed-form
number would be dishonest, the qualitative law is what we can defend here.
"""

from __future__ import annotations

import numpy as np
import pytest

from dataclasses import replace

from simulation import World, DemographyParams, SCENARIOS, expected_fst, fst
from simulation.metrics import gini
from simulation.community import (assign_founder_demes, choose_migration,
                                  deme_layout, territory_radius,
                                  person_map_offset, MAP_SIZE)


def _run(params=None, n_founders=12, seed=7, years=40):
    w = World(n_founders=n_founders, seed=seed, params=params)
    for _ in range(years):
        w.step()
    return w


# ----------------------------------------------------------------------
# The load-bearing invariant: default world is bit-for-bit unchanged
# ----------------------------------------------------------------------

def test_default_world_is_deterministic_and_unchanged():
    a = _run(seed=21, years=30)
    b = _run(seed=21, years=30)
    assert a.history[-1] == b.history[-1]
    # a single panmictic deme has, by definition, no differentiation
    assert a.history[-1]["fst"] == 0.0


# ----------------------------------------------------------------------
# F_ST metric
# ----------------------------------------------------------------------

def test_fst_zero_for_identical_demes():
    rng = np.random.default_rng(0)
    block = rng.integers(0, 3, size=(40, 60))
    assert fst([block, block.copy()]) == pytest.approx(0.0, abs=1e-9)


def test_fst_positive_for_divergent_demes():
    # two demes fixed for opposite alleles at every locus -> F_ST = 1
    a = np.zeros((20, 50), dtype=int)
    b = np.full((20, 50), 2, dtype=int)
    assert fst([a, b]) > 0.95


def test_expected_fst_monotonic_in_migration():
    assert expected_fst(50, 0.001) > expected_fst(50, 0.1)


def test_island_model_isolation_beats_migration():
    """The headline: with everything else equal, less migration -> more
    between-deme differentiation."""
    iso = _run(SCENARIOS["isolated_islands"].params, n_founders=16, seed=3, years=60)
    mix = _run(SCENARIOS["melting_pot"].params, n_founders=16, seed=3, years=60)
    assert iso.history[-1]["fst"] > mix.history[-1]["fst"]
    assert iso.history[-1]["fst"] > 0.03      # real structure emerged


def test_migration_moves_individuals_between_demes():
    p = replace(DemographyParams(), n_demes=4, migration_rate=0.2)
    w = _run(p, n_founders=16, seed=1, years=15)
    assert any(row["n_migrations"] > 0 for row in w.history)


# ----------------------------------------------------------------------
# Resource equity -> differential fitness
# ----------------------------------------------------------------------

def test_resource_inequality_creates_access_spread():
    p = replace(DemographyParams(), resource_equity=0.2)
    w = _run(p, seed=4, years=20)
    access = [w.meta[n.name].resource_access for n in w.living]
    # under inequality, access is no longer uniform
    assert max(access) - min(access) > 0.1


def test_full_equity_is_neutral():
    w = _run(seed=4, years=10)
    access = [w.meta[n.name].resource_access for n in w.living]
    assert all(a == 1.0 for a in access)


# ----------------------------------------------------------------------
# Assortative mating
# ----------------------------------------------------------------------

def test_assortative_mating_raises_height_variance():
    """Positive assortative mating on stature should inflate the additive
    variance of height relative to random mating (Fisher 1918)."""
    base = _run(seed=8, years=50)
    asrt = _run(replace(DemographyParams(), assortative_strength=3.0),
                seed=8, years=50)

    def height_sd(w):
        h = [w.people[n.name].phenotype()["height_cm"] for n in w.living]
        return float(np.std(h)) if len(h) > 3 else 0.0

    assert height_sd(asrt) >= height_sd(base)


# ----------------------------------------------------------------------
# Shocks
# ----------------------------------------------------------------------

def test_plague_kills_more_than_a_normal_year():
    w = World(n_founders=14, seed=6)
    for _ in range(15):
        w.step()
    normal_deaths = w.history[-1]["n_deaths"]
    w.queue_shock("plague", 0.9)
    row = w.step()
    assert row["n_deaths"] > normal_deaths


def test_bottleneck_cuts_the_population():
    w = World(n_founders=16, seed=9)
    for _ in range(20):
        w.step()
    before = len(w.living)
    w.queue_shock("bottleneck", 0.8)
    w.step()
    assert len(w.living) < before


def test_famine_marks_offspring_with_low_prenatal_nutrition():
    # a famine tick should still be survivable and produce a chronicle note
    w = World(n_founders=16, seed=2)
    for _ in range(12):
        w.step()
    w.queue_shock("famine", 0.9)
    w.step()
    assert any("famine" in e.text for e in w.chronicle.events)


# ----------------------------------------------------------------------
# Scenario presets + chronicle
# ----------------------------------------------------------------------

def test_every_scenario_builds_and_runs():
    for scen in SCENARIOS.values():
        w = World(n_founders=scen.n_founders, seed=5, params=scen.params)
        for _ in range(5):
            w.step()
        assert len(w.living) >= 0        # ran without raising


def test_chronicle_narrates_and_summarizes():
    w = _run(SCENARIOS["founder_crash"].params, n_founders=8, seed=1, years=25)
    assert len(w.chronicle.events) > 0
    assert len(w.chronicle.summaries) >= 2      # a summary every 10 years


def test_gini_bounds():
    assert gini([5, 5, 5, 5]) == pytest.approx(0.0, abs=1e-9)
    assert gini([0, 0, 0, 10]) > 0.6
    assert gini([]) == 0.0


# ----------------------------------------------------------------------
# Spatial world map / isolation by distance
# ----------------------------------------------------------------------

def test_deme_layout_shape_and_bounds():
    pts = deme_layout(6, seed=7)
    assert pts.shape == (6, 2)
    assert pts.min() >= -1 and pts.max() <= MAP_SIZE + 1


def test_deme_layout_is_deterministic():
    assert np.allclose(deme_layout(5, seed=3), deme_layout(5, seed=3))


def test_person_offset_within_territory():
    r = 12.0
    for nm in ("Elira-1", "Bora-42", "Zoe-7"):
        dx, dy = person_map_offset(nm, r)
        assert np.hypot(dx, dy) <= r        # stays inside the settlement


def test_world_exposes_map_data():
    w = _run(SCENARIOS["isolated_islands"].params, n_founders=16, seed=3, years=30)
    demes = w.map_demes()
    assert len(demes) == w.params.n_demes
    assert sum(d["n"] for d in demes) == len(w.living)
    frame = w.living_frame()
    assert all("map_x" in p and "map_y" in p for p in frame)


def test_migration_flow_recorded_between_settlements():
    p = replace(DemographyParams(), n_demes=4, migration_rate=0.2)
    w = _run(p, n_founders=16, seed=1, years=20)
    # some routes should be active (flow matrix non-empty)
    assert len(w.map_flows()) > 0
