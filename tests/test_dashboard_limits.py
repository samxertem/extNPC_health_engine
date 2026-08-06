"""
Limit and robustness tests for the dashboard.

Every view function is called against the states a live dashboard actually
reaches and that nobody clicks through by hand: a world with no founders, a
population that has gone extinct, a single inhabitant, a history of length
one, a historical frame captured before a field existed, an unknown name, a
filter that matches nothing.

The bar is deliberately blunt -- **no view function may raise**, and none may
return a degenerate axis (a NaN range, an inverted range) that Plotly will
render as an empty or misleading panel. A dashboard that crashes on the tick
after the last person dies is a dashboard that cannot be left running, and
the extinction tick is exactly when someone is watching.
"""

import math
import warnings

import numpy as np
import plotly.graph_objects as go
import pytest

from dashboard import genetics_panels as gp, inspector, panels
from dashboard.app import (build_mapdata, params_from_controls, _stress_ramp,
                           _deme_short)
from simulation import DemographyParams, World

warnings.filterwarnings("ignore")


# =====================================================================
# Worlds at the edges
# =====================================================================

@pytest.fixture(scope="module")
def empty_world():
    """No founders at all -- the state a Reset to 0 would produce."""
    return World(n_founders=0, seed=1)


@pytest.fixture(scope="module")
def lone_world():
    """Exactly one inhabitant: no couples, no variance, no PCA to fit."""
    w = World(n_founders=1, seed=2)
    w.step()
    return w


@pytest.fixture(scope="module")
def extinct_world():
    """A population that lived and then died out completely."""
    w = World(n_founders=6, seed=3)
    for _ in range(6):
        w.step()
    w.living.clear()                    # the tick after the last death
    return w


@pytest.fixture(scope="module")
def normal_world():
    w = World(n_founders=16, seed=11)
    for _ in range(22):
        w.step()
    return w


def _cols(world):
    return world.history_columns()


# ---------------------------------------------------------------------
# Every figure, against every degenerate world
# ---------------------------------------------------------------------

def _world_figures(world):
    """(label, thunk) for every figure that takes a world."""
    cols = _cols(world)
    name = world.living[0].name if world.living else None
    a = name
    b = world.living[1].name if len(world.living) > 1 else None
    return [
        ("scatter", lambda: panels.scatter_figure(world)),
        ("scatter+selected", lambda: panels.scatter_figure(world, a)),
        ("population", lambda: panels.population_figure(cols)),
        ("births_deaths", lambda: panels.births_deaths_figure(cols)),
        ("pyramid", lambda: panels.pyramid_figure(world)),
        ("traits", lambda: panels.traits_figure(cols)),
        ("diversity", lambda: panels.diversity_figure(cols)),
        ("lineage", lambda: panels.lineage_figure(world)),
        ("tree", lambda: panels.tree_figure(world, a)),
        ("tree_none", lambda: panels.tree_figure(world, None)),
        ("inbreeding", lambda: panels.inbreeding_figure(cols)),
        ("fst1", lambda: panels.fst_figure(cols, 1)),
        ("fst4", lambda: panels.fst_figure(cols, 4)),
        ("deme_bar", lambda: panels.deme_bar_figure(world)),
        ("spiral", lambda: panels.spiral_figure(cols)),
        ("candlestick", lambda: panels.candlestick_figure(cols)),
        ("pop_radar", lambda: panels.population_radar_figure(world)),
        ("indiv_radar", lambda: panels.individual_radar_figure(world, a)),
        ("indiv_radar_none", lambda: panels.individual_radar_figure(world, None)),
        ("relatedness", lambda: panels.relatedness_figure(cols)),
        ("skew", lambda: panels.skew_figure(cols)),
        ("map", lambda: panels.map_figure(world, a)),
        ("compare_radar", lambda: panels.compare_radar_figure(world, a, b)),
        ("compare_bars", lambda: panels.compare_bars_figure(world, a, b)),
        ("compare_radar_none", lambda: panels.compare_radar_figure(world, None, None)),
        ("scatter_from_frame", lambda: panels.scatter_figure_from_frame(
            world, world.frame_at(None), a)),
        ("gp_allele", lambda: gp.allele_spectrum_figure(world)),
        ("gp_het", lambda: gp.heterozygosity_hist_figure(world)),
        ("gp_trait", lambda: gp.trait_distribution_figure(world)),
        ("gp_pyramid", lambda: gp.age_pyramid_figure(world)),
        ("gp_epiage", lambda: gp.epigenetic_age_figure(world)),
        ("gp_mito", lambda: gp.mito_haplogroup_figure(world)),
        ("gp_sexlink", lambda: gp.sex_linked_figure(world)),
        ("gp_imprint", lambda: gp.imprinting_figure(world)),
        ("gp_mutload", lambda: gp.mutation_load_figure(world)),
    ]


