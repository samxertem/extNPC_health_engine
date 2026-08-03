"""
Plotly figure builders for the live dashboard.
==============================================

Design follows the dataviz method: dark surface, recessive grid, thin marks,
a legend whenever >=2 series, colour that follows the *entity* (a founder
lineage keeps its colour in the dot-cloud, the family tree AND the bloodlines
chart), and NEVER a dual y-axis -- traits on different scales are indexed to
their generation-0 mean instead.

The categorical slots are the validated dark-mode palette; per-lineage colours
are generated identity hues owned by `simulation.lineage`.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import plotly.graph_objects as go

from simulation import metrics as M
from health_engine.traits import TRAIT_TABLE

# ---- dark palette (validated dataviz defaults, dark steps) ----------------
SURFACE = "#1a1a19"
PLANE = "#0d0d0d"
INK = "#ffffff"
INK2 = "#d3d2c9"
# Lifted from #898781 (~4.7:1 on SURFACE). That scrapes past WCAG AA for body
# text but fails it at the 9-11px sizes this UI actually uses for axis ticks,
# slider marks and secondary labels. #a5a39c is ~6.6:1 -- comfortably AA at
# small sizes, AAA at normal ones -- and nothing here should be less legible
# than that, because every muted string in this dashboard is a data label.
MUTED = "#a5a39c"
GRID = "#2c2c2a"
AXIS = "#4a4a46"

CAT = ["#3987e5", "#199e70", "#c98500", "#008300",
       "#9085e9", "#e66767", "#d55181", "#d95926"]
GOOD = "#0ca30c"
CRIT = "#d03b3b"
WARN = "#c98500"
ACCENT = "#4ea3ff"   # futuristic cyan-blue accent for KPI bars / glows
FEMALE = "#3987e5"   # slot 1 blue
MALE = "#c98500"     # slot 3 yellow-gold (clear from blue under CVD)


def _style(fig: go.Figure, title: str = "", height: int = 260,
           legend: bool = False) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(color=INK2, size=13), x=0.02, y=0.97),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(color=INK2, family='system-ui, "Segoe UI", sans-serif', size=11),
        margin=dict(l=48, r=16, t=34 if title else 12, b=32),
        height=height,
        # Height stays fixed (the grid rows depend on it) but the width must
        # come from the container, or Plotly uses its 700px default and the
        # chart overflows its cell.
        autosize=True,
        showlegend=legend,
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=INK2, size=10),
                    orientation="h", yanchor="bottom", y=1.0, x=0),
        hovermode="closest",
        uirevision="keep",   # preserve zoom/pan across live updates
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=AXIS, linecolor=AXIS,
                     tickfont=dict(color=MUTED, size=10), title_font=dict(color=MUTED, size=11))
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=AXIS, linecolor=AXIS,
                     tickfont=dict(color=MUTED, size=10), title_font=dict(color=MUTED, size=11))
    return fig


# =====================================================================
# The main event: the genetic-PCA dot-cloud
# =====================================================================

def scatter_figure(world, selected: Optional[str] = None) -> go.Figure:
    frame = world.living_frame()
    fig = go.Figure()
    if not frame:
        return _style(fig, "Population — genetic map (PC1 x PC2)", height=520)

    # split by sex so each gets a marker symbol (identity beyond colour)
    for sex, symbol in (("female", "circle"), ("male", "diamond")):
        pts = [f for f in frame if f["sex"] == sex]
        if not pts:
            continue
        fig.add_trace(go.Scatter(
            x=[p["x"] for p in pts], y=[p["y"] for p in pts],
            mode="markers",
            marker=dict(
                size=[8 + 0.10 * p["age"] for p in pts],
                color=[p["color"] for p in pts],
                symbol=symbol,
                line=dict(width=0.6, color="rgba(0,0,0,0.5)"),
                opacity=0.92,
            ),
            customdata=[[p["name"], p["age"], p["lineage"], p["purity"],
                         p["generation"], p["partner"], p["children"],
                         p["height_cm"], p["bmi"], p["conditions"]] for p in pts],
            hovertemplate=(
                "<b>%{customdata[0]}</b> (" + sex + ")<br>"
                "age %{customdata[1]} · gen %{customdata[4]}<br>"
                "lineage %{customdata[2]} · purity %{customdata[3]}<br>"
                "partner %{customdata[5]} · children %{customdata[6]}<br>"
                "height %{customdata[7]}cm · bmi %{customdata[8]}<br>"
                "conditions %{customdata[9]}<extra></extra>"),
            name=sex,
        ))

    if selected:
        sel = next((f for f in frame if f["name"] == selected), None)
        if sel:
            fig.add_trace(go.Scatter(
                x=[sel["x"]], y=[sel["y"]], mode="markers",
                marker=dict(size=22, color="rgba(0,0,0,0)",
                            line=dict(width=2.5, color=INK)),
                hoverinfo="skip", showlegend=False, name="selected"))

    _style(fig, "Population — genetic map (PC1 × PC2), colour = founder lineage",
           height=520, legend=True)
    fig.update_xaxes(title="genetic PC1", showticklabels=False)
    fig.update_yaxes(title="genetic PC2", showticklabels=False)
    return fig


# =====================================================================
# Time-series panels
# =====================================================================

def population_figure(cols: Dict[str, List[float]]) -> go.Figure:
    fig = go.Figure()
    if cols:
        t = cols["tick"]
        fig.add_trace(go.Scatter(
            x=t, y=cols["n_alive"], mode="lines",
            line=dict(color=CAT[0], width=2.4, shape="spline", smoothing=0.6),
            fill="tozeroy", fillcolor="rgba(57,135,229,0.15)", name="alive",
            hovertemplate="year %{x}<br>%{y} alive<extra></extra>"))
        _mark_crashes(fig, t, cols["n_alive"])
    return _style(fig, "Population size", height=220)


def _mark_crashes(fig: go.Figure, t, series, drop: float = 0.20) -> None:
    """Annotate years where the series fell by >= `drop` fraction — inline
    alert markers so a crash is visible without reading the numbers."""
    y = np.asarray(series, dtype=float)
    for i in range(1, len(y)):
        if y[i - 1] > 0 and (y[i] - y[i - 1]) / y[i - 1] <= -drop:
            fig.add_trace(go.Scatter(
                x=[t[i]], y=[y[i]], mode="markers",
                marker=dict(symbol="triangle-down", size=11, color=CRIT,
                            line=dict(width=1, color="#fff")),
                hovertemplate=f"year %{{x}} · crash to %{{y}}<extra></extra>",
                showlegend=False))


def births_deaths_figure(cols: Dict[str, List[float]]) -> go.Figure:
    fig = go.Figure()
    if cols:
        t = cols["tick"]
        fig.add_trace(go.Scatter(x=t, y=cols["n_births"], mode="lines",
                                 line=dict(color=GOOD, width=1.9, shape="spline", smoothing=0.6),
                                 name="births",
                                 hovertemplate="year %{x}<br>%{y} births<extra></extra>"))
        fig.add_trace(go.Scatter(x=t, y=cols["n_deaths"], mode="lines",
                                 line=dict(color=CRIT, width=1.9, shape="spline", smoothing=0.6),
                                 name="deaths",
                                 hovertemplate="year %{x}<br>%{y} deaths<extra></extra>"))
    return _style(fig, "Births vs deaths", height=220, legend=True)


def pyramid_figure(world) -> go.Figure:
    labels, f, m = M.age_pyramid(world.living)
    fig = go.Figure()
    fig.add_trace(go.Bar(y=labels, x=[-v for v in f], orientation="h",
                         marker_color=FEMALE, name="female",
                         hovertemplate="%{y}<br>%{customdata} female<extra></extra>",
                         customdata=f))
    fig.add_trace(go.Bar(y=labels, x=list(m), orientation="h",
                         marker_color=MALE, name="male",
                         hovertemplate="%{y}<br>%{x} male<extra></extra>"))
    _style(fig, "Age pyramid", height=300, legend=True)
    fig.update_layout(barmode="relative", bargap=0.12)
    mx = max([1] + list(f) + list(m))
    fig.update_xaxes(range=[-mx - 1, mx + 1],
                     tickvals=[-mx, -mx//2, 0, mx//2, mx],
                     ticktext=[mx, mx//2, 0, mx//2, mx], title="count")
    return fig


def traits_figure(cols: Dict[str, List[float]]) -> go.Figure:
    """
    Trait means as change from their founding value, in phenotypic SD units.

    This used to plot PERCENT change, which is unusable for half these traits.
    Several of them are liability-scale with a population mean near zero
    (insulin_sensitivity, immune_reactivity, neuroticism), so dividing by that
    mean produced swings of +2000% / -1000% from a movement of a hundredth of
    a unit, and the readable traits were flattened against the axis.

    Standardising by each trait's phenotypic SD fixes both problems at once:
    the scale cannot blow up on a near-zero denominator, and a move of 0.2
    means the same thing -- a fifth of a standard deviation -- whether the
    trait is measured in centimetres or in liability units. That also makes
    the chart directly readable against the breeder's equation, where response
    is conventionally quoted in SD.
    """
    fig = go.Figure()
    if cols:
        t = cols["tick"]
        for i, trait in enumerate(M.TRACKED_TRAITS):
            y = np.array(cols[f"trait_{trait}"], dtype=float)
            if y.size == 0:
                continue
            spec = TRAIT_TABLE.get(trait)
            sd = float(getattr(spec, "sd", 1.0) or 1.0)
            delta = (y - y[0]) / sd
            fig.add_trace(go.Scatter(x=t, y=delta, mode="lines",
                                     line=dict(color=CAT[i % len(CAT)], width=1.9,
                                               shape="spline", smoothing=0.6),
                                     name=trait,
                                     hovertemplate=trait +
                                     " %{y:+.3f} SD<extra></extra>"))
        fig.add_hline(y=0.0, line=dict(color=AXIS, width=1))
    _style(fig, "Trait evolution — change from founding mean (SD units)",
           height=260, legend=True)
    fig.update_yaxes(title="Δ (phenotypic SD)")
    return fig


def diversity_figure(cols: Dict[str, List[float]]) -> go.Figure:
    fig = go.Figure()
    if cols:
        t = cols["tick"]
        h = np.asarray(cols["heterozygosity"], dtype=float)
        # threshold band: below 0.33 is the "diversity bleeding out" zone
        fig.add_hrect(y0=0, y1=0.33, line_width=0,
                      fillcolor="rgba(208,59,59,0.10)")
        fig.add_hline(y=0.33, line=dict(color=CRIT, width=1, dash="dot"),
                      annotation_text="drift-loss threshold",
                      annotation_font=dict(color=MUTED, size=9),
                      annotation_position="bottom right")
        fig.add_trace(go.Scatter(x=t, y=h, mode="lines",
                                 line=dict(color=CAT[1], width=2.2,
                                           shape="spline", smoothing=0.6),
                                 name="heterozygosity",
                                 hovertemplate="year %{x}<br>H %{y:.3f}<extra></extra>"))
        rng = [min(0.30, float(h.min()) - 0.01), max(0.42, float(h.max()) + 0.01)]
        fig.update_yaxes(range=rng)
    return _style(fig, "Genetic diversity (mean heterozygosity)", height=220)


def lineage_figure(world) -> go.Figure:
    """Stacked area of living headcount per founder lineage over time — the
    same colours as the dots, so you can read a bloodline's rise and fall."""
    fig = go.Figure()
    hist = world.lineage_history
    if hist:
        t = [r["tick"] for r in world.history]
        founders = world.registry.founders
        for name in founders:
            series = [h.get(name, 0) for h in hist]
            if not any(series):
                continue
            color = world.registry.color_hex({name: 1.0}, alive=True)
            fig.add_trace(go.Scatter(
                x=t, y=series, mode="lines", stackgroup="one",
                line=dict(width=0.5, color=color), fillcolor=color,
                name=name.split("-")[0],
                hovertemplate=name.split("-")[0] + " %{y}<extra></extra>"))
    _style(fig, "Bloodlines over time (dominant-lineage headcount)", height=260,
           legend=False)
    return fig


