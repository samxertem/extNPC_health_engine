"""
The dashboard/Unity sync file (item N1).

WHAT IS ACTUALLY AT RISK HERE. Not the happy path, which is four lines of
json.dump. The failure modes are a reader landing in the middle of a write, a
writer fighting its own echo, and one side taking the other down by raising in
a callback that also advances the world. Those are what these tests are about.
"""

from __future__ import annotations

import json
import os
import threading

import pytest

from dashboard.session_sync import (SCHEMA, SOURCE_DASHBOARD, SOURCE_UNITY,
                                    SessionState, SyncClient, default_path,
                                    read_state, write_state)


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "nested" / "session.json")


# ----------------------------------------------------------------------
# the round trip
# ----------------------------------------------------------------------

def test_a_state_survives_the_round_trip(path):
    written = SessionState(selected="Kaya-32", year=110, world="village",
                           source=SOURCE_DASHBOARD, seq=3)
    assert write_state(written, path)

    got = read_state(path)
    assert got.selected == "Kaya-32"
    assert got.year == 110
    assert got.world == "village"
    assert got.source == SOURCE_DASHBOARD
    assert got.seq == 3


def test_the_parent_directory_is_created(path):
    assert not os.path.isdir(os.path.dirname(path))
    assert write_state(SessionState(selected="A"), path)
    assert os.path.isfile(path)


def test_live_is_none_and_stays_none(path):
    """`year=None` means "follow the newest year" and is not the same as the
    newest year's number. Collapsing it would turn "follow the front" into
    "hold at 110", which is a different intention and stops following."""
    write_state(SessionState(selected="A", year=None), path)
    assert read_state(path).year is None


# ----------------------------------------------------------------------
# never raising, which is the contract
# ----------------------------------------------------------------------

def test_a_missing_file_is_no_news_rather_than_an_error(path):
    assert read_state(path) is None


def test_a_truncated_file_is_no_news(path):
    """The case a polling reader WILL hit if writes are not atomic."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('{"schema": 1, "selected": "Kay')
    assert read_state(path) is None


def test_a_file_that_is_not_an_object_is_no_news(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([1, 2, 3], fh)
    assert read_state(path) is None


def test_a_future_schema_is_ignored_rather_than_guessed_at(path):
    """Reading an unknown layout as if it were this one is how two versions of
    the same tool silently disagree about which villager is selected."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"schema": SCHEMA + 1, "selected": "Kaya-32"}, fh)
    assert read_state(path) is None


def test_writing_somewhere_impossible_returns_false(tmp_path):
    # A path whose parent is a FILE cannot be created as a directory.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    assert write_state(SessionState(selected="A"),
                       str(blocker / "sub" / "session.json")) is False


def test_a_failed_write_leaves_no_temp_file_behind(tmp_path, monkeypatch):
    """This runs on a timer, so a temp file per failure is a slow leak in a
    directory that lives as long as the user's home."""
    target = str(tmp_path / "session.json")

    def boom(*args, **kwargs):
        raise OSError("no")

    monkeypatch.setattr("dashboard.session_sync.os.replace", boom)
    assert write_state(SessionState(selected="A"), target) is False

    leftovers = [p for p in os.listdir(tmp_path) if p.startswith(".session-")]
    assert leftovers == [], leftovers


# ----------------------------------------------------------------------
# atomicity
# ----------------------------------------------------------------------

