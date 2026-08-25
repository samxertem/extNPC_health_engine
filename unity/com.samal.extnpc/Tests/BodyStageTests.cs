using System.Text.RegularExpressions;
using ExtNPC.View;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

namespace ExtNPC.Tests
{
    /// <summary>
    /// Per-life-stage bodies, on the reading side (item U6).
    ///
    /// The engine may now bake several bodies for one person, keyed
    /// <c>Name@stage</c>, so that scrubbing the timeline back to year 20 draws
    /// the child who was alive then rather than the adult they became. What is
    /// tested here is the LOOKUP, because the lookup is where the two bundle
    /// generations meet and where a mistake is silent: a body found for the
    /// wrong stage still renders, and a body not found at all falls back to a
    /// mesh that also renders.
    ///
    /// THE FALLBACK ORDER IS THE COMPATIBILITY STORY, so each step of it gets
    /// its own test: <c>Name@stage</c>, then <c>Name</c>, then the person's
    /// most mature baked body, then nothing. A staged bundle must give
    /// per-stage bodies; a legacy bundle must behave exactly as it did; a
    /// stage that was never baked must not fail; and a caller with no stage
    /// at all must still get that person's body rather than a shared mesh,
    /// which is the case `mpfb/unity_lineup.py` is and which broke first.
    ///
    /// These assert on the STEM MAP rather than on meshes, deliberately.
    /// Resolving a stem to a Mesh needs `Resources.Load` and an imported FBX,
    /// which an EditMode test has neither of; asserting that the right stem is
    /// selected is the part with logic in it, and the part that a bad key
    /// breaks.
    /// </summary>
    public class BodyStageTests
    {
        [TearDown]
        public void Cleanup()
        {
            BodyLibrary.Forget();
        }

        /// <summary>Ada lives through three stages; Bran is a founder who
        /// arrives grown and so has no childhood in this run.</summary>
        private const string Staged =
            "{\"bodies_schema\":2,\"staged\":true," +
            "\"appearance_channels\":{\"dressed\":false}," +
            "\"never_rendered\":[" +
            "{\"name\":\"Zoe-13\",\"age\":0.0,\"death_cause\":\"inbreeding\"," +
            "\"reason\":\"never alive at a captured tick\"}]," +
            "\"bodies\":[" +
            "{\"name\":\"Ada-16\",\"key\":\"Ada-16@child\",\"life_stage\":\"child\",\"age\":5.5,\"stem\":\"Ada-16_child\"}," +
            "{\"name\":\"Ada-16\",\"key\":\"Ada-16@adult\",\"life_stage\":\"adult\",\"age\":29.5,\"stem\":\"Ada-16_adult\"}," +
            "{\"name\":\"Ada-16\",\"key\":\"Ada-16@midlife\",\"life_stage\":\"midlife\",\"age\":48.5,\"stem\":\"Ada-16_midlife\"}," +
            "{\"name\":\"Bran-10\",\"key\":\"Bran-10@adult\",\"life_stage\":\"adult\",\"age\":37.0,\"stem\":\"Bran-10_adult\"}]}";

        /// <summary>A schema 1 bundle: one body per person, no `key`.</summary>
        private const string Legacy =
            "{\"bodies_schema\":1," +
            "\"bodies\":[" +
            "{\"name\":\"Ada-16\",\"stem\":\"Ada-16\"}," +
            "{\"name\":\"Bran-10\",\"stem\":\"Bran-10\"}]}";

        // ------------------------------------------------------------------
        // the key itself
        // ------------------------------------------------------------------

        [Test]
        public void AStageMakesACompoundKeyAndNoStageLeavesTheNameAlone()
        {
            Assert.AreEqual("Ada-16@child", BodyLibrary.KeyFor("Ada-16", "child"));
            Assert.AreEqual("Ada-16", BodyLibrary.KeyFor("Ada-16", null));
            Assert.AreEqual("Ada-16", BodyLibrary.KeyFor("Ada-16", ""));
        }

        [Test]
        public void AStagedManifestDeclaresBodiesNotPeople()
        {
            BodyLibrary.LoadManifest(Staged);

            // Four BODIES for three PEOPLE. A reader comparing Declared
            // against the village headcount needs to know which it is holding,
            // and this is the assertion that pins which.
            Assert.AreEqual(4, BodyLibrary.Declared);
            Assert.IsTrue(BodyLibrary.Staged);
        }

        [Test]
        public void ALegacyManifestIsNotStaged()
        {
            BodyLibrary.LoadManifest(Legacy);
            Assert.AreEqual(2, BodyLibrary.Declared);
            Assert.IsFalse(BodyLibrary.Staged,
                "a schema 1 bundle must not claim per-stage bodies");
        }

        // ------------------------------------------------------------------
        // the fallback chain, one test per step
        // ------------------------------------------------------------------

        [Test]
        public void AStagedBundleResolvesEachStageToItsOwnStem()
        {
            BodyLibrary.LoadManifest(Staged);

            // The assertion the whole feature rests on: one person, three
            // stages, three DIFFERENT bodies. Resolving them all to one stem
            // would satisfy every count in this file.
            Assert.AreEqual("Ada-16_child", BodyLibrary.StemFor("Ada-16", "child"));
            Assert.AreEqual("Ada-16_adult", BodyLibrary.StemFor("Ada-16", "adult"));
            Assert.AreEqual("Ada-16_midlife", BodyLibrary.StemFor("Ada-16", "midlife"));
        }

