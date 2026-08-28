"""
Adding a trait must cost the existing ones nothing.
===================================================

This is the tripwire under item E4, E5 and everything after them. It exists
because the hazard is invisible: adding a trait to `TRAIT_TABLE` and to
`PERIPHERAL_LOCUS_COUNT` looks like a purely additive change, produces no
error, and silently moves every other trait in every individual.

THE MEASUREMENT THAT MOTIVATED IT, taken on the way in rather than imagined.
Appending `sitting_height_ratio` and changing nothing else moved **1420 of
1560** pre-existing phenotype values across 40 founders, with all 39 older
traits affected. The cause is not interaction between traits, which does not
exist here; it is that `EnvironmentalDeviates.draw` drew every trait's
residual and THEN every trait's GxE input from a single stream, so one extra
name in the first block shifted the entire second block by one draw. With the
appended-trait path in place the same comparison moved 0 of 1560.

WHY IT MATTERS BEYOND TIDINESS. Session 11 recorded that committed figures did
not match what committed code produced, and traced it to a harness section
consuming the shared rng. Every published number in this project -- calibrated
heritabilities, the -11.93 cm/unit F depression, the Joshi nulls -- is a
property of a specific stream. A trait appended without this discipline
re-rolls all of them, every figure churns, and the diff gives no clue why.

WHAT THE FIXTURE IS. `fixtures/frozen_phenotypes.json` holds 12 founders' full
values for the 39 traits that predate the freeze, under a fixed seed. It is a
GOLDEN file in the strict sense: a failure here does not mean the new numbers
are wrong, it means they are DIFFERENT, and the difference has to be explained
before it is blessed. Regenerating it to make a red test go green throws away
the only evidence that anything moved.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pytest

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from health_engine.loci import PERIPHERAL_LOCUS_COUNT
from health_engine.npc import random_founder
from health_engine.traits import (APPENDED_TRAIT_NAMES, CONTINUOUS_TRAITS,
                                  FROZEN_TRAIT_NAMES, TRAIT_NAMES, TRAIT_TABLE)

FIXTURE = json.loads(
    (REPO / "tests" / "fixtures" / "frozen_phenotypes.json").read_text(
        encoding="utf-8"))


@pytest.fixture(scope="module")
def founders():
    rng = np.random.default_rng(FIXTURE["seed"])
    return [random_founder(f"F-{i}", rng)
            for i in range(FIXTURE["n_founders"])]


# ----------------------------------------------------------------------
# the guarantee
# ----------------------------------------------------------------------

def test_no_appended_trait_moves_a_frozen_one(founders):
    """The whole point of the file. 0 of 1560, not 1420 of 1560."""
    moved = []
    for npc, expected in zip(founders, FIXTURE["founders"]):
        assert npc.name == expected["name"]
        actual = npc.phenotype()
        for trait, want in expected["phenotype"].items():
            got = actual[trait]
            got = got if isinstance(got, str) else float(got)
            if got != want:
                moved.append(f"{npc.name}.{trait}: {want!r} -> {got!r}")

    assert not moved, (
        f"{len(moved)} frozen phenotype values moved. A trait was probably "
        f"inserted into TRAIT_TABLE or PERIPHERAL_LOCUS_COUNT above the "
        f"appended block, or declared without appended=True. First five:\n  "
        + "\n  ".join(moved[:5]))


def test_the_fixture_covers_every_frozen_trait():
    """A fixture that lost a trait would pass the test above while guarding
    nothing, which is the failure mode a golden file is most prone to."""
    covered = set(FIXTURE["founders"][0]["phenotype"])
    assert covered == set(FROZEN_TRAIT_NAMES), (
        f"fixture and FROZEN_TRAIT_NAMES disagree; "
        f"missing {sorted(set(FROZEN_TRAIT_NAMES) - covered)}, "
        f"extra {sorted(covered - set(FROZEN_TRAIT_NAMES))}")
    assert FIXTURE["n_frozen_traits"] == len(FROZEN_TRAIT_NAMES)


# ----------------------------------------------------------------------
# the discipline that makes the guarantee possible
# ----------------------------------------------------------------------

def test_appended_traits_are_last_in_the_table():
    """Order is load-bearing: `_build_map` threads one generator through
    TRAIT_TABLE in insertion order, so an appended trait sitting anywhere but
    the end re-rolls the architecture of everything after it."""
    flags = [TRAIT_TABLE[n].appended for n in TRAIT_NAMES]
    first_appended = flags.index(True) if True in flags else len(flags)
    assert all(flags[first_appended:]), (
        "a frozen trait is declared after an appended one; the appended block "
        "must stay at the bottom of TRAIT_TABLE")


def test_appended_traits_are_last_in_the_locus_quota_too():
    """The same rule for `loci.PERIPHERAL_LOCUS_COUNT`, which is walked in its
    own insertion order by its own generator. Getting one right and the other
    wrong is the easy mistake, because only one of them lives in traits.py."""
    order = list(PERIPHERAL_LOCUS_COUNT)
    appended = set(APPENDED_TRAIT_NAMES)
    present = [n for n in order if n in appended]
    assert present, "appended traits have no peripheral loci declared"
    tail = order[-len(present):]
    assert set(tail) == set(present), (
        f"appended traits must be last in PERIPHERAL_LOCUS_COUNT; the tail is "
        f"{tail}")


def test_the_split_is_exhaustive_and_disjoint():
    assert set(FROZEN_TRAIT_NAMES) | set(APPENDED_TRAIT_NAMES) == set(TRAIT_NAMES)
    assert not set(FROZEN_TRAIT_NAMES) & set(APPENDED_TRAIT_NAMES)
    assert APPENDED_TRAIT_NAMES, "nothing appended; this file guards nothing"


def test_an_appended_trait_still_gets_real_deviates(founders):
    """Derived-stream draws must still be draws.

    The way this could silently break is a derived generator created once and
    reused, or created from a constant seed, which would give every villager
    in the world the same environmental deviate for the new trait. Everyone
    would then differ only genetically and the trait's variance would come out
    at h2 instead of 1.
    """
    for trait in APPENDED_TRAIT_NAMES:
        values = [float(n.phenotype()[trait]) for n in founders]
        assert len(set(values)) == len(values), (
            f"{trait} repeats a value across founders; the derived generator "
            f"is probably not advancing")


def test_two_worlds_from_one_seed_agree_on_the_appended_traits():
    """Reproducibility, which the derived stream must not cost.

    `derived_rng` spawns from the parent's seed sequence, so the same parent
    seed must reach the same children. If this fails the new traits are
    reproducible only within a process, and no figure containing them could be
    regenerated.
    """
    def run():
        rng = np.random.default_rng(4242)
        return [[float(random_founder(f"X-{i}", rng).phenotype()[t])
                 for t in APPENDED_TRAIT_NAMES] for i in range(6)]

    assert run() == run()


# ----------------------------------------------------------------------
# and the new trait is a real trait, not a column of zeros
# ----------------------------------------------------------------------

def test_sitting_height_ratio_is_declared_as_a_continuous_trait():
    spec = TRAIT_TABLE["sitting_height_ratio"]
    assert "sitting_height_ratio" in CONTINUOUS_TRAITS
    assert spec.h2 == pytest.approx(0.80)
    assert spec.mean == pytest.approx(0.520)
    assert spec.sd == pytest.approx(0.021)


def test_sitting_height_ratio_lands_near_its_declared_distribution():
    """Loose bounds. This checks the trait is CALIBRATED, not that a sample of
    200 matches a mean to three decimals."""
    rng = np.random.default_rng(99)
    values = [float(random_founder(f"S-{i}", rng).phenotype()
                    ["sitting_height_ratio"]) for i in range(200)]
    mean = float(np.mean(values))
    sd = float(np.std(values, ddof=1))
    assert 0.510 < mean < 0.530, mean
    assert 0.014 < sd < 0.030, sd


def test_sitting_height_ratio_is_a_distinct_axis_from_stature():
    """The reason a RATIO was modelled rather than a leg length.

    A leg length would be most of `height_cm` again, and driving a body-shape
    channel from it would apply stature twice. The claim is distinctness, not
    orthogonality: real SHR does correlate weakly with stature, and the two
    share peripheral loci here by chance, so the bound is loose on purpose.
    """
    rng = np.random.default_rng(7)
    people = [random_founder(f"C-{i}", rng) for i in range(300)]
    height = np.array([float(p.phenotype()["height_cm"]) for p in people])
    shr = np.array([float(p.phenotype()["sitting_height_ratio"])
                    for p in people])
    r = float(np.corrcoef(height, shr)[0, 1])
    assert abs(r) < 0.25, f"SHR is not a distinct axis from stature: r={r:.3f}"


# ----------------------------------------------------------------------
# the stream discipline, tested at the mechanism
# ----------------------------------------------------------------------

def test_deriving_the_appended_streams_costs_the_parent_nothing_at_all():
    """The invariant, in BOTH currencies, and the second one cost a red suite.

    A generator has two resources a layer can consume. Draws advance the
    bit-generator state. Spawns advance a CHILD COUNTER on the shared seed
    sequence. `Generator.spawn` is free in the first currency and not in the
    second, which is exactly the trap this file exists to hold shut.

    What happened when the appended streams were spawned: `random_founder`
    also derives a generator for the deleterious load, so it got a different
    child, the load changed viability, viability changed who died, and
    `people.csv` and `history.csv` both moved. Meanwhile the frozen-phenotype
    fixture still reported 0 of 1560, because a phenotype fixture cannot see a
    mortality change. `test_export_golden.py` is what caught it.

    So the streams are derived from the parent's STATE, which is a read, and
    this test asserts both currencies rather than the one that was obvious.
    """
    from health_engine.inbreeding import derived_rng
    from health_engine.traits import _appended_streams

    # currency 1: draws
    plain = np.random.default_rng(7)
    expected_draw = plain.normal()
    drawn = np.random.default_rng(7)
    _appended_streams(drawn, 9)
    assert drawn.normal() == expected_draw, "the parent's draws moved"

    # currency 2: the child counter that `derived_rng` consumers share
    plain2 = np.random.default_rng(7)
    expected_child = derived_rng(plain2).normal()
    spawned = np.random.default_rng(7)
    _appended_streams(spawned, 9)
    assert derived_rng(spawned).normal() == expected_child, (
        "the parent's spawn counter moved, so every other derived_rng "
        "consumer -- the deleterious load among them -- will get a different "
        "stream and the exported world will change")


def test_the_appended_streams_survive_a_new_process():
    """Stable seeding, not `hash()`.

    Python salts `hash()` per process for strings, so a state-derived seed
    built on it gives a different villager on every interpreter restart, and
    the only symptom is a figure that cannot be regenerated to match the paper.
    These are pinned observations confirmed identical under PYTHONHASHSEED 0,
    1 and 999.
    """
    from health_engine.traits import _appended_streams

    got = [round(float(g.normal()), 9)
           for g in _appended_streams(np.random.default_rng(5), 2)]
    assert got == [1.086254671, 1.424639845], got


def test_appended_streams_are_positional():
    """Child k must be a function of k alone, so a trait appended later cannot
    disturb one appended earlier."""
    from health_engine.traits import _appended_streams

    def firsts(n):
        return [g.normal() for g in _appended_streams(np.random.default_rng(5), n)]

    one, two, five = firsts(1), firsts(2), firsts(5)
    assert one == two[:1] == five[:1]
    assert two == five[:2]


def test_the_frozen_stream_is_untouched_by_spawning():
    """Spawning must cost the caller nothing at all, or the frozen traits
    would move the moment an appended trait was added."""
    from health_engine.traits import _appended_streams

    plain = np.random.default_rng(5)
    expected = plain.normal()

    spawned = np.random.default_rng(5)
    _appended_streams(spawned, 7)
    assert spawned.normal() == expected


def test_lean_mass_fraction_is_declared_as_a_clipped_continuous_trait():
    spec = TRAIT_TABLE["lean_mass_fraction"]
    assert "lean_mass_fraction" in CONTINUOUS_TRAITS
    assert spec.h2 == pytest.approx(0.60)
    assert spec.mean == pytest.approx(0.750)
    assert spec.sd == pytest.approx(0.060)
    assert spec.clip == (0.50, 0.95)
    assert spec.h2 < TRAIT_TABLE["bmi"].h2, (
        "composition is declared LESS heritable than mass on purpose: it "
        "responds to activity and diet more than mass does")


def test_lean_mass_fraction_is_a_distinct_axis_from_bmi():
    """E4's whole premise. If composition tracked mass, `bmi` would already
    have carried it and the trait would buy nothing."""
    rng = np.random.default_rng(13)
    people = [random_founder(f"L-{i}", rng) for i in range(300)]
    bmi = np.array([float(p.phenotype()["bmi"]) for p in people])
    lean = np.array([float(p.phenotype()["lean_mass_fraction"])
                     for p in people])
    r = float(np.corrcoef(bmi, lean)[0, 1])
    assert abs(r) < 0.25, f"composition is not distinct from mass: r={r:.3f}"
