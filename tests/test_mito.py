"""
Mitochondrial-inheritance tests (roadmap #3).

The headline validations mirror the rest of the engine's closed-form ethos:
(1) mtDNA is strictly maternal -- a father's heteroplasmy never reaches his
children; (2) the oogenesis bottleneck gives offspring heteroplasmy the
variance h(1-h)/N_e; (3) OXPHOS capacity is a threshold function of mutant
load, the defining nonlinearity of mitochondrial disease; and (4) the
haplogroup marker traces the maternal line only.
"""

import numpy as np
import pytest

from health_engine.mito import (DISEASE_THRESHOLD, MITO_BOTTLENECK_N,
                                OXPHOS_THRESHOLD, MitoGenome, oxphos_capacity,
                                sample_founder_mito)
from health_engine.npc import random_founder, reproduce
from health_engine.validation import (mito_bottleneck, mito_is_strictly_maternal)


@pytest.fixture
def rng():
    return np.random.default_rng(20240724)


# ------------------------------------------------------ maternal inheritance

def test_mtdna_is_strictly_maternal(rng):
    """A father's mtDNA never reaches his offspring."""
    assert mito_is_strictly_maternal(2000, rng)


def test_child_mtdna_comes_from_mother_in_reproduce(rng):
    """Through the full reproduce() path: the child's haplogroup is the
    mother's, regardless of the father's."""
    mum = random_founder("mum", rng, sex="female")
    dad = random_founder("dad", rng, sex="male")
    # force distinct haplogroups so the source is unambiguous
    mum.mito = MitoGenome("J", 0.0)
    dad.mito = MitoGenome("H", 0.0)
    for i in range(30):
        kid = reproduce(mum, dad, f"k{i}", rng)
        assert kid.mito.haplogroup == "J"        # mother's, never father's "H"


def test_carrier_father_does_not_transmit(rng):
    """Even a homoplasmic-mutant father transmits no heteroplasmy."""
    mum = random_founder("mum", rng, sex="female")
    dad = random_founder("dad", rng, sex="male")
    mum.mito = MitoGenome("H", 0.0)
    dad.mito = MitoGenome("H", 1.0)              # father fully mutant
    for i in range(30):
        kid = reproduce(mum, dad, f"k{i}", rng)
        assert kid.mito.heteroplasmy == 0.0


# --------------------------------------------------------- the bottleneck

@pytest.mark.parametrize("h", [0.3, 0.5, 0.7])
def test_bottleneck_variance_matches_closed_form(rng, h):
    """Offspring heteroplasmy: mean = mother's, variance = h(1-h)/N_e."""
    res = mito_bottleneck(h, 20000, rng)
    assert res.passes(), (h, res)


def test_bottleneck_drives_toward_homoplasmy(rng):
    """Across generations the bottleneck pushes a lineage toward fixation
    (0 or 1) -- segregation, the reason heteroplasmy rarely stays at 50%."""
    # walk a single maternal lineage for many generations
    n_lineages, generations = 400, 80
    fixed = 0
    for _ in range(n_lineages):
        m = MitoGenome("H", 0.5)
        for _ in range(generations):
            m = m.transmit(rng)
        if m.heteroplasmy in (0.0, 1.0):
            fixed += 1
    # most lineages should have drifted to fixation
    assert fixed / n_lineages > 0.7


# --------------------------------------------------------- threshold effect

def test_oxphos_is_a_threshold_function():
    """Near-normal OXPHOS below threshold, steep fall above -- the defining
    nonlinearity (Rossignol 2003)."""
    below = oxphos_capacity(OXPHOS_THRESHOLD - 0.3)
    at = oxphos_capacity(OXPHOS_THRESHOLD)
    above = oxphos_capacity(OXPHOS_THRESHOLD + 0.2)
    assert below > 0.95                      # complementation keeps it normal
    assert above < 0.35                      # steep collapse past threshold
    assert below > at > above                # monotonic decreasing
    # the drop is concentrated at the knee, not linear
    low_slope = oxphos_capacity(0.2) - oxphos_capacity(0.4)
    knee_slope = oxphos_capacity(0.6) - oxphos_capacity(0.8)
    assert knee_slope > 5 * low_slope


def test_disease_manifests_only_above_threshold():
    assert not MitoGenome("H", DISEASE_THRESHOLD - 0.05).manifests_disease()
    assert MitoGenome("H", DISEASE_THRESHOLD + 0.05).manifests_disease()


def test_heteroplasmy_gates_aerobic_capacity(rng):
    """A high-heteroplasmy carrier has measurably lower effective aerobic
    capacity than the same nuclear genome with healthy mitochondria."""
    npc = random_founder("a", rng)
    npc.mito = MitoGenome("H", 0.0)
    healthy = npc.effective_aerobic_capacity()
    npc.mito = MitoGenome("H", 0.95)             # above threshold
    diseased = npc.effective_aerobic_capacity()
    assert diseased < 0.4 * healthy              # OXPHOS floor drags it down
    assert healthy == float(npc.phenotype()["aerobic_capacity"])  # no mito loss


# ----------------------------------------------------- haplogroup lineage

def test_haplogroup_traces_maternal_line(rng):
    """The haplogroup is constant down a maternal line but a father does not
    impose his on the children -- exactly how mtDNA marks maternal lineage."""
    founder_mum = random_founder("gm", rng, sex="female")
    founder_mum.mito = MitoGenome("X", 0.0)
    dad = random_founder("gd", rng, sex="male")
    dad.mito = MitoGenome("H", 0.0)
    # three generations down the female line
    line = founder_mum
    for gen in range(3):
        partner = random_founder(f"p{gen}", rng, sex="male")
        daughter = reproduce(line, partner, f"d{gen}", rng, sex="female")
        assert daughter.mito.haplogroup == "X"
        line = daughter


def test_founder_haplogroups_are_sampled(rng):
    """Founders draw haplogroups from the marker frequencies; H is commonest."""
    hgs = [sample_founder_mito(rng).haplogroup for _ in range(5000)]
    from collections import Counter
    c = Counter(hgs)
    assert c.most_common(1)[0][0] == "H"
    assert all(h == 0.0 for h in
               [sample_founder_mito(rng).heteroplasmy for _ in range(200)])


# ------------------------------------------------------------- invariant

def test_mito_layer_does_not_touch_nuclear_phenotype(rng):
    """The mitochondrial layer is parallel: nuclear expression is untouched."""
    npc = random_founder("f", rng)
    assert np.allclose(npc.expression, 1.0)
    assert npc.mito is not None and npc.mito.heteroplasmy == 0.0
