"""
`bake_report.json` after the bake was split into batches.
=========================================================

The bake used to be one Blender process and the report was written once, at
the end, with a plain overwrite. Both of those changed together, and the
overwrite is the half that would have gone unnoticed: a batched run writes the
report once per batch, so the last batch would have left a file describing
twenty bodies out of six hundred and eighty five.

WHY THAT IS NOT COSMETIC. `bake_report.json` is the provenance record. The
per-body seconds and megabytes quoted in `REPORT.md` and in the paper are read
out of it, and the run it would then be describing is the SLOWEST tail of the
bake, because a Blender process slows as it goes. The number would not merely
be incomplete, it would be biased, and nothing about the file would look
wrong.

WHAT IS TESTED HERE. Only `_merge_report`, which is pure. The bake itself
needs Blender, an asset pack and an FBX writer, and `G5` in the final line
says plainly that conflating those two is the fake verification this project
has a rule about. So this file runs the SHIPPED function out of the shipped
source rather than a copy, for the reason `test_bake_channels.py` gives: a
reimplementation here would keep passing while the real rule was broken.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _merge_report():
    """Load `_merge_report` out of a module that imports `bpy` at the top."""
    src = (REPO / "mpfb" / "bake_bodies.py").read_text(encoding="utf-8")
    start = src.index("def _merge_report")
    end = src.index("def _record_statures")
    namespace = {"json": json}
    exec(compile(src[start:end], "bake_bodies.py", "exec"), namespace)
    return namespace["_merge_report"]


MERGE = _merge_report()


def _manifest(*stems):
    return {"bodies": [{"name": s.split("_")[0], "stem": s} for s in stems]}


def _fresh(stems, seconds=10.0):
    return {
        "blender": "4.4.3",
        "mpfb": "2.0.17",
        "subdiv_levels": 0,
        "seconds_total": seconds,
        "bodies": [{"stem": s, "authored_stature_m": 1.7, "seconds": 2.5}
                   for s in stems],
    }


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


# ----------------------------------------------------------------------
# the regression this exists for
# ----------------------------------------------------------------------

def test_a_second_batch_does_not_erase_the_first(tmp_path):
    """The whole point. Two batches, and the report describes all four bodies.

    Under the old plain overwrite this file would have held two.
    """
    manifest = _manifest("A_adult", "B_adult", "C_adult", "D_adult")
    path = tmp_path / "bake_report.json"

    first = MERGE(str(path), _fresh(["A_adult", "B_adult"], 5.0), manifest)
    _write(path, first)
    second = MERGE(str(path), _fresh(["C_adult", "D_adult"], 6.0), manifest)

    assert [b["stem"] for b in second["bodies"]] == [
        "A_adult", "B_adult", "C_adult", "D_adult"]
    assert second["batches"] == 2
    assert second["complete"] is True


def test_the_bodies_come_out_in_manifest_order_not_batch_order(tmp_path):
    """The file should read the same whether one process baked it or thirty
    five, or a reader comparing two runs is comparing two orderings."""
    manifest = _manifest("A_adult", "B_adult", "C_adult")
    path = tmp_path / "bake_report.json"

    _write(path, MERGE(str(path), _fresh(["C_adult"]), manifest))
    merged = MERGE(str(path), _fresh(["A_adult", "B_adult"]), manifest)

    assert [b["stem"] for b in merged["bodies"]] == [
        "A_adult", "B_adult", "C_adult"]


def test_seconds_total_accumulates_across_batches(tmp_path):
    manifest = _manifest("A_adult", "B_adult")
    path = tmp_path / "bake_report.json"

    _write(path, MERGE(str(path), _fresh(["A_adult"], 4.0), manifest))
    merged = MERGE(str(path), _fresh(["B_adult"], 6.5), manifest)

    assert merged["seconds_total"] == pytest.approx(10.5)


def test_a_rebaked_body_is_replaced_not_duplicated(tmp_path):
    """`--start` overlapping a batch that already ran is a normal recovery.
    The body must appear once, with the LATER measurement, because that is the
    FBX now on disk."""
    manifest = _manifest("A_adult")
    path = tmp_path / "bake_report.json"

    _write(path, MERGE(str(path), _fresh(["A_adult"]), manifest))
    again = _fresh(["A_adult"])
    again["bodies"][0]["authored_stature_m"] = 1.82
    merged = MERGE(str(path), again, manifest)

    assert len(merged["bodies"]) == 1
    assert merged["bodies"][0]["authored_stature_m"] == 1.82


# ----------------------------------------------------------------------
# the ways a merge could carry a lie forward
# ----------------------------------------------------------------------

def test_a_body_the_bundle_no_longer_has_is_dropped(tmp_path):
    """Re-exporting a different world into a directory that still holds an old
    report must not leave a villager in the provenance who is not in the
    bundle. This is the rule `_record_statures` already follows."""
    path = tmp_path / "bake_report.json"
    _write(path, _fresh(["GHOST_adult", "A_adult"]))

    merged = MERGE(str(path), _fresh(["B_adult"]), _manifest("A_adult", "B_adult"))

    stems = [b["stem"] for b in merged["bodies"]]
    assert "GHOST_adult" not in stems
    assert stems == ["A_adult", "B_adult"]


def test_complete_is_false_while_bodies_are_missing(tmp_path):
    """A partial bake is a supported state, so the report says so rather than
    looking like a whole one."""
    manifest = _manifest("A_adult", "B_adult", "C_adult")
    path = tmp_path / "bake_report.json"

    merged = MERGE(str(path), _fresh(["A_adult"]), manifest)

    assert merged["complete"] is False
    assert len(merged["bodies"]) == 1


def test_a_truncated_prior_report_does_not_fail_the_bake(tmp_path):
    """An interrupted write leaves half a JSON file. Losing the older half of
    the provenance is bad; refusing to record a bake that actually happened is
    worse, so the fresh results are kept and the unreadable half is dropped."""
    path = tmp_path / "bake_report.json"
    path.write_text('{"bodies": [{"stem": "A_adult"', encoding="utf-8")

    merged = MERGE(str(path), _fresh(["B_adult"]), _manifest("A_adult", "B_adult"))

    assert [b["stem"] for b in merged["bodies"]] == ["B_adult"]
    assert merged["batches"] == 1


def test_no_prior_report_is_the_ordinary_first_batch(tmp_path):
    path = tmp_path / "bake_report.json"
    merged = MERGE(str(path), _fresh(["A_adult"]), _manifest("A_adult"))

    assert merged["batches"] == 1
    assert merged["complete"] is True
    assert merged["blender"] == "4.4.3"
    assert merged["seconds_total"] == pytest.approx(10.0)
