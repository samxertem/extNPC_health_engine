"""
Per-tick world snapshots -- the substrate the timeline scrubber, the
leaderboards and the map heatmaps all read from.

The load-bearing property is that capture is READ-ONLY: adding it must not
draw a single random number, or every calibrated result shifts.
"""

from dataclasses import replace

import numpy as np
import pytest

from simulation import DemographyParams, SCENARIOS, World
from simulation.snapshots import MAX_FRAMES, SnapshotBuffer, capture


def _run(params=None, n_founders=12, seed=5, years=25):
    w = World(n_founders=n_founders, seed=seed, params=params or DemographyParams())
    for _ in range(years):
        w.step()
    return w


# ----------------------------------------------------------------------
# The invariant
# ----------------------------------------------------------------------

def test_capture_does_not_perturb_the_rng_stream():
    """Two identical worlds must still replay identically with snapshots on."""
    a, b = _run(seed=21, years=20), _run(seed=21, years=20)
    assert a.history[-1] == b.history[-1]
    assert [p["name"] for p in a.frame_at(None)["people"]] == \
           [p["name"] for p in b.frame_at(None)["people"]]


def test_capture_is_pure():
    """Calling capture() repeatedly changes nothing about the world."""
    w = _run(years=10)
    before = w.rng.bit_generator.state
    f1, f2 = capture(w), capture(w)
    assert w.rng.bit_generator.state == before
    assert f1 == f2


# ----------------------------------------------------------------------
# Contents
# ----------------------------------------------------------------------

def test_a_frame_exists_for_every_tick_including_zero():
    w = _run(years=15)
    assert w.snapshots.first_tick == 0
    assert w.snapshots.last_tick == 15
    assert len(w.snapshots) == 16          # tick 0 plus 15 steps


def test_frame_zero_is_the_founding_population():
    w = World(n_founders=12, seed=5)
    f = w.frame_at(0)
    assert f["tick"] == 0
    assert f["n_alive"] == 12
    assert all(p["age"] >= 0 for p in f["people"])


def test_person_rows_carry_what_the_ui_draws():
    w = _run(years=12)
    p = w.frame_at(None)["people"][0]
    for key in ("name", "x", "y", "color", "sex", "age", "deme", "lineage",
                "stress", "aerobic", "conditions", "children", "generation"):
        assert key in p


def test_deme_rows_carry_the_heatmap_aggregates():
    p = replace(DemographyParams(), n_demes=3, migration_rate=0.05)
    w = _run(p, n_founders=12, years=20)
    demes = w.frame_at(None)["demes"]
    assert len(demes) == 3
    for d in demes:
        assert 0.0 <= d["dominance"] <= 1.0
        # NB stress is `inflammation_state`, a LIABILITY in SD units, so it is
        # signed -- a calm population sits below zero. The heatmap must
        # normalise rather than assume a 0-based scale.
        assert np.isfinite(d["mean_stress"])
        assert d["max_stress"] >= d["mean_stress"]


def test_deme_aggregates_agree_with_the_person_rows():
    p = replace(DemographyParams(), n_demes=3, migration_rate=0.05)
    w = _run(p, n_founders=12, years=20)
    f = w.frame_at(None)
    assert sum(d["n"] for d in f["demes"]) == len(f["people"])
    for d in f["demes"]:
        members = [q for q in f["people"] if q["deme"] == d["deme"]]
        assert d["n"] == len(members)
        if members:
            assert d["mean_stress"] == pytest.approx(
                np.mean([m["stress"] for m in members]), abs=1e-3)


# ----------------------------------------------------------------------
# Lookup semantics
# ----------------------------------------------------------------------

def test_at_returns_the_exact_tick_when_present():
    w = _run(years=20)
    for t in (0, 7, 13, 20):
        assert w.frame_at(t)["tick"] == t


def test_at_falls_back_to_the_nearest_earlier_frame():
    """After frames age out of the cap the scrubber must degrade gracefully
    rather than render an empty map."""
    buf = SnapshotBuffer(max_frames=5)
    for t in (10, 11, 12, 13, 14):
        buf.append({"tick": t, "people": [], "demes": [], "flows": [],
                    "n_alive": 0})
    assert buf.at(12)["tick"] == 12
    assert buf.at(3)["tick"] == 10          # before the window -> earliest
    assert buf.at(99)["tick"] == 14         # after -> latest
    assert buf.at(None)["tick"] == 14


def test_buffer_is_bounded():
    buf = SnapshotBuffer(max_frames=4)
    for t in range(20):
        buf.append({"tick": t, "people": [], "demes": [], "flows": [],
                    "n_alive": 0})
    assert len(buf) == 4
    assert buf.ticks == [16, 17, 18, 19]


def test_empty_buffer_returns_none():
    buf = SnapshotBuffer()
    assert buf.at(None) is None
    assert buf.at(3) is None
    assert buf.first_tick == 0 and buf.last_tick == 0


# ----------------------------------------------------------------------
# Event log (timeline markers)
# ----------------------------------------------------------------------

def test_shocks_are_recorded_on_the_event_log():
    from simulation.events import Shock
    w = World(n_founders=12, seed=5)
    w.shock_queue.append(Shock(kind="plague", magnitude=0.5))
    w.step()
    assert any(e["kind"] == "plague" for e in w.event_log)
    assert w.event_log[0]["tick"] == 1


def test_event_log_starts_empty():
    assert World(n_founders=12, seed=5).event_log == []
