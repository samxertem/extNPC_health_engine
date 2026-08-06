"""
The live population dashboard (Dash + Plotly) — session-8 command deck.
======================================================================

A tabbed, futuristic control room for the extNPC population simulation:

    * OVERVIEW    the genetic-PCA dot-cloud, a KPI strip, a decade summary,
                  and a live *chronicle* narrating the population's history;
    * GENETICS    trait evolution, diversity with a drift-loss threshold, a
                  per-decade OHLC candlestick, a population radar, repro skew;
    * COMMUNITY   F_ST over time, per-deme columns, a history spiral, bloodlines
                  and couple-kinship — the island model made visible;
    * CONTROLS    every knob grouped, scenario presets, shock injectors and a
                  cited glossary;
    * INDIVIDUAL  the inspector card, an individual-vs-population radar, tree.

Tabs are a custom button bar toggling panel visibility, so every Graph stays in
the DOM and its callback never targets a missing component.

Run:  python run_dashboard.py   ->  http://127.0.0.1:8050
"""

from __future__ import annotations

from dataclasses import replace

from dash import (ALL, Dash, dcc, html, Input, Output, State, ctx, no_update,
                  ClientsideFunction)

from simulation import (World, DemographyParams, SCENARIOS, scenario_list,
                        SHOCK_KINDS, GLOSSARY)
from simulation.demography import (DEFAULT_FERTILITY_SCHEDULE,
                                   FERTILITY_SCHEDULES, mean_reproductive_age)
from . import genetics_panels as gpanels, inspector, panels

# ---------------------------------------------------------------------
# One long-lived world, mutated by the interval callback.
# ---------------------------------------------------------------------
DEFAULTS = dict(seed=7, n_founders=10, carrying_capacity=150,
                birth_rate=0.42, mortality_scale=1.0, selection_pressure=0.4,
                mutation_rate_scale=1.0, recombination_scale=1.0,
                assortative_strength=0.0, inbreeding_threshold=0.5,
                n_demes=1, migration_rate=0.0, resource_equity=1.0,
                exposure_smoking=0.0, exposure_stress=0.0,
                exposure_prenatal_nutrition=1.0)


def params_from_controls(K, birth, mort, sel, mut, recomb, assort, inbreed,
                         n_demes, migr, equity, smoke, stress, prenat,
                         depression=1.0,
                         schedule=DEFAULT_FERTILITY_SCHEDULE
                         ) -> DemographyParams:
    """
    Map the control row onto `DemographyParams`.

    New arguments are appended with defaults that reproduce the previous
    behaviour, so a caller written before a feature landed still produces the
    params it always did: `depression` defaults to 1.0 (the calibrated
    strength, roadmap #31) and `schedule` to the legacy linear taper.
    """
    return DemographyParams(
        carrying_capacity=int(K), birth_rate=float(birth),
        mortality_scale=float(mort), selection_pressure=float(sel),
        mutation_rate_scale=float(mut), recombination_scale=float(recomb),
        assortative_strength=float(assort), inbreeding_threshold=float(inbreed),
        n_demes=int(n_demes), migration_rate=float(migr),
        resource_equity=float(equity), exposure_smoking=float(smoke),
        exposure_stress=float(stress), exposure_prenatal_nutrition=float(prenat),
        inbreeding_depression=float(depression),
        fertility_schedule=str(schedule or DEFAULT_FERTILITY_SCHEDULE))


def build_world(seed, n_founders, params: DemographyParams) -> World:
    return World(n_founders=int(n_founders), seed=int(seed), params=params)


WORLD = build_world(DEFAULTS["seed"], DEFAULTS["n_founders"], DemographyParams(
    carrying_capacity=DEFAULTS["carrying_capacity"],
    birth_rate=DEFAULTS["birth_rate"], mortality_scale=DEFAULTS["mortality_scale"],
    selection_pressure=DEFAULTS["selection_pressure"]))

# ---------------------------------------------------------------------
# Styling helpers
# ---------------------------------------------------------------------
SURFACE, PLANE, INK, INK2, MUTED, GRID = (
    panels.SURFACE, panels.PLANE, panels.INK, panels.INK2, panels.MUTED, panels.GRID)
ACCENT, GOOD, WARN, CRIT = panels.ACCENT, panels.GOOD, panels.WARN, panels.CRIT

LEVEL_COLOR = {"info": INK2, "good": GOOD, "warn": WARN, "crit": CRIT}


def _rgba_hdr(hex_color, a):
    return panels._rgba(hex_color, a)

CARD = {"backgroundColor": SURFACE, "border": f"1px solid {GRID}",
        "borderRadius": "12px", "padding": "12px",
        "boxShadow": "0 1px 0 rgba(255,255,255,0.03) inset"}
LBL = {"color": MUTED, "fontSize": "10px", "letterSpacing": "0.08em",
       "textTransform": "uppercase", "marginBottom": "3px"}
TABS = ["overview", "map", "genetics", "community", "controls",
        "individual", "guide"]
TAB_ICON = {"overview": "◧ Overview", "map": "🗺 World Map",
            "genetics": "🧬 Genetics", "community": "🌍 Community",
            "controls": "🎛 Controls", "individual": "👤 Individual",
            "guide": "❔ Guide"}
CHAR_TABS = ["info", "genetics", "health", "mind", "family"]
CHAR_ICON = {"info": "🪪 Info", "genetics": "🧬 Genetics",
             "health": "🩺 Health", "mind": "🧠 Mind", "family": "🌳 Family"}


def slider(id_, mn, mx, step, val, marks=None):
    return dcc.Slider(id=id_, min=mn, max=mx, step=step, value=val,
                      marks=marks or {}, tooltip={"placement": "bottom"},
                      updatemode="mouseup")


def labelled(label, comp, width="160px", tip=None):
    return html.Div([html.Div(label, style=LBL, title=tip or ""), comp],
                    style={"width": width})


def graph(id_, fig=None):
    """
    A chart that actually fits its grid cell.

    `responsive: True` is not optional here. Without it Plotly falls back to
    its built-in 700 px default width, which was invisible while the panels
    were full-page but overlaps badly now that the split-screen puts three
    charts in ~245 px cells. The width:100% style alone does not help — the
    SVG is sized by Plotly, not by CSS — so the config flag is what makes the
    chart re-measure its container on every resize.
    """
    return dcc.Graph(id=id_, config={"displayModeBar": False, "responsive": True},
                     style={"width": "100%"}, figure=fig or {})


# update_title=None stops Dash flashing "Updating…" in the tab on every tick.
app = Dash(__name__, title="extNPC — Living Population", update_title=None)
app.config.suppress_callback_exceptions = True


# =====================================================================
# Small view builders (HTML fragments rebuilt each tick)
# =====================================================================

def kpi_row(cols):
    tiles = panels.kpi_data(cols, WORLD.params)
    children = []
    for t in tiles:
        d = t["delta"]
        arrow = ("▲" if d > 0 else "▼" if d < 0 else "·")
        acol = (GOOD if d > 0 else CRIT if d < 0 else MUTED)
        children.append(html.Div(style={
            **CARD, "padding": "10px 12px", "flex": "1", "minWidth": "112px",
            "borderTop": f"2px solid {t['accent']}"},
            title=t["glossary"], children=[
            html.Div(t["label"], style={**LBL, "color": MUTED}),
            html.Div(t["value"], style={"fontSize": "22px", "fontWeight": 700,
                                        "color": INK, "fontVariantNumeric": "tabular-nums",
                                        "lineHeight": "1.1"}),
            html.Div(f"{arrow} {abs(d):.3g}" if t["fmt"] != "none" else "",
                     style={"fontSize": "10px", "color": acol}),
        ]))
    return children


def chronicle_feed(events):
    if not events:
        return [html.Div("The chronicle will fill as history unfolds.",
                         style={"color": MUTED, "fontSize": "12px"})]
    rows = []
    for e in events:
        rows.append(html.Div([
            html.Span(f"y{e.tick}", style={"color": MUTED, "fontSize": "10px",
                                           "fontVariantNumeric": "tabular-nums",
                                           "marginRight": "8px",
                                           "display": "inline-block", "width": "34px"}),
            html.Span(e.text, style={"color": LEVEL_COLOR.get(e.level, INK2),
                                     "fontSize": "12px"}),
        ], style={"padding": "3px 0", "borderLeft": f"2px solid {LEVEL_COLOR.get(e.level, GRID)}",
                  "paddingLeft": "8px", "marginBottom": "2px"}))
    return rows


def decade_banner():
    s = WORLD.chronicle.latest_summary()
    if not s:
        return html.Div("Press ▶ Play — a decade summary appears every 10 years.",
                        style={"color": MUTED, "fontSize": "12px"})
    return html.Div([
        html.Span(f"DECADE · YEAR {s.tick}  ", style={**LBL, "color": ACCENT}),
        html.Span(s.text, style={"color": INK2, "fontSize": "13px"}),
    ])


def glossary_panel():
    items = []
    for g in GLOSSARY.values():
        items.append(html.Div(style={"marginBottom": "10px"}, children=[
            html.Div(g["title"], style={"color": INK, "fontSize": "12px", "fontWeight": 600}),
            html.Div(g["text"], style={"color": INK2, "fontSize": "11px", "lineHeight": "1.4"}),
            html.Div(g["cite"], style={"color": MUTED, "fontSize": "10px", "fontStyle": "italic"}),
        ]))
    return items


# ---- character-sheet building blocks --------------------------------------
_EMPTY = html.Div("Click a villager (World Map) or a dot (Overview) to open "
                  "their character sheet.",
                  style={"color": MUTED, "fontSize": "13px", "padding": "8px"})


def _row(k, v, vcolor=None):
    return html.Div([html.Span(k, style={"color": MUTED}),
                     html.Span(str(v), style={"float": "right",
                               "color": vcolor or INK2,
                               "fontVariantNumeric": "tabular-nums"})],
                    style={"fontSize": "13px", "marginBottom": "5px"})


def _section(title, rows):
    return html.Div(style={**CARD, "marginBottom": "10px"}, children=[
        html.Div(title, style={**LBL, "color": ACCENT, "marginBottom": "8px"}),
        html.Div(rows)])


def _bar(label, frac, color):
    frac = max(0.0, min(1.0, float(frac)))
    return html.Div(style={"marginBottom": "7px"}, children=[
        html.Div([html.Span(label, style={"color": MUTED, "fontSize": "12px"}),
                  html.Span(f"{frac*100:.0f}", style={"float": "right", "color": INK2,
                            "fontSize": "12px", "fontVariantNumeric": "tabular-nums"})]),
        html.Div(style={"height": "7px", "background": PLANE, "borderRadius": "4px",
                        "overflow": "hidden", "marginTop": "2px"}, children=[
            html.Div(style={"width": f"{frac*100:.0f}%", "height": "100%",
                            "background": color})])])


