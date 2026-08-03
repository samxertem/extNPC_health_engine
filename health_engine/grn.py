"""
Gene-regulatory network / omnigenic layer (roadmap #8).
=======================================================

What this closes
----------------
Until now the engine had *pleiotropy* -- one gene writing weights onto many
traits (`loci.py`) -- but every gene acted in ISOLATION. Gene A's activity
never touched gene B's. The omnigenic model (Boyle, Li & Pritchard 2017,
Cell 169:1177) says the opposite: regulatory networks are so interconnected
that peripheral genes reach "core" trait genes *in trans*, and a master
regulator drives a whole developmental *program*, not one trait.

This module adds that trans layer as a sparse gene->gene network sitting on
top of the existing genotype->phenotype map, and gives it a perturbation API
so you can knock a regulator up or down and watch a coherent syndrome fall
out across traits the regulator does not directly weight.

The load-bearing invariant
---------------------------
`traits.py` is calibrated so that at the default epigenome the per-locus
`expression` multiplier is 1.0 everywhere and session-1 genetics reproduce
BIT FOR BIT. The GRN must not break that. It does not, by construction:

    trans_multiplier(target) = clip( 1 + sum_h W[target,h] * (act[h] - 1) )

where `act[h]` is hub h's *cis activity* -- which at baseline is its own
expression multiplier, 1.0. So (act - 1) = 0, every trans factor is exactly
1.0, and the composed expression is unchanged. The network only speaks when
a hub is driven off baseline -- by an epigenetic hit (chronic stress
silencing NR3C1) or by an explicit `perturb(...)` intervention. See
`test_grn.py::test_baseline_is_bit_for_bit`.

Because the trans layer keys off *deviations from baseline*, not off raw
genotype, it adds nothing to the population-genetic variance decomposition
either: at a default epigenome the heritability calibration in `traits.py`
is untouched. The GRN is a perturbation-response and epigenetic-propagation
layer, not a fourth variance component.

Hub topology: coherent developmental programs
---------------------------------------------
Hubs are not arbitrary graph nodes -- they are the genuine transcription
factors / master regulators already in the catalogue, each driving a
biologically-related target module with a CONSISTENT sign (the project
owner's chosen coupling policy). A master TF turns a program up or down as a
unit; it does not nudge its targets in random directions.

  RUNX2    osteoblast master regulator -> skeletal / craniofacial / stature
  SOX9     chondrogenesis              -> cartilage-derived facial shape
  PAX3     neural crest                -> pigment (via MITF axis) + midface
  PPARG    adipogenesis master switch  -> adiposity / insulin / lipids
  CLOCK    circadian core TF           -> chronotype + circadian-metabolic
  GATA3    ectodermal TF               -> hair / appendage
  HLA_DRB1 immune regulator            -> inflammation / immune tone
  NR3C1    glucocorticoid receptor     -> INHIBITS inflammation (see below)

NR3C1 is the one deliberately *inhibitory* program, and that is the correct
biology, not an exception to coherence: the glucocorticoid receptor
suppresses inflammatory genes, so its edges onto IL6/CRP are negative. When
chronic stress hypomethylates and silences NR3C1 (act < 1), a negative edge
*raises the expression* of the inflammation targets -- the brake comes off,
in expression space -- and this travels the same epigenome->NETWORK path the
roadmap-#18 pathway uses, with no rule scripting the coupling.

The symmetric-amplifier caveat (inherited from the epigenome layer)
------------------------------------------------------------------
The expression multiplier -- epigenome and GRN alike -- is SYMMETRIC: it
scales whatever signed genotypic value an individual already carries at a
locus. So a coherent program is coherent in EXPRESSION space (all of a hub's
targets move the same way), but the population-MEAN direction of a trait
under a perturbation is set by the targets' allele-frequency-weighted mean
genotypic value, not by the edge sign. Risk alleles at alt-freq < 0.5 have a
negative mean genotypic value (most individuals carry the reference allele),
so amplifying them can move the population mean opposite to the naive
"more expression -> more trait" intuition. This is the same subtlety
`epigenome.py` documents for inflammation: the multiplier changes each
individual's phenotype and the population VARIANCE; the directional mean
offset of an acquired state lives in a separate load term, not here. A
perturbation's trait-mean response is coherent when its targets share
frequency structure (as RUNX2's skeletal module largely does).

CAVEATS (roadmap Section 5 -- load-bearing)
-------------------------------------------
* "Core vs peripheral" is a modelling convenience, not settled fact
  (Wray et al. 2018, Cell 173:1573). We keep the network deliberately
  SPARSE -- 8 hubs, tens of targets each -- exactly as the roadmap's
  runtime-budget note licenses.
* Edge weights are plausible relative couplings, not measured regulatory
  strengths. Only the sign structure (coherent programs) and the sparsity
  carry claimed meaning.
* This is a directed activity-propagation caricature. Real GRNs have
  feedback, cooperativity and combinatorial cis-regulation we do not model;
  propagation here is a single trans hop, not a dynamical system.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .loci import LOCI, LOCUS_BY_SYMBOL, N_LOCI

# Fixed reference network, like the locus catalogue: generated once from a
# seed so every run sees the same "species".
GRN_SEED = 20240610

# Clip on the trans multiplier. A knocked-out hub (act = 0, dev = -1) can at
# most zero a positively-coupled target; an over-expressed hub can lift it to
# 1.5x, matching the epigenome's own EXPRESSION_MAX so composed values stay
# bounded.
TRANS_MIN = 0.0
TRANS_MAX = 1.5

# Edge-weight magnitude ranges. Curated core->core edges are the backbone of
# a program and carry real weight; sampled peripheral targets are the diffuse
# skirt and are an order of magnitude weaker.
CORE_EDGE_LO, CORE_EDGE_HI = 0.12, 0.38
PERIPH_EDGE_LO, PERIPH_EDGE_HI = 0.015, 0.06
# How many peripheral targets each hub recruits, from loci carrying weight on
# the program's traits. Kept modest to honour the sparsity caveat.
PERIPH_TARGETS_PER_HUB = 24


@dataclass(frozen=True)
class Program:
    """One hub's coherent regulatory program."""
    hub: str                    # regulator gene symbol
    sign: float                 # +1 activating program, -1 repressive (NR3C1)
    traits: Tuple[str, ...]     # the developmental program this hub drives
    core_targets: Tuple[str, ...]   # hand-curated downstream core genes


