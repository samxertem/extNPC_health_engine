"""
The Unity export script's shock scheduling.
===========================================

`events.csv` has been in the bundle since Stage 1 and has been EMPTY in every
bundle ever exported. Not because nothing interesting happened -- because the
only thing that appends to `world.event_log` is a shock draining out of
`world.shock_queue` (`world.py:224`), and until session 19 the only thing that
could fill that queue was a dashboard button. A batch export had no way to
schedule one.

That made the viewer's timeline markers a feature nothing could exercise, and
made an empty `events.csv` indistinguishable from a broken one.

`export_for_unity.py --shock KIND@YEAR[:MAG]` closes that. It queues exactly
what the dashboard queues, through the same `World.queue_shock`; no new
mechanism, no new randomness, and a run without the flag is byte-for-byte the
run it was before (which is what keeps `tests/test_export_golden.py` looking at
the same world).

What is tested here is the part with logic in it: the spec parser, and the
claim that a shock lands in the year the caller NAMED.
"""

from __future__ import annotations

import csv
import sys
import warnings
from pathlib import Path
from unittest import mock

import pytest

warnings.filterwarnings("ignore")

from export_for_unity import _parse_shocks, main
from simulation import export as EX


# ---------------------------------------------------------------------
# the spec parser
# ---------------------------------------------------------------------

def test_a_shock_spec_parses_into_a_year_a_kind_and_a_magnitude():
    assert _parse_shocks(["plague@30"]) == {30: ("plague", 0.6)}
    assert _parse_shocks(["famine@55:0.8"]) == {55: ("famine", 0.8)}
    assert _parse_shocks(["PLAGUE@7"]) == {7: ("plague", 0.6)}, (
        "the kind should be case-insensitive; a capitalised KIND is a typo "
        "that should not need a second attempt")


def test_several_shocks_can_be_scheduled():
    assert _parse_shocks(["plague@30", "famine@55:0.8", "bottleneck@70"]) == {
        30: ("plague", 0.6), 55: ("famine", 0.8), 70: ("bottleneck", 0.6)}


def test_no_shocks_is_the_default_and_produces_no_events():
    assert _parse_shocks([]) == {}


@pytest.mark.parametrize("spec", ["plague", "plague@", "plague@x", "@30",
                                  "plague@30:abc"])
def test_a_malformed_spec_is_refused_rather_than_guessed_at(spec):
    with pytest.raises(SystemExit):
        _parse_shocks([spec])


def test_an_unknown_kind_is_refused():
    """The engine ignores a kind it does not know -- `step()` matches on the
    string -- so a typo would produce a marked year in which nothing happened.
    Better to fail at the command line."""
    with pytest.raises(SystemExit):
        _parse_shocks(["plage@30"])


def test_two_shocks_in_one_year_are_refused():
    """The queue drains ONE shock per tick, so a second one aimed at the same
    year silently lands in the next -- and the timeline would mark a year
    nothing was asked to happen in."""
    with pytest.raises(SystemExit):
        _parse_shocks(["plague@30", "famine@30"])


def test_year_zero_is_refused():
    """`step()` increments the tick before draining, so the earliest year a
    shock can land in is 1. Accepting 0 would silently shift it."""
    with pytest.raises(SystemExit):
        _parse_shocks(["plague@0"])


# ---------------------------------------------------------------------
# the claim that matters: the shock lands in the year the caller named
# ---------------------------------------------------------------------

def _export(tmp_path, *args) -> Path:
    """Run the SCRIPT, not a copy of its loop.

    The first version of these tests rebuilt `main`'s year loop here and
    asserted against that -- which would have passed happily while the script
    itself queued a shock a year early, because the thing under test was the
    test's own arithmetic. Driving `main()` through argv is slower by a few
    seconds and is the only version that can fail for the right reason.
    """
    out = tmp_path / "bundle"
    argv = ["export_for_unity.py", "--years", "12", "--founders", "10",
            "--seed", "5", "--out", str(out)] + list(args)
    with mock.patch.object(sys, "argv", argv):
        main()
    return out


def _events(bundle: Path):
    rows = list(csv.DictReader((bundle / "events.csv").read_text(
        encoding="utf-8").splitlines()))
    return [(int(r["tick"]), r["kind"], r["label"]) for r in rows]


def test_a_scheduled_shock_lands_in_the_year_it_was_asked_for(tmp_path):
    """
    The claim the option is worth having.

    `World.step()` increments the tick and THEN drains the queue, so the
    queueing has to happen on the iteration before the target year. Off by one
    here means the timeline marks a year in which nothing was asked to happen,
    and nothing else in the pipeline would notice.
    """
    bundle = _export(tmp_path, "--shock", "plague@5", "--shock", "famine@9:0.7")
    got = [(tick, kind) for tick, kind, _ in _events(bundle)]
    assert got == [(5, "plague"), (9, "famine")], (
        f"shocks landed at {got}; they were scheduled for years 5 and 9")


def test_the_exported_events_table_has_the_schema_the_viewer_reads(tmp_path):
    bundle = _export(tmp_path, "--shock", "bottleneck@4:0.5")
    header = (bundle / "events.csv").read_text(
        encoding="utf-8").splitlines()[0].split(",")
    assert header == EX.EVENT_COLUMNS

    events = _events(bundle)
    assert len(events) == 1
    tick, kind, label = events[0]
    assert (tick, kind) == (4, "bottleneck")
    assert label, "an event with no label marks a year and says nothing"


def test_a_run_with_no_shocks_writes_a_header_and_no_rows(tmp_path):
    """
    The state every previously exported bundle was in, pinned so the claim in
    REPORT.md session 19 stays checkable: an empty events.csv was CORRECT, not
    broken -- and it still carries its header, so a consumer reads "zero
    events" rather than guessing at a zero-byte file.
    """
    bundle = _export(tmp_path)
    text = (bundle / "events.csv").read_text(encoding="utf-8")
    assert text.splitlines()[0].split(",") == EX.EVENT_COLUMNS
    assert _events(bundle) == []
