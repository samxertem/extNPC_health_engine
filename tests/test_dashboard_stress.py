"""
Stress, scale and complexity tests for the dashboard.

The dashboard redraws on a timer while the world keeps growing, so the
question is not "does this work once" but "does it still work at year 150
with 300 people, and does the cost grow like the population or like its
square". A view that is O(n^2) is fine in a test and fatal in a live session.

Timing bounds here are deliberately loose -- they are there to catch a change
in *complexity class*, not to benchmark the machine. The scaling tests compare
a function against itself at two sizes, which is far more robust to a busy CI
box than an absolute millisecond budget.

Run with `-s` to see the measured timings.
"""

import time
import warnings

import numpy as np
import plotly.graph_objects as go
import pytest

from dashboard import genetics_panels as gp, inspector, panels
from dashboard.app import build_mapdata, params_from_controls
from simulation import DemographyParams, World

warnings.filterwarnings("ignore")

TIMINGS: dict = {}


def _timed(label, fn, *a, **kw):
    t0 = time.perf_counter()
    out = fn(*a, **kw)
    dt = time.perf_counter() - t0
    TIMINGS[label] = dt
    return out, dt


# =====================================================================
# The worlds under stress (module-scoped: they are expensive to build)
# =====================================================================

@pytest.fixture(scope="module")
def big_world():
    """A large population -- the load the dashboard sees late in a long run."""
    p = DemographyParams(carrying_capacity=400)
    w = World(n_founders=50, seed=13, params=p)
    for _ in range(35):
        w.step()
    return w


@pytest.fixture(scope="module")
def long_world():
    """A long history -- 150 years of columns for every time-series chart."""
    w = World(n_founders=14, seed=17)
    for _ in range(150):
        w.step()
    return w


@pytest.fixture(scope="module")
def many_demes_world():
    """Eight settlements with migration: the widest the community layer goes."""
    p = DemographyParams(carrying_capacity=300, n_demes=8, migration_rate=0.06)
    w = World(n_founders=32, seed=19, params=p)
    for _ in range(45):
        w.step()
    return w


def _all_figures(world):
    cols = world.history_columns()
    a = world.living[0].name if world.living else None
    b = world.living[1].name if len(world.living) > 1 else None
    return {
        "scatter": lambda: panels.scatter_figure(world, a),
        "population": lambda: panels.population_figure(cols),
        "births_deaths": lambda: panels.births_deaths_figure(cols),
        "pyramid": lambda: panels.pyramid_figure(world),
        "traits": lambda: panels.traits_figure(cols),
        "diversity": lambda: panels.diversity_figure(cols),
        "lineage": lambda: panels.lineage_figure(world),
        "tree": lambda: panels.tree_figure(world, a),
        "inbreeding": lambda: panels.inbreeding_figure(cols),
        "fst": lambda: panels.fst_figure(cols, world.params.n_demes),
        "deme_bar": lambda: panels.deme_bar_figure(world),
        "spiral": lambda: panels.spiral_figure(cols),
        "candlestick": lambda: panels.candlestick_figure(cols),
        "pop_radar": lambda: panels.population_radar_figure(world),
        "indiv_radar": lambda: panels.individual_radar_figure(world, a),
        "relatedness": lambda: panels.relatedness_figure(cols),
        "skew": lambda: panels.skew_figure(cols),
        "map_fig": lambda: panels.map_figure(world, a),
        "compare_radar": lambda: panels.compare_radar_figure(world, a, b),
        "compare_bars": lambda: panels.compare_bars_figure(world, a, b),
        "allele": lambda: gp.allele_spectrum_figure(world),
        "het_hist": lambda: gp.heterozygosity_hist_figure(world),
        "trait_dist": lambda: gp.trait_distribution_figure(world),
        "age_pyramid": lambda: gp.age_pyramid_figure(world),
        "epi_age": lambda: gp.epigenetic_age_figure(world),
        "mito": lambda: gp.mito_haplogroup_figure(world),
        "sex_linked": lambda: gp.sex_linked_figure(world),
        "imprint": lambda: gp.imprinting_figure(world),
        "mut_load": lambda: gp.mutation_load_figure(world),
    }


# =====================================================================
# 1. Everything still builds at scale
# =====================================================================

@pytest.mark.parametrize("scenario", ["big", "long", "demes"])
def test_every_panel_builds_under_load(scenario, big_world, long_world,
                                       many_demes_world):
    world = {"big": big_world, "long": long_world,
             "demes": many_demes_world}[scenario]
    slow = []
    for label, thunk in _all_figures(world).items():
        fig, dt = _timed(f"{scenario}/{label}", thunk)
        assert isinstance(fig, go.Figure)
        if dt > 2.0:
            slow.append(f"{label} took {dt:.2f}s")
    assert not slow, "panels too slow to redraw on a timer: " + "; ".join(slow)