# ----------------------------------------------------------------------
# The programs. Hub symbols and their downstream core targets are all real
# genes in loci.py; the trait lists name the program each hub coordinates.
# ----------------------------------------------------------------------
_PROGRAMS: List[Program] = [
    # RUNX2: osteoblast master regulator. Drives the skeletal/craniofacial
    # program -- its trans reach covers chin, cheekbone, nose shape and
    # stature that it does NOT weight directly (direct: nose_bridge_breadth,
    # brow_ridge, height_cm). This is the #8 benchmark hub.
    Program("RUNX2", +1.0,
            ("nose_bridge_breadth", "brow_ridge", "height_cm", "chin_protrusion",
             "cheekbone_prominence", "nose_pointiness", "nose_width",
             "nasion_position", "adiposity"),
            ("SUPT3H", "SOX9", "DCHS2", "GLI3", "PAX1", "PAX3", "PKDCC",
             "TBX15", "HMGA2", "GDF5", "ACAN", "ZBTB38", "IGF1")),

    # SOX9: chondrogenesis. Cartilage-derived facial shape + long-bone growth.
    Program("SOX9", +1.0,
            ("nose_pointiness", "chin_protrusion", "cheekbone_prominence",
             "nose_bridge_breadth", "height_cm"),
            ("DCHS2", "ACAN", "GDF5", "RUNX2", "PKDCC")),

    # PAX3: neural crest. Feeds the melanocyte (MITF) axis and the midface.
    Program("PAX3", +1.0,
            ("skin_tone", "hair_pigment", "eye_color", "nasion_position",
             "nose_bridge_breadth"),
            ("MC1R", "ASIP", "TYR", "OCA2", "SOX9")),

    # PPARG: adipogenesis master switch. Adiposity, insulin, lipids together.
    Program("PPARG", +1.0,
            ("adiposity", "bmi", "insulin_sensitivity", "lipid_profile",
             "inflammation_tone", "aerobic_capacity"),
            ("FTO", "MC4R", "TCF7L2", "FADS1", "APOE", "LDLR", "PCSK9",
             "IGF1", "TBX15")),

    # CLOCK: circadian core TF. Chronotype + circadian control of metabolism.
    Program("CLOCK", +1.0,
            ("chronotype", "insulin_sensitivity", "lipid_profile",
             "inflammation_tone"),
            ("PER3", "ARNTL", "PPARG", "FADS1")),

    # GATA3: ectodermal TF. Hair/appendage program.
    Program("GATA3", +1.0,
            ("hair_curl", "hair_thickness", "immune_reactivity"),
            ("WNT10A", "PRSS53", "FRAS1", "EDAR")),

    # HLA_DRB1: immune regulatory hub. Inflammation / immune tone.
    Program("HLA_DRB1", +1.0,
            ("inflammation_tone", "immune_reactivity", "immune_resilience",
             "chronic_illness_predisposition"),
            ("IL6", "CRP", "FADS1", "AHRR")),

    # NR3C1: glucocorticoid receptor. INHIBITORY program -- GR suppresses
    # inflammation, so low NR3C1 activity (e.g. stress-silenced) DISINHIBITS
    # the inflammation targets. sign = -1 makes that the emergent behaviour.
    Program("NR3C1", -1.0,
            ("inflammation_tone", "immune_reactivity", "insulin_sensitivity",
             "chronic_illness_predisposition"),
            ("IL6", "CRP", "HLA_DRB1", "FADS1")),
]


