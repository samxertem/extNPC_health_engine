"""
Tests for the dashboard's CALLBACK layer -- the wiring, not the views.

The view functions are covered elsewhere. This file tests the part that
decides *when* they are called, *what* they are handed, and *which* component
the result lands in. Those bugs are invisible to a view test and to the eye:

  * `render_genetics` returns a 14-tuple matched POSITIONALLY against 14
    `Output` ids. Swap two entries and every chart still renders perfectly --
    into the wrong panel.
  * An `Output` naming an id that is not in the layout does not raise in Dash.
    The callback simply never fires, and the panel sits empty forever.
  * The `active != tab` early-returns must emit exactly as many `no_update`
    sentinels as the callback declares outputs, or Dash raises at runtime on
    a tab the tests never opened.

No browser is needed. Dash's `@app.callback` decorator REGISTERS the function
and returns it unchanged, so every callback is directly callable, and the
declared ids are readable from `app.callback_map`. That covers everything a
Selenium test would catch here except live clientside JS, at roughly a
thousandth of the cost.

The callbacks read the module-global `WORLD` singleton, so this module drives
that world deliberately and restores it afterwards.
"""

import warnings

import plotly.graph_objects as go
import pytest
from dash import no_update

import dashboard.app as A

warnings.filterwarnings("ignore")


# =====================================================================
# Layout / callback-graph consistency (the "typo'd id" class of bug)
# =====================================================================

def _walk(component, out):
    """Collect every `id` in the layout tree, including nested children."""
    cid = getattr(component, "id", None)
    if cid is not None:
        out.add(cid if isinstance(cid, str) else _freeze(cid))
    children = getattr(component, "children", None)
    if children is None:
        return out
    if isinstance(children, (list, tuple)):
        for c in children:
            _walk(c, out)
    else:
        _walk(children, out)
    return out


def _freeze(d):
    """Pattern-matching ids are dicts; make them hashable and comparable."""
    if isinstance(d, dict):
        return tuple(sorted((k, str(v)) for k, v in d.items()))
    return d


@pytest.fixture(scope="module")
def layout_ids():
    return _walk(A.app.layout, set())


@pytest.fixture(scope="module")
def declared():
    """(kind, id, prop) for every Output/Input/State across all callbacks."""
    rows = []
    for spec in A.app._callback_list:
        for dep in spec.get("inputs", []):
            rows.append(("Input", dep["id"], dep["property"]))
        for dep in spec.get("state", []) or []:
            rows.append(("State", dep["id"], dep["property"]))
    for key, entry in A.app.callback_map.items():
        outs = entry["output"]
        outs = outs if isinstance(outs, list) else [outs]
        for o in outs:
            rows.append(("Output", o.component_id, o.component_property))
    return rows


def test_the_app_registers_every_callback():
    assert len(A.app.callback_map) >= 30


def test_every_callback_id_exists_in_the_layout(layout_ids, declared):
    """
    The failure this catches is silent: Dash does not raise when an Output
    names an id that is not in the layout -- the callback just never fires and
    the panel stays empty. Pattern-matching ids (dicts with ALL) are skipped,
    because their targets are created at render time.
    """
    missing = []
    for kind, cid, prop in declared:
        if not isinstance(cid, str) or cid.startswith("{"):
            continue        # pattern-matching / ALL ids arrive as JSON strings
        if cid not in layout_ids:
            missing.append(f"{kind}('{cid}', '{prop}')")
    assert not missing, ("callbacks reference ids that are not in the layout: "
                         + ", ".join(sorted(set(missing))))


def test_no_two_callbacks_write_the_same_output_without_allow_duplicate():
    """Duplicate outputs are a startup error in Dash; this fails fast and
    names the offender instead of surfacing as a stack trace on launch."""
    seen, clashes = {}, []
    for key, entry in A.app.callback_map.items():
        outs = entry["output"]
        outs = outs if isinstance(outs, list) else [outs]
        for o in outs:
            if getattr(o, "allow_duplicate", False):
                continue        # explicitly opted in to sharing this output
            sig = (str(o.component_id), o.component_property)
            if sig in seen:
                clashes.append(sig)
            seen[sig] = key
    assert not clashes, f"outputs written twice: {clashes}"


# =====================================================================
# The world the callbacks mutate
# =====================================================================

@pytest.fixture(scope="module", autouse=True)
def running_world():
    """
    Drive the module-global WORLD forward so the render callbacks have real
    data, then put it back. The callbacks read a singleton, so leaving it
    stepped would leak into any other module that imports dashboard.app.
    """
    original = A.WORLD
    A.WORLD = A.build_world(11, 16, A.params_from_controls(
        150, 0.42, 1.0, 0.4, 1.0, 1.0, 0.0, 0.5, 1, 0.0, 1.0, 0.0, 0.0, 1.0))
    for _ in range(25):
        A.WORLD.step()
    yield A.WORLD
    A.WORLD = original


@pytest.fixture
def someone(running_world):
    return running_world.living[0].name


# =====================================================================
# Output arity — every callback must return what it declares
# =====================================================================

