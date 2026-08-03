"""
The chronicle: turning numbers into a readable history.
=======================================================

A dot-cloud drifting and a heterozygosity line sagging are only legible to
someone who already knows what to look for. The chronicle watches the metrics
stream and narrates the *notable* moments in plain language, so an examiner can
read the population's biography instead of decoding six charts:

    year 42 · Bora overtakes Elira as the largest bloodline
    year 51 · heterozygosity fell below 0.35 — diversity bleeding out
    year 63 · demes are differentiating (F_ST 0.11)

It also emits a **decade summary** every ten years (a short paragraph on what
changed and the mechanism behind it) and owns the **glossary** the dashboard
shows on hover, each entry with its citation — serving the thesis-grade
standard directly.

Everything here is derived from state already recorded; the chronicle adds no
biology, only interpretation. It keeps a little previous-state memory so it can
report *changes* (an overtake, a threshold crossing) rather than levels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ----------------------------------------------------------------------
# Severity tags -> used by the dashboard to colour a chronicle line / alert
# ----------------------------------------------------------------------
INFO, GOOD, WARN, CRIT = "info", "good", "warn", "crit"


@dataclass
class Event:
    tick: int
    text: str
    level: str = INFO


@dataclass
class Chronicle:
    events: List[Event] = field(default_factory=list)
    summaries: List[Event] = field(default_factory=list)     # decade paragraphs
    # remembered state for change detection
    _prev_dom: Optional[str] = None
    _prev_het_band: Optional[int] = None
    _prev_fst_band: Optional[int] = None
    _prev_gen: int = 0
    _prev_living_lineages: Optional[set] = None
    _decade_anchor: Optional[Dict[str, float]] = None

    # -- helpers ---------------------------------------------------------

    def _add(self, tick: int, text: str, level: str = INFO) -> None:
        self.events.append(Event(tick, text, level))

    @staticmethod
    def _het_band(h: float) -> int:
        # coarse bands so we only fire on a real crossing, not jitter
        for i, edge in enumerate((0.30, 0.33, 0.36, 0.39)):
            if h < edge:
                return i
        return 4

    @staticmethod
    def _fst_band(f: float) -> int:
        for i, edge in enumerate((0.02, 0.05, 0.10, 0.20)):
            if f < edge:
                return i
        return 4

    # -- the per-tick observer ------------------------------------------

    def observe(self, world) -> None:
        """Inspect the world after a step() and append any notable events."""
        if not world.history:
            return
        r = world.history[-1]
        tick = int(r["tick"])
        n = int(r["n_alive"])
        prev_n = int(world.history[-2]["n_alive"]) if len(world.history) > 1 else n

        # population shocks
        if prev_n > 0:
            change = (n - prev_n) / prev_n
            if change <= -0.20:
                self._add(tick, f"population crashed {prev_n}→{n} "
                                f"({change:+.0%}) in a single year", CRIT)
            elif change >= 0.25:
                self._add(tick, f"population boomed {prev_n}→{n} "
                                f"({change:+.0%})", GOOD)
        if n == 0 and prev_n > 0:
            self._add(tick, "the population has gone extinct", CRIT)
        elif 0 < n <= 10 and prev_n > 10:
            self._add(tick, f"only {n} left — the line teeters on extinction", CRIT)

        # generations
        gen = int(r.get("max_generation", 0))
        if gen > self._prev_gen:
            self._add(tick, f"generation {gen} is born", INFO)
            self._prev_gen = gen

        # dominant bloodline overtaking
        dom = world.dominant_lineage_name()
        if dom and self._prev_dom and dom != self._prev_dom:
            self._add(tick, f"{dom} overtakes {self._prev_dom} "
                            f"as the largest bloodline", INFO)
        if dom:
            self._prev_dom = dom

        # lineage extinction: a lineage that had living members last year and
        # has none now. Comparing to the immediately-previous living set fires
        # each extinction exactly once.
        living_lineages = world.living_lineage_set()
        if self._prev_living_lineages is not None:
            for name in sorted(self._prev_living_lineages - living_lineages):
                self._add(tick, f"the {name} bloodline has died out", WARN)
        self._prev_living_lineages = living_lineages

        # diversity thresholds
        het = float(r.get("heterozygosity", 0.0))
        band = self._het_band(het)
        if self._prev_het_band is not None and band < self._prev_het_band:
            self._add(tick, f"heterozygosity fell below "
                            f"{(0.30,0.33,0.36,0.39)[band]:.2f} "
                            f"(H={het:.3f}) — diversity bleeding out", WARN)
        self._prev_het_band = band

        # population structure (F_ST)
        fst = float(r.get("fst", 0.0))
        fband = self._fst_band(fst)
        if self._prev_fst_band is not None and fband > self._prev_fst_band and fst > 0:
            msg = {2: "demes are differentiating",
                   3: "demes are strongly structured",
                   4: "demes are nearly isolated"}.get(fband)
            if msg:
                self._add(tick, f"{msg} (F_ST={fst:.2f})", INFO)
        self._prev_fst_band = fband

        # decade summary
        if tick > 0 and tick % 10 == 0:
            self._decade_summary(world, r, tick)

    # -- the decade paragraph -------------------------------------------

    def _decade_summary(self, world, r: Dict[str, float], tick: int) -> None:
        anchor = self._decade_anchor
        self._decade_anchor = dict(r)
        n = int(r["n_alive"])
        het = float(r.get("heterozygosity", 0.0))
        fst = float(r.get("fst", 0.0))
        dom = world.dominant_lineage_name() or "no"
        gen = int(r.get("max_generation", 0))

        parts = [f"By year {tick}, {n} people live across "
                 f"{max(1, world.params.n_demes)} "
                 f"deme{'s' if world.params.n_demes > 1 else ''} "
                 f"(generation {gen})."]

        if anchor:
            dn = n - int(anchor["n_alive"])
            dh = het - float(anchor.get("heterozygosity", het))
            trend = ("grew" if dn > 0 else "shrank" if dn < 0 else "held steady")
            parts.append(f"The population {trend} by {abs(dn)} over the decade.")
            if dh < -0.004:
                parts.append(f"Genetic diversity eroded (H {dh:+.3f}) as the "
                             f"population inbred toward its commonest founders.")
            elif dh > 0.004:
                parts.append(f"Diversity rose (H {dh:+.3f}), likely from gene "
                             f"flow or fresh mutation.")
            else:
                parts.append(f"Diversity was roughly stable (H {het:.3f}).")

        parts.append(f"{dom} is the dominant bloodline.")
        if world.params.n_demes > 1:
            struct = ("well mixed" if fst < 0.02 else
                      "mildly structured" if fst < 0.05 else
                      "clearly differentiated" if fst < 0.15 else
                      "sharply isolated")
            parts.append(f"The demes are {struct} (F_ST={fst:.3f}).")
        if world.params.selection_pressure > 0.5:
            parts.append("Strong selection is culling the frail.")

        self.summaries.append(Event(tick, " ".join(parts), INFO))

    # -- external hook for shocks ---------------------------------------

    def note_shock(self, tick: int, text: str) -> None:
        self._add(tick, text, CRIT)

    # -- views for the dashboard ----------------------------------------

    def recent(self, k: int = 14) -> List[Event]:
        return list(reversed(self.events[-k:]))

    def latest_summary(self) -> Optional[Event]:
        return self.summaries[-1] if self.summaries else None


# ----------------------------------------------------------------------
# Glossary: what each metric means, with a citation. Shown on hover.
# ----------------------------------------------------------------------

GLOSSARY: Dict[str, Dict[str, str]] = {
    "heterozygosity": {
        "title": "Heterozygosity (H)",
        "text": "Fraction of loci at which an individual carries two different "
                "alleles, averaged over the population. Falls under inbreeding "
                "and drift — the empirical counterpart of Wright's F.",
        "cite": "Wright 1922; Hardy 1908 / Weinberg 1908",
    },
    "fst": {
        "title": "F_ST (population differentiation)",
        "text": "How much of the total genetic variance sits BETWEEN demes "
                "rather than within them. 0 = one homogeneous pool; higher = "
                "isolated, divergent communities. At migration–drift balance "
                "F_ST ≈ 1/(4·N_e·m+1).",
        "cite": "Wright 1931; Weir & Cockerham 1984",
    },
    "mean_relatedness": {
        "title": "Mean couple relatedness",
        "text": "Average realized genomic relatedness (GCTA-style) between "
                "mated partners. Rising values warn of inbreeding as a small "
                "closed population runs out of unrelated mates.",
        "cite": "Yang et al. 2010 (GCTA); Wright 1922",
    },
    "epi_accel": {
        "title": "Epigenetic age acceleration",
        "text": "Years by which the epigenetic (methylation) clock runs ahead "
                "of chronological age, driven by stress, smoking and "
                "inflammation. Predicts morbidity and mortality.",
        "cite": "Horvath 2013; Levine et al. 2018",
    },
    "inflammation": {
        "title": "Inflammation state",
        "text": "Mean standardized inflammatory tone = genetic predisposition + "
                "acquired load from chronic stress and illness (sickness "
                "behaviour, allostatic load).",
        "cite": "McEwen & Stellar 1993; Dantzer et al. 2008",
    },
    "n_couples": {
        "title": "Couples",
        "text": "Number of standing life-partnerships, formed by Gale–Shapley "
                "deferred acceptance so the matching has zero blocking pairs.",
        "cite": "Gale & Shapley 1962",
    },
    "reproductive_skew": {
        "title": "Reproductive skew (Gini)",
        "text": "Inequality in completed family size across the population (0 = "
                "everyone has equal offspring, 1 = a few monopolize "
                "reproduction). High skew shrinks the effective population size.",
        "cite": "Gini 1912; Crow 1958 (opportunity for selection)",
    },
}
