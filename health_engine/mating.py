"""
Life-partner selection.
=======================

The extNPC framework states plainly that "the health engine is used for
life partner choices" (Sec. 3.6). This module implements that.

STATUS: Stage 3 is now done. #30 (Gale-Shapley deferred acceptance) lives in
`simulation/demography.stable_matching`; #31 (full-pedigree Malecot kinship
and inbreeding depression) lives in `health_engine/inbreeding.py`. The greedy
matcher below is retained deliberately as the comparison baseline -- see
`count_blocking_pairs` for what it is a baseline *for*.

What is here now
----------------
* Homophily-based compatibility in personality space, as in the v0.2
  prototype and mirroring the node-similarity concept extNPComm already
  uses for social-edge generation. Assortative mating on personality is
  real and well replicated, though weakly (spousal correlations ~0.1-0.2
  for Big Five, far below the ~0.4 seen for education and height).

* An inbreeding guard that now uses REALISED GENOMIC RELATEDNESS rather
  than a name check. v0.2 compared parent tuples, so it blocked full sibs
  and parent/child and nothing else -- first cousins mated freely. We
  compute the GCTA relatedness estimator directly from the two genotypes
  (Yang et al. 2010):

      A_ab = mean_j [ (g_aj - 2p_j)(g_bj - 2p_j) / (2 p_j q_j) ]

  This is strictly better than the pedigree coefficient it approximates,
  because it measures the genome the individuals *actually* got rather
  than the expectation over meioses. Full sibs average 0.5 but scatter
  around it; the pedigree says 0.5 for all of them.

Where the rest of it went
-------------------------
* #30 Gale-Shapley deferred acceptance is in
  `simulation/demography.stable_matching`. `best_mate` below is greedy and
  one-sided, so it leaves blocking pairs -- two NPCs who each prefer the
  other over their assigned partner. Gale & Shapley 1962 proved a stable
  matching always exists; `count_blocking_pairs` measures how far the greedy
  one falls short of it.

* #31 Full-pedigree kinship (Malecot's coefficient walked over the whole
  ancestry graph) and the fitness cost of inbreeding are in
  `health_engine/inbreeding.py`. The genomic estimator here covers the
  *detection* half; `inbreeding.Pedigree` supplies the expectation this
  estimator realises, and the recessive-load layer supplies the depression.

  Note the division of labour, because it is deliberate. The guard below
  uses REALISED genomic relatedness, which is the better quantity for
  deciding whether a specific pair is too close. The pedigree coefficient is
  the better quantity for stating a population-level law, because Morton's
  ln S = ln S_0 - B F is written in terms of expected F. The engine keeps
  both and does not pretend they are interchangeable.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from .npc import NPC, genomic_relatedness
from .traits import OCEAN_TRAITS

# Wright's coefficient of relationship: full sibs and parent-offspring
# both sit at 0.5, first cousins at 0.125. Blocking above 0.125 excludes
# everything closer than (and including) first cousins.
DEFAULT_KINSHIP_THRESHOLD = 0.125


def relatedness(a: NPC, b: NPC) -> float:
    """Realised additive relatedness in [~0, 1]. See module docstring."""
    return genomic_relatedness(a, b)


def is_close_kin(a: NPC, b: NPC, threshold: float = DEFAULT_KINSHIP_THRESHOLD) -> bool:
    return relatedness(a, b) >= threshold


def mate_compatibility(a: NPC, b: NPC, diversity_weight: float = 0.15,
                       kinship_threshold: float = DEFAULT_KINSHIP_THRESHOLD
                       ) -> float:
    """
    Higher = more compatible. Returns -inf for close kin and same-sex
    pairs (reproduction here is obligate-sexual; social pairing is a
    different question this engine does not model).

      personality homophily  : negative RMS distance in OCEAN liability space
      genetic diversity bonus: 1 - relatedness, a proxy for avoiding
                               inbreeding depression

    The two pull in opposite directions only weakly, because personality
    liability and genome-wide relatedness are nearly orthogonal once
    close kin are excluded.
    """
    if a.sex == b.sex:
        return float("-inf")
    if is_close_kin(a, b, kinship_threshold):
        return float("-inf")

    za = np.array([a.liability(t) for t in OCEAN_TRAITS])
    zb = np.array([b.liability(t) for t in OCEAN_TRAITS])
    rms = float(np.sqrt(np.mean((za - zb) ** 2))) / math.sqrt(2.0)
    homophily = max(0.0, 1.0 - rms)

    diversity = 1.0 - max(0.0, relatedness(a, b))

    return (1.0 - diversity_weight) * homophily + diversity_weight * diversity


def best_mate(npc: NPC, candidates: List[NPC]) -> Optional[NPC]:
    """
    Greedy, one-sided. Kept for continuity with v0.2 and for comparison
    against the Gale-Shapley implementation that replaces it in Stage 3.
    """
    scored = [(mate_compatibility(npc, c), c)
              for c in candidates if c.name != npc.name]
    scored = [(s, c) for s, c in scored if s != float("-inf")]
    if not scored:
        return None
    return max(scored, key=lambda sc: sc[0])[1]


def count_blocking_pairs(matching: Dict[str, str], population: List[NPC]) -> int:
    """
    Diagnostic for why #30 matters. A blocking pair is two NPCs who each
    prefer the other over their current partner; a matching with any
    blocking pair is unstable. Greedy matching routinely produces them.
    Gale-Shapley produces zero, by construction.
    """
    by_name = {n.name: n for n in population}
    blocking = 0
    names = list(matching)
    for i, x in enumerate(names):
        for y in names[i + 1:]:
            if matching.get(x) == y:
                continue
            nx, ny = by_name[x], by_name[y]
            sxy = mate_compatibility(nx, ny)
            if sxy == float("-inf"):
                continue
            sx = mate_compatibility(nx, by_name[matching[x]]) if matching.get(x) else -math.inf
            sy = mate_compatibility(ny, by_name[matching[y]]) if matching.get(y) else -math.inf
            if sxy > sx and sxy > sy:
                blocking += 1
    return blocking
