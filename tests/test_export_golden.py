"""
The golden-fixture tripwire: proof that a change did not move the science.
==========================================================================

Stage 0 of `reads/UNITY_PLAN.md`. The Unity front-end is a *viewer*: it may
add export columns, but it must never perturb a calibrated number. That is an
easy promise to make and, without this file, an impossible one to check --
"the suite still passes" says nothing when no test in the suite would notice a
shifted RNG stream.

So this module freezes one world and asserts two things about it:

1. **Every scalar in `world.history`**, exactly, for 60 ticks. This is the
   sensitive half: `history` carries heterozygosity, mean inbreeding, Morton's
   B, viability and the tracked trait means, so almost any perturbation of the
   generator stream shows up here within a few ticks.

2. **An md5 of `people.csv` restricted to the columns that existed when the
   fixture was cut.** The restriction is the whole point: a new column may be
   *added* (the Unity work needs `map_x`/`map_y` and friends) while the old
   ones are proved not to have moved, been reordered, or changed type.

Why exact equality and not a tolerance
--------------------------------------
A tolerance answers "is this close enough?", which is a scientific question
about a *model*. This file asks a different and much narrower question: "is
this the same computation?" Bit-identical is the only honest answer to that,
and it is achievable because the engine is deterministic given a seed. A
tolerance here would quietly absorb exactly the drift the file exists to find.

The self-test
-------------
`test_the_tripwire_would_notice_a_perturbed_rng` is the most important test in
this module. It draws one throwaway number from the world's generator and
asserts the comparison *fails*. Without it, this file could rot into a check
that cannot fail -- a green tick that means nothing. A tripwire that has never
been seen to trip is not evidence.

Regenerating the fixture
------------------------
Deliberate science changes (a new layer, a recalibration) legitimately move
these numbers, and the fixture must then be re-cut. A golden file that is
re-cut silently is worse than no golden file at all, because it looks like
protection -- so the reason is mandatory and is committed into the fixture:

    EXTNPC_UPDATE_GOLDEN="session 18: added the X layer, V_D recalibrated" \
        python -m pytest tests/test_export_golden.py -q

A bare `1` is refused. See `_regeneration_is_authorised`, and record the same
reason in `reads/REPORT.md`.
"""

from __future__ import annotations

import hashlib
import json
import os
import warnings
from pathlib import Path
from typing import Dict, List

import pytest

from health_engine.loci import CATALOGUE_MODE
from simulation import World
from simulation import export as EX

warnings.filterwarnings("ignore")

# --------------------------------------------------------------------------
# The frozen run. Small enough to be fast (~1.5 s), long enough that births,
# deaths, pairing, inbreeding and the load layer have all had to happen.
# --------------------------------------------------------------------------
N_FOUNDERS = 12
SEED = 7
TICKS = 60

FIXTURE = Path(__file__).parent / "fixtures" / "golden_world_s7_f12_t60.json"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _build_world(perturb_rng: bool = False) -> World:
    """The frozen world. With `perturb_rng`, one throwaway draw is taken from
    the world's generator before stepping -- the deliberate sabotage the
    self-test uses to prove this module can fail."""
    w = World(n_founders=N_FOUNDERS, seed=SEED)
    if perturb_rng:
        w.rng.random()
    for _ in range(TICKS):
        w.step()
    return w


def _history(world: World) -> List[Dict]:
    """History rows as plain JSON scalars, so a fixture round-trips exactly.
    Python's json writes floats via repr, which is exact for float64."""
    return [{k: EX._safe(v) for k, v in row.items()} for row in world.history]


def _people_csv_md5(world: World, columns: List[str]) -> str:
    """md5 of people.csv projected onto `columns`, in that order.

    Projecting rather than hashing the whole file is what lets the Unity work
    add columns without re-cutting the fixture, while still catching a change
    to any column that already existed.
    """
    rows = EX.people_rows(world)
    projected = [{c: r.get(c, "") for c in columns} for r in rows]
    return hashlib.md5(EX._csv_bytes(projected).encode("utf-8")).hexdigest()


