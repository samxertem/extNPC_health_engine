"""
Founder-ancestry tracking -> the "family" colour of every individual.
=====================================================================

"Colour the dots by family" is easy for founders and a lie by generation 3,
because everyone then descends from several founders at once. So instead of a
surname we track, for each NPC, the *fraction* of its genome expected to come
from each founding lineage:

    founder            ancestry = {self: 1.0}
    child of A x B     ancestry = 0.5 * A.ancestry + 0.5 * B.ancestry

This is the pedigree expectation of genetic ancestry (each parent contributes
half its own ancestry). The colour shown is:

    hue        = the DOMINANT founder lineage (argmax fraction)
    saturation = purity (that max fraction): a pure-blooded founder descendant
                 is vivid; a fully-admixed individual is washed-out grey.

That way you can watch bloodlines stay vivid while isolated, then desaturate
as the population interbreeds -- the visual signature of gene flow.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np


# A palette of visually distinct founder hues (HSV hue angles, 0..1).
# Chosen around the wheel so adjacent lineages read as different colours.
_FOUNDER_HUES = [
    0.00,   # red
    0.58,   # azure
    0.33,   # green
    0.09,   # orange
    0.78,   # violet
    0.16,   # yellow-gold
    0.50,   # cyan
    0.88,   # magenta
    0.42,   # teal-green
    0.68,   # indigo
]


@dataclass
class Lineage:
    """One founding bloodline: a founder NPC and the colour assigned to it."""
    founder_name: str
    hue: float
    index: int


class LineageRegistry:
    """Assigns a stable hue to each founder and computes admixture colours."""

    def __init__(self) -> None:
        self._lineages: Dict[str, Lineage] = {}

    def register_founder(self, name: str) -> Lineage:
        if name not in self._lineages:
            idx = len(self._lineages)
            hue = _FOUNDER_HUES[idx % len(_FOUNDER_HUES)]
            # after one full turn of the wheel, jitter so new founders differ
            hue = (hue + 0.5 * (idx // len(_FOUNDER_HUES)) / len(_FOUNDER_HUES)) % 1.0
            self._lineages[name] = Lineage(name, hue, idx)
        return self._lineages[name]

    @property
    def founders(self) -> List[str]:
        return list(self._lineages)

    def hue_of(self, founder_name: str) -> float:
        return self._lineages[founder_name].hue

    # -- ancestry algebra ------------------------------------------------

    @staticmethod
    def founder_ancestry(name: str) -> Dict[str, float]:
        return {name: 1.0}

    @staticmethod
    def child_ancestry(mother: Dict[str, float],
                       father: Dict[str, float]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for anc, frac in mother.items():
            out[anc] = out.get(anc, 0.0) + 0.5 * frac
        for anc, frac in father.items():
            out[anc] = out.get(anc, 0.0) + 0.5 * frac
        # prune negligible contributions so the dict cannot grow unboundedly
        return {a: f for a, f in out.items() if f >= 1e-3}

    # -- colour ----------------------------------------------------------

    def dominant(self, ancestry: Dict[str, float]) -> Tuple[str, float]:
        """(founder_name, fraction) of the largest ancestry share."""
        if not ancestry:
            return ("", 0.0)
        name = max(ancestry, key=ancestry.get)
        return name, ancestry[name]

    def color_hex(self, ancestry: Dict[str, float], alive: bool = True) -> str:
        """
        A hex colour for an individual given its founder-ancestry mix.

        Pure descendant -> vivid founder hue. Fully admixed -> desaturated
        grey. Dead individuals are dimmed (lower value) for the tree/history.
        """
        name, purity = self.dominant(ancestry)
        if not name:
            hue, sat = 0.0, 0.0
        else:
            hue = self.hue_of(name)
            # Keep the dominant lineage's colour clearly readable even once
            # everyone is admixed: a high saturation floor so the hue always
            # reads, with purity modulating the top end (pure founders vivid,
            # heavily-mixed individuals a touch softer but still coloured).
            sat = float(np.clip(0.55 + 0.45 * purity, 0.55, 1.0))
        val = 0.95 if alive else 0.5
        r, g, b = colorsys.hsv_to_rgb(hue, float(sat), val)
        return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"

    def legend(self) -> List[Tuple[str, str]]:
        """(founder_name, hex) pairs for a colour legend."""
        out = []
        for name, lin in self._lineages.items():
            r, g, b = colorsys.hsv_to_rgb(lin.hue, 0.85, 0.92)
            out.append((name, f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"))
        return out
