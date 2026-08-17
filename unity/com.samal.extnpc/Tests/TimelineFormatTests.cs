using System.Globalization;
using System.Threading;
using ExtNPC.View;
using NUnit.Framework;

namespace ExtNPC.Tests
{
    /// <summary>
    /// The KPI strip's wording, and the two em-dash rules it exists to keep.
    ///
    /// The generated parity fixture already replays these formatters against
    /// the dashboard's real output; what it cannot express is WHY a value is an
    /// em dash, because it only carries numbers. These tests pin the reasoning:
    /// F_ST is unmeasurable because of the world's SHAPE (one deme, no
    /// partition to estimate over) and B(t) because the load layer has no
    /// measurement — not because either value happened to come out zero.
    /// </summary>
    public class TimelineFormatTests
    {
        [Test]
        public void FstIsAnEmDashInASingleDemeWorldEvenWhenAValueIsPresent()
        {
            // The distinction that matters: a 0.000 on screen asserts "no
            // differentiation was measured", which is a different claim from
            // "there was nothing to measure". The engine's manifest reports
            // fst as null for exactly this reason.
            Assert.AreEqual(TimelineFormat.Unmeasurable,
                            TimelineFormat.Fst(0.019, 1));
            Assert.AreEqual(TimelineFormat.Unmeasurable,
                            TimelineFormat.Fst(0, 1));
        }

        [Test]
        public void FstIsPrintedWhenThereAreDemesToCompare()
        {
            Assert.AreEqual("0.103", TimelineFormat.Fst(0.1032, 3));
            // A genuine zero in a multi-deme world IS a measurement, and is
            // shown as one.
            Assert.AreEqual("0.000", TimelineFormat.Fst(0, 3));
        }

        [Test]
        public void LoadIsAnEmDashUntilThereIsAMeasurement()
        {
            Assert.AreEqual(TimelineFormat.Unmeasurable, TimelineFormat.Load(0));
            Assert.AreEqual("1.400", TimelineFormat.Load(1.4));
        }

        [Test]
        public void TheEmDashIsAnEmDashAndNotAHyphen()
        {
            // U+2014. A hyphen would look almost identical on screen and would
            // be a silent parity break against dashboard/panels.py.
            Assert.AreEqual("—", TimelineFormat.Unmeasurable);
        }

        [Test]
        public void AliveTruncatesTheWayPythonsIntDoes()
        {
            Assert.AreEqual("36", TimelineFormat.Alive(36));
            Assert.AreEqual("35", TimelineFormat.Alive(35.9));
        }

        [Test]
        public void InbreedingKeepsFourDecimals()
        {
            // Three would round distinct pedigrees together: a second-cousin
            // child (0.0156) and a first-cousin-once-removed one (0.0312) are
            // both "0.016"/"0.031" at three, but mean F in a village lives in
            // the fourth decimal.
            Assert.AreEqual("0.0625", TimelineFormat.Inbreeding(0.0625));
        }

        [Test]
        public void EveryFormatterSurvivesACommaDecimalLocale()
        {
            // The failure this project has already been bitten by twice: an
            // ambient culture turning 0.103 into "0,103" on one operator's
            // machine and not another's.
            var previous = Thread.CurrentThread.CurrentCulture;
            try
            {
                Thread.CurrentThread.CurrentCulture = new CultureInfo("de-DE");
                Assert.AreEqual("0.103", TimelineFormat.Fst(0.1032, 3));
                Assert.AreEqual("1.400", TimelineFormat.Load(1.4));
                Assert.AreEqual("0.0625", TimelineFormat.Inbreeding(0.0625));
                Assert.AreEqual("0.412", TimelineFormat.Heterozygosity(0.412));
                Assert.AreEqual("4.0 yr/s", TimelineFormat.Speed(4));
                Assert.AreEqual("year 40 of 12–90",
                                TimelineFormat.Range(40, 12, 90));
            }
            finally
            {
                Thread.CurrentThread.CurrentCulture = previous;
            }
        }

        [Test]
        public void TheScrubStateNamesTheYearAndTheWayBack()
        {
            Assert.AreEqual("REPLAY · VIEWING YEAR 40 — press Live to return",
                            TimelineFormat.ScrubState(40));
        }

        /// <summary>
        /// Every non-ASCII character the HUD prints must be one that has been
        /// looked at, in pixels, in a running editor.
        ///
        /// AN ALLOWLIST, NOT A BAN ON EMOJI. A list of emoji codepoint ranges
        /// would need maintaining against a moving standard and would still
        /// miss the next character nobody checked. This asks the question that
        /// actually matters instead: has anyone seen this one drawn?
        ///
        /// U+23F1 is why the rule exists. It has emoji presentation, so it
        /// resolved through an OS emoji font rather than the text font,
        /// rendering white and red on Windows inside an amber label and liable
        /// to box on a target with no emoji font at all. It sat on the one
        /// banner whose whole job is to say the view is not live.
        ///
        /// Adding a character here is meant to be a deliberate act with a
        /// screenshot behind it, not a formality.
        /// </summary>
        [Test]
        public void TheHudPrintsOnlyGlyphsSomeoneHasSeenRendered()
        {
            // Confirmed in a running editor, session 21, at 6x magnification.
            const string confirmed = "·—–●→₂";

            string[] banners =
            {
                TimelineFormat.LiveState,
                TimelineFormat.ScrubState(40),
                TimelineFormat.CosmeticMotionNote,
                TimelineFormat.Unmeasurable,
                TimelineFormat.NoEventsNote,
                TimelineFormat.Range(40, 0, 90),
                TimelineFormat.Speed(4f),
                TimelineFormat.EventEntry(12, "plague"),
                TimelineFormat.AliveLabel,
                TimelineFormat.HeterozygosityLabel,
                TimelineFormat.FstLabel,
                TimelineFormat.InbreedingLabel,
                TimelineFormat.LoadLabel,
                TimelineFormat.EventNotePrefix,
            };

            foreach (string banner in banners)
            {
                foreach (char c in banner)
                {
                    if (c < 128 || confirmed.IndexOf(c) >= 0) continue;
                    Assert.Fail(
                        $"'{banner}' contains U+{(int)c:X4}, which is not in " +
                        $"the set of glyphs confirmed to render as text. " +
                        $"Look at it in an editor and add it, or use a word.");
                }
            }
        }

        [Test]
        public void AnEventEntryReadsTheWayTheDashboardsNoteDoes()
        {
            Assert.AreEqual("y12 plague swept the valley",
                            TimelineFormat.EventEntry(12, "plague swept the valley"));
        }

        [Test]
        public void TheRoundingModeIsPythonsEverywhereOnThisPanel()
        {
            // Half to even, as Python's format spec rounds — .NET's F formats
            // round half away from zero, and the two disagree on exact
            // midpoints. Dyadic values are the normal case for F.
            Assert.AreEqual("0.0312", TimelineFormat.Inbreeding(0.03125));
            Assert.AreEqual("0.062", TimelineFormat.Heterozygosity(0.0625));
        }
    }
}