# =====================================================================
# Family tree
# =====================================================================

def tree_figure(world, name: Optional[str]) -> go.Figure:
    from simulation.pedigree import ego_tree
    fig = go.Figure()
    if not name:
        _style(fig, "Family tree — click an individual", height=340)
        return fig
    nodes, edges = ego_tree(world, name, up=4, down=3)
    if not nodes:
        _style(fig, "Family tree", height=340)
        return fig
    pos = {n["name"]: (n["x"], n["y"]) for n in nodes}

    for u, v in edges:
        if u in pos and v in pos:
            fig.add_trace(go.Scatter(
                x=[pos[u][0], pos[v][0]], y=[pos[u][1], pos[v][1]],
                mode="lines", line=dict(color=AXIS, width=1),
                hoverinfo="skip", showlegend=False))

    fig.add_trace(go.Scatter(
        x=[n["x"] for n in nodes], y=[n["y"] for n in nodes],
        mode="markers+text",
        marker=dict(
            size=[26 if n["is_ego"] else 18 for n in nodes],
            color=[n["color"] for n in nodes],
            symbol=["circle" if n["sex"] == "female" else "diamond" for n in nodes],
            line=dict(width=[2.5 if n["is_ego"] else 1 for n in nodes],
                      color=[INK if n["is_ego"] else "rgba(0,0,0,0.5)" for n in nodes]),
        ),
        text=[n["label"] for n in nodes],
        textposition="bottom center",
        textfont=dict(color=INK2, size=9),
        customdata=[[n["name"], n["age"], n["alive"]] for n in nodes],
        hovertemplate="<b>%{customdata[0]}</b><br>age %{customdata[1]}"
                      "<br>%{customdata[2]}<extra></extra>",
        showlegend=False,
    ))
    _style(fig, f"Family tree of {name.split('-')[0]} "
                "(ego ◯ · ancestors below · descendants above)", height=340)
    # pin explicit (non-degenerate) ranges so a 1-node tree never auto-ranges to NaN
    xs = [n["x"] for n in nodes] or [0.0]
    ys = [n["y"] for n in nodes] or [0.0]
    fig.update_xaxes(range=[min(xs) - 1, max(xs) + 1],
                     showticklabels=False, showgrid=False, zeroline=False)
    fig.update_yaxes(range=[min(ys) - 0.6, max(ys) + 0.6],
                     title="generation", showgrid=False)
    return fig


