"""
extNPC Health Engine -- Reproduction, Inheritance & Medical Issues
==================================================================

Status: v0.5.0. Demo / entry point. The engine itself lives in the
`health_engine/` package; this file only drives it.

Covers all three Health Engine sub-components named in Table 1 of the
extNPC framework paper -- Medical Issues | Inheritance | Reproduction --
plus the paper's statement that the Health Engine is "used for life
partner choices" (Sec. 3.6).

WHAT CHANGED IN v0.3  (roadmap Stage 0, the blocking foundation refactor)
------------------------------------------------------------------------
v0.2 modelled inheritance as three layered heuristics: Simulated Binary
Crossover for continuous traits, single-gene Mendelian dominance for
discrete ones, and an Evolution-Strategy self-adaptive mutation sigma.
Each was a reasonable engineering choice and none of them is how genomes
work. The consequences were not cosmetic:

  * one locus = one trait, so no gene could affect two things;
  * loci assorted independently, so there was no linkage and no genome;
  * SBX interpolated a child's phenotype between its parents', so
    heritability could not be a parameter and selection response was
    structurally wrong;
  * `phenotype()` re-rolled its epigenetic silencing check on every call,
    so an NPC's eye colour changed depending on when you looked.

v0.3 replaces all of that with the standard quantitative-genetics model:

  * 22 autosomes with real centimorgan maps; meiosis draws crossovers as
    a Poisson process, so linked genes co-inherit (roadmap #1).
  * ~500 biallelic loci -- 50 named GWAS genes plus a peripheral
    background -- feeding a sparse gene x trait weight matrix, so EDAR
    touches hair, teeth, ears, chin and sweat glands at once (#7).
  * Phenotype = additive + dominance + epistasis + GxE + environment,
    with each trait's variance components solved to hit a target
    heritability exactly (#9, #10).
  * Discrete traits are liability-threshold traits (Falconer 1965), not
    single-gene switches. Expression is deterministic given the genome.
  * Founders sampled under Hardy-Weinberg (#29).
  * A validation harness proving the whole thing obeys Hardy-Weinberg,
    Haldane's map function, the midparent-offspring regression, the
    breeder's equation and Daetwyler's PGS law (#32).

WHAT LANDED AFTER v0.3  (sessions 2-8; see reads/REPORT.md)
-----------------------------------------------------------
Stage 1 is complete: lifetime-dynamic epigenetics with a germline
firewall (#15-#20, `epigenome.py`), the physiological state vector with
hormones, interoception and allostatic load (#21-#27, `physiology.py`),
and the gene-regulatory / omnigenic network (#8, `grn.py`). Stage 2 has
sex chromosomes with X-inactivation and hemizygosity (#2, `sexchrom.py`)
and maternal mitochondrial inheritance with a heteroplasmy bottleneck
(#3, `mito.py`). Stage 3 has Gale-Shapley stable matching (#30), which
lives in the population layer at `simulation/demography.py`.

Stage 2 also has genomic imprinting (#4, `imprint.py`): IGF2 is
paternally expressed, so reciprocal heterozygotes -- same genotype,
opposite parent of origin -- differ by exactly 2*s*a.

WHAT IS STILL MISSING
---------------------
Stage 2: the developmental trajectory / life-stage expression gating
(#13), and the canalization half of #14 (reaction norms are in, Waddington
buffering is not). Stage 3: inbreeding depression (#31) is partial -- the
kinship guard rejects close pairs, but no explicit fitness load scales
with F. #12 models point mutations but not structural variants.

Run:  python health_engine_prototype.py [--fast]

Note this demo drives the ENGINE only, on a hand-built nine-person
pedigree. The population layer (yearly turnover, demes, migration) and
the live dashboard are separate:  python run_dashboard.py
"""

from __future__ import annotations

import os
import sys

import numpy as np