def char_header(name):
    npc, meta = WORLD.people[name], WORLD.meta[name]
    dom, purity = WORLD.registry.dominant(meta.ancestry)
    alive = ("● alive" if npc.alive
             else f"✝ died year {meta.death_tick} ({meta.death_cause})")
    acol = GOOD if npc.alive else CRIT
    swatch = html.Span(style={"display": "inline-block", "width": "16px",
                              "height": "16px", "borderRadius": "4px",
                              "background": meta.color, "marginRight": "8px",
                              "border": f"1px solid {GRID}"})
    return html.Div(style={"display": "flex", "alignItems": "center",
                           "gap": "10px", "flexWrap": "wrap"}, children=[
        swatch,
        html.Span(name.split("-")[0], style={"fontSize": "20px", "fontWeight": 800}),
        html.Span(f"#{name.split('-')[1]}", style={"color": MUTED, "fontSize": "12px"}),
        html.Span(f"{npc.sex} · age {npc.age} · gen {npc.generation}",
                  style={"color": INK2, "fontSize": "13px"}),
        html.Span(f"{dom.split('-')[0]} {purity:.0%}",
                  style={"color": MUTED, "fontSize": "12px",
                         "border": f"1px solid {GRID}", "borderRadius": "999px",
                         "padding": "2px 10px"}),
        html.Span(f"{panels_deme_label(meta.deme)}",
                  style={"color": MUTED, "fontSize": "12px",
                         "border": f"1px solid {GRID}", "borderRadius": "999px",
                         "padding": "2px 10px"}),
        html.Div(style={"flex": 1}),
        html.Span(alive, style={"color": acol, "fontSize": "12px", "fontWeight": 700}),
    ])


def char_info(name):
    npc, meta = WORLD.people[name], WORLD.meta[name]
    dom, purity = WORLD.registry.dominant(meta.ancestry)
    parents = (" × ".join(p.split("-")[0] for p in npc.parents)
               if npc.parents else "founder (no parents)")
    return html.Div(style={"display": "grid",
                           "gridTemplateColumns": "repeat(2, minmax(0, 1fr))", "gap": "10px"}, children=[
        _section("IDENTITY", [
            _row("name", name.split("-")[0]), _row("sex", npc.sex),
            _row("age", f"{npc.age} yrs"), _row("generation", npc.generation),
            _row("status", "alive" if npc.alive else "deceased")]),
        _section("COMMUNITY & LINEAGE", [
            _row("settlement", panels_deme_label(meta.deme)),
            _row("bloodline", f"{dom.split('-')[0]} ({purity:.0%} pure)"),
            _row("resource access", f"{meta.resource_access:.2f}",
                 GOOD if meta.resource_access >= 1 else WARN)]),
        _section("FAMILY", [
            _row("parents", parents),
            _row("partner", meta.partner.split("-")[0] if meta.partner else "—"),
            _row("children", meta.n_children)]),
        # Height AS EXPRESSED AT THIS AGE (#13). `phenotype()` is age-blind by
        # design -- that is what keeps the calibration safe -- so the sheet
        # has to ask for the developmental value explicitly, and shows the
        # mature endpoint beside it while the individual is still growing.
        _section("APPEARANCE", [
            _row("height", f"{npc.height_at_age():.1f} cm"),
            _row("adult height", f"{npc.phenotype()['height_cm']:.1f} cm",
                 MUTED if npc.life_stage() in ("adult", "midlife") else WARN),
            _row("life stage", npc.life_stage()),
            _row("BMI", f"{npc.phenotype()['bmi']:.1f}"),
            _row("eye colour", npc.phenotype().get("eye_color", "?")),
            _row("skin tone", f"{npc.phenotype()['skin_tone']:+.2f}"),
            _row("handedness", npc.phenotype().get("handedness", "?"))]),
    ])


def _inbreeding_section(name, npc):
    """Rows for the character sheet's inbreeding / genetic-load block (#31, #12)."""
    from .inspector import relationship_label

    F = WORLD.inbreeding_of(name)
    rows = [
        _row("pedigree F", f"{F:.4f}", CRIT if F >= 0.0625 else
             (WARN if F >= 0.015625 else INK)),
        _row("parents were", relationship_label(F) if F > 1e-9 else "unrelated"),
        _row("realised F", f"{npc.realised_inbreeding():+.4f}"),
        _row("relative viability", f"{npc.relative_viability():.3f}",
             CRIT if npc.relative_viability() < 0.9 else GOOD),
    ]
    if npc.load is not None:
        rows.append(_row("hidden recessive load", f"{npc.load.n_carried} alleles"))
        rows.append(_row("expressed (homozygous)", npc.load.n_homozygous,
                         CRIT if npc.load.n_homozygous else INK))
    variants = npc.cnv_variants()
    if variants:
        for v in variants:
            rows.append(_row(f"CNV {v['region']}",
                             f"{v['kind']} · {v['copies']} copies · "
                             f"{v['parent_of_origin']}", WARN))
    else:
        rows.append(_row("copy-number variants", "none"))
    return rows


def char_genetics(name):
    npc = WORLD.people[name]
    ph = npc.phenotype()
    mito = npc.mito_phenotype()
    xl = npc.x_linked_phenotype()
    return html.Div(style={"display": "grid",
                           "gridTemplateColumns": "repeat(2, minmax(0, 1fr))", "gap": "10px"}, children=[
        _section("GENOME", [
            _row("heterozygosity", f"{npc.heterozygosity():.3f}"),
            _row("de novo mutations", npc.de_novo_mutations),
            _row("mito haplogroup", mito.get("haplogroup", "—")),
            _row("mtDNA heteroplasmy", f"{mito.get('heteroplasmy', 0):.2f}"),
            _row("OXPHOS capacity", f"{mito.get('oxphos_capacity', 1):.2f}")]),
        # #31 + #12. Pedigree F and realised F are both shown because they are
        # different quantities: an expectation over meioses versus what this
        # genome actually got.
        _section("INBREEDING & LOAD", _inbreeding_section(name, npc)),
        _section("SEX-LINKED (X)", [
            _row("colour vision", xl.get("color_vision", "—")),
            _row("G6PD activity", f"{xl.get('g6pd_activity', 1):.2f}"),
            _row("pattern baldness", "yes" if xl.get("pattern_baldness") else "no")]),
        _section("HAIR & FACE", [
            _row("hair curl", f"{ph['hair_curl']:+.2f}"),
            _row("hair thickness", f"{ph['hair_thickness']:+.2f}"),
            _row("nose width", f"{ph['nose_width']:+.2f}"),
            _row("chin protrusion", f"{ph['chin_protrusion']:+.2f}"),
            _row("brow ridge", f"{ph['brow_ridge']:+.2f}")]),
        _section("FITNESS PROXY", [
            _row("aerobic (VO₂)", f"{ph['aerobic_capacity']:.1f}"),
            _row("effective VO₂", f"{npc.effective_aerobic_capacity():.1f}"),
            _row("lung capacity", f"{ph['lung_capacity']:.1f}"),
            _row("immune reactivity", f"{ph['immune_reactivity']:+.2f}"),
            _row("immune resilience", str(ph.get("immune_resilience", "?")))]),
    ])


def char_health(name):
    npc = WORLD.people[name]
    ph = npc.phenotype()
    conds = npc.medical_conditions
    if conds:
        clist = [html.Div([
            html.Span("● ", style={"color": CRIT}),
            html.Span(c.name.replace("_", " "), style={"color": INK2}),
            html.Span(f"  onset {c.onset_age} · severity {c.severity:.0%}",
                      style={"color": MUTED, "fontSize": "11px"})],
            style={"fontSize": "13px", "marginBottom": "4px"}) for c in conds]
    else:
        clist = [html.Div("no chronic conditions",
                          style={"color": GOOD, "fontSize": "13px"})]
    accel = npc.epigenetic_age_acceleration
    return html.Div(style={"display": "grid",
                           "gridTemplateColumns": "repeat(2, minmax(0, 1fr))", "gap": "10px"}, children=[
        _section(f"CONDITIONS ({len(conds)})", clist),
        _section("BIOLOGICAL AGEING", [
            _row("chronological age", f"{npc.age} yrs"),
            _row("epigenetic age", f"{npc.epigenetic_age:.1f} yrs"),
            _row("age acceleration", f"{accel:+.1f} yrs",
                 CRIT if accel > 3 else (WARN if accel > 1 else GOOD)),
            _row("inflammation", f"{npc.inflammation_state:+.2f}",
                 CRIT if npc.inflammation_state > 0.3 else INK2)]),
        _section("ORGAN FUNCTION", [
            _row("insulin sensitivity", f"{ph['insulin_sensitivity']:+.2f}"),
            _row("blood-pressure set", f"{ph['bp_set_point']:.0f} mmHg"),
            _row("lipid profile", f"{ph['lipid_profile']:+.2f}"),
            _row("chronic-illness risk",
                 str(ph.get("chronic_illness_predisposition", "?")).replace("_", " "))]),
        _section("SENSES", [
            _row("vision acuity", npc.phenotype().get("vision_acuity", "?")),
            _row("hearing", npc.phenotype().get("hearing_ability", "?")),
            _row("mito disease", "yes" if npc.mito_phenotype().get("mito_disease") else "no")]),
    ])


def char_mind(name):
    """OCEAN + chronotype/interoception + a live physiological mood read."""
    npc = WORLD.people[name]
    ph = npc.phenotype()
    ocean = [("openness", "#3987e5"), ("conscientiousness", "#199e70"),
             ("extraversion", "#c98500"), ("agreeableness", "#008300"),
             ("neuroticism", "#e66767")]
    bars = [_bar(t.capitalize(), 0.5 + ph[t] / 4.0, c) for t, c in ocean]
    try:
        mood = npc.physiological_state().to_prompt()
    except Exception:
        mood = "—"
    return html.Div([
        _section("PERSONALITY (OCEAN)", bars),
        _section("TEMPERAMENT", [
            _row("chronotype", f"{ph['chronotype']:+.2f} "
                 f"({'lark' if ph['chronotype'] < 0 else 'owl'})"),
            _row("interoceptive acc.", f"{ph['interoceptive_accuracy']:+.2f}")]),
        _section("PHYSIOLOGICAL READ", [
            html.Div(mood, style={"color": INK2, "fontSize": "13px",
                                  "lineHeight": "1.5", "fontStyle": "italic"})]),
    ])


def panels_deme_label(d):
    from simulation import deme_label
    return deme_label(d)


def _stress_ramp(t: float) -> str:
    """
    Calm-to-critical ramp for the stress overlay.

    Deliberately NOT a red-green scale: it runs teal -> amber -> red, which
    stays separable under the common CVD types and keeps the same ordering in
    greyscale. `t` is already normalised.
    """
    t = max(0.0, min(1.0, float(t)))
    stops = [(0.0, (32, 122, 118)), (0.5, (201, 133, 0)), (1.0, (208, 59, 59))]
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            f = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            r, g, b = (int(a + (b_ - a) * f) for a, b_ in zip(c0, c1))
            return f"#{r:02x}{g:02x}{b:02x}"
    return "#d03b3b"


