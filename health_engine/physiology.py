"""
Physiological state vector: body -> mind signal layer.
======================================================

Roadmap Thrust 3, items #21 (physiological state vector for the LLM),
#22 (interoception), #23 (neuroendocrine/hormonal signalling), #24
(homeostasis / allostasis / allostatic load), with #25 (weak genetic
priors on hormone params), #26 (circadian) and #27 (sickness behaviour)
wired in.

The idea
--------
Human behaviour is continuously biased by internal physiological state
(Damasio 1994; Craig 2002/2009). An LLM "brain" reasoning over an NPC
needs that bias as input, or the NPC is a disembodied chatbot. This
module produces, from the body:

  1. a `PhysiologicalState` vector (glucose, hydration, sleep pressure,
     pain, core-temperature deviation, the HPA axis, adrenaline, the
     monoamine tones, oxytocin, sex hormone, inflammation, circadian
     phase, allostatic load);
  2. an interoceptive read-out (#22) — the salient signals the NPC would
     actually *feel*, sharpened by a heritable interoceptive-accuracy
     gain;
  3. a behavioural bias — a probability distribution over action classes
     (#21's "logit biases toward action classes"); and
  4. a natural-language summary for the LLM prompt.

The Stage-1 benchmark is met by (3): identical prompts produce measurably
different action distributions under "hungry / high-cortisol" vs "sated /
calm" states — no live LLM required, because the distribution IS the
logit-bias output.

How this extends session 2
--------------------------
Session 2 introduced exactly one trait-vs-state split:
`NPC.inflammation_state` = genetic predisposition + acquired epigenetic
load. This module generalises that pattern to a whole vector of states,
and reads `inflammation_state` straight in as its sickness signal. The
epigenetic clock's coupling to allostatic load (#24: "high load ...
accelerates the epigenetic clock") closes the loop back to session 2.

CAVEATS (roadmap §5, load-bearing)
----------------------------------
* #25's genetic priors are DELIBERATELY WEAK and polygenic. Neuroticism
  nudges HPA reactivity, extraversion nudges dopamine tone, etc., each
  through a tanh of a standardised polygenic liability with a small
  coefficient. These are NOT gene->behaviour switches. The candidate-gene
  era (COMT, 5-HTTLPR, MAOA) failed to replicate at scale (Border et al.
  2019); do not read these priors as anything but faint biases that
  environment and state swamp.
* The hormone dynamics are a legible caricature, not endocrinology. The
  HPA cascade (CRH -> ACTH -> cortisol -> negative feedback) has the right
  topology and the right qualitative behaviour (acute spike, negative
  feedback, chronic-stress elevation, morning circadian peak) but the
  rate constants are tuned for a readable hour-by-hour simulation, not
  fit to data (cf. Sapolsky, Romero & Munck 2000; McEwen 1998).
* Allostatic load is a scalar accumulator (McEwen & Stellar 1993); real
  allostatic load is a multi-system index. The direction of every
  coupling is right; the magnitudes are game-design choices.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import numpy as np

if TYPE_CHECKING:
    from .npc import NPC
    from .traits import Environment


# ======================================================================
# Action classes — the behavioural repertoire the state biases (#21)
# ======================================================================

ACTION_CLASSES: Tuple[str, ...] = (
    "forage",      # seek and consume food
    "drink",       # seek water
    "rest",        # sleep / recover
    "socialize",   # affiliate, bond
    "defend",      # fight or flee (threat response)
    "explore",     # goal-directed work / exploration
    "withdraw",    # sickness behaviour: disengage, conserve
    "court",       # mate-seeking
)


# ======================================================================
# Genetic priors on hormone / receptor parameters (#25)
# ======================================================================

@dataclass(frozen=True)
class HormoneParams:
    """
    Per-individual endocrine "constitution". Every field is a WEAK
    polygenic prior (see module caveat), derived from standardised trait
    liabilities via a small-coefficient tanh so nothing is a switch.
    """
    hpa_reactivity: float = 1.0          # gain on the stress -> cortisol path
    cortisol_feedback: float = 1.0       # strength of HPA negative feedback
    dopamine_baseline: float = 0.50      # motivation / reward tone
    serotonin_baseline: float = 0.50     # mood / impulse control
    oxytocin_baseline: float = 0.50      # affiliative tone
    sex_hormone_baseline: float = 0.50   # drive; sex-dependent
    interoception_gain: float = 1.0      # how loudly the body reaches the mind
    chronotype_shift_h: float = 0.0      # circadian phase offset, hours (neg = lark)
    thermoregulation: float = 0.50       # cooling capacity (EDAR sweat glands!)
    energy_reserve: float = 0.50         # fatigue resistance (aerobic capacity)


def _nudge(center: float, liability: float, coef: float,
           lo: float = 0.0, hi: float = 1.0) -> float:
    """Weak, bounded, SATURATING prior — for the behavioural/hormonal
    parameters that must stay faint (the #25 caveat). tanh squashes even
    a large liability into a small nudge."""
    return float(min(max(center + coef * math.tanh(liability), lo), hi))


def _organ_map(center: float, liability: float, slope: float,
               lo: float, hi: float) -> float:
    """LINEAR map for organ-function capacities (thermoregulation, energy
    reserve). Unlike the weak behavioural priors, these are real
    physiological pathways we want to be responsive across the whole
    range, so a single gene's marginal effect shows up consistently
    wherever the individual sits — not squashed by tanh at the tails.
    This is what lets EDAR's sweat-gland dosage reach behaviour reliably."""
    return float(min(max(center + slope * liability, lo), hi))


def derive_hormone_priors(npc: "NPC") -> HormoneParams:
    """
    Map genotype (via standardised trait liabilities) onto endocrine
    parameters — roadmap #25. The couplings are intentionally faint:

      neuroticism           -> HPA reactivity up, feedback down, serotonin down
      extraversion          -> dopamine tone up
      agreeableness         -> oxytocin tone up
      interoceptive_accuracy-> interoception gain (this one is allowed to
                               matter more: it is literally the gain of the
                               body->mind channel, and it is heritable, #22)
      chronotype            -> circadian phase offset (#26)
      sweat_gland_density   -> thermoregulatory cooling capacity. THIS is
                               EDAR reaching behaviour through an organ
                               function, exactly as promised in session 1,
                               not through a fictitious gene->personality
                               weight.
      aerobic_capacity      -> energy reserve / fatigue resistance
      sex + a faint genetic term -> sex-hormone baseline
    """
    L = npc.liability
    neuro = L("neuroticism")
    male = npc.sex == "male"
    return HormoneParams(
        hpa_reactivity=_nudge(1.0, neuro, 0.25, 0.5, 1.8),
        cortisol_feedback=_nudge(1.0, -neuro, 0.15, 0.5, 1.5),
        dopamine_baseline=_nudge(0.50, L("extraversion"), 0.12),
        serotonin_baseline=_nudge(0.50, -neuro, 0.12),
        oxytocin_baseline=_nudge(0.50, L("agreeableness"), 0.12),
        sex_hormone_baseline=_nudge(0.70 if male else 0.40,
                                    L("extraversion"), 0.06, 0.1, 0.95),
        interoception_gain=_nudge(1.0, L("interoceptive_accuracy"), 0.40, 0.4, 1.8),
        chronotype_shift_h=2.5 * math.tanh(L("chronotype")),
        thermoregulation=_organ_map(0.50, L("sweat_gland_density"), 0.16, 0.05, 0.95),
        energy_reserve=_organ_map(0.50, L("aerobic_capacity"), 0.14, 0.10, 0.95),
    )


# ======================================================================
# Circadian oscillator (#26)
# ======================================================================

def circadian_cortisol(phase_h: float, shift_h: float) -> float:
    """
    Diurnal cortisol rhythm: sharp peak shortly after habitual wake
    (~08:00), trough around midnight. `shift_h` is the chronotype offset
    (a lark's peak comes earlier). Returned as a multiplier in ~[0.2, 1].
    """
    peak = (8.0 + shift_h) % 24.0
    ang = 2 * math.pi * ((phase_h - peak) % 24.0) / 24.0
    return 0.6 + 0.4 * math.cos(ang)


def circadian_alertness(phase_h: float, shift_h: float) -> float:
    """Alertness: high across the biological day, low at biological night."""
    mid_wake = (14.0 + shift_h) % 24.0
    ang = 2 * math.pi * ((phase_h - mid_wake) % 24.0) / 24.0
    return 0.5 + 0.5 * math.cos(ang)         # ~1 mid-day, ~0 at biological 02:00


# ======================================================================
# The state vector (#21)
# ======================================================================

# Homeostatic set points.
GLUCOSE_SETPOINT = 0.75
HYDRATION_SETPOINT = 0.80
CORE_TEMP_SETPOINT = 0.0        # deviation from 37 C, in "discomfort units"

# Allostatic load accrues when cortisol sits above this for long periods.
ALLOSTATIC_CORTISOL_THRESHOLD = 0.65


@dataclass
class PhysiologicalState:
    """
    An NPC's instantaneous internal milieu. Units are mostly [0, 1] and
    game-legible rather than physiological. Evolve it with `step`.
    """
    # metabolic / homeostatic
    glucose: float = GLUCOSE_SETPOINT
    hydration: float = HYDRATION_SETPOINT
    sleep_pressure: float = 0.20        # Process S; rises awake, falls asleep
    pain: float = 0.0
    core_temp: float = 0.0              # deviation from set point

    # HPA axis (#23)
    crh: float = 0.10
    acth: float = 0.10
    cortisol: float = 0.35
    adrenaline: float = 0.05

    # monoamine / neuropeptide tone (#23)
    dopamine: float = 0.50
    serotonin: float = 0.50
    oxytocin: float = 0.50
    sex_hormone: float = 0.50

    # sickness signal, read from the epigenome-backed inflammation state (#27)
    inflammation: float = 0.0

    # context / clocks
    circadian_phase: float = 8.0        # hours [0, 24)
    awake: bool = True

    # cumulative wear (#24)
    allostatic_load: float = 0.0

    # -------------------- dynamics --------------------

    def step(self, hours: float, params: HormoneParams,
             stressor: float = 0.0, threat: float = 0.0,
             food: float = 0.0, water: float = 0.0,
             social: float = 0.0, exertion: float = 0.0,
             ambient_heat: float = 0.0) -> None:
        """
        Advance the state by `hours`. Inputs are RATES/intensities that
        hold across the interval:

        `stressor`  : sustained psychological/physical load [0, ~2]
        `threat`    : acute danger [0, 1] -> adrenaline + HPA
        `food/water`: intake rate per hour [0, ~1]
        `social`    : quality of affiliative contact [0, 1] -> oxytocin
        `exertion`  : physical effort [0, 1] -> glucose/hydration/heat cost
        `ambient_heat`: environmental heat load [0, 1]

        The HPA cascade is a stiff little ODE system; a raw Euler step at
        one-hour resolution oscillates and can collapse cortisol to zero.
        So we sub-step internally at <= 0.25 h, making the result
        stable and independent of the caller's chosen `hours`.
        """
        n = max(1, int(math.ceil(hours / 0.25)))
        h = hours / n
        for _ in range(n):
            self._step_once(h, params, stressor, threat, food, water,
                            social, exertion, ambient_heat)

    def _step_once(self, dt: float, params: HormoneParams,
                   stressor: float, threat: float, food: float, water: float,
                   social: float, exertion: float, ambient_heat: float) -> None:
        self.circadian_phase = (self.circadian_phase + dt) % 24.0
        cort_circ = circadian_cortisol(self.circadian_phase, params.chronotype_shift_h)

        # -- metabolic homeostasis (food/water are intake RATES) --------
        self.glucose = _clip(self.glucose
                             + (food - 0.015 - 0.06 * exertion) * dt)
        self.hydration = _clip(self.hydration
                               + (water - 0.012 - 0.03 * exertion
                                  - 0.05 * ambient_heat) * dt)

        # -- sleep pressure (Process S) ---------------------------------
        if self.awake:
            self.sleep_pressure = _clip(self.sleep_pressure
                                        + (0.05 + 0.02 * exertion) * dt
                                        / max(params.energy_reserve, 0.2))
        else:
            self.sleep_pressure = _clip(self.sleep_pressure - 0.13 * dt)

        # -- thermoregulation (EDAR pathway, #7 -> #21) -----------------
        # Heat load raises core temp; sweat-gland capacity cools it.
        cooling = (0.20 + 0.9 * params.thermoregulation) * dt
        heat_in = (1.2 * ambient_heat + 0.4 * exertion) * dt
        self.core_temp = self.core_temp + heat_in - cooling * max(self.core_temp, 0.0)
        self.core_temp = max(self.core_temp - (0.0 if self.core_temp > 0 else 0.1 * dt),
                             -1.0)
        self.core_temp = min(self.core_temp, 3.0)

        # -- pain decays unless refreshed by conditions (set externally) -
        self.pain = _clip(self.pain - 0.04 * dt, 0.0, 3.0)

        # -- HPA axis: CRH -> ACTH -> cortisol -> negative feedback ------
        # Internal stressors add to the external one: heat, low glucose,
        # pain, inflammation, circadian misalignment.
        alertness = circadian_alertness(self.circadian_phase, params.chronotype_shift_h)
        misalignment = (1.0 - alertness) if self.awake else 0.0
        total_stress = (stressor
                        + 0.8 * threat
                        + 0.6 * max(self.core_temp - 0.5, 0.0)
                        + 0.5 * max(GLUCOSE_SETPOINT - self.glucose, 0.0)
                        + 0.5 * self.pain
                        + 0.4 * max(self.inflammation, 0.0)
                        + 0.3 * misalignment)

        drive = params.hpa_reactivity * total_stress
        self.crh += dt * (1.6 * drive - 1.2 * params.cortisol_feedback * self.cortisol
                          - 1.5 * self.crh)
        self.crh = max(self.crh, 0.0)
        self.acth += dt * (1.5 * self.crh - 1.4 * self.acth)
        self.acth = max(self.acth, 0.0)
        target_cort = 0.35 * cort_circ + 1.3 * self.acth
        self.cortisol += dt * 1.2 * (target_cort - self.cortisol)
        self.cortisol = _clip(self.cortisol, 0.0, 2.5)

        # -- adrenaline: fast up on threat, fast decay ------------------
        self.adrenaline += dt * (3.0 * threat - 2.5 * self.adrenaline)
        self.adrenaline = _clip(self.adrenaline)

        # -- monoamines / oxytocin drift toward genetic baseline --------
        # modulated by state: reward from eating, dopamine hit; cortisol
        # suppresses serotonin; social contact raises oxytocin.
        reward = food + 0.5 * social
        self.dopamine += dt * (0.8 * (params.dopamine_baseline - self.dopamine)
                               + 0.6 * reward - 0.3 * self.pain)
        self.dopamine = _clip(self.dopamine)
        self.serotonin += dt * (0.7 * (params.serotonin_baseline - self.serotonin)
                                - 0.4 * max(self.cortisol - 0.6, 0.0))
        self.serotonin = _clip(self.serotonin)
        self.oxytocin += dt * (0.6 * (params.oxytocin_baseline - self.oxytocin)
                               + 1.2 * social)
        self.oxytocin = _clip(self.oxytocin)
        self.sex_hormone += dt * 0.3 * (params.sex_hormone_baseline - self.sex_hormone)
        self.sex_hormone = _clip(self.sex_hormone)

        # -- allostatic load (#24): the price of staying stressed -------
        overshoot = max(self.cortisol - ALLOSTATIC_CORTISOL_THRESHOLD, 0.0)
        self.allostatic_load += dt * (0.10 * overshoot
                                      + 0.03 * max(self.inflammation, 0.0)
                                      + 0.02 * max(self.core_temp - 0.5, 0.0))

    # -------------------- interoception (#22) --------------------

    def interoceptive_signals(self, params: HormoneParams) -> Dict[str, float]:
        """
        The felt signals, in [0, 1], after the heritable interoceptive
        gain and a threshold non-linearity that makes strong signals
        disproportionately salient (Craig 2002; Critchley 2004). These are
        what the NPC is *aware of*, distinct from the raw variables.
        """
        raw = {
            "hunger": max(GLUCOSE_SETPOINT - self.glucose, 0.0) / GLUCOSE_SETPOINT,
            "thirst": max(HYDRATION_SETPOINT - self.hydration, 0.0) / HYDRATION_SETPOINT,
            "fatigue": self.sleep_pressure,
            "pain": min(self.pain, 1.0),
            # scaled over a wider range so severe hyperthermia (core_temp up
            # to ~3) still registers gradations rather than pinning at 1.0
            "thermal_discomfort": min(abs(self.core_temp) / 2.0, 1.0),
            "sickness": min(max(self.inflammation, 0.0) / 2.0, 1.0),
            "stress": min(self.cortisol / 1.5, 1.0),
        }
        g = params.interoception_gain
        return {k: _salience(v, g) for k, v in raw.items()}

    # -------------------- behavioural bias (#21) --------------------

    def behavioral_bias(self, params: HormoneParams,
                        partner_present: bool = False) -> Dict[str, float]:
        """
        Logit contributions per action class, from the current state and
        the felt interoceptive signals. Higher = more likely. This is the
        vector an LLM harness would add to its action-selection logits, or
        equivalently softmax into a prior over actions.
        """
        s = self.interoceptive_signals(params)
        sickness = s["sickness"]
        # Sickness behaviour (#27): inflammation withdraws energy from
        # everything outward-facing.
        social_ok = 1.0 - 0.8 * sickness
        alertness = circadian_alertness(self.circadian_phase, params.chronotype_shift_h)

        logits = {a: 0.0 for a in ACTION_CLASSES}
        logits["forage"] += 3.2 * s["hunger"]
        logits["drink"] += 3.2 * s["thirst"]
        logits["rest"] += (2.6 * s["fatigue"] + 1.2 * sickness
                           + 2.4 * s["thermal_discomfort"] - 1.0 * alertness)
        logits["withdraw"] += (3.0 * sickness + 1.6 * s["pain"]
                               + 2.2 * s["thermal_discomfort"])
        # Defend is an ACUTE (adrenaline) response. Cortisol is the chronic
        # stress hormone and must not read as "fight" on its own -- generic
        # stress or heat should not make an NPC aggressive. So cortisol
        # contributes to defend only when adrenaline confirms a live threat.
        logits["defend"] += 3.2 * self.adrenaline \
            + 1.4 * max(self.cortisol - 0.6, 0.0) * min(self.adrenaline * 4.0, 1.0)
        logits["socialize"] += (1.8 * self.oxytocin + 1.0 * self.serotonin) * social_ok \
            - 1.2 * s["hunger"] - 1.2 * s["thirst"]
        logits["explore"] += (2.0 * self.dopamine + 1.4 * alertness) * social_ok \
            - 1.6 * s["fatigue"] - 1.0 * s["hunger"]
        logits["court"] += (2.2 * self.sex_hormone + 0.8 * self.dopamine
                            + 0.6 * self.oxytocin) * social_ok \
            - 1.5 * (s["hunger"] + s["thirst"] + s["pain"]) \
            + (0.8 if partner_present else -2.0)
        return logits

    def action_distribution(self, params: HormoneParams,
                            partner_present: bool = False,
                            temperature: float = 1.0) -> Dict[str, float]:
        """Softmax of the behavioural bias — a prior over action classes."""
        logits = self.behavioral_bias(params, partner_present)
        keys = list(logits)
        z = np.array([logits[k] for k in keys]) / max(temperature, 1e-3)
        z -= z.max()
        p = np.exp(z)
        p /= p.sum()
        return {k: float(v) for k, v in zip(keys, p)}

    def dominant_action(self, params: HormoneParams,
                        partner_present: bool = False) -> str:
        d = self.action_distribution(params, partner_present)
        return max(d, key=d.get)

    # -------------------- LLM serialization (#21) --------------------

    def to_prompt(self, params: HormoneParams, max_signals: int = 4) -> str:
        """
        Compact natural-language summary for the LLM prompt, prioritising
        the highest-salience interoceptive signals (roadmap's "collapse to
        a compact NL summary" note). Mood comes from the monoamine tone.
        """
        sig = self.interoceptive_signals(params)
        phrases = []
        for name, val in sorted(sig.items(), key=lambda kv: -kv[1]):
            word = _describe_signal(name, val)
            if word:
                phrases.append(word)
            if len(phrases) >= max_signals:
                break
        mood = _describe_mood(self.serotonin, self.dopamine, self.cortisol)
        body = "; ".join(phrases) if phrases else "comfortable"
        tod = _describe_time(self.circadian_phase)
        return f"[body] {body}. [mood] {mood}. [time] {tod}."


# ======================================================================
# Construction & coupling to the rest of the engine
# ======================================================================

def resting_state(npc: "NPC", params: Optional[HormoneParams] = None,
                  phase_h: float = 8.0) -> PhysiologicalState:
    """A rested, fed NPC at a given clock time, with its inflammation
    signal read from the session-2 epigenome-backed state."""
    st = PhysiologicalState(circadian_phase=phase_h)
    st.inflammation = npc.inflammation_state
    st.dopamine = (params or derive_hormone_priors(npc)).dopamine_baseline
    st.serotonin = (params or derive_hormone_priors(npc)).serotonin_baseline
    st.oxytocin = (params or derive_hormone_priors(npc)).oxytocin_baseline
    st.sex_hormone = (params or derive_hormone_priors(npc)).sex_hormone_baseline
    return st


def refresh_pain_and_sickness(npc: "NPC", state: PhysiologicalState) -> None:
    """Pull pain from active medical conditions and the sickness signal
    from the inflammation state, so acquired illness reaches behaviour (#27)."""
    state.pain = min(sum(c.severity for c in npc.medical_conditions), 3.0)
    state.inflammation = npc.inflammation_state


def book_allostatic_load_to_clock(npc: "NPC", state: PhysiologicalState,
                                  scale: float = 0.05) -> float:
    """
    Roadmap #24: high allostatic load accelerates the epigenetic clock.
    Returns the epigenetic-years added. Call after simulating a stressful
    stretch; closes the loop back to session 2's clock.
    """
    added = scale * state.allostatic_load
    npc.epigenome.epigenetic_age += added
    return added


# ======================================================================
# Distribution helpers (used by the benchmark)
# ======================================================================

def kl_divergence(p: Dict[str, float], q: Dict[str, float]) -> float:
    """KL(p || q) over action classes, in nats. The benchmark's yardstick
    for 'measurably different action distributions'."""
    eps = 1e-9
    return float(sum(p[k] * math.log((p[k] + eps) / (q[k] + eps)) for k in p))


# ======================================================================
# small helpers
# ======================================================================

def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return float(min(max(x, lo), hi))


def _salience(raw: float, gain: float, threshold: float = 0.35) -> float:
    """Interoceptive salience: linear below threshold, amplified above it,
    scaled by the heritable gain, clipped to [0, 1]."""
    amp = raw + max(raw - threshold, 0.0)      # signals past threshold shout
    return _clip(gain * amp)


def _describe_signal(name: str, val: float) -> str:
    if val < 0.15:
        return ""
    tiers = {
        "hunger": ["peckish", "hungry", "ravenous"],
        "thirst": ["a little thirsty", "thirsty", "parched"],
        "fatigue": ["slightly tired", "tired", "exhausted"],
        "pain": ["a dull ache", "in pain", "in severe pain"],
        "thermal_discomfort": ["warm", "overheating", "dangerously hot"],
        "sickness": ["a bit unwell", "sick", "gravely ill"],
        "stress": ["a little tense", "on edge", "highly stressed"],
    }
    words = tiers.get(name)
    if not words:
        return ""
    i = 0 if val < 0.4 else (1 if val < 0.7 else 2)
    return words[i]


def _describe_mood(serotonin: float, dopamine: float, cortisol: float) -> str:
    if cortisol > 0.9:
        return "anxious and on guard"
    if dopamine > 0.62 and serotonin > 0.55:
        return "upbeat and motivated"
    if serotonin < 0.4:
        return "low and irritable"
    if dopamine < 0.4:
        return "flat, unmotivated"
    return "even-keeled"


def _describe_time(phase_h: float) -> str:
    h = int(phase_h) % 24
    if 5 <= h < 12:
        return f"morning ({h:02d}:00)"
    if 12 <= h < 17:
        return f"afternoon ({h:02d}:00)"
    if 17 <= h < 21:
        return f"evening ({h:02d}:00)"
    return f"night ({h:02d}:00)"


def summary() -> str:
    return (
        "Physiological state layer (roadmap #21-#27)\n"
        f"  state variables : {len(PhysiologicalState().__dict__)} "
        "(metabolic, HPA axis, monoamines, circadian, allostatic load)\n"
        f"  action classes  : {', '.join(ACTION_CLASSES)}\n"
        "  interoception   : heritable gain (#22) + threshold salience\n"
        "  hormone priors  : weak polygenic (#25), NOT gene->behaviour switches\n"
        "  circadian       : chronotype-shifted cortisol + alertness rhythm (#26)\n"
        "  couplings       : sickness->withdrawal (#27); allostatic load->clock (#24);\n"
        "                    EDAR sweat glands -> thermoregulation -> action bias"
    )
