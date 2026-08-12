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
        "people.csv", "history.csv", "pedigree.csv",
        "frames.csv", "demes.csv", "flows.csv", "events.csv",
        "manifest.json", "README.txt"}


def test_the_analysis_only_bundle_omits_the_frame_tables(world):
    """The longitudinal tables are much the largest part of a long run, so a
    caller who only wants the cross-section can say so -- and the older,
    smaller file set is still a tested promise rather than a memory."""
    blob = EX.build_csv_bundle(world, include_frames=False)
    assert set(zipfile.ZipFile(io.BytesIO(blob)).namelist()) == {
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


# ---------------------------------------------------------------------
# Provenance: which model version produced these numbers (session 16)
# ---------------------------------------------------------------------

def test_manifest_records_the_locus_catalogue(world):
    """Two exports with the same seed under different catalogues are
    different model versions, and nothing in the numbers themselves says
    so. The manifest has to.

    Asserted against whatever mode the process is actually running, not
    against "synthetic" -- the point is that the manifest TRACKS the
    catalogue, and hardcoding one mode would make this test fail under
    the very flag it exists to describe."""
    m = EX.manifest(world)
    from health_engine.loci import CATALOGUE_MODE
    assert m["catalogue"] == CATALOGUE_MODE
    assert CATALOGUE_MODE in ("synthetic", "empirical")


def test_readme_and_caveats_cover_the_new_columns(world):
    """A named diagnosis and a purging series are both easy to over-read.
    The bundle must ship the caveat next to the data, not only in the
    report."""
    m = EX.manifest(world)
    caveats = " ".join(m["caveats"]).lower()
    assert "mendelian_diagnoses" in caveats
    assert "cystic fibrosis" in caveats          # the documented misfit
    assert "lethal_equivalents" in caveats
    assert "purging" in caveats

    blob = EX.build_csv_bundle(world)
    readme = zipfile.ZipFile(io.BytesIO(blob)).read("README.txt").decode()
    assert "mendelian_carrier_of" in readme
    assert "lethal_equivalents" in readme


# =====================================================================
# Longitudinal tables -- the world-viewer feed (UNITY_PLAN.md stage 1)
# =====================================================================
# These are a pure re-serialisation of the snapshot ring. The standard of
# proof is therefore not "are the numbers right" -- snapshots.py owns that --
# but "did anything get invented, dropped, or silently reshaped on the way
# out", plus the honest limits being stated where a consumer will see them.


@pytest.fixture(scope="module")
def spatial_world():
    """Three demes with migration, so flows.csv is not trivially empty."""
    w = World(n_founders=16, seed=5,
              params=DemographyParams(n_demes=3, migration_rate=0.10))
    for _ in range(25):
        w.step()
    return w


def test_frames_hold_exactly_the_living_of_every_retained_year(spatial_world):
    """One row per living person per frame -- nobody invented, nobody lost."""
    rows = EX.frame_rows(spatial_world)
    assert len(rows) == sum(f["n_alive"] for f in spatial_world.snapshots)

    per_tick = {}
    for r in rows:
        per_tick[r["tick"]] = per_tick.get(r["tick"], 0) + 1
    for frame in spatial_world.snapshots:
        assert per_tick[frame["tick"]] == frame["n_alive"]


def test_the_frame_schema_matches_what_snapshots_actually_emits(spatial_world):
    """FRAME_COLUMNS is declared, not derived, so that an empty table still
    writes a header. That only stays true if the declaration keeps up with
    snapshots.py -- this is the test that notices when it does not."""
    emitted = list(EX.frame_rows(spatial_world)[0].keys())
    assert emitted == EX.FRAME_COLUMNS, (
        "simulation/snapshots.py changed its per-person fields; update "
        "export.FRAME_COLUMNS and bump BUNDLE_SCHEMA if a column changed "
        "meaning.")

    demes = list(EX.deme_frame_rows(spatial_world)[0].keys())
    assert demes == EX.DEME_COLUMNS


def test_frames_carry_age_expressed_stature_not_the_mature_value(spatial_world):
    """A child must not be exported adult-sized. `people.csv` carries the
    mature `trait_height_cm`; the frame carries what the body actually is."""
    growing = [r for r in EX.frame_rows(spatial_world) if r["age"] < 12]
    assert growing, "no children in the run -- test proves nothing"
    people = {r["name"]: r for r in EX.people_rows(spatial_world)}
    assert any(r["height"] < people[r["name"]]["trait_height_cm"] - 1.0
               for r in growing)


def test_flows_are_present_with_structure_and_empty_without(spatial_world, world):
    """Migration routes exist only when there is somewhere to migrate. The
    single-deme default has none, and that is a correct empty, not a bug."""
    assert EX.flow_rows(spatial_world), "3 demes with migration produced no flows"
    assert EX.flow_rows(world) == []


def test_an_empty_table_still_writes_its_header(world):
    """A zero-byte file is indistinguishable from a truncated download. A
    consumer must be able to read 'zero rows' instead of guessing."""
    files = EX._bundle_files(world)
    for name, columns in (("flows.csv", EX.FLOW_COLUMNS),
                          ("events.csv", EX.EVENT_COLUMNS)):
        text = files[name]
        assert text, f"{name} is empty with no header"
        assert text.splitlines()[0] == ",".join(columns)


def test_the_directory_export_is_identical_to_the_zip(spatial_world, tmp_path):
    """One definition, two containers. If these can drift, a viewer and an
    analysis download can disagree about the same run."""
    out = EX.export_world_dir(spatial_world, tmp_path / "w", note="pytest")
    blob = zipfile.ZipFile(io.BytesIO(
        EX.build_csv_bundle(spatial_world, note="pytest")))

    on_disk = {p.name for p in out.iterdir()}
    assert on_disk == set(blob.namelist())
    for name in on_disk:
        if name == "manifest.json":
            continue                      # carries an export timestamp
        assert (out / name).read_text(encoding="utf-8") == \
            blob.read(name).decode("utf-8"), f"{name} differs"


def test_the_directory_export_does_not_translate_line_endings(spatial_world, tmp_path):
    """Written with newline="" so the same world exported on Windows and
    Linux is byte-identical. Without it the text layer inserts CRLF."""
    out = EX.export_world_dir(spatial_world, tmp_path / "w")
    assert b"\r\n" not in (out / "frames.csv").read_bytes()


def test_the_manifest_says_what_the_frames_cover(spatial_world):
    """The snapshot ring is capped, so a long run silently loses its earliest
    years. A viewer that assumed year 0 would mislabel its own timeline."""
    m = EX.manifest(spatial_world)["frames"]
    assert m["n_frames"] == len(spatial_world.snapshots)
    assert m["first_tick"] == spatial_world.snapshots.first_tick
    assert m["last_tick"] == spatial_world.snapshots.last_tick
    assert m["truncated"] is False          # 25 ticks, cap is 600
    assert m["max_frames"] == 600


def test_truncation_is_reported_when_the_ring_overflows():
    """Forced with a tiny cap rather than by running 600 years. The flag must
    be true exactly when early frames were dropped."""
    from simulation.snapshots import SnapshotBuffer
    w = World(n_founders=10, seed=3)
    w.snapshots = SnapshotBuffer(max_frames=5)
    for _ in range(20):
        w.step()

    m = EX.manifest(w)["frames"]
    assert m["truncated"] is True
    assert m["n_frames"] == 5
    assert m["first_tick"] > 0
    assert EX.frame_rows(w)[0]["tick"] == m["first_tick"]


def test_the_readme_states_the_frame_tables_limits(spatial_world):
    """The caveats must ship next to the data, not only in the plan."""
    readme = EX._readme(spatial_world).lower()
    assert "frames.csv" in readme
    assert "living only" in readme            # a death is a disappearance
    assert "truncated" in readme              # the ring cap
    assert "not genomes" in readme            # no dead person's genetics
    assert "expressed at that age" in readme  # not mature stature


def test_the_bundle_declares_a_schema_version(spatial_world):
    """A consumer outside Python cannot notice a silently reshaped table."""
    assert EX.manifest(spatial_world)["bundle_schema"] == EX.BUNDLE_SCHEMA


def test_exporting_frames_does_not_mutate_the_world(spatial_world):
    """The whole point: reading the ring is read-only."""
    before = (spatial_world.tick, len(spatial_world.people),
              len(spatial_world.snapshots), spatial_world.rng.bit_generator.state)
    EX.frame_rows(spatial_world)
    EX.deme_frame_rows(spatial_world)
    EX.flow_rows(spatial_world)
    after = (spatial_world.tick, len(spatial_world.people),
             len(spatial_world.snapshots), spatial_world.rng.bit_generator.state)
    assert before == after


def test_the_directory_export_survives_an_empty_and_an_extinct_world(tmp_path):
    """A world with no one in it must still produce a readable bundle: a
    viewer should render an empty village, not fail to parse. This is the
    case the header-on-empty-tables rule exists for."""
    empty = World(n_founders=0, seed=1)
    out = EX.export_world_dir(empty, tmp_path / "empty")
    frames = (out / "frames.csv").read_text(encoding="utf-8")
    assert frames.splitlines() == [",".join(EX.FRAME_COLUMNS)]   # header, no rows

    extinct = World(n_founders=6, seed=2)
    for _ in range(5):
        extinct.step()
    extinct.living.clear()
    out = EX.export_world_dir(extinct, tmp_path / "extinct")
    # the dead are gone from the live frame but their earlier years remain
    rows = (out / "frames.csv").read_text(encoding="utf-8").splitlines()
    assert len(rows) > 1
    assert EX.manifest(extinct)["frames"]["n_frames"] == len(extinct.snapshots)