def build_mapdata(world, selected, frame=None, layer="default",
                  historical=False):
    """
    Compact JSON payload the canvas renderer (rts_map.js) draws from.

    Reads a snapshot `frame` rather than the live world, so the identical path
    serves both live rendering and time travel. `layer` selects the overlay:

      default    -- villagers tinted by bloodline (the original view)
      dominance  -- each territory washed with its dominant bloodline's colour,
                    opacity = how dominant it is
      stress     -- each territory washed by mean physiological load

    Stress is `inflammation_state`, a LIABILITY in SD units, so it is signed.
    The overlay normalises across the settlements present in this frame rather
    than assuming a 0-based scale (a calm population sits below zero).
    """
    frame = frame or world.frame_at(None)
    if not frame:
        return {"size": 100, "seed": int(world.seed), "demes": [], "people": [],
                "flows": [], "selected": selected, "layer": layer,
                "historical": historical, "tick": world.tick}

    stresses = [d["mean_stress"] for d in frame["demes"] if d["n"] > 0]
    lo, hi = (min(stresses), max(stresses)) if stresses else (0.0, 1.0)
    if hi - lo < 1e-6:                      # flat -> mid-ramp, not divide-by-zero
        lo, hi = lo - 0.5, hi + 0.5

    demes = []
    for d in frame["demes"]:
        row = {"id": d["deme"], "label": _deme_short(d["deme"]),
               "x": d["x"], "y": d["y"], "r": d["r"], "n": d["n"],
               "color": panels.deme_color(d["deme"])}
        if layer == "dominance":
            row["wash"] = d["dominant_color"]
            row["washAlpha"] = round(0.10 + 0.45 * d["dominance"], 3)
            row["badge"] = f"{d['dominant'].split('-')[0]} {d['dominance']:.0%}"
        elif layer == "stress":
            t = (d["mean_stress"] - lo) / (hi - lo)
            row["wash"] = _stress_ramp(t)
            row["washAlpha"] = round(0.16 + 0.42 * t, 3)
            row["badge"] = f"load {d['mean_stress']:+.2f}"
        demes.append(row)

    people = [{"name": p["name"], "x": p["x"], "y": p["y"],
               "color": p["color"], "sex": p["sex"]} for p in frame["people"]]
    flows = [{"x0": f["x0"], "y0": f["y0"], "x1": f["x1"], "y1": f["y1"],
              "w": f["w"]} for f in frame["flows"]]
    return {"size": 100, "seed": int(world.seed), "demes": demes,
            "people": people, "flows": flows, "selected": selected,
            "layer": layer, "historical": bool(historical),
            "tick": int(frame["tick"])}


def _deme_short(d: int) -> str:
    from simulation import deme_label
    return deme_label(d).split("-")[0]


def lineage_legend_view():
    swatches = panels.lineage_legend(WORLD)
    rows = []
    if WORLD.params.n_demes <= 1:
        # A single town on the map is the configured world, not a rendering
        # fault -- say so, because it is the first thing the map looks like.
        rows.append(html.Div(
            "One settlement — this world is a single panmictic deme, which is "
            "the reproducibility baseline. Raise “demes” in Controls and press "
            "Reset to populate the map and make F_ST measurable.",
            style={"color": MUTED, "fontSize": "11px", "lineHeight": "1.5",
                   "marginBottom": "10px"}))
    rows.append(html.Div("BLOODLINES", style={**LBL, "marginBottom": "8px"}))
    for name, hexc in swatches:
        rows.append(html.Div([
            html.Span(style={"display": "inline-block", "width": "11px",
                             "height": "11px", "borderRadius": "3px",
                             "background": hexc, "marginRight": "7px"}),
            html.Span(name.split("-")[0], style={"fontSize": "12px", "color": INK2}),
        ], style={"marginBottom": "4px"}))
    return rows


MAP_LAYERS = [
    ("default", "Bloodlines", "villagers tinted by founder lineage"),
    ("dominance", "Dominance", "which bloodline holds each settlement"),
    ("stress", "Stress load", "mean physiological load per settlement"),
]


def layer_selector():
    """Segmented control for the world-map overlays."""
    return html.Div(style={"display": "flex", "gap": "4px", "flexWrap": "wrap"},
                    children=[
        html.Button(label, id=f"layer-{key}", n_clicks=0, title=hint, style={
            "background": "transparent", "border": f"1px solid {GRID}",
            "borderRadius": "999px", "color": INK2, "padding": "5px 13px",
            "fontSize": "11px", "fontWeight": 700, "cursor": "pointer"})
        for key, label, hint in MAP_LAYERS])


def inspector_column(suffix: str, extras=None):
    """
    The persistent right-hand drawer, one instance per host tab.

    Distinct ids per tab (rather than one shared component moved around)
    because Dash needs every id to exist exactly once in the DOM; a single
    callback fans the same content into all of them, so they never diverge.
    """
    extras = extras or []
    return html.Div(style={"display": "flex", "flexDirection": "column",
                           "gap": "12px", "minWidth": 0}, children=[
        html.Div(id=f"drawer-{suffix}", style={**CARD, "minHeight": "260px"}),
        html.Div(style={**CARD, "padding": "10px 12px"}, children=[
            html.Div(style={"display": "flex", "gap": "4px", "marginBottom": "9px"},
                     children=[
                html.Button("★ Extremes", id=f"dmode-extremes-{suffix}", n_clicks=0,
                            style={"flex": 1, "background": "transparent",
                                   "border": f"1px solid {GRID}", "color": INK2,
                                   "borderRadius": "7px", "padding": "5px",
                                   "fontSize": "11px", "fontWeight": 700,
                                   "cursor": "pointer"}),
                html.Button("🔍 Directory", id=f"dmode-directory-{suffix}", n_clicks=0,
                            style={"flex": 1, "background": "transparent",
                                   "border": f"1px solid {GRID}", "color": INK2,
                                   "borderRadius": "7px", "padding": "5px",
                                   "fontSize": "11px", "fontWeight": 700,
                                   "cursor": "pointer"}),
            ]),
            html.Div(id=f"dirtools-{suffix}", style={"display": "none"}, children=[
                dcc.Input(id=f"dirq-{suffix}", type="text", debounce=True,
                          placeholder="name or bloodline…",
                          style={"width": "100%", "background": PLANE, "color": INK,
                                 "border": f"1px solid {GRID}", "borderRadius": "6px",
                                 "padding": "6px 8px", "fontSize": "12px",
                                 "marginBottom": "6px"}),
                html.Div(style={"display": "flex", "gap": "6px",
                                "alignItems": "center", "marginBottom": "8px"},
                         children=[
                    html.Div(dcc.Dropdown(id=f"dirsort-{suffix}",
                                          options=inspector.SORT_FIELDS,
                                          value="age", clearable=False,
                                          className="dk-dd",
                                          style={"fontSize": "12px"}),
                             style={"flex": 1, "minWidth": 0}),
                    # Direction toggle. The list is capped at 40 rows, so
                    # without this the youngest / least inbred / shortest
                    # individuals cannot be reached at all -- and a child is
                    # exactly who you need selected to see #13 do anything.
                    html.Button("↓", id=f"dirdir-{suffix}", n_clicks=0,
                                title="sort descending (click for ascending)",
                                style={"background": "transparent",
                                       "border": f"1px solid {GRID}",
                                       "color": INK2, "borderRadius": "6px",
                                       "padding": "5px 10px", "fontSize": "13px",
                                       "fontWeight": 700, "cursor": "pointer",
                                       "flex": "0 0 auto"}),
                ]),
            ]),
            html.Div(id=f"dlist-{suffix}",
                     style={"maxHeight": "420px", "overflowY": "auto"}),
        ]),
        *extras,
    ])


def _g(title, body):
    return html.Div(style={**CARD, "marginBottom": "12px"}, children=[
        html.Div(title, style={"color": ACCENT, "fontSize": "13px",
                               "fontWeight": 700, "marginBottom": "6px",
                               "letterSpacing": "0.04em"}),
        html.Div(body, style={"color": INK2, "fontSize": "13px", "lineHeight": "1.6"}),
    ])


def _steps(items):
    return html.Ol(style={"margin": "0", "paddingLeft": "18px"},
                   children=[html.Li(x, style={"marginBottom": "5px"}) for x in items])


def guide_content():
    return html.Div(style={"maxWidth": "1050px"}, children=[
        html.Div("A living population, generation over generation",
                 style={"fontSize": "18px", "fontWeight": 700, "marginBottom": "4px"}),
        html.Div("Each dot is a genetically-modelled person with a full genome, "
                 "epigenome and physiology. Press Play and the world ages one year "
                 "per tick — people pair, reproduce, migrate, sicken and die, and "
                 "the population evolves. Nothing is scripted; the patterns emerge.",
                 style={"color": MUTED, "fontSize": "13px", "marginBottom": "14px"}),

        html.Div(style={"display": "grid", "gridTemplateColumns": "repeat(2, minmax(0, 1fr))", "gap": "12px"},
                 children=[
            _g("1 · Get started", _steps([
                "Press ▶ Play (top-left) to run time. Use ⏭ Step for one year, "
                "⟲ Reset to restart with the current settings.",
                "Set speed, random seed and founder count in the transport bar. "
                "Seed + settings fully determine a run — the same seed replays exactly.",
                "Click any person — on the World Map or the Overview genetic map — "
                "to open their full profile in the Individual tab.",
            ])),
            _g("2 · Read the KPI strip", [
                "The eight tiles under the transport bar track the population at a "
                "glance; hover any tile for its definition and citation. The arrow "
                "shows the 10-year trend. Watch ", html.B("Diversity H"),
                " fall as the population inbreeds, ", html.B("F_ST"),
                " rise as communities isolate, and ", html.B("Kinship"),
                " climb when unrelated mates run out.",
            ]),
            _g("3 · The tabs", [
                html.Div([html.B("World Map — "),
                          "settlements, territories and people in space; migration "
                          "routes show gene flow. Click a unit to inspect it. The "
                          "layer selector swaps in bloodline-dominance and "
                          "physiological-stress overlays."]),
                html.Div([html.B("Genetics — "),
                          "thirteen charts in three bands: population-wide variation "
                          "(trait evolution, allele-frequency spectrum, "
                          "heterozygosity, phenotype distributions); selection, drift "
                          "and structure (volatility, reproductive skew, age "
                          "structure, mutational load); and the parallel inheritance "
                          "layers (imprinting, X-linked, mitochondrial, the "
                          "epigenetic clock)."]),
                html.Div([html.B("Community — "),
                          "F_ST, per-deme headcount, a history spiral, bloodlines "
                          "and couple-kinship: the island model made visible."]),
                html.Div([html.B("Individual — "),
                          "one person's profile, their fingerprint vs the population, "
                          "their family tree, and Compare mode for reading two "
                          "individuals side by side with their genomic relatedness."]),
            ]),
            _g("4 · Drive evolution (Controls)", [
                "Every slider is live — drag it and the next tick obeys. ",
                html.B("Selection pressure"), " culls the frail; ",
                html.B("assortative mating"), " pairs like with like; ",
                html.B("demes + migration"), " split the world into communities "
                "(raise demes, then press Reset); ", html.B("resource equity"),
                " concentrates survival among dominant families; the ",
                html.B("exposure"), " sliders drive smoking/stress/famine into the "
                "epigenome. Fire ", html.B("shocks"),
                " (plague, famine, bottleneck) for one-off history.",
            ]),
            _g("5 · What to look for (the science)", [
                html.Div("• Genetic drift: diversity H sags as a small closed "
                         "population descends from a few founders."),
                html.Div("• Lineage dominance & extinction: a few bloodlines take "
                         "over the headcount while others vanish."),
                html.Div("• Isolation by distance: with several demes and low "
                         "migration, F_ST climbs toward Wright's 1/(4Nₑm+1)."),
                html.Div("• The breeder's equation: turn up selection and watch "
                         "the trait means move."),
            ]),
            _g("6 · Presets to try", [
                html.Div("Load a scenario in Controls, then Play:"),
                html.Div("• Isolated islands → F_ST climbs, demes diverge."),
                html.Div("• Melting pot → heavy migration keeps F_ST ≈ 0."),
                html.Div("• Founder crash → rapid drift, extinctions."),
                html.Div("• Harsh & unequal → differential survival by strata."),
            ]),
        ]),
        html.Div("This is a scientific model, not medical or clinical guidance. "
                 "Gene–trait associations are population-level statistical findings; "
                 "behaviour is deliberately only weakly heritable.",
                 style={"color": MUTED, "fontSize": "11px", "marginTop": "12px",
                        "fontStyle": "italic"}),
    ])


