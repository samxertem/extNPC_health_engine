using ExtNPC.View;
using NUnit.Framework;
using UnityEngine;

namespace ExtNPC.Tests
{
    /// <summary>
    /// Which surface each part of a villager is drawn as, and the HUD's
    /// coordinate space.
    ///
    /// WHY THIS IS TESTED AT ALL, given that it is cosmetic. Two of these
    /// have a failure mode that renders perfectly and is wrong, which is this
    /// project's house failure: a slot array one element short silently drops
    /// every part after it, and a per-base material cache that misses turns
    /// into three material allocations per frame that nothing reports. Both
    /// look fine in a screenshot.
    /// </summary>
    public class BodyMaterialsTests
    {
        [TearDown]
        public void Cleanup()
        {
            BodyMaterials.Forget();
            SkinMaterials.Forget();
            HairCardMaterials.Forget();
            HudScale.userScale = 1f;
        }

        // ------------------------------------------------------------------
        // the channel vocabulary
        // ------------------------------------------------------------------

        [Test]
        public void EveryChannelTheBakeWritesHasASurface()
        {
            // The vocabulary is `mpfb/bake_bodies.py`'s, seen in a real
            // bodies.json: hair, skin, eyebrows, eyelashes, suit, eyes,
            // shoes, teeth, tongue. A channel that fell through to the
            // default would be drawn as flesh, which for a suit is wrong and
            // silent.
            Assert.AreEqual(BodyMaterials.Surface.Skin, BodyMaterials.SurfaceOf("skin"));
            Assert.AreEqual(BodyMaterials.Surface.Eyes, BodyMaterials.SurfaceOf("eyes"));
            Assert.AreEqual(BodyMaterials.Surface.Hair, BodyMaterials.SurfaceOf("hair"));
            Assert.AreEqual(BodyMaterials.Surface.Cloth, BodyMaterials.SurfaceOf("suit"));
            Assert.AreEqual(BodyMaterials.Surface.Cloth, BodyMaterials.SurfaceOf("clothes"));
            Assert.AreEqual(BodyMaterials.Surface.Cloth, BodyMaterials.SurfaceOf("shoes"));
            Assert.AreEqual(BodyMaterials.Surface.Flesh, BodyMaterials.SurfaceOf("teeth"));
            Assert.AreEqual(BodyMaterials.Surface.Flesh, BodyMaterials.SurfaceOf("tongue"));
        }

        [Test]
        public void EyebrowsAndEyelashesAreHairAndNotSkin()
        {
            // Item 4 of the viewer pass. They have no colour of their own in
            // the manifest, so they used to fall back to skin along with the
            // teeth, and a face with skin-coloured brows reads as wrong
            // before a viewer can say why. Their SURFACE follows the colour
            // that moved with them.
            Assert.AreEqual(BodyMaterials.Surface.Hair,
                            BodyMaterials.SurfaceOf("eyebrows"));
            Assert.AreEqual(BodyMaterials.Surface.Hair,
                            BodyMaterials.SurfaceOf("eyelashes"));
        }

        [Test]
        public void AnUnknownOrMissingChannelIsFleshRatherThanNothing()
        {
            // Mirrors the colour side's fallback-to-skin decision. A channel
            // arriving from a future bake should render as a slightly wrong
            // human, never as an untextured white shape.
            Assert.AreEqual(BodyMaterials.Surface.Flesh,
                            BodyMaterials.SurfaceOf("wings"));
            Assert.AreEqual(BodyMaterials.Surface.Flesh,
                            BodyMaterials.SurfaceOf(null));
            Assert.AreEqual(BodyMaterials.Surface.Flesh,
                            BodyMaterials.SurfaceOf(""));
        }

        [Test]
        public void ChannelsAreMatchedCaseInsensitively()
        {
            Assert.AreEqual(BodyMaterials.Surface.Hair, BodyMaterials.SurfaceOf("HAIR"));
            Assert.AreEqual(BodyMaterials.Surface.Skin, BodyMaterials.SurfaceOf("Skin"));
        }

        // ------------------------------------------------------------------
        // the slot array
        // ------------------------------------------------------------------

        [Test]
        public void ThereIsExactlyOneSlotPerSubmeshEvenWithNoChannels()
        {
            // THE LENGTH CONTRACT, and the reason it is first. A renderer
            // draws only as many submeshes as it has materials, so a
            // nine-submesh body on a shorter array loses every part past the
            // end and the villager renders as hair alone. That is not a
            // crash and not a warning; it is a person with no body.
            var slots = BodyMaterials.SlotsFor(9, null, null, null, null, null);
            Assert.AreEqual(9, slots.Length);
            foreach (var m in slots) Assert.IsNotNull(m);
        }