def _load_fixture() -> dict:
    if not FIXTURE.exists():
        pytest.fail(
            f"Golden fixture missing: {FIXTURE}\n"
            f"Cut it with:  EXTNPC_UPDATE_GOLDEN=1 python -m pytest "
            f"tests/test_export_golden.py -q")
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _write_fixture(world: World) -> dict:
    columns = list(EX.people_rows(world)[0].keys())
    payload = {
        "_comment": (
            "Golden fixture for tests/test_export_golden.py -- the tripwire "
            "proving that additive export work did not move a calibrated "
            "number. DO NOT regenerate to make a red test go green. See the "
            "module docstring."),
        "seed": SEED,
        "n_founders": N_FOUNDERS,
        "ticks": TICKS,
        "catalogue": CATALOGUE_MODE,
        # WHY this fixture was re-cut. Committed on purpose: it is the record
        # that makes a regeneration reviewable instead of invisible.
        "recut_reason": _regeneration_reason(),
        # Informational, never asserted -- it would go stale on every commit.
        "engine_commit_when_cut": EX.git_commit(),
        "people_columns": columns,
        "people_csv_md5": _people_csv_md5(world, columns),
        "history": _history(world),
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _regeneration_reason() -> str:
    """The reason given for re-cutting the fixture, or "" if none was."""
    return os.environ.get("EXTNPC_UPDATE_GOLDEN", "").strip()


def _regeneration_is_authorised() -> bool:
    """
    Whether this run is allowed to overwrite the golden fixture.

    TRADE-OFF, and the reason this is its own function: a regeneration path
    that is too easy defeats the tripwire, because the natural reflex on a red
    test is to re-cut the fixture and move on -- which silently blesses
    whatever drift caused the failure. A path that is too hard gets worked
    around by deleting the file, which is worse.

    POLICY: a bare flag is not enough. The variable must carry a *reason*,
    which `_write_fixture` writes into the committed JSON. A silent re-cut
    therefore becomes a visible line in `git diff` sitting next to the numbers
    it excuses, and a reviewer can ask what changed. Nothing here can stop a
    determined re-cut -- the point is that it cannot be done invisibly.

        EXTNPC_UPDATE_GOLDEN="session 18: added the X layer, V_D recalibrated" \
            python -m pytest tests/test_export_golden.py -q

    Then record the same reason in reads/REPORT.md.
    """
    reason = _regeneration_reason()
    if not reason or reason in {"1", "true", "yes", "y", "on"}:
        return False
    return len(reason) >= _MIN_REASON_CHARS


# Long enough that "ok", "fix" and "asdf" do not qualify; short enough that a
# real one-line reason is not a chore.
_MIN_REASON_CHARS = 12


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def world() -> World:
    return _build_world()


@pytest.fixture(scope="module")
def golden(world) -> dict:
    if _regeneration_is_authorised():
        return _write_fixture(world)
    return _load_fixture()


# --------------------------------------------------------------------------
# the guard
# --------------------------------------------------------------------------

def test_the_fixture_matches_the_active_catalogue(golden):
    """The fixture is cut under one locus catalogue and means nothing under
    the other. Session 16 learned this the expensive way: a check that cannot
    distinguish model versions is not a check."""
    if golden["catalogue"] != CATALOGUE_MODE:
        pytest.skip(
            f"fixture is for catalogue={golden['catalogue']!r}, "
            f"running under {CATALOGUE_MODE!r} -- not comparable")
    assert golden["seed"] == SEED and golden["ticks"] == TICKS


def test_history_is_unchanged(world, golden):
    """Every scalar of every year, exactly. This is the sensitive half."""
    if golden["catalogue"] != CATALOGUE_MODE:
        pytest.skip("fixture cut under a different catalogue")

    now = _history(world)
    expected = golden["history"]

    assert len(now) == len(expected), (
        f"history length changed: {len(expected)} -> {len(now)} rows")

    for i, (a, b) in enumerate(zip(expected, now)):
        assert set(a) == set(b), (
            f"tick {i}: history columns changed\n"
            f"  removed: {sorted(set(a) - set(b))}\n"
            f"  added:   {sorted(set(b) - set(a))}")
        for key in a:
            assert a[key] == b[key], (
                f"tick {i}, column {key!r} moved: {a[key]!r} -> {b[key]!r}\n"
                f"Something perturbed the calibrated computation. This is the "
                f"tripwire in reads/UNITY_PLAN.md Part 0 doing its job.")


def test_no_frozen_people_column_has_disappeared(world, golden):
    """Additive-only, checked as its own assertion so the failure message
    names the missing column instead of just reporting an md5 mismatch."""
    if golden["catalogue"] != CATALOGUE_MODE:
        pytest.skip("fixture cut under a different catalogue")

    current = set(EX.people_rows(world)[0].keys())
    frozen = set(golden["people_columns"])
    missing = sorted(frozen - current)
    assert not missing, (
        f"people.csv lost frozen column(s): {missing}. Export changes must be "
        f"ADDITIVE (UNITY_PLAN.md invariant 2).")


def test_people_csv_is_unchanged_on_the_frozen_columns(world, golden):
    """New columns are allowed; the old ones must be byte-identical."""
    if golden["catalogue"] != CATALOGUE_MODE:
        pytest.skip("fixture cut under a different catalogue")

    got = _people_csv_md5(world, golden["people_columns"])
    assert got == golden["people_csv_md5"], (
        "people.csv changed on columns that existed when the fixture was cut. "
        "Adding a column is fine; changing an existing value, its order or "
        "its formatting is not.")


# --------------------------------------------------------------------------
# the self-test -- the reason this module is evidence and not decoration
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value,allowed", [
    ("", False),
    ("1", False),                                   # the reflexive one
    ("true", False),
    ("yes", False),
    ("fix", False),                                 # too short to be a reason
    ("session 18: added the X layer", True),
])
def test_regeneration_demands_a_real_reason(monkeypatch, value, allowed):
    """The fixture may only be re-cut by someone willing to say why, because
    the reason lands in the committed JSON where a reviewer will see it."""
    monkeypatch.setenv("EXTNPC_UPDATE_GOLDEN", value)
    assert _regeneration_is_authorised() is allowed


def test_the_committed_fixture_records_why_it_was_cut(golden):
    """A fixture with no reason on it cannot be audited later."""
    assert len(golden.get("recut_reason", "")) >= _MIN_REASON_CHARS, (
        "the committed golden fixture carries no regeneration reason")


def test_the_tripwire_would_notice_a_perturbed_rng(golden):
    """
    Draw ONE throwaway number from the world's generator, then assert the
    comparison above fails.

    If this test ever passes-by-not-failing -- i.e. if a perturbed world
    produces the golden history -- then the guard tests are vacuous and their
    green ticks mean nothing. This is the check that keeps them honest.
    """
    if golden["catalogue"] != CATALOGUE_MODE:
        pytest.skip("fixture cut under a different catalogue")

    sabotaged = _history(_build_world(perturb_rng=True))
    expected = golden["history"]

    differs = (len(sabotaged) != len(expected) or
               any(a[k] != b.get(k) for a, b in zip(expected, sabotaged)
                   for k in a))
    assert differs, (
        "A single extra RNG draw did not change the recorded history. The "
        "guard tests in this module cannot detect drift and are worthless as "
        "written -- fix them before trusting any 'nothing changed' claim.")