# =====================================================================
# Layout
# =====================================================================

def btn(label, id_, primary=False):
    style = {"borderRadius": "7px", "padding": "8px 14px", "cursor": "pointer",
             "fontWeight": 600, "fontSize": "12px", "border": f"1px solid {GRID}",
             "background": (ACCENT if primary else SURFACE),
             "color": ("#04121f" if primary else INK)}
    return html.Button(label, id=id_, n_clicks=0, style=style)


def tab_button(t):
    return html.Button(TAB_ICON[t], id=f"tab-{t}", n_clicks=0, style={
        "background": "transparent", "border": "none",
        "borderBottom": f"2px solid transparent", "color": MUTED,
        "padding": "10px 16px", "cursor": "pointer", "fontSize": "13px",
        "fontWeight": 600, "letterSpacing": "0.02em"})


def panel(id_, children, visible=False):
    return html.Div(id=id_, style={"display": "block" if visible else "none"},
                    children=children)


# Order MUST match `params_from_controls`' positional signature -- the advance
# callback splats these straight into it.
CTRL_INPUTS = ["K", "birth", "mort", "sel", "mut", "recomb", "assort",
               "inbreed", "ndemes", "migr", "equity", "smoke", "stress",
               "prenat", "depress", "fertsched"]

# The split-screen: main content, then the persistent inspector drawer.
# `minmax(0, …)` on the first column stops wide Plotly figures from forcing
# the grid wider than the viewport (the classic CSS-grid overflow trap).
SPLIT = {"display": "grid",
         "gridTemplateColumns": "minmax(0, 3fr) minmax(260px, 1fr)",
         "gap": "12px", "alignItems": "start"}

# Drawer instances, one per host tab. Every fan-out callback iterates this.
DRAWERS = ["overview", "map", "genetics"]

# Two equal chart columns. `minmax(0, 1fr)` rather than plain `1fr` matters:
# a bare 1fr track has min-width:auto, so a chart wider than its share pushes
# the track open instead of shrinking, which is exactly how the Genetics charts
# ended up overlapping.
GRID2 = {"display": "grid", "gridTemplateColumns": "repeat(2, minmax(0, 1fr))",
         "gap": "12px", "marginBottom": "12px"}


def _band(title: str):
    """A section heading that groups related charts."""
    return html.Div(title, style={
        "color": ACCENT, "fontSize": "10px", "fontWeight": 800,
        "letterSpacing": "0.16em", "textTransform": "uppercase",
        "margin": "4px 0 8px", "paddingBottom": "6px",
        "borderBottom": f"1px solid {GRID}"})