from health_engine import legacy, validation, viz
from health_engine.epigenome import summary as epigenome_summary
from health_engine.physiology import summary as physiology_summary
from health_engine.loci import CORE_SYMBOLS, N_LOCI, describe, pleiotropic_genes
from health_engine.mating import best_mate, count_blocking_pairs, mate_compatibility, relatedness
from health_engine.medical import simulate_aging
from health_engine.npc import genomic_relatedness, random_founder, reproduce
from health_engine.traits import (ARCHITECTURE, CATEGORICAL_TRAITS, Environment,
                                  OCEAN_TRAITS, architecture_summary,
                                  traits_touched_by)

SEED = 7
FAST = "--fast" in sys.argv

SHOWCASE_TRAITS = [
    "height_cm", "bmi", "skin_tone", "hair_curl", "hair_thickness",
    "nose_width", "chin_protrusion", "incisor_shovelling",
    "sweat_gland_density", "insulin_sensitivity", "bp_set_point",
    "aerobic_capacity", "chronotype",
    *OCEAN_TRAITS, *CATEGORICAL_TRAITS,
]


def banner(text: str) -> None:
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def _top(dist, k: int = 3) -> str:
    """Format the top-k action classes of a distribution."""
    items = sorted(dist.items(), key=lambda kv: -kv[1])[:k]
    return ", ".join(f"{a} {p:.2f}" for a, p in items)