def test_an_interrupted_write_leaves_the_previous_payload_intact(path, monkeypatch):
    """The real point of the temp-and-replace, tested deterministically.

    THE FIRST VERSION OF THIS TEST PROVED NOTHING. It ran a reader thread
    against a writer and asserted that every value read was one that had been
    written. It passed with the atomicity REMOVED, because a torn read raises
    inside json.load, `read_state` turns that into None, and the test skipped
    Nones. It was measuring its own tolerance.

    The property that actually distinguishes the two implementations is this
    one: if a write is interrupted, the target must still hold the last
    complete payload. With temp-and-replace the damage lands on the temp file,
    which is removed. With a plain write the target itself is truncated and the
    previous state is gone.
    """
    good = SessionState(selected="Kaya-32", year=110, world="village")
    assert write_state(good, path)

    calls = {"n": 0}
    real_dump = json.dump

    def dump_then_die(obj, fh, **kwargs):
        calls["n"] += 1
        fh.write('{"schema": 1, "selec')      # a plausible partial document
        raise OSError("disk went away mid-write")

    monkeypatch.setattr("dashboard.session_sync.json.dump", dump_then_die)
    assert write_state(SessionState(selected="doomed", year=1), path) is False
    assert calls["n"] == 1, "the sabotage did not run, so this proved nothing"

    monkeypatch.undo()
    survivor = read_state(path)
    assert survivor is not None, "the interrupted write destroyed the payload"
    assert survivor.selected == "Kaya-32"
    assert survivor.year == 110


def test_a_polling_reader_only_ever_sees_values_that_were_written(path):
    """A concurrency smoke test, and deliberately a weak one.

    It cannot distinguish atomic from non-atomic writes: a torn read fails to
    parse and arrives as None, which is indistinguishable from "no news". The
    deterministic test above is what pins atomicity. This one is here to catch
    a reader returning a value nobody ever wrote, which no amount of
    single-threaded testing would find.
    """
    write_state(SessionState(selected="start", year=0, world="village"), path)

    stop = threading.Event()
    seen = []
    errors = []

    def reader():
        while not stop.is_set():
            try:
                state = read_state(path)
            except Exception as exc:          # pragma: no cover
                errors.append(exc)
                return
            if state is not None:
                seen.append(state.selected)

    thread = threading.Thread(target=reader)
    thread.start()
    try:
        for i in range(200):
            write_state(SessionState(selected="villager-%d" % i, year=i,
                                     world="village"), path)
    finally:
        stop.set()
        thread.join(timeout=5)

    assert not errors, errors
    assert seen, "the reader never saw anything, so this proved nothing"
    allowed = {"start"} | {"villager-%d" % i for i in range(200)}
    assert set(seen) <= allowed


# ----------------------------------------------------------------------
# the echo problem
# ----------------------------------------------------------------------

def test_a_client_does_not_hear_its_own_writes(path):
    """Without this the two viewers fight the user's input: the dashboard
    publishes a selection, reads it back, applies it, publishes again."""
    dash = SyncClient(SOURCE_DASHBOARD, world="village", path=path)
    assert dash.publish("Kaya-32", 110)
    assert dash.poll() is None


def test_a_restarted_client_does_not_hear_its_own_previous_process(path):
    """The case that isolates the `source` check from the `seq` check.

    Within one process, `publish` records the sequence it just wrote, so the
    seq bookkeeping alone is enough to swallow the echo, and a test using one
    client passes with the source check DELETED. Restarting is different: the
    new client starts at seq 0 having never seen anything, and the file still
    holds the old process's payload. Without the source check it would read
    that back and apply it as if the other side had said it, so a dashboard
    restart would silently re-select whatever was selected before the crash.
    """
    first = SyncClient(SOURCE_DASHBOARD, world="village", path=path)
    first.publish("Kaya-32", 110)

    restarted = SyncClient(SOURCE_DASHBOARD, world="village", path=path)
    assert restarted.poll() is None

    # And the other side is still heard normally after the restart.
    unity = SyncClient(SOURCE_UNITY, world="village", path=path)
    unity.publish("Ines-30", 40)
    heard = restarted.poll()
    assert heard is not None and heard.selected == "Ines-30"


