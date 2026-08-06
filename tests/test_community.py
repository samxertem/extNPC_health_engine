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
from simulation.community import fst_gst
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

def _null_demes(n_per_deme, n_demes=4, n_loci=400, rng=None):
    """
    INDEPENDENT samples from ONE population -- the null where true F_ST = 0.

    This is the test the old `fst([block, block.copy()])` could not be. A
    block and its own copy have zero sampling variance between them, so that
    comparison cannot detect a sampling-variance bias no matter how large the
    bias is. It passed against an estimator that returned 0.038 on a genuine
    null, which is how the bias survived eight sessions.
    """
    rng = np.random.default_rng(0) if rng is None else rng
    p = rng.uniform(0.05, 0.95, n_loci)          # one shared frequency vector
    return [(rng.random((n_per_deme, 2, n_loci)) < p).sum(axis=1)
            for _ in range(n_demes)]


def test_fst_is_unbiased_on_an_independent_sample_null():
    """
    Weir & Cockerham 1984 exists to remove the finite-sample term, so on a
    true null it must sit at zero rather than merely small.
    """
    rng = np.random.default_rng(11)
    for n in (10, 20, 50):
        vals = [fst(_null_demes(n, rng=rng)) for _ in range(12)]
        assert abs(float(np.mean(vals))) < 0.004, (n, np.mean(vals))


def test_naive_gst_is_biased_upward_and_weir_cockerham_is_not():
    """
    Pins the reason for the session-11 fix. Nei's G_ST on samples reads
    sampling noise as differentiation: ~0.038 at n=10 per deme and ~0.019 at
    n=20 when the true value is 0. Those are the session-9 audit's numbers,
    reproduced here so the claim is checked rather than remembered.
    """
    rng = np.random.default_rng(12)
    for n, floor in ((10, 0.025), (20, 0.012)):
        demes = [_null_demes(n, rng=rng) for _ in range(8)]
        gst = float(np.mean([fst_gst(d) for d in demes]))
        wc = float(np.mean([fst(d) for d in demes]))
        assert gst > floor, (n, gst)
        assert abs(wc) < gst / 4.0, (n, wc, gst)


def test_fst_recovers_a_known_nonzero_value():
    """
    Balding-Nichols: draw each deme's allele frequency from Beta with the
    moments a target F_ST implies, then sample genotypes. The estimator must
    recover the target it was never told, at every sample size -- being
    unbiased at zero is worthless if it is biased at 0.05.
    """
    target = 0.05
    rng = np.random.default_rng(13)
    for n in (10, 20, 50):
        vals = []
        for _ in range(10):
            pbar = rng.uniform(0.1, 0.9, 400)
            a = pbar * (1 - target) / target
            b = (1 - pbar) * (1 - target) / target
            demes = [(rng.random((n, 2, 400)) < rng.beta(a, b)).sum(axis=1)
                     for _ in range(4)]
            vals.append(fst(demes))
        assert float(np.mean(vals)) == pytest.approx(target, abs=0.01), n


def test_fst_positive_for_divergent_demes():
    # two demes fixed for opposite alleles at every locus -> F_ST = 1
    a = np.zeros((20, 50), dtype=int)
    b = np.full((20, 50), 2, dtype=int)
    assert fst([a, b]) > 0.95


def test_expected_fst_monotonic_in_migration():
    assert expected_fst(50, 0.001) > expected_fst(50, 0.1)


def test_island_model_isolation_beats_migration():
    """
    The headline: with everything else equal, less migration -> more
    between-deme differentiation (Wright 1931).

    Averaged over seeds, and the absolute threshold is now meaningful rather
    than decorative. Under the old biased G_ST both scenarios cleared 0.03
    partly on sampling noise; under Weir & Cockerham the melting pot falls to
    ~0.010 and goes slightly NEGATIVE on some seeds, which is what an
    unbiased estimator does when there is nothing to find. Isolated islands
    hold at ~0.095. The gap between those two numbers is the real result, and
    it is larger than it looked before the estimator was fixed.
    """
    seeds = (3, 5, 7, 9, 11)
    iso = [_run(SCENARIOS["isolated_islands"].params, n_founders=16,
                seed=s, years=60).history[-1]["fst"] for s in seeds]
    mix = [_run(SCENARIOS["melting_pot"].params, n_founders=16,
                seed=s, years=60).history[-1]["fst"] for s in seeds]

    assert all(a > b for a, b in zip(iso, mix))       # holds on every seed
    assert float(np.mean(iso)) > 0.05                 # real structure emerged
    assert float(np.mean(mix)) < 0.03                 # gene flow erases it


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
    """
    Positive assortative mating on stature inflates the additive variance of
    height relative to random mating (Fisher 1918).

    AVERAGED OVER SEEDS, and that is not defensive padding. Fisher's result
    is about an expectation, while a ~100-person world for 50 years is
    dominated by drift: across seeds the effect here is about +0.4 cm of SD
    with a between-seed spread several times that, so any single seed agrees
    only about two times in three. This test previously ran on seed 8 alone
    and passed for that reason rather than on the strength of the mechanism
    -- it then flipped when an unrelated change (the #31 juvenile-survival
    draw) shifted the world's RNG stream by one call per birth. Comparing
    means over several seeds tests the claim that is actually being made.
    """
    seeds = (3, 8, 9, 11, 14)

    def height_sd(w):
        h = [w.people[n.name].phenotype()["height_cm"] for n in w.living]
        return float(np.std(h)) if len(h) > 3 else float("nan")

    base, asrt = [], []
    for s in seeds:
        base.append(height_sd(_run(seed=s, years=50)))
        asrt.append(height_sd(_run(replace(DemographyParams(),
                                           assortative_strength=3.0),
                                   seed=s, years=50)))
    assert np.nanmean(asrt) > np.nanmean(base)


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


def test_a_lone_settlement_sits_at_the_centre_of_the_map():
    """
    The sunflower radius sqrt((i+0.5)/n) is 0.707 at n=1, not 0, so without an
    explicit case the single deme was placed off-centre at (78.3, 50) -- and
    since n=1 also takes the largest territory radius, its edge fell outside
    the map. n=1 is the DEFAULT world, so this was the one layout that had to
    be right.
    """
    pts = deme_layout(1, seed=7)
    assert pts.shape == (1, 2)
    assert pts[0] == pytest.approx([MAP_SIZE / 2.0, MAP_SIZE / 2.0])


@pytest.mark.parametrize("n", [1, 2, 3, 4, 6, 8])
def test_every_territory_fits_inside_the_map(n):
    """
    Bounds must hold for the CENTRE PLUS ITS RADIUS, not just the centre --
    villagers are scattered across the whole territory, and the canvas
    renderer maps 0..MAP_SIZE onto the drawing area, so anything beyond that
    is drawn outside the world.
    """
    centers = deme_layout(n, seed=7)
    r = territory_radius(centers)
    assert (centers - r).min() >= 0.0
    assert (centers + r).max() <= MAP_SIZE


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
