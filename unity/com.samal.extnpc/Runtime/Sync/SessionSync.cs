using System;
using System.Globalization;
using System.IO;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace ExtNPC.Sync
{
    /// <summary>
    /// One side of the dashboard link: what both viewers are looking at (N1).
    ///
    /// The C# half of `dashboard/session_sync.py`. Read that file for the
    /// reasoning; this one only has to agree with it. The agreement is a JSON
    /// object with `schema`, `selected`, `year`, `world`, `source` and `seq`,
    /// and `tests/test_session_sync.py` plus <c>SessionSyncTests</c> pin the
    /// same shape from both ends.
    ///
    /// WHY A FILE. Neither process may be able to wedge the other. A socket
    /// would make one of them a server, with a startup order, a port to
    /// collide and a reconnect loop; and an editor blocking on a read from a
    /// dashboard that is busy stepping a year is a frozen editor. Both sides
    /// poll a file, both tolerate its absence, and a closed dashboard looks
    /// like a value that stopped changing.
    ///
    /// IT DOES NOT STEP THE SIMULATION. FINAL_LINE N2 measured that: engine
    /// import is 12.4 s and a tick runs ~111 ms at 67 living, so roughly a
    /// second per simulated year at 600 people. Export then view is the right
    /// shape for this workload. This points two viewers at the same villager
    /// and the same year; it does not make Unity a client of the engine.
    ///
    /// THE ECHO PROBLEM. Both sides write and both sides read, so each will
    /// read back its own writes and, if it applies them, fight the user. Every
    /// payload names its `source` and a reader drops its own. `seq` then tells
    /// a new message from the same one polled twice. Both are needed: within a
    /// process the seq is enough, but after a RESTART the seq resets to zero
    /// while the file still holds the old process's payload, and only the
    /// source check stops that being read back as news.
    /// </summary>
    public sealed class SessionSync
    {
        public const int Schema = 1;
        public const string SourceUnity = "unity";
        public const string SourceDashboard = "dashboard";

        /// <summary>What the other side is looking at.</summary>
        public struct State
        {
            /// <summary>Selected villager, or null for no selection. Null is a
            /// MESSAGE, not a silence: deselecting has to travel or the other
            /// side keeps the old villager highlighted forever.</summary>
            public string Selected;

            /// <summary>The year being viewed, or null for "follow the newest".
            /// Not collapsed to the latest tick, because "follow the front" and
            /// "hold at year 40" are different intentions.</summary>
            public int? Year;

            public string World;
            public string Source;
            public long Seq;
        }

        private readonly string _source;
        private readonly string _world;
        private long _seq;

        // (source, seq) of the last payload accepted as news.
        //
        // THE PAIR, NOT THE SEQ. `seq` counts each writer's OWN messages, so
        // the two counters collide: the dashboard's first message and this
        // viewer's first message are both seq 1. Comparing a bare seq made a
        // genuine message look like one already seen, and the link went deaf
        // the moment BOTH sides had spoken. Found end to end on 2026-08-24;
        // every unit test on both sides passed, because each had only one side
        // talking.
        private string _lastSeenSource;
        private long _lastSeenSeq = -1;

        public string Path { get; private set; }

        public SessionSync(string source, string world, string path = null)
        {
            _source = source;
            _world = world ?? "";
            Path = string.IsNullOrEmpty(path) ? DefaultPath() : path;
        }

        /// <summary>
        /// Where the file lives when nobody says otherwise.
        ///
        /// NOT INSIDE THE BUNDLE, which is the obvious place and is wrong. The
        /// bundle here is a COPY: the exporter writes `outputs/unity/&lt;world&gt;`
        /// and that is installed into `Assets/StreamingAssets/extnpc/&lt;world&gt;`,
        /// so a file written into one is not the file read from the other. Both
        /// sides would work perfectly on different files, which is the worst
        /// kind of bug to be looking at. A user-level path outside both trees
        /// has no such copy.
        /// </summary>
        public static string DefaultPath()
        {
            string over = Environment.GetEnvironmentVariable("EXTNPC_SESSION_FILE");
            if (!string.IsNullOrEmpty(over)) return over;

            string home = Environment.GetFolderPath(
                Environment.SpecialFolder.UserProfile);
            if (string.IsNullOrEmpty(home))
                home = Environment.GetEnvironmentVariable("HOME") ?? ".";
            return System.IO.Path.Combine(home, ".extnpc", "session.json");
        }

        /// <summary>
        /// Announce what this side is looking at. False when it could not be
        /// written, which is not worth an exception: the next change tries
        /// again and the other side simply has stale news in the meantime.
        /// </summary>
        public bool Publish(string selected, int? year)
        {
            _seq++;
            var payload = new JObject
            {
                ["schema"] = Schema,
                ["selected"] = selected == null ? JValue.CreateNull() : new JValue(selected),
                ["year"] = year.HasValue ? new JValue(year.Value) : JValue.CreateNull(),
                ["world"] = _world,
                ["source"] = _source,
                ["seq"] = _seq,
                ["written_ms"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            };

            try
            {
                string dir = System.IO.Path.GetDirectoryName(Path);
                if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);

                // Same temp-then-move as the Python side, for the same reason:
                // the other side is polling, so an interrupted write must
                // damage a temp file rather than the payload anyone is reading.
                //
                // NOT A GUID, and the reason is a project rule rather than a
                // preference. `test_the_visual_layer_draws_no_random_numbers`
                // forbids `Guid.NewGuid` anywhere under Runtime, because
                // invariant 5 forbids the viewer inventing variance and the
                // rule is deliberately absolute rather than case-by-case. A
                // temp filename is not visual variance, but arguing the
                // exception would cost the rule its teeth, and nothing here
                // actually needs randomness: the source names the writer and
                // the sequence number is already unique per message, so the two
                // together are unique without drawing anything.
                string temp = Path + ".tmp-" + _source + "-" + _seq;
                try
                {
                    File.WriteAllText(temp, payload.ToString());
                    if (File.Exists(Path)) File.Delete(Path);
                    File.Move(temp, Path);
                }
                catch
                {
                    try { if (File.Exists(temp)) File.Delete(temp); } catch { }
                    throw;
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning("[extNPC] could not write the session file at " +
                                 Path + ": " + e.Message);
                return false;
            }

            // No bookkeeping needed for our own write: the source check in
            // TryPoll drops it, and it drops a previous process's payload too,
            // which a sequence number cannot because it resets on restart.
            return true;
        }

        /// <summary>
        /// What the OTHER side is looking at, or false when there is no news.
        ///
        /// NEVER THROWS. This runs from an editor update on a timer, and the
        /// file is being replaced by another process, so a missing file, a
        /// half-written one, one being swapped underneath us and a payload from
        /// a future schema all have to mean the same thing: no news. On Windows
        /// a replace can even make the reader's own Open fail transiently,
        /// which is measured and expected and is harmless to a poller.
        /// </summary>
        public bool TryPoll(out State state)
        {
            state = default(State);

            JObject root;
            try
            {
                if (!File.Exists(Path)) return false;
                root = JObject.Parse(File.ReadAllText(Path));
            }
            catch
            {
                return false;
            }

            int? schema = (int?)root["schema"];
            if (!schema.HasValue || schema.Value != Schema) return false;

            string source = (string)root["source"] ?? "";
            if (source == _source) return false;

            long seq = (long?)root["seq"] ?? 0L;
            if (source == _lastSeenSource && seq == _lastSeenSeq) return false;

            string world = (string)root["world"] ?? "";
            // A dashboard on a different world must not drag the viewer to a
            // villager who does not exist in the one on screen. Empty means
            // "not stated", which is allowed so a caller can opt out.
            if (!string.IsNullOrEmpty(_world) && !string.IsNullOrEmpty(world)
                && world != _world)
                return false;

            _lastSeenSource = source;
            _lastSeenSeq = seq;
            state = new State
            {
                Selected = root["selected"] != null && root["selected"].Type != JTokenType.Null
                    ? (string)root["selected"] : null,
                Year = root["year"] != null && root["year"].Type != JTokenType.Null
                    ? (int?)(int)root["year"] : null,
                World = world,
                Source = source,
                Seq = seq,
            };
            return true;
        }

        /// <summary>Formats a year the way the Python side parses it. Invariant
        /// culture on purpose: this machine writes commas for decimal points in
        /// its own locale, and the reader on the other end does not.</summary>
        public static string FormatYear(int year)
        {
            return year.ToString(CultureInfo.InvariantCulture);
        }
    }
}
