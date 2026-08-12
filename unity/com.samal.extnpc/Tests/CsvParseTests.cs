using System.Globalization;
using System.Threading;
using ExtNPC.Data;
using NUnit.Framework;

namespace ExtNPC.Tests
{
    /// <summary>
    /// The parser tests that can actually fail.
    ///
    /// Everything here targets a way the loader could silently produce wrong
    /// numbers rather than an error: a locale that reinterprets a decimal
    /// point, a naive split that shifts every field after a comma, a
    /// zero-byte file that looks like an empty table. None of these throw on
    /// their own, which is exactly why they need pinning.
    /// </summary>
    public class CsvParseTests
    {
        // ------------------------------------------------------------------
        // locale
        // ------------------------------------------------------------------

        [Test]
        public void FloatsParseTheSameUnderACommaDecimalLocale()
        {
            // Python writes 1.75 with a dot. Under de-DE, float.Parse with the
            // ambient culture returns 175 -- and does NOT throw. A villager 175
            // metres tall would be noticed; the same slip on a viability or
            // stress column would not.
            var previous = Thread.CurrentThread.CurrentCulture;
            try
            {
                Thread.CurrentThread.CurrentCulture = new CultureInfo("de-DE");
                Assert.AreEqual(1.75f, CsvParse.Float("1.75"), 1e-6f);
                Assert.AreEqual(-0.0762497f, CsvParse.Float("-0.0762497"), 1e-6f);
                Assert.AreEqual(169.544f, CsvParse.Float("169.544"), 1e-3f);
            }
            finally
            {
                Thread.CurrentThread.CurrentCulture = previous;
            }
        }

        [Test]
        public void PythonsSpellingsOfNonFiniteFloatsAreAccepted()
        {
            // json/csv from Python write nan and inf, not NaN and Infinity.
            Assert.IsNaN(CsvParse.Float("nan"));
            Assert.AreEqual(float.PositiveInfinity, CsvParse.Float("inf"));
            Assert.AreEqual(float.NegativeInfinity, CsvParse.Float("-inf"));
        }

        [Test]
        public void PythonsSpellingOfBooleansIsAccepted()
        {
            Assert.IsTrue(CsvParse.Bool("True"));       // csv.DictWriter's form
            Assert.IsFalse(CsvParse.Bool("False"));
        }

        [Test]
        public void AnEmptyCellMeansAbsentNotZero()
        {
            Assert.AreEqual(0, CsvParse.List("").Length);
            Assert.IsNaN(CsvParse.Float("", float.NaN));
        }

        [Test]
        public void SemicolonListsSplitIntoTheirEntries()
        {
            // mendelian_carrier_of and friends are ;-joined so the cell stays
            // one CSV field.
            CollectionAssert.AreEqual(new[] { "PAH", "SMN1" },
                CsvParse.List("PAH;SMN1"));
        }

        // ------------------------------------------------------------------
        // the CSV dialect
        // ------------------------------------------------------------------

        [Test]
        public void HeaderAndRowsAreReadInOrder()
        {
            using (var r = CsvReader.FromText("a,b,c\n1,2,3\n4,5,6\n"))
            {
                CollectionAssert.AreEqual(new[] { "a", "b", "c" }, r.Columns);
                Assert.IsTrue(r.ReadRow());
                CollectionAssert.AreEqual(new[] { "1", "2", "3" }, r.Current);
                Assert.IsTrue(r.ReadRow());
                CollectionAssert.AreEqual(new[] { "4", "5", "6" }, r.Current);
                Assert.IsFalse(r.ReadRow());
            }
        }

        [Test]
        public void AQuotedFieldMayContainACommaWithoutShiftingTheRow()
        {
            // The failure a naive Split(',') produces is not an exception --
            // it is every subsequent field landing in the wrong column, which
            // renders as plausible but wrong data.
            using (var r = CsvReader.FromText("a,b\n\"x,y\",z\n"))
            {
                Assert.IsTrue(r.ReadRow());
                Assert.AreEqual(2, r.Current.Count);
                Assert.AreEqual("x,y", r.Current[0]);
                Assert.AreEqual("z", r.Current[1]);
            }
        }

        [Test]
        public void DoubledQuotesBecomeOneLiteralQuote()
        {
            using (var r = CsvReader.FromText("a\n\"he said \"\"hi\"\"\"\n"))
            {
                Assert.IsTrue(r.ReadRow());
                Assert.AreEqual("he said \"hi\"", r.Current[0]);
            }
        }

        [Test]
        public void ANewlineInsideQuotesDoesNotEndTheRecord()
        {
            using (var r = CsvReader.FromText("a,b\n\"line1\nline2\",z\n"))
            {
                Assert.IsTrue(r.ReadRow());
                Assert.AreEqual("line1\nline2", r.Current[0]);
                Assert.AreEqual("z", r.Current[1]);
                Assert.IsFalse(r.ReadRow());
            }
        }

