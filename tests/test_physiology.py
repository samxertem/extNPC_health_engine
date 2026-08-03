"""
Physiological state / hormones / interoception tests (roadmap #21-#27).

The headline is `test_state_biases_action_distribution` — the roadmap's
Stage-1 benchmark: identical prompts (here, identical action-selection
priors) come out measurably different under 'hungry/high-cortisol' vs
'sated/calm' states. No live LLM is needed because the distribution over
action classes IS the logit-bias output.
"""

import math

import numpy as np
import pytest

from health_engine import physiology as P
from health_engine.physiology import (ACTION_CLASSES, HormoneParams,
                                       PhysiologicalState, circadian_cortisol,
                                       kl_divergence)
from health_engine.medical import simulate_aging
from health_engine.npc import random_founder
from health_engine.traits import Environment


@pytest.fixture
def rng():
    return np.random.default_rng(20240612)


@pytest.fixture
def params(rng):
    return random_founder("subject", rng).hormone_params()


# ------------------------------------------------------- THE BENCHMARK

def test_state_biases_action_distribution(params):
    """
    Roadmap Stage-1 item-5 benchmark. Two internal states, one body, one
    (implicit) prompt -> measurably different action priors.
    """
    hungry = PhysiologicalState(glucose=0.12, hydration=0.45, cortisol=1.15,
                                adrenaline=0.25, circadian_phase=13.0)
    sated = PhysiologicalState(glucose=0.80, hydration=0.85, cortisol=0.35,
                               dopamine=0.68, oxytocin=0.66, serotonin=0.6,
                               circadian_phase=13.0)

    d_hungry = hungry.action_distribution(params)
    d_sated = sated.action_distribution(params)

    # The distributions are far apart.
    assert kl_divergence(d_hungry, d_sated) > 0.5

    # And they point at qualitatively different behaviour.
    assert hungry.dominant_action(params) in ("forage", "drink", "defend")
    assert sated.dominant_action(params) in ("explore", "socialize", "court")
    assert d_hungry["forage"] > 3 * d_sated["forage"]
    assert d_sated["explore"] > 3 * d_hungry["explore"]


def test_prompt_reflects_state(params):
    hungry = PhysiologicalState(glucose=0.10, cortisol=1.2, circadian_phase=9.0)
    text = hungry.to_prompt(params)
    assert "hungry" in text or "ravenous" in text
    assert "morning" in text
    assert text.startswith("[body]")


# ------------------------------------------------------- HPA axis (#23)

def test_acute_threat_spikes_cortisol_then_recovers(params):
    st = PhysiologicalState(circadian_phase=12.0, cortisol=0.35)
    baseline = st.cortisol
    # Adrenaline is the fast alarm; cortisol lags because it must climb the
    # CRH -> ACTH -> cortisol cascade, so its peak arrives an hour or two
    # after the stressor. Track the running max rather than the instant.
    # A sustained one-hour threatening encounter.
    st.step(0.5, params, threat=1.0)
    assert st.adrenaline > 0.3, "adrenaline should spike immediately"
    st.step(0.5, params, threat=1.0)
    peak = st.cortisol
    for _ in range(16):
        st.step(0.5, params)          # calm afterwards
        peak = max(peak, st.cortisol)
    recovered = st.cortisol

    assert peak > baseline + 0.2, "no acute cortisol response"
    assert st.adrenaline < 0.1, "adrenaline should have decayed"
    assert recovered < peak - 0.15, "negative feedback did not bring cortisol down"


def test_chronic_stress_sustains_cortisol_and_builds_allostatic_load(params):
    st = PhysiologicalState(circadian_phase=12.0)
    for _ in range(48):
        st.step(1.0, params, stressor=1.5)
    assert st.cortisol > 1.0, "chronic stressor should sustain high cortisol"
    assert st.allostatic_load > 1.0, "allostatic load should accumulate"