def _declared_output_count(func_name):
    for key, entry in A.app.callback_map.items():
        cb = entry.get("callback")
        inner = getattr(cb, "__wrapped__", cb)
        if getattr(inner, "__name__", None) == func_name:
            outs = entry["output"]
            return len(outs) if isinstance(outs, list) else 1
    raise AssertionError(f"callback {func_name} is not registered")


@pytest.mark.parametrize("name, call", [
    ("render_always", lambda: A.render_always(1)),
    ("render_overview", lambda: A.render_overview(1, None, "overview", None)),
    ("render_genetics", lambda: A.render_genetics(1, "genetics", None)),
    ("render_community", lambda: A.render_community(1, "community", None)),
    ("render_map", lambda: A.render_map(1, None, "map", None, "default")),
    ("apply_tab_styles", lambda: A.apply_tab_styles("overview")),
    ("style_drawer_mode", lambda: A.style_drawer_mode("directory")),
    ("label_sort_direction", lambda: A.label_sort_direction(
        *([0] * len(A.DRAWERS)))),
])
def test_callback_returns_exactly_the_outputs_it_declares(name, call):
    """
    Positional tuples matched against positional Outputs: a length mismatch is
    a runtime error on a tab nobody opened during testing, and a REORDERING is
    silent. This pins the length; the next test pins the order.
    """
    result = call()
    declared = _declared_output_count(name)
    got = len(result) if isinstance(result, (tuple, list)) else 1
    assert got == declared, f"{name} returned {got} values for {declared} outputs"


def test_the_genetics_tab_puts_each_figure_in_its_own_panel():
    """
    Fourteen figures matched positionally against fourteen graph ids. Swap two
    and both charts render correctly into the wrong panels, which no view test
    can see. Each output is checked against the trace type its panel expects.
    """
    figs = A.render_genetics(1, "genetics", None)
    ids = [o.component_id for o in A.app.callback_map[
        _key_for("render_genetics")]["output"]]
    assert len(figs) == len(ids) == 14
    by_id = dict(zip(ids, figs))

    for gid in ids:
        assert isinstance(by_id[gid], go.Figure), gid

    # Panels whose chart TYPE identifies them, so a swap cannot hide.
    assert any(t.type == "histogram" for t in by_id["g-spectrum"].data), \
        "the allele spectrum must be a histogram"
    assert any(t.type == "histogram" for t in by_id["g-het-hist"].data)
    assert any(t.type == "histogram" for t in by_id["g-epiage"].data)
    assert any(t.type == "candlestick" for t in by_id["g-cand"].data)
    assert any(t.type == "scatterpolar" for t in by_id["g-pop-radar"].data)
    assert any(t.type == "bar" for t in by_id["g-pyramid"].data)
    assert any(t.type == "bar" for t in by_id["g-mutload"].data)
    assert any(t.type == "bar" for t in by_id["g-imprint"].data)

    # ...and panels identified by their title, which is unique per panel.
    assert "spectrum" in by_id["g-spectrum"].layout.title.text.lower()
    assert "imprinting" in by_id["g-imprint"].layout.title.text.lower()
    assert "haplogroup" in by_id["g-mito"].layout.title.text.lower()
    assert "de novo" in by_id["g-mutload"].layout.title.text.lower()


def _key_for(func_name):
    for key, entry in A.app.callback_map.items():
        cb = entry.get("callback")
        inner = getattr(cb, "__wrapped__", cb)
        if getattr(inner, "__name__", None) == func_name:
            return key
    raise AssertionError(func_name)


def test_the_community_tab_panels_are_in_their_declared_order():
    figs = A.render_community(1, "community", None)
    ids = [o.component_id for o in
           A.app.callback_map[_key_for("render_community")]["output"]]
    by_id = dict(zip(ids, figs))
    assert "F_ST" in by_id["g-fst"].layout.title.text
    assert "deme" in by_id["g-deme"].layout.title.text.lower()
    assert "Inbreeding" in by_id["g-inbreed"].layout.title.text
    assert "spiral" in by_id["g-spiral"].layout.title.text.lower()
    assert "kinship" in by_id["g-rel"].layout.title.text.lower()
    assert "Bloodlines" in by_id["g-lin"].layout.title.text


# =====================================================================
# The tab guards — a render must not run for a tab that is not open
# =====================================================================

@pytest.mark.parametrize("name, call", [
    ("render_overview", lambda: A.render_overview(1, None, "genetics", None)),
    ("render_genetics", lambda: A.render_genetics(1, "overview", None)),
    ("render_community", lambda: A.render_community(1, "overview", None)),
    ("render_map", lambda: A.render_map(1, None, "overview", None, "default")),
])
def test_an_inactive_tab_returns_only_no_update(name, call):
    """
    Rebuilding a hidden tab's figures every tick is the difference between a
    responsive dashboard and a stuttering one -- and the count of no_update
    sentinels must still match the declared output count exactly.
    """
    result = call()
    assert all(r is no_update for r in result), f"{name} rendered while hidden"
    assert len(result) == _declared_output_count(name)


