"""
v0.2 operators, retained as measurable baselines.
=================================================

The original prototype kept single-point and multi-point crossover so its
novel operator could be compared against textbook GA. We keep all three
old operators here for the same reason -- and add the measurement that
was missing.

The claim being tested
----------------------
SBX (Simulated Binary Crossover) interpolates a child's *phenotype*
between its parents' phenotypes. Real inheritance transmits alleles; the
phenotype lands wherever the transmitted alleles and a fresh
environmental draw put it. `sbx_vs_meiosis_report()` measures three
consequences rather than asserting them:

  1. Midparent-offspring regression slope near 1.0, whatever heritability
     you claim to want. There is no environmental variance and no
     Mendelian sampling, so a child cannot regress toward the population
     mean. Real slope = h^2.

  2. Elevated full-sib correlation. Two SBX children of the same parents
     differ only by the beta draw. Real full sibs correlate at
     (1/2)h^2 + (1/4)(V_D/V_P) -- about 0.41 for height.

  3. Realised heritability near 1.0 under truncation selection. Because
     an SBX child inherits its parents' *phenotypes*, selecting extreme
     parents moves the offspring mean by nearly the full selection
     differential: R/S ~ 1. Under real meiosis only the additive half is
     transmitted, so R/S = h^2 (Lush 1937). This is the sharpest
     discriminator, and it is the roadmap's own Stage-0 benchmark.

What SBX gets RIGHT, and what we initially got wrong about it
-------------------------------------------------------------
It is tempting to add a fourth charge -- "blending inheritance halves the
trait variance every generation", Fleeming Jenkin's 1867 objection to
Darwin. That charge does NOT stick to SBX, and we checked. The beta
distribution in SBX is *specifically engineered* so that the spread of
the children matches the spread of the parents; a six-generation run of
SBX random mating holds the variance flat at 1.0. Naive averaging
(child = midparent) would indeed collapse; SBX does not.

The honest statement is narrower and more damning: SBX preserves variance
by construction rather than by mechanism. It has no genotype, so there is
nothing for dominance, epistasis, linkage, relatedness or a polygenic
score to be *about*, and heritability is not a parameter it can be given.
Mendelian transmission preserves variance as a side effect of being
particulate -- which is Fisher's 1918 reconciliation of Mendel with the
biometricians, and the reason this whole rewrite was necessary.

SBX is not bad. It is an excellent real-coded crossover operator for
optimisation, which is what Deb & Agrawal invented it for in 1995. It is
simply not inheritance.
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

import numpy as np

from .genome import cross, sample_founder_genome
from .genome import dosage_matrix
from .traits import (ARCHITECTURE, CONTINUOUS_TRAITS, EnvironmentalDeviates,
                     TRAIT_TABLE, TraitKind, population_liabilities)


# ----------------------------------------------------------------------
# The old operators
# ----------------------------------------------------------------------

def sbx_blend(x1: float, x2: float, low: float, high: float,
              rng: np.random.Generator, eta: float = 15.0) -> float:
    """Deb & Agrawal 1995. Distribution index eta: higher = children closer
    to parents. The v0.2 prototype used eta=15."""
    u = rng.random()
    if u <= 0.5:
        beta = (2.0 * u) ** (1.0 / (eta + 1.0))
    else:
        beta = (1.0 / (2.0 * (1.0 - u))) ** (1.0 / (eta + 1.0))
    c1 = 0.5 * ((1.0 + beta) * x1 + (1.0 - beta) * x2)
    c2 = 0.5 * ((1.0 - beta) * x1 + (1.0 + beta) * x2)
    c = c1 if rng.random() < 0.5 else c2
    return min(max(c, low), high)


def single_point_crossover(v1: List[float], v2: List[float],
                           rng: np.random.Generator) -> List[float]:
    cut = int(rng.integers(1, len(v1)))
    return list(v1[:cut]) + list(v2[cut:])


def multi_point_crossover(v1: List[float], v2: List[float],
                          rng: np.random.Generator, n_points: int = 3) -> List[float]:
    cuts = sorted(rng.choice(np.arange(1, len(v1)),
                             size=min(n_points, len(v1) - 1), replace=False))
    out, src, k = [], 0, 0
    pair = (v1, v2)
    for i in range(len(v1)):
        while k < len(cuts) and i == cuts[k]:
            src = 1 - src
            k += 1
        out.append(pair[src][i])
    return out


# ----------------------------------------------------------------------
# The measurement
# ----------------------------------------------------------------------

def _sbx_children_liabilities(zp1: np.ndarray, zp2: np.ndarray,
                              rng: np.random.Generator, eta: float = 15.0
                              ) -> np.ndarray:
    """Apply SBX on the standardised liability scale, so the result is
    directly comparable to `validation.parent_offspring_regression`."""
    return np.array([sbx_blend(a, b, -6.0, 6.0, rng, eta)
                     for a, b in zip(zp1, zp2)])


def sbx_vs_meiosis_report(trait: str, n_families: int,
                          rng: np.random.Generator, eta: float = 15.0) -> str:
    arch = ARCHITECTURE[trait]
    v_p = arch.v_a + arch.v_d + arch.v_i + arch.v_gxe + arch.v_e
    h2 = arch.v_a / v_p

    mums = [sample_founder_genome(rng) for _ in range(n_families)]
    dads = [sample_founder_genome(rng) for _ in range(n_families)]

    def liab(genomes):
        d = dosage_matrix(genomes)
        n = d.shape[0]
        return population_liabilities(arch, d, rng.normal(0, 1, n), rng.normal(0, 1, n))

    zm, zf = liab(mums), liab(dads)
    mp = 0.5 * (zm + zf)

    # --- real meiosis: two full sibs per family -------------------------
    kids1 = [cross(m, f, rng, mutation=False)[0] for m, f in zip(mums, dads)]
    kids2 = [cross(m, f, rng, mutation=False)[0] for m, f in zip(mums, dads)]
    zk1, zk2 = liab(kids1), liab(kids2)

    # --- SBX: two "sibs" per family -------------------------------------
    sk1 = _sbx_children_liabilities(zm, zf, rng, eta)
    sk2 = _sbx_children_liabilities(zm, zf, rng, eta)

    def slope(x, y):
        return float(np.polyfit(x, y, 1)[0])

    parent_var = float(np.var(np.concatenate([zm, zf])))

    # --- truncation selection under each regime --------------------------
    all_parents = np.concatenate([zm, zf])
    all_genomes = mums + dads
    base_mean = float(all_parents.mean())
    k = max(4, int(0.2 * all_parents.size))
    chosen = np.argsort(all_parents)[-k:]
    S = float(all_parents[chosen].mean() - base_mean)

    sel_kids = [cross(all_genomes[i], all_genomes[j], rng, mutation=False)[0]
                for i, j in rng.choice(chosen, size=(n_families, 2))]
    R_meiosis = float(liab(sel_kids).mean() - base_mean)

    sbx_sel = _sbx_children_liabilities(
        all_parents[rng.choice(chosen, n_families)],
        all_parents[rng.choice(chosen, n_families)], rng, eta)
    R_sbx = float(sbx_sel.mean() - base_mean)

    rows = [
        ("midparent-offspring slope", slope(mp, zk1), slope(mp, sk1),
         f"h2 + V_AA/2Vp = {h2 + arch.v_i / (2 * v_p):.3f}"),
        ("full-sib correlation", float(np.corrcoef(zk1, zk2)[0, 1]),
         float(np.corrcoef(sk1, sk2)[0, 1]),
         f"h2/2 + Vd/4Vp = {h2 / 2 + arch.v_d / (4 * v_p):.3f}"),
        ("realised h2 under selection (R/S)", R_meiosis / S, R_sbx / S,
         f"h2 = {h2:.3f}   (Lush 1937)"),
        ("offspring variance / parent variance",
         float(np.var(zk1)) / parent_var, float(np.var(sk1)) / parent_var,
         "1.000 -- BOTH conserve it"),
    ]

    out = [
        "=" * 78,
        f"SBX vs REAL MEIOSIS  --  trait: {trait}  (h2 = {h2:.2f})",
        "=" * 78,
        f"{'quantity':<38}{'meiosis':>10}{'SBX':>10}   theory",
    ]
    for label, a, b, theory in rows:
        out.append(f"{label:<38}{a:>10.3f}{b:>10.3f}   {theory}")
    out += [
        "",
        "Read the last row first: SBX does NOT collapse trait variance. Its beta",
        "distribution is engineered to conserve spread, so the textbook charge",
        "against blending inheritance misses it. The real failures are the first",
        "three rows. An SBX child cannot regress to the population mean, its",
        "siblings resemble it too much, and selecting extreme parents moves the",
        "next generation by nearly the whole selection differential instead of",
        "by h^2 of it. SBX has no genotype, so heritability cannot be a",
        "parameter of it. It is a fine optimiser and not a model of inheritance.",
    ]
    return "\n".join(out)
