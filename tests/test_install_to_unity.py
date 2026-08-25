"""
Installing an exported bundle into the consuming Unity project.
===============================================================

The gap this closes made a whole session's work invisible. The consuming
project references the package by `file:` path, and **a package reference
carries CODE ONLY**: new C# is live after a refresh, but FBX bodies and world
bundles are assets and travel by nothing. In session 23 a pipeline was built,
verified in the throwaway `unity/test-project`, and reported as working while
the owner's editor showed no change at all.

WHAT IS TESTED. Not that `shutil.copytree` copies; that is the standard
library. The parts with logic in them are the REFUSALS and the ADDITIVE
default:

  * a bundle with no baked FBX must be refused with the command that bakes
    them, because the alternative is a silent install of nothing;
  * installing world B must not remove world A's bodies, because the FBX pool
    is shared and `--clean-bodies` is the opt-in that says otherwise;
  * and the FBX must NOT be copied into StreamingAssets as well, or every
    build carries a second copy of a payload measured at ~1.75 MB a body.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from install_to_unity import check_bundle, check_project, install


def make_project(tmp_path: Path) -> Path:
    project = tmp_path / "UnityProject"
    (project / "Assets").mkdir(parents=True)
    (project / "Packages").mkdir(parents=True)
    (project / "Packages" / "manifest.json").write_text("{}", encoding="utf-8")
    return project


def make_bundle(tmp_path: Path, name: str, people, staged=True,
                bake=True) -> Path:
    bundle = tmp_path / name
    (bundle / "bodies" / "fbx").mkdir(parents=True)
    (bundle / "manifest.json").write_text('{"schema":1}', encoding="utf-8")
    (bundle / "people.csv").write_text("name\n", encoding="utf-8")

    entries = []
    for person, stage in people:
        stem = f"{person}_{stage}" if staged else person
        entries.append({"name": person, "key": f"{person}@{stage}" if staged
                        else person, "life_stage": stage if staged else "",
                        "stem": stem, "mhm": f"{stem}.mhm", "age": 30.0})
        (bundle / "bodies" / f"{stem}.mhm").write_text("x", encoding="utf-8")
        if bake:
            (bundle / "bodies" / "fbx" / f"{stem}.fbx").write_bytes(b"FBX")
    (bundle / "bodies" / "bodies.json").write_text(json.dumps({
        "bodies_schema": 2, "staged": staged, "count": len(entries),
        "people": len({p for p, _ in people}), "never_rendered": [],
        "bodies": entries}), encoding="utf-8")
    return bundle


# ----------------------------------------------------------------------
# refusals
# ----------------------------------------------------------------------

def test_a_path_that_is_not_a_unity_project_is_refused(tmp_path):
    """A few hundred megabytes into a mistyped path is silent and slow to
    notice, so the shape of the target is checked before anything is written."""
    (tmp_path / "random").mkdir()
    with pytest.raises(SystemExit, match="not a Unity project"):
        check_project(tmp_path / "random")


def test_a_project_with_assets_but_no_package_manifest_is_refused(tmp_path):
    (tmp_path / "half" / "Assets").mkdir(parents=True)
    with pytest.raises(SystemExit, match="manifest.json"):
        check_project(tmp_path / "half")


def test_an_unbaked_bundle_is_refused_and_names_the_bake_command(tmp_path):
    """THE IMPORTANT REFUSAL. The `.mhm` files exist and the manifest is
    complete, so the bundle looks finished; only the FBX are missing. Copying
    it installs a world in which every villager falls back to the shared mesh,
    which reads as "the bodies do not work" rather than "the bake did not run".
    """
    bundle = make_bundle(tmp_path, "w", [("A", "adult")], bake=False)
    with pytest.raises(SystemExit) as exc:
        check_bundle(bundle)
    assert "bake_bodies.py" in str(exc.value), (
        "the refusal must say how to fix it, not just that it failed")


def test_a_bundle_with_no_bodies_at_all_names_the_export_command(tmp_path):
    bundle = tmp_path / "w"
    bundle.mkdir()
    (bundle / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="export_bodies.py|Export for Unity"):
        check_bundle(bundle)


def test_a_directory_that_is_not_a_bundle_is_refused(tmp_path):
    (tmp_path / "nope").mkdir()
    with pytest.raises(SystemExit, match="not an exported bundle"):
        check_bundle(tmp_path / "nope")


def test_a_partial_bake_is_allowed_but_reported(tmp_path, capsys):
    """Legitimate: `bodies.json` names every body whether or not its FBX
    exists, and a villager with no body draws on the shared mesh. Refusing
    would make a cancelled bake unrecoverable."""
    bundle = make_bundle(tmp_path, "w", [("A", "adult"), ("B", "child")])
    (bundle / "bodies" / "fbx" / "B_child.fbx").unlink()
    check_bundle(bundle)
    assert "1 of 2" in capsys.readouterr().out


# ----------------------------------------------------------------------
# the additive default
# ----------------------------------------------------------------------

def test_installing_a_second_world_keeps_the_first_worlds_bodies(tmp_path):
    """The FBX pool is SHARED and flat. Stems are unique per world, so two
    worlds coexist; quietly emptying the pool would break a bundle the caller
    was not thinking about."""
    project = make_project(tmp_path)
    a = make_bundle(tmp_path, "world-a", [("A", "adult")])
    b = make_bundle(tmp_path, "world-b", [("B", "child")])

    install(a, project)
    result = install(b, project)

    pool = project / "Assets" / "Resources" / "extnpc" / "bodies"
    assert (pool / "A_adult.fbx").exists(), "world A's body was removed"
    assert (pool / "B_child.fbx").exists()
    assert result["bodies_present"] == 2
    assert result["bodies_removed"] == 0


def test_clean_bodies_empties_the_pool_and_says_how_many(tmp_path):
    project = make_project(tmp_path)
    install(make_bundle(tmp_path, "world-a", [("A", "adult")]), project)
    result = install(make_bundle(tmp_path, "world-b", [("B", "child")]),
                     project, clean_bodies=True)

    pool = project / "Assets" / "Resources" / "extnpc" / "bodies"
    assert not (pool / "A_adult.fbx").exists()
    assert (pool / "B_child.fbx").exists()
    assert result["bodies_removed"] == 1


def test_each_world_keeps_its_own_manifest_in_its_own_bundle(tmp_path):
    """The loader reads the body manifest from THE BUNDLE, not from Resources.
    One shared manifest would mean installing world B silently repointed world
    A's names at world B's stems."""
    project = make_project(tmp_path)
    install(make_bundle(tmp_path, "world-a", [("A", "adult")]), project)
    install(make_bundle(tmp_path, "world-b", [("B", "child")]), project)

    sa = project / "Assets" / "StreamingAssets" / "extnpc"
    for world, person in (("world-a", "A"), ("world-b", "B")):
        manifest = json.loads(
            (sa / world / "bodies" / "bodies.json").read_text(encoding="utf-8"))
        assert [b["name"] for b in manifest["bodies"]] == [person]


# ----------------------------------------------------------------------
# what must NOT be copied
# ----------------------------------------------------------------------

def test_the_fbx_are_not_also_copied_into_streamingassets(tmp_path):
    """They live in Resources. A second copy here would double a payload of
    about 1.75 MB a body and ship it into every build."""
    project = make_project(tmp_path)
    bundle = make_bundle(tmp_path, "w", [("A", "adult"), ("A", "child")])
    install(bundle, project)

    dest = project / "Assets" / "StreamingAssets" / "extnpc" / "w"
    assert list(dest.rglob("*.fbx")) == []
    assert list(dest.rglob("*.mhm")) == [], "the .mhm sources are build input"
    assert (dest / "bodies" / "bodies.json").exists()
    assert (dest / "manifest.json").exists()


def test_reinstalling_the_same_world_replaces_rather_than_merges(tmp_path):
    """A rename between exports would otherwise leave a file no manifest names,
    which is invisible and inflates nothing but the next person's confusion."""
    project = make_project(tmp_path)
    install(make_bundle(tmp_path, "w", [("A", "adult")]), project)

    stale = (project / "Assets" / "StreamingAssets" / "extnpc" / "w"
             / "gone.csv")
    stale.write_text("x", encoding="utf-8")
    install(make_bundle(tmp_path / "second", "w", [("A", "adult")]), project)
    assert not stale.exists()


def test_the_result_reports_bodies_and_people_separately(tmp_path):
    """They differ in staged mode, and a reader comparing either against the
    village headcount needs to know which one they are holding."""
    project = make_project(tmp_path)
    bundle = make_bundle(tmp_path, "w",
                         [("A", "infant"), ("A", "child"), ("A", "adult")])
    result = install(bundle, project)
    assert result["staged"] is True
    assert result["bodies_copied"] == 3
    assert result["people"] == 1
