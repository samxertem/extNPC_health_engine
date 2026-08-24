using System.Text.RegularExpressions;
using ExtNPC.View;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

namespace ExtNPC.Tests
{
    /// <summary>
    /// Reading `bodies.json`, and the one case in it that is silent.
    ///
    /// `body_stature_m` is the body's own height as Blender measured it
    /// UNDRESSED, and <see cref="HumanMesh"/> divides by it so that hair and
    /// shoes stand proud of a villager who is exactly 1 m tall. A body with no
    /// recorded stature falls back to measuring the whole mesh, which is right
    /// for the shared bodies (they wear nothing) and wrong for a dressed one
    /// (it loses the height of its own hair).
    ///
    /// The fallback cannot be an error, because bundles baked before the key
    /// existed are still legitimate. So the manifest has to say whether these
    /// bodies are dressed, and the mismatch has to be reported.
    /// </summary>
    public class BodyLibraryTests
    {
        [TearDown]
        public void Cleanup()
        {
            BodyLibrary.Forget();
        }

        private const string Dressed =
            "{\"appearance_channels\":{\"dressed\":true}," +
            "\"bodies\":[" +
            "{\"name\":\"A\",\"stem\":\"a\",\"body_stature_m\":1.75}," +
            "{\"name\":\"B\",\"stem\":\"b\",\"body_stature_m\":1.60}]}";

        private const string DressedMissingStature =
            "{\"appearance_channels\":{\"dressed\":true}," +
            "\"bodies\":[" +
            "{\"name\":\"A\",\"stem\":\"a\",\"body_stature_m\":1.75}," +
            "{\"name\":\"B\",\"stem\":\"b\"}]}";

        private const string BareNoStature =
            "{\"appearance_channels\":{\"dressed\":false}," +
            "\"bodies\":[{\"name\":\"A\",\"stem\":\"a\"}]}";

        [Test]
        public void ADressedManifestWithEveryStatureIsQuiet()
        {
            BodyLibrary.LoadManifest(Dressed);
            Assert.AreEqual(2, BodyLibrary.Declared);
        }

        [Test]
        public void ADressedBodyWithNoStatureIsReported()
        {
            // The symptom otherwise is a village that draws, counts and logs
            // correctly with everyone slightly too short. This is what running
            // export_bodies.py after bake_bodies.py looks like: the exporter
            // rewrites bodies.json from scratch and only the bake knows the
            // statures.
            LogAssert.Expect(LogType.Warning, new Regex("carry no body_stature_m"));
            BodyLibrary.LoadManifest(DressedMissingStature);
            Assert.AreEqual(2, BodyLibrary.Declared,
                "the village still draws; this is a warning, not a refusal");
        }

        [Test]
        public void AnUndressedManifestWithNoStatureIsNotAProblem()
        {
            // Bodies with nothing on them measure themselves correctly, so the
            // key is genuinely optional there. Warning here would train the
            // reader to ignore the warning that matters.
            BodyLibrary.LoadManifest(BareNoStature);
            Assert.AreEqual(1, BodyLibrary.Declared);
        }

        [Test]
        public void AManifestWithNoChannelBlockIsNotAProblem()
        {
            // Bundles predating `appearance_channels` are still readable.
            BodyLibrary.LoadManifest(
                "{\"bodies\":[{\"name\":\"A\",\"stem\":\"a\"}]}");
            Assert.AreEqual(1, BodyLibrary.Declared);
        }

        [Test]
        public void ForgetClearsTheStaturesToo()
        {
            BodyLibrary.LoadManifest(Dressed);
            BodyLibrary.Forget();
            Assert.AreEqual(0, BodyLibrary.Declared);

            // Reloading a manifest that has lost the key must then warn, which
            // it cannot do if the previous run's statures are still cached.
            LogAssert.Expect(LogType.Warning, new Regex("carry no body_stature_m"));
            BodyLibrary.LoadManifest(DressedMissingStature);
        }

        [Test]
        public void AnUnknownVillagerFallsBackToTheSharedBodyForTheirSex()
        {
            // The contract CharacterPortrait now depends on. It used to ask
            // HumanMesh directly for the shared male or female mesh, so every
            // woman in the village had the same face as every other woman, in
            // the one panel that exists BECAUSE somebody clicked a particular
            // person. It asks BodyLibrary now.
            //
            // The fallback is what makes that safe: a villager with no baked
            // body must still get a portrait, and it must be exactly the mesh
            // the old code would have used. Asserted by reference, and it holds
            // when both are null, which is the state of a package that ships no
            // assets.
            BodyLibrary.LoadManifest(Dressed);

            Assert.AreSame(HumanMesh.UnitBody(true),
                BodyLibrary.UnitBodyFor("nobody-by-that-name", true));
            Assert.AreSame(HumanMesh.UnitBody(false),
                BodyLibrary.UnitBodyFor("nobody-by-that-name", false));
        }

        [Test]
        public void ANullVillagerNameIsSurvivable()
        {
            // The portrait can be asked to draw before a selection exists.
            Assert.DoesNotThrow(() => BodyLibrary.UnitBodyFor(null, true));
        }

        [Test]
        public void MalformedJsonStillLeavesTheVillageDrawable()
        {
            LogAssert.Expect(LogType.Warning, new Regex("not readable"));
            BodyLibrary.LoadManifest("{ this is not json");
            Assert.AreEqual(0, BodyLibrary.Declared);
        }
    }
}
