"""
Inspector drawer, directory / leaderboards, and the A-vs-B comparison.
======================================================================

Split out of `app.py` deliberately. That file already carries the layout and
every callback; adding three more view families inline would have pushed it
past the point where a change in one panel can be reasoned about without
reading the whole thing.

Everything here is a pure view function: it takes a `World` (and optionally a
historical frame from `simulation.snapshots`) and returns Dash components. No
callbacks, no global state, no mutation -- which is what makes them safe to
call from several callbacks at different ticks.

Live vs historical
------------------
The snapshot buffer stores ~12 scalars per person, not genomes. So these views
work in two modes and say which one they are in:

  * **live**   -- the individual is in `world.people`, so anything the engine
                  can compute is available.
  * **historical** -- we only have the frame row. Headline stats render; the
                  deep genetic sheet is honestly marked unavailable rather
                  than silently blank.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from dash import dcc, html

from health_engine.npc import genomic_relatedness

from .panels import (ACCENT, CAT, CRIT, GOOD, GRID, INK, INK2, MUTED, PLANE,
                     SURFACE, WARN)

CARD = {"background": SURFACE, "border": f"1px solid {GRID}",
        "borderRadius": "12px", "padding": "12px 14px"}
LBL = {"color": MUTED, "fontSize": "10px", "fontWeight": 700,
       "letterSpacing": "0.14em", "textTransform": "uppercase"}


# ---------------------------------------------------------------------
# small shared bits
# ---------------------------------------------------------------------

def _kv(k, v, vcolor=None, small=False):
    return html.Div([
        html.Span(k, style={"color": MUTED, "fontSize": "11px" if small else "12px"}),
        html.Span(str(v), style={"float": "right", "color": vcolor or INK,
                                 "fontSize": "11px" if small else "12px",
                                 "fontWeight": 600,
                                 "fontVariantNumeric": "tabular-nums"}),
    ], style={"marginBottom": "5px", "overflow": "hidden"})


def _meter(label, frac, color, hint=""):
    frac = max(0.0, min(1.0, float(frac)))
    return html.Div(style={"marginBottom": "8px"}, children=[
        html.Div([
            html.Span(label, style={"color": INK2, "fontSize": "11px"}),
            html.Span(hint, style={"float": "right", "color": MUTED,
                                   "fontSize": "11px",
                                   "fontVariantNumeric": "tabular-nums"}),
        ]),
        html.Div(style={"height": "6px", "background": PLANE, "borderRadius": "4px",
                        "overflow": "hidden", "marginTop": "3px"}, children=[
            html.Div(style={"width": f"{frac*100:.0f}%", "height": "100%",
                            "background": color})]),
    ])


def _swatch(color, size=14):
    return html.Span(style={"display": "inline-block", "width": f"{size}px",
                            "height": f"{size}px", "borderRadius": "4px",
                            "background": color, "border": f"1px solid {GRID}",
                            "flexShrink": 0})


def _pill(text, color=None):
    return html.Span(text, style={
        "color": color or MUTED, "fontSize": "11px", "whiteSpace": "nowrap",
        "border": f"1px solid {GRID}", "borderRadius": "999px",
        "padding": "2px 9px"})


def _norm(value, lo, hi):
    """Normalise into [0,1] for a meter. Handles signed liabilities."""
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (float(value) - lo) / (hi - lo)))


def _frame_person(frame: Optional[dict], name: str) -> Optional[dict]:
    if not frame:
        return None
    for p in frame["people"]:
        if p["name"] == name:
            return p
    return None


# ---------------------------------------------------------------------
# 1. Persistent inspector drawer
# ---------------------------------------------------------------------

def summary_card(world, name: Optional[str],
                 frame: Optional[dict] = None,
                 historical: bool = False) -> List:
    """
    The compact live card for the right-hand drawer. Deliberately NOT the
    full character sheet -- that stays on the Individual tab. This is what
    you want visible while you keep looking at the map.
    """
    if not name:
        return [
            html.Div("INSPECTOR", style={**LBL, "marginBottom": "10px"}),
            html.Div("Click any villager on the map, or any dot in the "
                     "genetic cloud, to inspect them here without leaving "
                     "this view.",
                     style={"color": INK2, "fontSize": "12px",
                            "lineHeight": "1.55"}),
            html.Div(style={"height": "1px", "background": GRID,
                            "margin": "12px 0"}),
            html.Div("The Individual tab holds the full character sheet: "
                     "genetics, health, mind and family tree.",
                     style={"color": MUTED, "fontSize": "11px",
                            "lineHeight": "1.5"}),
        ]

    row = _frame_person(frame, name)
    live = (not historical) and name in world.people

    if not live and row is None:
        return [
            html.Div("INSPECTOR", style={**LBL, "marginBottom": "10px"}),
            html.Div(f"{name.split('-')[0]} was not alive at this point in "
                     f"the timeline.",
                     style={"color": WARN, "fontSize": "12px"}),
        ]

    # ---- identity ----------------------------------------------------
    if live:
        npc, meta = world.people[name], world.meta[name]
        dom, purity = world.registry.dominant(meta.ancestry)
        color, sex, age, gen = meta.color, npc.sex, npc.age, npc.generation
        deme = meta.deme
        alive = npc.alive
        death = "" if alive else f"died year {meta.death_tick} ({meta.death_cause})"
    else:
        color, sex, age, gen = row["color"], row["sex"], row["age"], row["generation"]
        dom, purity, deme = row["lineage"], row["purity"], row["deme"]
        alive, death = True, ""

    from simulation import deme_label

    head = html.Div(style={"display": "flex", "alignItems": "center",
                           "gap": "9px", "marginBottom": "8px"}, children=[
        _swatch(color, 18),
        html.Div([
            html.Div(name.split("-")[0], style={"fontSize": "17px",
                                                "fontWeight": 800, "color": INK}),
            html.Div(f"{sex} · age {age} · gen {gen}",
                     style={"color": INK2, "fontSize": "11px"}),
        ]),
    ])

    tags = html.Div(style={"display": "flex", "gap": "5px", "flexWrap": "wrap",
                           "marginBottom": "10px"}, children=[
        _pill(f"{dom.split('-')[0]} {purity:.0%}", INK2),
        _pill(deme_label(deme), INK2),
        _pill("● alive" if alive else "✝ dead", GOOD if alive else CRIT),
    ])

    body: List = [html.Div("INSPECTOR", style={**LBL, "marginBottom": "10px"}),
                  head, tags]

    if historical:
        body.append(html.Div(
            f"⏱ historical view — year {frame['tick']}",
            style={"color": WARN, "fontSize": "11px", "fontWeight": 700,
                   "marginBottom": "8px"}))

    # ---- headline stats ----------------------------------------------
    if live:
        npc = world.people[name]
        ph = npc.phenotype()
        meta = world.meta[name]
        stats = [
            _kv("height", f"{ph['height_cm']:.1f} cm"),
            _kv("BMI", f"{ph['bmi']:.1f}"),
            _kv("VO₂ (mito-gated)", f"{npc.effective_aerobic_capacity():.2f}"),
            _kv("epigenetic age", f"{npc.epigenome.epigenetic_age:.1f}",
                CRIT if npc.epigenetic_age_acceleration > 3 else INK),
            _kv("age acceleration", f"{npc.epigenetic_age_acceleration:+.1f} y",
                CRIT if npc.epigenetic_age_acceleration > 3 else INK),
            _kv("inflammation", f"{npc.inflammation_state:+.2f}",
                CRIT if npc.inflammation_state > 0.6 else INK),
            _kv("conditions", len(npc.medical_conditions),
                CRIT if npc.medical_conditions else INK),
            _kv("partner", (meta.partner or "—").split("-")[0]),
            _kv("children", meta.n_children),
        ]
        meters = [
            _meter("heterozygosity", _norm(npc.heterozygosity(), 0.0, 0.6),
                   CAT[1], f"{npc.heterozygosity():.3f}"),
            _meter("stress load", _norm(npc.inflammation_state, -1.5, 2.5),
                   CRIT, f"{npc.inflammation_state:+.2f}"),
        ]
    else:
        stats = [
            _kv("stress", f"{row['stress']:+.2f}"),
            _kv("VO₂", f"{row['aerobic']:.2f}"),
            _kv("age acceleration", f"{row['epi_accel']:+.1f} y"),
            _kv("conditions", row["conditions"]),
            _kv("children", row["children"]),
        ]
        meters = [_meter("stress load", _norm(row["stress"], -1.5, 2.5), CRIT,
                         f"{row['stress']:+.2f}")]

    body.append(html.Div(stats))
    body.append(html.Div(style={"height": "1px", "background": GRID,
                                "margin": "10px 0"}))
    body.extend(meters)

    if not alive and death:
        body.append(html.Div(death, style={"color": CRIT, "fontSize": "11px",
                                           "marginTop": "6px"}))

    if not live:
        body.append(html.Div(
            "Full genetic sheet is available for living individuals only — "
            "the history buffer keeps headline stats, not genomes.",
            style={"color": MUTED, "fontSize": "10px", "marginTop": "10px",
                   "lineHeight": "1.5"}))
    else:
        body.append(html.Div(
            "Open the Individual tab for the full character sheet.",
            style={"color": MUTED, "fontSize": "10px", "marginTop": "10px"}))

    return body


# ---------------------------------------------------------------------
# 2. Leaderboards -- "The Extremes"
# ---------------------------------------------------------------------

# (key, label, accessor, formatter, reverse) -- accessor reads a frame row,
# so leaderboards work identically live and historically.
BOARDS: List[Tuple[str, str, str, str, bool]] = [
    ("oldest", "Oldest living", "age", "{:.0f} y", True),
    ("fittest", "Highest VO₂", "aerobic", "{:.2f}", True),
    ("stressed", "Highest stress load", "stress", "{:+.2f}", True),
    ("ill", "Most conditions", "conditions", "{:.0f}", True),
    ("prolific", "Most children", "children", "{:.0f}", True),
]


def leaderboard_entries(frame: Optional[dict], key: str,
                        top: int = 5) -> List[dict]:
    """Top `top` rows of one board, straight off a snapshot frame."""
    if not frame or not frame["people"]:
        return []
    spec = next((b for b in BOARDS if b[0] == key), None)
    if spec is None:
        return []
    _, _, field, _, reverse = spec
    rows = sorted(frame["people"], key=lambda p: p[field], reverse=reverse)
    return rows[:top]


def lineage_sizes(frame: Optional[dict], top: int = 5) -> List[Tuple[str, int, str]]:
    """Largest bloodlines by living headcount: (lineage, n, colour)."""
    if not frame or not frame["people"]:
        return []
    counts: Dict[str, int] = {}
    colors: Dict[str, str] = {}
    for p in frame["people"]:
        counts[p["lineage"]] = counts.get(p["lineage"], 0) + 1
        colors.setdefault(p["lineage"], p["color"])
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:top]
    return [(k, v, colors[k]) for k, v in ranked]


def leaderboard_view(frame: Optional[dict], selected: Optional[str] = None) -> List:
    """
    The Extremes panel. Every row is a button, so clicking it selects that
    individual -- which is the whole point: stop hunting on the map.
    """
    if not frame or not frame["people"]:
        return [html.Div("No living population.",
                         style={"color": MUTED, "fontSize": "12px"})]

    blocks: List = []
    for key, label, field, fmt, _rev in BOARDS:
        rows = leaderboard_entries(frame, key, top=3)
        items = []
        for p in rows:
            is_sel = p["name"] == selected
            items.append(html.Button(
                [
                    _swatch(p["color"], 10),
                    html.Span(p["name"].split("-")[0],
                              style={"marginLeft": "7px", "fontWeight": 600,
                                     "color": INK, "fontSize": "12px"}),
                    html.Span(fmt.format(p[field]),
                              style={"float": "right", "color": INK2,
                                     "fontSize": "12px",
                                     "fontVariantNumeric": "tabular-nums"}),
                ],
                id={"type": "board-pick", "name": p["name"]},
                n_clicks=0,
                style={"display": "block", "width": "100%", "textAlign": "left",
                       "background": (PLANE if is_sel else "transparent"),
                       "border": f"1px solid {ACCENT if is_sel else 'transparent'}",
                       "borderRadius": "7px", "padding": "5px 8px",
                       "marginBottom": "3px", "cursor": "pointer"}))
        blocks.append(html.Div(style={"marginBottom": "12px"}, children=[
            html.Div(label, style={**LBL, "color": ACCENT, "marginBottom": "5px"}),
            html.Div(items)]))

    # bloodlines
    lines = lineage_sizes(frame, top=4)
    items = [html.Div([
        _swatch(c, 10),
        html.Span(k.split("-")[0], style={"marginLeft": "7px", "color": INK,
                                          "fontSize": "12px", "fontWeight": 600}),
        html.Span(f"{n}", style={"float": "right", "color": INK2,
                                 "fontSize": "12px",
                                 "fontVariantNumeric": "tabular-nums"}),
    ], style={"padding": "5px 8px"}) for k, n, c in lines]
    blocks.append(html.Div(children=[
        html.Div("Largest bloodlines",
                 style={**LBL, "color": ACCENT, "marginBottom": "5px"}),
        html.Div(items)]))

    return blocks


# ---------------------------------------------------------------------
# 3. Directory / smart filter
# ---------------------------------------------------------------------

SORT_FIELDS = [
    {"label": "age", "value": "age"},
    {"label": "stress load", "value": "stress"},
    {"label": "VO₂", "value": "aerobic"},
    {"label": "conditions", "value": "conditions"},
    {"label": "children", "value": "children"},
    {"label": "generation", "value": "generation"},
]


def directory_rows(frame: Optional[dict], query: str = "",
                   sort_by: str = "age", deme: Optional[int] = None,
                   sex: Optional[str] = None, limit: int = 40,
                   selected: Optional[str] = None) -> List:
    """Filtered, sorted, clickable list of everyone alive in this frame."""
    if not frame or not frame["people"]:
        return [html.Div("No living population.",
                         style={"color": MUTED, "fontSize": "12px"})]

    rows = frame["people"]
    q = (query or "").strip().lower()
    if q:
        rows = [p for p in rows
                if q in p["name"].lower() or q in p["lineage"].lower()]
    if deme is not None:
        rows = [p for p in rows if p["deme"] == deme]
    if sex in ("female", "male"):
        rows = [p for p in rows if p["sex"] == sex]

    field = sort_by if sort_by in {f["value"] for f in SORT_FIELDS} else "age"
    rows = sorted(rows, key=lambda p: p[field], reverse=True)[:limit]

    if not rows:
        return [html.Div("Nothing matches that filter.",
                         style={"color": WARN, "fontSize": "12px"})]

    from simulation import deme_label
    out = []
    for p in rows:
        is_sel = p["name"] == selected
        out.append(html.Button([
            _swatch(p["color"], 10),
            html.Span(p["name"].split("-")[0],
                      style={"marginLeft": "7px", "color": INK,
                             "fontSize": "12px", "fontWeight": 600}),
            html.Span(f"{'♀' if p['sex'] == 'female' else '♂'} {p['age']}y · "
                      f"{deme_label(p['deme'])}",
                      style={"marginLeft": "8px", "color": MUTED,
                             "fontSize": "11px"}),
            html.Span(f"{p[field]:.2f}" if isinstance(p[field], float)
                      else f"{p[field]}",
                      style={"float": "right", "color": INK2, "fontSize": "12px",
                             "fontVariantNumeric": "tabular-nums"}),
        ], id={"type": "dir-pick", "name": p["name"]}, n_clicks=0,
            style={"display": "block", "width": "100%", "textAlign": "left",
                   "background": (PLANE if is_sel else "transparent"),
                   "border": f"1px solid {ACCENT if is_sel else 'transparent'}",
                   "borderRadius": "7px", "padding": "5px 8px",
                   "marginBottom": "3px", "cursor": "pointer"}))
    return out


# ---------------------------------------------------------------------
# 4. A-vs-B comparison
# ---------------------------------------------------------------------

COMPARE_ROWS = [
    ("height_cm", "height", "{:.1f} cm"),
    ("bmi", "BMI", "{:.1f}"),
    ("adiposity", "adiposity", "{:+.2f}"),
    ("insulin_sensitivity", "insulin sensitivity", "{:+.2f}"),
    ("bp_set_point", "BP set point", "{:+.2f}"),
    ("lipid_profile", "lipid profile", "{:+.2f}"),
    ("lung_capacity", "lung capacity", "{:+.2f}"),
    ("immune_reactivity", "immune reactivity", "{:+.2f}"),
    ("inflammation_tone", "inflammation tone", "{:+.2f}"),
]


def compare_table(world, a: Optional[str], b: Optional[str]) -> List:
    """
    Side-by-side metabolic / physiological read-out plus the genomic
    relatedness coefficient. Only meaningful for two LIVING individuals --
    the comparison needs genomes, which the history buffer does not keep.
    """
    if not a or not b:
        return [html.Div("Pick a second individual to compare.",
                         style={"color": MUTED, "fontSize": "12px"})]
    if a not in world.people or b not in world.people:
        return [html.Div("Comparison needs two individuals with genomes on "
                         "record (living, or dead but still in this run).",
                         style={"color": WARN, "fontSize": "12px"})]
    if a == b:
        return [html.Div("Those are the same individual.",
                         style={"color": WARN, "fontSize": "12px"})]

    na, nb = world.people[a], world.people[b]
    pa, pb = na.phenotype(), nb.phenotype()
    r = genomic_relatedness(na, nb)

    # relatedness interpretation, using the standard thresholds the engine's
    # own kinship guard works with
    if r >= 0.45:
        rel, rcol = "parent-offspring or full sibs", CRIT
    elif r >= 0.20:
        rel, rcol = "half sibs / grandparent-grandchild", WARN
    elif r >= 0.10:
        rel, rcol = "about first cousins", WARN
    elif r >= 0.03:
        rel, rcol = "distant kin", INK2
    else:
        rel, rcol = "effectively unrelated", GOOD

    header = html.Div(style={
        "display": "grid", "gridTemplateColumns": "1.4fr 1fr 1fr",
        "gap": "8px", "alignItems": "center", "marginBottom": "10px"}, children=[
        html.Div(""),
        html.Div([_swatch(world.meta[a].color, 12),
                  html.Span(a.split("-")[0], style={"marginLeft": "6px",
                            "fontWeight": 800, "color": INK, "fontSize": "13px"})],
                 style={"textAlign": "center"}),
        html.Div([_swatch(world.meta[b].color, 12),
                  html.Span(b.split("-")[0], style={"marginLeft": "6px",
                            "fontWeight": 800, "color": INK, "fontSize": "13px"})],
                 style={"textAlign": "center"}),
    ])

    def _crow(label, va, vb, fmt):
        try:
            sa, sb = fmt.format(va), fmt.format(vb)
        except (TypeError, ValueError):
            sa, sb = str(va), str(vb)
        hi = ACCENT
        return html.Div(style={
            "display": "grid", "gridTemplateColumns": "1.4fr 1fr 1fr",
            "gap": "8px", "padding": "4px 0",
            "borderBottom": f"1px solid {GRID}"}, children=[
            html.Div(label, style={"color": INK2, "fontSize": "12px"}),
            html.Div(sa, style={"textAlign": "center", "color": INK,
                                "fontSize": "12px", "fontWeight": 600,
                                "fontVariantNumeric": "tabular-nums"}),
            html.Div(sb, style={"textAlign": "center", "color": INK,
                                "fontSize": "12px", "fontWeight": 600,
                                "fontVariantNumeric": "tabular-nums"}),
        ])

    rows = [
        _crow("age", na.age, nb.age, "{:.0f}"),
        _crow("generation", na.generation, nb.generation, "{:.0f}"),
        _crow("community", world.meta[a].deme, world.meta[b].deme, "{:.0f}"),
        _crow("heterozygosity", na.heterozygosity(), nb.heterozygosity(), "{:.3f}"),
        _crow("epigenetic age", na.epigenome.epigenetic_age,
              nb.epigenome.epigenetic_age, "{:.1f}"),
        _crow("age acceleration", na.epigenetic_age_acceleration,
              nb.epigenetic_age_acceleration, "{:+.1f}"),
        _crow("inflammation state", na.inflammation_state,
              nb.inflammation_state, "{:+.2f}"),
        _crow("VO₂ (mito-gated)", na.effective_aerobic_capacity(),
              nb.effective_aerobic_capacity(), "{:.2f}"),
        _crow("conditions", len(na.medical_conditions),
              len(nb.medical_conditions), "{:.0f}"),
    ]
    for key, label, fmt in COMPARE_ROWS:
        if key in pa and key in pb:
            rows.append(_crow(label, pa[key], pb[key], fmt))

    rel_card = html.Div(style={**CARD, "marginBottom": "12px",
                               "borderColor": rcol}, children=[
        html.Div("GENOMIC RELATEDNESS", style={**LBL, "marginBottom": "6px"}),
        html.Div([
            html.Span(f"r = {r:+.3f}", style={"fontSize": "22px",
                      "fontWeight": 800, "color": rcol,
                      "fontVariantNumeric": "tabular-nums"}),
            html.Span(f"  {rel}", style={"color": INK2, "fontSize": "12px",
                                         "marginLeft": "10px"}),
        ]),
        html.Div("Realised GCTA relatedness across all 500 loci — the actual "
                 "shared fraction, not a pedigree expectation.",
                 style={"color": MUTED, "fontSize": "11px", "marginTop": "6px",
                        "lineHeight": "1.5"}),
    ])

    return [rel_card, header, html.Div(rows)]