app.layout = html.Div(style={
    "background": f"radial-gradient(1200px 600px at 20% -10%, #14161c 0%, {PLANE} 60%)",
    "minHeight": "100vh", "padding": "14px 18px 120px",
    "fontFamily": 'system-ui, "Segoe UI", sans-serif', "color": INK}, children=[

    dcc.Store(id="tick", data=WORLD.tick),
    dcc.Store(id="selected", data=None),
    dcc.Store(id="running", data=False),
    dcc.Store(id="active-tab", data="overview"),
    dcc.Store(id="char-tab", data="info"),
    dcc.Store(id="shock-log", data=0),
    # None = live; an int = viewing that historical year (time travel)
    dcc.Store(id="timeline", data=None),
    # Last value written to the slider BY THE APP rather than by the user.
    # Without this the slider is a feedback loop: the tick callback moves the
    # handle to the newest frame, that move re-fires the drag handler, and if
    # the world has advanced in between, the stale value pins the view to a
    # past year. Comparing against the echo tells a real drag from a redraw.
    dcc.Store(id="slider-echo", data=None),
    dcc.Store(id="drawer-mode", data="extremes"),
    dcc.Store(id="map-layer", data="default"),
    dcc.Store(id="cmp-on", data=False),
    dcc.Store(id="cmp-b", data=None),
    dcc.Interval(id="timer", interval=1000, disabled=True),

    # ---- header ------------------------------------------------------
    html.Div(style={"display": "flex", "alignItems": "center",
                    "justifyContent": "space-between", "marginBottom": "6px"},
             children=[
        html.Div(style={"display": "flex", "alignItems": "center", "gap": "12px"},
                 children=[
            html.Div("🧬", style={
                "fontSize": "24px", "width": "44px", "height": "44px",
                "display": "flex", "alignItems": "center", "justifyContent": "center",
                "background": f"linear-gradient(135deg,{_rgba_hdr(ACCENT,0.22)},"
                              f"{_rgba_hdr('#9085e9',0.18)})",
                "border": f"1px solid {GRID}", "borderRadius": "12px"}),
            html.Div([
                html.Span("extNPC", style={"fontSize": "22px", "fontWeight": 800,
                                           "letterSpacing": "0.02em"}),
                html.Span(" · LIVING POPULATION", style={"fontSize": "14px",
                          "color": ACCENT, "fontWeight": 700, "letterSpacing": "0.12em"}),
                html.Div("genetics · epigenetics · physiology · community — "
                         "a life-simulator, generation over generation",
                         style={"color": MUTED, "fontSize": "11px", "marginTop": "2px"}),
            ]),
        ]),
        html.Div(id="headline", style={"color": INK2, "fontSize": "13px",
                                        "fontVariantNumeric": "tabular-nums",
                                        "textAlign": "right"}),
    ]),
    # accent bar + live ticker
    html.Div(style={"height": "2px", "background":
             f"linear-gradient(90deg,{ACCENT},transparent)", "marginBottom": "8px"}),
    html.Div(id="ticker", style={"color": MUTED, "fontSize": "12px",
                                 "marginBottom": "10px", "minHeight": "16px"}),

    # ---- transport bar ----------------------------------------------
    html.Div(style={**CARD, "display": "flex", "gap": "12px",
                    "alignItems": "center", "marginBottom": "10px",
                    "flexWrap": "wrap"}, children=[
        btn("▶ Play", "btn-play", primary=True),
        btn("⏭ Step", "btn-step"),
        btn("⟲ Reset", "btn-reset"),
        labelled("speed (ticks/s)", slider("speed", 0.5, 8, 0.5, 2), "150px"),
        labelled("seed", dcc.Input(id="seed", type="number", value=DEFAULTS["seed"],
                 style={"width": "70px", "background": PLANE, "color": INK,
                        "border": f"1px solid {GRID}", "borderRadius": "5px",
                        "padding": "5px"}), "84px"),
        labelled("founders", dcc.Input(id="nfounders", type="number",
                 value=DEFAULTS["n_founders"], min=4, max=40, step=2,
                 style={"width": "70px", "background": PLANE, "color": INK,
                        "border": f"1px solid {GRID}", "borderRadius": "5px",
                        "padding": "5px"}), "84px",
                 "structural — applied on Reset"),
        html.Div(style={"flex": 1}),
        html.Div(id="run-state", style={"color": MUTED, "fontSize": "12px"}),
    ]),

    # ---- KPI strip + decade banner ----------------------------------
    html.Div(id="kpi-row", style={"display": "flex", "gap": "8px",
                                  "marginBottom": "8px", "flexWrap": "wrap"}),
    html.Div(id="summary-banner", style={**CARD, "marginBottom": "10px",
                                         "padding": "10px 14px"}),

    # ---- tab bar -----------------------------------------------------
    html.Div(style={"display": "flex", "gap": "4px", "borderBottom":
             f"1px solid {GRID}", "marginBottom": "12px"},
             children=[tab_button(t) for t in TABS]),

    # =================================================================
    # PANELS (visibility toggled by the tab bar)
    # =================================================================

    # ---- OVERVIEW ----------------------------------------------------
    panel("panel-overview", visible=True, children=[
        html.Div(style=SPLIT, children=[
            # main column
            html.Div(style={"minWidth": 0}, children=[
                html.Div(style={**CARD, "marginBottom": "12px"},
                         children=[graph("g-scatter",
                                         panels.scatter_figure(WORLD))]),
                html.Div(style={"display": "grid",
                                "gridTemplateColumns": "repeat(3, minmax(0, 1fr))",
                                "gap": "12px", "marginBottom": "12px"}, children=[
                    html.Div(style=CARD, children=[graph("g-pop")]),
                    html.Div(style=CARD, children=[graph("g-bd")]),
                    html.Div(style=CARD, children=[graph("g-div-o")]),
                ]),
                html.Div(style={**CARD, "maxHeight": "300px",
                                "overflowY": "auto"}, children=[
                    html.Div("CHRONICLE", style={**LBL, "marginBottom": "8px"}),
                    html.Div(id="chronicle"),
                ]),
            ]),
            # persistent inspector drawer
            inspector_column("overview"),
        ]),
    ]),

    # ---- WORLD MAP ---------------------------------------------------
    panel("panel-map", children=[
        dcc.Store(id="mapdata"),
        html.Div(id="rts-sink", style={"display": "none"}),
        html.Div(style=SPLIT, children=[
            html.Div(style={"minWidth": 0}, children=[
                # command bar above the map
                html.Div(style={**CARD, "display": "flex", "alignItems": "center",
                                "gap": "12px", "flexWrap": "wrap",
                                "marginBottom": "10px", "padding": "9px 12px"},
                         children=[
                    html.Span("MAP LAYER", style=LBL),
                    layer_selector(),
                    html.Div(style={"flex": 1}),
                    html.Div(id="layer-hint", style={"color": MUTED,
                                                     "fontSize": "11px"}),
                ]),
                html.Div(style={**CARD, "background": "#0b0e12", "padding": "8px",
                                "boxShadow": "0 18px 48px rgba(0,0,0,0.55), "
                                             "inset 0 0 0 1px rgba(78,163,255,0.10)",
                                "borderColor": "#1d2530"}, children=[
                    # Height is solved against the chrome above it (header, KPI
                    # strip, tabs, layer bar) and the sticky scrubber below, so
                    # the map fills the viewport without the scrubber floating
                    # over it. A flat vh value overshot and clipped the map.
                    html.Canvas(id="rts-canvas",
                                style={"width": "100%",
                                       "height": "calc(100vh - 440px)",
                                       "minHeight": "460px",
                                       "display": "block", "borderRadius": "10px",
                                       "imageRendering": "pixelated"}),
                    html.Div("Art: Kenney “Tiny Town” (CC0) · villagers team-tinted "
                             "by bloodline · click a villager to inspect",
                             style={"color": MUTED, "fontSize": "10px",
                                    "textAlign": "center", "padding": "6px 4px 2px"}),
                ]),
            ]),
            inspector_column("map", extras=[
                html.Div(id="map-legend", style={**CARD, "maxHeight": "220px",
                                                 "overflowY": "auto"}),
                html.Div(style=CARD, children=[
                    html.Div("HOW TO READ THIS MAP", style={**LBL, "marginBottom": "8px"}),
                    html.Div([
                        html.Div("★ settlement — size = population"),
                        html.Div("◯ shaded ring — the community's territory"),
                        html.Div("┈ dotted line — a migration route "
                                 "(thicker = more gene flow)"),
                        html.Div("● / ◆ dot — a person (female / male), "
                                 "colour = bloodline"),
                        html.Div("Click any person to inspect them.",
                                 style={"color": ACCENT, "marginTop": "6px"}),
                        html.Div("Raise ‘demes’ in Controls then Reset to populate "
                                 "the map with multiple communities.",
                                 style={"color": MUTED, "marginTop": "6px",
                                        "fontSize": "11px"}),
                    ], style={"fontSize": "12px", "color": INK2, "lineHeight": "1.7"}),
                ]),
            ]),
        ]),
    ]),

    # ---- GENETICS ----------------------------------------------------
    # Grouped into three labelled bands so the tab reads as an argument
    # (variation -> structure -> the parallel inheritance layers) rather than
    # as a wall of charts. Two columns, not three: at the split-screen width
    # three charts per row leaves each too narrow to read.
    panel("panel-genetics", children=[
        html.Div(style=SPLIT, children=[
            html.Div(style={"minWidth": 0}, children=[

                _band("POPULATION-WIDE VARIATION"),
                html.Div(style=GRID2, children=[
                    html.Div(style=CARD, children=[graph("g-traits")]),
                    html.Div(style=CARD, children=[graph("g-pop-radar")]),
                ]),
                html.Div(style=GRID2, children=[
                    html.Div(style=CARD, children=[graph("g-spectrum")]),
                    html.Div(style=CARD, children=[graph("g-het-hist")]),
                ]),
                html.Div(style=GRID2, children=[
                    html.Div(style=CARD, children=[graph("g-trait-dist")]),
                    html.Div(style=CARD, children=[graph("g-div-g")]),
                ]),

                _band("SELECTION, DRIFT & STRUCTURE"),
                html.Div(style=GRID2, children=[
                    html.Div(style=CARD, children=[graph("g-cand")]),
                    html.Div(style=CARD, children=[graph("g-skew")]),
                ]),
                html.Div(style=GRID2, children=[
                    html.Div(style=CARD, children=[graph("g-pyramid")]),
                    html.Div(style=CARD, children=[graph("g-mutload")]),
                ]),

                _band("PARALLEL INHERITANCE LAYERS"),
                html.Div(style=GRID2, children=[
                    html.Div(style=CARD, children=[graph("g-imprint")]),
                    html.Div(style=CARD, children=[graph("g-sexlink")]),
                ]),
                html.Div(style=GRID2, children=[
                    html.Div(style=CARD, children=[graph("g-mito")]),
                    html.Div(style=CARD, children=[graph("g-epiage")]),
                ]),
            ]),
            inspector_column("genetics"),
        ]),
    ]),

    # ---- COMMUNITY ---------------------------------------------------
    panel("panel-community", children=[
        html.Div(style={"display": "grid", "gridTemplateColumns": "repeat(2, minmax(0, 1fr))",
                        "gap": "12px", "marginBottom": "12px"}, children=[
            html.Div(style=CARD, children=[graph("g-fst")]),
            html.Div(style=CARD, children=[graph("g-deme")]),
        ]),
        html.Div(style={"display": "grid", "gridTemplateColumns": "repeat(2, minmax(0, 1fr))",
                        "gap": "12px", "marginBottom": "12px"}, children=[
            html.Div(style=CARD, children=[graph("g-inbreed")]),
            html.Div(style=CARD, children=[graph("g-rel")]),
        ]),
        html.Div(style={"display": "grid", "gridTemplateColumns": "repeat(2, minmax(0, 1fr))",
                        "gap": "12px"}, children=[
            html.Div(style=CARD, children=[graph("g-spiral")]),
            html.Div(style=CARD, children=[graph("g-lin")]),
        ]),
    ]),

    # ---- CONTROLS ----------------------------------------------------
    panel("panel-controls", children=[
        html.Div(style={"display": "grid", "gridTemplateColumns": "repeat(3, minmax(0, 1fr))",
                        "gap": "12px", "marginBottom": "12px"}, children=[
            html.Div(style=CARD, children=[
                html.Div("POPULATION", style={**LBL, "color": ACCENT, "marginBottom": "8px"}),
                labelled("carrying capacity", slider("K", 30, 400, 10, DEFAULTS["carrying_capacity"]), "auto"),
                labelled("birth rate", slider("birth", 0.05, 1.0, 0.01, DEFAULTS["birth_rate"]), "auto"),
                labelled("mortality ×", slider("mort", 0.2, 4.0, 0.1, DEFAULTS["mortality_scale"]), "auto"),
                labelled("selection pressure", slider("sel", 0.0, 2.0, 0.05, DEFAULTS["selection_pressure"]), "auto",
                         "couples mortality to a frailty proxy — the breeder's equation live"),
            ]),
            html.Div(style=CARD, children=[
                html.Div("GENETIC PROCESS", style={**LBL, "color": ACCENT, "marginBottom": "8px"}),
                labelled("mutation rate ×", slider("mut", 0.0, 40.0, 0.5, 1.0), "auto",
                         "EXPERIMENTAL multiplier on the Kong-2012 de novo rate"),
                labelled("recombination ×", slider("recomb", 0.2, 3.0, 0.1, 1.0), "auto",
                         "EXPERIMENTAL multiplier on deCODE map length (crossover freq)"),
                html.Div("SOCIAL STRUCTURE", style={**LBL, "color": ACCENT, "margin": "12px 0 8px"}),
                labelled("assortative mating", slider("assort", 0.0, 5.0, 0.1, 0.0), "auto",
                         "positive assortative mating on stature (Fisher 1918)"),
                labelled("inbreeding avoidance (max r)", slider("inbreed", 0.0625, 0.5, 0.0625, 0.5,
                         {0.0625: "cousins", 0.25: "half-sib", 0.5: "sib"}), "auto",
                         "reject pairs above this genomic relatedness (Wright 1922)"),
                labelled("inbreeding depression ×", slider("depress", 0.0, 2.0, 0.1, 1.0,
                         {0.0: "off", 1.0: "1.4 LE", 2.0: "2×"}), "auto",
                         "cost of homozygous recessive load at birth. 1.0 = the "
                         "calibrated 1.4 lethal equivalents per gamete "
                         "(Charlesworth & Willis 2009); 0 turns the fitness "
                         "cost off for an A/B run"),
                labelled("fertility schedule (Reset to apply)",
                         dcc.Dropdown(
                             id="fertsched",
                             options=[{"label": s.label, "value": k}
                                      for k, s in FERTILITY_SCHEDULES.items()],
                             value=DEFAULT_FERTILITY_SCHEDULE, clearable=False,
                             className="dk-dd", style={"fontSize": "12px"}),
                         "260px",
                         "shape of fecundability with MATERNAL AGE. "
                         "‘Legacy’ is the engine's original straight taper and "
                         "is the calibration baseline. ‘Pre-industrial’ is "
                         "Coale & Trussell 1974 natural fertility with "
                         "adolescent subfecundity; ‘Modern’ postpones births "
                         "into the late twenties and thirties. birth_rate "
                         "still sets the LEVEL — this only sets its shape"),
                html.Div(id="fertsched-blurb",
                         style={"color": MUTED, "fontSize": "11px",
                                "lineHeight": "1.5", "marginTop": "4px"}),
            ]),
            html.Div(style=CARD, children=[
                html.Div("COMMUNITY & RESOURCES", style={**LBL, "color": ACCENT, "marginBottom": "8px"}),
                labelled("demes (Reset to apply)", slider("ndemes", 1, 8, 1, DEFAULTS["n_demes"],
                         {1: "1", 4: "4", 8: "8"}), "auto",
                         "Wright 1931 island model: separate settlements that "
                         "pair within themselves and exchange migrants. The "
                         "default of 1 is deliberate — a single panmictic deme "
                         "is the reproducibility baseline (no structure means "
                         "no extra RNG draws), and it leaves F_ST undefined. "
                         "Raise this to make the community layer measurable; "
                         "founders are split across demes, so raise founders "
                         "too or small demes may fail to pair"),
                labelled("migration rate", slider("migr", 0.0, 0.3, 0.005, 0.0), "auto",
                         "annual P(an individual changes deme) — gene flow"),
                labelled("resource equity", slider("equity", 0.0, 1.0, 0.05, 1.0), "auto",
                         "1 = equal; below 1 concentrates resources in dominant lineages"),
                html.Div("LIFETIME EXPOSURES", style={**LBL, "color": ACCENT, "margin": "12px 0 8px"}),
                labelled("smoking", slider("smoke", 0.0, 1.0, 0.05, 0.0), "auto",
                         "drives AHRR hypomethylation (Joehanes 2016)"),
                labelled("chronic stress", slider("stress", 0.0, 1.0, 0.05, 0.0), "auto",
                         "pro-inflammatory hypomethylation + epigenetic ageing"),
                labelled("prenatal nutrition", slider("prenat", 0.0, 1.0, 0.05, 1.0), "auto",
                         "low = famine → IGF2 imprint (DOHaD, Heijmans 2008)"),
            ]),
        ]),
        html.Div(style={"display": "grid", "gridTemplateColumns": "2fr 1fr",
                        "gap": "12px"}, children=[
            html.Div(style=CARD, children=[
                html.Div("SCENARIO PRESETS", style={**LBL, "color": ACCENT, "marginBottom": "8px"}),
                html.Div(style={"display": "flex", "flexWrap": "wrap", "gap": "8px"},
                         children=[btn(s.title, f"preset-{s.key}") for s in scenario_list()]),
                html.Div(id="preset-blurb", style={"color": MUTED, "fontSize": "11px",
                                                   "marginTop": "10px", "minHeight": "28px"}),
                html.Div("SHOCKS  (fire on the next tick)",
                         style={**LBL, "color": CRIT, "margin": "14px 0 8px"}),
                labelled("shock magnitude", slider("shock-mag", 0.1, 1.0, 0.1, 0.7), "220px"),
                html.Div(style={"display": "flex", "gap": "8px", "marginTop": "8px"}, children=[
                    btn("☣ Plague", "shock-plague"),
                    btn("🌾 Famine", "shock-famine"),
                    btn("⧗ Bottleneck", "shock-bottleneck"),
                ]),
                html.Div(id="shock-msg", style={"color": WARN, "fontSize": "11px",
                                                "marginTop": "8px", "minHeight": "16px"}),
            ]),
            html.Div(style={**CARD, "maxHeight": "420px", "overflowY": "auto"}, children=[
                html.Div("GLOSSARY", style={**LBL, "marginBottom": "8px"}),
                html.Div(glossary_panel()),
            ]),
        ]),
    ]),

    # ---- INDIVIDUAL (a game-style character sheet) -------------------
    panel("panel-individual", children=[
        html.Div(id="char-header", style={**CARD, "marginBottom": "10px",
                                          "padding": "12px 14px"}),

        # ---- compare mode --------------------------------------------
        html.Div(style={**CARD, "marginBottom": "10px", "padding": "10px 14px",
                        "display": "flex", "alignItems": "center", "gap": "12px",
                        "flexWrap": "wrap"}, children=[
            html.Button("⇄ Compare mode", id="btn-compare", n_clicks=0, style={
                "background": "transparent", "border": f"1px solid {GRID}",
                "borderRadius": "999px", "color": INK2, "padding": "6px 15px",
                "fontSize": "12px", "fontWeight": 700, "cursor": "pointer"}),
            html.Div(id="cmp-picker-wrap", style={"display": "none",
                                                  "flex": 1, "minWidth": "220px"},
                     children=[
                dcc.Dropdown(id="cmp-picker", options=[], value=None,
                             placeholder="choose a second individual…",
                             className="dk-dd", style={"fontSize": "12px"}),
            ]),
            html.Div(id="cmp-note", style={"color": MUTED, "fontSize": "11px"}),
        ]),
        html.Div(id="cmp-section", style={"display": "none"}, children=[
            html.Div(style={"display": "grid",
                            "gridTemplateColumns": "minmax(0, 1fr) minmax(0, 1fr)",
                            "gap": "12px", "marginBottom": "12px"}, children=[
                html.Div(style=CARD, children=[graph("g-cmp-radar")]),
                html.Div(style={**CARD, "maxHeight": "440px",
                                "overflowY": "auto"}, id="cmp-table"),
            ]),
            html.Div(style={**CARD, "marginBottom": "12px"},
                     children=[graph("g-cmp-bars")]),
        ]),
        html.Div(style={"display": "flex", "gap": "4px", "borderBottom":
                 f"1px solid {GRID}", "marginBottom": "10px"},
                 children=[html.Button(CHAR_ICON[c], id=f"ctab-{c}", n_clicks=0,
                     style={"background": "transparent", "border": "none",
                            "borderBottom": "2px solid transparent", "color": MUTED,
                            "padding": "8px 14px", "cursor": "pointer",
                            "fontSize": "12px", "fontWeight": 600})
                     for c in CHAR_TABS]),
        # sub-panels (visibility toggled by char-tab); every graph stays in DOM
        html.Div(id="cpanel-info"),
        html.Div(id="cpanel-genetics", style={"display": "none"}),
        html.Div(id="cpanel-health", style={"display": "none"}),
        html.Div(id="cpanel-mind", style={"display": "none"}, children=[
            html.Div(style={"display": "grid", "gridTemplateColumns": "minmax(0, 1.2fr) minmax(0, 1fr)",
                            "gap": "10px"}, children=[
                html.Div(id="char-mind"),
                html.Div(style=CARD, children=[graph("g-indiv-radar")]),
            ])]),
        html.Div(id="cpanel-family", style={"display": "none"},
                 children=[html.Div(style=CARD, children=[graph("g-tree",
                     panels.tree_figure(WORLD, None))])]),
    ]),

    # ---- GUIDE -------------------------------------------------------
    panel("panel-guide", children=[html.Div(style=CARD, children=[guide_content()])]),

    # ---- TIMELINE SCRUBBER (fixed above the footer) ------------------
    # Sticky, so the scrubber is always reachable — but it must sit ABOVE the
    # panels (z-index) and the page needs bottom padding, or it overlays the
    # last card instead of floating clear of it.
    html.Div(style={**CARD, "marginTop": "14px", "padding": "10px 16px 4px",
                    "position": "sticky", "bottom": "10px", "zIndex": 60,
                    "backdropFilter": "blur(8px)",
                    "background": "rgba(20,22,28,0.96)",
                    "border": f"1px solid {GRID}",
                    "boxShadow": "0 -10px 30px rgba(0,0,0,0.65)"}, children=[
        html.Div(style={"display": "flex", "alignItems": "center",
                        "gap": "12px", "marginBottom": "2px"}, children=[
            html.Span("TIMELINE", style=LBL),
            html.Div(id="timeline-state", style={"fontSize": "11px",
                                                 "fontWeight": 700}),
            html.Div(style={"flex": 1}),
            btn("⏮ Live", "btn-live"),
        ]),
        html.Div(id="timeline-wrap", children=[
            dcc.Slider(id="timeline-slider", min=0, max=1, step=1, value=0,
                       marks=None, updatemode="mouseup",
                       tooltip={"placement": "top", "always_visible": False}),
        ]),
        html.Div(id="timeline-events", style={"color": MUTED, "fontSize": "10px",
                                              "minHeight": "14px",
                                              "paddingBottom": "4px"}),
    ]),
])


