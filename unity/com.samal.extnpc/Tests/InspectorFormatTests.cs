using System.Globalization;
using System.Threading;
using ExtNPC.View;
using NUnit.Framework;

namespace ExtNPC.Tests
{
    /// <summary>
    /// The Stage 4 parity rules, pinned where they can be executed.
    ///
    /// tests/test_unity_contract.py compares this file's TABLES with
    /// dashboard/inspector.py by reading both as text — that is what catches a
    /// threshold edited on one side only. What text comparison cannot catch is
    /// a table that is correct and a formatter that renders it wrongly, which
    /// is what these tests are for.
    ///
    /// The locale cases are the important ones. This project has already been
    /// bitten once by the FORMATTING half of the culture rule: the first
    /// in-editor run printed "4.111 rows" for 4,111 rows, because an
    /// interpolated $"{n:N0}" formats with the ambient culture. The parsing
    /// half was invariant and correct, which is the only reason the numbers
    /// underneath were right. Both halves need pinning, and only one of them
    /// had been.
    /// </summary>
    public class InspectorFormatTests
    {
        private static void UnderGermanCulture(System.Action body)
        {
            var previous = Thread.CurrentThread.CurrentCulture;
            try
            {
                Thread.CurrentThread.CurrentCulture = new CultureInfo("de-DE");
                body();
            }
            finally
            {
                Thread.CurrentThread.CurrentCulture = previous;
            }
        }

        // ------------------------------------------------------------------
        // the relationship ladder -- inspector.py:108
        // ------------------------------------------------------------------

        [Test]
        public void TheRelationshipLadderReadsAsAtLeastThisClose()
        {
            // Exactly on a threshold must take that threshold's label: the
            // Python side compares with a 1e-9 tolerance for the same reason,
            // because 0.0625 is a value F actually takes for a first-cousin
            // child rather than one it approaches.
            Assert.AreEqual("full sib / parent–offspring",
                            InspectorFormat.RelationshipLabel(0.25));
            Assert.AreEqual("full sib / parent–offspring",
                            InspectorFormat.RelationshipLabel(0.5));
            Assert.AreEqual("uncle–niece / double first cousin",
                            InspectorFormat.RelationshipLabel(0.125));
            Assert.AreEqual("first cousins",
                            InspectorFormat.RelationshipLabel(0.0625));
            Assert.AreEqual("first cousins once removed",
                            InspectorFormat.RelationshipLabel(0.03125));
            Assert.AreEqual("second cousins",
                            InspectorFormat.RelationshipLabel(0.015625));
        }

        [Test]
        public void OutbredAndDistantKinAreDifferentClaims()
        {
            // Zero F is "outbred"; a small non-zero F is "distant kin". They
            // are not the same statement about someone's parents, and the
            // dashboard distinguishes them (inspector.py:113).
            Assert.AreEqual("outbred", InspectorFormat.RelationshipLabel(0));
            Assert.AreEqual("distant kin", InspectorFormat.RelationshipLabel(0.004));
        }

        // ------------------------------------------------------------------
        // F formatting -- inspector.py:116
        // ------------------------------------------------------------------

        [Test]
        public void PedigreeFKeepsFourDecimalsAndCollapsesZeroToABareZero()
        {
            // Four decimals is not fussiness: at two, a first-cousin child
            // (0.0625) and a second-cousin child (0.0156) both round to
            // something uninformative, and telling them apart is the whole
            // point of showing F.
            Assert.AreEqual("0.0625", InspectorFormat.FmtF(0.0625));
            Assert.AreEqual("0.0156", InspectorFormat.FmtF(0.015625));
            Assert.AreEqual("0", InspectorFormat.FmtF(0));
        }

