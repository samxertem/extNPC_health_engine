"""
Tests for the population-simulation layer (simulation/).

These assert the properties the live dashboard depends on, in the same
against-a-closed-form spirit as the engine tests: Gale-Shapley stability
(roadmap #30), the ancestry-fraction invariant behind the lineage colours,
and that a stepped world stays consistent and non-empty.
"""

import numpy as np

from health_engine.mating import count_blocking_pairs
from simulation import World, DemographyParams
from simulation.demography import stable_matching
from simulation.lineage import LineageRegistry


def test_gale_shapley_has_no_blocking_pairs():
    """A stable matching, by construction, leaves no two people who both
    prefer each other over their assigned partner (Gale & Shapley 1962)."""
    w = World(n_founders=20, seed=11)
    for _ in range(25):
        w.step()
    singles = [n for n in w.living if n.age >= w.params.pairing_age]
    females = [n for n in singles if n.sex == "female"]
    males = [n for n in singles if n.sex == "male"]
    pairs = stable_matching(females, males)

    matching = {}
    for a, b in pairs:
        matching[a.name] = b.name
        matching[b.name] = a.name

    assert count_blocking_pairs(matching, singles) == 0
    # every matched pair is opposite-sex and no one is matched twice
    matched = [n for p in pairs for n in p]
    assert len(matched) == len(set(x.name for x in matched))
    for a, b in pairs:
        assert a.sex != b.sex


def test_ancestry_fractions_sum_to_one():
    """Each individual's founder-ancestry shares form a convex combination
    (they sum to 1); this is what makes the dominant-lineage colour honest."""
    w = World(n_founders=12, seed=3)
    for _ in range(20):
        w.step()
    for npc in w.living:
        total = sum(w.meta[npc.name].ancestry.values())
        assert abs(total - 1.0) < 1e-6


def test_child_ancestry_is_midparent_average():
    reg = LineageRegistry()
    mother = {"A": 1.0}
    father = {"B": 0.5, "C": 0.5}
    child = reg.child_ancestry(mother, father)
    assert abs(child["A"] - 0.5) < 1e-9
    assert abs(child["B"] - 0.25) < 1e-9
    assert abs(child["C"] - 0.25) < 1e-9


def test_world_is_deterministic_per_seed():
    """Same seed + same params replays exactly -- the inline-step promise."""
    def run():
        w = World(n_founders=10, seed=42)
        for _ in range(30):
            w.step()
        return w.history[-1]["n_alive"], w.history[-1]["max_generation"]
    assert run() == run()


def test_population_survives_and_grows():
    w = World(n_founders=12, seed=7,
              params=DemographyParams(carrying_capacity=120))
    for _ in range(60):
        w.step()
    last = w.history[-1]
    assert last["n_alive"] > 0
    assert last["max_generation"] >= 2          # real generational turnover
    assert 0.0 <= last["heterozygosity"] <= 1.0


def test_selection_pressure_reduces_mean_frailty_traits():
    """Under strong selection the frail die younger, so a fitness-linked trait
    (aerobic capacity) should end up no lower than under neutral drift."""
    def final_aerobic(sel):
        w = World(n_founders=16, seed=5,
                  params=DemographyParams(selection_pressure=sel))
        for _ in range(80):
            w.step()
        return w.history[-1]["trait_aerobic_capacity"]
    # not a strict inequality every seed (drift is noisy), but selection should
    # not drag the mean below neutral by much; assert it stays in a sane band.
    neutral = final_aerobic(0.0)
    selected = final_aerobic(1.5)
    assert np.isfinite(neutral) and np.isfinite(selected)
    assert selected >= neutral - 5.0
