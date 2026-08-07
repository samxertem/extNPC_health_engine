"""
Tests for the named Mendelian disease layer (diseases.py).

Three claims, in increasing order of interest:

  1. The assignment is a deterministic constant of the engine: same loci
     on every import, unique, and within documented distance of the
     literature -- with cystic fibrosis pinned as the KNOWN misfit, so the
     documentation cannot quietly go stale.
  2. The layer is a pure read-out. No RNG anywhere, no mutation of the
     load it reads, no change to the spectrum's calibration -- an affected
     individual's survival cost is the SAME cost it paid before the locus
     had a name.
  3. The epidemiology is recoverable: P(affected) = q^2 + Fpq at the
     panel loci, exactly linear in F, recovered by validation [9d] from
     simulated pedigrees that never evaluate it.
"""

import numpy as np
import pytest

from health_engine import validation as V
from health_engine.diseases import (CATALOGUE, DISEASES, PANEL_LOCI, _assign,
                                    carrier_of, diagnoses,
                                    expected_affected_count,
                                    expected_carrier_share, relative_risk)
from health_engine.inbreeding import (SPECTRUM, DeleteriousLoad,
                                      sample_founder_load)
from health_engine.npc import random_founder


# ======================================================================
# 1. The assignment is a frozen, honest constant
# ======================================================================

# Pinned loci, in catalogue order. If this fails, either the spectrum seed
# changed (a model-version event) or the catalogue order changed (which
# silently reassigns every disease) -- both must be deliberate.
_EXPECTED_LOCI = [1866, 1432, 1893, 127, 667, 1897, 700, 204, 1173]


def test_assignment_is_pinned_and_unique():
    assert [d.locus for d in DISEASES] == _EXPECTED_LOCI
    assert len({d.locus for d in DISEASES}) == len(DISEASES)
    # And reproducible from scratch, not an import-order accident.
    assert [d.locus for d in _assign(SPECTRUM, CATALOGUE)] == _EXPECTED_LOCI


def test_assignment_tracks_the_literature():
    """Every disease except the documented CF misfit matches the
    literature frequency within a factor of 1.5 and severity within a
    factor of 2. CF is asserted to MISS, because mutation-selection
    balance cannot hold q = 0.02 at s ~ 1 -- if a future spectrum change
    made CF fit, the module docstring's central caveat would be stale."""
    for d in DISEASES:
        if d.name == "cystic_fibrosis":
            assert d.q_ratio < 0.8 and d.s_ratio < 0.6
            assert "misfit" in d.spec.note.lower()
        else:
            assert 1 / 1.5 < d.q_ratio < 1.5, d.name
            assert 0.5 < d.s_ratio < 2.0, d.name


def test_engine_frequencies_are_the_spectrum_frequencies():
    for d in DISEASES:
        assert d.q == SPECTRUM.q[d.locus]
        assert d.s == SPECTRUM.s[d.locus]
        assert d.h == SPECTRUM.h[d.locus]


def test_calibration_is_untouched():
    """Labelling loci must not move the lethal-equivalent calibration:
    the panel loci were already inside B before they had names."""
    assert SPECTRUM.lethal_equivalents == pytest.approx(1.4, abs=1e-6)


# ======================================================================
# 2. Pure read-out: no RNG, no mutation, cost already paid
# ======================================================================

def _empty_load() -> DeleteriousLoad:
    return DeleteriousLoad(np.zeros((2, SPECTRUM.n_loci), dtype=np.int8))


def test_diagnosis_and_carrier_readout():
    load = _empty_load()
    pku = next(d for d in DISEASES if d.name == "phenylketonuria")
    cf = next(d for d in DISEASES if d.name == "cystic_fibrosis")
    load.haplotypes[:, pku.locus] = 1          # homozygous -> affected
    load.haplotypes[0, cf.locus] = 1           # heterozygous -> carrier
    assert [d.name for d in diagnoses(load)] == ["phenylketonuria"]
    assert [d.name for d in carrier_of(load)] == ["cystic_fibrosis"]


def test_readout_does_not_mutate_the_load():
    rng = np.random.default_rng(11)
    load = sample_founder_load(rng)
    before = load.haplotypes.copy()
    diagnoses(load), carrier_of(load)
    assert np.array_equal(load.haplotypes, before)


def test_npc_accessors_and_the_no_load_guard():
    npc = random_founder("proband", np.random.default_rng(3))
    assert isinstance(npc.mendelian_diagnoses(), list)
    assert isinstance(npc.mendelian_carrier_of(), list)
    npc.load = None
    assert npc.mendelian_diagnoses() == []
    assert npc.mendelian_carrier_of() == []


def test_affected_individual_pays_exactly_the_locus_s():
    """The disease's severity IS the assigned locus's selection
    coefficient, already applied by DeleteriousLoad.viability. Making the
    locus homozygous must multiply viability by exactly (1 - s)."""
    sma = next(d for d in DISEASES if d.name == "spinal_muscular_atrophy")
    clean = _empty_load()
    w0 = clean.viability()
    affected = _empty_load()
    affected.haplotypes[:, sma.locus] = 1
    assert affected.viability() / w0 == pytest.approx(1.0 - sma.s, rel=1e-12)


# ======================================================================
# 3. The epidemiology
# ======================================================================

def test_expected_affected_count_is_exactly_linear_in_F():
    q = np.array([d.q for d in DISEASES])
    intercept = float(np.sum(q ** 2))
    slope = float(np.sum((1.0 - q) * q))
    for F in (0.0, 1 / 64, 1 / 16, 0.25, 1.0):
        assert expected_affected_count(F) == pytest.approx(
            intercept + slope * F, rel=1e-12)


def test_first_cousin_relative_risk_is_many_fold():
    """The Modell & Darr 2002 signature: consanguinity multiplies rare-
    recessive incidence several-fold. For this panel the closed form
    lands near 7x at F = 1/16."""
    rr = relative_risk(1.0 / 16.0)
    assert 4.0 < rr < 12.0


def test_outbred_carrier_share_is_about_one_in_six():
    share = expected_carrier_share()
    assert 0.10 < share < 0.25


def test_founder_allele_frequencies_segregate_at_panel_q():
    """Founders draw panel alleles at the spectrum's q -- the closed forms
    above describe the genotypes the engine actually produces."""
    rng = np.random.default_rng(20260807)
    n = 4000
    counts = np.zeros(len(DISEASES))
    for _ in range(n):
        counts += sample_founder_load(rng).haplotypes[:, PANEL_LOCI].sum(axis=0)
    q_hat = counts / (2 * n)
    q = np.array([d.q for d in DISEASES])
    se = np.sqrt(q * (1 - q) / (2 * n))
    assert np.all(np.abs(q_hat - q) < 4.5 * se)


def test_mendelian_incidence_law_passes():
    """Validation [9d] end to end at a test-sized n."""
    r = V.mendelian_incidence(n_per_level=1200,
                              rng=np.random.default_rng(20260808))
    assert r.passes()
    assert r.expected_slope == pytest.approx(
        sum((1 - d.q) * d.q for d in DISEASES), rel=1e-12)
    # The most inbred cohort must sit clearly above the outbred one.
    assert r.mean_count[-1] > r.mean_count[0]