# =====================================================================
# Session-8 panels: KPI tiles, F_ST, demes, spiral, candlestick, radar
# =====================================================================

def _last(cols: Dict[str, List[float]], key: str, default=0.0):
    v = cols.get(key)
    return v[-1] if v else default


def kpi_data(cols: Dict[str, List[float]], params) -> List[dict]:
    """Values + short glossary for the KPI stat-tile row. `delta` is the change
    over the last 10 recorded years, for a sparkline-free trend arrow."""
    from simulation import GLOSSARY

    def delta(key):
        s = cols.get(key)
        if not s or len(s) < 2:
            return 0.0
        back = s[-11] if len(s) > 11 else s[0]
        return s[-1] - back

    tiles = [
        dict(key="n_alive", label="ALIVE", value=f"{int(_last(cols,'n_alive'))}",
             delta=delta("n_alive"), fmt="int", accent=ACCENT,
             glossary="Living individuals in the world right now."),
        dict(key="max_generation", label="GENERATION",
             value=f"{int(_last(cols,'max_generation'))}", delta=0, fmt="none",
             accent=CAT[4], glossary="Deepest pedigree generation reached."),
        dict(key="n_couples", label="COUPLES", value=f"{int(_last(cols,'n_couples'))}",
             delta=delta("n_couples"), fmt="int", accent=CAT[2],
             glossary=GLOSSARY["n_couples"]["text"]),
        dict(key="heterozygosity", label="DIVERSITY H",
             value=f"{_last(cols,'heterozygosity'):.3f}",
             delta=delta("heterozygosity"), fmt="f3", accent=CAT[1],
             glossary=GLOSSARY["heterozygosity"]["text"]),
        dict(key="fst", label="F_ST", value=f"{_last(cols,'fst'):.3f}",
             delta=delta("fst"), fmt="f3", accent=CAT[6],
             glossary=GLOSSARY["fst"]["text"]),
        dict(key="mean_relatedness", label="KINSHIP",
             value=f"{_last(cols,'mean_relatedness'):.3f}",
             delta=delta("mean_relatedness"), fmt="f3", accent=CAT[5],
             glossary=GLOSSARY["mean_relatedness"]["text"]),
        dict(key="reproductive_skew", label="REPRO SKEW",
             value=f"{_last(cols,'reproductive_skew'):.2f}",
             delta=delta("reproductive_skew"), fmt="f2", accent=CAT[7],
             glossary=GLOSSARY["reproductive_skew"]["text"]),
        dict(key="epi_accel", label="EPI-AGE ACCEL",
             value=f"{_last(cols,'epi_accel'):+.1f}y", delta=delta("epi_accel"),
             fmt="f1", accent=CAT[3], glossary=GLOSSARY["epi_accel"]["text"]),
    ]
    return tiles