# =====================================================================
# Callbacks
# =====================================================================

@app.callback(
    Output("tick", "data"),
    Output("selected", "data", allow_duplicate=True),
    Input("timer", "n_intervals"),
    Input("btn-step", "n_clicks"),
    Input("btn-reset", "n_clicks"),
    State("seed", "value"), State("nfounders", "value"),
    [State(c, "value") for c in CTRL_INPUTS],
    State("selected", "data"),
    prevent_initial_call=True,
)
def advance(_n, _step, _reset, seed, nfounders, *rest):
    global WORLD
    *ctrl, selected = rest
    params = params_from_controls(*ctrl)
    trig = ctx.triggered_id
    if trig == "btn-reset":
        WORLD = build_world(seed or 7, nfounders or 10, params)
        return WORLD.tick, None
    # live-apply every non-structural knob, then advance one year
    keep_demes = WORLD.params.n_demes
    WORLD.params = replace(params, n_demes=keep_demes)  # demes only change on reset
    WORLD.step()
    return WORLD.tick, selected


@app.callback(
    Output("timer", "disabled"), Output("running", "data"),
    Output("btn-play", "children"), Output("btn-play", "style"),
    Output("run-state", "children"),
    Input("btn-play", "n_clicks"), State("running", "data"),
    prevent_initial_call=True,
)
def toggle_play(_n, running):
    running = not running
    base = {"borderRadius": "7px", "padding": "8px 14px", "cursor": "pointer",
            "fontWeight": 600, "fontSize": "12px", "border": f"1px solid {GRID}"}
    pill = {"padding": "5px 12px", "borderRadius": "999px", "fontSize": "11px",
            "fontWeight": 700, "letterSpacing": "0.06em"}
    if running:
        return (False, True, "⏸ Pause",
                {**base, "background": CRIT, "color": "#fff"},
                html.Span("● RUNNING", className="pulse",
                          style={**pill, "color": GOOD,
                                 "background": _rgba_hdr(GOOD, 0.12)}))
    return (True, False, "▶ Play",
            {**base, "background": ACCENT, "color": "#04121f"},
            html.Span("❚❚ PAUSED", style={**pill, "color": MUTED,
                                          "background": _rgba_hdr(MUTED, 0.12)}))


@app.callback(Output("timer", "interval"), Input("speed", "value"))
def set_speed(v):
    return int(1000 / max(0.5, float(v)))


@app.callback(Output("selected", "data", allow_duplicate=True),
              Input("g-scatter", "clickData"),
              prevent_initial_call=True)
def pick(scatter_click):
    # (World-Map clicks are handled in rts_map.js via dash_clientside.set_props)
    if not scatter_click:
        return no_update
    try:
        return scatter_click["points"][0]["customdata"][0]
    except (KeyError, IndexError, TypeError):
        return no_update


# ---- tab switching (store-driven, so a map click can open a tab too) ----
@app.callback(
    Output("active-tab", "data", allow_duplicate=True),
    [Input(f"tab-{t}", "n_clicks") for t in TABS],
    prevent_initial_call=True,
)
def set_active_tab(*_clicks):
    trig = ctx.triggered_id or "tab-overview"
    return trig.replace("tab-", "")


@app.callback(
    [Output(f"panel-{t}", "style") for t in TABS] +
    [Output(f"tab-{t}", "style") for t in TABS],
    Input("active-tab", "data"),
)
def apply_tab_styles(active):
    active = active or "overview"
    panel_styles = [{"display": "block" if t == active else "none"} for t in TABS]
    tab_styles = []
    for t in TABS:
        on = (t == active)
        tab_styles.append({
            "background": "transparent", "border": "none",
            "borderBottom": f"2px solid {ACCENT if on else 'transparent'}",
            "color": INK if on else MUTED, "padding": "10px 16px",
            "cursor": "pointer", "fontSize": "13px", "fontWeight": 600})
    return panel_styles + tab_styles


