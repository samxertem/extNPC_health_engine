"""
The "Export for Unity" button: the world on screen, and a bake behind it.
=========================================================================

`export_for_unity.py` and `export_bodies.py --bundle` already did this work,
but only for a world THEY built from flags. The dashboard's world comes from
its sliders, and the defaults differ: the dashboard opens with 10 founders and
`export_bodies.py` with 12. Two casts, and the symptom is not a crash but a
village that renders perfectly while selection sync silently does nothing.

WHAT IS WORTH TESTING HERE. Not that the exporter exports; `test_export.py`
and `test_export_golden.py` already cover the bundle, and re-asserting it here
would be a check that cannot fail. The parts with logic in them are:

  * the SPLIT between the two phases, which is a concurrency claim: phase 1
    reads the live world and must hold the lock, phase 2 reads only files;
  * the progress parser, which reads Blender's stdout and is the one place a
    plausible wrong number can reach the screen;
  * and the status machine, because a bake that fails must not read as one
    that finished.

Blender is NOT launched here. A test that shells out to a real bake would take
minutes, need an install, and still not exercise the parsing branch that
matters (a bake that dies half way). The subprocess is faked instead, which is
what lets the failure paths be tested at all.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.export_job import (
    BakeJob,
    JobStatus,
    default_out_dir,
    export_now,
    world_lock,
)
from simulation import World


@pytest.fixture(scope="module")
def world():
    w = World(n_founders=10, seed=7)      # the DASHBOARD's default, not 12
    for _ in range(25):
        w.step()
    return w


# ----------------------------------------------------------------------
# phase 1: the live world, in one piece
# ----------------------------------------------------------------------

def test_the_bundle_and_the_bodies_describe_the_same_cast(world, tmp_path):
    """The whole reason the button exists.

    Run the two exporters separately with different flags and the bodies
    belong to different people than the villagers on screen, while enough
    names match that the village still draws. Here there are no flags.
    """
    import csv

    result = export_now(world, str(tmp_path / "w"), staged=True)

    with open(Path(result.bundle_dir) / "people.csv", encoding="utf-8") as fh:
        in_bundle = {r["name"] for r in csv.DictReader(fh)}

    import json
    manifest = json.loads(
        (Path(result.bodies_dir) / "bodies.json").read_text(encoding="utf-8"))
    with_bodies = {b["name"] for b in manifest["bodies"]}
    never = {u["name"] for u in manifest["never_rendered"]}

    # Every person is accounted for: they have a body, or they are named as
    # someone who could never have one. Nobody falls off the list silently.
    assert with_bodies | never == in_bundle, (
        f"unaccounted for: {sorted(in_bundle - with_bodies - never)}")


def test_staged_export_makes_more_bodies_than_people(world, tmp_path):
    result = export_now(world, str(tmp_path / "w"), staged=True)
    assert result.staged is True
    assert result.bodies > result.people, "staging bought nothing"


def test_unstaged_export_makes_exactly_one_body_per_person(world, tmp_path):
    result = export_now(world, str(tmp_path / "w"), staged=False)
    assert result.staged is False
    assert result.bodies == result.people


def test_export_holds_the_world_lock_while_it_reads(world, tmp_path):
    """The concurrency claim, asserted rather than asserted-in-a-comment.

    Dash serves callbacks on threads, so an export and the dashboard's own
    `WORLD.step()` genuinely overlap. Without the lock the export is torn:
    some people captured at one tick and some at the next, which is the
    mismatch this module exists to remove, arrived at from inside.
    """
    held = threading.Event()
    released = threading.Event()

    def watcher():
        # Cannot take the lock while the export holds it, so this blocks.
        held.wait(timeout=10)
        got = world_lock().acquire(blocking=False)
        if got:
            world_lock().release()
        released.set()
        watcher.acquired_during_export = got

    watcher.acquired_during_export = None
    t = threading.Thread(target=watcher, daemon=True)
    t.start()

    real_lock = world_lock()
    original_enter = real_lock.__enter__

    # Signal the watcher the moment the export is inside the lock.
    class Probe:
        def __enter__(self):
            r = original_enter()
            held.set()
            time.sleep(0.15)
            return r

        def __exit__(self, *a):
            return real_lock.__exit__(*a)

    import dashboard.export_job as EJ
    monkeyed = EJ.world_lock
    EJ.world_lock = lambda: Probe()
    try:
        export_now(world, str(tmp_path / "w"), staged=False)
    finally:
        EJ.world_lock = monkeyed

    released.wait(timeout=10)
    assert watcher.acquired_during_export is False, (
        "the world lock was free while the export was reading the world")


def test_default_out_dir_is_keyed_on_the_seed(world):
    """Two different worlds must not overwrite each other's bodies while
    `bodies.json` still names the first world's people."""
    a = default_out_dir(world)
    other = World(n_founders=10, seed=99)
    assert default_out_dir(other) != a
    assert "7" in Path(a).name


