using System.IO;
using ExtNPC.Sync;
using NUnit.Framework;

namespace ExtNPC.Tests
{
    /// <summary>
    /// The Unity half of the dashboard link (N1).
    ///
    /// There are TWO implementations of this format, one here and one in
    /// `dashboard/session_sync.py`, and nothing but agreement keeps them
    /// talking. That is the risk these tests exist for: a field renamed on one
    /// side does not fail, it just means the other side never hears anything,
    /// which looks exactly like "the user has not clicked yet".
    ///
    /// `tests/test_session_sync.py::test_a_unity_written_payload_is_readable`
    /// closes the loop from the other direction by parsing a payload this file
    /// documents byte for byte.
    /// </summary>
    public class SessionSyncTests
    {
        private string _dir;
        private string _path;

        [SetUp]
        public void SetUp()
        {
            _dir = Path.Combine(Path.GetTempPath(),
                "extnpc-sync-" + System.Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_dir);
            _path = Path.Combine(_dir, "session.json");
        }

        [TearDown]
        public void TearDown()
        {
            try { Directory.Delete(_dir, true); } catch { }
        }

        private SessionSync Unity()
        {
            return new SessionSync(SessionSync.SourceUnity, "village", _path);
        }

        private SessionSync Dashboard()
        {
            return new SessionSync(SessionSync.SourceDashboard, "village", _path);
        }

        // ------------------------------------------------------------------
        // the round trip
        // ------------------------------------------------------------------

        [Test]
        public void TheOtherSideIsHeard()
        {
            Dashboard().Publish("Kaya-32", 110);

            SessionSync.State state;
            Assert.IsTrue(Unity().TryPoll(out state));
            Assert.AreEqual("Kaya-32", state.Selected);
            Assert.AreEqual(110, state.Year);
        }

        [Test]
        public void AClientDoesNotHearItsOwnWrites()
        {
            var unity = Unity();
            unity.Publish("Kaya-32", 110);

            SessionSync.State state;
            Assert.IsFalse(unity.TryPoll(out state),
                "the viewer would fight the user's own clicks");
        }

        [Test]
        public void ARestartedClientDoesNotHearItsOwnPreviousProcess()
        {
            // Isolates the source check from the seq check. Within one instance
            // the seq bookkeeping alone swallows the echo; after a restart the
            // seq is back at zero while the file still holds the old process's
            // payload, and only the source check stops it reading as news.
            Unity().Publish("Kaya-32", 110);

            SessionSync.State state;
            Assert.IsFalse(Unity().TryPoll(out state),
                "a domain reload would re-apply the last selection");
        }

        [Test]
        public void TheSameMessageIsOnlyNewsOnce()
        {
            Dashboard().Publish("Kaya-32", 110);
            var unity = Unity();

            SessionSync.State state;
            Assert.IsTrue(unity.TryPoll(out state));
            Assert.IsFalse(unity.TryPoll(out state),
                "polling on a timer must not keep re-applying one selection");
        }

        [Test]
        public void ATwoWayConversationDoesNotGoDeaf()
        {
            // The bug every other test in this file missed, and its twin on the
            // Python side missed too. `seq` counts each writer's OWN messages,
            // so the counters collide: the dashboard's first message and this
            // viewer's first message are both seq 1. Comparing a bare seq made
            // a genuine message look like one already seen, and the link went
            // deaf the moment BOTH sides had spoken. Every test above passed,
            // because each had only one side talking. This one alternates.
            var dash = Dashboard();
            var unity = Unity();

            var script = new[]
            {
                new { Speaker = dash,  Listener = unity, Name = "Kaya-32",  Year = 110 },
                new { Speaker = unity, Listener = dash,  Name = "Ines-30",  Year = 42 },
                new { Speaker = dash,  Listener = unity, Name = "Leyla-46", Year = 42 },
                new { Speaker = unity, Listener = dash,  Name = "Arda-53",  Year = 7 },
            };

            foreach (var line in script)
            {
                Assert.IsTrue(line.Speaker.Publish(line.Name, line.Year));

                SessionSync.State state;
                Assert.IsTrue(line.Listener.TryPoll(out state),
                    "went deaf after the counters collided, at " + line.Name);
                Assert.AreEqual(line.Name, state.Selected);
                Assert.AreEqual(line.Year, state.Year);

                Assert.IsFalse(line.Listener.TryPoll(out state),
                    "the same message must only be news once");
            }
        }

        [Test]
        public void ClearingASelectionIsAMessageNotASilence()
        {
            var dash = Dashboard();
            var unity = Unity();

            dash.Publish("Kaya-32", 110);
            SessionSync.State state;
            unity.TryPoll(out state);

            dash.Publish(null, 110);
            Assert.IsTrue(unity.TryPoll(out state),
                "deselecting has to travel");
            Assert.IsNull(state.Selected);
        }

