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

from dash import (Dash, dcc, html, Input, Output, State, ctx, no_update,
                  ClientsideFunction)

from simulation import (World, DemographyParams, SCENARIOS, scenario_list,
                        SHOCK_KINDS, GLOSSARY)
from . import panels

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
                         n_demes, migr, equity, smoke, stress, prenat
                         ) -> DemographyParams:
    return DemographyParams(
        carrying_capacity=int(K), birth_rate=float(birth),
        mortality_scale=float(mort), selection_pressure=float(sel),
        mutation_rate_scale=float(mut), recombination_scale=float(recomb),
        assortative_strength=float(assort), inbreeding_threshold=float(inbreed),
        n_demes=int(n_demes), migration_rate=float(migr),
        resource_equity=float(equity), exposure_smoking=float(smoke),
        exposure_stress=float(stress), exposure_prenatal_nutrition=float(prenat))


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
    return dcc.Graph(id=id_, config={"displayModeBar": False},
                     figure=fig or {})


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
                           "gridTemplateColumns": "1fr 1fr", "gap": "10px"}, children=[
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
        _section("APPEARANCE", [
            _row("height", f"{npc.phenotype()['height_cm']:.1f} cm"),
            _row("BMI", f"{npc.phenotype()['bmi']:.1f}"),
            _row("eye colour", npc.phenotype().get("eye_color", "?")),
            _row("skin tone", f"{npc.phenotype()['skin_tone']:+.2f}"),
            _row("handedness", npc.phenotype().get("handedness", "?"))]),
    ])