def fst_figure(cols: Dict[str, List[float]], n_demes: int) -> go.Figure:
    """F_ST over time — between-deme differentiation, the island-model headline."""
    fig = go.Figure()
    if cols and n_demes > 1:
        t = cols["tick"]
        fig.add_hrect(y0=0.05, y1=0.15, line_width=0,
                      fillcolor="rgba(217,89,54,0.08)")
        fig.add_hline(y=0.05, line=dict(color=MUTED, width=1, dash="dot"),
                      annotation_text="moderate structure",
                      annotation_font=dict(color=MUTED, size=9))
        fig.add_trace(go.Scatter(
            x=t, y=cols["fst"], mode="lines",
            line=dict(color=CAT[6], width=2.4, shape="spline", smoothing=0.6),
            fill="tozeroy", fillcolor="rgba(213,81,129,0.12)", name="F_ST",
            hovertemplate="year %{x}<br>F_ST %{y:.3f}<extra></extra>"))
    else:
        fig.add_annotation(text="single deme — no differentiation to measure<br>"
                                "(raise 'demes' in Controls, then Reset)",
                           showarrow=False, font=dict(color=MUTED, size=12))
    _style(fig, "Population structure  F_ST  =  (H_T − H_S) / H_T   ·  Wright 1931",
           height=240)
    fig.update_yaxes(rangemode="tozero", title="F_ST")
    return fig


def deme_bar_figure(world) -> go.Figure:
    """Column chart: population per deme, labelled with within-deme diversity."""
    demes = world.deme_summary()
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[d["label"] for d in demes],
        y=[d["n"] for d in demes],
        marker=dict(color=[CAT[d["deme"] % len(CAT)] for d in demes],
                    line=dict(width=0)),
        text=[f"H {d['heterozygosity']:.3f}" for d in demes],
        textposition="outside",
        textfont=dict(color=MUTED, size=10),
        hovertemplate="%{x}<br>%{y} people<br>%{text}<extra></extra>",
        showlegend=False))
    _style(fig, "Communities — headcount per deme", height=240)
    fig.update_yaxes(rangemode="tozero", title="people")
    return fig