        [Test]
        public void LiveIsNullAndStaysNull()
        {
            // year=null means "follow the newest year", which is not the same
            // as the newest year's number.
            Dashboard().Publish("Kaya-32", null);

            SessionSync.State state;
            Assert.IsTrue(Unity().TryPoll(out state));
            Assert.IsFalse(state.Year.HasValue);
        }

        // ------------------------------------------------------------------
        // never throwing, which is the contract
        // ------------------------------------------------------------------

        [Test]
        public void AMissingFileIsNoNewsRatherThanAnError()
        {
            SessionSync.State state;
            Assert.IsFalse(Unity().TryPoll(out state));
        }

        [Test]
        public void ATruncatedFileIsNoNews()
        {
            // The case a polling reader WILL hit if the writer is not atomic.
            File.WriteAllText(_path, "{\"schema\": 1, \"selected\": \"Kay");

            SessionSync.State state;
            Assert.DoesNotThrow(() => Unity().TryPoll(out state));
            Assert.IsFalse(Unity().TryPoll(out state));
        }

        [Test]
        public void AFutureSchemaIsIgnoredRatherThanGuessedAt()
        {
            File.WriteAllText(_path,
                "{\"schema\": 99, \"selected\": \"Kaya-32\", \"source\": \"dashboard\", \"seq\": 1}");

            SessionSync.State state;
            Assert.IsFalse(Unity().TryPoll(out state));
        }

        [Test]
        public void APayloadForAnotherWorldIsIgnored()
        {
            new SessionSync(SessionSync.SourceDashboard, "onedeme", _path)
                .Publish("Someone-Else", 40);

            SessionSync.State state;
            Assert.IsFalse(Unity().TryPoll(out state),
                "a dashboard on another world must not drag the viewer to a " +
                "villager who does not exist here");
        }

        [Test]
        public void AnUnstatedWorldIsAccepted()
        {
            new SessionSync(SessionSync.SourceDashboard, "", _path)
                .Publish("Kaya-32", 110);

            SessionSync.State state;
            Assert.IsTrue(Unity().TryPoll(out state));
        }

        [Test]
        public void AnInterruptedWriteLeavesThePreviousPayloadIntact()
        {
            // Same property the Python side pins: the target only ever holds a
            // payload that was written completely. Simulated by leaving a stray
            // temp file, which must not be mistaken for the payload.
            Dashboard().Publish("Kaya-32", 110);
            File.WriteAllText(_path + ".tmp-orphan", "{ half a doc");

            SessionSync.State state;
            Assert.IsTrue(Unity().TryPoll(out state));
            Assert.AreEqual("Kaya-32", state.Selected);
        }

        // ------------------------------------------------------------------
        // the format both sides have to agree on
        // ------------------------------------------------------------------

        [Test]
        public void ThePayloadThePythonSideExpectsIsWhatWeWrite()
        {
            // Pinned as literal field names. Renaming one here does not fail
            // anywhere else: it just means the dashboard stops hearing this
            // viewer, which is indistinguishable from nobody having clicked.
            Dashboard().Publish("Kaya-32", 110);
            string text = File.ReadAllText(_path);

            foreach (string field in new[] { "schema", "selected", "year",
                                             "world", "source", "seq" })
            {
                StringAssert.Contains("\"" + field + "\"", text,
                    "the Python side reads this field by name");
            }
        }

        [Test]
        public void APythonWrittenPayloadIsReadable()
        {
            // Byte for byte what `dashboard/session_sync.py` produces, with its
            // indent=1 formatting, so this fails if either side drifts.
            File.WriteAllText(_path,
                "{\n" +
                " \"schema\": 1,\n" +
                " \"selected\": \"Ines-30\",\n" +
                " \"year\": 42,\n" +
                " \"world\": \"village\",\n" +
                " \"source\": \"dashboard\",\n" +
                " \"seq\": 7,\n" +
                " \"written_ms\": 1787568000000\n" +
                "}\n");

            SessionSync.State state;
            Assert.IsTrue(Unity().TryPoll(out state));
            Assert.AreEqual("Ines-30", state.Selected);
            Assert.AreEqual(42, state.Year);
            Assert.AreEqual("village", state.World);
            Assert.AreEqual(7L, state.Seq);
        }

        [Test]
        public void TheDefaultPathIsOutsideBothTrees()
        {
            // The bundle Unity reads is a COPY of the exported one, so a file
            // inside it is not shared with the dashboard.
            string path = SessionSync.DefaultPath();
            StringAssert.DoesNotContain("StreamingAssets", path);
            StringAssert.DoesNotContain("outputs", path);
            StringAssert.EndsWith("session.json", path);
        }
    }
}