def char_genetics(name):
    npc = WORLD.people[name]
    ph = npc.phenotype()
    mito = npc.mito_phenotype()
    xl = npc.x_linked_phenotype()
    return html.Div(style={"display": "grid",
                           "gridTemplateColumns": "1fr 1fr", "gap": "10px"}, children=[
        _section("GENOME", [
            _row("heterozygosity", f"{npc.heterozygosity():.3f}"),
            _row("de novo mutations", npc.de_novo_mutations),
            _row("mito haplogroup", mito.get("haplogroup", "—")),
            _row("mtDNA heteroplasmy", f"{mito.get('heteroplasmy', 0):.2f}"),
            _row("OXPHOS capacity", f"{mito.get('oxphos_capacity', 1):.2f}")]),
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
                           "gridTemplateColumns": "1fr 1fr", "gap": "10px"}, children=[
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


def build_mapdata(world, selected):
    """Compact JSON payload the canvas renderer (rts_map.js) draws from."""
    demes = [{"id": d["deme"], "label": d["label"].split("-")[0],
              "x": d["x"], "y": d["y"], "r": d["radius"], "n": d["n"],
              "color": panels.deme_color(d["deme"])}
             for d in world.map_demes()]
    people = [{"name": p["name"], "x": p["map_x"], "y": p["map_y"],
               "color": p["color"], "sex": p["sex"]}
              for p in world.living_frame()]
    flows = [{"x0": f["x0"], "y0": f["y0"], "x1": f["x1"], "y1": f["y1"],
              "w": f["weight"]} for f in world.map_flows()]
    return {"size": 100, "seed": int(world.seed), "demes": demes,
            "people": people, "flows": flows, "selected": selected}


def lineage_legend_view():
    swatches = panels.lineage_legend(WORLD)
    rows = [html.Div("BLOODLINES", style={**LBL, "marginBottom": "8px"})]
    for name, hexc in swatches:
        rows.append(html.Div([
            html.Span(style={"display": "inline-block", "width": "11px",
                             "height": "11px", "borderRadius": "3px",
                             "background": hexc, "marginRight": "7px"}),
            html.Span(name.split("-")[0], style={"fontSize": "12px", "color": INK2}),
        ], style={"marginBottom": "4px"}))
    return rows


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

        html.Div(style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "12px"},
                 children=[
            _g("① Get started", _steps([
                "Press ▶ Play (top-left) to run time. Use ⏭ Step for one year, "
                "⟲ Reset to restart with the current settings.",
                "Set speed, random seed and founder count in the transport bar. "
                "Seed + settings fully determine a run — the same seed replays exactly.",
                "Click any person — on the World Map or the Overview genetic map — "
                "to open their full profile in the Individual tab.",
            ])),
            _g("② Read the KPI strip", [
                "The eight tiles under the transport bar track the population at a "
                "glance; hover any tile for its definition and citation. The arrow "
                "shows the 10-year trend. Watch ", html.B("Diversity H"),
                " fall as the population inbreeds, ", html.B("F_ST"),
                " rise as communities isolate, and ", html.B("Kinship"),
                " climb when unrelated mates run out.",
            ]),
            _g("③ The tabs", [
                html.Div([html.B("🗺 World Map — "),
                          "settlements, territories and people in space; migration "
                          "routes show gene flow. Click a unit to inspect it."]),
                html.Div([html.B("🧬 Genetics — "),
                          "trait evolution, a diversity threshold, a per-decade "
                          "volatility candlestick and a population phenotype radar."]),
                html.Div([html.B("🌍 Community — "),
                          "F_ST, per-deme headcount, a history spiral, bloodlines "
                          "and couple-kinship: the island model made visible."]),
                html.Div([html.B("👤 Individual — "),
                          "one person's profile, their fingerprint vs the population, "
                          "and their family tree."]),
            ]),
            _g("④ Drive evolution (Controls)", [
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
            _g("⑤ What to look for (the science)", [
                html.Div("• Genetic drift: diversity H sags as a small closed "
                         "population descends from a few founders."),
                html.Div("• Lineage dominance & extinction: a few bloodlines take "
                         "over the headcount while others vanish."),
                html.Div("• Isolation by distance: with several demes and low "
                         "migration, F_ST climbs toward Wright's 1/(4Nₑm+1)."),
                html.Div("• The breeder's equation: turn up selection and watch "
                         "the trait means move."),
            ]),
            _g("⑥ Presets to try", [
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


CTRL_INPUTS = ["K", "birth", "mort", "sel", "mut", "recomb", "assort",
               "inbreed", "ndemes", "migr", "equity", "smoke", "stress", "prenat"]


app.layout = html.Div(style={
    "background": f"radial-gradient(1200px 600px at 20% -10%, #14161c 0%, {PLANE} 60%)",
    "minHeight": "100vh", "padding": "14px 18px",
    "fontFamily": 'system-ui, "Segoe UI", sans-serif', "color": INK}, children=[

    dcc.Store(id="tick", data=WORLD.tick),
    dcc.Store(id="selected", data=None),
    dcc.Store(id="running", data=False),
    dcc.Store(id="active-tab", data="overview"),
    dcc.Store(id="char-tab", data="info"),
    dcc.Store(id="shock-log", data=0),
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
        html.Div(style={"display": "grid", "gridTemplateColumns": "1.7fr 1fr",
                        "gap": "12px", "marginBottom": "12px"}, children=[
            html.Div(style=CARD, children=[graph("g-scatter",
                     panels.scatter_figure(WORLD))]),
            html.Div(style={**CARD, "maxHeight": "540px", "overflowY": "auto"},
                     children=[
                html.Div("CHRONICLE", style={**LBL, "marginBottom": "8px"}),
                html.Div(id="chronicle"),
            ]),
        ]),
        html.Div(style={"display": "grid", "gridTemplateColumns": "1fr 1fr 1fr",
                        "gap": "12px"}, children=[
            html.Div(style=CARD, children=[graph("g-pop")]),
            html.Div(style=CARD, children=[graph("g-bd")]),
            html.Div(style=CARD, children=[graph("g-div-o")]),
        ]),
    ]),

    # ---- WORLD MAP ---------------------------------------------------
    panel("panel-map", children=[
        dcc.Store(id="mapdata"),
        html.Div(id="rts-sink", style={"display": "none"}),
        html.Div(style={"display": "grid", "gridTemplateColumns": "3fr 1fr",
                        "gap": "12px"}, children=[
            html.Div(style={**CARD, "background": "#0f1216", "padding": "6px"},
                     children=[
                html.Canvas(id="rts-canvas",
                            style={"width": "100%", "height": "620px",
                                   "display": "block", "borderRadius": "8px",
                                   "imageRendering": "pixelated"}),
                html.Div("Art: Kenney “Tiny Town” (CC0) · villagers team-tinted "
                         "by bloodline · click a villager to inspect",
                         style={"color": MUTED, "fontSize": "10px",
                                "textAlign": "center", "padding": "4px"}),
            ]),
            html.Div(style={"display": "flex", "flexDirection": "column", "gap": "12px"},
                     children=[
                html.Div(id="map-legend", style={**CARD, "maxHeight": "300px",
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
    panel("panel-genetics", children=[
        html.Div(style={"display": "grid", "gridTemplateColumns": "1.4fr 1fr",
                        "gap": "12px", "marginBottom": "12px"}, children=[
            html.Div(style=CARD, children=[graph("g-traits")]),
            html.Div(style=CARD, children=[graph("g-pop-radar")]),
        ]),
        html.Div(style={"display": "grid", "gridTemplateColumns": "1fr 1fr 1fr",
                        "gap": "12px"}, children=[
            html.Div(style=CARD, children=[graph("g-div-g")]),
            html.Div(style=CARD, children=[graph("g-cand")]),
            html.Div(style=CARD, children=[graph("g-skew")]),
        ]),
    ]),

    # ---- COMMUNITY ---------------------------------------------------
    panel("panel-community", children=[
        html.Div(style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                        "gap": "12px", "marginBottom": "12px"}, children=[
            html.Div(style=CARD, children=[graph("g-fst")]),
            html.Div(style=CARD, children=[graph("g-deme")]),
        ]),
        html.Div(style={"display": "grid", "gridTemplateColumns": "1fr 1fr 1fr",
                        "gap": "12px"}, children=[
            html.Div(style=CARD, children=[graph("g-spiral")]),
            html.Div(style=CARD, children=[graph("g-lin")]),
            html.Div(style=CARD, children=[graph("g-rel")]),
        ]),
    ]),

    # ---- CONTROLS ----------------------------------------------------
    panel("panel-controls", children=[
        html.Div(style={"display": "grid", "gridTemplateColumns": "1fr 1fr 1fr",
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
            ]),
            html.Div(style=CARD, children=[
                html.Div("COMMUNITY & RESOURCES", style={**LBL, "color": ACCENT, "marginBottom": "8px"}),
                labelled("demes (Reset to apply)", slider("ndemes", 1, 8, 1, DEFAULTS["n_demes"],
                         {1: "1", 4: "4", 8: "8"}), "auto"),
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
            html.Div(style={"display": "grid", "gridTemplateColumns": "1.2fr 1fr",
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
            p.exposure_stress, p.exposure_prenatal_nutrition]
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
    headline = (f"year {int(r.get('tick', 0))} · {int(r.get('n_alive', 0))} alive · "
                f"gen {int(r.get('max_generation', 0))} · "
                f"{int(r.get('n_couples', 0))} couples · "
                f"H {r.get('heterozygosity', 0):.3f} · F_ST {r.get('fst', 0):.3f}")
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
)
def render_overview(_tick, selected, active):
    if active != "overview":
        return (no_update,) * 4
    cols = WORLD.history_columns()
    return (panels.scatter_figure(WORLD, selected),
            panels.population_figure(cols),
            panels.births_deaths_figure(cols),
            panels.diversity_figure(cols))


@app.callback(
    Output("mapdata", "data"), Output("map-legend", "children"),
    Input("tick", "data"), Input("selected", "data"), Input("active-tab", "data"),
)
def render_map(_tick, selected, active):
    if active != "map":
        return no_update, no_update
    return build_mapdata(WORLD, selected), lineage_legend_view()


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
    Input("tick", "data"), Input("active-tab", "data"),
)
def render_genetics(_tick, active):
    if active != "genetics":
        return (no_update,) * 5
    cols = WORLD.history_columns()
    return (panels.traits_figure(cols),
            panels.population_radar_figure(WORLD),
            panels.diversity_figure(cols),
            panels.candlestick_figure(cols),
            panels.skew_figure(cols))


@app.callback(
    Output("g-fst", "figure"), Output("g-deme", "figure"),
    Output("g-spiral", "figure"), Output("g-lin", "figure"),
    Output("g-rel", "figure"),
    Input("tick", "data"), Input("active-tab", "data"),
)
def render_community(_tick, active):
    if active != "community":
        return (no_update,) * 5
    cols = WORLD.history_columns()
    return (panels.fst_figure(cols, WORLD.params.n_demes),
            panels.deme_bar_figure(WORLD),
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


if __name__ == "__main__":
    app.run(debug=False, port=8050)
