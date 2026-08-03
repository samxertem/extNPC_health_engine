"""
Gene-regulatory network / omnigenic layer tests (roadmap #8).

The headline is `test_hub_knockout_shifts_unrelated_traits`, which is the
roadmap's own Stage-1 acceptance criterion for #8:

    "perturbing one core gene's activity measurably shifts >= 3 unrelated
     phenotypes through the network, not just through direct pleiotropy."

The other load-bearing test is `test_baseline_is_bit_for_bit`: introducing
the network must not perturb a single calibrated phenotype at the default
epigenome, or every heritability in traits.py silently moves.
"""

import numpy as np
import pytest

from health_engine import grn
from health_engine.grn import NETWORK, TRANS_MAX, TRANS_MIN
from health_engine.loci import LOCI, LOCUS_BY_SYMBOL, N_LOCI
from health_engine.npc import random_founder
from health_engine.traits import ARCHITECTURE

CONTINUOUS = [t for t, a in ARCHITECTURE.items()
              if a.spec.kind.value == "continuous"]


@pytest.fixture
def rng():
    return np.random.default_rng(20240612)


# ----------------------------------------------------- the baseline invariant

def test_baseline_is_bit_for_bit():
    """compose(ones, no perturbation) must be exactly ones -- not close,
    exactly -- so the pre-GRN engine is reproduced bit for bit."""
    o = np.ones(N_LOCI)
    comp = NETWORK.compose(o, None)
    assert np.array_equal(comp, o)


def test_default_npc_expression_unchanged(rng):
    """A founder with a default epigenome and no perturbation expresses at
    1.0 everywhere: the network is silent until something drives a hub off
    baseline."""
    npc = random_founder("f0", rng)
    npc.refresh_expression()
    assert np.allclose(npc.expression, 1.0)


# ----------------------------------------------------------- network shape

def test_network_is_sparse():
    """Wray et al. 2018: keep 'core vs peripheral' a sparse engineering
    device. A handful of hubs, tens of targets each -- not a dense graph."""
    assert NETWORK.n_hubs == len(grn._PROGRAMS)
    assert NETWORK.n_hubs <= 12
    # sparse: each hub reaches well under 10% of the genome, and the whole
    # graph is far from the fully-connected hub x locus limit.
    max_targets = max(len(NETWORK.targets_of(p.hub)) for p in grn._PROGRAMS)
    assert max_targets < 0.10 * N_LOCI
    assert NETWORK.n_edges < 0.10 * NETWORK.n_hubs * N_LOCI


def test_no_self_loops():
    for tpos, hpos, w in zip(NETWORK.edge_target, NETWORK.edge_hubpos,
                             NETWORK.edge_weight):
        assert int(tpos) != int(NETWORK.hub_idx[int(hpos)])


def test_hubs_are_real_transcription_factors():
    """Hubs must be genuine catalogue genes, not invented nodes."""
    for p in grn._PROGRAMS:
        assert p.hub in LOCUS_BY_SYMBOL
        assert LOCUS_BY_SYMBOL[p.hub].is_core


def test_edges_are_sign_coherent_per_program():
    """The owner's chosen coupling policy: every edge a hub emits shares the
    program's sign, so a perturbation reads as a coherent syndrome rather
    than directionless noise."""
    for p in grn._PROGRAMS:
        for _, w in NETWORK.targets_of(p.hub):
            assert np.sign(w) == np.sign(p.sign)


# --------------------------------------------------------- the #8 benchmark

def test_hub_knockout_shifts_unrelated_traits(rng):
    """
    Roadmap #8 acceptance: knocking out RUNX2 (a hub) measurably and
    coherently shifts >= 3 traits it does NOT weight directly -- the effect
    travels through the regulatory network, not through direct pleiotropy.
    """
    runx2_direct = set(LOCUS_BY_SYMBOL["RUNX2"].weights)

    base = {t: [] for t in CONTINUOUS}
    ko = {t: [] for t in CONTINUOUS}
    for i in range(300):
        npc = random_founder(f"n{i}", rng)
        b = {t: npc.liability(t) for t in CONTINUOUS}
        npc.perturb_gene("RUNX2", 0.0)          # knockout
        k = {t: npc.liability(t) for t in CONTINUOUS}
        for t in CONTINUOUS:
            base[t].append(b[t]); ko[t].append(k[t])

    shift = {t: float(np.mean(np.array(ko[t]) - np.array(base[t])))
             for t in CONTINUOUS}

    trans_only = {t: s for t, s in shift.items()
                  if t not in runx2_direct and abs(s) > 0.02}

    # at least three UNRELATED traits move through the network
    assert len(trans_only) >= 3, trans_only
    # and the shift is a coherent program, not sign-scrambled noise
    signs = np.sign(list(trans_only.values()))
    assert abs(signs.sum()) == len(signs), trans_only


