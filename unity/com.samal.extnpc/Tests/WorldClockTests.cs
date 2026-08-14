using ExtNPC.View;
using NUnit.Framework;

namespace ExtNPC.Tests
{
    /// <summary>
    /// The timeline arithmetic, driven directly.
    ///
    /// <see cref="TimelineCursor"/> is a plain struct precisely so this can
    /// exist: every off-by-one a scrub bar can have is reachable here without a
    /// scene, a bundle, a frame loop or a Unity Play session. What it cannot
    /// check is that the clock is wired to the renderer — that needs the
    /// editor, and the console line the renderer prints per year is the
    /// evidence for it.
    ///
    /// The cases are chosen around the two claims Stage 5 makes about time:
    /// a scrub always lands ON an exported year, and playback never runs past
    /// the last one into a year that does not exist.
    /// </summary>
    public class WorldClockTests
    {
        [Test]
        public void AdvanceWithinAYearOnlyMovesAlpha()
        {
            var c = new TimelineCursor();
            bool ended = c.Advance(0.25f, 10, false);

            Assert.IsFalse(ended);
            Assert.AreEqual(0, c.Index);
            Assert.AreEqual(0.25f, c.Alpha, 1e-5f);
        }

        [Test]
        public void AdvanceRollsOverIntoTheNextYear()
        {
            var c = new TimelineCursor();
            c.Advance(1.5f, 10, false);

            Assert.AreEqual(1, c.Index);
            Assert.AreEqual(0.5f, c.Alpha, 1e-5f);
        }

        [Test]
        public void ALongFrameDoesNotSwallowYears()
        {
            // A hitch — an editor recompile, a garbage collection — hands
            // Update a large deltaTime. The cursor must land where the elapsed
            // time says, not one year on.
            var c = new TimelineCursor();
            c.Advance(4.75f, 10, false);

            Assert.AreEqual(4, c.Index);
            Assert.AreEqual(0.75f, c.Alpha, 1e-5f);
        }

        [Test]
        public void PlaybackParksExactlyOnTheLastYear()
        {
            // The claim: a finished run shows the final EXPORTED frame, not a
            // blend toward a year the engine never simulated.
            var c = new TimelineCursor { Index = 8 };
            bool ended = c.Advance(5f, 10, false);

            Assert.IsTrue(ended);
            Assert.AreEqual(9, c.Index);
            Assert.AreEqual(0f, c.Alpha, 0f, "a parked cursor must carry no " +
                "inter-tick fraction: there is no year after the last one");
        }

        [Test]
        public void LoopingWrapsWithoutOverrunning()
        {
            var c = new TimelineCursor { Index = 9 };
            bool ended = c.Advance(1.25f, 10, true);

            Assert.IsFalse(ended);
            Assert.Less(c.Index, 10);
            Assert.GreaterOrEqual(c.Index, 0);
        }

        [Test]
        public void ASingleFrameBundleIsNotATimeline()
        {
            // One retained year: there is nothing to scrub and nothing to blend
            // toward. Anything other than a parked cursor here would divide by
            // a zero-length range in the HUD.
            var c = new TimelineCursor();
            bool ended = c.Advance(3f, 1, false);

            Assert.IsTrue(ended);
            Assert.AreEqual(0, c.Index);
            Assert.AreEqual(0f, c.Alpha);
        }

        [Test]
        public void SeekLandsOnAYearAndDropsTheCosmeticFraction()
        {
            var c = new TimelineCursor { Index = 3, Alpha = 0.6f };
            c.Seek(7, 10);

            Assert.AreEqual(7, c.Index);
            Assert.AreEqual(0f, c.Alpha, 0f,
                "scrubbing must show an exported frame, never a blend");
        }

        [Test]
        public void SeekClampsToTheRetainedRange()
        {
            var c = new TimelineCursor();

            c.Seek(999, 10);
            Assert.AreEqual(9, c.Index);

            c.Seek(-4, 10);
            Assert.AreEqual(0, c.Index);
        }
    }
}