        [Test]
        public void AStagedBundleAskedForAStageItDidNotBakeFallsBackToThePerson()
        {
            BodyLibrary.LoadManifest(Staged);

            // Bran is a founder: he arrives aged 29, so his childhood is not
            // in this run and no `Bran-10@child` was baked. Asking for one
            // must not fail -- it falls through to the body he does have.
            // Returning null would drop him to the shared mesh, and his own
            // body at the wrong age is a far better picture than nobody's.
            Assert.AreEqual("Bran-10_adult", BodyLibrary.StemFor("Bran-10", "child"));
            Assert.AreEqual("Bran-10_adult", BodyLibrary.StemFor("Bran-10", "adult"));
        }

        [Test]
        public void ACallerWithNoStageGetsThePersonsMostMatureBody()
        {
            BodyLibrary.LoadManifest(Staged);

            // THE REGRESSION THIS CATCHES. `mpfb/unity_lineup.py` calls
            // `UnitBodyFor(name, female)` with no stage, and its entire
            // verdict is "did anyone fall back to a shared body". Against a
            // staged bundle every key is `Name@stage`, so a bare-name lookup
            // resolves nothing and the harness fails on all of them.
            //
            // Most mature, not first or arbitrary: that reproduces the pre-U6
            // semantic exactly, where `select_everyone` baked one body at the
            // person's age now or at death.
            Assert.AreEqual("Ada-16_midlife", BodyLibrary.StemFor("Ada-16", null));
            Assert.AreEqual("Ada-16_midlife", BodyLibrary.StemFor("Ada-16", ""));
        }

        [Test]
        public void TheMostMatureBodyIsPickedByAgeNotByManifestOrder()
        {
            // Ages deliberately descending, so a "last one wins" or "first one
            // wins" implementation picks the infant and passes nothing.
            BodyLibrary.LoadManifest(
                "{\"staged\":true,\"bodies\":[" +
                "{\"name\":\"C\",\"key\":\"C@senescent\",\"age\":71.0,\"stem\":\"c_old\"}," +
                "{\"name\":\"C\",\"key\":\"C@adult\",\"age\":30.0,\"stem\":\"c_adult\"}," +
                "{\"name\":\"C\",\"key\":\"C@infant\",\"age\":0.5,\"stem\":\"c_baby\"}]}");
            Assert.AreEqual("c_old", BodyLibrary.StemFor("C", null));
            Assert.AreEqual("c_baby", BodyLibrary.StemFor("C", "infant"));
        }

        [Test]
        public void ALegacyBundleAnswersAStagedRequestWithThePersonsOneBody()
        {
            BodyLibrary.LoadManifest(Legacy);

            // This is the step that keeps every existing bundle working. The
            // renderer now always passes a stage, so without the bare-name
            // fallback a schema 1 bundle would resolve NOTHING and the whole
            // village would drop to the shared mesh.
            Assert.AreEqual("Ada-16", BodyLibrary.StemFor("Ada-16", "child"));
            Assert.AreEqual("Ada-16", BodyLibrary.StemFor("Ada-16", "midlife"));
            Assert.AreEqual("Ada-16", BodyLibrary.StemFor("Ada-16", null));
        }

        [Test]
        public void AVillagerInNoManifestResolvesToNothing()
        {
            BodyLibrary.LoadManifest(Staged);
            Assert.IsNull(BodyLibrary.StemFor("Nobody-99", "adult"));
            Assert.IsNull(BodyLibrary.StemFor("Nobody-99", null));
            Assert.IsNull(BodyLibrary.StemFor(null, "adult"));
        }

        // ------------------------------------------------------------------
        // people who never had a body, which is not the same as a miss
        // ------------------------------------------------------------------

        [Test]
        public void AStillbirthIsNamedWithItsReasonRatherThanLeftMissing()
        {
            BodyLibrary.LoadManifest(Staged);

            // A plain miss and a person who was never renderable need opposite
            // treatment. Falling back to the shared ADULT mesh for a stillborn
            // infant is item U6's defect arrived at from the other side, so
            // the viewer has to be able to tell the two apart.
            string why = BodyLibrary.NeverRenderedReason("Zoe-13");
            Assert.IsNotNull(why, "the stillbirth must be named, not silently absent");
            StringAssert.Contains("inbreeding", why,
                "the reason should carry the cause the engine recorded");

            Assert.IsNull(BodyLibrary.NeverRenderedReason("Ada-16"),
                "a villager with a body must not be reported as never rendered");
            Assert.IsNull(BodyLibrary.NeverRenderedReason("Nobody-99"),
                "an unknown name is a miss, not a recorded stillbirth");
        }

        [Test]
        public void ALegacyBundleReportsNobodyAsNeverRendered()
        {
            // Absence of the key is not evidence that everyone was rendered,
            // but it is all an old bundle can say, and it must not invent an
            // answer either way.
            BodyLibrary.LoadManifest(Legacy);
            Assert.IsNull(BodyLibrary.NeverRenderedReason("Zoe-13"));
        }

        [Test]
        public void ForgetClearsTheStagedStateAndTheStillbirths()
        {
            BodyLibrary.LoadManifest(Staged);
            BodyLibrary.Forget();

            Assert.AreEqual(0, BodyLibrary.Declared);
            Assert.IsFalse(BodyLibrary.Staged);
            Assert.IsNull(BodyLibrary.NeverRenderedReason("Zoe-13"),
                "a stale stillbirth would suppress a later bundle's portrait");
        }

        [Test]
        public void AMalformedNeverRenderedBlockDoesNotStopTheBundleLoading()
        {
            // Same policy as the rest of this class: the village draws.
            BodyLibrary.LoadManifest(
                "{\"staged\":true,\"never_rendered\":[{\"age\":0.0}]," +
                "\"bodies\":[{\"name\":\"A\",\"key\":\"A@adult\",\"stem\":\"a\"}]}");
            Assert.AreEqual(1, BodyLibrary.Declared);
            Assert.AreEqual("a", BodyLibrary.StemFor("A", "adult"));
        }
    }
}