        [Test]
        public void ExactMidpointsRoundHalfToEvenLikePythonNotAwayFromZero()
        {
            // FOUND BY THE PARITY FIXTURE, not by anyone reading the code.
            //
            // Python's format spec rounds half to EVEN; .NET's F/0.00 formats
            // round half AWAY FROM ZERO. The two agree on every value that is
            // not an exact midpoint, which is most of them -- so the bug is
            // invisible to a hand-written test unless you pick the midpoint on
            // purpose, and the hand-written tests above did not.
            //
            // These are not exotic inputs. Pedigree F and lineage purity are
            // dyadic rationals, so exact midpoints are routine: 0.03125 is the
            // ladder's own "first cousins once removed" threshold, and 0.125
            // is one eighth of ancestry.
            Assert.AreEqual("0.0312", InspectorFormat.FmtF(0.03125),
                            "F=0.03125 must round to even, as Python does");
            Assert.AreEqual("12%", InspectorFormat.Percent0(0.125),
                            "12.5% must round to even, as Python does");

            // The control: 37.5 rounds to 38 under BOTH modes. If this one
            // ever disagrees the cause is precision, not rounding mode, and
            // the fix is a different fix.
            Assert.AreEqual("38%", InspectorFormat.Percent0(0.375));
        }

        [Test]
        public void ADisplayedNumberIsParsedAtTheWidthPythonHoldsIt()
        {
            // FOUND IN STAGE 5, AND THE FIRST DEFECT OF ITS CLASS.
            //
            // The formatters were correct and the parse was wrong. Python holds
            // history and frame values as binary64 and formats from that; this
            // package parsed the same text into binary32, so the two sides were
            // formatting DIFFERENT NUMBERS -- and at a rounding boundary they
            // print different text while both look entirely plausible.
            //
            // "-1.385" is a real `stress` value from a 40-year export. It is an
            // exact 3-decimal midpoint printed at 2 decimals, which is the
            // ORDINARY case here: snapshots.py rounds stress and aerobic to
            // three decimals and the drawer shows two. Measured on that export,
            // 77 of 1323 stress values and 64 of 1323 aerobic values differed.
            //
            // The two assertions below are the bug and the fix, side by side.
            Assert.AreEqual("-1.39",
                InspectorFormat.Signed2(ExtNPC.Data.CsvParse.Double("-1.385")),
                "parsed as double, the viewer must print what the dashboard prints");
            Assert.AreEqual("-1.38",
                InspectorFormat.Signed2(ExtNPC.Data.CsvParse.Float("-1.385")),
                "parsed as float this is the WRONG neighbour — if this ever " +
                "starts passing as -1.39, binary32 has stopped being the " +
                "problem and this test can go");

            Assert.AreEqual("39.30",
                InspectorFormat.Fixed2(ExtNPC.Data.CsvParse.Double("39.305")));
            Assert.AreEqual("39.31",
                InspectorFormat.Fixed2(ExtNPC.Data.CsvParse.Float("39.305")));
        }

        [Test]
        public void EveryNumberFormatterIsCultureProof()
        {
            UnderGermanCulture(() =>
            {
                // Under de-DE the ambient decimal separator is a comma. Each of
                // these would render "0,0625" / "168,3 cm" / "+0,21" if the
                // formatter had used the ambient culture, and the dashboard
                // would be showing the same villager different text.
                Assert.AreEqual("0.0625", InspectorFormat.FmtF(0.0625));
                Assert.AreEqual("168.3 cm", InspectorFormat.Height(168.34));
                Assert.AreEqual("+0.21", InspectorFormat.Signed2(0.213));
                Assert.AreEqual("-0.21", InspectorFormat.Signed2(-0.213));
                Assert.AreEqual("41.55", InspectorFormat.Fixed2(41.554));
                Assert.AreEqual("0.973", InspectorFormat.Fixed3(0.9734));
                Assert.AreEqual("+1.2 y", InspectorFormat.SignedYears(1.24));
                Assert.AreEqual("-1.31 cm", InspectorFormat.StatureCost(-1.312));
                Assert.AreEqual("+0.0701", InspectorFormat.Signed4(0.07014));
            });
        }

        [Test]
        public void PercentagesRenderWithoutASpaceLikePythonsPercentFormat()
        {
            // THE trap this formatter exists for. Python's f"{p:.0%}" gives
            // "50%". C#'s ToString("P0", InvariantCulture) gives "50 %" --
            // invariant culture's percent pattern inserts a space before the
            // sign. Both look correct in isolation, and the acceptance
            // criterion for this stage is a character-for-character match, so
            // the near-miss IS the failure.
            Assert.AreEqual("50%", InspectorFormat.Percent0(0.5));
            Assert.AreEqual("87%", InspectorFormat.Percent0(0.8734));
            Assert.AreEqual("100%", InspectorFormat.Percent0(1));
            UnderGermanCulture(() =>
                Assert.AreEqual("50%", InspectorFormat.Percent0(0.5)));
        }