def spiral_figure(cols: Dict[str, List[float]]) -> go.Figure:
    """A time-spiral: each year is a point winding outward (one loop ≈ 12 yrs),
    coloured and sized by population — a futuristic read of the whole history."""
    fig = go.Figure()
    if cols:
        t = np.asarray(cols["tick"], dtype=float)
        n = np.asarray(cols["n_alive"], dtype=float)
        theta = (t * 30.0) % 360.0                # 12 years per revolution
        r = t                                     # wind outward with time
        fig.add_trace(go.Scatterpolar(
            r=r, theta=theta, mode="markers+lines",
            line=dict(color="rgba(78,163,255,0.35)", width=1),
            marker=dict(size=6 + 8 * n / (n.max() or 1),
                        color=n, colorscale="Viridis", showscale=True,
                        colorbar=dict(title="alive", tickfont=dict(color=MUTED, size=9),
                                      title_font=dict(color=MUTED, size=10),
                                      outlinewidth=0, thickness=10),
                        line=dict(width=0.4, color="rgba(0,0,0,0.4)")),
            customdata=n,
            hovertemplate="year %{r}<br>%{customdata} alive<extra></extra>"))
    _style(fig, "History spiral — population winding through time (1 loop ≈ 12 yrs)",
           height=340)
    fig.update_polars(bgcolor=SURFACE,
                      radialaxis=dict(showticklabels=False, gridcolor=GRID,
                                      linecolor=AXIS),
                      angularaxis=dict(showticklabels=False, gridcolor=GRID,
                                       linecolor=AXIS))
    return fig


