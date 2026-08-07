"""
Synthetic vs empirical catalogue: what grounding a model in real allele
frequencies actually costs.
======================================================================

`EXTNPC_CATALOGUE=empirical` (loci.py) replaces 21 core genes' hand-set
allele frequencies with measured 1000 Genomes phase 3 EUR values. This
module runs the engine under BOTH catalogues and tabulates what moves,
which is the comparison the thesis wants: not "the model reproduces the
data", but **what breaks when you make a model face real frequencies,
and why**.

Why a subprocess, not an import
-------------------------------
The catalogue is read once at import because the entire trait
architecture is *solved* against it at import time. Two catalogues
therefore cannot coexist in one interpreter, so each arm is measured in
its own process and the results are compared here. That is also why this
module is deliberately NOT part of `validation.full_report`: it spawns
processes, and it must not consume the harness's shared generator or it
would shift every committed figure.

The result this is built to show
--------------------------------
V_A = sum_j a_j^2 * 2 p_j q_j. Effect size and variance contribution are
different things, and the difference is `2pq`: **a locus with an enormous
effect contributes NOTHING to variance if it is fixed**, because there is
no variation left for it to explain. That is not a modelling artefact, it
is the definition of variance, and it is the single most common
misreading of "gene for X" claims.

`SLC24A5` is the worked example, and it is the textbook case in the
literature too: it carries `skin_tone`'s largest weight (-1.80) and sits
at **q = 0.997 in Europeans** — one of the strongest signals of recent
positive selection in the human genome (Lamason et al. 2005). Under the
synthetic catalogue it is a polymorphic major-effect locus at 0.35; under
real EUR frequencies it is effectively fixed, `2pq` collapses from 0.455
to 0.006, and the trait's calibration overshoots compensating for the
variance it lost.

The general claim this measures
-------------------------------
Traits whose additive variance is CONCENTRATED in a few loci are fragile
to allele-frequency misspecification; traits whose variance is SPREAD
over many loci are robust to it. `height_cm` and `neuroticism` are
unmoved because they are omnigenic in this catalogue (Boyle, Li &
Pritchard 2017); `skin_tone` and `eye_color` move because they are not.
`concentration` below is the Herfindahl index of per-locus variance
shares, which is what turns that statement into a number.

Caveats that must travel with any table this produces
-----------------------------------------------------
* 21 of 53 core genes are grounded; the other 32 and all 450 peripheral
  loci keep synthetic values, so this is a PARTIAL swap and the measured
  divergence is a lower bound on a fully grounded one.
* EUR only. This is synthetic-vs-European, not a cross-ancestry
  comparison. Real cross-ancestry work is where the portability
  literature lives (Martin et al. 2019).
* The empirical arm is EXPERIMENTAL and fails 6 tests (see loci.py's
  KNOWN FAILURES). The failures are the finding; do not present the
  empirical arm as a working alternative model.

References
----------
Lamason et al. 2005 (*Science* 310:1782) -- SLC24A5, golden, and the
    European light-skin sweep.
Boyle, Li & Pritchard 2017 (*Cell* 169:1177) -- the omnigenic model.
Manolio et al. 2009 (*Nature* 461:747) -- missing heritability; predicted
    versus observed variance is the informative quantity.
Martin et al. 2019 (*Nat. Genet.* 51:584) -- polygenic scores transfer
    poorly across ancestries, for exactly the frequency reasons here.
Falconer & Mackay 1996 -- V_A = sum 2pq a^2.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np


# Traits worth tabulating: the two calibrated against measured depression,
# the pigmentation traits whose major loci are the ones that moved, and a
# behavioural trait as the omnigenic control.
DEFAULT_TRAITS: List[str] = [
    "height_cm", "skin_tone", "eye_color", "hair_pigment",
    "hearing_ability", "neuroticism", "lung_capacity", "bmi",
]


# Executed inside each arm's own interpreter. Printed as one JSON blob on
# stdout so the parent can parse it without importing the other mode.
_PROBE = r'''
import json, warnings
warnings.filterwarnings("ignore")
import numpy as np
from health_engine.loci import CATALOGUE_MODE, LOCI, LOCUS_BY_SYMBOL
from health_engine.traits import ARCHITECTURE

traits = json.loads(%r)
out = {"mode": CATALOGUE_MODE, "traits": {}, "loci": {}}

for t in traits:
    arch = ARCHITECTURE[t]
    twopq = 2.0 * arch.p * (1.0 - arch.p)
    contrib = (arch.a ** 2) * twopq          # per-locus additive variance
    v_a = float(contrib.sum())
    v_d = float(np.sum((twopq * arch.d) ** 2))
    total = contrib.sum()
    shares = contrib / total if total > 0 else contrib
    # Herfindahl concentration: 1/m if variance is spread evenly over m
    # loci, ~1 if one locus carries everything.
    herf = float(np.sum(shares ** 2))
    top = int(np.argmax(contrib))
    out["traits"][t] = {
        "declared_h2": float(arch.spec.h2),
        "v_a": v_a,
        "v_d": v_d,
        "n_loci": int(arch.a.size),
        "concentration": herf,
        "effective_loci": float(1.0 / herf) if herf > 0 else 0.0,
        "top_locus": LOCI[int(arch.idx[top])].symbol,
        "top_share": float(shares[top]),
    }

for L in LOCI:
    if L.is_core:
        out["loci"][L.symbol] = {
            "alt_freq": float(L.alt_freq),
            "twopq": float(2.0 * L.alt_freq * (1.0 - L.alt_freq)),
            "traits": sorted(L.weights),
        }

print("@@JSON@@" + json.dumps(out))
'''


def _probe(mode: str, traits: List[str]) -> dict:
    """Run the probe under `mode` in a fresh interpreter and parse it."""
    env = dict(os.environ, EXTNPC_CATALOGUE=mode)
    proc = subprocess.run([sys.executable, "-c", _PROBE % json.dumps(traits)],
                          env=env, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"{mode} arm failed:\n{proc.stderr}")
    for line in proc.stdout.splitlines():
        if line.startswith("@@JSON@@"):
            return json.loads(line[len("@@JSON@@"):])
    raise RuntimeError(f"{mode} arm produced no result:\n{proc.stdout}")


@dataclass
class CatalogueComparison:
    """Both arms' measurements, plus the deltas the thesis table needs."""
    traits: List[str]
    synthetic: dict
    empirical: dict

    def trait_rows(self) -> List[dict]:
        rows = []
        for t in self.traits:
            s = self.synthetic["traits"][t]
            e = self.empirical["traits"][t]
            rows.append({
                "trait": t,
                "declared_h2": s["declared_h2"],
                "v_a_syn": s["v_a"],
                "v_a_emp": e["v_a"],
                "v_a_ratio": e["v_a"] / s["v_a"] if s["v_a"] else float("nan"),
                "effective_loci_syn": s["effective_loci"],
                "top_locus": s["top_locus"],
                "top_share_syn": s["top_share"],
                "top_share_emp": e["top_share"],
            })
        return rows

    def locus_rows(self, min_delta: float = 0.02) -> List[dict]:
        """Core loci whose frequency actually moved between catalogues."""
        rows = []
        for sym, s in self.synthetic["loci"].items():
            e = self.empirical["loci"].get(sym)
            if e is None:
                continue
            if abs(e["alt_freq"] - s["alt_freq"]) < min_delta:
                continue
            rows.append({
                "locus": sym,
                "freq_syn": s["alt_freq"],
                "freq_emp": e["alt_freq"],
                "twopq_syn": s["twopq"],
                "twopq_emp": e["twopq"],
                "variance_ratio": (e["twopq"] / s["twopq"]
                                   if s["twopq"] > 0 else float("nan")),
                "traits": s["traits"],
            })
        rows.sort(key=lambda r: r["variance_ratio"])
        return rows

    def fragile_traits(self, tol: float = 0.10) -> List[str]:
        """Traits whose additive variance moved by more than `tol`."""
        return [r["trait"] for r in self.trait_rows()
                if abs(r["v_a_ratio"] - 1.0) > tol]