def test_hpa_integration_is_timestep_independent(params):
    """The stiff HPA ODEs must give the same answer at 1 h and 0.25 h steps
    (internal sub-stepping), not oscillate to zero at coarse resolution."""
    coarse = PhysiologicalState(circadian_phase=12.0)
    fine = PhysiologicalState(circadian_phase=12.0)
    for _ in range(48):
        coarse.step(1.0, params, stressor=1.5)
    for _ in range(192):
        fine.step(0.25, params, stressor=1.5)
    assert abs(coarse.cortisol - fine.cortisol) < 0.05


# ------------------------------------------------------- allostasis (#24)

def test_allostatic_load_accelerates_the_epigenetic_clock(rng):
    """High allostatic load books epigenetic years (#24 -> session 2 clock)."""
    npc = random_founder("worn", rng)
    st = npc.physiological_state(phase_h=12.0)
    hp = npc.hormone_params()
    for _ in range(60):
        st.step(1.0, hp, stressor=1.6)
    age_before = npc.epigenetic_age
    added = P.book_allostatic_load_to_clock(npc, st)
    assert st.allostatic_load > 2.0
    assert added > 0.0
    assert npc.epigenetic_age == pytest.approx(age_before + added)


# ------------------------------------------------------- circadian (#26)

def test_cortisol_rhythm_peaks_in_the_morning():
    """Diurnal cortisol: morning peak, small-hours trough (no chronotype shift)."""
    vals = {h: circadian_cortisol(h, 0.0) for h in range(0, 24, 3)}
    assert max(vals, key=vals.get) in (6, 9)
    assert min(vals, key=vals.get) in (21, 0)


def test_chronotype_shifts_the_cortisol_peak():
    """A lark (negative chronotype shift) peaks earlier than an owl."""
    lark_peak = max(range(24), key=lambda h: circadian_cortisol(h, -3.0))
    owl_peak = max(range(24), key=lambda h: circadian_cortisol(h, +3.0))
    assert lark_peak < owl_peak


# ------------------------------------------------------- interoception (#22)

def test_interoception_gain_sharpens_salience():
    """A heritable high interoceptive-accuracy makes the same body state
    feel louder — the gain on the body->mind channel."""
    st = PhysiologicalState(glucose=0.4)          # moderately hungry
    dull = HormoneParams(interoception_gain=0.5)
    sharp = HormoneParams(interoception_gain=1.7)
    assert (st.interoceptive_signals(sharp)["hunger"]
            > st.interoceptive_signals(dull)["hunger"])


def test_salience_has_a_threshold_nonlinearity():
    """Signals past threshold become disproportionately salient (Craig 2002)."""
    p = HormoneParams(interoception_gain=1.0)
    mild = PhysiologicalState(glucose=P.GLUCOSE_SETPOINT - 0.15)
    severe = PhysiologicalState(glucose=0.0)
    mild_h = mild.interoceptive_signals(p)["hunger"]
    severe_h = severe.interoceptive_signals(p)["hunger"]
    # severe hunger is far more than proportionally salient
    assert severe_h > 3 * mild_h


# ------------------------------------------------------- sickness behaviour (#27)

def test_inflammation_drives_withdrawal(params):
    """Sickness behaviour: high inflammation withdraws from outward action
    (Dantzer 2008). The sickness signal comes from session 2's
    inflammation state."""
    well = PhysiologicalState(inflammation=0.0, glucose=0.75, dopamine=0.6)
    sick = PhysiologicalState(inflammation=1.8, glucose=0.75, dopamine=0.6)
    d_well = well.action_distribution(params)
    d_sick = sick.action_distribution(params)
    assert d_sick["withdraw"] > d_well["withdraw"] + 0.15
    assert d_sick["explore"] < d_well["explore"]
    assert d_sick["socialize"] < d_well["socialize"]


def test_sickness_signal_reads_from_inflammation_state(rng):
    """The physiological state's sickness pulls straight from the NPC's
    epigenome-backed inflammation state (session 2 -> session 3 link)."""
    npc = random_founder("subject", rng)
    st = npc.physiological_state()
    assert st.inflammation == pytest.approx(npc.inflammation_state)