def candlestick_figure(cols: Dict[str, List[float]], key: str = "n_alive",
                       title: str = "Population volatility (per-decade OHLC)"
                       ) -> go.Figure:
    """Per-decade candlesticks of a metric: open = first year of the decade,
    close = last, high/low = the decade's extremes. Reads volatility the way a
    price chart does — green decades ended higher than they opened."""
    fig = go.Figure()
    if cols and cols.get(key):
        t = np.asarray(cols["tick"], dtype=float)
        y = np.asarray(cols[key], dtype=float)
        decades: Dict[int, List[float]] = {}
        order: List[int] = []
        for ti, yi in zip(t, y):
            d = int(ti // 10) * 10
            if d not in decades:
                decades[d] = []
                order.append(d)
            decades[d].append(yi)
        o = [decades[d][0] for d in order]
        c = [decades[d][-1] for d in order]
        hi = [max(decades[d]) for d in order]
        lo = [min(decades[d]) for d in order]
        fig.add_trace(go.Candlestick(
            x=[f"{d}s" for d in order], open=o, high=hi, low=lo, close=c,
            increasing=dict(line=dict(color=GOOD), fillcolor=GOOD),
            decreasing=dict(line=dict(color=CRIT), fillcolor=CRIT),
            whiskerwidth=0.4, showlegend=False))
    _style(fig, title, height=260)
    fig.update_layout(xaxis_rangeslider_visible=False)
    return fig


# --- radar / polar ---------------------------------------------------------

_OCEAN = ["openness", "conscientiousness", "extraversion",
          "agreeableness", "neuroticism"]
_BODY = ["height_cm", "bmi", "aerobic_capacity", "insulin_sensitivity",
         "immune_reactivity"]


def _to_score(trait: str, val: float) -> float:
    """Map a phenotype value onto a 0–100 radar scale. OCEAN traits are ~N(0,1)
    liabilities; body traits carry their own units, so each gets a plausible
    display centre/scale. Purely cosmetic normalisation for the radar."""
    centres = {"height_cm": (171, 12), "bmi": (24, 5),
               "aerobic_capacity": (0, 1), "insulin_sensitivity": (0, 1),
               "immune_reactivity": (0, 1)}
    mu, sd = centres.get(trait, (0.0, 1.0))
    z = (val - mu) / (sd or 1.0)
    return float(np.clip(50 + 16 * z, 2, 98))


def _rgba(hex_color: str, a: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{a})"


def _radar(fig, labels, scores, name, color):
    labels = labels + [labels[0]]
    scores = scores + [scores[0]]
    fig.add_trace(go.Scatterpolar(
        r=scores, theta=labels, fill="toself", name=name,
        line=dict(color=color, width=2), fillcolor=_rgba(color, 0.18)))


def population_radar_figure(world) -> go.Figure:
    """Population-mean phenotype fingerprint — OCEAN + body traits on one polar
    axis, so the whole population's 'shape' is legible at a glance."""
    fig = go.Figure()
    living = world.living
    if living:
        phes = [n.phenotype() for n in living]
        labels = [t[:4].upper() for t in _OCEAN] + \
                 ["HGT", "BMI", "AERO", "INS", "IMM"]
        traits = _OCEAN + _BODY
        scores = [float(np.mean([_to_score(t, p[t]) for p in phes]))
                  for t in traits]
        _radar(fig, labels, scores, "population mean", ACCENT)
    _style(fig, "Population phenotype fingerprint (mean, 0–100)", height=340)
    fig.update_polars(bgcolor=SURFACE,
                      radialaxis=dict(range=[0, 100], gridcolor=GRID,
                                      tickfont=dict(color=MUTED, size=8), linecolor=AXIS),
                      angularaxis=dict(gridcolor=GRID, linecolor=AXIS,
                                       tickfont=dict(color=INK2, size=10)))
    return fig


def individual_radar_figure(world, name: Optional[str]) -> go.Figure:
    """One individual's phenotype fingerprint vs the population mean."""
    fig = go.Figure()
    if name and name in world.people:
        traits = _OCEAN + _BODY
        labels = [t[:4].upper() for t in _OCEAN] + ["HGT", "BMI", "AERO", "INS", "IMM"]
        if world.living:                         # population mean (skip if extinct)
            pop = [n.phenotype() for n in world.living]
            mean_scores = [float(np.mean([_to_score(t, p[t]) for p in pop]))
                           for t in traits]
            _radar(fig, labels, mean_scores, "population", MUTED)
        p = world.people[name].phenotype()       # the selected individual, always
        me = [_to_score(t, p[t]) for t in traits]
        _radar(fig, labels, me, name.split("-")[0], ACCENT)
    _style(fig, "Individual vs population fingerprint", height=320, legend=True)
    fig.update_polars(bgcolor=SURFACE,
                      radialaxis=dict(range=[0, 100], gridcolor=GRID,
                                      tickfont=dict(color=MUTED, size=8), linecolor=AXIS),
                      angularaxis=dict(gridcolor=GRID, linecolor=AXIS,
                                       tickfont=dict(color=INK2, size=10)))
    return fig


def relatedness_figure(cols: Dict[str, List[float]]) -> go.Figure:
    """Mean couple relatedness over time — the inbreeding early-warning line."""
    fig = go.Figure()
    if cols:
        t = cols["tick"]
        fig.add_hline(y=0.0625, line=dict(color=MUTED, width=1, dash="dot"),
                      annotation_text="first cousins",
                      annotation_font=dict(color=MUTED, size=9))
        fig.add_trace(go.Scatter(
            x=t, y=cols["mean_relatedness"], mode="lines",
            line=dict(color=CAT[5], width=2.2, shape="spline", smoothing=0.6),
            name="couple kinship",
            hovertemplate="year %{x}<br>r %{y:.3f}<extra></extra>"))
    _style(fig, "Couple kinship (mean genomic relatedness)", height=240)
    fig.update_yaxes(rangemode="tozero")
    return fig


def skew_figure(cols: Dict[str, List[float]]) -> go.Figure:
    """Reproductive skew (Gini of family size) over time."""
    fig = go.Figure()
    if cols:
        t = cols["tick"]
        fig.add_trace(go.Scatter(
            x=t, y=cols["reproductive_skew"], mode="lines",
            line=dict(color=CAT[7], width=2.2, shape="spline", smoothing=0.6),
            fill="tozeroy", fillcolor=_rgba(CAT[7], 0.12), name="skew",
            hovertemplate="year %{x}<br>Gini %{y:.2f}<extra></extra>"))
    _style(fig, "Reproductive skew (Gini of family size)", height=240)
    fig.update_yaxes(range=[0, 1])
    return fig


# =====================================================================
# The world map — an RTS-style spatial view of settlements & people
# =====================================================================

def deme_color(deme_id: int) -> str:
    return CAT[deme_id % len(CAT)]


def map_figure(world, selected: Optional[str] = None) -> go.Figure:
    """
    A top-down strategy-game map:

        * each settlement (deme) is a translucent circular TERRITORY;
        * a settlement MARKER sits at its centre, sized by population;
        * migration ROUTES link settlements, thickness = recent gene flow,
          hover shows the distance (isolation by distance is literally drawn);
        * every living person is a UNIT dot inside their settlement, coloured
          by bloodline, shaped by sex — click one to inspect it.
    """
    from simulation.community import MAP_SIZE

    fig = go.Figure()
    demes = world.map_demes()
    frame = world.living_frame()

    # 1) territories (filled circles, drawn as shapes so they scale with axes)
    for d in demes:
        col = deme_color(d["deme"])
        fig.add_shape(type="circle", xref="x", yref="y",
                      x0=d["x"] - d["radius"], y0=d["y"] - d["radius"],
                      x1=d["x"] + d["radius"], y1=d["y"] + d["radius"],
                      line=dict(color=col, width=1.4),
                      fillcolor=_rgba(col, 0.10), layer="below")

    # 2) migration routes (thickness ∝ flow)
    flows = world.map_flows()
    wmax = max((f["weight"] for f in flows), default=1.0)
    for f in flows:
        fig.add_trace(go.Scatter(
            x=[f["x0"], f["x1"]], y=[f["y0"], f["y1"]], mode="lines",
            line=dict(color=_rgba(ACCENT, 0.5),
                      width=1 + 5 * f["weight"] / wmax, dash="dot"),
            hovertemplate=f"migration route<br>distance {f['distance']:.0f} u"
                          f"<br>flow {f['weight']:.1f}<extra></extra>",
            hoverinfo="text", showlegend=False))

    # 3) people as unit dots (split by sex for a symbol, coloured by lineage)
    for sex, symbol in (("female", "circle"), ("male", "diamond")):
        pts = [p for p in frame if p["sex"] == sex]
        if not pts:
            continue
        fig.add_trace(go.Scatter(
            x=[p["map_x"] for p in pts], y=[p["map_y"] for p in pts],
            mode="markers",
            marker=dict(size=[7 + 0.08 * p["age"] for p in pts],
                        color=[p["color"] for p in pts], symbol=symbol,
                        line=dict(width=0.5, color="rgba(0,0,0,0.55)"),
                        opacity=0.95),
            customdata=[[p["name"], p["age"], p["lineage"], p["deme_label"],
                         p["children"]] for p in pts],
            hovertemplate="<b>%{customdata[0]}</b> (" + sex + ")<br>"
                          "age %{customdata[1]} · %{customdata[3]}<br>"
                          "lineage %{customdata[2]} · children %{customdata[4]}"
                          "<extra></extra>",
            name=sex))

    # 4) settlement markers + labels
    fig.add_trace(go.Scatter(
        x=[d["x"] for d in demes], y=[d["y"] for d in demes],
        mode="markers+text",
        marker=dict(size=[18 + 1.1 * d["n"] for d in demes], symbol="star",
                    color=[_rgba(deme_color(d["deme"]), 0.9) for d in demes],
                    line=dict(width=1.5, color=INK)),
        text=[f"{d['label']} · {d['n']}" for d in demes],
        textposition="top center", textfont=dict(color=INK2, size=11),
        hovertemplate="<b>%{text}</b><br>within-deme H %{customdata:.3f}<extra></extra>",
        customdata=[d["heterozygosity"] for d in demes],
        showlegend=False))

    # 5) selection ring
    if selected:
        sel = next((p for p in frame if p["name"] == selected), None)
        if sel:
            fig.add_trace(go.Scatter(
                x=[sel["map_x"]], y=[sel["map_y"]], mode="markers",
                marker=dict(size=22, color="rgba(0,0,0,0)",
                            line=dict(width=2.5, color=INK)),
                hoverinfo="skip", showlegend=False))

    _style(fig, "World map — settlements, territories & people (click a unit)",
           height=620, legend=True)
    fig.update_xaxes(range=[-4, MAP_SIZE + 4], showticklabels=False,
                     showgrid=False, zeroline=False, constrain="domain")
    fig.update_yaxes(range=[-4, MAP_SIZE + 4], showticklabels=False,
                     showgrid=False, zeroline=False,
                     scaleanchor="x", scaleratio=1)
    # a faint "terrain" backdrop
    fig.update_layout(plot_bgcolor="#0f1216",
                      paper_bgcolor=SURFACE)
    return fig


def lineage_legend(world) -> List:
    """(name, hex) swatch data for the founder-lineage legend beside the map."""
    return world.registry.legend()


# =====================================================================
# Comparative analysis (A vs B) and historical scrubbing
# =====================================================================

def compare_radar_figure(world, a: Optional[str], b: Optional[str]) -> go.Figure:
    """
    Two individuals' phenotype fingerprints as overlapping polygons, with the
    population mean behind them for scale. Each keeps its own bloodline
    colour, so the reading matches the map and the dot-cloud rather than
    inventing a fresh A/B palette.
    """
    fig = go.Figure()
    traits = _OCEAN + _BODY
    labels = [t[:4].upper() for t in _OCEAN] + ["HGT", "BMI", "AERO", "INS", "IMM"]

    if world.living:
        pop = [n.phenotype() for n in world.living]
        _radar(fig, labels,
               [float(np.mean([_to_score(t, p[t]) for p in pop])) for t in traits],
               "population", MUTED)

    for name in (a, b):
        if name and name in world.people:
            p = world.people[name].phenotype()
            colour = world.meta[name].color if name in world.meta else ACCENT
            _radar(fig, labels, [_to_score(t, p[t]) for t in traits],
                   name.split("-")[0], colour)

    _style(fig, "Phenotype fingerprints — A vs B", height=380, legend=True)
    fig.update_polars(bgcolor=SURFACE,
                      radialaxis=dict(range=[0, 100], gridcolor=GRID,
                                      tickfont=dict(color=MUTED, size=8),
                                      linecolor=AXIS),
                      angularaxis=dict(gridcolor=GRID, linecolor=AXIS,
                                       tickfont=dict(color=INK2, size=10)))
    return fig


def compare_bars_figure(world, a: Optional[str], b: Optional[str]) -> go.Figure:
    """
    Metabolic / physiological set-points as paired bars. A radar is good for
    overall shape but poor for reading a difference; this is the companion
    that answers "by how much".

    Plotted as z-scores against the CURRENT population, not raw phenotype
    values. These traits do not share a unit -- bp_set_point is in mmHg-like
    units and lung_capacity in its own scale, while insulin_sensitivity is
    already a liability -- so putting the raw numbers on one axis would put
    +109 next to +0.7 and label the axis "SD", which is simply false.
    Standardising makes the axis honest and the traits comparable.
    """
    fig = go.Figure()
    keys = ["insulin_sensitivity", "bp_set_point", "lipid_profile",
            "lung_capacity", "immune_reactivity", "inflammation_tone"]
    nice = ["insulin sens.", "BP set point", "lipids", "lung cap.",
            "immune react.", "inflam. tone"]

    pop = [n.phenotype() for n in world.living]
    mu, sd = {}, {}
    for k in keys:
        vals = np.array([float(p[k]) for p in pop if k in p], dtype=float) \
            if pop else np.array([0.0])
        mu[k] = float(vals.mean()) if vals.size else 0.0
        s = float(vals.std()) if vals.size else 0.0
        sd[k] = s if s > 1e-9 else 1.0        # a monomorphic trait -> no scaling

    for name in (a, b):
        if name and name in world.people:
            p = world.people[name].phenotype()
            colour = world.meta[name].color if name in world.meta else ACCENT
            z = [(float(p.get(k, mu[k])) - mu[k]) / sd[k] for k in keys]
            fig.add_trace(go.Bar(
                x=nice, y=z, name=name.split("-")[0], marker_color=colour,
                customdata=[float(p.get(k, 0.0)) for k in keys],
                hovertemplate="%{x}<br>%{y:+.2f} SD from population mean"
                              "<br>raw %{customdata:.2f}<extra></extra>"))

    fig.add_hline(y=0.0, line=dict(color=AXIS, width=1))
    _style(fig, "Set-points, standardised against the living population",
           height=280, legend=True)
    fig.update_layout(barmode="group")
    fig.update_yaxes(title="SD from population mean")
    return fig


def history_columns_upto(world, tick: Optional[int]) -> Dict[str, List[float]]:
    """
    History transposed to columns, truncated at `tick`.

    This is what makes the timeline scrubber work for every time-series chart:
    the charts are pure functions of these columns, so trimming the columns
    rewinds the charts with no other change. `tick=None` means live.
    """
    cols = world.history_columns()
    if not cols or tick is None:
        return cols
    ticks = cols.get("tick", [])
    keep = sum(1 for t in ticks if t <= tick)
    if keep >= len(ticks):
        return cols
    return {k: v[:keep] for k, v in cols.items()}


def scatter_figure_from_frame(world, frame: Optional[dict],
                              selected: Optional[str] = None) -> go.Figure:
    """
    The genetic dot-cloud for a HISTORICAL frame.

    The PCA embedding itself is refit on the living population, so a past
    frame cannot be re-embedded faithfully -- the snapshot keeps map
    coordinates, not genome projections. Rather than fake it, this plots the
    settlement layout the frame does carry and says so in the title. The live
    dot-cloud remains `scatter_figure`.
    """
    fig = go.Figure()
    if frame and frame["people"]:
        xs = [p["x"] for p in frame["people"]]
        ys = [p["y"] for p in frame["people"]]
        cs = [p["color"] for p in frame["people"]]
        names = [p["name"] for p in frame["people"]]
        sizes = [13 if n == selected else 9 for n in names]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers", customdata=names,
            marker=dict(size=sizes, color=cs,
                        line=dict(width=[2 if n == selected else 0.5 for n in names],
                                  color=[INK if n == selected else "rgba(0,0,0,0.5)"
                                         for n in names])),
            hovertemplate="%{customdata}<extra></extra>", showlegend=False))
    _style(fig, f"Settlement positions — year {frame['tick'] if frame else 0} "
                f"(historical; PCA embedding is live-only)", height=420)
    fig.update_xaxes(showticklabels=False, title="")
    fig.update_yaxes(showticklabels=False, title="", scaleanchor="x")
    return fig