        [Test]
        public void FewerChannelsThanSubmeshesStillFillsEverySlot()
        {
            // A manifest and a mesh that disagree about how many parts there
            // are is a bundle-versioning problem, not a reason to stop
            // drawing the villager.
            var slots = BodyMaterials.SlotsFor(
                5, new[] { "skin", "hair" }, null, null, null, null);
            Assert.AreEqual(5, slots.Length);
            foreach (var m in slots) Assert.IsNotNull(m);
        }

        [Test]
        public void EachSurfaceGetsItsOwnMaterialAndPartsOfOneKindShareIt()
        {
            // The whole point: hair and cloth must not be the same material,
            // or they render as the same substance in different tints. And
            // two hair parts MUST share one, or the saving that makes this
            // affordable is gone.
            var slots = BodyMaterials.SlotsFor(
                4, new[] { "skin", "hair", "eyebrows", "suit" },
                null, null, null, null);

            Assert.AreNotSame(slots[1], slots[3], "hair and cloth share a material");
            Assert.AreNotSame(slots[0], slots[1], "skin and hair share a material");
            Assert.AreSame(slots[1], slots[2],
                           "two hair parts must share one material");
        }

        [Test]
        public void TheSkinSlotTakesTheDetailMapAndOnlyTheSkinSlot()
        {
            // Teeth and tongue are separate meshes with their own UVs, so
            // sampling the BODY's detail map on them would paint a lip
            // crease across a molar. They get flesh instead.
            var map = new Material(Shader.Find("Standard") ??
                                   Shader.Find("Sprites/Default"));
            var slots = BodyMaterials.SlotsFor(
                3, new[] { "skin", "teeth", "tongue" }, null, null, map, null);

            Assert.AreSame(map, slots[0]);
            Assert.AreNotSame(map, slots[1]);
            Assert.AreNotSame(map, slots[2]);
            Object.DestroyImmediate(map);
        }

        [Test]
        public void SkinFallsBackToFleshWhenNoMapIsInstalled()
        {
            // The package ships no assets, so no detail map is a SUPPORTED
            // state and not an error: the villager goes back to the flat tone
            // it had before, which is a worse picture and not a broken one.
            var slots = BodyMaterials.SlotsFor(
                1, new[] { "skin" }, null, null, null, null);
            Assert.AreSame(BodyMaterials.Flesh(null), slots[0]);
        }

        [Test]
        public void TheEyeSlotFallsBackToFleshRatherThanToNull()
        {
            // A null in a material array draws the submesh with Unity's error
            // shader, which is magenta. Falling back to flesh keeps the flat
            // eye colour the viewer drew before the textures existed.
            var slots = BodyMaterials.SlotsFor(
                2, new[] { "skin", "eyes" }, null, null, null, null);
            Assert.IsNotNull(slots[1]);
            Assert.AreSame(BodyMaterials.Flesh(null), slots[1]);
        }

        // ------------------------------------------------------------------
        // the per-base cache
        // ------------------------------------------------------------------

        [Test]
        public void TwoBaseMaterialsDoNotEvictEachOther()
        {
            // THE BUG THIS EXISTS FOR, and it was written and then found
            // before it shipped. WorldRenderer passes its villagerMaterial
            // and CharacterPortrait passes its own portrait skin. With one
            // remembered base, whichever drew second invalidated the other,
            // so both rebuilt three materials EVERY FRAME, forever, and
            // nothing on screen would have looked wrong.
            Shader shader = Shader.Find("Standard") ?? Shader.Find("Sprites/Default");
            var world = new Material(shader) { name = "world" };
            var portrait = new Material(shader) { name = "portrait" };

            Material worldHair = BodyMaterials.Hair(world);
            Material portraitHair = BodyMaterials.Hair(portrait);

            Assert.AreNotSame(worldHair, portraitHair,
                              "two bases must get their own variants");
            Assert.AreSame(worldHair, BodyMaterials.Hair(world),
                           "asking again for the same base must not rebuild");
            Assert.AreSame(portraitHair, BodyMaterials.Hair(portrait));

            Object.DestroyImmediate(world);
            Object.DestroyImmediate(portrait);
        }

        [Test]
        public void TheSurfacesDifferInSmoothnessAndNotInMetal()
        {
            // Nothing on a villager is a metal, and the three smoothness
            // values are the entire reason this class exists.
            Assert.AreNotEqual(BodyMaterials.SkinSmoothness,
                               BodyMaterials.ClothSmoothness);
            Assert.AreNotEqual(BodyMaterials.HairSmoothness,
                               BodyMaterials.ClothSmoothness);
            Assert.Less(BodyMaterials.ClothSmoothness, BodyMaterials.SkinSmoothness,
                        "cloth is the most matte thing on a villager");
        }