# ---- scenario presets ----------------------------------------------
@app.callback(
    [Output(c, "value") for c in CTRL_INPUTS] +
    [Output("seed", "value"), Output("nfounders", "value"),
     Output("tick", "data", allow_duplicate=True),
     Output("selected", "data", allow_duplicate=True),
     Output("preset-blurb", "children")],
    [Input(f"preset-{s.key}", "n_clicks") for s in scenario_list()],
    prevent_initial_call=True,
)
def apply_preset(*_clicks):
    global WORLD
    trig = ctx.triggered_id
    if not trig:
        return no_update
    key = trig.replace("preset-", "")
    scen = SCENARIOS[key]
    p = scen.params
    WORLD = build_world(DEFAULTS["seed"], scen.n_founders, p)
    vals = [p.carrying_capacity, p.birth_rate, p.mortality_scale,
            p.selection_pressure, p.mutation_rate_scale, p.recombination_scale,
            p.assortative_strength, p.inbreeding_threshold, p.n_demes,
            p.migration_rate, p.resource_equity, p.exposure_smoking,
            p.exposure_stress, p.exposure_prenatal_nutrition,
            p.inbreeding_depression,
            getattr(p, "fertility_schedule", DEFAULT_FERTILITY_SCHEDULE)]
    return vals + [DEFAULTS["seed"], scen.n_founders, WORLD.tick, None,
                   f"“{scen.title}” — {scen.blurb}"]


# ---- shocks ---------------------------------------------------------
@app.callback(
    Output("shock-msg", "children"),
    Input("shock-plague", "n_clicks"), Input("shock-famine", "n_clicks"),
    Input("shock-bottleneck", "n_clicks"),
    State("shock-mag", "value"),
    prevent_initial_call=True,
)
def fire_shock(_p, _f, _b, mag):
    trig = ctx.triggered_id
    if not trig:
        return no_update
    kind = trig.replace("shock-", "")
    WORLD.queue_shock(kind, float(mag))
    return f"{kind.capitalize()} queued (magnitude {mag:.1f}) — fires on the next tick."


# ---- always-on rendering (header, KPIs, chronicle, summary) --------
@app.callback(
    Output("kpi-row", "children"), Output("headline", "children"),
    Output("ticker", "children"), Output("chronicle", "children"),
    Output("summary-banner", "children"),
    Input("tick", "data"),
)
def render_always(_tick):
    cols = WORLD.history_columns()
    r = WORLD.history[-1] if WORLD.history else {}
    # F_ST reads "—" in a single-deme world for the same reason the KPI tile
    # and the Community chart do: there is no partition to estimate over, and
    # printing 0.000 would assert a measurement that was never made.
    fst_txt = (f"{r.get('fst', 0):.3f}" if WORLD.params.n_demes > 1 else "—")
    headline = (f"year {int(r.get('tick', 0))} · {int(r.get('n_alive', 0))} alive · "
                f"gen {int(r.get('max_generation', 0))} · "
                f"{int(r.get('n_couples', 0))} couples · "
                f"H {r.get('heterozygosity', 0):.3f} · F_ST {fst_txt}")
    recent = WORLD.chronicle.recent(3)
    ticker = "  ·  ".join(f"y{e.tick} {e.text}" for e in recent) if recent else \
        "the chronicle will narrate notable events as they happen"
    return (kpi_row(cols), headline, ticker,
            chronicle_feed(WORLD.chronicle.recent(16)), decade_banner())


# ---- per-tab figure rendering --------------------------------------
@app.callback(
    Output("g-scatter", "figure"), Output("g-pop", "figure"),
    Output("g-bd", "figure"), Output("g-div-o", "figure"),
    Input("tick", "data"), Input("selected", "data"), Input("active-tab", "data"),
    Input("timeline", "data"),
)
def render_overview(_tick, selected, active, scrub):
    if active != "overview":
        return (no_update,) * 4
    cols = panels.history_columns_upto(WORLD, scrub)
    scatter = (panels.scatter_figure_from_frame(WORLD, WORLD.frame_at(scrub), selected)
               if scrub is not None
               else panels.scatter_figure(WORLD, selected))
    return (scatter,
            panels.population_figure(cols),
            panels.births_deaths_figure(cols),
            panels.diversity_figure(cols))


@app.callback(
    Output("mapdata", "data"), Output("map-legend", "children"),
    Input("tick", "data"), Input("selected", "data"), Input("active-tab", "data"),
    Input("timeline", "data"), Input("map-layer", "data"),
)
def render_map(_tick, selected, active, scrub, layer):
    if active != "map":
        return no_update, no_update
    frame = WORLD.frame_at(scrub)
    return (build_mapdata(WORLD, selected, frame, layer or "default",
                          historical=scrub is not None),
            lineage_legend_view())


# the clientside canvas renderer (rts_map.js) draws the map from `mapdata`
app.clientside_callback(
    ClientsideFunction(namespace="extnpc", function_name="renderMap"),
    Output("rts-sink", "children"),
    Input("mapdata", "data"),
)


@app.callback(
    Output("g-traits", "figure"), Output("g-pop-radar", "figure"),
    Output("g-div-g", "figure"), Output("g-cand", "figure"),
    Output("g-skew", "figure"),
    Output("g-spectrum", "figure"), Output("g-het-hist", "figure"),
    Output("g-trait-dist", "figure"), Output("g-pyramid", "figure"),
    Output("g-mutload", "figure"), Output("g-imprint", "figure"),
    Output("g-sexlink", "figure"), Output("g-mito", "figure"),
    Output("g-epiage", "figure"),
    Input("tick", "data"), Input("active-tab", "data"), Input("timeline", "data"),
)
def render_genetics(_tick, active, scrub):
    """
    Thirteen figures, five from the history buffer and eight measured off the
    living population.

    The distribution panels have no historical counterpart: the snapshot buffer
    keeps ~12 scalars per person, not genomes, so an allele spectrum or an
    imprinting breakdown for a past year cannot be reconstructed. Under time
    travel the time-series charts rewind and the distributions keep showing the
    live population, which is the honest behaviour -- the alternative is
    inventing data or blanking half the tab.
    """
    if active != "genetics":
        return (no_update,) * 14
    cols = panels.history_columns_upto(WORLD, scrub)
    return (panels.traits_figure(cols),
            panels.population_radar_figure(WORLD),
            panels.diversity_figure(cols),
            panels.candlestick_figure(cols),
            panels.skew_figure(cols),
            gpanels.allele_spectrum_figure(WORLD),
            gpanels.heterozygosity_hist_figure(WORLD),
            gpanels.trait_distribution_figure(WORLD, "height_cm"),
            gpanels.age_pyramid_figure(WORLD),
            gpanels.mutation_load_figure(WORLD),
            gpanels.imprinting_figure(WORLD),
            gpanels.sex_linked_figure(WORLD),
            gpanels.mito_haplogroup_figure(WORLD),
            gpanels.epigenetic_age_figure(WORLD))


@app.callback(
    Output("g-fst", "figure"), Output("g-deme", "figure"),
    Output("g-inbreed", "figure"),
    Output("g-spiral", "figure"), Output("g-lin", "figure"),
    Output("g-rel", "figure"),
    Input("tick", "data"), Input("active-tab", "data"), Input("timeline", "data"),
)
def render_community(_tick, active, scrub):
    if active != "community":
        return (no_update,) * 6
    cols = panels.history_columns_upto(WORLD, scrub)
    return (panels.fst_figure(cols, WORLD.params.n_demes),
            panels.deme_bar_figure(WORLD),
            panels.inbreeding_figure(cols),
            panels.spiral_figure(cols),
            panels.lineage_figure(WORLD),
            panels.relatedness_figure(cols))


@app.callback(
    Output("char-header", "children"), Output("cpanel-info", "children"),
    Output("cpanel-genetics", "children"), Output("cpanel-health", "children"),
    Output("char-mind", "children"), Output("g-indiv-radar", "figure"),
    Output("g-tree", "figure"),
    Input("tick", "data"), Input("selected", "data"), Input("active-tab", "data"),
)
def render_individual(_tick, selected, active):
    if active != "individual":
        return (no_update,) * 7
    if not selected or selected not in WORLD.people:
        return (_EMPTY, _EMPTY, _EMPTY, _EMPTY, _EMPTY,
                panels.individual_radar_figure(WORLD, None),
                panels.tree_figure(WORLD, None))
    return (char_header(selected), char_info(selected), char_genetics(selected),
            char_health(selected), char_mind(selected),
            panels.individual_radar_figure(WORLD, selected),
            panels.tree_figure(WORLD, selected))


# ---- character-sheet sub-tabs (Info / Genetics / Health / Mind / Family) --
@app.callback(
    Output("char-tab", "data"),
    [Input(f"ctab-{c}", "n_clicks") for c in CHAR_TABS],
    prevent_initial_call=True,
)
def set_char_tab(*_clicks):
    trig = ctx.triggered_id or "ctab-info"
    return trig.replace("ctab-", "")


@app.callback(
    [Output(f"cpanel-{c}", "style") for c in CHAR_TABS] +
    [Output(f"ctab-{c}", "style") for c in CHAR_TABS],
    Input("char-tab", "data"),
)
def apply_char_styles(active):
    active = active or "info"
    panel_styles = [{"display": "block" if c == active else "none"} for c in CHAR_TABS]
    tab_styles = []
    for c in CHAR_TABS:
        on = (c == active)
        tab_styles.append({
            "background": "transparent", "border": "none",
            "borderBottom": f"2px solid {ACCENT if on else 'transparent'}",
            "color": INK if on else MUTED, "padding": "8px 14px",
            "cursor": "pointer", "fontSize": "12px", "fontWeight": 600})
    return panel_styles + tab_styles


# =====================================================================
# Persistent inspector drawer  (feature 1)
# =====================================================================
# One callback fans identical content into every drawer instance, so the
# copies cannot drift apart. Keeping all three in the DOM is what lets a
# single Output list address them without conditional layouts.

@app.callback(
    [Output(f"drawer-{s}", "children") for s in DRAWERS],
    Input("selected", "data"), Input("tick", "data"), Input("timeline", "data"),
)
def render_drawer(selected, _tick, scrub):
    frame = WORLD.frame_at(scrub)
    card = inspector.summary_card(WORLD, selected, frame,
                                  historical=scrub is not None)
    return [card] * len(DRAWERS)


@app.callback(
    Output("drawer-mode", "data"),
    [Input(f"dmode-extremes-{s}", "n_clicks") for s in DRAWERS] +
    [Input(f"dmode-directory-{s}", "n_clicks") for s in DRAWERS],
    prevent_initial_call=True,
)
def set_drawer_mode(*_clicks):
    trig = str(ctx.triggered_id or "")
    return "directory" if trig.startswith("dmode-directory") else "extremes"


