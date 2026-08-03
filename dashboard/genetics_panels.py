"""
Genetics tab: population-genetic distributions.
===============================================

Separate from `panels.py` because these answer a different question. The
figures in `panels.py` are mostly *time series* built from the history buffer
-- how the population changed. These are *distributions of the current frame*
-- the shape of the population right now, read straight off the living NPCs.

Each one surfaces a mechanism the engine models but the dashboard never showed.
Between them they cover the full stack: allele frequencies (drift), individual
heterozygosity (inbreeding), phenotype spread (the genotype->phenotype map),
age structure (demography), the epigenetic clock (#17), mitochondrial lineages
(#3), X-linked hemizygosity (#2), genomic imprinting (#4) and mutational load
(#12).

All of them degrade to a labelled empty panel rather than raising when the
relevant layer is inactive or the population has gone extinct.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np
import plotly.graph_objects as go

from simulation import metrics as M

from .panels import (ACCENT, CAT, CRIT, FEMALE, GRID, INK, INK2, MALE, MUTED,
                     SURFACE, WARN, _style)
from health_engine.traits import TRAIT_TABLE


def _empty(fig: go.Figure, title: str, height: int,
           msg: str = "no living population") -> go.Figure:
    fig.add_annotation(text=msg, showarrow=False,
                       font=dict(color=MUTED, size=12))
    fig = _style(fig, title, height=height)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


# ---------------------------------------------------------------------
# Allele frequencies and diversity
# ---------------------------------------------------------------------

def allele_spectrum_figure(world) -> go.Figure:
    """
    The site-frequency spectrum: how many loci sit at each alternate-allele
    frequency. This is drift made visible. A young population is humped in the
    middle; as drift proceeds mass piles up at the 0 and 1 edges as loci are
    lost or fixed, and that erosion of the middle IS the loss of heritable
    variation the diversity line reports as a single number.
    """
    fig = go.Figure()
    if not world.living:
        return _empty(fig, "Allele-frequency spectrum", 240)
    dos = np.array([n.genome.dosage for n in world.living], dtype=float)
    p = dos.mean(axis=0) / 2.0
    fixed = int(np.sum(p >= 0.999))
    lost = int(np.sum(p <= 0.001))
    fig.add_trace(go.Histogram(
        x=p, nbinsx=26, marker_color=CAT[0],
        marker_line=dict(width=0.5, color=SURFACE),
        hovertemplate="freq %{x:.2f}<br>%{y} loci<extra></extra>"))
    _style(fig, f"Allele-frequency spectrum — {lost} lost, {fixed} fixed",
           height=240)
    fig.update_xaxes(title="alternate-allele frequency", range=[0, 1])
    fig.update_yaxes(title="loci")
    return fig


def heterozygosity_hist_figure(world) -> go.Figure:
    """
    Per-individual heterozygosity. The population mean is the diversity line;
    this is its spread, and the left tail is where inbreeding shows up first --
    a child of related parents carries long runs of homozygosity before the
    population average has moved at all.
    """
    fig = go.Figure()
    if not world.living:
        return _empty(fig, "Individual heterozygosity", 240)
    h = np.array([n.heterozygosity() for n in world.living])
    fig.add_trace(go.Histogram(
        x=h, nbinsx=22, marker_color=CAT[1],
        marker_line=dict(width=0.5, color=SURFACE),
        hovertemplate="H %{x:.3f}<br>%{y} people<extra></extra>"))
    fig.add_vline(x=float(h.mean()), line=dict(color=ACCENT, width=1.5, dash="dot"),
                  annotation_text=f"mean {h.mean():.3f}",
                  annotation_font=dict(color=ACCENT, size=9))
    _style(fig, "Individual heterozygosity", height=240)
    fig.update_xaxes(title="fraction of heterozygous loci")
    fig.update_yaxes(title="people")
    return fig


def trait_distribution_figure(world, trait: str = "height_cm") -> go.Figure:
    """
    A phenotype distribution, split by sex. Quantitative traits should be
    approximately normal -- the central-limit consequence of summing many small
    allele effects -- so seeing that emerge is a check on the
    genotype->phenotype map, not decoration.
    """
    fig = go.Figure()
    if not world.living:
        return _empty(fig, f"{trait} distribution", 240)
    spec = TRAIT_TABLE[trait]
    for sex, colour in (("female", FEMALE), ("male", MALE)):
        vals = [n.phenotype()[trait] for n in world.living if n.sex == sex]
        if vals:
            fig.add_trace(go.Histogram(
                x=vals, name=sex, marker_color=colour, opacity=0.62, nbinsx=20,
                hovertemplate=sex + "<br>%{x:.1f}<br>%{y} people<extra></extra>"))
    fig.update_layout(barmode="overlay")
    _style(fig, f"{trait} distribution by sex", height=240, legend=True)
    fig.update_xaxes(title=spec.unit or trait)
    fig.update_yaxes(title="people")
    return fig


# ---------------------------------------------------------------------
# Demography and ageing
# ---------------------------------------------------------------------

def age_pyramid_figure(world) -> go.Figure:
    """
    The classic population pyramid. Its shape reads the demography directly: a
    broad base means a growing population, a waist means a past crash still
    working its way up through the age classes.
    """
    fig = go.Figure()
    if not world.living:
        return _empty(fig, "Age structure", 260)
    labels, f, m = M.age_pyramid(world.living, bin_width=10, max_age=100)
    fig.add_trace(go.Bar(y=labels, x=-f, orientation="h", name="female",
                         marker_color=FEMALE, customdata=f,
                         hovertemplate="%{y}<br>%{customdata} female<extra></extra>"))
    fig.add_trace(go.Bar(y=labels, x=m, orientation="h", name="male",
                         marker_color=MALE,
                         hovertemplate="%{y}<br>%{x} male<extra></extra>"))
    fig.update_layout(barmode="overlay", bargap=0.12)
    _style(fig, "Age structure", height=260, legend=True)
    top = max(int(max(f.max(), m.max())), 1)
    stepv = max(1, top // 3)
    ticks = list(range(-top, top + 1, stepv))
    fig.update_xaxes(title="people", range=[-top - 1, top + 1],
                     tickvals=ticks, ticktext=[str(abs(v)) for v in ticks])
    return fig


def epigenetic_age_figure(world) -> go.Figure:
    """
    Epigenetic age acceleration (Horvath 2013): the gap between the methylation
    clock and the calendar. Positive is ageing fast. Chronic stress and illness
    push this right, and because it feeds back into mortality, a rightward
    drift here precedes a rise in deaths.
    """
    fig = go.Figure()
    if not world.living:
        return _empty(fig, "Epigenetic age acceleration", 240)
    acc = np.array([n.epigenetic_age_acceleration for n in world.living])
    fig.add_trace(go.Histogram(
        x=acc, nbinsx=24, marker_color=WARN,
        marker_line=dict(width=0.5, color=SURFACE),
        hovertemplate="%{x:+.1f} y<br>%{y} people<extra></extra>"))
    fig.add_vline(x=0.0, line=dict(color=MUTED, width=1),
                  annotation_text="on schedule",
                  annotation_font=dict(color=MUTED, size=9))
    _style(fig, f"Epigenetic age acceleration (mean {acc.mean():+.1f} y)",
           height=240)
    fig.update_xaxes(title="epigenetic − chronological age (years)")
    fig.update_yaxes(title="people")
    return fig


# ---------------------------------------------------------------------
# The parallel inheritance layers
# ---------------------------------------------------------------------

def mito_haplogroup_figure(world) -> go.Figure:
    """
    Maternal haplogroups (#3). mtDNA passes only mother -> child, so these
    counts are strict female-line descent: a haplogroup vanishes the moment its
    last female carrier fails to have a daughter, which is why mitochondrial
    lineages are lost far faster than autosomal ancestry.
    """
    fig = go.Figure()
    carriers = [n for n in world.living if n.mito is not None]
    if not carriers:
        return _empty(fig, "Maternal haplogroups (mtDNA)", 240,
                      "mitochondrial layer inactive")
    counts: Dict[str, int] = {}
    for n in carriers:
        counts[n.mito.haplogroup] = counts.get(n.mito.haplogroup, 0) + 1
    keys = sorted(counts, key=lambda k: -counts[k])
    fig.add_trace(go.Bar(
        x=keys, y=[counts[k] for k in keys],
        marker_color=[CAT[i % len(CAT)] for i in range(len(keys))],
        text=[counts[k] for k in keys], textposition="outside",
        textfont=dict(color=INK2, size=10),
        hovertemplate="haplogroup %{x}<br>%{y} people<extra></extra>"))
    _style(fig, f"Maternal haplogroups — {len(keys)} surviving female lines",
           height=240)
    fig.update_yaxes(title="people", rangemode="tozero")
    return fig


def sex_linked_figure(world) -> go.Figure:
    """
    The hemizygosity signature (#2). X-linked recessives appear at ~q in males
    but ~q^2 in females, so the male bars should tower over the female ones.
    Nothing computes that ratio -- it falls out of males carrying a single X.
    """
    fig = go.Figure()
    people = [n for n in world.living if n.sex_chromosomes is not None]
    if not people:
        return _empty(fig, "X-linked conditions by sex", 240,
                      "sex-chromosome layer inactive")
    cats = ["colour-blind", "G6PD deficient", "balding"]
    series = {}
    for sex in ("female", "male"):
        grp = [n for n in people if n.sex == sex]
        d = max(len(grp), 1)
        ph = [n.x_linked_phenotype() for n in grp]
        series[sex] = [
            100.0 * sum(1 for p in ph if p.get("color_vision") != "normal") / d,
            100.0 * sum(1 for p in ph
                        if float(p.get("g6pd_activity", 1.0)) < 0.4) / d,
            100.0 * sum(1 for p in ph if p.get("pattern_baldness")) / d,
        ]
    fig.add_trace(go.Bar(x=cats, y=series["female"], name="female",
                         marker_color=FEMALE,
                         hovertemplate="female<br>%{x}<br>%{y:.1f}%<extra></extra>"))
    fig.add_trace(go.Bar(x=cats, y=series["male"], name="male",
                         marker_color=MALE,
                         hovertemplate="male<br>%{x}<br>%{y:.1f}%<extra></extra>"))
    fig.update_layout(barmode="group")
    _style(fig, "X-linked & sex-limited prevalence", height=240, legend=True)
    fig.update_yaxes(title="% of that sex", rangemode="tozero")
    return fig


def imprinting_figure(world) -> go.Figure:
    """
    Genomic imprinting (#4) in the living population. IGF2 is transcribed from
    the paternal copy only, so people are grouped by which allele they actually
    express -- and the heterozygotes split into two classes whose phenotypes
    differ despite identical genotypes. That split is the whole mechanism,
    shown on real inhabitants rather than a constructed pair.
    """
    fig = go.Figure()
    if not world.living:
        return _empty(fig, "IGF2 parent-of-origin", 250)
    try:
        from health_engine.imprint import parent_of_origin_report
    except ImportError:
        return _empty(fig, "IGF2 parent-of-origin", 250, "imprint layer absent")

    labels = ["ref / ref", "het — alt from<br>mother (silenced)",
              "het — alt from<br>father (expressed)", "alt / alt"]
    counts = [0, 0, 0, 0]
    for n in world.living:
        r = parent_of_origin_report(n.genome, "IGF2")
        if r["dosage"] == 0:
            counts[0] += 1
        elif r["dosage"] == 2:
            counts[3] += 1
        elif r["expressed_allele"] == 1:
            counts[2] += 1
        else:
            counts[1] += 1
    fig.add_trace(go.Bar(
        x=labels, y=counts, marker_color=[MUTED, CAT[0], CAT[5], MUTED],
        text=counts, textposition="outside",
        textfont=dict(color=INK2, size=10),
        hovertemplate="%{x}<br>%{y} people<extra></extra>"))
    _style(fig, "IGF2 imprinting — the two heterozygote classes differ",
           height=250)
    fig.update_yaxes(title="people", rangemode="tozero")
    fig.update_xaxes(tickfont=dict(size=9))
    return fig


def mutation_load_figure(world) -> go.Figure:
    """
    De novo mutations per individual by generation (#12). Founders carry none
    by construction; every later generation accumulates them at the Kong 2012
    rate, scaled by paternal age. This is the mutational clock ticking.
    """
    fig = go.Figure()
    born = [n for n in world.living if n.generation > 0]
    if not born:
        return _empty(fig, "De novo mutation load", 240,
                      "no post-founder generation yet")
    by_gen: Dict[int, List[float]] = {}
    for n in born:
        by_gen.setdefault(n.generation, []).append(float(n.de_novo_mutations))
    gens = sorted(by_gen)
    means = [float(np.mean(by_gen[g])) for g in gens]
    fig.add_trace(go.Bar(
        x=[f"gen {g}" for g in gens], y=means, marker_color=CAT[2],
        customdata=[len(by_gen[g]) for g in gens],
        text=[f"{m:.2f}" for m in means], textposition="outside",
        textfont=dict(color=INK2, size=10),
        hovertemplate="%{x}<br>%{y:.2f} de novo / person"
                      "<br>n=%{customdata}<extra></extra>"))
    _style(fig, "De novo mutations per individual, by generation", height=240)
    fig.update_yaxes(title="mean de novo count", rangemode="tozero")
    return fig