        // ------------------------------------------------------------------
        // stature: the #13 rule, at the point it becomes visible text
        // ------------------------------------------------------------------

        [Test]
        public void AGrowingIndividualShowsBothStaturesAndAGrownOneShowsOne()
        {
            // Showing only the mature value renders a child adult-sized and
            // looks entirely normal; showing only the expressed value hides
            // the genetic endpoint the child is growing toward. The dashboard
            // shows both while they differ (inspector.py:290) and this
            // reproduces its spacing, arrow and rounding exactly.
            Assert.AreEqual("112.4 cm  → 171 adult",
                            InspectorFormat.HeightLive(112.4, 171.2));
            Assert.AreEqual("171.2 cm",
                            InspectorFormat.HeightLive(171.2, 171.2));
            Assert.IsFalse(InspectorFormat.IsGrowing(171.20, 171.23),
                           "a 0.03 cm gap is not growth");
            Assert.IsTrue(InspectorFormat.IsGrowing(171.2, 171.5));
        }

        [Test]
        public void BmiIsLabelledAtMaturityWhileTheIndividualIsStillGrowing()
        {
            // #13 models stature only -- Preece-Baines is a height curve and
            // the engine has no body-mass trajectory -- so there is nothing to
            // age-express BMI with. The bare number put "BMI 24.4" against a
            // three-year-old, which is not a possible value for a toddler.
            Assert.AreEqual("24.4 at maturity", InspectorFormat.Bmi(24.42, true));
            Assert.AreEqual("24.4", InspectorFormat.Bmi(24.42, false));
        }

        // ------------------------------------------------------------------
        // colour thresholds -- inspector.py:120, 340
        // ------------------------------------------------------------------

        [Test]
        public void InbreedingColoursTurnAtTheStandardConsanguinityMarks()
        {
            Assert.AreEqual(InspectorFormat.Crit, InspectorFormat.FColor(0.0625));
            Assert.AreEqual(InspectorFormat.Warn, InspectorFormat.FColor(0.015625));
            Assert.AreEqual(InspectorFormat.Ink, InspectorFormat.FColor(0.01));
            Assert.AreEqual(InspectorFormat.Ink, InspectorFormat.FColor(0));
        }

        [Test]
        public void ViabilityAndAgeAccelerationUseTheDashboardsCutoffs()
        {
            Assert.AreEqual(InspectorFormat.Crit, InspectorFormat.ViabilityColor(0.89));
            Assert.AreEqual(InspectorFormat.Ink, InspectorFormat.ViabilityColor(0.9));
            Assert.AreEqual(InspectorFormat.Crit, InspectorFormat.EpiAccelColor(3.1));
            Assert.AreEqual(InspectorFormat.Ink, InspectorFormat.EpiAccelColor(3));
        }

        [Test]
        public void TheStressMeterUsesTheDashboardsRange()
        {
            // _norm(stress, -1.5, 2.5): a meter on a different range tells a
            // different story about the same number.
            Assert.AreEqual(0f, InspectorFormat.Norm(-1.5, -1.5, 2.5), 1e-5f);
            Assert.AreEqual(1f, InspectorFormat.Norm(2.5, -1.5, 2.5), 1e-5f);
            Assert.AreEqual(0.375f, InspectorFormat.Norm(0, -1.5, 2.5), 1e-5f);
            // clamped, not extrapolated
            Assert.AreEqual(0f, InspectorFormat.Norm(-9, -1.5, 2.5), 1e-5f);
            Assert.AreEqual(1f, InspectorFormat.Norm(9, -1.5, 2.5), 1e-5f);
        }

        // ------------------------------------------------------------------
        // names
        // ------------------------------------------------------------------

        [Test]
        public void TheDisplayNameIsTheGivenNameOnly()
        {
            // The engine's key is "Given-NNNN" and every dashboard surface
            // shows the part before the first dash.
            Assert.AreEqual("Elira", InspectorFormat.GivenName("Elira-1"));
            Assert.AreEqual("Sena", InspectorFormat.GivenName("Sena-1042"));
            Assert.AreEqual("", InspectorFormat.GivenName(""));
            Assert.AreEqual("Plain", InspectorFormat.GivenName("Plain"));
        }
    }
}
