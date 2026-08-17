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


# Pedigree F is meaningless to most readers as a bare number, so every place
# it appears is labelled with the mating that produces it. Values are Wright's
# coefficients; the label is the CLOSEST standard relationship at or below the
# observed F, so it reads as "at least this close".
_F_LABELS: List[Tuple[float, str]] = [
    (0.25, "full sib / parent–offspring"),
    (0.125, "uncle–niece / double first cousin"),
    (0.0625, "first cousins"),
    (0.03125, "first cousins once removed"),
    (0.015625, "second cousins"),
]


def relationship_label(F: float) -> str:
    """Plain-language reading of a pedigree inbreeding coefficient."""
    for threshold, label in _F_LABELS:
        if F >= threshold - 1e-9:
            return label
    return "outbred" if F <= 1e-9 else "distant kin"


def _fmt_f(F: float) -> str:
    return f"{F:.4f}" if F else "0"


def _f_color(F: float) -> str:
    if F >= 0.0625:
        return CRIT
    if F >= 0.015625:
        return WARN
    return INK


def _inbreeding_rows(F: float, npc, cnvs: List[dict]) -> List:
    """
    The #31/#12 block: pedigree F, what it means, the realised value, the
    hidden recessive load, and any copy-number variants.

    Pedigree F and realised F are both shown on purpose. The pedigree value is
    an EXPECTATION over meioses; the realised value is what this individual's
    genome actually got, and the two differ because meiosis is a lottery.
    Showing only one of them would hide the engine's own point.

    `viability` and `stature cost` are the engine's TWO costs of inbreeding and
    are deliberately adjacent: recessive load decides survival, directional
    dominance decides height, and they are independent. The stature figure is
    an expectation at this pedigree F -- see `app._inbreeding_section` for why
    it is not keyed off the realised value.
    """
    from health_engine.inbreeding import predicted_depression

    rows = [
        _kv("pedigree F", _fmt_f(F), _f_color(F)),
    ]
    if F > 1e-9:
        rows.append(_kv("parents were", relationship_label(F), _f_color(F),
                        small=True))
    rows.append(_kv("realised F", f"{npc.realised_inbreeding():+.4f}",
                    _f_color(max(npc.realised_inbreeding(), 0.0))))
    rows.append(_kv("viability", f"{npc.relative_viability():.3f}",
                    CRIT if npc.relative_viability() < 0.9 else INK))
    if F > 1e-9:
        stature = predicted_depression("height_cm", F)
        rows.append(_kv("stature cost", f"{stature:+.2f} cm",
                        CRIT if stature <= -1.0 else WARN))
    if npc.load is not None:
        rows.append(_kv("hidden load", f"{npc.load.n_carried} alleles",
                        small=True))
        if npc.load.n_homozygous:
            rows.append(_kv("expressed load", f"{npc.load.n_homozygous} loci",
                            CRIT))
        # Named Mendelian recessives (diseases.py): the panel loci of the
        # load that are homozygous get their real-disorder names. The
        # anonymous "expressed load" count above stays -- the panel names
        # nine loci out of 2000, so the two rows answer different questions.
        for dx in npc.mendelian_diagnoses():
            rows.append(_kv(f"dx {dx.spec.gene}", dx.label, CRIT, small=True))
        carriers = npc.mendelian_carrier_of()
        if carriers:
            rows.append(_kv("carrier of",
                            ", ".join(d.spec.gene for d in carriers),
                            small=True))
    for v in cnvs:
        rows.append(_kv(f"CNV {v['region']}",
                        f"{v['kind']} ({v['copies']} copies, {v['parent_of_origin']})",
                        WARN))
    return rows


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
            f"historical view — year {frame['tick']}",
            style={"color": WARN, "fontSize": "11px", "fontWeight": 700,
                   "marginBottom": "8px"}))

    # ---- headline stats ----------------------------------------------
    if live:
        npc = world.people[name]
        ph = npc.phenotype()
        meta = world.meta[name]
        # Height AS EXPRESSED AT THIS AGE (#13). `phenotype()` returns the
        # MATURE value, so before this the drawer showed a five-year-old at
        # adult stature. The mature figure is still worth seeing -- it is the
        # genetic endpoint the child is growing toward -- so both are shown
        # while the individual is still growing.
        h_now = npc.height_at_age()
        growing = abs(h_now - ph["height_cm"]) > 0.05
        F = world.inbreeding_of(name)
        cnvs = npc.cnv_variants()

        stats = [
            _kv("height", (f"{h_now:.1f} cm  → {ph['height_cm']:.0f} adult"
                           if growing else f"{h_now:.1f} cm")),
            _kv("life stage", npc.life_stage()),
            # BMI is the MATURE value and is labelled as such while the
            # individual is still growing. #13 models stature only --
            # Preece-Baines is a height curve and the engine has no body-mass
            # trajectory -- so there is nothing to age-express BMI with.
            # Printing the bare number put "BMI 24.4" against a three-year-old,
            # which is not a possible value for a toddler (~15-16) and read as
            # a measurement rather than an endpoint.
            _kv("BMI", (f"{ph['bmi']:.1f} at maturity" if growing
                        else f"{ph['bmi']:.1f}")),
            _kv("VO₂ (mito-gated)", f"{npc.effective_aerobic_capacity():.2f}"),
            _kv("epigenetic age", f"{npc.epigenome.epigenetic_age:.1f}",
                CRIT if npc.epigenetic_age_acceleration > 3 else INK),
            _kv("age acceleration", f"{npc.epigenetic_age_acceleration:+.1f} y",
                CRIT if npc.epigenetic_age_acceleration > 3 else INK),
            _kv("inflammation", f"{npc.inflammation_state:+.2f}",
                CRIT if npc.inflammation_state > 0.6 else INK),
            # Names, not a count: "conditions: 2" made the reader open the
            # full character sheet to learn WHAT the individual has, which
            # is exactly the sort of unanswered claim this drawer is for.
            _kv("conditions",
                (", ".join(sorted({c.name.replace("_", " ")
                                   for c in npc.medical_conditions}))
                 if npc.medical_conditions else "none"),
                CRIT if npc.medical_conditions else INK,
                small=bool(npc.medical_conditions)),
            _kv("partner", (meta.partner or "—").split("-")[0]),
            _kv("children", meta.n_children),
        ]
        stats.extend(_inbreeding_rows(F, npc, cnvs))
        meters = [
            _meter("heterozygosity", _norm(npc.heterozygosity(), 0.0, 0.6),
                   CAT[1], f"{npc.heterozygosity():.3f}"),
            _meter("stress load", _norm(npc.inflammation_state, -1.5, 2.5),
                   CRIT, f"{npc.inflammation_state:+.2f}"),
        ]
    else:
        stats = [
            _kv("height", f"{row.get('height', 0):.1f} cm"),
            _kv("life stage", row.get("life_stage", "—")),
            _kv("stress", f"{row['stress']:+.2f}"),
            _kv("VO₂", f"{row['aerobic']:.2f}"),
            _kv("age acceleration", f"{row['epi_accel']:+.1f} y"),
            _kv("conditions", row["conditions"]),
            _kv("children", row["children"]),
            _kv("pedigree F", _fmt_f(row.get("pedigree_f", 0.0)),
                _f_color(row.get("pedigree_f", 0.0))),
            _kv("viability", f"{row.get('viability', 1.0):.3f}",
                CRIT if row.get("viability", 1.0) < 0.9 else INK),
        ]
        if row.get("cnv"):
            stats.append(_kv("CNVs", row["cnv"], WARN))
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
    # #31: the two ends of the genetic-load axis. "Most inbred" is the one
    # worth hunting for -- it is where consanguinity actually shows up in a
    # population, long before the mean moves.
    ("inbred", "Most inbred (pedigree F)", "pedigree_f", "{:.4f}", True),
    ("frail", "Lowest viability", "viability", "{:.3f}", False),
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
    rows = sorted(frame["people"], key=lambda p: p.get(field, 0),
                  reverse=reverse)
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
                    html.Span(fmt.format(p.get(field, 0)),
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
    {"label": "pedigree F", "value": "pedigree_f"},
    {"label": "viability", "value": "viability"},
    {"label": "height", "value": "height"},
]