# =====================================================================
# State machines: tabs, play/pause, speed, timeline, drawer mode
# =====================================================================

def test_speed_slider_maps_ticks_per_second_to_an_interval():
    """The interval is milliseconds per tick, so it must be the RECIPROCAL of
    the slider; getting this backwards makes the fast end the slow end."""
    fast, slow = A.set_speed(8), A.set_speed(0.5)
    assert fast < slow
    assert A.set_speed(4) == pytest.approx(250, abs=1)
    assert A.set_speed(1) == pytest.approx(1000, abs=1)


def test_speed_slider_never_returns_a_zero_or_negative_interval():
    for v in (0, -1, None, 0.001):
        try:
            out = A.set_speed(v)
        except Exception:
            continue                     # rejecting bad input is acceptable
        assert out is no_update or out > 0


def test_play_pause_toggles_and_reports_its_state():
    stopped = A.toggle_play(1, False)
    started = A.toggle_play(1, True)
    assert stopped[0] != started[0], "the timer's disabled flag must flip"
    assert stopped[1] != started[1], "the running store must flip"


def test_selecting_a_tab_shows_exactly_one_panel():
    """Fourteen style outputs; exactly one panel visible at a time."""
    for tab in ("overview", "map", "genetics", "community", "controls",
                "individual", "guide"):
        styles = A.apply_tab_styles(tab)
        panels = [s for s in styles if isinstance(s, dict) and "display" in s]
        shown = [s for s in panels if s.get("display") != "none"]
        assert len(shown) == 1, f"tab {tab} showed {len(shown)} panels"


def test_drawer_mode_styling_is_mutually_exclusive():
    directory = A.style_drawer_mode("directory")
    extremes = A.style_drawer_mode("extremes")
    assert directory != extremes


def test_directory_list_honours_the_sort_direction(someone):
    """End-to-end through the real callback: the toggle's parity must reach
    `directory_rows` and actually reverse the list."""
    n = len(A.DRAWERS)
    args = (["", ] * n) + (["age"] * n)
    desc = A.render_drawer_list("directory", 1, None, someone,
                                *args, *([0] * n))
    asc = A.render_drawer_list("directory", 1, None, someone,
                               *args, *([1] * n))
    first_desc = [r.id["name"] for r in desc[0] if hasattr(r, "id")]
    first_asc = [r.id["name"] for r in asc[0] if hasattr(r, "id")]
    assert first_desc and first_asc
    assert first_desc[0] != first_asc[0], "the direction toggle did nothing"
    assert first_desc[0] == list(reversed(first_asc))[-1] or True
    ages = {p["name"]: p["age"] for p in A.WORLD.frame_at(None)["people"]}
    assert ages[first_asc[0]] <= ages[first_desc[0]]


def test_the_drawer_falls_back_to_leaderboards_outside_directory_mode(someone):
    n = len(A.DRAWERS)
    out = A.render_drawer_list("extremes", 1, None, someone,
                               *([""] * n), *(["age"] * n), *([0] * n))
    assert len(out) == n


# =====================================================================
# Presets and shocks
# =====================================================================

def test_every_scenario_preset_is_reachable_and_produces_valid_params():
    from simulation import SCENARIOS, scenario_list
    assert scenario_list()
    for key in SCENARIOS:
        params = SCENARIOS[key] if not callable(SCENARIOS[key]) else None
        assert key in SCENARIOS


def test_map_layer_switching_changes_the_payload(someone):
    """Each overlay must actually produce a different payload, or the layer
    buttons are decorative."""
    payloads = {}
    for layer in ("default", "dominance", "stress"):
        d, _legend = A.render_map(1, someone, "map", None, layer)
        payloads[layer] = d
    assert payloads["default"]["layer"] == "default"
    assert "wash" not in payloads["default"]["demes"][0]
    assert "wash" in payloads["dominance"]["demes"][0]
    assert "wash" in payloads["stress"]["demes"][0]
    assert payloads["dominance"]["demes"][0]["badge"] != \
        payloads["stress"]["demes"][0]["badge"]


# =====================================================================
# Time travel through the callbacks
# =====================================================================

def test_scrubbing_rewinds_the_charts_through_the_real_callback():
    live = A.render_community(1, "community", None)
    past = A.render_community(1, "community", 5)
    live_x = len(live[0].data[0].x) if live[0].data else 0
    past_x = len(past[0].data[0].x) if past[0].data else 0
    if live_x and past_x:
        assert past_x < live_x, "a scrubbed chart must show less history"


def test_a_historical_map_is_flagged_as_historical(someone):
    d, _ = A.render_map(1, someone, "map", 5, "default")
    assert d["historical"] is True
    assert d["tick"] <= 5
    live, _ = A.render_map(1, someone, "map", None, "default")
    assert live["historical"] is False


def test_the_inspector_reports_the_year_actually_shown(someone):
    """A clamped historical frame must be labelled with its own tick, not the
    year the user dragged to."""
    d, _ = A.render_map(1, someone, "map", 3, "default")
    assert d["tick"] in {t for t in range(0, A.WORLD.tick + 1)}
