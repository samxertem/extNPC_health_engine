"""
The one small file the dashboard and the Unity viewer both watch (item N1).

WHY A FILE AND NOT A SOCKET. Neither process may be able to wedge the other.
A socket makes one of them a server and the other a client, which means a
startup order, a port to collide, a connection to drop and a reconnect loop to
get wrong; and the moment the viewer blocks on a read, a dashboard that is busy
stepping a year has stalled the editor. A file has none of that. Both sides
poll it, both sides tolerate it being absent, and if one of them is closed the
other simply sees a value that stops changing.

WHY NOT INSIDE THE BUNDLE, which is the obvious place. The bundle Unity reads
is a COPY: `outputs/unity/village` is installed into the consuming project's
`Assets/StreamingAssets/extnpc/<world>/`, so a file written into one is not the
file read from the other. That copy is easy to forget and produces the worst
kind of bug, where both sides are working perfectly on different files. So the
sync file lives at a fixed user-level path that neither side owns, outside both
trees, overridable with `EXTNPC_SESSION_FILE` for tests and for a second
concurrent session.

WHAT IT CARRIES. A selection and a year, which FINAL_LINE N1 says are one
mechanism and are done together: they are both "what am I looking at", they
change together when you click a villager in a past year, and splitting them
into two files would let them disagree.

WHAT IT DOES NOT CARRY, and this is N2's decision rather than an omission. It
does not step the simulation. Engine import is 12.4 s and a tick is ~111 ms at
67 living, so roughly a second per simulated year at 600 people; export then
view is the right shape for this workload. This file points two viewers at the
same thing. It does not make Unity a client of the engine.

THE ECHO PROBLEM, which is the one real subtlety. Both sides write and both
sides read, so each will read back its own writes and, if it applies them,
fight the user's input. Every payload therefore names its `source`, and a
reader ignores anything it wrote itself. `seq` increases so a reader can also
tell a genuinely new message from the same one polled twice, which matters
because two writes inside the same clock tick are otherwise indistinguishable.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any, Dict, Optional

__all__ = [
    "SCHEMA",
    "SessionState",
    "default_path",
    "read_state",
    "write_state",
]

SCHEMA = 1

#: Sentinel for "this client has published nothing yet". A module-level object
#: rather than None, because (None, None) is a legitimate state to publish.
_NOTHING_PUBLISHED = object()

#: Who wrote a payload. A reader ignores its own source.
SOURCE_DASHBOARD = "dashboard"
SOURCE_UNITY = "unity"


def default_path() -> str:
    """Where the sync file lives when nobody says otherwise.

    A user-level path rather than a temp directory: a session-scoped temp
    directory is cleaned up underneath a long-running editor, and the two
    processes start at different times, so "the temp dir" is not necessarily
    the same directory for both of them.
    """
    override = os.environ.get("EXTNPC_SESSION_FILE")
    if override:
        return override
    return os.path.join(os.path.expanduser("~"), ".extnpc", "session.json")


class SessionState:
    """What both viewers are looking at.

    `year` is the simulated year being VIEWED, which is not always the newest
    one: the dashboard calls that time travel and stores None for "live". None
    is preserved rather than collapsed to the latest tick, because "follow the
    front" and "hold at year 40" are different intentions and the viewer on the
    other side should be able to honour the difference.
    """

    __slots__ = ("selected", "year", "world", "source", "seq", "written_ms")

    def __init__(self, selected: Optional[str] = None,
                 year: Optional[int] = None,
                 world: str = "",
                 source: str = "",
                 seq: int = 0,
                 written_ms: int = 0) -> None:
        self.selected = selected
        self.year = year
        self.world = world
        self.source = source
        self.seq = int(seq)
        self.written_ms = int(written_ms)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": SCHEMA,
            "selected": self.selected,
            "year": self.year,
            "world": self.world,
            "source": self.source,
            "seq": self.seq,
            "written_ms": self.written_ms,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionState":
        return cls(
            selected=data.get("selected"),
            year=data.get("year"),
            world=data.get("world") or "",
            source=data.get("source") or "",
            seq=data.get("seq") or 0,
            written_ms=data.get("written_ms") or 0,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SessionState):
            return NotImplemented
        return (self.selected == other.selected and self.year == other.year
                and self.world == other.world)

    def __repr__(self) -> str:
        return (f"SessionState(selected={self.selected!r}, year={self.year!r}, "
                f"world={self.world!r}, source={self.source!r}, seq={self.seq})")


def read_state(path: Optional[str] = None) -> Optional[SessionState]:
    """The current state, or None when there is nothing usable to read.

    NEVER RAISES, and that is the contract rather than defensive habit. This is
    called from a Dash callback on a timer. An exception here would take out
    the callback that also advances the world, so a missing file, a half-written
    one, a file being replaced under us or a payload from a future schema all
    have to mean the same thing: no news. The alternative is a viewer that dies
    because the other viewer was mid-write.
    """
    target = path or default_path()
    try:
        with open(target, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None

    if not isinstance(data, dict):
        return None
    # An unknown schema is ignored rather than guessed at. Reading a future
    # field layout as if it were this one is how two versions of the same tool
    # silently disagree about which villager is selected.
    if data.get("schema") != SCHEMA:
        return None
    return SessionState.from_dict(data)


def write_state(state: SessionState, path: Optional[str] = None) -> bool:
    """Write atomically. Returns False rather than raising when it cannot.

    ATOMIC BECAUSE THE READER IS POLLING. A plain open-and-write leaves a
    window in which the file exists and is half a JSON document, and the other
    side is reading on a timer, so it WILL land in that window eventually. The
    temp-file-then-replace means the target only ever holds a payload that was
    written completely: an interrupted write damages the temp file, which is
    then removed, and the previous payload survives untouched.

    WHAT IT DOES NOT BUY, measured on Windows on 2026-08-24 rather than
    assumed. It does not make writes invisible to a concurrent reader. Under a
    reader polling flat out, failed reads went from about 35% of attempts with
    a plain write to about 9% with this one -- a real improvement, and not
    zero, because `os.replace` can collide with a reader that currently has the
    file open and make its `open()` fail. That surfaces as OSError, which
    `read_state` already reports as "no news", and no news is harmless to a
    poller: the next tick reads the new payload. The claim here is that the
    file is never CORRUPT, not that a read never fails.

    `os.replace` rather than `os.rename`: on Windows, rename onto an existing
    file raises, which would make every write after the first one fail.
    """
    target = path or default_path()
    directory = os.path.dirname(target)
    try:
        if directory:
            os.makedirs(directory, exist_ok=True)
        state.written_ms = int(time.time() * 1000)

        handle, temp = tempfile.mkstemp(
            dir=directory or None, prefix=".session-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(state.to_dict(), fh, indent=1)
                fh.write("\n")
            os.replace(temp, target)
        except BaseException:
            # Do not leave a temp file behind on a failed write; the directory
            # is long-lived and this runs on a timer.
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise
        return True
    except OSError:
        return False


class SyncClient:
    """One side of the link: writes its own state, ignores its own echo.

    Holds the sequence number and the last state it published, so a caller can
    poll on a timer and be told only about genuine changes made by the OTHER
    side. Keeping that bookkeeping here rather than in the Dash callback is
    what stops the callback from becoming a feedback loop, which is the same
    failure `slider-echo` already exists to prevent in `app.py`.
    """

    def __init__(self, source: str, world: str = "",
                 path: Optional[str] = None) -> None:
        self.source = source
        self.world = world
        self.path = path or default_path()
        self._seq = 0
        # (source, seq) of the last payload this client accepted as news.
        #
        # THE PAIR, NOT THE SEQ. `seq` counts each writer's own messages, so
        # the two counters collide: the dashboard's third message and the
        # viewer's third message are both seq 3. Comparing a bare seq made a
        # genuine message from the other side look like one already seen, and
        # the sync silently stopped working as soon as BOTH sides had spoken.
        # Every unit test passed, because each one had only one side talking.
        self._last_seen = None
        # The last (selected, year) this side put on the wire, or a sentinel
        # meaning "nothing yet". A caller polling on a timer uses it to avoid
        # rewriting an unchanged state two or three times a second forever; the
        # sentinel is a distinct object rather than None so that publishing
        # (None, None) -- nobody selected, following the newest year, which is
        # the dashboard's opening state -- still counts as having published.
        self._last_published = _NOTHING_PUBLISHED

    @property
    def last_published(self):
        """What this side last put on the wire, as `(selected, year)`.

        Compares unequal to every real pair until something has been published,
        so the first call always writes.
        """
        return self._last_published

    def publish(self, selected: Optional[str], year: Optional[int]) -> bool:
        """Announce what this side is looking at."""
        self._seq += 1
        state = SessionState(selected=selected, year=year, world=self.world,
                             source=self.source, seq=self._seq)
        ok = write_state(state, self.path)
        if ok:
            self._last_published = (selected, year)
        return ok

    def poll(self) -> Optional[SessionState]:
        """What the OTHER side is looking at, or None when there is no news.

        Returns None for: no file, unreadable file, our own writes, a payload
        already returned, and a payload for a different world.
        """
        state = read_state(self.path)
        if state is None:
            return None
        # Our own writes, including those of a previous process: after a
        # restart `seq` is back at zero while the file still holds the old
        # payload, and only this check stops it being read back as news.
        if state.source == self.source:
            return None
        if (state.source, state.seq) == self._last_seen:
            return None
        # A dashboard running a different world must not drag the viewer to a
        # villager who does not exist in the one on screen. Empty means "not
        # stated", which is allowed so a caller can opt out.
        if self.world and state.world and state.world != self.world:
            return None
        self._last_seen = (state.source, state.seq)
        # Record what we heard as though we had published it. Without this the
        # caller applies the incoming state, sees on its next tick that its own
        # state differs from `last_published`, and sends it straight back. The
        # other side drops that as a duplicate rather than looping forever, so
        # the symptom is not a hang: it is two processes writing the same file
        # to each other several times a second for no reason. The C# bridge
        # does the same thing after applying a payload.
        self._last_published = (state.selected, state.year)
        return state