def main() -> None:
    rng = np.random.default_rng(SEED)

    # ------------------------------------------------------------------
    banner("0. THE GENOME")
    print(f"{N_LOCI} biallelic loci across 22 autosomes "
          f"({len(CORE_SYMBOLS)} named genes + background).\n")
    print("Pleiotropic core genes (one gene, many traits) -- roadmap #7:")
    for locus in pleiotropic_genes(min_traits=3)[:5]:
        print("\n  " + describe(locus.symbol).replace("\n", "\n  "))

    banner("0b. TRAIT ARCHITECTURE (variance components, all calibrated)")
    print(architecture_summary())

    # ------------------------------------------------------------------
    banner("1. GENERATION 0 -- founders sampled under Hardy-Weinberg (#29)")
    elira = random_founder("Elira", rng, sex="female")
    tomas = random_founder("Tomas", rng, sex="male")
    ines = random_founder("Ines", rng, sex="female")
    darius = random_founder("Darius", rng, sex="male")
    for f in (elira, tomas, ines, darius):
        f.pretty_print(SHOWCASE_TRAITS)

    # ------------------------------------------------------------------
    banner("2. GENERATION 1 -- children via meiosis with recombination (#1)")
    # A reaction-norm environment (#14): childhood undernutrition costs
    # height and raises inflammatory tone; it does NOT touch the genome.
    harsh = Environment(
        name="scarce, high-stress settlement",
        trait_shifts={"height_cm": -0.6, "inflammation_tone": 0.5,
                      "insulin_sensitivity": -0.3},
        gxe_means={"insulin_sensitivity": -0.4},
        stress=1.4,
    )
    # Sexes are pinned so the demo always has cross-family, opposite-sex,
    # unrelated pairs available in generation 1. `reproduce` samples sex
    # 50/50 when it is not given one.
    sena = reproduce(elira, tomas, "Sena", rng, environment=harsh, sex="female")
    kaan = reproduce(elira, tomas, "Kaan", rng, environment=harsh, sex="male")
    mira = reproduce(ines, darius, "Mira", rng, sex="female")
    baran = reproduce(ines, darius, "Baran", rng, sex="male")
    for child in (sena, kaan, mira, baran):
        child.pretty_print(SHOWCASE_TRAITS)

    print("\nSena and Kaan are full siblings of the same two parents, yet they")
    print("differ. In v0.2 they could not have: SBX drew both between the same")
    print("two parental phenotypes. Here each received a different random half")
    print("of each parent's genome.")
    print(f"  relatedness(Sena, Kaan)   = {genomic_relatedness(sena, kaan):+.3f}   (full sibs,  expect 0.50 on average)")
    print(f"  relatedness(Sena, Elira)  = {genomic_relatedness(sena, elira):+.3f}   (parent,     exactly 0.50 in truth)")
    print(f"  relatedness(Sena, Mira)   = {genomic_relatedness(sena, mira):+.3f}   (unrelated,  expect 0.00)")
    print("\n  Both 0.50s carry visible error because the GCTA estimator is computed")
    print("  from only 500 loci. The parent-offspring value is exactly 0.50 in")
    print("  truth (a child always gets half of each parent) and its scatter here")
    print("  is pure measurement noise; the sibling value genuinely varies, because")
    print("  which half each sib received is a meiotic lottery. Only the second")
    print("  kind of scatter survives on a real dense genome.")

    # ------------------------------------------------------------------
    banner("3. PLEIOTROPY IN ACTION -- perturb EDAR, watch five traits move (#7)")
    from health_engine.loci import locus_index
    probe = random_founder("EDAR-probe", rng)
    idx = locus_index("EDAR")

    probe.genome.haplotypes[:, idx] = 0
    probe.invalidate()
    before = probe.phenotype()
    probe.genome.haplotypes[:, idx] = 1
    probe.invalidate()
    after = probe.phenotype()

    print("Same individual, same environment, EDAR 0/0 -> 1/1. Nothing else touched.\n")
    print(f"  {'trait':<26}{'EDAR 0/0':>12}{'EDAR 1/1':>12}{'delta':>10}")
    for t in sorted(traits_touched_by("EDAR")):
        print(f"  {t:<26}{before[t]:>12.3f}{after[t]:>12.3f}{after[t] - before[t]:>+10.3f}")
    print(f"\n  {'eye_color (no EDAR weight)':<26}{str(before['eye_color']):>12}"
          f"{str(after['eye_color']):>12}{'unchanged':>10}")
    print("\nsweat_gland_density is the interesting one: it is an ORGAN FUNCTION,")
    print("not an appearance trait. It is how EDAR will eventually reach behaviour")
    print("-- via thermoregulatory capacity -> physiological state -> action bias")
    print("(roadmap #21-#24) -- rather than through a fictitious gene->personality")
    print("weight, which the literature does not support (Border et al. 2019).")

    # ------------------------------------------------------------------
    banner("3b. LIFETIME-DYNAMIC EPIGENETICS -- the top-priority gap (#15-#20)")
    print(epigenome_summary())
    print("\nOne NPC, one genome, three life histories. The alleles never change;")
    print("the epigenome does, and it drives the physiological state.\n")

    from health_engine.traits import Environment as Env
    smoker = random_founder("Smoker", rng, sex="female")
    father_e = random_founder("FatherE", rng, sex="male")
    ahrr0 = smoker.epigenome.methylation_of("AHRR")
    simulate_aging(smoker, 20, rng, Env("smoky", exposures={"smoking": 1.0}))
    ahrr_smoked = smoker.epigenome.methylation_of("AHRR")

    # Children conceived at the HEIGHT of her smoking, to test the firewall
    # against the largest deviation.
    child_devs = []
    for i in range(50):
        c = reproduce(smoker, father_e, f"gc{i}", rng, mutation=False)
        child_devs.append(abs(c.epigenome.methylation_of("AHRR") - ahrr0))

    simulate_aging(smoker, 15, rng, Env("clean"))
    ahrr_quit = smoker.epigenome.methylation_of("AHRR")

    print(f"  AHRR cg05575921 methylation (Joehanes 2016 smoking signal):")
    print(f"    at birth                      : {ahrr0:.3f}")
    print(f"    after 20 years smoking        : {ahrr_smoked:.3f}   (hypomethylation)")
    print(f"    after 15 years cessation      : {ahrr_quit:.3f}   (partial recovery)")

    calm = random_founder("Calm", rng)
    simulate_aging(calm, 40, rng, Env("calm", stress=1.0))
    stressed = random_founder("Stressed", rng)
    simulate_aging(stressed, 40, rng,
                   Env("harsh", stress=2.0, exposures={"psychosocial_stress": 1.0}))
    print(f"\n  Epigenetic clock after 40 chronological years (#17):")
    print(f"    calm life    -> epigenetic age {calm.epigenetic_age:5.1f}  "
          f"(accel {calm.epigenetic_age_acceleration:+.1f})")
    print(f"    stressed life-> epigenetic age {stressed.epigenetic_age:5.1f}  "
          f"(accel {stressed.epigenetic_age_acceleration:+.1f})")
    print(f"    inflammation STATE: calm {calm.inflammation_state:+.2f} vs "
          f"stressed {stressed.inflammation_state:+.2f} (genetic + acquired load)")

    # germline firewall (children were conceived above, mid-smoking)
    print(f"\n  Germline firewall (#20): at conception the smoker's AHRR "
          f"deviation was {abs(ahrr_smoked - ahrr0):.3f};")
    print(f"    mean deviation across her 50 children is only "
          f"{sum(child_devs)/len(child_devs):.4f} "
          f"({100*(sum(child_devs)/len(child_devs))/abs(ahrr_smoked-ahrr0):.1f}% of the parent's).")
    print("    Acquired marks almost never cross the germline (base reset 0.95).")
    print("    IGF2, the one escaper, is the exception -- see the figure.")

    # ------------------------------------------------------------------
    banner("4. MEDICAL ISSUES -- aging 30 years, acquiring conditions")
    for npc in (sena, kaan, mira, baran):
        simulate_aging(npc, years=30, rng=rng,
                       environment=harsh if npc.name in ("Sena", "Kaan") else None)
        conds = npc.medical_conditions or "none"
        print(f"\n  {npc.name:<7} age {npc.age} | epi-age "
              f"{npc.epigenetic_age:.0f} (accel {npc.epigenetic_age_acceleration:+.0f}) "
              f"| {conds}")
        if npc.medical_conditions:
            print(f"          action-set restrictions: {npc.restricted_actions()}")
    print("\nAcquired conditions are never transmitted. Predisposition genes only")
    print("set the hazard; the illness itself dies with the individual. The harsh-")
    print("environment siblings (Sena, Kaan) also carry higher epigenetic age.")

    # ------------------------------------------------------------------
    banner("4b. BODY -> MIND SIGNAL LAYER -- physiological state (#21-#27)")
    print(physiology_summary())

    from health_engine.physiology import PhysiologicalState, kl_divergence
    hp = sena.hormone_params()

    print("\n  The Stage-1 benchmark: one body, one prompt, two internal states.")
    hungry = PhysiologicalState(glucose=0.12, hydration=0.5, cortisol=1.1,
                                adrenaline=0.2, circadian_phase=13.0)
    sated = PhysiologicalState(glucose=0.8, cortisol=0.35, dopamine=0.68,
                               oxytocin=0.66, serotonin=0.6, circadian_phase=13.0)
    dh, ds = hungry.action_distribution(hp), sated.action_distribution(hp)
    print(f"\n    HUNGRY/STRESSED  -> {hungry.dominant_action(hp).upper():<9} | "
          f"{hungry.to_prompt(hp)}")
    print(f"      top actions: {_top(dh)}")
    print(f"    SATED/CALM       -> {sated.dominant_action(hp).upper():<9} | "
          f"{sated.to_prompt(hp)}")
    print(f"      top actions: {_top(ds)}")
    print(f"\n    KL divergence between the two action distributions: "
          f"{kl_divergence(dh, ds):.2f} nats -- measurably different, no LLM required.")

    # Sena's real, lived state: her acquired conditions become felt pain and
    # her harsh-environment inflammation becomes sickness behaviour (#27).
    sena_state = sena.physiological_state(phase_h=20.0)
    print(f"\n  Sena's actual lived state at 20:00 (age {sena.age}, "
          f"{len(sena.medical_conditions)} conditions, "
          f"inflammation {sena.inflammation_state:+.2f}):")
    print(f"    {sena_state.to_prompt(hp)}")
    print(f"    action bias: {_top(sena_state.action_distribution(hp))}")

    # EDAR reaches behaviour through an organ function, as promised in session 1.
    print("\n  One gene reaching behaviour (#7 -> #21): toggle EDAR, expose to heat.")
    from health_engine.loci import locus_index
    edar = locus_index("EDAR")
    twin = random_founder("Twin", rng)
    for allele, label in [(0, "EDAR absent "), (1, "EDAR present")]:
        twin.genome.haplotypes[:, edar] = allele
        twin.invalidate()
        tp = twin.hormone_params()
        st = twin.physiological_state(phase_h=13.0)
        st.sleep_pressure = 0.1
        for _ in range(5):
            st.step(1.0, tp, ambient_heat=0.45)
        d = st.action_distribution(tp)
        print(f"    {label}: sweat-gland capacity {tp.thermoregulation:.2f} -> "
              f"core temp {st.core_temp:.2f} -> "
              f"shelter-seeking (rest+withdraw) {d['rest'] + d['withdraw']:.2f}")
    print("    Same NPC, one locus. EDAR's sweat-gland arm changes thermoregulation,")
    print("    which under heat changes core temperature, which biases behaviour --")
    print("    the honest gene->organ->state->behaviour route, not a gene->mood switch.")

    # ------------------------------------------------------------------
    banner("5. LIFE PARTNER SELECTION -- Health Engine's mate-choice role")
    gen1 = [sena, kaan, mira, baran]
    matching = {}
    for npc in gen1:
        partner = best_mate(npc, gen1)
        if partner is None:
            print(f"  {npc.name:<7} no eligible partner "
                  f"(same sex, or too closely related)")
            continue
        matching[npc.name] = partner.name
        print(f"  {npc.name:<7} ({npc.sex:<6}) -> {partner.name:<7} "
              f"score={mate_compatibility(npc, partner):.3f}  "
              f"relatedness={relatedness(npc, partner):+.3f}")

    print(f"\n  sibling pairs blocked by the kinship guard: "
          f"relatedness(Sena,Kaan)={relatedness(sena, kaan):.3f} "
          f">= threshold 0.125")
    print(f"  blocking pairs in this greedy matching: {count_blocking_pairs(matching, gen1)}")
    print("  (Gale-Shapley -- roadmap #30 -- guarantees zero, and IS implemented:")
    print("   simulation/demography.py:stable_matching, used by the population layer.")
    print("   This demo keeps the greedy matcher deliberately, as the baseline whose")
    print("   blocking pairs motivate it. Compare the two in the dashboard.)")

    # ------------------------------------------------------------------
    banner("6. GENERATION 2 -- a grandchild, with an older father (#12)")
    partner = best_mate(sena, gen1)
    if partner is None:
        partner = next(p for p in gen1 if p.sex != sena.sex and relatedness(sena, p) < 0.125)
    mother, father = (sena, partner) if sena.sex == "female" else (partner, sena)
    deren = reproduce(mother, father, "Deren", rng)
    deren.pretty_print(SHOWCASE_TRAITS)
    print(f"\n  father's age at conception: {father.age}  ->  de novo mutations: "
          f"{deren.de_novo_mutations}")
    print("\n  A single birth tells you nothing: at ~0.18 de novo events per birth")
    print("  across 500 loci, most children have exactly zero. The paternal-age")
    print("  effect only resolves in aggregate. Sampling gametes directly:\n")

    from health_engine.genome import mutate_gamete, paternal_age_multiplier
    from health_engine.loci import N_LOCI as L

    reps = 4000 if FAST else 20000

    def mean_mutations(sex: str, age: float | None = None) -> float:
        return sum(mutate_gamete(np.zeros(L, np.int8), rng, sex, age)
                   for _ in range(reps)) / reps

    egg = mean_mutations("female")
    print(f"  {'paternal age':>14}{'sperm':>10}{'egg':>10}{'per birth':>12}{'vs age 20':>12}")
    baseline = None
    for age in (20, 30, 40, 50):
        sperm = mean_mutations("male", age)
        per_birth = sperm + egg
        baseline = baseline if baseline is not None else per_birth
        print(f"  {age:>14}{sperm:>10.4f}{egg:>10.4f}{per_birth:>12.4f}"
              f"{per_birth / baseline:>11.2f}x")

    print(f"\n  paternal:maternal ratio at the reference age = "
          f"{mean_mutations('male', 29.7) / egg:.2f} : 1")
    print("\n  Kong et al. 2012 (Nature 488:471): de novo count ~ 25.6 + 2.01 x")
    print("  paternal age, a ~4:1 paternal:maternal bias, and ~+2 mutations per")
    print("  year of the father's age. Our multiplier at 50 vs the reference age")
    print(f"  of 29.7 is {paternal_age_multiplier(50.0):.2f}x. The mother's contribution does not move:")
    print("  her oocytes arrested in prophase I before she was born.")

    # ------------------------------------------------------------------
    banner("7. SBX vs REAL MEIOSIS -- what the old operator could not do")
    print(legacy.sbx_vs_meiosis_report("height_cm", 600 if FAST else 1500, rng))

    # ------------------------------------------------------------------
    banner("8. VALIDATION HARNESS (#32)")
    print(validation.full_report(rng, fast=FAST))

    # ------------------------------------------------------------------
    banner("9. FIGURES")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
    os.makedirs(out, exist_ok=True)
    population = [elira, tomas, ines, darius, sena, kaan, mira, baran, deren]

    # The three session 5-7 figures below take their OWN seeds and never touch
    # `rng`, so adding them leaves every other number in this run unchanged --
    # the same stream discipline the engine layers themselves follow.
    paths = [
        viz.plot_pedigree_relatedness(population, os.path.join(out, "pedigree_relatedness.png")),
        viz.plot_family_radars({
            "Family A: Elira x Tomas": [elira, tomas, sena, kaan],
            "Family B: Ines x Darius": [ines, darius, mira, baran],
            f"Cross-family: {mother.name} x {father.name}": [mother, father, deren],
        }, os.path.join(out, "family_ocean_radars.png")),
        viz.plot_pleiotropy_matrix(os.path.join(out, "pleiotropy_matrix.png")),
        viz.plot_heritability_validation(
            ["height_cm", "neuroticism"], 500 if FAST else 1500, rng,
            os.path.join(out, "heritability_validation.png")),
        viz.plot_recombination_haldane(
            rng, os.path.join(out, "recombination_haldane.png"),
            n_meioses=1200 if FAST else 4000, n_pairs=20 if FAST else 40),
        viz.plot_epigenetics(rng, os.path.join(out, "epigenetics.png")),
        viz.plot_physiology(rng, os.path.join(out, "physiology.png")),
        viz.plot_grn_perturbation(os.path.join(out, "grn_network.png"),
                                  n=150 if FAST else 400),
        viz.plot_sex_linked_inheritance(os.path.join(out, "sex_linked.png"),
                                        n=8000 if FAST else 30000),
        viz.plot_mito_inheritance(os.path.join(out, "mito_inheritance.png")),
        viz.plot_imprinting(os.path.join(out, "imprinting.png"),
                            n=1200 if FAST else 4000),
        viz.plot_canalization(os.path.join(out, "canalization.png"),
                              n=1000 if FAST else 3000),
        viz.plot_inbreeding_depression(
            os.path.join(out, "inbreeding_depression.png"),
            n=800 if FAST else 3000),
        viz.plot_directional_dominance(
            os.path.join(out, "directional_dominance.png"),
            n=500 if FAST else 1500),
        viz.plot_mendelian_diseases(
            os.path.join(out, "mendelian_diseases.png"),
            n=800 if FAST else 3000),
        viz.plot_load_purging(
            os.path.join(out, "load_purging.png"),
            n_lines=60 if FAST else 150,
            n_control=500 if FAST else 1500),
        viz.plot_cnv_dosage(os.path.join(out, "cnv_dosage.png"),
                            n=800 if FAST else 2500),
        viz.plot_development(os.path.join(out, "development.png")),
    ]
    for p in paths:
        print(f"  {p}")

    banner("PEDIGREE SUMMARY")
    for npc in population:
        lineage = f"{npc.parents[0]} x {npc.parents[1]}" if npc.parents else "founder"
        print(f"  gen {npc.generation} | {npc.name:<12} {npc.sex:<7} <- {lineage}")


if __name__ == "__main__":
    main()