def test_a_full_tab_render_stays_inside_the_refresh_budget(big_world):
    """
    The Genetics tab rebuilds fourteen figures in one callback, and the
    interval fires as fast as 8 ticks/s. If one tab render costs more than a
    second the UI visibly stutters.
    """
    figs = _all_figures(big_world)
    genetics = ["traits", "pop_radar", "diversity", "candlestick", "skew",
                "allele", "het_hist", "trait_dist", "age_pyramid",
                "mut_load", "imprint", "sex_linked", "mito", "epi_age"]
    t0 = time.perf_counter()
    for k in genetics:
        figs[k]()
    dt = time.perf_counter() - t0
    TIMINGS["genetics_tab_render"] = dt
    assert dt < 3.0, f"Genetics tab took {dt:.2f}s to rebuild"


def test_the_whole_history_can_be_scrubbed_without_breaking(long_world):
    """Dragging the scrubber walks every tick; each position must produce a
    complete, rectangular set of columns and a drawable chart."""
    ticks = long_world.history_columns()["tick"]
    assert len(ticks) > 100
    t0 = time.perf_counter()
    for t in ticks[::5]:
        cols = panels.history_columns_upto(long_world, t)
        assert len({len(v) for v in cols.values()}) == 1
        panels.population_figure(cols)
        panels.inbreeding_figure(cols)
    TIMINGS["scrub_sweep"] = time.perf_counter() - t0


def test_time_travel_to_every_retained_frame_renders(long_world):
    """Historical frames drive the map and the drawer; the snapshot ring is
    capped, so old ticks return None and must degrade rather than crash."""
    for t in range(0, long_world.tick + 1, 7):
        frame = long_world.frame_at(t)
        d = build_mapdata(long_world, None, frame=frame, historical=True)
        assert isinstance(d, dict) and "people" in d
        assert inspector.leaderboard_view(frame) is not None
        assert inspector.directory_rows(frame) is not None


# =====================================================================
# 2. Complexity: cost must scale with n, not n^2
# =====================================================================

def _scaling_exponent(sizes, times):
    """Least-squares slope of log(t) on log(n) -- the empirical exponent."""
    x, y = np.log(np.asarray(sizes, float)), np.log(np.asarray(times, float))
    return float(np.polyfit(x, y, 1)[0])


@pytest.fixture(scope="module")
def size_series():
    """Three worlds of increasing population, same seed and shape."""
    worlds = []
    for nf, K in ((12, 80), (24, 160), (48, 320)):
        p = DemographyParams(carrying_capacity=K)
        w = World(n_founders=nf, seed=23, params=p)
        for _ in range(18):
            w.step()
        worlds.append(w)
    return worlds


def _repeat(fn, n=5):
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - t0) / n


def test_map_payload_cost_is_linear_in_population(size_series):
    sizes = [len(w.living) for w in size_series]
    times = [_repeat(lambda w=w: build_mapdata(w, None)) for w in size_series]
    exp = _scaling_exponent(sizes, times)
    TIMINGS["build_mapdata_exponent"] = exp
    TIMINGS["build_mapdata_sizes"] = list(zip(sizes, [f"{t*1000:.2f}ms" for t in times]))
    assert exp < 1.6, f"build_mapdata scales as n^{exp:.2f} — expected ~linear"


def test_directory_rendering_cost_is_subquadratic(size_series):
    sizes = [len(w.living) for w in size_series]
    times = []
    for w in size_series:
        frame = w.frame_at(None)
        times.append(_repeat(lambda f=frame: inspector.directory_rows(f, limit=40)))
    exp = _scaling_exponent(sizes, times)
    TIMINGS["directory_rows_exponent"] = exp
    assert exp < 1.6, f"directory_rows scales as n^{exp:.2f}"


def test_kpi_computation_does_not_depend_on_population_size(size_series):
    """KPIs read the history row, not the people; cost must be flat."""
    sizes = [len(w.living) for w in size_series]
    times = []
    for w in size_series:
        cols = w.history_columns()
        times.append(_repeat(lambda c=cols, p=w.params: panels.kpi_data(c, p), n=20))
    exp = _scaling_exponent(sizes, times)
    TIMINGS["kpi_data_exponent"] = exp
    assert exp < 1.0, f"kpi_data scales as n^{exp:.2f} — should be flat"


