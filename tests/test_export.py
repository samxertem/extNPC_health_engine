"""
Tests for getting a run out of the engine.

Two different jobs with two different standards of proof:

* the **CSV bundle** is for analysis, so what matters is that the numbers in
  the tables are the numbers in the world, that nobody is silently dropped,
  and that the manifest describes the run accurately enough to reproduce it;

* the **world save** is engine-ready, so the only standard that means anything
  is that a restored world **continues identically**. A save that merely
  round-trips its fields can still be silently wrong -- that is exactly the
  bug this suite found, and `test_a_restored_world_continues_identically` is
  the test that catches it.
"""

import gzip
import io
import json
import warnings
import zipfile

import numpy as np
import pytest

from simulation import DemographyParams, World
from simulation import export as EX
from simulation.worldsave import build_world_save, load_world_save

warnings.filterwarnings("ignore")


@pytest.fixture(scope="module")
def world():
    w = World(n_founders=14, seed=11)
    for _ in range(30):
        w.step()
    return w


@pytest.fixture(scope="module")
def bundle(world):
    return zipfile.ZipFile(io.BytesIO(EX.build_csv_bundle(world, note="pytest")))


def _rows(zf, name):
    import csv
    text = zf.read(name).decode("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


# =====================================================================
# CSV bundle
# =====================================================================

def test_the_bundle_contains_every_promised_file(bundle):
    assert set(bundle.namelist()) == {
        "people.csv", "history.csv", "pedigree.csv", "manifest.json",
        "README.txt"}


def test_people_table_includes_the_dead(world, bundle):
    """Excluding the dead is the classic way to condition an analysis on
    survival, so they are in by default and flagged rather than dropped."""
    rows = _rows(bundle, "people.csv")
    assert len(rows) == len(world.people)
    alive = {n.name for n in world.living}
    assert sum(1 for r in rows if r["alive"] == "True") == len(alive)
    assert any(r["alive"] == "False" for r in rows), "nobody died in this run"


def test_living_only_scope_really_filters(world):
    blob = EX.build_csv_bundle(world, living_only=True)
    rows = _rows(zipfile.ZipFile(io.BytesIO(blob)), "people.csv")
    assert len(rows) == len(world.living)
    assert all(r["alive"] == "True" for r in rows)


def test_people_table_values_match_the_engine(world, bundle):
    rows = {r["name"]: r for r in _rows(bundle, "people.csv")}
    for npc in list(world.living)[:25]:
        r = rows[npc.name]
        assert r["sex"] == npc.sex
        assert int(r["age"]) == npc.age
        assert int(r["generation"]) == npc.generation
        assert float(r["heterozygosity"]) == pytest.approx(npc.heterozygosity())
        assert float(r["pedigree_f"]) == pytest.approx(
            world.inbreeding_of(npc.name))
        assert float(r["realised_f"]) == pytest.approx(npc.realised_inbreeding())
        assert float(r["trait_height_cm"]) == pytest.approx(
            npc.phenotype()["height_cm"])
        assert float(r["height_at_age_cm"]) == pytest.approx(npc.height_at_age())


def test_mature_and_age_expressed_height_are_separate_columns(world, bundle):
    """The distinction #13 introduced has to survive the export, or every
    downstream analysis silently uses adult stature for children."""
    rows = _rows(bundle, "people.csv")
    growing = [r for r in rows
               if abs(float(r["trait_height_cm"]) - float(r["height_at_age_cm"])) > 1.0]
    assert growing, "no one is mid-growth, so the columns cannot be distinguished"


def test_parents_round_trip_into_the_pedigree_table(world, bundle):
    edges = _rows(bundle, "pedigree.csv")
    expected = sum(1 for n in world.people.values() for p in (n.parents or ()) if p)
    assert len(edges) == expected
    assert {e["role"] for e in edges} <= {"mother", "father"}
    names = set(world.people)
    for e in edges:
        assert e["child"] in names and e["parent"] in names


def test_history_table_is_one_row_per_year(world, bundle):
    rows = _rows(bundle, "history.csv")
    assert len(rows) == len(world.history)
    assert int(rows[-1]["tick"]) == world.tick
    assert int(rows[-1]["n_alive"]) == len(world.living)


def test_manifest_records_what_produced_the_numbers(world, bundle):
    m = json.loads(bundle.read("manifest.json"))
    assert m["seed"] == world.seed and m["tick"] == world.tick
    assert m["note"] == "pytest"
    assert m["params"]["carrying_capacity"] == world.params.carrying_capacity
    assert m["summary"]["n_living"] == len(world.living)
    assert m["summary"]["n_ever_lived"] == len(world.people)
    assert m["git_commit"] and m["python"]
    assert m["libraries"]["numpy"] == np.__version__


def test_manifest_reports_fst_as_null_in_a_single_deme_world(world, bundle):
    """Same honesty rule as the dashboard: undefined is not zero."""
    assert world.params.n_demes == 1
    assert json.loads(bundle.read("manifest.json"))["summary"]["fst"] is None


def test_manifest_reports_fst_when_there_is_structure():
    w = World(n_founders=16, seed=5,
              params=DemographyParams(n_demes=4, migration_rate=0.02))
    for _ in range(12):
        w.step()
    assert EX.manifest(w)["summary"]["fst"] is not None


def test_manifest_carries_its_caveats(bundle):
    caveats = " ".join(json.loads(bundle.read("manifest.json"))["caveats"])
    assert "CROSS-SECTIONAL" in caveats
    assert "survival" in caveats


def test_the_bundle_survives_an_empty_and_an_extinct_world():
    empty = World(n_founders=0, seed=1)
    blob = EX.build_csv_bundle(empty)
    assert zipfile.ZipFile(io.BytesIO(blob)).namelist()

    dead = World(n_founders=6, seed=2)
    for _ in range(5):
        dead.step()
    dead.living.clear()
    assert EX.build_csv_bundle(dead)


def test_export_does_not_mutate_the_world(world):
    before = (world.tick, len(world.living), len(world.people),
              len(world.history))
    EX.build_csv_bundle(world)
    EX.manifest(world)
    build_world_save(world)
    assert (world.tick, len(world.living), len(world.people),
            len(world.history)) == before


# =====================================================================
# World save
# =====================================================================

def test_a_save_round_trips_every_individual(world):
    restored = load_world_save(build_world_save(world))
    assert restored.tick == world.tick
    assert len(restored.people) == len(world.people)
    assert [n.name for n in restored.living] == [n.name for n in world.living]
    for name, npc in list(world.people.items())[:20]:
        other = restored.people[name]
        assert other.sex == npc.sex and other.age == npc.age
        assert np.array_equal(other.genome.haplotypes, npc.genome.haplotypes)
        assert other.phenotype()["height_cm"] == pytest.approx(
            npc.phenotype()["height_cm"])


def test_a_restored_world_continues_identically(world):
    """
    THE test for this feature. Field-by-field equality is not enough: a save
    can restore every visible value and still diverge on the next step.

    That is exactly what happened here. `Generator.spawn()` -- which the
    engine uses for inherited deleterious load (#31) precisely BECAUSE it
    leaves the bit-generator state untouched -- advances the seed sequence's
    child counter, and that counter is not part of `bit_generator.state`.
    Restoring state alone rewound it, so the reloaded world produced identical
    people, identical births and identical draws, with different inherited
    load. It first showed up as `load_carried` and `mean_viability` diverging
    five years after the reload.
    """
    restored = load_world_save(build_world_save(world))
    a = World.__new__(World)                       # placate linters; unused
    del a

    for step in range(1, 26):
        left, right = world.step(), restored.step()
        differing = {k for k in left
                     if abs(float(left[k]) - float(right[k])) > 1e-12}
        assert not differing, \
            f"diverged {step} years after reload on {sorted(differing)}"
    assert [n.name for n in world.living] == [n.name for n in restored.living]


def test_the_spawn_counter_is_part_of_the_save(world):
    """Pinned explicitly, because it is invisible in every other check."""
    restored = load_world_save(build_world_save(world))
    assert (restored.rng.bit_generator.seed_seq.n_children_spawned
            == world.rng.bit_generator.seed_seq.n_children_spawned)
    assert restored.rng.bit_generator.state == world.rng.bit_generator.state


def test_a_save_preserves_the_snapshot_ring_and_its_cap(world):
    restored = load_world_save(build_world_save(world))
    assert len(restored.snapshots) == len(world.snapshots)
    assert restored.snapshots._frames.maxlen == world.snapshots._frames.maxlen
    assert restored.frame_at(world.tick)["tick"] == world.tick


def test_a_save_preserves_names_and_does_not_reissue_them(world):
    restored = load_world_save(build_world_save(world))
    assert restored._id == world._id
    assert restored._name_seq == world._name_seq
    for _ in range(3):
        restored.step()
    names = [n.name for n in restored.people.values()]
    assert len(names) == len(set(names)), "reloading reissued an existing name"


def test_a_save_preserves_the_pedigree(world):
    restored = load_world_save(build_world_save(world))
    for name in list(world.people)[:20]:
        assert restored.inbreeding_of(name) == pytest.approx(
            world.inbreeding_of(name))


def test_a_save_preserves_params_including_new_fields(world):
    restored = load_world_save(build_world_save(world))
    assert restored.params == world.params
    assert restored.params.fertility_schedule == world.params.fertility_schedule


def test_a_save_is_gzipped_json_and_costs_a_sane_amount_per_person():
    """
    Built on its own world, not the shared fixture, because other tests step
    that one forward and the size would drift with test order.

    Each person carries 2x2000 int8 of deleterious-load haplotypes (#31),
    2x505 of genome, plus methylation and X chromosomes. Base64 of the raw
    buffer is ~1.33 bytes per byte before gzip; a few kB each is expected and
    anything far above it means an array is being written as a JSON list of
    numbers, which is roughly 4x worse.
    """
    w = World(n_founders=12, seed=17)
    for _ in range(10):
        w.step()
    blob = build_world_save(w)
    assert blob[:2] == b"\x1f\x8b", "should be gzipped"
    payload = json.loads(gzip.decompress(blob).decode("utf-8"))
    assert payload["format"] == EX.SAVE_FORMAT_VERSION
    assert "manifest" in payload

    per_person = len(blob) / max(1, len(w.people))
    assert per_person < 15_000, f"{per_person:.0f} bytes per person is bloated"


def test_an_unknown_save_format_is_refused(world):
    payload = json.loads(gzip.decompress(build_world_save(world)).decode())
    payload["format"] = 999
    blob = gzip.compress(json.dumps(payload).encode())
    with pytest.raises(ValueError, match="unsupported save format"):
        load_world_save(blob)


def test_the_decoder_refuses_classes_from_outside_the_project():
    """A save file is data. Data must not be able to name an arbitrary
    importable class and have it constructed."""
    from simulation.worldsave import decode
    with pytest.raises(ValueError, match="refusing to load"):
        decode({"__dataclass__": "os.system"})
    with pytest.raises(ValueError, match="refusing to load"):
        decode({"__object__": "subprocess.Popen"})


def test_the_codec_round_trips_the_awkward_types():
    from simulation.worldsave import decode, encode
    from collections import deque
    cases = [
        np.arange(6, dtype=np.int8).reshape(2, 3),
        np.array([1.5, 2.5]),
        {"a": 1, "b": [1, 2, {"c": None}]},
        (1, "two", 3.0),
        {1, 2, 3},
        deque([1, 2, 3], maxlen=5),
    ]
    for case in cases:
        out = decode(encode(case))
        if isinstance(case, np.ndarray):
            assert np.array_equal(out, case) and out.dtype == case.dtype
        elif isinstance(case, deque):
            assert list(out) == list(case) and out.maxlen == case.maxlen
        else:
            assert out == case
            assert type(out) is type(case)


def test_a_save_of_an_empty_world_reloads():
    empty = World(n_founders=0, seed=3)
    restored = load_world_save(build_world_save(empty))
    assert len(restored.people) == 0
    restored.step()                     # and is still a working world