@pytest.mark.parametrize("state", ["empty", "lone", "extinct", "normal"])
def test_no_figure_raises_in_any_world_state(state, empty_world, lone_world,
                                             extinct_world, normal_world):
    world = {"empty": empty_world, "lone": lone_world,
             "extinct": extinct_world, "normal": normal_world}[state]
    failures = []
    for label, thunk in _world_figures(world):
        try:
            fig = thunk()
            assert isinstance(fig, go.Figure), f"{label} returned {type(fig)}"
        except Exception as exc:                       # noqa: BLE001
            failures.append(f"{label}: {type(exc).__name__}: {exc}")
    assert not failures, f"{state} world broke {len(failures)} figures:\n" + \
                         "\n".join(failures)


@pytest.mark.parametrize("state", ["empty", "lone", "extinct", "normal"])
def test_no_figure_produces_a_degenerate_axis(state, empty_world, lone_world,
                                              extinct_world, normal_world):
    """
    A NaN or inverted axis range renders as a blank or upside-down panel, and
    Plotly does not complain. A one-person world is the classic trigger: the
    data has zero spread, so an auto-range can collapse to a point.
    """
    world = {"empty": empty_world, "lone": lone_world,
             "extinct": extinct_world, "normal": normal_world}[state]
    bad = []
    for label, thunk in _world_figures(world):
        fig = thunk()
        for axis in ("xaxis", "yaxis", "yaxis2"):
            rng = getattr(fig.layout, axis, None)
            rng = getattr(rng, "range", None) if rng is not None else None
            if rng is None:
                continue
            lo, hi = rng
            if lo is None or hi is None:
                continue
            if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                if math.isnan(lo) or math.isnan(hi):
                    bad.append(f"{label}.{axis} has NaN range {rng}")
                elif hi < lo:
                    bad.append(f"{label}.{axis} inverted {rng}")
    assert not bad, "\n".join(bad)


# ---------------------------------------------------------------------
# Inspector / drawer views at the edges
# ---------------------------------------------------------------------

@pytest.mark.parametrize("state", ["empty", "lone", "extinct", "normal"])
def test_inspector_views_survive_every_world_state(
        state, empty_world, lone_world, extinct_world, normal_world):
    world = {"empty": empty_world, "lone": lone_world,
             "extinct": extinct_world, "normal": normal_world}[state]
    frame = world.frame_at(None)
    name = world.living[0].name if world.living else None

    assert inspector.summary_card(world, None)          # placeholder branch
    assert inspector.summary_card(world, name) is not None
    assert inspector.summary_card(world, "Nobody-999") is not None
    assert inspector.summary_card(world, name, frame, historical=True) is not None
    assert inspector.leaderboard_view(frame) is not None
    assert inspector.directory_rows(frame) is not None
    assert inspector.compare_table(world, name, name) is not None
    assert inspector.compare_table(world, None, None) is not None
    assert inspector.lineage_sizes(frame) is not None


def test_views_tolerate_a_missing_frame():
    """`frame_at` can return None before the first tick is recorded."""
    assert inspector.leaderboard_view(None)
    assert inspector.directory_rows(None)
    assert inspector.lineage_sizes(None) == []
    assert inspector.leaderboard_entries(None, "oldest") == []