@app.callback(
    [Output(f"dirtools-{s}", "style") for s in DRAWERS] +
    [Output(f"dmode-extremes-{s}", "style") for s in DRAWERS] +
    [Output(f"dmode-directory-{s}", "style") for s in DRAWERS],
    Input("drawer-mode", "data"),
)
def style_drawer_mode(mode):
    directory = (mode == "directory")
    base = {"flex": 1, "borderRadius": "7px", "padding": "5px",
            "fontSize": "11px", "fontWeight": 700, "cursor": "pointer"}
    on = {**base, "background": _rgba_hdr(ACCENT, 0.16),
          "border": f"1px solid {ACCENT}", "color": ACCENT}
    off = {**base, "background": "transparent",
           "border": f"1px solid {GRID}", "color": INK2}
    tools = {"display": "block" if directory else "none"}
    return ([tools] * len(DRAWERS)
            + [(off if directory else on)] * len(DRAWERS)
            + [(on if directory else off)] * len(DRAWERS))


@app.callback(
    Output("fertsched-blurb", "children"),
    Input("fertsched", "value"),
)
def describe_fertility_schedule(key):
    """Say what the chosen curve implies and where it comes from, so the
    control is a modelling decision rather than an unlabelled preference."""
    spec = FERTILITY_SCHEDULES.get(key or DEFAULT_FERTILITY_SCHEDULE)
    if spec is None:
        return ""
    return (f"implied mean maternal age {mean_reproductive_age(spec.name):.1f} y "
            f"· {spec.citation}")


def sort_is_descending(n_clicks) -> bool:
    """
    Direction from the toggle's click count: even = descending (the original
    behaviour and the sensible default for "oldest", "most inbred"), odd =
    ascending. Parity is used rather than a `dcc.Store` because the direction
    is pure UI state with no meaning to the world -- adding a Store would put
    it in the layout, the callback graph and every snapshot for nothing.
    """
    return int(n_clicks or 0) % 2 == 0


@app.callback(
    [Output(f"dlist-{s}", "children") for s in DRAWERS],
    Input("drawer-mode", "data"), Input("tick", "data"),
    Input("timeline", "data"), Input("selected", "data"),
    [Input(f"dirq-{s}", "value") for s in DRAWERS],
    [Input(f"dirsort-{s}", "value") for s in DRAWERS],
    [Input(f"dirdir-{s}", "n_clicks") for s in DRAWERS],
)
def render_drawer_list(mode, _tick, scrub, selected, *rest):
    frame = WORLD.frame_at(scrub)
    if mode == "directory":
        n = len(DRAWERS)
        queries, sorts, dirs = rest[:n], rest[n:2 * n], rest[2 * n:3 * n]
        # each drawer keeps its own filter box, sort and direction
        return [inspector.directory_rows(frame, q or "", s or "age",
                                         selected=selected,
                                         descending=sort_is_descending(d))
                for q, s, d in zip(queries, sorts, dirs)]
    view = inspector.leaderboard_view(frame, selected)
    return [view] * len(DRAWERS)


@app.callback(
    [Output(f"dirdir-{s}", "children") for s in DRAWERS],
    [Output(f"dirdir-{s}", "title") for s in DRAWERS],
    [Input(f"dirdir-{s}", "n_clicks") for s in DRAWERS],
)
def label_sort_direction(*clicks):
    """Arrow and tooltip follow the direction, so the control says what it
    will do rather than what it just did."""
    arrows, titles = [], []
    for c in clicks:
        desc = sort_is_descending(c)
        arrows.append("↓" if desc else "↑")
        titles.append("sorting descending — click for ascending" if desc else
                      "sorting ascending — click for descending")
    return arrows + titles


@app.callback(
    Output("selected", "data", allow_duplicate=True),
    Input({"type": "board-pick", "name": ALL}, "n_clicks"),
    Input({"type": "dir-pick", "name": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def pick_from_list(_b, _d):
    """
    Clicking any leaderboard or directory row selects that individual.

    The obvious guard -- trust `n_clicks` -- does not work here, and it took a
    server-side trace to see why. The list is rebuilt on every tick, so each
    rebuild hands React fresh buttons with n_clicks back at 0; a genuine click
    therefore arrives reporting `value: 0`, indistinguishable from an untouched
    button.

    What *does* separate them is the shape of the trigger. Re-rendering the
    list fires this callback with EVERY button in `ctx.triggered` (10-12
    entries, all zero); a real click fires it with exactly one. So the arity of
    the trigger is the signal, not the value.
    """
    if len(ctx.triggered) != 1:
        return no_update                      # a list rebuild, not a click
    trig = ctx.triggered_id
    if not isinstance(trig, dict):
        return no_update
    name = trig.get("name")
    # only select someone who actually exists in this run
    return name if name and name in WORLD.people else no_update


# =====================================================================
# Timeline scrubber  (feature 3)
# =====================================================================

@app.callback(
    Output("timeline-slider", "max"), Output("timeline-slider", "min"),
    Output("timeline-slider", "marks"), Output("timeline-slider", "value"),
    Output("slider-echo", "data"),
    Input("tick", "data"), Input("timeline", "data"),
)
def sync_timeline(_tick, scrub):
    lo, hi = WORLD.snapshots.first_tick, max(WORLD.snapshots.last_tick, 1)
    marks = {}
    step = max(1, (hi - lo) // 8)
    for t in range(lo, hi + 1, step):
        marks[int(t)] = {"label": str(int(t)),
                         "style": {"color": MUTED, "fontSize": "9px"}}
    # event markers take precedence over the regular ticks
    icons = {"plague": "☣", "famine": "🌾", "bottleneck": "⧗"}
    for e in WORLD.event_log:
        t = int(e["tick"])
        if lo <= t <= hi:
            marks[t] = {"label": icons.get(e["kind"], "◆"),
                        "style": {"color": CRIT, "fontSize": "12px"}}
    value = hi if scrub is None else scrub
    # record what we wrote, so set_timeline can ignore the echo
    return hi, lo, marks, value, value


@app.callback(
    Output("timeline", "data"),
    Input("timeline-slider", "value"), Input("btn-live", "n_clicks"),
    Input("btn-reset", "n_clicks"),
    State("slider-echo", "data"),
    prevent_initial_call=True,
)
def set_timeline(value, _live, _reset, echo):
    if ctx.triggered_id in ("btn-live", "btn-reset"):
        return None
    if value is None:
        return no_update
    # Ignore our own redraw. Comparing to `echo` rather than to
    # snapshots.last_tick matters: under fast stepping the world advances
    # between the write and the echo, so a last_tick comparison sees a stale
    # value, decides the user scrubbed backwards, and freezes the dashboard in
    # the past. That bug was live until this guard.
    if echo is not None and int(value) == int(echo):
        return no_update
    return None if int(value) >= WORLD.snapshots.last_tick else int(value)


@app.callback(
    Output("timeline-state", "children"), Output("timeline-events", "children"),
    Input("timeline", "data"), Input("tick", "data"),
)
def render_timeline_state(scrub, _tick):
    if scrub is None:
        state = html.Span("● LIVE", style={"color": GOOD})
    else:
        state = html.Span(f"⏱ VIEWING YEAR {scrub} — press Live to return",
                          style={"color": WARN})
    if not WORLD.event_log:
        note = ("Drag to replay the run. Charts rebuild from history; the map "
                "rebuilds from the snapshot buffer.")
    else:
        note = "events:  " + "   ".join(
            f"y{e['tick']} {e['label']}" for e in WORLD.event_log[-6:])
    return state, note


# =====================================================================
# Map layer selector  (feature 6)
# =====================================================================

@app.callback(
    Output("map-layer", "data"),
    [Input(f"layer-{k}", "n_clicks") for k, _, _ in MAP_LAYERS],
    prevent_initial_call=True,
)
def set_map_layer(*_clicks):
    return str(ctx.triggered_id or "layer-default").replace("layer-", "")


@app.callback(
    [Output(f"layer-{k}", "style") for k, _, _ in MAP_LAYERS] +
    [Output("layer-hint", "children")],
    Input("map-layer", "data"),
)
def style_map_layer(active):
    active = active or "default"
    base = {"borderRadius": "999px", "padding": "5px 13px", "fontSize": "11px",
            "fontWeight": 700, "cursor": "pointer"}
    styles, hint = [], ""
    for key, _label, h in MAP_LAYERS:
        if key == active:
            styles.append({**base, "background": _rgba_hdr(ACCENT, 0.18),
                           "border": f"1px solid {ACCENT}", "color": ACCENT})
            hint = h
        else:
            styles.append({**base, "background": "transparent",
                           "border": f"1px solid {GRID}", "color": INK2})
    return styles + [hint]


# =====================================================================
# Comparative character matrix  (feature 2)
# =====================================================================

@app.callback(
    Output("cmp-on", "data"), Input("btn-compare", "n_clicks"),
    State("cmp-on", "data"), prevent_initial_call=True,
)
def toggle_compare(_n, on):
    return not bool(on)


@app.callback(
    Output("btn-compare", "style"), Output("cmp-picker-wrap", "style"),
    Output("cmp-section", "style"), Output("cmp-picker", "options"),
    Output("cmp-note", "children"),
    Input("cmp-on", "data"), Input("tick", "data"), Input("selected", "data"),
)
def sync_compare(on, _tick, selected):
    base = {"borderRadius": "999px", "padding": "6px 15px", "fontSize": "12px",
            "fontWeight": 700, "cursor": "pointer"}
    if not on:
        return ({**base, "background": "transparent",
                 "border": f"1px solid {GRID}", "color": INK2},
                {"display": "none"}, {"display": "none"}, [],
                "Compare two individuals side by side — traits, set-points "
                "and their genomic relatedness.")
    opts = [{"label": f"{n.name.split('-')[0]} · {n.sex} · age {n.age}",
             "value": n.name}
            for n in sorted(WORLD.living, key=lambda p: p.name)
            if n.name != selected]
    note = ("Agent A is the selected individual."
            if selected else "Select someone first — they become Agent A.")
    return ({**base, "background": _rgba_hdr(ACCENT, 0.18),
             "border": f"1px solid {ACCENT}", "color": ACCENT},
            {"display": "block", "flex": 1, "minWidth": "220px"},
            {"display": "block"}, opts, note)


@app.callback(
    Output("cmp-b", "data"), Input("cmp-picker", "value"),
    prevent_initial_call=True,
)
def set_compare_b(value):
    return value


@app.callback(
    Output("cmp-table", "children"), Output("g-cmp-radar", "figure"),
    Output("g-cmp-bars", "figure"),
    Input("cmp-on", "data"), Input("cmp-b", "data"), Input("selected", "data"),
    Input("tick", "data"), Input("active-tab", "data"),
)
def render_compare(on, b, a, _tick, active):
    if not on or active != "individual":
        return no_update, no_update, no_update
    return (inspector.compare_table(WORLD, a, b),
            panels.compare_radar_figure(WORLD, a, b),
            panels.compare_bars_figure(WORLD, a, b))


if __name__ == "__main__":
    app.run(debug=False, port=8050)
