"""
Per-life-stage bodies: baking what the timeline can actually show.
=================================================================

Item U6's real fix. Before this, a person got ONE body baked at ONE age --
their age now, or their age at death -- so scrubbing the viewer's timeline
back to their childhood drew adult proportions on a correctly-scaled small
body. `select_everyone_staged` bakes a body per `(person, life stage)`
instead, and `BodyTarget.key` is what the viewer looks one up by.

WHAT IS ACTUALLY WORTH TESTING HERE, because most of this file could be
written so that it cannot fail. The selection reads back the recorded frames
rather than reasoning from the stage boundaries, and that choice is the whole
design: it is what makes the baked set exactly the set the viewer can request.
So the tests that matter are the ones that would catch a return to reasoning
from boundaries:

  * a founder arrives aged 18 to 35 and has no childhood IN THIS RUN, so
    asking for one is 2.5 s and 1.8 MB spent on a mesh no frame references;
  * conversely nothing a frame DOES reference may be missing, or the viewer
    falls back to the shared adult mesh and the defect is back;
  * and the stage bodies have to actually differ, because a feature that
    triples the bake count and emits 136 identical files would pass every
    count-based assertion in this file.

The world is built once for the module. It is the default village -- 12
founders, seed 7, 60 years -- because the interesting cases in it (founders
who arrive grown, a girl who dies at exactly a stage boundary, three
stillbirths that appear in no frame at all) are the ones that were found by
looking, and a smaller synthetic world would contain none of them.
"""

from __future__ import annotations

import collections
import hashlib
import json
import sys
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from export_bodies import (
    BodyTarget,
    bake_age_for_span,
    observable_age_floor,
    select_everyone,
    select_everyone_staged,
    select_family,
    targets_from_names,
    write_bodies,
)
from simulation import World


FOUNDERS, SEED, YEARS = 12, 7, 60


@pytest.fixture(scope="module")
def world():
    w = World(n_founders=FOUNDERS, seed=SEED)
    for _ in range(YEARS):
        w.step()
    return w


@pytest.fixture(scope="module")
def framed(world):
    """`{(name, life_stage)}` and `{name: [ages]}` as the frames recorded them.

    This is the viewer's own ground truth: it replays `frames.csv`, so the set
    of bodies it can ever ask for is exactly the set of pairs in here. Built
    independently of `select_everyone_staged` so the two can be compared.
    """
    pairs = set()
    ages = collections.defaultdict(list)
    for frame in world.snapshots:
        for row in frame["people"]:
            pairs.add((row["name"], row["life_stage"]))
            ages[row["name"]].append(float(row["age"]))
    return pairs, ages


@pytest.fixture(scope="module")
def targets(world):
    return select_everyone_staged(world)


# ----------------------------------------------------------------------
# the fixture itself has to contain the cases, or nothing below is a test
# ----------------------------------------------------------------------

def test_the_village_contains_the_cases_these_tests_need(world, framed):
    """Guard the fixture. Every assertion below is vacuous on a world with no
    founders who arrive grown and no one absent from the frames, and a seed
    change could quietly produce one."""
    pairs, _ = framed
    framed_names = {n for n, _ in pairs}

    grown_on_arrival = [n for n in world.people
                        if observable_age_floor(world, n) > 0]
    assert grown_on_arrival, "no founder arrives already grown -- test is vacuous"

    absent = set(world.people) - framed_names
    assert absent, "nobody is missing from the frames -- test is vacuous"

    assert len(world.people) > len(world.living), "nobody died -- test is vacuous"


# ----------------------------------------------------------------------
# the two directions: nothing unreachable, nothing missing
# ----------------------------------------------------------------------

def test_no_body_is_baked_that_no_frame_can_ask_for(targets, framed):
    """The 20% saving, and the assertion that protects it.

    Reasoning from the stage boundaries instead would bake every founder an
    infancy that is not in this run: 34 of 167 bakes on this village, each
    2.5 s and 1.8 MB, for meshes no frame references.
    """
    pairs, _ = framed
    unreachable = sorted({(t.name, t.stage) for t in targets} - pairs)
    assert unreachable == [], (
        f"{len(unreachable)} bodies would be baked that no frame can request, "
        f"e.g. {unreachable[:3]}")