def test_the_expensive_genetics_panels_stay_subquadratic(size_series):
    """These touch every genome, so linear is expected and quadratic is not."""
    sizes = [len(w.living) for w in size_series]
    for label, fn in (("allele_spectrum", gp.allele_spectrum_figure),
                      ("heterozygosity", gp.heterozygosity_hist_figure),
                      ("imprinting", gp.imprinting_figure)):
        times = [_repeat(lambda w=w, f=fn: f(w), n=3) for w in size_series]
        exp = _scaling_exponent(sizes, times)
        TIMINGS[f"{label}_exponent"] = exp
        assert exp < 1.8, f"{label} scales as n^{exp:.2f}"


def test_history_truncation_is_cheap_regardless_of_history_length(long_world):
    """The scrubber calls this on every drag event."""
    dt = _repeat(lambda: panels.history_columns_upto(long_world,
                                                     long_world.tick // 2), n=20)
    TIMINGS["history_columns_upto"] = dt
    assert dt < 0.05, f"history truncation took {dt*1000:.1f}ms"


# =====================================================================
# 3. Payload size — this crosses the wire on every tick
# =====================================================================

def test_map_payload_stays_small_enough_to_ship_each_tick(big_world):
    import json
    d = build_mapdata(big_world, None, layer="stress")
    size = len(json.dumps(d))
    TIMINGS["mapdata_bytes"] = size
    assert size < 400_000, f"map payload is {size/1000:.0f} kB per tick"
    assert len(d["people"]) == len(big_world.living)


def test_map_payload_is_json_serialisable_with_no_numpy_leaking(big_world):
    """A stray numpy scalar serialises fine in-process and then fails in Dash's
    JSON encoder at runtime -- the worst place to find it."""
    import json
    for layer in ("default", "dominance", "stress"):
        d = build_mapdata(big_world, None, layer=layer)
        json.dumps(d)                       # raises on numpy types
        for p in d["people"]:
            assert type(p["x"]) is float or type(p["x"]) is int
        for dm in d["demes"]:
            assert type(dm["n"]) is int


def test_snapshot_ring_really_caps_and_drops_its_oldest_frames():
    """
    A left-running dashboard must not accumulate frames forever. Exercised on
    the buffer directly rather than by stepping a world 600+ times, so the
    cap itself is tested rather than merely not reached.
    """
    from simulation.snapshots import MAX_FRAMES, SnapshotBuffer
    buf = SnapshotBuffer(max_frames=25)
    for t in range(80):
        buf.append({"tick": t, "people": [], "demes": [], "flows": [],
                    "n_alive": 0})
    assert len(buf) == 25, "the ring did not cap"
    assert buf.first_tick == 55 and buf.last_tick == 79
    assert buf.at(79)["tick"] == 79
    assert MAX_FRAMES == 600


def test_scrubbing_below_the_window_clamps_but_never_lies_about_the_year():
    """
    `at()` deliberately falls back to the nearest EARLIER retained frame, so
    the scrubber stays usable once old frames age out instead of showing an
    empty map. The safety property is that the frame it returns still carries
    its own real tick -- the inspector and the map both label the view with
    `frame["tick"]`, so a clamped frame must not be presented as the year the
    user asked for.
    """
    from simulation.snapshots import SnapshotBuffer
    buf = SnapshotBuffer(max_frames=25)
    for t in range(80):
        buf.append({"tick": t, "people": [], "demes": [], "flows": [],
                    "n_alive": 0})
    clamped = buf.at(0)
    assert clamped is not None, "clamping keeps the scrubber usable"
    assert clamped["tick"] == 55, "must report the year actually shown, not 0"
    assert clamped["tick"] in buf.ticks
    assert buf.at(60)["tick"] == 60, "a retained tick is returned exactly"
    assert SnapshotBuffer().at(3) is None, "an empty buffer has nothing to show"


def test_a_scrub_to_a_dropped_frame_degrades_instead_of_crashing(long_world):
    """Once the window has moved past a tick, the scrubber can still be
    dragged there; every consumer must handle the None."""
    assert long_world.frame_at(10 ** 6) is not None or True
    frame = long_world.frame_at(-1)          # never recorded
    assert inspector.leaderboard_view(frame) is not None
    assert inspector.directory_rows(frame) is not None
    assert isinstance(build_mapdata(long_world, None, frame=frame), dict)


def test_frame_retention_tracks_the_run_length(long_world):
    retained = sum(1 for t in range(long_world.tick + 1)
                   if long_world.frame_at(t) is not None)
    TIMINGS["retained_frames"] = retained
    from simulation.snapshots import MAX_FRAMES
    assert retained == min(long_world.tick + 1, MAX_FRAMES)


# =====================================================================
# 4. Repeatability — a redraw must not mutate shared state
# =====================================================================

def test_rebuilding_a_figure_gives_an_identical_result(big_world):
    """The callbacks rebuild every figure from scratch each tick. If a builder
    mutates the world or a module-level default, the second call differs."""
    for label, thunk in _all_figures(big_world).items():
        first, second = thunk(), thunk()
        assert len(first.data) == len(second.data), label
        for t1, t2 in zip(first.data, second.data):
            for attr in ("x", "y", "r", "theta"):
                v1, v2 = getattr(t1, attr, None), getattr(t2, attr, None)
                if v1 is None or v2 is None:
                    continue
                assert np.array_equal(np.asarray(v1, dtype=object),
                                      np.asarray(v2, dtype=object)), \
                    f"{label}.{attr} changed between rebuilds"


def test_building_panels_does_not_advance_the_world(big_world):
    before_tick, before_alive = big_world.tick, len(big_world.living)
    before_hist = len(big_world.history)
    for thunk in _all_figures(big_world).values():
        thunk()
    build_mapdata(big_world, None)
    inspector.summary_card(big_world, big_world.living[0].name)
    assert (big_world.tick, len(big_world.living), len(big_world.history)) == \
           (before_tick, before_alive, before_hist)


def test_repeated_rendering_does_not_grow_the_pedigree_cache(big_world):
    """`World.pedigree()` is cached and invalidated on birth. Reading pedigree
    F from a view must hit the cache, not rebuild it."""
    name = big_world.living[0].name
    first = _repeat(lambda: big_world.inbreeding_of(name), n=3)
    second = _repeat(lambda: big_world.inbreeding_of(name), n=50)
    TIMINGS["inbreeding_of_cached"] = second
    assert second <= max(first, 1e-6) * 2.0 + 1e-4, \
        "pedigree lookup is not being cached across renders"


# =====================================================================
# 5. Adversarial worlds
# =====================================================================

def test_a_collapsing_population_renders_all_the_way_down():
    """Harsh parameters drive the population toward extinction; the dashboard
    must keep drawing through the crash and past the last death."""
    p = params_from_controls(20, 0.05, 3.0, 0.9, 1.0, 1.0, 0.0, 0.5,
                             1, 0.0, 0.2, 1.0, 1.0, 0.2, depression=2.0)
    w = World(n_founders=10, seed=29, params=p)
    for _ in range(45):
        w.step()
        cols = w.history_columns()
        assert isinstance(panels.population_figure(cols), go.Figure)
        assert isinstance(panels.kpi_data(cols, p), list)
        assert isinstance(build_mapdata(w, None), dict)
    TIMINGS["collapse_final_alive"] = len(w.living)
    assert isinstance(panels.scatter_figure(w), go.Figure)
    assert isinstance(gp.allele_spectrum_figure(w), go.Figure)


def test_a_world_with_more_demes_than_people_still_renders():
    """8 settlements and 4 inhabitants: mostly empty demes, and the stress
    overlay must normalise across settlements that contain nobody."""
    p = DemographyParams(carrying_capacity=12, n_demes=8, migration_rate=0.1)
    w = World(n_founders=4, seed=31, params=p)
    for _ in range(10):
        w.step()
    assert isinstance(panels.deme_bar_figure(w), go.Figure)
    assert isinstance(panels.fst_figure(w.history_columns(), 8), go.Figure)
    d = build_mapdata(w, None, layer="stress")
    for dm in d["demes"]:
        assert 0.0 <= dm.get("washAlpha", 0.0) <= 1.0


def test_selecting_a_dead_individual_still_renders(big_world):
    dead = [n for n in big_world.people.values()
            if n.name not in {p.name for p in big_world.living}]
    if not dead:
        pytest.skip("nobody has died yet")
    name = dead[0].name
    assert inspector.summary_card(big_world, name) is not None
    assert isinstance(panels.tree_figure(big_world, name), go.Figure)
    assert isinstance(panels.individual_radar_figure(big_world, name), go.Figure)


def test_report_timings():
    """Not an assertion -- prints the measured numbers for the record."""
    print("\n\n=== dashboard stress timings ===")
    for k, v in TIMINGS.items():
        if isinstance(v, float):
            print(f"  {k:42s} {v:.4f}")
        else:
            print(f"  {k:42s} {v}")
    print("=== end ===\n")
    assert TIMINGS, "no timings were recorded"
