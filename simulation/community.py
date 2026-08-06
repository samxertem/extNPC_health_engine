"""
Community structure: the island model of population subdivision.
================================================================

Session 4's world was *panmictic* -- one well-mixed mating pool -- and its own
report flagged the gap: "distance on the map is genetic, not spatial." This
module adds the missing spatial/social axis as **demes** (villages / bands /
communities) under Wright's classic **island model** (Wright 1931):

    * every individual belongs to a deme;
    * mating happens *within* a deme (Gale-Shapley is run per deme);
    * each year an individual emigrates to another deme with probability
      `migration_rate` (m), carrying its whole genome with it -- gene flow.

Two forces then fight, and you can watch the balance live:

    * **Drift + local founder effects** push demes APART (each small deme
      wanders to its own allele frequencies).
    * **Migration** pulls them back TOGETHER (gene flow homogenises).

The equilibrium of that tug-of-war is the headline, and it is a *closed-form
law we can validate against*, exactly like the HWE / Haldane / breeder's /
mtDNA-bottleneck checks the engine already ships:

        F_ST  ~=  1 / (4 N_e m + 1)          (Wright 1931)

where N_e is the per-deme effective size and m the migration rate. Low
migration -> high F_ST (differentiated villages); high migration -> F_ST -> 0
(one homogeneous population). Nothing in the code computes that formula; F_ST
falls out of measuring per-deme allele frequencies.

Intra-family structure (households / kin networks) rides on top of this: within
a deme, the pedigree edges the world already stores ARE the family network, and
`household_of` groups a couple with their dependent children.

References
----------
Wright 1931 (Genetics 16:97, "Evolution in Mendelian Populations");
Wright 1943 (isolation by distance); Weir & Cockerham 1984 (F_ST estimator);
Bhatia et al. 2013 (Genome Res. 23:1514, how to average F_ST over loci).
"""

from __future__ import annotations

import zlib
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

MAP_SIZE = 100.0        # world map is MAP_SIZE x MAP_SIZE arbitrary units


# Human-readable deme names, cycled + numbered like the person names.
DEME_NAMES = [
    "Aravel", "Bryn", "Corriel", "Dunmar", "Estwick",
    "Fenholt", "Galewood", "Highmere", "Ironvale", "Jorund",
]


def deme_label(deme_id: int) -> str:
    base = DEME_NAMES[deme_id % len(DEME_NAMES)]
    tag = deme_id // len(DEME_NAMES)
    return base if tag == 0 else f"{base}{tag+1}"