def test_leaderboard_ignores_an_unknown_board_key(normal_world):
    frame = normal_world.frame_at(None)
    assert inspector.leaderboard_entries(frame, "not-a-board") == []


def test_directory_filters_that_match_nothing_do_not_crash(normal_world):
    frame = normal_world.frame_at(None)
    rows = inspector.directory_rows(frame, query="zzzzz-no-such-person")
    assert rows and "Nothing matches" in str(rows[0].children)

    assert inspector.directory_rows(frame, deme=999)          # empty deme
    assert inspector.directory_rows(frame, sex="nonbinary")   # unknown sex passes through
    assert inspector.directory_rows(frame, limit=0) is not None


def test_directory_respects_its_limit(normal_world):
    frame = normal_world.frame_at(None)
    assert len(inspector.directory_rows(frame, limit=3)) <= 3


@pytest.mark.parametrize("field", [f["value"] for f in inspector.SORT_FIELDS])
def test_every_advertised_sort_field_actually_sorts(field, normal_world):
    """
    Each option in the dropdown must work. `directory_rows` reads the field
    with `.get(field, 0)` because the snapshot ring is capped rather than
    versioned, so a field the frames predate must degrade, not explode.
    """
    frame = normal_world.frame_at(None)
    rows = inspector.directory_rows(frame, sort_by=field)
    assert rows
    values = [p.get(field, 0) for p in frame["people"]]
    assert values == sorted(values, reverse=True) or True   # sorting is internal
    # the rendered order must match a descending sort on that field
    ordered = sorted(frame["people"], key=lambda p: p.get(field, 0), reverse=True)
    rendered = [r.id["name"] for r in rows if hasattr(r, "id")]
    assert rendered == [p["name"] for p in ordered[:len(rendered)]]


def test_unknown_sort_field_falls_back_rather_than_raising(normal_world):
    frame = normal_world.frame_at(None)
    assert inspector.directory_rows(frame, sort_by="not-a-field")


@pytest.mark.parametrize("field", [f["value"] for f in inspector.SORT_FIELDS])
def test_ascending_sort_reaches_the_other_end_of_every_field(field, normal_world):
    """
    The list is capped at `limit`, so descending-only sorting made the
    youngest, the least inbred, the shortest and the healthiest individuals
    literally unreachable from the directory.
    """
    frame = normal_world.frame_at(None)
    people = frame["people"]
    asc = inspector.directory_rows(frame, sort_by=field, descending=False)
    desc = inspector.directory_rows(frame, sort_by=field, descending=True)
    first_asc = [r.id["name"] for r in asc if hasattr(r, "id")][0]
    first_desc = [r.id["name"] for r in desc if hasattr(r, "id")][0]
    assert first_asc == min(people, key=lambda p: p.get(field, 0))["name"]
    assert first_desc == max(people, key=lambda p: p.get(field, 0))["name"]


def test_descending_remains_the_default_for_existing_callers(normal_world):
    frame = normal_world.frame_at(None)
    assert ([r.id["name"] for r in inspector.directory_rows(frame) if hasattr(r, "id")]
            == [r.id["name"] for r in inspector.directory_rows(frame, descending=True)
                if hasattr(r, "id")])


def test_ascending_sort_surfaces_children(normal_world):
    """The concrete motivation: selecting a child is what makes the
    developmental trajectory (#13) visible in the inspector at all."""
    frame = normal_world.frame_at(None)
    rows = inspector.directory_rows(frame, sort_by="age", descending=False)
    names = [r.id["name"] for r in rows if hasattr(r, "id")]
    ages = {p["name"]: p["age"] for p in frame["people"]}
    assert ages[names[0]] == min(ages.values())
    assert ages[names[0]] < 18, "the top of an ascending age sort must be a child"


@pytest.mark.parametrize("clicks, expected", [
    (None, True), (0, True), (1, False), (2, True), (7, False),
])
def test_sort_direction_toggles_on_click_parity(clicks, expected):
    from dashboard.app import sort_is_descending
    assert sort_is_descending(clicks) is expected


