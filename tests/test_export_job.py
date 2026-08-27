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

import json
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


class FakeBatches:
    """A `Popen` stand-in that reads `--start` and `--limit` off the command.

    The plain `FakeBlender` returns the same canned lines whatever it is
    asked for, which is fine for the parser and useless for the batch loop: an
    offset bug, a batch that repeats bodies and a batch that skips them all
    produce identical output against a fake that ignores its arguments. This
    one generates the lines the real bake would print for the slice it was
    handed, and records the slices so a test can check they tile the village.
    """

    def __init__(self, code=0, on_batch=None):
        self.batches = []
        self.job = None          # set by `_run_batched` before the job starts
        self._code = code
        self._on_batch = on_batch

    def __call__(self, cmd, *a, **k):
        start = int(cmd[cmd.index("--start") + 1])
        limit = int(cmd[cmd.index("--limit") + 1])
        self.batches.append((start, limit))
        if self._on_batch is not None:
            self._on_batch(self, start, limit)
        lines = [f"[BAKE] blender 4.4.3, mpfb 2.0.17, {limit} bodies, subdiv 0"]
        lines += [f"[BAKE] {i:3d}/{limit}  P-{start + i:<12d} "
                  f"1.7700 m   8550 verts    2.4s"
                  for i in range(1, limit + 1)]
        lines.append(f"[BAKE] done in {limit * 2}s, 2.4s each")
        return FakeBlender(lines, self._code)


def _manifest_dir(tmp_path, n):
    """A `bodies.json` with `n` entries, which is what the batch loop counts."""
    bodies = [{"name": f"P-{i}", "stem": f"P-{i}_adult",
               "mhm": f"P-{i}_adult.mhm"} for i in range(n)]
    (tmp_path / "bodies.json").write_text(
        json.dumps({"count": n, "people": n, "staged": False,
                    "bodies": bodies}), encoding="utf-8")
    return str(tmp_path)


def _settle(job, ticks=400):
    for _ in range(ticks):
        if not job.status().running:
            break
        time.sleep(0.01)
    return job


def _run_fake(monkeypatch, lines, code=0, expected=3, bodies_dir="/bodies"):
    job = BakeJob()
    monkeypatch.setattr("dashboard.export_job._find_blender",
                        lambda: "C:/fake/blender.exe")
    monkeypatch.setattr(subprocess, "Popen",
                        lambda *a, **k: FakeBlender(lines, code))
    job.start(bodies_dir, expected=expected)
    return _settle(job)


def _run_batched(monkeypatch, bodies_dir, total, batch, code=0, on_batch=None):
    job = BakeJob(batch=batch)
    popen = FakeBatches(code=code, on_batch=on_batch)
    popen.job = job
    monkeypatch.setattr("dashboard.export_job._find_blender",
                        lambda: "C:/fake/blender.exe")
    monkeypatch.setattr(subprocess, "Popen", popen)
    job.start(bodies_dir, expected=total)
    return _settle(job), popen


BAKE_LINES = [
    "[BAKE] blender 4.4.3, mpfb 2.0.17, 3 bodies, subdiv 0",
    "[BAKE]   1/3  Ada-16_child       1.1460 m   7824 verts    2.4s",
    "[BAKE]   2/3  Ada-16_adult       1.7700 m   8550 verts    2.5s",
    "[BAKE]   3/3  Bran-10_adult      1.8100 m   9512 verts    2.3s",
    "[BAKE] done in 7s, 2.4s each",
]


def test_the_total_comes_from_the_manifest_not_the_caller(tmp_path, monkeypatch):
    """The denominator is `bodies.json`, the list the bake itself indexes.

    It used to be read off the bake's own progress line, which was right while
    one process baked everything and is wrong now that the bake runs in
    batches: a batch counts within the BATCH, so a bar fed that denominator
    would read "80/80" three times over on a 240-body village. The caller's
    `expected` is not trusted either, and the 99 here is deliberately wrong,
    because it is the number that produced two different casts in the first
    place.
    """
    bodies_dir = _manifest_dir(tmp_path, 10)
    job, _popen = _run_batched(monkeypatch, bodies_dir, total=99, batch=4)
    st = job.status()
    assert st.phase == "done"
    assert (st.done, st.total) == (10, 10)
    assert st.fraction == pytest.approx(1.0)


def test_the_batches_tile_the_village_exactly_once(tmp_path, monkeypatch):
    """Every body baked, none baked twice, and the last batch short.

    A batch loop has three classic off-by-ones and they all render: bodies
    skipped at a boundary leave villagers on the shared mesh, bodies baked
    twice cost minutes, and a last batch that runs past the end makes Blender
    slice an empty list and exit successfully having done nothing.
    """
    bodies_dir = _manifest_dir(tmp_path, 10)
    job, popen = _run_batched(monkeypatch, bodies_dir, total=10, batch=4)
    assert job.status().phase == "done"
    assert popen.batches == [(0, 4), (4, 4), (8, 2)]
    covered = [i for start, limit in popen.batches
               for i in range(start, start + limit)]
    assert covered == list(range(10))


def test_the_bar_does_not_restart_at_each_batch(tmp_path, monkeypatch):
    """The offset, checked where it would fail silently.

    Without it the bar runs 1 to 4 and then 1 to 4 again, and the run looks
    stuck at 40% for half an hour. Progress is sampled as each batch is
    launched, before it has printed anything, so these are the totals carried
    over from the batches before it.
    """
    seen = []

    def on_batch(factory, start, limit):
        seen.append(factory.job.status().done)

    bodies_dir = _manifest_dir(tmp_path, 10)
    job, _popen = _run_batched(monkeypatch, bodies_dir, total=10, batch=4,
                               on_batch=on_batch)
    assert seen == [0, 4, 8]
    assert job.status().done == 10


def test_cancel_stops_the_loop_and_not_just_one_batch(tmp_path, monkeypatch):
    """The hazard the batch loop introduces, and the reason `cancel()` sets a
    flag before it kills anything.

    Terminating the current Blender ends one batch. Without the flag the loop
    reads that as a batch finishing and starts the next one, so the work
    carries on for another half hour behind a button that already said
    cancelled and a status that already said failed.
    """
    def on_batch(factory, start, limit):
        if len(factory.batches) == 1:
            factory.job.cancel()

    bodies_dir = _manifest_dir(tmp_path, 40)
    job, popen = _run_batched(monkeypatch, bodies_dir, total=40, batch=4,
                              on_batch=on_batch)
    assert len(popen.batches) == 1, "the loop kept going after cancel"
    st = job.status()
    assert st.phase == "failed"
    assert "cancelled" in st.error


def test_a_batch_that_dies_stops_the_run_and_names_the_bodies(tmp_path,
                                                              monkeypatch):
    """A failure in batch two must not be reported as a finished bake, and the
    error has to say WHICH bodies, because the recovery is a `--start`."""
    bodies_dir = _manifest_dir(tmp_path, 10)
    job, popen = _run_batched(monkeypatch, bodies_dir, total=10, batch=4,
                              code=3)
    st = job.status()
    assert st.phase == "failed"
    assert len(popen.batches) == 1, "it kept baking after a batch failed"
    assert "1 to 4 of 10" in st.error


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