@dataclass
class RegulatoryNetwork:
    """
    A fixed sparse gene->gene activity network.

    Stored as a flat edge list (three parallel arrays) plus a hub index, so
    the trans multiplier is one `np.add.at` scatter -- cheap enough to run on
    every `refresh_expression`.
    """
    programs: List[Program]
    hub_idx: np.ndarray             # (H,) locus index of each hub
    hub_pos: Dict[int, int]         # locus index -> position in hub_idx
    edge_target: np.ndarray         # (E,) target locus index
    edge_hubpos: np.ndarray         # (E,) hub position (into hub_idx) of source
    edge_weight: np.ndarray         # (E,) signed trans weight

    # --- introspection ------------------------------------------------
    @property
    def n_hubs(self) -> int:
        return int(self.hub_idx.size)

    @property
    def n_edges(self) -> int:
        return int(self.edge_target.size)

    def hub_symbols(self) -> List[str]:
        return [p.hub for p in self.programs]

    def targets_of(self, hub_symbol: str) -> List[Tuple[str, float]]:
        """(target_symbol, weight) edges leaving a hub, strongest first."""
        h = LOCUS_BY_SYMBOL[hub_symbol].index
        hp = self.hub_pos[h]
        mask = self.edge_hubpos == hp
        pairs = [(LOCI[int(t)].symbol, float(w))
                 for t, w in zip(self.edge_target[mask], self.edge_weight[mask])]
        return sorted(pairs, key=lambda tw: -abs(tw[1]))

    # --- the core operation -------------------------------------------
    def trans_multiplier(self, cis_activity: np.ndarray) -> np.ndarray:
        """
        (L,) trans-regulatory multiplier given each locus's cis activity.

        `cis_activity` is normally the epigenome's expression vector (1.0 at
        baseline). Only the hub entries are read. At baseline every hub
        deviation is 0 and this returns all-ones exactly.
        """
        dev = cis_activity[self.hub_idx] - 1.0          # (H,)
        acc = np.zeros(N_LOCI)
        np.add.at(acc, self.edge_target, self.edge_weight * dev[self.edge_hubpos])
        return np.clip(1.0 + acc, TRANS_MIN, TRANS_MAX)

    def compose(self, cis_expression: np.ndarray,
                perturbation: Optional[Dict[str, float]] = None) -> np.ndarray:
        """
        Full expression = cis * trans, with optional hub perturbations.

        A perturbation `{symbol: factor}` clamps a gene's cis activity to
        `factor` (0 = knockout, 1 = wild type, >1 = over-expression). That
        clamp propagates two ways, both biologically right:
          * it replaces the hub's OWN expression, so the hub's direct trait
            weights scale too (a knockout loses its direct effect); and
          * it enters `trans_multiplier` as a hub deviation, so the hub's
            downstream program shifts.
        """
        cis = cis_expression
        if perturbation:
            cis = cis.copy()
            for sym, factor in perturbation.items():
                cis[LOCUS_BY_SYMBOL[sym].index] = factor
        return cis * self.trans_multiplier(cis)