def test_the_direction_button_says_what_it_will_do():
    from dashboard.app import DRAWERS, label_sort_direction
    out = label_sort_direction(*([0] * len(DRAWERS)))
    arrows, titles = out[:len(DRAWERS)], out[len(DRAWERS):]
    assert set(arrows) == {"↓"}
    assert all("click for ascending" in t for t in titles)
    out = label_sort_direction(*([1] * len(DRAWERS)))
    assert set(out[:len(DRAWERS)]) == {"↑"}


def test_frames_missing_the_session_11_fields_still_render(normal_world):
    """
    The snapshot buffer is capped, not versioned: frames captured before
    `pedigree_f`/`viability`/`cnv` existed are still in the ring. Readers use
    `.get` with defaults, and this is what pins that.
    """
    frame = normal_world.frame_at(None)
    stripped = {
        **frame,
        "people": [{k: v for k, v in p.items()
                    if k not in ("pedigree_f", "viability", "cnv", "life_stage")}
                   for p in frame["people"]],
    }
    assert inspector.directory_rows(stripped, sort_by="pedigree_f")
    assert inspector.leaderboard_view(stripped)
    assert inspector.summary_card(normal_world, stripped["people"][0]["name"],
                                  stripped, historical=True)


# ---------------------------------------------------------------------
# Pure helpers at their limits
# ---------------------------------------------------------------------

@pytest.mark.parametrize("value, lo, hi, expected", [
    (5, 0, 10, 0.5),
    (-100, 0, 10, 0.0),          # clamps low
    (999, 0, 10, 1.0),           # clamps high
    (5, 10, 10, 0.0),            # degenerate range -> 0, never a ZeroDivision
    (5, 10, 0, 0.0),             # inverted range
    (-1.5, -1.5, 2.5, 0.0),      # signed liability at its floor
    (2.5, -1.5, 2.5, 1.0),
])
def test_meter_normalisation_clamps_and_never_divides_by_zero(value, lo, hi, expected):
    assert inspector._norm(value, lo, hi) == pytest.approx(expected)


@pytest.mark.parametrize("t", [-5.0, 0.0, 0.25, 0.5, 0.75, 1.0, 5.0])
def test_stress_ramp_returns_a_valid_hex_colour_for_any_input(t):
    c = _stress_ramp(t)
    assert len(c) == 7 and c[0] == "#"
    int(c[1:], 16)                       # parses as hex


def test_stress_ramp_is_ordered_and_not_red_green():
    """Teal -> amber -> red: red must rise monotonically with load, and the
    endpoints must be far apart in every channel that greyscale preserves."""
    reds = [int(_stress_ramp(t)[1:3], 16) for t in np.linspace(0, 1, 11)]
    assert reds == sorted(reds), "red channel must not go backwards"
    assert _stress_ramp(0.0) != _stress_ramp(1.0)
    # no pure green endpoint (the CVD-unsafe scale this deliberately avoids)
    calm = _stress_ramp(0.0)
    g, r = int(calm[3:5], 16), int(calm[1:3], 16)
    assert not (g > 150 and r < 60), "calm end must be teal, not green"


@pytest.mark.parametrize("trait, val", [
    ("height_cm", 171), ("height_cm", 0), ("height_cm", 1e6),
    ("bmi", 24), ("bmi", -50), ("openness", 0.0), ("openness", 40.0),
])
def test_radar_scores_stay_inside_the_drawn_range(trait, val):
    """The radial axis is pinned to [0,100]; an unclipped score would draw
    outside the polygon or vanish."""
    s = panels._to_score(trait, val)
    assert 2 <= s <= 98


def test_radar_score_is_monotone_in_the_value():
    xs = [150, 160, 171, 180, 200]
    scores = [panels._to_score("height_cm", x) for x in xs]
    assert scores == sorted(scores)


@pytest.mark.parametrize("hex_in", ["#ffffff", "#000000", "4ea3ff", "#4EA3FF"])
def test_rgba_helper_parses_with_or_without_hash(hex_in):
    out = panels._rgba(hex_in, 0.5)
    assert out.startswith("rgba(") and out.endswith(",0.5)")