def compare(traits: Optional[List[str]] = None) -> CatalogueComparison:
    """Measure both catalogues. Costs two subprocess imports, no RNG."""
    traits = list(traits or DEFAULT_TRAITS)
    return CatalogueComparison(
        traits=traits,
        synthetic=_probe("synthetic", traits),
        empirical=_probe("empirical", traits),
    )


def report(cmp_: Optional[CatalogueComparison] = None) -> str:
    """A markdown table pair, ready to paste into the thesis."""
    c = cmp_ or compare()
    out: List[str] = []
    add = out.append

    add("## Synthetic vs empirical catalogue")
    add("")
    add("Additive variance is `V_A = sum_j a_j^2 * 2 p_j q_j`. Swapping in")
    add("measured 1000G phase 3 EUR frequencies for 21 core genes changes")
    add("`2pq`, and therefore changes how much variance each locus can")
    add("contribute -- without touching a single effect size.")
    add("")
    add("| trait | declared h2 | V_A synthetic | V_A empirical | ratio | "
        "effective loci | largest locus | its share (syn -> emp) |")
    add("|---|---|---|---|---|---|---|---|")
    for r in c.trait_rows():
        flag = " **" if abs(r["v_a_ratio"] - 1.0) > 0.10 else " "
        add(f"| {r['trait']}{flag}| {r['declared_h2']:.2f} | "
            f"{r['v_a_syn']:.4f} | {r['v_a_emp']:.4f} | "
            f"{r['v_a_ratio']:.3f} | {r['effective_loci_syn']:.1f} | "
            f"{r['top_locus']} | {r['top_share_syn']:.1%} -> "
            f"{r['top_share_emp']:.1%} |")
    add("")
    add("`**` marks a trait whose additive variance moved by more than 10%.")
    add("`effective loci` is 1/Herfindahl over per-locus variance shares:")
    add("how many loci the trait's variance is *effectively* spread across.")
    add("")
    add("### The loci that moved, ranked by variance lost")
    add("")
    add("| locus | freq syn | freq EUR | 2pq syn | 2pq EUR | variance x | traits |")
    add("|---|---|---|---|---|---|---|")
    for r in c.locus_rows():
        add(f"| {r['locus']} | {r['freq_syn']:.3f} | {r['freq_emp']:.4f} | "
            f"{r['twopq_syn']:.4f} | {r['twopq_emp']:.4f} | "
            f"{r['variance_ratio']:.3f} | {', '.join(r['traits'][:3])} |")
    add("")
    fragile = c.fragile_traits()
    add("### Reading")
    add("")
    add(f"Fragile under the swap: **{', '.join(fragile) or 'none'}**.")
    add("")
    add("The pattern is the result: traits whose variance is concentrated")
    add("in a few loci are fragile to allele-frequency misspecification;")
    add("omnigenic traits are robust to it. A locus with a large effect")
    add("contributes NOTHING to variance once it is fixed -- SLC24A5 keeps")
    add("its -1.80 weight in both arms and loses ~99% of its variance")
    add("contribution, because 2pq collapses. Effect size and variance")
    add("contribution are different quantities, and confusing them is the")
    add("standard misreading of 'a gene for X'.")
    add("")
    add("CAVEATS: 21 of 53 core genes are grounded and no peripheral locus")
    add("is, so this is a partial swap and a lower bound. EUR only, so this")
    add("is synthetic-vs-European and not a cross-ancestry comparison. The")
    add("empirical arm is EXPERIMENTAL and fails 6 tests (loci.py, KNOWN")
    add("FAILURES) -- those failures are the finding, not a working model.")
    return "\n".join(out)


if __name__ == "__main__":       # pragma: no cover
    print(report())