        [Test]
        public void EmptyFieldsSurviveAsEmptyStrings()
        {
            using (var r = CsvReader.FromText("a,b,c\n1,,3\n"))
            {
                Assert.IsTrue(r.ReadRow());
                CollectionAssert.AreEqual(new[] { "1", "", "3" }, r.Current);
            }
        }

        [Test]
        public void ALastLineWithoutATrailingNewlineIsStillARow()
        {
            using (var r = CsvReader.FromText("a,b\n1,2"))
            {
                Assert.IsTrue(r.ReadRow());
                CollectionAssert.AreEqual(new[] { "1", "2" }, r.Current);
                Assert.IsFalse(r.ReadRow());
            }
        }

        [Test]
        public void CrlfIsToleratedEvenThoughTheEngineWritesLf()
        {
            using (var r = CsvReader.FromText("a,b\r\n1,2\r\n"))
            {
                CollectionAssert.AreEqual(new[] { "a", "b" }, r.Columns);
                Assert.IsTrue(r.ReadRow());
                CollectionAssert.AreEqual(new[] { "1", "2" }, r.Current);
            }
        }

        [Test]
        public void AHeaderWithNoRowsIsAnEmptyTableNotAnAbsentOne()
        {
            // flows.csv and events.csv are legitimately empty in the default
            // single-deme, no-shock world. The engine writes their header for
            // exactly this reason: "zero rows" must be distinguishable from
            // "truncated download".
            using (var r = CsvReader.FromText("tick,x0,y0,x1,y1,w\n"))
            {
                Assert.IsFalse(r.IsEmpty);
                Assert.AreEqual(6, r.Columns.Length);
                Assert.IsFalse(r.ReadRow());
            }
        }

        [Test]
        public void ATrulyEmptyFileIsReportedAsEmpty()
        {
            using (var r = CsvReader.FromText(""))
            {
                Assert.IsTrue(r.IsEmpty);
                Assert.AreEqual(0, r.Columns.Length);
            }
        }

        [Test]
        public void AMissingRequiredColumnFailsLoudlyAndNamesTheHeader()
        {
            using (var r = CsvReader.FromText("a,b\n1,2\n"))
            {
                var e = Assert.Throws<BundleFormatException>(
                    () => r.RequireIndex("pedigree_f"));
                StringAssert.Contains("pedigree_f", e.Message);
                StringAssert.Contains("a, b", e.Message);
            }
        }
    }

    /// <summary>The manifest is the run's provenance; misreading it silently
    /// is how a scene ends up unable to say which engine build produced it.</summary>
    public class ManifestTests
    {
        private const string Sample = @"{
          ""bundle_schema"": 1,
          ""seed"": 7,
          ""tick"": 60,
          ""catalogue"": ""synthetic"",
          ""git_commit"": ""5522176e5b5770cc943235b97f2fddf2367b0e23"",
          ""frames"": {""n_frames"": 61, ""first_tick"": 0, ""last_tick"": 60,
                       ""max_frames"": 600, ""truncated"": false},
          ""params"": {""carrying_capacity"": 120},
          ""summary"": {""n_living"": 31, ""fst"": null},
          ""caveats"": [""people.csv is CROSS-SECTIONAL""]
        }";

        [Test]
        public void ProvenanceIsReadIncludingTheCatalogue()
        {
            var m = Manifest.Parse(Sample);
            Assert.AreEqual(1, m.BundleSchema);
            Assert.AreEqual(7, m.Seed);
            Assert.AreEqual("synthetic", m.Catalogue);
            Assert.AreEqual(61, m.Frames.NFrames);
            Assert.IsFalse(m.Frames.Truncated);
            Assert.AreEqual(1, m.Caveats.Count);
            StringAssert.Contains("synthetic", m.ToString());
        }

        [Test]
        public void ANullFstIsPreservedRatherThanBecomingZero()
        {
            // Undefined is not zero. With a single deme there is no partition
            // to estimate F_ST over, and the engine reports null on purpose.
            var m = Manifest.Parse(Sample);
            Assert.IsTrue(m.Summary["fst"].Type == Newtonsoft.Json.Linq.JTokenType.Null);
        }

        [Test]
        public void AFutureSchemaIsRefusedRatherThanMisread()
        {
            var m = Manifest.Parse(Sample.Replace("\"bundle_schema\": 1",
                                                  "\"bundle_schema\": 99"));
            Assert.Throws<BundleFormatException>(() => m.RequireSupportedSchema());
        }

        [Test]
        public void AManifestWithoutASchemaIsRefused()
        {
            var m = Manifest.Parse(@"{""seed"": 1}");
            Assert.Throws<BundleFormatException>(() => m.RequireSupportedSchema());
        }
    }
}