def test_every_stage_a_frame_records_has_a_body(targets, framed):
    """The other direction. A missing body is worse than a wasted one: the
    viewer falls back to the SHARED ADULT mesh, which is the small-adult
    defect this whole feature exists to remove."""
    pairs, _ = framed
    missing = sorted(pairs - {(t.name, t.stage) for t in targets})
    assert missing == [], (
        f"{len(missing)} recorded (person, stage) pairs have no body, "
        f"e.g. {missing[:3]}")


def test_a_founder_gets_no_stage_from_before_the_simulation(world, targets):
    """A founder aged 29 in year 0 has no childhood the timeline can reach.

    Derived from `final_age - final_tick`, NOT from `PersonMeta.birth_tick`,
    which is stamped 0 for every founder even though they arrive aged 18 to
    35 and is therefore not a birth date for them.
    """
    by_name = collections.defaultdict(list)
    for t in targets:
        by_name[t.name].append(t)

    checked = 0
    for name in world.people:
        floor = observable_age_floor(world, name)
        if floor <= 0:
            continue
        checked += 1
        for t in by_name.get(name, []):
            assert t.age >= floor - 1.0, (
                f"{name} is baked at age {t.age:.2f} for stage {t.stage}, but "
                f"was already {floor:.2f} when the run began")
    assert checked >= 1


# ----------------------------------------------------------------------
# the feature is not a no-op
# ----------------------------------------------------------------------

def test_one_persons_stage_bodies_are_actually_different(world, targets, tmp_path):
    """The assertion that a count-based test cannot make.

    136 identical `.mhm` files would satisfy every other test in this file
    while tripling the bake cost for nothing.
    """
    by_name = collections.defaultdict(list)
    for t in targets:
        by_name[t.name].append(t)
    # The person with the most stages: the longest life is the strongest case.
    name = max(by_name, key=lambda n: len(by_name[n]))
    mine = sorted(by_name[name], key=lambda t: t.age)
    assert len(mine) >= 4, "pick a world where somebody lives through 4 stages"

    out = tmp_path / "bodies"
    manifest = write_bodies(world, mine, str(out))
    entries = sorted(manifest["bodies"], key=lambda e: e["age"])

    digests = [hashlib.sha256((out / e["mhm"]).read_bytes()).hexdigest()
               for e in entries]
    assert len(set(digests)) == len(digests), (
        f"{name}'s stage bodies are not all distinct -- staging is a no-op")

    heights = [e["height_cm"] for e in entries]
    assert heights[0] < heights[-1], (
        f"{name} does not get taller across their stages: {heights}")


def test_the_bake_age_sits_inside_the_stage_it_stands_for(world, targets, framed):
    """A body baked outside the ages it will be shown at is worse than no
    staging: it claims a shape for a span it never had."""
    _, ages = framed
    per_pair = collections.defaultdict(list)
    for frame in world.snapshots:
        for row in frame["people"]:
            per_pair[(row["name"], row["life_stage"])].append(float(row["age"]))

    for t in targets:
        seen = per_pair[(t.name, t.stage)]
        assert min(seen) <= t.age <= max(seen), (
            f"{t.key} baked at {t.age:.2f}, outside the "
            f"{min(seen):.2f}..{max(seen):.2f} it is displayed at")


def test_bake_age_is_the_midpoint():
    """Pinned because the docstring argues for it: the midpoint bounds the
    worst error at half the span rather than all of it."""
    assert bake_age_for_span("child", 2.0, 9.6) == pytest.approx(5.8)
    assert bake_age_for_span("infant", 0.0, 2.0) == pytest.approx(1.0)


# ----------------------------------------------------------------------
# the manifest has to be honest about what it did not bake
# ----------------------------------------------------------------------

def test_people_with_no_body_are_named_not_silently_dropped(world, targets,
                                                            tmp_path):
    """Three stillbirths from inbreeding depression are born and dead inside
    one tick, so they appear in no frame and get no body.

    They must be NAMED. A consumer that simply finds no body falls back to the
    shared adult mesh, and drawing a stillborn infant as an adult is the
    defect item U6 exists to remove, arrived at from the other side.
    """
    manifest = write_bodies(world, targets, str(tmp_path / "b"))
    listed = {u["name"] for u in manifest["never_rendered"]}
    expected = set(world.people) - {t.name for t in targets}

    assert listed == expected
    assert listed, "vacuous -- this world has no unrendered people"
    for entry in manifest["never_rendered"]:
        assert entry["reason"]
        assert entry["age"] == pytest.approx(0.0, abs=1.0)