def test_the_other_side_is_heard(path):
    dash = SyncClient(SOURCE_DASHBOARD, world="village", path=path)
    unity = SyncClient(SOURCE_UNITY, world="village", path=path)

    dash.publish("Kaya-32", 110)
    heard = unity.poll()
    assert heard is not None
    assert heard.selected == "Kaya-32"
    assert heard.year == 110


def test_the_same_message_is_only_news_once(path):
    """A poll on a timer must not re-apply a selection the user has since
    changed locally; that would make the other side's stale value keep
    snapping the view back."""
    dash = SyncClient(SOURCE_DASHBOARD, world="village", path=path)
    unity = SyncClient(SOURCE_UNITY, world="village", path=path)

    dash.publish("Kaya-32", 110)
    assert unity.poll() is not None
    assert unity.poll() is None
    assert unity.poll() is None


def test_two_writes_in_the_same_millisecond_are_two_messages(path):
    """Why `seq` exists at all rather than leaning on the timestamp: two writes
    inside one clock tick are indistinguishable by time, and on Windows the
    clock granularity is coarse enough for that to be common."""
    dash = SyncClient(SOURCE_DASHBOARD, world="village", path=path)
    unity = SyncClient(SOURCE_UNITY, world="village", path=path)

    dash.publish("A", 1)
    first = unity.poll()
    dash.publish("B", 1)
    second = unity.poll()

    assert first.selected == "A"
    assert second is not None and second.selected == "B"


def test_a_payload_for_another_world_is_ignored(path):
    """A dashboard on a different world must not drag the viewer to a villager
    who does not exist in the one on screen."""
    other = SyncClient(SOURCE_DASHBOARD, world="onedeme", path=path)
    unity = SyncClient(SOURCE_UNITY, world="village", path=path)

    other.publish("Someone-Else", 40)
    assert unity.poll() is None


def test_an_unstated_world_is_accepted(path):
    """Empty means "not stated" so a caller can opt out rather than being
    forced to name a world it does not know."""
    anon = SyncClient(SOURCE_DASHBOARD, world="", path=path)
    unity = SyncClient(SOURCE_UNITY, world="village", path=path)

    anon.publish("Kaya-32", 110)
    assert unity.poll() is not None


def test_selection_and_year_travel_together(path):
    """FINAL_LINE N1 makes these one mechanism on purpose: they change together
    when you click a villager in a past year, and two files could disagree."""
    dash = SyncClient(SOURCE_DASHBOARD, world="village", path=path)
    unity = SyncClient(SOURCE_UNITY, world="village", path=path)

    dash.publish("Ines-30", 42)
    heard = unity.poll()
    assert (heard.selected, heard.year) == ("Ines-30", 42)


def test_clearing_a_selection_is_a_message_not_a_silence(path):
    """Deselecting has to travel. If None meant "no news" the other side would
    keep the old villager highlighted forever."""
    dash = SyncClient(SOURCE_DASHBOARD, world="village", path=path)
    unity = SyncClient(SOURCE_UNITY, world="village", path=path)

    dash.publish("Kaya-32", 110)
    unity.poll()
    dash.publish(None, 110)

    heard = unity.poll()
    assert heard is not None
    assert heard.selected is None


# ----------------------------------------------------------------------
# the format both sides have to agree on
# ----------------------------------------------------------------------