# ----------------------------------------------------------------------
# phase 2: the progress parser and the status machine
# ----------------------------------------------------------------------

class FakeBlender:
    """Stands in for `subprocess.Popen`, emitting bake lines then exiting."""

    def __init__(self, lines, code=0):
        self.stdout = iter(lines)
        self._code = code
        self.terminated = False

    def poll(self):
        return self._code

    def wait(self):
        return self._code

    def terminate(self):
        self.terminated = True


def _run_fake(monkeypatch, lines, code=0, expected=3):
    job = BakeJob()
    monkeypatch.setattr("dashboard.export_job._find_blender",
                        lambda: "C:/fake/blender.exe")
    monkeypatch.setattr(subprocess, "Popen",
                        lambda *a, **k: FakeBlender(lines, code))
    job.start("/bodies", expected=expected)
    for _ in range(200):
        if not job.status().running:
            break
        time.sleep(0.01)
    return job


BAKE_LINES = [
    "[BAKE] blender 4.4.3, mpfb 2.0.17, 3 bodies, subdiv 0",
    "[BAKE]   1/3  Ada-16_child       1.1460 m   7824 verts    2.4s",
    "[BAKE]   2/3  Ada-16_adult       1.7700 m   8550 verts    2.5s",
    "[BAKE]   3/3  Bran-10_adult      1.8100 m   9512 verts    2.3s",
    "[BAKE] done in 7s, 2.4s each",
]


def test_progress_follows_the_bakes_own_count(monkeypatch):
    """Read from Blender's stdout, not from the caller's expectation.

    The two differ when `--limit` is in play or the manifest moved, and
    trusting the caller's number shows a bar that stops at 80% on a complete
    run. `expected` is 99 here and the bake says 3.
    """
    job = _run_fake(monkeypatch, BAKE_LINES, expected=99)
    st = job.status()
    assert st.phase == "done"
    assert (st.done, st.total) == (3, 3)
    assert st.fraction == pytest.approx(1.0)


def test_the_header_line_is_not_counted_as_a_bake(monkeypatch):
    """`[BAKE] blender 4.4.3, mpfb 2.0.17, 3 bodies` starts with the same tag
    as a progress line and contains the number 3. A looser pattern reads it as
    3 of 3 done before anything has been baked."""
    job = _run_fake(monkeypatch, [BAKE_LINES[0]], expected=3)
    assert job.status().done == 0


def test_a_bake_that_dies_reads_as_failed_not_finished(monkeypatch):
    """The dangerous case. A bake that stops at 2 of 3 and exits non-zero must
    not report success, or the village is missing a body nobody looks for."""
    job = _run_fake(monkeypatch, BAKE_LINES[:3], code=1, expected=3)
    st = job.status()
    assert st.phase == "failed"
    assert "1" in st.error
    assert st.done == 2, "progress made before the failure is still reported"


def test_a_second_start_while_one_is_running_is_ignored(monkeypatch):
    """Two Blender processes writing one FBX directory interleave, and the
    loser's file is whatever the winner wrote last."""
    job = BakeJob()
    monkeypatch.setattr("dashboard.export_job._find_blender",
                        lambda: "C:/fake/blender.exe")
    started = []

    def slow(*a, **k):
        started.append(1)
        return FakeBlender(iter(_Blocking()), 0)

    class _Blocking(list):
        def __iter__(self):
            time.sleep(0.4)
            return iter([])

    monkeypatch.setattr(subprocess, "Popen", slow)
    job.start("/bodies", expected=3)
    job.start("/bodies", expected=3)
    assert len(started) == 1
    job.cancel()


def test_a_missing_blender_fails_loudly_rather_than_hanging(monkeypatch):
    job = BakeJob()

    def boom():
        raise RuntimeError("no installed Blender at or above 4.2")

    monkeypatch.setattr("dashboard.export_job._find_blender", boom)
    st = job.start("/bodies", expected=3)
    assert st.phase == "failed"
    assert "Blender" in st.error
    assert not st.running


# ----------------------------------------------------------------------
# the status object itself
# ----------------------------------------------------------------------

def test_eta_is_absent_until_there_is_a_rate_to_measure():
    """A borrowed benchmark is a guess wearing a number's clothes. Before a
    single body is baked this run has no rate, so it reports nothing."""
    assert JobStatus(phase="baking", done=0, total=10,
                     started=time.time()).eta_seconds() is None
    assert JobStatus(phase="idle").eta_seconds() is None


def test_eta_comes_from_this_runs_own_rate():
    st = JobStatus(phase="baking", done=2, total=10,
                   started=time.time() - 10.0)
    # 5 s a body so far, 8 to go.
    assert st.eta_seconds() == pytest.approx(40.0, rel=0.2)


def test_fraction_never_exceeds_one():
    """A bake reporting more bodies than expected must not drive a progress
    bar past its own end."""
    assert JobStatus(done=12, total=10).fraction == 1.0
    assert JobStatus(done=0, total=0).fraction == 0.0