# ------------------------------------------------------- gene -> behaviour (#25)

def test_genetic_priors_on_hormones_are_weak(rng):
    """
    Roadmap §5: behaviour is weakly polygenic; no gene->behaviour switch.
    Across many genotypes the endocrine priors must stay in a narrow band,
    never pinning an NPC's temperament deterministically.
    """
    dopa, hpa = [], []
    for i in range(200):
        hp = random_founder(f"n{i}", rng).hormone_params()
        dopa.append(hp.dopamine_baseline)
        hpa.append(hp.hpa_reactivity)
    dopa, hpa = np.array(dopa), np.array(hpa)
    # dopamine baseline stays within a narrow band around 0.5
    assert dopa.min() > 0.35 and dopa.max() < 0.65
    # HPA reactivity varies but never explodes
    assert hpa.min() > 0.6 and hpa.max() < 1.5


def test_edar_thermoregulation_reaches_behaviour(rng):
    """
    Session 1's promise, paid off: perturbing ONE pleiotropic gene (EDAR)
    changes an organ function (sweat-gland density -> thermoregulation),
    which under heat changes core temperature, the interoceptive thermal
    signal, and the action distribution. A bias, not a switch -- so we
    verify robustness in aggregate and direction, not a dramatic flip.
    """
    from health_engine.loci import locus_index
    edar = locus_index("EDAR")

    core_diffs, shelter_diffs = [], []
    for seed in range(12):
        npc = random_founder("twin", np.random.default_rng(seed))

        def under_heat(allele):
            npc.genome.haplotypes[:, edar] = allele    # 0/0 or 1/1 -> dosage 0 or 2
            npc.invalidate()
            hp = npc.hormone_params()
            st = npc.physiological_state(phase_h=13.0)
            st.sleep_pressure = 0.10
            for _ in range(3):
                st.step(1.0, hp, ambient_heat=0.35)
            d = st.action_distribution(hp)
            return hp.thermoregulation, st.core_temp, d["rest"] + d["withdraw"]

        t_absent, c_absent, sh_absent = under_heat(0)
        t_present, c_present, sh_present = under_heat(1)

        assert t_present > t_absent               # EDAR raises cooling capacity
        core_diffs.append(c_absent - c_present)   # absent runs hotter
        shelter_diffs.append(sh_absent - sh_present)

    core_diffs, shelter_diffs = np.array(core_diffs), np.array(shelter_diffs)
    assert core_diffs.mean() > 0.05               # robustly hotter without EDAR
    assert (core_diffs > 0).all()                 # every single genotype
    assert shelter_diffs.mean() > 0.0             # and it biases behaviour


# ------------------------------------------------------- basic homeostasis

def test_hunger_thirst_fatigue_drive_the_right_actions(params):
    hungry = PhysiologicalState(glucose=0.1)
    thirsty = PhysiologicalState(hydration=0.1)
    tired = PhysiologicalState(sleep_pressure=0.95, circadian_phase=2.0)
    assert hungry.dominant_action(params) == "forage"
    assert thirsty.dominant_action(params) == "drink"
    assert tired.dominant_action(params) == "rest"


def test_metabolic_variables_decay_and_replenish(params):
    st = PhysiologicalState(glucose=0.75, hydration=0.8)
    st.step(4.0, params, exertion=0.5)            # no intake, exerting
    assert st.glucose < 0.75 and st.hydration < 0.8
    st.step(2.0, params, food=0.2, water=0.2)     # eat and drink
    assert st.glucose > 0.4


def test_action_distribution_is_a_probability_distribution(params):
    st = PhysiologicalState(glucose=0.3, cortisol=0.7)
    d = st.action_distribution(params)
    assert set(d) == set(ACTION_CLASSES)
    assert abs(sum(d.values()) - 1.0) < 1e-9
    assert all(0.0 <= v <= 1.0 for v in d.values())
