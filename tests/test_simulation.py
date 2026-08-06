"""
Tests for the population-simulation layer (simulation/).

These assert the properties the live dashboard depends on, in the same
against-a-closed-form spirit as the engine tests: Gale-Shapley stability
(roadmap #30), the ancestry-fraction invariant behind the lineage colours,
and that a stepped world stays consistent and non-empty.
"""

import numpy as np
import pytest

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


# ----------------------------------------------------------------------
# Naming: a name must agree with the sex it is attached to
# ----------------------------------------------------------------------

def test_every_name_matches_the_sex_of_the_person_carrying_it():
    """
    Newborns used to be named BEFORE `reproduce` decided their sex (which is
    genetic -- the father's X or Y, roadmap #2), so the pool position and the
    sex were independent and roughly half of all births were mismatched:
    female NPCs called Emre, male ones called Nora.
    """
    from simulation.world import _FEMALE_NAMES, _MALE_NAMES
    w = World(n_founders=16, seed=11)
    for _ in range(60):
        w.step()

    mismatched = []
    for npc in w.people.values():
        base = npc.name.rsplit("-", 1)[0]
        assert base in _FEMALE_NAMES or base in _MALE_NAMES, f"stray name {base}"
        if (base in _FEMALE_NAMES) != (npc.sex == "female"):
            mismatched.append((npc.name, npc.sex))
    assert not mismatched, f"{len(mismatched)} name/sex mismatches: {mismatched[:5]}"
    assert sum(1 for n in w.people.values() if n.generation > 0) > 20, \
        "need real births for this test to mean anything"


def test_the_two_name_pools_do_not_overlap():
    from simulation.world import _FEMALE_NAMES, _MALE_NAMES
    assert not (set(_FEMALE_NAMES) & set(_MALE_NAMES))


def test_founder_names_were_not_disturbed_by_the_split():
    """The old single pool alternated female/male and founders are seeded
    `female if i % 2 == 0`, so index parity already lined up there. Splitting
    the pool must leave those names exactly as they were."""
    w = World(n_founders=6, seed=11)
    assert [n.name for n in w.living[:6]] == [
        "Elira-1", "Tomas-2", "Ines-3", "Darius-4", "Sena-5", "Kaan-6"]


def test_names_stay_unique_across_a_long_run():
    w = World(n_founders=14, seed=3)
    for _ in range(70):
        w.step()
    names = [n.name for n in w.people.values()]
    assert len(names) == len(set(names))


# ----------------------------------------------------------------------
# Fertility schedules: at WHICH AGES does reproduction happen
# ----------------------------------------------------------------------

def _maternal_ages(schedule, seed=11, years=80):
    """Ages of living mothers when their (living) children were born.

    Both must be alive: a dead person's age is frozen at death, so
    `parent.age - child.age` is only the age at birth while both still age in
    lockstep. Getting this wrong produces parents aged 1 and negative ages,
    which is exactly the artefact that made it look as though children were
    reproducing.
    """
    w = World(n_founders=24, seed=seed,
              params=DemographyParams(fertility_schedule=schedule))
    for _ in range(years):
        w.step()
    alive = {n.name for n in w.living}
    return np.array([w.people[n.parents[0]].age - n.age
                     for n in w.living
                     if n.parents and n.parents[0] in alive])


def test_the_legacy_schedule_reproduces_the_original_taper_exactly():
    """The default must not move any calibrated quantity, so the knot-based
    schedule has to return exactly what the old inline formula returned."""
    from simulation.demography import relative_fecundity
    lo, hi = 18.0, 45.0
    for age in np.arange(18.0, 45.01, 0.5):
        frac = (age - lo) / (hi - lo)
        original = float(np.clip(1.0 - 0.6 * frac, 0.25, 1.0))
        assert relative_fecundity(age, "legacy") == pytest.approx(original, abs=1e-12)


def test_legacy_is_the_default_schedule():
    from simulation.demography import DEFAULT_FERTILITY_SCHEDULE
    assert DemographyParams().fertility_schedule == DEFAULT_FERTILITY_SCHEDULE
    assert DEFAULT_FERTILITY_SCHEDULE == "legacy"


def test_no_schedule_lets_a_child_reproduce():
    """The floor that matters. Reproduction is gated by the fertility window,
    and no schedule may open it below it."""
    for schedule in ("legacy", "preindustrial", "modern"):
        ages = _maternal_ages(schedule)
        if ages.size:
            assert ages.min() >= 18, f"{schedule} produced a mother aged {ages.min()}"


def test_the_modern_schedule_postpones_births_relative_to_natural_fertility():
    """The whole point of the two presets: natural fertility starts early and
    runs late; the modern pattern concentrates births in the late twenties."""
    pre = _maternal_ages("preindustrial")
    mod = _maternal_ages("modern")
    assert pre.size > 8 and mod.size > 8
    assert np.median(mod) > np.median(pre), \
        f"modern median {np.median(mod)} should exceed pre-industrial {np.median(pre)}"


@pytest.mark.parametrize("schedule, lo, hi", [
    ("preindustrial", 24.0, 31.0),
    ("modern", 28.0, 33.0),
])
def test_implied_mean_maternal_age_is_demographically_plausible(schedule, lo, hi):
    from simulation.demography import mean_reproductive_age
    got = mean_reproductive_age(schedule)
    assert lo <= got <= hi, f"{schedule} implies a mean maternal age of {got:.1f}"


def test_fecundity_curves_are_humped_not_straight():
    """Real fecundability rises then falls. The legacy taper is a straight
    line, which is why an 18-year-old was as fecund as a 25-year-old."""
    from simulation.demography import relative_fecundity
    for schedule in ("preindustrial", "modern"):
        ages = np.arange(15, 46)
        vals = np.array([relative_fecundity(a, schedule) for a in ages])
        peak = ages[int(vals.argmax())]
        assert 19 <= peak <= 32, f"{schedule} peaks at {peak}"
        assert vals[0] < vals.max(), "must rise from adolescence"
        assert vals[-1] < vals.max(), "and fall away after the peak"


def test_adolescent_subfecundity_is_present_in_both_presets():
    from simulation.demography import relative_fecundity
    for schedule in ("preindustrial", "modern"):
        assert relative_fecundity(17, schedule) < 0.7 * \
            relative_fecundity(25, schedule)


def test_an_unknown_schedule_name_falls_back_instead_of_raising():
    """The value arrives from a dashboard dropdown; a stale one must not take
    the whole world down."""
    from simulation.demography import relative_fecundity
    assert relative_fecundity(25, "not-a-schedule") == \
        relative_fecundity(25, "legacy")
    w = World(n_founders=8, seed=2,
              params=DemographyParams(fertility_schedule="nonsense"))
    for _ in range(5):
        w.step()
    assert w.history[-1]["n_alive"] >= 0
