"""
Export the world on screen for the Unity viewer, and bake its bodies.
=====================================================================

The owner's architecture, and it is the right one: run the engine in the
dashboard, press a button, open the result in Unity. Simulating first is what
removes the blocker that made a LIVE link pointless. A body is baked in
Blender, out of process, at a measured 2.50 s, so a villager BORN during live
stepping cannot have a genome-driven body and falls back to the shared mesh
until someone re-bakes; in a genetics simulator the newborns are the point.
Export after the run has finished and that problem does not exist, because the
whole cast is already known before the first bake starts. The cost does not
get smaller, it moves off the critical path.

WHY THIS BUTTON RATHER THAN THE TWO COMMANDS THAT ALREADY EXISTED. `export_
for_unity.py` and `export_bodies.py --bundle` do the work, but only from a
world THEY build from flags. The dashboard's world is built from the sliders,
and the defaults differ: the dashboard opens with 10 founders and
`export_bodies.py` with 12. Two different worlds, two different casts, and the
symptom is not a crash. Timeline sync works, selection sync silently does
nothing, and the village on screen renders perfectly because enough names
happen to match. This exports `WORLD` itself, so there is one world and the
question cannot arise.

THE TWO PHASES, AND WHY ONLY THE SECOND ONE IS THREADED
-------------------------------------------------------
Phase 1, the bundle and the `.mhm` files, READS THE LIVE WORLD and takes a few
seconds. Phase 2, the bake, reads only the files phase 1 wrote and takes
minutes.

That difference decides the design. Running phase 1 on a background thread
would let the dashboard's own timer call `WORLD.step()` half way through it,
and the export would come out torn: some people captured at tick 60 and some
at 61, with `frames.csv` and `bodies.json` disagreeing about who exists. That
is the same mismatch this module exists to remove, arrived at from inside. So
phase 1 runs SYNCHRONOUSLY in the callback, under `world_lock()`, and the user
waits a few seconds; phase 2 runs on a thread, because by then nothing it
touches can change.

The consequence is the good one: Unity can open the bundle as soon as the
button returns, with the shared mesh, and the real bodies appear when the bake
lands.

WHAT THIS DOES NOT DO. It does not install anything into a Unity project. The
package reference in a consuming project carries CODE ONLY, so FBX bodies and
world bundles are assets and have to be copied in separately. Saying "exported"
and meaning "visible in your editor" is a claim this module is not entitled to
make, so it reports paths and says what to do with them.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field, replace
from typing import List, Optional


# ----------------------------------------------------------------------
# the lock
# ----------------------------------------------------------------------

_WORLD_LOCK = threading.RLock()


def world_lock() -> threading.RLock:
    """The lock held while the world is stepped, and while it is exported.

    Dash serves callbacks on threads, so `advance()` calling `WORLD.step()`
    and an export reading `WORLD` genuinely do overlap. Every other callback
    only READS the world and a stale panel is harmless, which is why this is
    not held everywhere: it is held exactly where a torn read would be
    written to disk and later believed.

    Re-entrant because the export path takes it once and calls into code that
    is free to take it again.
    """
    return _WORLD_LOCK


# ----------------------------------------------------------------------
# how big a batch is
# ----------------------------------------------------------------------

# Bodies per Blender process. The bake is a loop of these rather than one
# long process, for the two reasons set out in `BakeJob._run`.
#
# WHERE THE NUMBER COMES FROM. Per-body cost is
#
#     base + S / B + d * B / 2
#
# for a batch of B, where S is Blender startup plus MPFB init, paid once per
# batch, and d is the per-body slowdown inside one process. Smallest at
# B = sqrt(2 * S / d). Both inputs are now measured:
#
#   base = 2.534 s, d = 0.00598 s per body. Least squares over all 685 bodies
#       of the dashboard-4 bake, from `fbx/bake_report.json`. The run went
#       from 2.26 s a body over the first twenty to 6.27 s over the last
#       twenty and never levelled off. An earlier reading of this curve called
#       it a plateau at body 160; it was not, and the whole-run fit is what
#       settled it.
#   S = 9.85 s. MEASURED, by timing a `--limit 1` bake end to end (12.11 s
#       wall) and subtracting the steady-state cost of the one body in it.
#       An earlier revision of this comment guessed 25 s from the gap between
#       process launch and first FBX, which was wrong by a factor of 2.5.
#
# sqrt(2 * 9.85 / 0.00598) is 57.
#
# AND THE CHOICE BARELY MATTERS, which is worth knowing before anyone tunes
# it. Projected minutes for a 685-body village: 35.2 at B=20, 33.1 at 40,
# 32.8 at 56, 33.1 at 80, 34.5 at 140. Every batch size from 40 to 100 lands
# within 1.5% of the best. What matters is that B is finite: the same village
# in ONE process measured 52.3 minutes.
BATCH_BODIES = 56


# ----------------------------------------------------------------------
# job status
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class JobStatus:
    """A snapshot of the bake, safe to read from a callback thread.

    Frozen and returned by value rather than handed out live: a status object
    that mutated while a callback formatted it would render a line describing
    two different moments.
    """
    phase: str = "idle"          # idle | exporting | baking | done | failed
    done: int = 0
    total: int = 0
    message: str = ""
    error: str = ""
    bundle_dir: str = ""
    bodies_dir: str = ""
    started: float = 0.0
    finished: float = 0.0

    @property
    def running(self) -> bool:
        return self.phase in ("exporting", "baking")

    @property
    def fraction(self) -> float:
        return 0.0 if self.total <= 0 else min(1.0, self.done / self.total)

    @property
    def elapsed(self) -> float:
        end = self.finished if self.finished else time.time()
        return max(0.0, end - self.started) if self.started else 0.0

    def eta_seconds(self) -> Optional[float]:
        """Remaining time from the rate THIS run has achieved, not from the
        2.50 s the village measured. A slower machine, a bigger asset pack or
        a different subdivision level all change it, and a progress line that
        quotes someone else's benchmark is a guess wearing a number's clothes.
        """
        if self.phase != "baking" or self.done <= 0 or self.total <= 0:
            return None
        rate = self.elapsed / self.done
        return max(0.0, rate * (self.total - self.done))


class BakeJob:
    """Runs the Blender bake on a thread and reports progress.

    One at a time, deliberately. Two Blender processes writing the same FBX
    directory would interleave their output and the loser's file would be
    whatever the winner wrote last; and the useful reading of a second click
    is "I want this again", not "I want two".
    """

    _BAKE_LINE = re.compile(r"^\[BAKE\]\s+(\d+)\s*/\s*(\d+)\b")

    def __init__(self, batch: int = BATCH_BODIES) -> None:
        self._status = JobStatus()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._proc: Optional[subprocess.Popen] = None
        self._cancelled = threading.Event()
        self._batch = max(1, int(batch))

    # -- reading ------------------------------------------------------

    def status(self) -> JobStatus:
        with self._lock:
            return self._status

    def _set(self, **kw) -> None:
        with self._lock:
            self._status = replace(self._status, **kw)

    # -- writing ------------------------------------------------------

    def start(self, bodies_dir: str, expected: int,
              blender: Optional[str] = None) -> JobStatus:
        """Launch the bake. Returns immediately with the new status."""
        with self._lock:
            if self._status.running:
                return self._status

        try:
            exe = blender or str(_find_blender())
        except Exception as exc:                          # noqa: BLE001
            self._set(phase="failed", error=str(exc),
                      message="no Blender found", finished=time.time())
            return self.status()

        total = _total_from_manifest(bodies_dir, expected)
        self._cancelled.clear()
        self._set(phase="baking", done=0, total=total, error="",
                  message="starting Blender", bodies_dir=bodies_dir,
                  started=time.time(), finished=0.0)

        self._thread = threading.Thread(
            target=self._run, args=(exe, bodies_dir, total), daemon=True,
            name="extnpc-bake")
        self._thread.start()
        return self.status()

    def cancel(self) -> None:
        """Stop the bake. The FBX files already written stay: they are whole
        files for whole villagers, and `bodies.json` names every body whether
        or not its FBX is installed, so a partial bake is a bundle with some
        villagers on the shared mesh, which is a supported state.

        THE FLAG IS SET BEFORE THE PROCESS IS KILLED, and the order is the
        whole of it. The bake is a loop of batches now, so terminating the
        current Blender without the flag would end one batch and let the loop
        start the next: the button would report cancelled while the work
        carried on for another half hour."""
        self._cancelled.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
        self._set(message="cancelled", phase="failed",
                  error="cancelled by the user", finished=time.time())

    def _run(self, exe: str, bodies_dir: str, total: int) -> None:
        """Bake `total` bodies as a sequence of batches, one process each.

        WHY NOT ONE PROCESS, which is what this was until it was measured. A
        single Blender accumulates orphaned MPFB datablocks across sequential
        `.mhm` loads and slows as it goes. Measured on the 685-body
        dashboard-4 export: 2.21 s a body over bodies 1 to 20, 3.50 s over 61
        to 80, and 4.60 s over 336 to 356. That is a rise of roughly 0.007 s
        per body which had not levelled off by a third of the way in, and
        integrated over 685 bodies it is about 53 minutes against about 25 at
        the fresh rate.

        THE SECOND REASON IS THE ONE THAT LOSES DATA, and it is not about
        speed at all. `_record_statures` and the bake report are written ONCE,
        after the last body of a process. A single run therefore carries every
        villager's `body_stature_m` in memory for the whole bake and commits
        it at the end, so a crash at body 600 leaves `bodies.json` with none
        of them. Worse, the obvious recovery does not recover: `--start 600`
        stamps only the bodies that run baked, because `_record_statures`
        deliberately leaves entries it did not measure alone, so 0 to 599 stay
        unstamped for good short of baking them again. Unity then falls back
        to measuring the combined mesh, which includes hair, and every
        villager loses height in proportion to their hairstyle while nothing
        on screen looks wrong. Batching commits both files every `batch`
        bodies, so a crash costs one batch.
        """
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = os.path.join(repo, "mpfb", "bake_bodies.py")
        tail: List[str] = []

        for start in range(0, total, self._batch):
            if self._cancelled.is_set():
                return
            limit = min(self._batch, total - start)
            cmd = [exe, "-b", "-P", script, "--", "--bodies", bodies_dir,
                   "--start", str(start), "--limit", str(limit)]
            code, tail = self._run_batch(cmd, start, total)
            # Checked again after the batch: `cancel()` terminates the child,
            # which surfaces here as a non-zero exit, and reporting that as a
            # Blender failure would bury the real reason under a stack of
            # Blender's shutdown chatter.
            if self._cancelled.is_set():
                return
            if code != 0:
                self._set(phase="failed", finished=time.time(),
                          error=f"Blender exited {code} while baking bodies "
                                f"{start + 1} to {start + limit} of {total}",
                          message="\n".join(tail[-12:]))
                return

        st = self.status()
        self._set(phase="done", finished=time.time(),
                  message=f"baked {st.done} bodies")

    def _run_batch(self, cmd: List[str], offset: int, total: int):
        """One Blender process. Returns its exit code and the tail of its log.

        The progress line a batch prints counts within the BATCH, so it is
        offset here. Reporting the batch's own number would send the bar back
        to zero every `batch` bodies. The single-process version warned
        against trusting the caller's expectation for the denominator and it
        was right to: `total` comes from `bodies.json` via
        `_total_from_manifest`, which is the same list the bake indexes.
        """
        tail: List[str] = []
        try:
            # Line-buffered text, and stderr folded in: Blender writes its
            # own startup chatter to both and the progress lines are the only
            # thing read out of either.
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as exc:                          # noqa: BLE001
            self._set(phase="failed", error=str(exc),
                      message="could not start Blender", finished=time.time())
            return 1, [str(exc)]

        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            tail.append(line)
            del tail[:-40]
            m = self._BAKE_LINE.match(line)
            if m:
                self._set(done=min(total, offset + int(m.group(1))),
                          total=total, message=line)

        return self._proc.wait(), tail


JOB = BakeJob()


# ----------------------------------------------------------------------
# phase 1: the part that reads the live world
# ----------------------------------------------------------------------

@dataclass
class ExportResult:
    bundle_dir: str
    bodies_dir: str
    bodies: int
    people: int
    staged: bool
    seconds: float
    never_rendered: List[dict] = field(default_factory=list)


def export_now(world, out_dir: str, staged: bool = True) -> ExportResult:
    """Write the bundle and the `.mhm` files from THIS world. Seconds, not
    minutes, and synchronous for the reason in the module docstring.

    Both halves come off the same `world` object in one call, which is the
    whole point: `export_bodies.py` documents at length that running the two
    exporters separately lets their flags drift apart and produces bodies
    belonging to different people than the villagers on screen. Here there
    are no flags to drift.
    """
    from export_bodies import (select_everyone, select_everyone_staged,
                               targets_from_names, write_bodies)
    from health_engine.mhm_assets import MissingAssetPack, load_catalogue
    from simulation.export import export_world_dir

    t0 = time.perf_counter()
    with world_lock():
        bundle = export_world_dir(world, out_dir,
                                  note="exported from the dashboard")
        targets = (select_everyone_staged(world) if staged else
                   targets_from_names(world, select_everyone(world)))

        try:
            catalogue = load_catalogue()
        except MissingAssetPack:
            # A reported fallback, never a silent one: bare bodies are a
            # legitimate export and an eyeless mannequin nobody expected is
            # not. The caller surfaces this in the status line.
            catalogue = None

        bodies_dir = os.path.join(out_dir, "bodies")
        manifest = write_bodies(world, targets, bodies_dir,
                                catalogue=catalogue)

    return ExportResult(
        bundle_dir=str(bundle),
        bodies_dir=bodies_dir,
        bodies=int(manifest["count"]),
        people=int(manifest["people"]),
        staged=bool(manifest["staged"]),
        seconds=time.perf_counter() - t0,
        never_rendered=list(manifest.get("never_rendered", [])),
    )


def _total_from_manifest(bodies_dir: str, expected: int) -> int:
    """How many bodies there are, asked of the manifest rather than assumed.

    The batch loop needs a real total, because it slices `--start` and
    `--limit` out of it: a number that is too small silently leaves the tail
    of the village unbaked and then reports success, which is the worst shape
    a bug can take here. `bodies.json` is the file `bake_bodies.py` itself
    indexes, so reading it means both sides are counting the same list.

    `expected` survives only as the fallback for a manifest that cannot be
    read, where baking what the caller asked for beats refusing to start.
    """
    try:
        path = os.path.join(bodies_dir, "bodies.json")
        with open(path, encoding="utf-8") as fh:
            return len(json.load(fh)["bodies"])
    except (OSError, ValueError, KeyError, TypeError):
        return int(expected)


def _find_blender():
    """Reuse the probe's locator rather than hardcoding an install path.

    `run_mpfb_probe.find_blender()` already honours `$BLENDER`, scans the Hub
    layout and enforces a minimum version. A second copy of that here would
    be a second thing to update when Blender moves.
    """
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo not in sys.path:
        sys.path.insert(0, repo)
    from run_mpfb_probe import find_blender
    return find_blender()


def default_out_dir(world) -> str:
    """Where an unconfigured export lands: `outputs/unity/dashboard-<seed>`.

    Keyed on the SEED so exporting two different worlds does not have the
    second silently overwrite the first's bodies while `bodies.json` still
    names the first's people.
    """
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo, "outputs", "unity",
                        f"dashboard-{int(world.seed)}")
