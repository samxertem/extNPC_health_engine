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

    def __init__(self) -> None:
        self._status = JobStatus()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._proc: Optional[subprocess.Popen] = None

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

        self._set(phase="baking", done=0, total=expected, error="",
                  message="starting Blender", bodies_dir=bodies_dir,
                  started=time.time(), finished=0.0)

        self._thread = threading.Thread(
            target=self._run, args=(exe, bodies_dir), daemon=True,
            name="extnpc-bake")
        self._thread.start()
        return self.status()

    def cancel(self) -> None:
        """Stop the bake. The FBX files already written stay: they are whole
        files for whole villagers, and `bodies.json` names every body whether
        or not its FBX is installed, so a partial bake is a bundle with some
        villagers on the shared mesh, which is a supported state."""
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
        self._set(message="cancelled", phase="failed",
                  error="cancelled by the user", finished=time.time())

    def _run(self, exe: str, bodies_dir: str) -> None:
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = os.path.join(repo, "mpfb", "bake_bodies.py")
        cmd = [exe, "-b", "-P", script, "--", "--bodies", bodies_dir]
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
            return

        tail: List[str] = []
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            tail.append(line)
            del tail[:-40]
            m = self._BAKE_LINE.match(line)
            if m:
                # The bake's OWN count, not the one the caller expected. They
                # differ if `--limit` is in play or the manifest moved under
                # us, and trusting the caller's number would show a progress
                # bar that stops at 80% on a complete run.
                self._set(done=int(m.group(1)), total=int(m.group(2)),
                          message=line)

        code = self._proc.wait()
        if code == 0:
            st = self.status()
            self._set(phase="done", finished=time.time(),
                      message=f"baked {st.done} bodies")
        else:
            self._set(phase="failed", finished=time.time(),
                      error=f"Blender exited {code}",
                      message="\n".join(tail[-12:]))


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