def _sort_value_text(value, field: str) -> str:
    """
    Format the sorted-on column. Pedigree F needs four decimals -- at two, a
    first-cousin child (0.0625) and a second-cousin child (0.0156) both round
    to something uninformative, and telling them apart is the entire point of
    sorting by it.
    """
    if not isinstance(value, float):
        return str(value)
    return f"{value:.4f}" if field == "pedigree_f" else f"{value:.2f}"


def directory_rows(frame: Optional[dict], query: str = "",
                   sort_by: str = "age", deme: Optional[int] = None,
                   sex: Optional[str] = None, limit: int = 40,
                   selected: Optional[str] = None,
                   descending: bool = True) -> List:
    """
    Filtered, sorted, clickable list of everyone alive in this frame.

    `descending` defaults to True, which is what every caller written before
    the toggle existed will get. The ascending direction is not a nicety: the
    list is capped at `limit`, so with descending-only sorting the youngest,
    the least inbred, the shortest and the healthiest individuals are all
    literally unreachable -- and a child is exactly who you need to select to
    see the developmental trajectory (#13) do anything.
    """
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
    # `.get` with a default because the snapshot buffer is capped, not
    # versioned: frames captured before a field existed are still in the ring
    # and must not crash the directory when the user sorts by it.
    rows = sorted(rows, key=lambda p: p.get(field, 0),
                  reverse=bool(descending))[:limit]

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
            html.Span(_sort_value_text(p.get(field, 0), field),
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
    # Wright's coefficient of relationship from the pedigree, 2f (#31) --
    # the expectation the measured value scatters around.
    ped_r = world.pedigree().relationship(a, b)

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
        _crow("life stage", na.life_stage(), nb.life_stage(), "{}"),
        _crow("generation", na.generation, nb.generation, "{:.0f}"),
        _crow("community", world.meta[a].deme, world.meta[b].deme, "{:.0f}"),
        _crow("height now", na.height_at_age(), nb.height_at_age(), "{:.1f}"),
        _crow("height at maturity", pa["height_cm"], pb["height_cm"], "{:.1f}"),
        _crow("pedigree F", world.inbreeding_of(a), world.inbreeding_of(b),
              "{:.4f}"),
        _crow("realised F", na.realised_inbreeding(),
              nb.realised_inbreeding(), "{:+.4f}"),
        _crow("viability", na.relative_viability(),
              nb.relative_viability(), "{:.3f}"),
        _crow("hidden load (alleles)",
              na.load.n_carried if na.load else 0,
              nb.load.n_carried if nb.load else 0, "{:.0f}"),
        _crow("CNVs", len(na.cnv_variants()), len(nb.cnv_variants()), "{:.0f}"),
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
        html.Div([
            html.Span("pedigree expects ", style={"color": MUTED}),
            html.Span(f"{ped_r:+.3f}", style={"color": INK, "fontWeight": 700,
                                              "fontVariantNumeric": "tabular-nums"}),
            html.Span(f"  ·  measured {r:+.3f}  ·  difference "
                      f"{r - ped_r:+.3f}", style={"color": MUTED}),
        ], style={"fontSize": "11px", "marginTop": "6px"}),
        html.Div("Two different quantities, deliberately shown together. The "
                 "pedigree coefficient (2f, Malécot) is an EXPECTATION over "
                 "meioses; the GCTA figure is the fraction these two genomes "
                 "actually share. Full sibs all have a pedigree 0.5 and "
                 "scatter around it in reality, because meiosis is a lottery.",
                 style={"color": MUTED, "fontSize": "11px", "marginTop": "6px",
                        "lineHeight": "1.5"}),
    ])

    return [rel_card, header, html.Div(rows)]