def _build_network() -> RegulatoryNetwork:
    rng = np.random.default_rng(GRN_SEED)

    hub_symbols = [p.hub for p in _PROGRAMS]
    hub_idx = np.array([LOCUS_BY_SYMBOL[s].index for s in hub_symbols], dtype=np.int64)
    hub_pos = {int(ix): pos for pos, ix in enumerate(hub_idx)}
    hub_set = set(int(i) for i in hub_idx)

    # Precompute, per trait, the peripheral (non-core) loci carrying weight on
    # it, so a hub can recruit a diffuse skirt of same-program background loci.
    periph_by_trait: Dict[str, List[int]] = {}
    for L in LOCI:
        if L.is_core:
            continue
        for t in L.weights:
            periph_by_trait.setdefault(t, []).append(L.index)

    tgt: List[int] = []
    hubp: List[int] = []
    wgt: List[float] = []

    for pos, prog in enumerate(_PROGRAMS):
        h_index = int(hub_idx[pos])

        # --- curated core targets: the program backbone, strong edges -----
        for sym in prog.core_targets:
            j = LOCUS_BY_SYMBOL[sym].index
            if j == h_index:
                continue                       # no self-loops
            w = rng.uniform(CORE_EDGE_LO, CORE_EDGE_HI) * prog.sign
            tgt.append(j); hubp.append(pos); wgt.append(float(w))

        # --- diffuse peripheral skirt: many weak same-sign edges ----------
        pool: List[int] = []
        for t in prog.traits:
            pool.extend(periph_by_trait.get(t, ()))
        pool = list({j for j in pool if j not in hub_set})
        if pool:
            k = min(PERIPH_TARGETS_PER_HUB, len(pool))
            chosen = rng.choice(pool, size=k, replace=False)
            for j in chosen:
                w = rng.uniform(PERIPH_EDGE_LO, PERIPH_EDGE_HI) * prog.sign
                tgt.append(int(j)); hubp.append(pos); wgt.append(float(w))

    return RegulatoryNetwork(
        programs=_PROGRAMS,
        hub_idx=hub_idx,
        hub_pos=hub_pos,
        edge_target=np.array(tgt, dtype=np.int64),
        edge_hubpos=np.array(hubp, dtype=np.int64),
        edge_weight=np.array(wgt, dtype=np.float64),
    )


# The one shared reference network.
NETWORK: RegulatoryNetwork = _build_network()


# ----------------------------------------------------------------------
# Convenience for experiments / the #8 benchmark
# ----------------------------------------------------------------------

def network_summary() -> str:
    lines = [f"regulatory network: {NETWORK.n_hubs} hubs, {NETWORK.n_edges} edges"]
    for p in NETWORK.programs:
        edges = NETWORK.targets_of(p.hub)
        core = sum(1 for sym, _ in edges if LOCUS_BY_SYMBOL[sym].is_core)
        sign = "+" if p.sign > 0 else "-"
        lines.append(
            f"  {p.hub:<10} ({sign}) {len(edges):>3} targets "
            f"({core} core) -> program: {', '.join(p.traits[:4])}..."
        )
    return "\n".join(lines)