        // ------------------------------------------------------------------
        // the skin age bands
        // ------------------------------------------------------------------

        [Test]
        public void TheAgeBandsAreTheOnesTheInstallerWrites()
        {
            // Pinned against `install_to_unity.skin_band_for_age` from the
            // Python side as well, because this rule has two implementations
            // and the viewer has to resolve a band with no Python in the
            // process.
            Assert.AreEqual("young", SkinMaterials.BandForAge(0f));
            Assert.AreEqual("young", SkinMaterials.BandForAge(44.9f));
            Assert.AreEqual("middleage", SkinMaterials.BandForAge(45f));
            Assert.AreEqual("middleage", SkinMaterials.BandForAge(64.9f));
            Assert.AreEqual("old", SkinMaterials.BandForAge(65f));
            Assert.AreEqual("old", SkinMaterials.BandForAge(120f));
        }

        [Test]
        public void AMissingSkinMapIsNullRatherThanAnException()
        {
            // No assets installed is the package's normal state.
            Assert.IsNull(SkinMaterials.For("nosuchband", "female"));
            Assert.IsNull(SkinMaterials.For(null, null));
        }

        // ------------------------------------------------------------------
        // brow and lash cutouts
        // ------------------------------------------------------------------

        [Test]
        public void AnEmptyAssetNameHasNoCard()
        {
            Assert.IsNull(HairCardMaterials.For(null));
            Assert.IsNull(HairCardMaterials.For(""));
            Assert.IsFalse(HairCardMaterials.Has(null));
        }

        [Test]
        public void ScalpHairIsNotGivenACutout()
        {
            // DELIBERATE, and measured. Hair assets run 38 to 100 percent
            // opaque -- `braid01` is a solid mesh with no cutout at all -- so
            // hair reads correctly as a volume, and `bob02`'s texture is a
            // light blonde whose colour would be double-counted against the
            // tint. Nothing installs a card for a hair asset, so a hair
            // submesh must fall through to the flat hair material.
            var slots = BodyMaterials.SlotsFor(
                1, new[] { "hair" }, new[] { "afro01" }, null, null, null);
            Assert.AreSame(BodyMaterials.Hair(null), slots[0]);
        }

        [Test]
        public void ABrowWithNoInstalledCardStillGetsAMaterial()
        {
            // The package ships no assets. Without the pack the brow falls
            // back to the flat hair material, and BodyLibrary separately
            // withholds the dark hair COLOUR in that case, so what renders
            // is the skin-toned card the viewer drew before -- a hidden
            // defect rather than a mascara-shaped one.
            var slots = BodyMaterials.SlotsFor(
                1, new[] { "eyebrows" }, new[] { "no_such_brow_asset" },
                null, null, null);
            Assert.IsNotNull(slots[0]);
            Assert.AreSame(BodyMaterials.Hair(null), slots[0]);
        }

        [Test]
        public void HasAgreesWithFor()
        {
            // Has() gates the COLOUR and For() supplies the MATERIAL. If the
            // two ever disagreed, a villager could be given a dark brow
            // colour without the alpha that makes it the right shape, which
            // is precisely the defect.
            foreach (var asset in new[] { "eyebrow001", "afro01", "nonsense" })
            {
                Assert.AreEqual(HairCardMaterials.For(asset) != null,
                                HairCardMaterials.Has(asset), asset);
            }
        }

        // ------------------------------------------------------------------
        // the HUD's coordinate space
        // ------------------------------------------------------------------

        [Test]
        public void TheHudNeverScalesBelowWhatItWasAuthoredAt()
        {
            // Below 1 the panels would be smaller than the numbers they were
            // laid out with and the hairlines would go sub-pixel, which no
            // display needs.
            HudScale.userScale = 0.01f;
            Assert.GreaterOrEqual(HudScale.Current, HudScale.MinScale);
        }

        [Test]
        public void TheHudNeverScalesOffItsOwnScreen()
        {
            HudScale.userScale = 99f;
            Assert.LessOrEqual(HudScale.Current, HudScale.MaxScale);
        }

        [Test]
        public void AZeroOrNegativeUserScaleCannotInvertTheHud()
        {
            // A negative matrix scale mirrors the whole HUD and a zero one
            // collapses it to a point. Both are recoverable only by editing
            // the field back, which is a bad thing to leave reachable.
            HudScale.userScale = 0f;
            Assert.GreaterOrEqual(HudScale.Current, HudScale.MinScale);
            HudScale.userScale = -3f;
            Assert.GreaterOrEqual(HudScale.Current, HudScale.MinScale);
        }
    }
}
