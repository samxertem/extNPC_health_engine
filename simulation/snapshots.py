"""
Per-tick world snapshots: the substrate for time travel.
========================================================

`World.history` is a list of *scalar* rows -- one number per metric per year.
That is enough to redraw a time series, and `metrics.py` says plainly why it
stops there: "Distributions that only matter for the current frame ... are
computed on demand by the panel builders from the live list, not stored, to
keep the history compact."

The consequence bites as soon as you want to scrub backwards. The charts can
be rebuilt from `history`, but the *people* who were alive in year 50 are gone
-- the map, the leaderboards and the inspector have nothing to reconstruct
from. This module fixes that with the smallest thing that works: a compact,
capped, per-tick frame of exactly the fields the UI reads.

What is deliberately NOT stored
-------------------------------
Genomes, epigenomes, pedigrees, physiological state vectors. A single NPC
carries a (2, 500) haplotype array plus three (500,) epigenetic mark vectors;
retaining that for every individual for every year would be hundreds of
megabytes and would turn a browsable history into a memory leak. So a frame
holds the ~12 scalars the map and the directory actually draw, and nothing
else.

This has an honest consequence the UI must respect and does: **for a past
tick you can see who was alive, where they stood, and their headline stats,
but you cannot open the full genetic character sheet of someone long dead.**
Deep inspection is available for the living. The dashboard marks historical
mode explicitly rather than silently degrading.

Cost
----
~150 people x ~12 floats x `MAX_FRAMES` ticks. At the 600-frame cap that is
roughly a million small values -- a few MB, bounded, and it never grows past
the cap because the buffer discards its oldest frame.

Capture is strictly read-only: it touches no generator and appends after the
step has finished, so it cannot perturb the calibrated RNG stream.
"""

from __future__ import annotations

from collections import deque
from typing import Deque, Dict, List, Optional

import numpy as np

# How many yearly frames to retain. A 250-year demo run fits comfortably;
# beyond the cap the oldest frames are dropped and the scrubber's lower bound
# follows the window.
MAX_FRAMES: int = 600


def _person_rows(world) -> List[dict]:
    """
    Compact per-living-person record. Field names match what the canvas
    renderer and the directory already expect, so nothing downstream has to
    translate between a live frame and a historical one.
    """
    rows = []
    ped = world.pedigree()          # cached; one memo shared by this whole loop
    for npc in world.living:
        meta = world.meta[npc.name]
        dom, purity = world.registry.dominant(meta.ancestry)
        cx, cy = world.deme_centers[min(meta.deme, len(world.deme_centers) - 1)]
        from .community import person_map_offset
        ox, oy = person_map_offset(npc.name, world.territory_radius)
        rows.append({
            "name": npc.name,
            "x": float(cx + ox),
            "y": float(cy + oy),
            "color": meta.color,
            "sex": npc.sex,
            "age": int(npc.age),
            "deme": int(meta.deme),
            "lineage": dom,
            "purity": round(float(purity), 2),
            "generation": int(npc.generation),
            "children": int(meta.n_children),
            # physiological load, for the stress overlay and the leaderboards
            "stress": round(float(npc.inflammation_state), 3),
            "epi_accel": round(float(npc.epigenetic_age_acceleration), 2),
            "aerobic": round(float(npc.effective_aerobic_capacity()), 3),
            "conditions": len(npc.medical_conditions),
            # Session-11 layers. Cheap scalars, so time travel keeps them:
            # pedigree F (#31), relative viability (#31 + #12) and the number
            # of copy-number variants carried (#12). Note what is NOT here --
            # the load genotypes themselves, for the same reason genomes are
            # not: they would dominate the frame size.
            "pedigree_f": round(float(ped.inbreeding(npc.name)), 4),
            "viability": round(float(npc.relative_viability()), 3),
            "cnv": len(npc.cnv_variants()),
            # Height AS EXPRESSED AT THIS AGE (#13), not the mature value.
            # A child in a historical frame must not be drawn adult-sized.
            "height": round(float(npc.height_at_age()), 1),
            "life_stage": npc.life_stage(),
        })
    return rows


def _deme_rows(world, people: List[dict]) -> List[dict]:
    """
    Per-settlement aggregates, computed once at capture instead of re-derived
    on every render. Feeds the map's territory rings and both heatmap layers
    (bloodline dominance, physiological stress).
    """
    by_deme: Dict[int, List[dict]] = {}
    for p in people:
        by_deme.setdefault(p["deme"], []).append(p)

    out = []
    for d in range(max(1, world.params.n_demes)):
        cx, cy = world.deme_centers[min(d, len(world.deme_centers) - 1)]
        members = by_deme.get(d, [])
        stresses = [m["stress"] for m in members]
        # dominant bloodline in this settlement, and how dominant it is
        counts: Dict[str, int] = {}
        for m in members:
            counts[m["lineage"]] = counts.get(m["lineage"], 0) + 1
        if counts:
            top = max(counts.items(), key=lambda kv: kv[1])
            dom_name, dom_share = top[0], top[1] / len(members)
            dom_color = next(m["color"] for m in members if m["lineage"] == dom_name)
        else:
            dom_name, dom_share, dom_color = "-", 0.0, "#888888"
        out.append({
            "deme": d,
            "x": float(cx), "y": float(cy),
            "r": float(world.territory_radius),
            "n": len(members),
            "mean_stress": round(float(np.mean(stresses)), 3) if stresses else 0.0,
            "max_stress": round(float(np.max(stresses)), 3) if stresses else 0.0,
            "dominant": dom_name,
            "dominance": round(dom_share, 3),
            "dominant_color": dom_color,
        })
    return out


def capture(world) -> dict:
    """
    Build one frame for the current world state. Read-only: draws no random
    numbers and mutates nothing, so it cannot disturb the RNG stream.
    """
    people = _person_rows(world)
    flows = [{"x0": f["x0"], "y0": f["y0"], "x1": f["x1"], "y1": f["y1"],
              "w": f["weight"]} for f in world.map_flows()]
    return {
        "tick": int(world.tick),
        "people": people,
        "demes": _deme_rows(world, people),
        "flows": flows,
        "n_alive": len(people),
    }


class SnapshotBuffer:
    """A bounded, tick-indexed ring of world frames."""

    def __init__(self, max_frames: int = MAX_FRAMES) -> None:
        self._frames: Deque[dict] = deque(maxlen=max_frames)

    def __len__(self) -> int:
        return len(self._frames)

    def append(self, frame: dict) -> None:
        self._frames.append(frame)

    def clear(self) -> None:
        self._frames.clear()

    @property
    def ticks(self) -> List[int]:
        return [f["tick"] for f in self._frames]

    @property
    def first_tick(self) -> int:
        return self._frames[0]["tick"] if self._frames else 0

    @property
    def last_tick(self) -> int:
        return self._frames[-1]["tick"] if self._frames else 0

    def at(self, tick: Optional[int]) -> Optional[dict]:
        """
        The frame for `tick`, or the nearest earlier one still retained.

        Returns the latest frame when `tick` is None (live mode) and None when
        nothing has been captured yet. Falling back to the nearest earlier
        frame keeps the scrubber usable after old frames age out of the cap
        rather than showing an empty map.
        """
        if not self._frames:
            return None
        if tick is None:
            return self._frames[-1]
        best = None
        for f in self._frames:
            if f["tick"] <= tick:
                best = f
            else:
                break
        return best if best is not None else self._frames[0]