def test_never_rendered_is_not_just_everyone_the_caller_skipped(world, tmp_path):
    """The two sets are different and only one of them is a claim.

    `select_family` exports a related subset for the Stage 8 contact sheet.
    Subtracting it from the world would label every villager the caller simply
    did not ask for as someone who "appears in no frame" -- a sentence that is
    false, specific, and printed with a straight face. It reached a user-facing
    installer line reading "30 people have no body by design" before it was
    caught, so it is pinned here.
    """
    family = targets_from_names(world, select_family(world, 6))
    subset = write_bodies(world, family, str(tmp_path / "few"))
    everyone = write_bodies(world, select_everyone_staged(world),
                            str(tmp_path / "all"))

    named_in_subset = {u["name"] for u in subset["never_rendered"]}
    named_in_full = {u["name"] for u in everyone["never_rendered"]}

    assert named_in_subset == named_in_full, (
        "who was never renderable is a property of the WORLD, not of which "
        "bodies this call happened to export")
    assert len(family) < len(world.people)
    assert named_in_subset, "vacuous -- this world has no unrendered people"


def test_manifest_separates_bodies_from_people(world, targets, tmp_path):
    """`count` is bodies and `people` is individuals; in staged mode they
    differ, and a reader comparing either against the village headcount has to
    know which one they are holding."""
    manifest = write_bodies(world, targets, str(tmp_path / "b"))
    assert manifest["bodies_schema"] == 2
    assert manifest["staged"] is True
    assert manifest["count"] == len(targets)
    assert manifest["people"] == len({t.name for t in targets})
    assert manifest["count"] > manifest["people"], "staging bought nothing"


def test_every_body_key_is_unique_and_survives_a_filename(world, targets,
                                                          tmp_path):
    """Two bodies landing on one file would silently overwrite, and the loser
    would render as whoever won."""
    manifest = write_bodies(world, targets, str(tmp_path / "b"))
    keys = [e["key"] for e in manifest["bodies"]]
    stems = [e["stem"] for e in manifest["bodies"]]
    assert len(set(keys)) == len(keys)
    assert len(set(stems)) == len(stems), "two bodies collide on one filename"
    for e in manifest["bodies"]:
        assert (tmp_path / "b" / e["mhm"]).exists()


# ----------------------------------------------------------------------
# the un-staged path still behaves as it did
# ----------------------------------------------------------------------

def test_unstaged_export_is_one_body_per_person_keyed_by_name(world, tmp_path):
    """Stage 8's contact sheet and every existing consumer read this path.

    `key` must equal `name` here, or a viewer written against schema 1 stops
    finding anybody.
    """
    names = select_everyone(world)
    manifest = write_bodies(world, targets_from_names(world, names),
                            str(tmp_path / "b"))
    assert manifest["staged"] is False
    assert manifest["count"] == manifest["people"] == len(names)
    for e in manifest["bodies"]:
        assert e["key"] == e["name"]
        assert e["life_stage"] == ""


def test_unstaged_bakes_each_person_at_their_own_final_age(world, tmp_path):
    """The pre-U6 contract: a person's one body is their age now, or at death."""
    names = select_everyone(world)[:8]
    manifest = write_bodies(world, targets_from_names(world, names),
                            str(tmp_path / "b"))
    for e in manifest["bodies"]:
        assert e["age"] == pytest.approx(float(world.people[e["name"]].age), abs=1e-3)


def test_staged_selection_falls_back_when_nothing_was_captured():
    """A zero-tick world has no frames. Returning nothing would export a
    village of no one, which reads as success."""
    w = World(n_founders=6, seed=3)
    w.snapshots.clear()
    out = select_everyone_staged(w)
    assert {t.name for t in out} == set(w.people)
    assert all(t.stage is None for t in out)
    assert all(t.key == t.name for t in out)
