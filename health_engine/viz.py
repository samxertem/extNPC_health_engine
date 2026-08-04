"""
Figures.
========

v0.2 produced three: a pairwise similarity heatmap, family OCEAN radars,
and a boxplot of self-adaptive mutation sigma drifting across
generations. The third is gone -- `mutation_sigma` no longer exists,
because Evolution-Strategy step sizes are not a thing organisms carry.

What replaces it are figures that show the new machinery is *correct*,
not merely that it produced numbers:

  1. pedigree_relatedness.png   realised genomic relatedness, all pairs
  2. family_ocean_radars.png    OCEAN profiles, founders vs offspring
  3. heritability_validation.png  midparent-offspring regression vs h^2
  4. pleiotropy_matrix.png      core gene x trait weight matrix (EDAR!)
  5. recombination_haldane.png  observed recombination fraction vs theory
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")               # headless: no display in this environment
import matplotlib.pyplot as plt
import numpy as np

from .genetic_map import haldane_recombination_fraction
from .loci import CM_POS, CHROM, LOCI, N_LOCI
from .npc import NPC, genomic_relatedness
from .traits import ARCHITECTURE, OCEAN_TRAITS, TRAIT_TABLE


def _save(fig, path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# ----------------------------------------------------------------------

def plot_pedigree_relatedness(population: List[NPC], out_path: str) -> str:
    """
    Realised additive relatedness (GCTA estimator) between every pair.

    What to look for: parent-offspring and full-sibling cells both average
    0.50, but for different reasons. A child inherits exactly half its
    genome from each parent every time -- that 0.50 is a constant, and any
    scatter you see in those cells is estimator noise from having only 500
    loci. Full sibs share half *on average* and genuinely vary around it,
    because which half each sib received is a meiotic lottery. The extra
    biological variance in the sibling cells is a direct consequence of
    modelling meiosis; a model without it cannot produce the asymmetry.
    With a real 10^6-marker genome the estimator noise vanishes and only
    the sibling scatter (sd ~ 0.036) remains.
    """
    names = [n.name for n in population]
    k = len(names)
    # The diagonal is the self-relatedness 1 + F, so it reports each
    # individual's own inbreeding coefficient rather than a trivial 1.0.
    M = np.array([[genomic_relatedness(a, b) for b in population]
                  for a in population])

    fig, ax = plt.subplots(figsize=(1.0 * k + 3, 1.0 * k + 1))
    im = ax.imshow(M, vmin=-0.15, vmax=1.0, cmap="magma")
    ax.set_xticks(range(k), names, rotation=45, ha="right")
    ax.set_yticks(range(k), names)
    for i in range(k):
        for j in range(k):
            ax.text(j, i, f"{M[i, j]:.2f}", ha="center", va="center",
                    fontsize=7, color="white" if M[i, j] < 0.55 else "black")
    ax.set_title("Realised genomic relatedness across the pedigree\n"
                 "(GCTA estimator; 0.50 = parent-offspring or full sibs)",
                 fontsize=11, fontweight="bold")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    return _save(fig, out_path)


def plot_family_radars(families: Dict[str, List[NPC]], out_path: str) -> str:
    """OCEAN liabilities per family. Founders dashed, offspring solid."""
    angles = np.linspace(0, 2 * np.pi, len(OCEAN_TRAITS), endpoint=False).tolist()
    angles += angles[:1]

    n = len(families)
    fig, axes = plt.subplots(1, n, subplot_kw=dict(polar=True), figsize=(6 * n, 6))
    if n == 1:
        axes = [axes]
    for ax, (fam, members) in zip(axes, families.items()):
        for npc in members:
            vals = [npc.phenotype()[t] for t in OCEAN_TRAITS]
            vals += vals[:1]
            ax.plot(angles, vals, "--" if npc.parents is None else "-",
                    linewidth=2, label=npc.name)
            ax.fill(angles, vals, alpha=0.08)
        ax.set_xticks(angles[:-1], [t[:4].capitalize() for t in OCEAN_TRAITS], fontsize=9)
        ax.set_ylim(0, 1)
        ax.set_title(fam, fontsize=11)
        ax.legend(loc="upper right", bbox_to_anchor=(1.35, 1.15), fontsize=8)
    fig.suptitle("OCEAN personality: founders (dashed) vs offspring (solid)",
                 fontsize=13, fontweight="bold")
    return _save(fig, out_path)


def plot_heritability_validation(traits: List[str], n_families: int,
                                 rng: np.random.Generator, out_path: str) -> str:
    """
    The Stage-0 benchmark, drawn. Each panel scatters offspring liability
    against midparent liability and overlays two lines: the fitted OLS
    slope, and the theoretical h^2. If the genotype->phenotype
    calibration and the meiosis are both right, they lie on top of each
    other.

    The visual difference between panels is the whole of quantitative
    genetics: height's cloud is a tight diagonal (h^2 = 0.80), so tall
    parents reliably make tall children. Neuroticism's cloud is nearly
    round (h^2 = 0.40 diluted by a large environmental residual), so a
    neurotic parent tells you comparatively little.
    """
    from .validation import random_mating_trios, _liabilities
    from .genome import dosage_matrix

    fig, axes = plt.subplots(1, len(traits), figsize=(5.4 * len(traits), 5))
    if len(traits) == 1:
        axes = [axes]

    for ax, trait in zip(axes, traits):
        arch = ARCHITECTURE[trait]
        trios = random_mating_trios(n_families, rng)
        zm = _liabilities(arch, dosage_matrix([t.mother for t in trios]), rng)
        zf = _liabilities(arch, dosage_matrix([t.father for t in trios]), rng)
        zc = _liabilities(arch, dosage_matrix([t.child for t in trios]), rng)
        mp = 0.5 * (zm + zf)
        slope, intercept = np.polyfit(mp, zc, 1)

        v_p = arch.v_a + arch.v_d + arch.v_i + arch.v_gxe + arch.v_e
        h2 = arch.v_a / v_p

        ax.scatter(mp, zc, s=6, alpha=0.25, color="#3b6ea5", edgecolors="none")
        xs = np.linspace(mp.min(), mp.max(), 50)
        ax.plot(xs, slope * xs + intercept, color="#c0392b", lw=2.2,
                label=f"observed slope = {slope:.3f}")
        ax.plot(xs, h2 * xs, color="#111111", lw=1.6, ls="--",
                label=f"theory: $h^2$ = {h2:.3f}")
        ax.axhline(0, color="grey", lw=0.5)
        ax.axvline(0, color="grey", lw=0.5)
        ax.set_xlabel("midparent liability (z)")
        ax.set_ylabel("offspring liability (z)")
        ax.set_title(f"{trait}\n{arch.n_loci} loci", fontsize=11)
        ax.legend(fontsize=8, loc="upper left")

    fig.tight_layout(rect=(0, 0, 1, 0.86))
    fig.suptitle("Parent-offspring regression recovers the target heritability\n"
                 "(nothing in reproduce() knows what $h^2$ is -- the slope is emergent)",
                 fontsize=12, fontweight="bold", y=0.99)
    return _save(fig, out_path)


def plot_pleiotropy_matrix(out_path: str, min_traits: int = 2) -> str:
    """
    The gene x trait weight matrix for core genes -- roadmap #7 made
    literal. Read EDAR's row: one allele, five traits, spanning hair
    shaft diameter, tooth shape, ear cartilage, chin projection and
    eccrine sweat-gland density. Read HERC2's: eye colour, skin tone,
    hair pigment.

    The white cells are the point. The matrix is sparse -- most genes
    touch one trait -- but the rows that are not sparse are what make a
    genome behave like a body rather than a list of independent sliders.
    """
    genes = [L for L in LOCI if L.is_core and len(L.weights) >= min_traits]
    genes.sort(key=lambda L: (-len(L.weights), L.symbol))
    traits = [t for t in TRAIT_TABLE if any(t in g.weights for g in genes)]

    M = np.zeros((len(genes), len(traits)))
    for i, g in enumerate(genes):
        for j, t in enumerate(traits):
            M[i, j] = g.weights.get(t, 0.0)

    lim = float(np.abs(M).max())
    fig, ax = plt.subplots(figsize=(0.42 * len(traits) + 4, 0.34 * len(genes) + 3))
    im = ax.imshow(M, cmap="RdBu_r", vmin=-lim, vmax=lim, aspect="auto")
    ax.set_xticks(range(len(traits)), traits, rotation=60, ha="right", fontsize=8)
    ax.set_yticks(range(len(genes)), [g.symbol for g in genes], fontsize=8)
    for i, g in enumerate(genes):
        if g.symbol == "EDAR":
            ax.axhspan(i - 0.5, i + 0.5, facecolor="none", edgecolor="black", lw=1.6)
    ax.set_title("Pleiotropy: core gene x trait weight matrix\n"
                 f"({len(genes)} genes touching >= {min_traits} traits; EDAR outlined)",
                 fontsize=11, fontweight="bold")
    fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02, label="additive weight (alt allele)")
    return _save(fig, out_path)


def plot_epigenetics(rng: np.random.Generator, out_path: str) -> str:
    """
    Three panels telling the lifetime-epigenetics story (roadmap #15-#20):

      (a) AHRR methylation over a life of smoking then cessation, showing
          the dose-dependent shift and its partial, slower recovery.
      (b) The epigenetic clock: chronological vs epigenetic age under a
          calm life and a chronically stressed one.
      (c) Germline firewall: parent-vs-child methylation deviation at an
          escaper locus (IGF2) and a non-escaper (AHRR), showing that
          acquired marks almost never cross the germline.
    """
    from .epigenome import (BASELINE_METHYLATION, Epigenome, IGF2_IDX,
                            germline_transmit)
    from .medical import simulate_aging
    from .npc import random_founder, reproduce
    from .traits import Environment

    fig, axes = plt.subplots(1, 3, figsize=(17, 5))

    # (a) smoking trajectory ------------------------------------------------
    ax = axes[0]
    for intensity, colour in [(1.0, "#c0392b"), (0.5, "#e08e0b")]:
        npc = random_founder("s", rng)
        traj = [npc.epigenome.methylation_of("AHRR")]
        for _ in range(25):
            simulate_aging(npc, 1, rng, Environment("smoky", exposures={"smoking": intensity}))
            traj.append(npc.epigenome.methylation_of("AHRR"))
        for _ in range(25):
            simulate_aging(npc, 1, rng, Environment("clean"))
            traj.append(npc.epigenome.methylation_of("AHRR"))
        ax.plot(range(len(traj)), traj, color=colour, lw=2,
                label=f"smoking intensity {intensity:g}")
    ax.axhline(BASELINE_METHYLATION, color="grey", ls=":", lw=1, label="baseline")
    ax.axvspan(0, 25, color="#c0392b", alpha=0.07)
    ax.axvspan(25, 50, color="#2e8b57", alpha=0.07)
    ax.text(12, 0.475, "smoking", ha="center", fontsize=9, color="#8a2020")
    ax.text(37, 0.475, "cessation", ha="center", fontsize=9, color="#1e5e3a")
    ax.set_xlabel("age (years)")
    ax.set_ylabel("AHRR cg05575921 methylation")
    ax.set_title("(a) Smoking hypomethylates AHRR;\npartial recovery on cessation", fontsize=10)
    ax.legend(fontsize=8, loc="lower right")

    # (b) epigenetic clock --------------------------------------------------
    ax = axes[1]
    for label, env, colour in [
        ("calm (stress 1.0)", Environment("calm", stress=1.0), "#2e8b57"),
        ("chronic stress (2.0)", Environment("harsh", stress=2.0,
                                             exposures={"psychosocial_stress": 1.0}), "#c0392b"),
    ]:
        npc = random_founder("c", rng)
        chrono, epi = [0], [0.0]
        for yr in range(1, 51):
            simulate_aging(npc, 1, rng, env)
            chrono.append(yr)
            epi.append(npc.epigenetic_age)
        ax.plot(chrono, epi, color=colour, lw=2, label=label)
    ax.plot([0, 50], [0, 50], color="grey", ls="--", lw=1, label="1:1 (no acceleration)")
    ax.set_xlabel("chronological age (years)")
    ax.set_ylabel("epigenetic age (years)")
    ax.set_title("(b) The epigenetic clock:\nstress accelerates biological aging", fontsize=10)
    ax.legend(fontsize=8, loc="upper left")

    # (c) germline firewall -------------------------------------------------
    ax = axes[2]
    parent_dev = 0.30
    igf2_child, ahrr_child = [], []
    from .epigenome import AHRR_IDX
    for _ in range(300):
        p1, p2 = Epigenome.default(), Epigenome.default()
        for e in (p1, p2):
            e.methylation[IGF2_IDX] = BASELINE_METHYLATION - parent_dev
            e.methylation[AHRR_IDX] = BASELINE_METHYLATION - parent_dev
        child = germline_transmit(p1, p2, rng)
        igf2_child.append(BASELINE_METHYLATION - child.methylation[IGF2_IDX])
        ahrr_child.append(BASELINE_METHYLATION - child.methylation[AHRR_IDX])
    ax.bar([0, 1], [parent_dev, parent_dev], width=0.5, color="#888", label="parent deviation")
    ax.bar([0, 1], [np.mean(igf2_child), np.mean(ahrr_child)], width=0.5,
           color=["#2e8b57", "#c0392b"], label="mean child deviation")
    ax.set_xticks([0, 1], ["IGF2\n(escaper)", "AHRR\n(non-escaper)"])
    ax.set_ylabel("methylation deviation from baseline")
    ax.set_title("(c) The germline firewall:\nacquired marks rarely cross", fontsize=10)
    ax.legend(fontsize=8)

    fig.suptitle("Lifetime-dynamic epigenetics (roadmap #15-#20): marks move during "
                 "life, and almost none are inherited",
                 fontsize=12, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return _save(fig, out_path)


def plot_physiology(rng: np.random.Generator, out_path: str) -> str:
    """
    Four panels for the body->mind layer (roadmap #21-#27):

      (a) The Stage-1 benchmark: action-class distributions under
          'hungry / high-cortisol' vs 'sated / calm'.
      (b) The HPA axis over a day with a midday threat: adrenaline spikes
          instantly, cortisol lags and recovers via negative feedback,
          riding the circadian rhythm.
      (c) Allostatic load and the epigenetic-clock coupling: a calm day vs
          a chronically stressful one.
      (d) EDAR -> thermoregulation -> behaviour: one gene, measurably
          different core temperature and shelter-seeking under heat.
    """
    from .loci import locus_index
    from .npc import random_founder
    from .physiology import (PhysiologicalState, book_allostatic_load_to_clock,
                            circadian_cortisol)

    npc = random_founder("subject", rng)
    hp = npc.hormone_params()

    fig, axes = plt.subplots(1, 4, figsize=(20, 4.8))

    # (a) benchmark distributions ------------------------------------------
    ax = axes[0]
    hungry = PhysiologicalState(glucose=0.12, hydration=0.45, cortisol=1.15,
                                adrenaline=0.25, circadian_phase=13.0)
    sated = PhysiologicalState(glucose=0.80, hydration=0.85, cortisol=0.35,
                               dopamine=0.68, oxytocin=0.66, serotonin=0.6,
                               circadian_phase=13.0)
    dh = hungry.action_distribution(hp)
    ds = sated.action_distribution(hp)
    acts = list(dh)
    x = np.arange(len(acts))
    ax.bar(x - 0.2, [dh[a] for a in acts], 0.4, label="hungry / high-cortisol", color="#c0392b")
    ax.bar(x + 0.2, [ds[a] for a in acts], 0.4, label="sated / calm", color="#2e8b57")
    ax.set_xticks(x, acts, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("P(action class)")
    ax.set_title("(a) State biases behaviour\n(the Stage-1 benchmark)", fontsize=10)
    ax.legend(fontsize=8)

    # (b) HPA over a day ---------------------------------------------------
    ax = axes[1]
    st = PhysiologicalState(circadian_phase=0.0, cortisol=0.35)
    hours, cort, adr, circ = [], [], [], []
    for step in range(48):        # 24 h at 0.5 h resolution
        threat = 1.0 if 24 <= step < 26 else 0.0   # a threat around midday
        st.step(0.5, hp, threat=threat)
        t = step * 0.5
        hours.append(t); cort.append(st.cortisol); adr.append(st.adrenaline)
        circ.append(0.35 * circadian_cortisol(st.circadian_phase, hp.chronotype_shift_h))
    ax.plot(hours, cort, color="#8e44ad", lw=2, label="cortisol")
    ax.plot(hours, adr, color="#e67e22", lw=1.5, label="adrenaline")
    ax.plot(hours, circ, color="#8e44ad", lw=1, ls=":", alpha=0.6, label="circadian drive")
    ax.axvspan(12, 13, color="#c0392b", alpha=0.15)
    ax.text(12.5, ax.get_ylim()[1] * 0.9, "threat", ha="center", fontsize=8, color="#8a2020")
    ax.set_xlabel("hour of day")
    ax.set_ylabel("level")
    ax.set_title("(b) HPA axis: fast adrenaline,\nlagging cortisol, negative feedback", fontsize=10)
    ax.legend(fontsize=8, loc="upper left")

    # (c) allostatic load --------------------------------------------------
    ax = axes[2]
    for label, stressor, colour in [("calm day", 0.0, "#2e8b57"),
                                    ("chronic stress", 1.5, "#c0392b")]:
        s = PhysiologicalState(circadian_phase=8.0)
        load = [0.0]
        for _ in range(72):
            s.step(1.0, hp, stressor=stressor)
            load.append(s.allostatic_load)
        ax.plot(range(len(load)), load, color=colour, lw=2, label=label)
    ax.set_xlabel("hours under load")
    ax.set_ylabel("allostatic load")
    ax.set_title("(c) Allostatic load accumulates\nunder chronic stress (-> clock, #24)", fontsize=10)
    ax.legend(fontsize=8, loc="upper left")

    # (d) EDAR pathway -----------------------------------------------------
    ax = axes[3]
    edar = locus_index("EDAR")
    twin = random_founder("twin", rng)
    cores = {}
    shelters = {}
    for allele, lbl in [(0, "EDAR absent"), (1, "EDAR present")]:
        twin.genome.haplotypes[:, edar] = allele
        twin.invalidate()
        tp = twin.hormone_params()
        s = twin.physiological_state(phase_h=13.0)
        s.sleep_pressure = 0.10
        traj = [s.core_temp]
        for _ in range(6):
            s.step(1.0, tp, ambient_heat=0.4)
            traj.append(s.core_temp)
        cores[lbl] = traj
        d = s.action_distribution(tp)
        shelters[lbl] = d["rest"] + d["withdraw"]
    ax.plot(cores["EDAR absent"], color="#c0392b", lw=2,
            label=f"EDAR absent (shelter {shelters['EDAR absent']:.2f})")
    ax.plot(cores["EDAR present"], color="#2e8b57", lw=2,
            label=f"EDAR present (shelter {shelters['EDAR present']:.2f})")
    ax.set_xlabel("hours in heat")
    ax.set_ylabel("core temperature (deviation)")
    ax.set_title("(d) One gene reaches behaviour:\nEDAR -> sweat glands -> heat -> action", fontsize=10)
    ax.legend(fontsize=8, loc="lower right")

    fig.suptitle("Body -> mind signal layer (roadmap #21-#27): physiological state biases "
                 "the action distribution fed to the LLM",
                 fontsize=12, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return _save(fig, out_path)


def plot_recombination_haldane(rng: np.random.Generator, out_path: str,
                               n_meioses: int = 4000, n_pairs: int = 45) -> str:
    """
    Observed recombination fraction between locus pairs versus Haldane's
    map function. Every point is measured by actually running meiosis on
    a fully heterozygous test individual; the curve is analytic.

    Points hugging the curve mean linkage is emerging from the geometry of
    the centimorgan map rather than from any hand-tuned correlation. The
    saturation at r = 0.5 is free assortment: beyond ~150 cM, two loci on
    the same chromosome are inherited as independently as two loci on
    different chromosomes.
    """
    from .validation import empirical_recombination_fraction

    same_chrom_pairs: List[Tuple[int, int]] = []
    for _ in range(4000):
        i, j = rng.integers(0, N_LOCI, 2)
        if i != j and CHROM[i] == CHROM[j]:
            same_chrom_pairs.append((int(i), int(j)))
    # spread the sample across the whole cM range
    same_chrom_pairs.sort(key=lambda p: abs(CM_POS[p[0]] - CM_POS[p[1]]))
    step = max(1, len(same_chrom_pairs) // n_pairs)
    picked = same_chrom_pairs[::step][:n_pairs]

    d_obs, r_obs = [], []
    for i, j in picked:
        d_obs.append(abs(CM_POS[i] - CM_POS[j]))
        r_obs.append(empirical_recombination_fraction(i, j, n_meioses, rng))

    xs = np.linspace(0, max(d_obs) * 1.02, 300)
    ys = [haldane_recombination_fraction(x) for x in xs]

    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.plot(xs, ys, color="#111111", lw=2,
            label=r"Haldane:  $r = (1-e^{-2d})/2$")
    ax.scatter(d_obs, r_obs, s=26, color="#c0392b", zorder=3, alpha=0.8,
               label=f"simulated meiosis ({n_meioses} gametes/pair)")
    ax.axhline(0.5, color="grey", ls=":", lw=1, label="free assortment (r = 0.5)")
    ax.set_xlabel("genetic distance between loci (cM)")
    ax.set_ylabel("recombination fraction  r")
    ax.set_ylim(0, 0.58)
    ax.set_title("Linkage emerges from the map, not from a fitted parameter",
                 fontsize=12, fontweight="bold")
    ax.legend(fontsize=9, loc="lower right")
    return _save(fig, out_path)


# ----------------------------------------------------------------------

def plot_grn_perturbation(out_path: str, hub: str = "RUNX2",
                          n: int = 400, seed: int = 20240613) -> str:
    """
    The gene-regulatory network (#8) benchmark, made visual.

    Left: knock out one hub's activity and measure the mean liability shift
    across a founder cohort. Direct-weight traits (dark) collapse because the
    hub's own expression is scaled; UNRELATED traits (accent) move too --
    that is the network talking, not direct pleiotropy. The roadmap asks for
    >= 3 unrelated traits to shift; the accent bars are them.

    Right: the hub's coherent program -- the developmental module it drives
    with a consistent sign, which is why the left panel's trans shifts point
    the same way instead of scattering.
    """
    from .grn import NETWORK
    from .loci import LOCUS_BY_SYMBOL
    from .npc import random_founder

    direct = set(LOCUS_BY_SYMBOL[hub].weights)
    traits = [t for t, a in ARCHITECTURE.items()
              if a.spec.kind.value == "continuous"]

    rng = np.random.default_rng(seed)
    acc = {t: [] for t in traits}
    for i in range(n):
        npc = random_founder(f"g{i}", rng)
        b = {t: npc.liability(t) for t in traits}
        npc.perturb_gene(hub, 0.0)
        for t in traits:
            acc[t].append(npc.liability(t) - b[t])

    shift = {t: float(np.mean(acc[t])) for t in traits}
    shown = sorted((t for t in traits if abs(shift[t]) > 0.02),
                   key=lambda t: shift[t])
    vals = [shift[t] for t in shown]
    colors = ["#1f2d3d" if t in direct else "#e67e22" for t in shown]

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13, 6),
                                   gridspec_kw={"width_ratios": [3, 2]})

    axL.barh(range(len(shown)), vals, color=colors)
    axL.set_yticks(range(len(shown)), shown, fontsize=9)
    axL.axvline(0, color="grey", lw=0.8)
    axL.set_xlabel("mean liability shift under knockout (SD units)")
    axL.set_title(f"{hub} knockout -> a coherent syndrome",
                  fontsize=12, fontweight="bold")
    from matplotlib.patches import Patch
    axL.legend(handles=[Patch(color="#1f2d3d", label=f"{hub} direct weight"),
                        Patch(color="#e67e22", label="trans (via network)")],
               fontsize=9, loc="lower right")

    edges = NETWORK.targets_of(hub)[:14]
    esym = [s for s, _ in edges][::-1]
    ew = [w for _, w in edges][::-1]
    axR.barh(range(len(esym)), ew,
             color=["#8e44ad" if LOCUS_BY_SYMBOL[s].is_core else "#b8a9c9"
                    for s in esym])
    axR.set_yticks(range(len(esym)), esym, fontsize=8)
    axR.axvline(0, color="grey", lw=0.8)
    axR.set_xlabel("trans-regulatory edge weight")
    axR.set_title(f"{hub}'s downstream program (top edges)",
                  fontsize=12, fontweight="bold")

    fig.suptitle("Omnigenic layer: one regulator, a whole program (roadmap #8)",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()
    return _save(fig, out_path)


# ----------------------------------------------------------------------

def plot_sex_linked_inheritance(out_path: str, n: int = 30000,
                                seed: int = 20240721) -> str:
    """
    Sex chromosomes (#2): three mechanisms, each validated against real
    epidemiology.

    (a) Hemizygosity. Red-green colour blindness at ~q in males but ~q^2 in
        females -- the reason X-linked recessives are a "male" phenomenon.
    (b) X-inactivation (Lyon 1961). G6PD activity is all-or-nothing in
        hemizygous males but INTERMEDIATE in carrier females, who are cellular
        mosaics -- the quantitative fingerprint of Lyonisation.
    (c) Sex-limited expression. The androgen-receptor baldness allele
        manifests as patterned hair loss chiefly in males (androgen-gated).
    """
    from .sexchrom import (X_LOCI, X_LOCUS_INDEX, sample_founder_sex_chromosomes,
                           x_linked_prevalence)

    rng = np.random.default_rng(seed)
    kar = [sample_founder_sex_chromosomes(rng, "male" if rng.random() < 0.5
                                          else "female") for _ in range(n)]
    males = [k for k in kar if k.sex == "male"]
    females = [k for k in kar if k.sex == "female"]

    fig, (axA, axB, axC) = plt.subplots(1, 3, figsize=(15, 5))

    # (a) colour blindness
    q = X_LOCI[X_LOCUS_INDEX["color_vision"]].risk_freq
    mp, fp = x_linked_prevalence(kar, "color_vision")
    axA.bar(["male", "female"], [mp * 100, fp * 100],
            color=["#2c7fb8", "#c51b8a"])
    axA.axhline(q * 100, ls="--", color="#2c7fb8", lw=1, label=f"q = {q:.2f} (male expect)")
    axA.axhline(q * q * 100, ls="--", color="#c51b8a", lw=1,
                label=f"q\u00b2 = {q*q:.4f} (female expect)")
    for i, v in enumerate([mp, fp]):
        axA.text(i, v * 100, f" {v*100:.2f}%", ha="center", va="bottom", fontsize=10)
    axA.set_ylabel("prevalence (%)")
    axA.set_title("(a) Hemizygosity:\nred-green colour blindness", fontweight="bold")
    axA.legend(fontsize=8)

    # (b) G6PD mosaic
    gi = X_LOCUS_INDEX["g6pd"]
    male_act = [k.g6pd_activity() for k in males]
    carriers = [k.g6pd_activity() for k in females
                if k.x_maternal[gi] + k.x_paternal[gi] == 1]
    bins = np.linspace(0, 1.05, 30)
    axB.hist(male_act, bins=bins, alpha=0.6, color="#2c7fb8",
             label="males (all-or-nothing)", density=True)
    axB.hist(carriers, bins=bins, alpha=0.6, color="#c51b8a",
             label="carrier females (mosaic)", density=True)
    axB.set_xlabel("relative G6PD activity")
    axB.set_ylabel("density")
    axB.set_title("(b) X-inactivation (Lyon 1961):\ncarriers are intermediate",
                  fontweight="bold")
    axB.legend(fontsize=8)

    # (c) sex-limited baldness
    bm = np.mean([k.manifests_baldness() for k in males]) * 100
    bf = np.mean([k.manifests_baldness() for k in females]) * 100
    axC.bar(["male", "female"], [bm, bf], color=["#2c7fb8", "#c51b8a"])
    for i, v in enumerate([bm, bf]):
        axC.text(i, v, f" {v:.1f}%", ha="center", va="bottom", fontsize=10)
    axC.set_ylabel("manifesting androgenetic alopecia (%)")
    axC.set_title("(c) Sex-limited expression:\nAR / male-pattern baldness",
                  fontweight="bold")

    fig.suptitle("Sex chromosomes: X-linked, mosaic and sex-limited inheritance "
                 "(roadmap #2)", fontsize=13, fontweight="bold")
    fig.tight_layout()
    return _save(fig, out_path)


# ----------------------------------------------------------------------

def plot_mito_inheritance(out_path: str, seed: int = 20240724) -> str:
    """
    Mitochondrial inheritance (#3): three mechanisms.

    (a) THRESHOLD. OXPHOS capacity is flat while wild-type mitochondria
        complement the defect, then collapses past ~70% mutant load -- the
        nonlinearity that lets one carrier be healthy and a higher-load sibling
        ill (Rossignol 2003).
    (b) BOTTLENECK. Offspring of a 50%-heteroplasmy mother scatter widely, with
        variance h(1-h)/N_e; the observed histogram matches the closed form.
    (c) SEGREGATION. Followed across generations the bottleneck drives lineages
        toward fixation (0 or 1) -- why heteroplasmy rarely lingers at 50%.
    """
    from .mito import (MITO_BOTTLENECK_N, OXPHOS_THRESHOLD, MitoGenome,
                       oxphos_capacity)

    rng = np.random.default_rng(seed)
    fig, (axA, axB, axC) = plt.subplots(1, 3, figsize=(15, 5))

    # (a) threshold
    hs = np.linspace(0, 1, 200)
    axA.plot(hs, [oxphos_capacity(h) for h in hs], color="#b2182b", lw=2.5)
    axA.axvline(OXPHOS_THRESHOLD, ls="--", color="grey", lw=1,
                label=f"threshold ~{OXPHOS_THRESHOLD:.0%}")
    axA.set_xlabel("pathogenic mtDNA heteroplasmy")
    axA.set_ylabel("relative OXPHOS capacity")
    axA.set_title("(a) Threshold effect\n(Rossignol 2003)", fontweight="bold")
    axA.legend(fontsize=9)

    # (b) bottleneck, single generation from a 0.5 mother
    h0 = 0.5
    kids = np.array([MitoGenome("H", h0).transmit(rng).heteroplasmy
                     for _ in range(20000)])
    axB.hist(kids, bins=np.arange(-0.5, MITO_BOTTLENECK_N + 1.5) / MITO_BOTTLENECK_N,
             density=True, color="#2166ac", alpha=0.7, label="offspring (observed)")
    sd = np.sqrt(h0 * (1 - h0) / MITO_BOTTLENECK_N)
    xs = np.linspace(0, 1, 300)
    axB.plot(xs, np.exp(-0.5 * ((xs - h0) / sd) ** 2) / (sd * np.sqrt(2 * np.pi)),
             color="#b2182b", lw=2,
             label=f"closed form\nvar = h(1-h)/{MITO_BOTTLENECK_N}")
    axB.axvline(h0, ls=":", color="grey", lw=1, label="mother = 0.50")
    axB.set_xlabel("offspring heteroplasmy")
    axB.set_ylabel("density")
    axB.set_title(f"(b) Bottleneck (N_e = {MITO_BOTTLENECK_N})\n"
                  "mean preserved, wide scatter", fontweight="bold")
    axB.legend(fontsize=8)

    # (c) segregation to fixation across generations
    for _ in range(25):
        traj, m = [0.5], MitoGenome("H", 0.5)
        for _ in range(60):
            m = m.transmit(rng)
            traj.append(m.heteroplasmy)
        axC.plot(traj, lw=0.8, alpha=0.6)
    axC.axhline(0, color="k", lw=0.5); axC.axhline(1, color="k", lw=0.5)
    axC.set_xlabel("generations down a maternal line")
    axC.set_ylabel("heteroplasmy")
    axC.set_ylim(-0.03, 1.03)
    axC.set_title("(c) Segregation:\ndrift toward fixation", fontweight="bold")

    fig.suptitle("Mitochondrial inheritance: maternal, threshold and "
                 "bottleneck (roadmap #3)", fontsize=13, fontweight="bold")
    fig.tight_layout()
    return _save(fig, out_path)


def plot_imprinting(out_path: str, symbol: str = "IGF2",
                    trait: str = "height_cm", n: int = 4000,
                    seed: int = 20260803) -> str:
    """
    Genomic imprinting (#4): parent-of-origin effects, three ways.

    Left: the reciprocal-heterozygote experiment. Two individuals with the
    IDENTICAL genotype at an imprinted locus -- one carrying the alternate
    allele from its father, one from its mother -- plotted against the
    biallelic (non-imprinted) expectation they would share under Mendel.
    The split is the whole phenomenon.

    Middle: the law. Measured gap vs the closed form 2*s*a as silencing
    strength s is swept from 0 (biallelic) to 1 (fully monoallelic). The
    points sit on the line because nothing computes the line.

    Right: what imprinting does to a population. The trait distribution
    with and without imprinting at the same genotypes -- the mean is
    unmoved (IGF2 is purely additive, so the algebra predicts no shift)
    while the variance rises. Same lesson as the epigenome and GRN layers:
    these mechanisms move variance, not the average.
    """
    from .genome import Genome
    from .imprint import (IMPRINTED, expressed_haplotype_vector,
                          imprint_state, imprint_strength_vector, relax_imprint)
    from .loci import LOCUS_BY_SYMBOL
    from .npc import NPC, random_founder
    from .traits import liability

    _HAPN = {0: "maternal", 1: "paternal"}

    rng = np.random.default_rng(seed)
    arch = ARCHITECTURE[trait]
    spec = IMPRINTED[symbol]
    i = LOCUS_BY_SYMBOL[symbol].index
    idx = arch.idx.tolist()
    a_eff = float(arch.a[idx.index(i)])
    hap = expressed_haplotype_vector()
    tspec = TRAIT_TABLE[trait]

    base = random_founder("base", rng)
    expressed, silenced = spec.expressed_from, 1 - spec.expressed_from

    def _make(alt_on):
        h = base.genome.haplotypes.copy()
        h[alt_on, i] = 1
        h[1 - alt_on, i] = 0
        return NPC(name="x", genome=Genome(h), deviates=base.deviates)

    hi, lo = _make(expressed), _make(silenced)

    fig, (axL, axM, axR) = plt.subplots(1, 3, figsize=(15, 4.6))

    # ---- left: the reciprocal pair -------------------------------------
    def _pheno(npc, strength):
        z = liability(arch, npc.genome.dosage, npc.deviates, npc.expression,
                      imprint_state(npc.genome, strength, hap))
        return tspec.mean + tspec.sd * z

    off = np.zeros(N_LOCI)
    mendel = _pheno(hi, off)                       # identical for both
    vals = [_pheno(lo, imprint_strength_vector()),
            mendel,
            _pheno(hi, imprint_strength_vector())]
    labels = [f"alt from\n{spec.silenced_parent}\n(silenced)",
              "Mendel:\nboth identical\n(biallelic)",
              f"alt from\n{_HAPN[spec.expressed_from]}\n(expressed)"]
    colors = ["#2c6fa8", "#9aa5b1", "#c0504d"]
    axL.bar(range(3), vals, color=colors, width=0.62)
    axL.set_xticks(range(3))
    axL.set_xticklabels(labels, fontsize=8)
    axL.set_ylabel(tspec.unit or trait)
    lo_v, hi_v = min(vals), max(vals)
    pad = max(hi_v - lo_v, 1e-6)
    axL.set_ylim(lo_v - 1.6 * pad, hi_v + 0.8 * pad)
    axL.axhline(mendel, color="#9aa5b1", ls=":", lw=1)
    axL.set_title(f"Same genotype at {symbol} (dosage 1)\ndifferent parent of origin",
                  fontsize=10)
    axL.annotate("", xy=(2, vals[2]), xytext=(0, vals[0]),
                 arrowprops=dict(arrowstyle="<->", color="#333", lw=1.2))
    axL.text(1.0, (vals[0] + vals[2]) / 2, f"  gap = 2sa\n  = {vals[2]-vals[0]:.2f}",
             fontsize=8, va="center")

    # ---- middle: the law ------------------------------------------------
    ss = np.linspace(0.0, 1.0, 11)
    obs, pred = [], []
    for s_scale in ss:
        sv = relax_imprint(s_scale / spec.strength) if spec.strength else off
        sv = np.clip(sv, 0.0, 1.0)
        g = (liability(arch, hi.genome.dosage, hi.deviates, hi.expression,
                       imprint_state(hi.genome, sv, hap))
             - liability(arch, lo.genome.dosage, lo.deviates, lo.expression,
                         imprint_state(lo.genome, sv, hap)))
        obs.append(g)
        pred.append(2.0 * s_scale * a_eff)
    axM.plot(ss, pred, "-", color="#2c6fa8", lw=2,
             label=r"closed form  $2\cdot s\cdot a$")
    axM.plot(ss, obs, "o", color="#c0504d", ms=5, label="simulated")
    axM.set_xlabel("silencing strength $s$")
    axM.set_ylabel("reciprocal gap (liability SD)")
    axM.set_title("The law\n$s=0$ biallelic  ...  $s=1$ monoallelic", fontsize=10)
    axM.legend(fontsize=8, frameon=False)
    axM.grid(alpha=0.25)

    # ---- right: population effect ---------------------------------------
    pop = [random_founder(f"p{k}", rng) for k in range(n)]
    sv = imprint_strength_vector()
    with_i = np.array([tspec.mean + tspec.sd *
                       liability(arch, p.genome.dosage, p.deviates, p.expression,
                                 imprint_state(p.genome, sv, hap)) for p in pop])
    without = np.array([tspec.mean + tspec.sd *
                        liability(arch, p.genome.dosage, p.deviates,
                                  p.expression, None) for p in pop])
    bins = np.linspace(min(with_i.min(), without.min()),
                       max(with_i.max(), without.max()), 60)
    axR.hist(without, bins=bins, color="#9aa5b1", alpha=0.75, label="biallelic")
    axR.hist(with_i, bins=bins, histtype="step", color="#c0504d", lw=1.8,
             label=f"{symbol} imprinted")
    axR.axvline(without.mean(), color="#5a6570", ls="--", lw=1)
    axR.axvline(with_i.mean(), color="#c0504d", ls=":", lw=1.4)
    axR.set_xlabel(tspec.unit or trait)
    axR.set_ylabel("individuals")
    axR.set_title(f"Population, n={n}\n"
                  f"mean {without.mean():.2f} -> {with_i.mean():.2f}   "
                  f"sd {without.std():.3f} -> {with_i.std():.3f}", fontsize=9)
    axR.legend(fontsize=8, frameon=False)

    fig.suptitle(
        f"Genomic imprinting (#4): {symbol} is expressed from the "
        f"{_HAPN[spec.expressed_from]} copy only (DeChiara 1991)", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return _save(fig, out_path)


def plot_canalization(out_path: str, trait: str = "height_cm",
                      n: int = 3000, seed: int = 20260814) -> str:
    """
    Canalization (#14b): the buffer, and what happens when it breaks.

    Left: phenotypic variance as stress rises. Flat below the buffering
    threshold -- that is the buffer holding, and it is exactly why the
    engine's calibrated heritabilities are undisturbed -- then rising once
    stress overwhelms it. The dashed curve is k^2 V_gen + V_env, predicted
    from the BASELINE decomposition alone.

    Middle: the released genetic fraction against its closed form
    h2(k) = k^2 h2_0 / (k^2 h2_0 + 1 - h2_0).

    Right: the two distributions. Same genotypes, same environmental draws,
    same mean -- a wider spread. Cryptic variation made visible, which is
    Waddington's claim in one picture.
    """
    from .canalize import (CANALIZATION_THRESHOLD, canalization_factor,
                           expected_heritability)
    from .npc import random_founder
    from .traits import liability

    rng = np.random.default_rng(seed)
    arch = ARCHITECTURE[trait]
    tspec = TRAIT_TABLE[trait]

    pop = [random_founder(f"c{i}", rng) for i in range(n)]
    imp = [p.imprint_state() for p in pop]

    def _z(k):
        return np.array([liability(arch, p.genome.dosage, p.deviates,
                                   p.expression, m, k)
                         for p, m in zip(pop, imp)])

    z0 = _z(1.0)
    genetic = None
    stresses = np.linspace(0.0, 3.0, 25)
    obs_var, pred_var, obs_h2, pred_h2 = [], [], [], []
    for s in stresses:
        k = canalization_factor(s, trait)
        z = _z(k)
        if genetic is None and k > 1.0:
            genetic = (z - z0) / (k - 1.0)
    v_gen = float(genetic.var())
    v_env = float(z0.var()) - v_gen
    h2_0 = v_gen / float(z0.var())

    for s in stresses:
        k = canalization_factor(s, trait)
        z = _z(k)
        obs_var.append(float(z.var()))
        pred_var.append(k * k * v_gen + v_env)
        obs_h2.append((k * k * v_gen) / float(z.var()))
        pred_h2.append(expected_heritability(h2_0, k))

    fig, (axL, axM, axR) = plt.subplots(1, 3, figsize=(15, 4.6))

    axL.plot(stresses, obs_var, "o", color="#c0504d", ms=4, label="simulated")
    axL.plot(stresses, pred_var, "--", color="#2c6fa8", lw=2,
             label=r"$k^2 V_{gen} + V_{env}$")
    axL.axvline(CANALIZATION_THRESHOLD, color="#5a6570", ls=":", lw=1.2)
    axL.annotate("buffer holds", xy=(0.35, min(obs_var) + 0.02),
                 fontsize=8, color="#5a6570")
    axL.annotate("buffer breaks\n(cryptic variation released)",
                 xy=(1.65, max(obs_var) * 0.80), fontsize=8, color="#c0504d")
    axL.set_xlabel("developmental stress")
    axL.set_ylabel("phenotypic variance (liability)")
    axL.set_title("Canalization: variance vs stress", fontsize=10)
    axL.legend(fontsize=8, frameon=False, loc="upper left")
    axL.grid(alpha=0.25)

    axM.plot(stresses, obs_h2, "o", color="#c0504d", ms=4, label="simulated")
    axM.plot(stresses, pred_h2, "--", color="#2c6fa8", lw=2,
             label=r"$k^2h^2_0/(k^2h^2_0+1-h^2_0)$")
    axM.axvline(CANALIZATION_THRESHOLD, color="#5a6570", ls=":", lw=1.2)
    axM.set_xlabel("developmental stress")
    axM.set_ylabel("genetic fraction of variance")
    axM.set_title("Released heritability", fontsize=10)
    axM.legend(fontsize=8, frameon=False, loc="lower right")
    axM.grid(alpha=0.25)

    k_hi = canalization_factor(2.0, trait)
    zc = tspec.mean + tspec.sd * z0
    zs = tspec.mean + tspec.sd * _z(k_hi)
    bins = np.linspace(min(zc.min(), zs.min()), max(zc.max(), zs.max()), 55)
    axR.hist(zc, bins=bins, color="#9aa5b1", alpha=0.75, label="buffered (neutral)")
    axR.hist(zs, bins=bins, histtype="step", color="#c0504d", lw=1.8,
             label="decanalized (stress 2.0)")
    axR.axvline(zc.mean(), color="#5a6570", ls="--", lw=1)
    axR.axvline(zs.mean(), color="#c0504d", ls=":", lw=1.4)
    axR.set_xlabel(tspec.unit or trait)
    axR.set_ylabel("individuals")
    axR.set_title(f"Same genotypes, same mean, wider spread\n"
                  f"mean {zc.mean():.2f} -> {zs.mean():.2f}   "
                  f"sd {zc.std():.3f} -> {zs.std():.3f}", fontsize=9)
    axR.legend(fontsize=8, frameon=False)

    fig.suptitle("Canalization and cryptic genetic variation (#14b) -- "
                 "Waddington 1942; Rutherford & Lindquist 1998", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return _save(fig, out_path)


def plot_inbreeding_depression(out_path: str, n: int = 3000,
                               seed: int = 20260901) -> str:
    """
    Inbreeding depression (#31): the Morton/Crow/Muller regression.

    Left: ln(survival) against pedigree F. The slope IS the number of lethal
    equivalents per gamete. Points are simulated cohorts whose viability comes
    out of their actual load genotypes; the line is the closed form computed
    from the load spectrum, which nothing in that path evaluates.

    Middle: pedigree F is an EXPECTATION over meioses, not a measurement.
    Every full-sib child has pedigree F = 1/4, but realised homozygosity
    scatters around it because meiosis is a lottery (Franklin 1977). The
    spread is the point.

    Right: where depression actually comes from. Rare recessive alleles are
    almost invisible in an outbred population -- they sit heterozygous, hidden
    -- and inbreeding converts them to homozygotes in proportion to F.
    """
    from .inbreeding import SPECTRUM
    from .validation import _INBREEDING_TEMPLATES, _inbred_child

    rng = np.random.default_rng(seed)
    sp = SPECTRUM

    levels, mean_w, spread_F, hom = [], [], [], []
    for label, F in _INBREEDING_TEMPLATES:
        kids = [_inbred_child(label, rng, sp) for _ in range(n)]
        w = np.array([k.viability(sp) for k in kids])
        het = np.array([float(np.mean(k.dosage == 1)) for k in kids])
        h_exp = float(np.mean(2.0 * sp.p * sp.q))
        levels.append(F)
        mean_w.append(float(w.mean()))
        spread_F.append(1.0 - het / h_exp)
        hom.append(np.array([k.n_homozygous for k in kids], dtype=float))

    # Measure realised F against the contemporaneous outbred cohort, as the
    # validation harness does. Three generations of one-way mutation leave a
    # constant excess heterozygosity in EVERY cohort; not subtracting it
    # would shift all five violins down by ~0.026 and make the identity line
    # look biased when it is not.
    baseline = float(spread_F[0].mean())
    spread_F = [arr - baseline for arr in spread_F]

    log_s = np.log(np.array(mean_w) / mean_w[0])
    F = np.array(levels)
    slope, intercept = np.polyfit(F, np.log(np.array(mean_w)), 1)
    B_obs, B_exp = -slope, sp.lethal_equivalents

    fig, (axL, axM, axR) = plt.subplots(1, 3, figsize=(15, 4.6))

    grid = np.linspace(0, 0.27, 60)
    axL.plot(grid, -B_exp * grid, "--", color="#2c6fa8", lw=2,
             label=f"closed form  $-BF$, B = {B_exp:.3f}")
    axL.plot(F, log_s, "o", color="#c0504d", ms=7,
             label=f"simulated cohorts (n={n} each)")
    for x, y, lab in zip(F, log_s, ["outbred", "half 1st cous.", "1st cousins",
                                    "double 1st cous.", "full sibs"]):
        axL.annotate(lab, xy=(x, y), xytext=(9, 7),
                     textcoords="offset points", fontsize=7.5, color="#5a6570")
    axL.set_xlabel("pedigree inbreeding coefficient  F")
    axL.set_ylabel(r"$\ln S(F) - \ln S_0$")
    axL.set_title(f"Lethal equivalents recovered: B = {B_obs:.3f}\n"
                  f"(closed form {B_exp:.3f})", fontsize=10)
    axL.legend(fontsize=8, frameon=False, loc="lower left")
    axL.grid(alpha=0.25)

    parts = axM.violinplot(spread_F, positions=F, widths=0.035,
                           showmeans=True, showextrema=False)
    for body in parts["bodies"]:
        body.set_facecolor("#9aa5b1")
        body.set_alpha(0.7)
    axM.plot([0, 0.25], [0, 0.25], "--", color="#2c6fa8", lw=1.6,
             label="realised = pedigree")
    axM.set_xlabel("pedigree F")
    axM.set_ylabel("realised F (excess homozygosity)")
    axM.set_title("Pedigree F is an expectation;\nrealised F is a measurement",
                  fontsize=10)
    axM.legend(fontsize=8, frameon=False, loc="upper left")
    axM.grid(alpha=0.25)

    bins = np.arange(0, max(h.max() for h in hom) + 2) - 0.5
    for arr, F_lab, colour in ((hom[0], "outbred (F = 0)", "#9aa5b1"),
                               (hom[-1], "full-sib child (F = 1/4)", "#c0504d")):
        axR.hist(arr, bins=bins, alpha=0.65, color=colour,
                 label=f"{F_lab}\nmean {arr.mean():.2f} loci")
    axR.set_xlabel("load loci homozygous for the deleterious allele")
    axR.set_ylabel("individuals")
    axR.set_title("Inbreeding exposes what heterozygosity hid", fontsize=10)
    axR.legend(fontsize=8, frameon=False)

    fig.suptitle("Inbreeding depression (#31) -- Morton, Crow & Muller 1956; "
                 f"calibrated to {B_exp:.1f} lethal equivalents "
                 "(Charlesworth & Willis 2009)", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return _save(fig, out_path)