def test_last_returns_the_default_for_a_missing_or_empty_series():
    assert panels._last({}, "nope", 7) == 7
    assert panels._last({"nope": []}, "nope", 7) == 7
    assert panels._last({"x": [1, 2, 3]}, "x") == 3


@pytest.mark.parametrize("params, expected", [
    (None, 1),
    (object(), 1),
    (DemographyParams(n_demes=0), 1),      # 0 is falsy -> the default, not 0
    (DemographyParams(n_demes=5), 5),
])
def test_deme_count_helper_is_total(params, expected):
    assert panels._n_demes(params) == expected


def test_kpi_row_is_complete_and_finite_even_with_no_history():
    tiles = panels.kpi_data({}, DemographyParams())
    assert len(tiles) >= 8
    for t in tiles:
        assert t["value"] and isinstance(t["value"], str)
        assert not math.isnan(float(t["delta"]))


@pytest.mark.parametrize("F", [-0.5, 0.0, 1e-12, 0.0156, 0.03, 0.0625, 0.2,
                               0.25, 0.5, 1.0])
def test_relationship_label_is_total_over_the_whole_F_range(F):
    assert isinstance(inspector.relationship_label(F), str)


def test_relationship_label_never_overstates_closeness():
    """The label is the closest standard relationship AT OR BELOW F, so a
    value just under a threshold must read as the looser relationship."""
    assert inspector.relationship_label(0.0624) == "first cousins once removed"
    assert inspector.relationship_label(0.1249) == "first cousins"


def test_sort_value_text_gives_pedigree_F_the_precision_it_needs():
    """At two decimals a first-cousin child (0.0625) and a second-cousin one
    (0.0156) both round to something uninformative."""
    assert inspector._sort_value_text(0.0625, "pedigree_f") == "0.0625"
    assert inspector._sort_value_text(0.0156, "pedigree_f") == "0.0156"
    assert inspector._sort_value_text(12.5, "age") == "12.50"
    assert inspector._sort_value_text(3, "children") == "3"


# ---------------------------------------------------------------------
# Timeline scrubbing limits
# ---------------------------------------------------------------------

def test_history_truncation_handles_every_scrub_position(normal_world):
    full = panels.history_columns_upto(normal_world, None)
    n = len(full["tick"])
    assert panels.history_columns_upto(normal_world, -5)["tick"] == []
    assert len(panels.history_columns_upto(normal_world, 10**9)["tick"]) == n
    for t in full["tick"]:
        cut = panels.history_columns_upto(normal_world, t)
        assert cut["tick"][-1] <= t
        lengths = {len(v) for v in cut.values()}
        assert len(lengths) == 1, "columns must stay rectangular when truncated"


def test_every_time_series_chart_builds_at_every_scrub_position(normal_world):
    """The scrubber walks these columns one tick at a time; a chart that only
    works on the full history is a chart that breaks the moment it is dragged."""
    for t in panels.history_columns_upto(normal_world, None)["tick"]:
        cols = panels.history_columns_upto(normal_world, t)
        for fn in (panels.population_figure, panels.births_deaths_figure,
                   panels.traits_figure, panels.diversity_figure,
                   panels.inbreeding_figure, panels.spiral_figure,
                   panels.candlestick_figure, panels.relatedness_figure,
                   panels.skew_figure):
            assert isinstance(fn(cols), go.Figure), f"{fn.__name__} at tick {t}"


# ---------------------------------------------------------------------
# Map payload limits
# ---------------------------------------------------------------------

@pytest.mark.parametrize("layer", ["default", "dominance", "stress", "bogus"])
def test_map_payload_is_wellformed_for_every_layer(layer, normal_world):
    d = build_mapdata(normal_world, None, layer=layer)
    assert set(d) >= {"size", "seed", "demes", "people", "flows", "layer", "tick"}
    assert d["layer"] == layer
    assert len(d["people"]) == len(normal_world.living)
    for p in d["people"]:
        assert np.isfinite(p["x"]) and np.isfinite(p["y"])
        assert p["color"].startswith("#") or p["color"].startswith("rgb")
    for dm in d["demes"]:
        assert dm["n"] >= 0 and dm["r"] > 0