def test_a_unity_written_payload_is_readable(path):
    """Byte for byte what `SessionSync.Publish` produces on the C# side.

    THERE ARE TWO IMPLEMENTATIONS OF THIS FORMAT and nothing but agreement
    keeps them talking. A field renamed on one side does not raise: it means
    the other side never hears anything, which looks exactly like "the user has
    not clicked yet". So each side parses a payload the other one documents,
    and `SessionSyncTests.APythonWrittenPayloadIsReadable` is this test facing
    the other way.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            '{\n'
            '  "schema": 1,\n'
            '  "selected": "Kaya-32",\n'
            '  "year": 110,\n'
            '  "world": "village",\n'
            '  "source": "unity",\n'
            '  "seq": 4,\n'
            '  "written_ms": 1787568000000\n'
            '}'
        )

    dash = SyncClient(SOURCE_DASHBOARD, world="village", path=path)
    heard = dash.poll()
    assert heard is not None, "the dashboard cannot hear the viewer"
    assert heard.selected == "Kaya-32"
    assert heard.year == 110
    assert heard.world == "village"
    assert heard.seq == 4


def test_the_field_names_are_pinned(path):
    """Renaming a field here is a silent break on the other side, so the names
    are asserted as literals rather than left to the round trip, which would
    happily agree with itself."""
    write_state(SessionState(selected="A", year=1, world="village",
                             source=SOURCE_DASHBOARD, seq=1), path)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    for field in ("schema", "selected", "year", "world", "source", "seq"):
        assert '"%s"' % field in text, field


# ----------------------------------------------------------------------
# where the file lives
# ----------------------------------------------------------------------

def test_the_default_path_is_outside_both_trees(monkeypatch):
    """The bundle Unity reads is a COPY of the exported one, so a file inside
    it is not shared. The default has to be somewhere neither side owns."""
    monkeypatch.delenv("EXTNPC_SESSION_FILE", raising=False)
    target = default_path()
    assert "outputs" not in target
    assert "StreamingAssets" not in target
    assert target.endswith("session.json")


def test_the_path_is_overridable(monkeypatch, tmp_path):
    monkeypatch.setenv("EXTNPC_SESSION_FILE", str(tmp_path / "elsewhere.json"))
    assert default_path() == str(tmp_path / "elsewhere.json")


def test_hearing_a_state_counts_as_having_published_it(path):
    """Applying an incoming state must not cause it to be sent back.

    Without this the caller applies what it heard, notices on its next tick
    that its state differs from what it last published, and republishes it. The
    other side drops the duplicate, so nothing hangs; the symptom is two
    processes writing the same file at each other a few times a second.
    """
    dash = SyncClient(SOURCE_DASHBOARD, world="village", path=path)
    unity = SyncClient(SOURCE_UNITY, world="village", path=path)

    unity.publish("Kaya-32", 110)
    heard = dash.poll()
    assert heard is not None

    assert dash.last_published == ("Kaya-32", 110)


def test_publishing_nothing_selected_still_counts_as_published(path):
    """(None, None) is the dashboard's opening state: nobody selected, following
    the newest year. If the "have I published?" sentinel were None, that state
    would be republished on every single tick forever."""
    dash = SyncClient(SOURCE_DASHBOARD, world="village", path=path)
    assert dash.last_published != (None, None)

    dash.publish(None, None)
    assert dash.last_published == (None, None)


def test_a_two_way_conversation_does_not_go_deaf(path):
    """The bug every other test in this file missed.

    `seq` counts each writer's OWN messages, so the counters collide: the
    dashboard's first message and the viewer's first message are both seq 1.
    Comparing a bare seq made a genuine message from the other side look like
    one already seen, and the link silently stopped working the moment BOTH
    sides had spoken. Every test above passed because each had only one side
    talking. This one alternates.
    """
    dash = SyncClient(SOURCE_DASHBOARD, world="village", path=path)
    unity = SyncClient(SOURCE_UNITY, world="village", path=path)

    conversation = [
        (dash, unity, "Kaya-32", 110),
        (unity, dash, "Ines-30", 42),
        (dash, unity, "Leyla-46", 42),
        (unity, dash, "Arda-53", 7),
        (dash, unity, None, 7),
        (unity, dash, "Bora-52", 90),
    ]

    for speaker, listener, name, year in conversation:
        assert speaker.publish(name, year)
        heard = listener.poll()
        assert heard is not None, (
            "went deaf after the counters collided: %r said %r" % (speaker.source, name))
        assert heard.selected == name
        assert heard.year == year
        # And it is only news once.
        assert listener.poll() is None