def test_knockout_also_kills_direct_effect(rng):
    """Perturbing a hub scales its OWN expression too, so its direct trait
    weights collapse -- a knockout is not trans-only."""
    npc = random_founder("d0", rng)
    before = npc.liability("nose_bridge_breadth")   # RUNX2 direct
    npc.perturb_gene("RUNX2", 0.0)
    after = npc.liability("nose_bridge_breadth")
    assert abs(after - before) > 1e-9


def test_perturbation_is_reversible(rng):
    """factor=1.0 restores wild type exactly (removes the override)."""
    npc = random_founder("r0", rng)
    p0 = npc.phenotype().copy()
    npc.perturb_gene("RUNX2", 0.0)
    assert npc.grn_perturbation
    npc.perturb_gene("RUNX2", 1.0)
    assert not npc.grn_perturbation
    p1 = npc.phenotype()
    assert all(p0[t] == p1[t] for t in p0)


# ------------------------------------- epigenome -> GRN coupling (the loop)

def test_epigenetic_silencing_propagates_through_network(rng):
    """
    The epigenome -> GRN coupling, via the REAL composition path
    (epigenome.expression() -> NETWORK.compose), not just the perturb API.

    Hypermethylating NR3C1 -- the same channel chronic stress uses
    (roadmap #18) -- drops its activity below baseline, and because NR3C1 is
    a hub its INFLAMMATION-family targets all move together. We assert the
    perturbation (i) reaches inflammation_tone measurably and (ii) is
    coherent across the program's traits (same sign), which is the honest
    claim: the multiplier is a symmetric amplifier, so the shift is coherent
    but its mean direction is governed by the targets' allele frequencies,
    not by the edge sign (see module docstring).
    """
    from health_engine.epigenome import BASELINE_METHYLATION
    nr3c1 = LOCUS_BY_SYMBOL["NR3C1"].index
    program_traits = ["inflammation_tone", "immune_reactivity"]

    shifts = {t: [] for t in program_traits}
    for i in range(300):
        npc = random_founder(f"s{i}", rng)
        before = {t: npc.liability(t) for t in program_traits}
        # hypermethylate NR3C1 -> lower its expression below 1.0
        npc.epigenome.methylation[nr3c1] = min(1.0, BASELINE_METHYLATION + 0.4)
        npc.refresh_expression()
        for t in program_traits:
            shifts[t].append(npc.liability(t) - before[t])

    mean_shift = {t: float(np.mean(shifts[t])) for t in program_traits}
    # (i) the coupling reaches the program measurably: at least one program
    # trait clearly moves, and inflammation_tone itself is non-trivially
    # perturbed (thresholds well clear of sampling noise, not knife-edge).
    assert max(abs(s) for s in mean_shift.values()) > 0.01, mean_shift
    assert abs(mean_shift["inflammation_tone"]) > 0.004, mean_shift
    # (ii) ...and the program's traits move coherently (same direction).
    signs = np.sign(list(mean_shift.values()))
    assert abs(signs.sum()) == len(signs), mean_shift


def test_trans_multiplier_stays_bounded(rng):
    """Even stacking every hub knockout at once, the trans multiplier stays
    inside its clip bounds -- composed expression can never go negative or
    explode."""
    cis = np.ones(N_LOCI)
    perturb = {p.hub: 0.0 for p in grn._PROGRAMS}
    expr = NETWORK.compose(cis, perturb)
    assert expr.min() >= TRANS_MIN - 1e-12
    assert expr.max() <= TRANS_MAX + 1e-12