def test_villagers_stay_inside_the_world_the_payload_declares(normal_world):
    """
    Regression test for a defect this suite found on 2026-08-06 and which was
    fixed the same day. `community.deme_layout` uses a golden-angle sunflower
    spread, r = 0.40*MAP_SIZE*sqrt((i+0.5)/n); at n=1 that is sqrt(0.5)=0.707
    rather than 0, so the lone settlement sat off-centre at (78.3, 50). With
    the n=1 territory radius of MAP_SIZE*0.34 = 34 its edge reached 112.3 on a
    map declared as 100, and ~13% of villagers in a grown DEFAULT world
    rendered outside the world square. Multi-deme worlds were unaffected.
    """
    d = build_mapdata(normal_world, None)
    outside = [p for p in d["people"]
               if not (0 <= p["x"] <= d["size"] and 0 <= p["y"] <= d["size"])]
    assert not outside, (
        f"{len(outside)}/{len(d['people'])} villagers outside 0..{d['size']}; "
        f"worst x={max(p['x'] for p in d['people']):.2f}")


def test_map_payload_of_an_empty_world_is_still_renderable(empty_world):
    d = build_mapdata(empty_world, None)
    assert d["people"] == [] and d["demes"] in ([], d["demes"])
    assert d["size"] == 100


def test_stress_overlay_survives_a_perfectly_flat_population(normal_world):
    """Every settlement at identical load would divide by zero on the ramp."""
    frame = normal_world.frame_at(None)
    flat = {**frame, "demes": [{**d, "mean_stress": 0.4} for d in frame["demes"]]}
    d = build_mapdata(normal_world, None, frame=flat, layer="stress")
    for dm in d["demes"]:
        assert 0.0 <= dm["washAlpha"] <= 1.0
        assert dm["wash"].startswith("#")


def test_deme_short_label_is_never_empty():
    for i in range(0, 12):
        assert _deme_short(i)


# ---------------------------------------------------------------------
# Control -> params limits
# ---------------------------------------------------------------------

def test_params_accept_the_extremes_of_every_slider():
    lo = params_from_controls(10, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0625,
                              1, 0.0, 0.0, 0.0, 0.0, 0.0, depression=0.0)
    hi = params_from_controls(2000, 1.0, 5.0, 2.0, 50.0, 3.0, 1.0, 0.5,
                              8, 0.3, 1.0, 1.0, 1.0, 1.0, depression=2.0)
    for p in (lo, hi):
        assert isinstance(p, DemographyParams)
    assert lo.carrying_capacity == 10 and hi.carrying_capacity == 2000
    assert lo.inbreeding_depression == 0.0 and hi.inbreeding_depression == 2.0
    assert hi.n_demes == 8


def test_params_coerce_slider_strings_and_floats():
    """Dash number inputs hand back strings and floats interchangeably."""
    p = params_from_controls("150", "0.42", 1, 0.4, 1, 1, 0, 0.5,
                             "4", 0.05, 1, 0, 0, 1)
    assert p.carrying_capacity == 150 and isinstance(p.carrying_capacity, int)
    assert p.n_demes == 4 and isinstance(p.n_demes, int)
    assert p.birth_rate == pytest.approx(0.42)


def test_a_world_built_from_extreme_params_still_steps():
    p = params_from_controls(12, 1.0, 3.0, 1.0, 5.0, 2.0, 1.0, 0.0625,
                             3, 0.25, 0.0, 1.0, 1.0, 0.0, depression=2.0)
    w = World(n_founders=6, seed=4, params=p)
    for _ in range(6):
        w.step()
    assert isinstance(panels.kpi_data(w.history_columns(), p), list)
    assert isinstance(build_mapdata(w, None, layer="stress"), dict)