def assign_founder_demes(n_founders: int, n_demes: int,
                         rng: np.random.Generator) -> List[int]:
    """
    Spread founders across demes, balancing the sexes within each deme so
    pairing is possible everywhere. Founders alternate female/male by index
    (see World._seed_founders), so we deal them round-robin: consecutive
    founders (opposite sexes) land in the same deme before moving on.
    """
    n_demes = max(1, int(n_demes))
    demes = []
    for i in range(n_founders):
        demes.append((i // 2) % n_demes)   # pairs share a deme, then rotate
    return demes


# ----------------------------------------------------------------------
# F_ST -- the differentiation metric (the validation target)
# ----------------------------------------------------------------------

def fst(dosage_by_deme: Sequence[np.ndarray], min_deme: int = 2) -> float:
    """
    F_ST by the Weir & Cockerham 1984 estimator (their theta-hat).

    `dosage_by_deme[i]` is an (n_i, L) int array of alternate-allele dosages
    (0/1/2) for the living members of deme i.

    WHY NOT THE OBVIOUS FORMULA. The intuitive definition,

        F_ST = (H_T - H_S) / H_T                          (Nei's G_ST)

    is a statement about *populations*, and applying it to *samples* biases it
    upward: two samples drawn from one identical population differ by sampling
    alone, and that difference is read as differentiation. The bias is of order
    1/(2n) per deme, which is not small at the deme sizes this engine
    simulates. Measured on this codebase before the fix: four demes drawn from
    a single shared allele-frequency vector, so true F_ST = 0, returned
    **0.019 at n=20 per deme and 0.038 at n=10**. Session 8's melting-pot
    figure of ~0.025 was not meaningfully above that floor.

    Weir & Cockerham's estimator exists precisely to remove that term. It
    decomposes the total variance in allele frequency into among-deme (a),
    among-individual-within-deme (b) and within-individual (c) components,
    each corrected for finite sample size, and forms

        theta = a / (a + b + c)

    Per locus, with r demes of sizes n_i, frequencies p_i and observed
    heterozygote proportions h_i:

        n_bar = mean(n_i)
        n_c   = (r n_bar - sum(n_i^2)/(r n_bar)) / (r - 1)
        p_bar = sum(n_i p_i) / (r n_bar)
        s2    = sum(n_i (p_i - p_bar)^2) / ((r - 1) n_bar)
        h_bar = sum(n_i h_i) / (r n_bar)

    `h_i` is why the estimator needs GENOTYPES and not just frequencies: the
    within-individual component c cannot be recovered from allele frequencies
    alone. That is also why the old signature happened to be adequate for
    G_ST and is not adequate here.

    Combined across loci as a **ratio of sums**, sum(a) / sum(a+b+c), which is
    what Bhatia et al. 2013 recommend over averaging per-locus ratios --
    per-locus theta is wildly unstable at near-monomorphic loci.

    NOT CLIPPED AT ZERO, deliberately. An unbiased estimator of a quantity
    that is truly zero must be able to come out negative; clipping would
    reintroduce exactly the upward bias this function exists to remove. A
    small negative value means "no detectable differentiation", not an error.

    Returns 0.0 when fewer than `min_deme` demes have members.
    """
    n_i, p_i, h_i = [], [], []
    for d in dosage_by_deme:
        arr = np.asarray(d)
        if arr.size == 0:
            continue
        n_i.append(arr.shape[0])
        p_i.append(arr.mean(axis=0) / 2.0)             # (L,) alt freq
        h_i.append((arr == 1).mean(axis=0))            # (L,) heterozygote frac
    r = len(n_i)
    if r < min_deme:
        return 0.0

    n = np.asarray(n_i, dtype=float)[:, None]          # (r, 1)
    P = np.vstack(p_i)                                 # (r, L)
    H = np.vstack(h_i)                                 # (r, L)

    n_bar = float(n.mean())
    if n_bar <= 1.0:
        return 0.0
    n_c = (r * n_bar - float(np.sum(n ** 2)) / (r * n_bar)) / (r - 1.0)

    p_bar = (n * P).sum(axis=0) / (r * n_bar)          # (L,)
    s2 = (n * (P - p_bar) ** 2).sum(axis=0) / ((r - 1.0) * n_bar)
    h_bar = (n * H).sum(axis=0) / (r * n_bar)

    pq = p_bar * (1.0 - p_bar)
    common = pq - ((r - 1.0) / r) * s2

    a = (n_bar / n_c) * (s2 - (common - h_bar / 4.0) / (n_bar - 1.0))
    b = (n_bar / (n_bar - 1.0)) * (common
                                   - ((2.0 * n_bar - 1.0) / (4.0 * n_bar)) * h_bar)
    c = h_bar / 2.0

    num = float(np.sum(a))
    den = float(np.sum(a + b + c))
    if den == 0.0:
        return 0.0
    return float(num / den)


def fst_gst(dosage_by_deme: Sequence[np.ndarray], min_deme: int = 2) -> float:
    """
    Nei's G_ST from sample frequencies -- the estimator this module used
    until the session-11 fix, kept so the bias can be demonstrated rather
    than merely asserted.

        F_ST = (H_T - H_S) / H_T

    Correct as a statement about populations, upward-biased as a statistic
    computed on samples. `test_community` compares the two on an
    independent-sample null where the true value is zero.
    """
    freqs = []
    for d in dosage_by_deme:
        arr = np.asarray(d, dtype=float)
        if arr.size == 0:
            continue
        freqs.append(arr.mean(axis=0) / 2.0)
    if len(freqs) < min_deme:
        return 0.0

    P = np.vstack(freqs)
    p_bar = P.mean(axis=0)
    H_S = (2.0 * P * (1.0 - P)).mean(axis=0)
    H_T = 2.0 * p_bar * (1.0 - p_bar)
    den = float(np.sum(H_T))
    if den <= 0.0:
        return 0.0
    return float(np.clip(float(np.sum(H_T - H_S)) / den, 0.0, 1.0))


def expected_fst(effective_size: float, migration_rate: float) -> float:
    """
    Wright's island-model equilibrium F_ST = 1 / (4 N_e m + 1). A reference
    curve for the dashboard and the validation test, NOT used to drive the sim.
    """
    denom = 4.0 * max(effective_size, 1e-9) * max(migration_rate, 0.0) + 1.0
    return 1.0 / denom


# ----------------------------------------------------------------------
# Migration
# ----------------------------------------------------------------------

def choose_migration(deme_id: int, n_demes: int,
                     rng: np.random.Generator) -> int:
    """Pick a destination deme != current under the pure island model (any
    other deme equally likely). Kept for reference / tests."""
    if n_demes <= 1:
        return deme_id
    dest = int(rng.integers(0, n_demes - 1))
    if dest >= deme_id:
        dest += 1
    return dest


# ----------------------------------------------------------------------
# Spatial layout + isolation by distance (Wright 1943)
# ----------------------------------------------------------------------

def deme_layout(n_demes: int, seed: int) -> np.ndarray:
    """
    Place demes on the 2-D world map as settlement coordinates.

    Uses a golden-angle (sunflower) spread for an even, natural-looking scatter,
    with a little deterministic jitter. Crucially it draws from its OWN RNG
    seeded off `seed`, never the World's main generator, so adding a map does
    not perturb the calibrated genetic RNG stream — the default single-deme
    world stays bit-for-bit identical.
    """
    n = max(1, int(n_demes))
    rng = np.random.default_rng(np.uint64(seed) * np.uint64(2654435761) % (2**63))
    cx = cy = MAP_SIZE / 2.0
    golden = np.pi * (3.0 - np.sqrt(5.0))       # ~2.399963 rad
    pts = np.empty((n, 2))
    for i in range(n):
        # A lone settlement sits at the centre. The sunflower radius is
        # sqrt((i+0.5)/n), which is 0.707 -- not 0 -- at n=1, so without this
        # the single deme was placed off-centre at (78.3, 50); combined with
        # the n=1 territory radius of MAP_SIZE*0.34 = 34 that put its edge at
        # 112.3 on a map of 100, and ~13% of villagers rendered outside the
        # world square. Centred, the same radius spans 16..84 comfortably.
        r = 0.0 if n == 1 else 0.40 * MAP_SIZE * np.sqrt((i + 0.5) / n)
        th = i * golden
        jitter = rng.uniform(-0.03, 0.03, size=2) * MAP_SIZE if n > 1 else np.zeros(2)
        pts[i] = (cx + r * np.cos(th) + jitter[0],
                  cy + r * np.sin(th) + jitter[1])
    return pts


def territory_radius(centers: np.ndarray) -> float:
    """
    A settlement's territory radius = ~45% of the nearest-neighbour spacing,
    so territories are roomy but rarely overlap.

    The radius is additionally capped so that **every** territory fits inside
    the map. Spacing alone does not guarantee that: a settlement placed near
    an edge can be far from its neighbours and still overhang the boundary,
    which draws its villagers outside the world square. n=3 overhung by ~0.9
    units before this cap; the old n=1 case overhung by 12.3.
    """
    n = len(centers)
    # distance from the closest centre to the nearest map edge -- no territory
    # may be wider than this without leaving the map
    to_edge = float(min(centers.min(), MAP_SIZE - centers.max()))
    ceiling = min(MAP_SIZE * 0.34, max(to_edge, 1.0))
    if n <= 1:
        return float(ceiling)
    best = np.inf
    for i in range(n):
        d = np.hypot(*(centers - centers[i]).T)
        d[i] = np.inf
        best = min(best, float(d.min()))
    return float(np.clip(0.45 * best, min(6.0, ceiling), ceiling))


def choose_migration_weighted(deme_id: int, centers: np.ndarray,
                              rng: np.random.Generator) -> int:
    """
    Distance-weighted destination: a migrant is far likelier to move to a NEAR
    settlement than a distant one (probability ∝ 1/distance²). This turns the
    pure island model into **isolation by distance** (Wright 1943): neighbours
    exchange more genes, so F_ST grows with geographic separation rather than
    uniformly. Falls back to the current deme when there is nowhere to go.
    """
    n = len(centers)
    if n <= 1:
        return deme_id
    d2 = np.sum((centers - centers[deme_id]) ** 2, axis=1)
    d2[deme_id] = np.inf
    w = 1.0 / (d2 + 1e-6)
    w[deme_id] = 0.0
    s = w.sum()
    if s <= 0:
        return deme_id
    return int(rng.choice(n, p=w / s))


def person_map_offset(name: str, radius: float) -> Tuple[float, float]:
    """
    A stable in-territory offset for an individual, derived from a CRC of its
    name (NOT the RNG), so people scatter inside their settlement without
    consuming the genetic RNG stream and without jittering every tick.
    """
    h = zlib.crc32(name.encode("utf-8"))
    ang = (h & 0xFFFF) / 0xFFFF * 2.0 * np.pi
    rad = radius * 0.95 * np.sqrt(((h >> 16) & 0xFFFF) / 0xFFFF)
    return float(rad * np.cos(ang)), float(rad * np.sin(ang))
