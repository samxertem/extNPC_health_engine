using ExtNPC.View;
using NUnit.Framework;

namespace ExtNPC.Tests
{
    /// <summary>
    /// The portrait's idle motion and framing, driven directly.
    ///
    /// <see cref="PortraitPose"/> is a pure struct precisely so this can exist:
    /// every property the animation claims is checkable here without a camera,
    /// a render texture or a Play session. What these cannot check is that the
    /// portrait is wired to the inspector, or that the face looks like a face.
    /// Those need eyes.
    ///
    /// The cases are chosen around the two claims the portrait makes: it is
    /// REPRODUCIBLE (invariant 5 forbids the viewer inventing variance, so the
    /// motion must be a function of the name and the clock, never of a random
    /// number), and it is BOUNDED (a head that swings 90 degrees is not an idle
    /// animation, it is a bug that only shows up eleven seconds in).
    /// </summary>
    public class PortraitPoseTests
    {
        // ---- reproducibility ---------------------------------------------

        [Test]
        public void SameNameAndTimeGiveTheSamePose()
        {
            uint seed = PortraitPose.StableSeed("Selin-24");
            PortraitPose a = PortraitPose.Idle(12.5, seed);
            PortraitPose b = PortraitPose.Idle(12.5, seed);

            Assert.AreEqual(a.Yaw, b.Yaw);
            Assert.AreEqual(a.Pitch, b.Pitch);
            Assert.AreEqual(a.Bob, b.Bob);
            Assert.AreEqual(a.Blink, b.Blink);
        }

        [Test]
        public void TheSeedIsPinnedSoTheAnimationCannotSilentlyChange()
        {
            // Golden values, computed independently in Python from the same
            // FNV-1a-plus-finaliser definition. string.GetHashCode() is
            // explicitly NOT stable across .NET versions or even across runs,
            // and swapping it in here would make every villager animate
            // differently after an editor upgrade while every other test in
            // this file still passed. Pinning the numbers is what makes that
            // substitution visible.
            Assert.AreEqual(4056933007u, PortraitPose.StableSeed("Selin-24"));
            Assert.AreEqual(3731491809u, PortraitPose.StableSeed("Tomas-28"));
            Assert.AreEqual(2246831626u, PortraitPose.StableSeed("Nora-30"));
            Assert.AreEqual(1947474976u, PortraitPose.StableSeed(""));
        }

        [Test]
        public void NullNameDoesNotThrow()
        {
            Assert.DoesNotThrow(() => PortraitPose.StableSeed(null));
        }

        [Test]
        public void DifferentVillagersAreNotInLockstep()
        {
            // The whole reason phases are derived from the name. If two
            // villagers shared a phase the panel would look like a screensaver.
            uint a = PortraitPose.StableSeed("Selin-24");
            uint b = PortraitPose.StableSeed("Tomas-28");
            Assert.AreNotEqual(a, b);

            int differing = 0;
            for (double t = 0.0; t < 20.0; t += 0.25)
            {
                if (System.Math.Abs(PortraitPose.Idle(t, a).Yaw -
                                    PortraitPose.Idle(t, b).Yaw) > 0.5f) differing++;
            }
            Assert.Greater(differing, 60,
                "two villagers should mostly be at different points in the sway");
        }

        [Test]
        public void NamesThatDifferByOneCharacterGetUnrelatedPhases()
        {
            // FNV-1a alone clusters short similar strings; the finaliser is
            // what breaks that up, and villager names differ exactly like this.
            uint a = PortraitPose.StableSeed("Nora-30");
            uint b = PortraitPose.StableSeed("Nora-31");
            Assert.AreNotEqual(a, b);
            Assert.Greater(CountDifferingBits(a, b), 8,
                "one character of difference should not give an adjacent seed");
        }

        private static int CountDifferingBits(uint a, uint b)
        {
            uint x = a ^ b;
            int n = 0;
            while (x != 0) { n += (int)(x & 1u); x >>= 1; }
            return n;
        }

        // ---- bounds -------------------------------------------------------

        [Test]
        public void TheHeadStaysWithinItsStatedAmplitudes()
        {
            uint seed = PortraitPose.StableSeed("Darius-29");
            // Long enough to cover several glance periods, which is where a
            // naive sum of oscillators goes out of range.
            for (double t = 0.0; t < 300.0; t += 0.01)
            {
                PortraitPose p = PortraitPose.Idle(t, seed);
                Assert.LessOrEqual(System.Math.Abs(p.Yaw), 27.0f,
                    $"yaw out of range at t={t}");
                Assert.LessOrEqual(System.Math.Abs(p.Pitch), 3.5f,
                    $"pitch out of range at t={t}");
                Assert.LessOrEqual(System.Math.Abs(p.Bob), 0.006f,
                    $"bob out of range at t={t}");
                Assert.GreaterOrEqual(p.Blink, 0f);
                Assert.LessOrEqual(p.Blink, 1.0001f);
            }
        }

        [Test]
        public void TheHeadActuallyMoves()
        {
            // The mirror of the bounds test, and the one that fails if an
            // amplitude is ever zeroed "temporarily".
            uint seed = PortraitPose.StableSeed("Ceren-32");
            float lo = float.MaxValue, hi = float.MinValue;
            for (double t = 0.0; t < 30.0; t += 0.05)
            {
                float yaw = PortraitPose.Idle(t, seed).Yaw;
                if (yaw < lo) lo = yaw;
                if (yaw > hi) hi = yaw;
            }
            Assert.Greater(hi - lo, 12f, "the sway should be visible");
        }

        [Test]
        public void BlinksAreRareAndComplete()
        {
            uint seed = PortraitPose.StableSeed("Bora-33");
            int closedSamples = 0, total = 0;
            float peak = 0f;
            for (double t = 0.0; t < 60.0; t += 0.005)
            {
                float blink = PortraitPose.Idle(t, seed).Blink;
                if (blink > 0.5f) closedSamples++;
                if (blink > peak) peak = blink;
                total++;
            }
            Assert.Greater(peak, 0.98f, "a blink should fully close");
            Assert.Less(closedSamples / (double)total, 0.05,
                "eyes should be open almost all of the time");
        }

        [Test]
        public void TheGlanceIsOccasionalRatherThanConstant()
        {
            uint seed = PortraitPose.StableSeed("Sena-76");
            // Sample the yaw excursion beyond what the two sine terms can
            // produce on their own (13 + 2.6 = 15.6 degrees).
            int beyond = 0, total = 0;
            for (double t = 0.0; t < 120.0; t += 0.01)
            {
                if (System.Math.Abs(PortraitPose.Idle(t, seed).Yaw) > 16f) beyond++;
                total++;
            }
            Assert.Greater(beyond, 0, "the glance should sometimes fire");
            Assert.Less(beyond / (double)total, 0.25,
                "the glance should be a punctuation, not the default state");
        }

        // ---- framing -------------------------------------------------------

        [Test]
        public void TheCameraFramesExactlyTheIntendedSliceOfTheBody()
        {
            // The framing contract: at the returned distance, a vertical span
            // of FramedFraction * stature exactly fills the vertical fov.
            const float fov = CharacterPortrait.FovDeg;
            foreach (float stature in new[] { 0.75f, 1.2f, 1.754592f, 1.99f })
            {
                float d = PortraitPose.CameraDistance(stature, fov);
                double halfFov = fov * 0.5 * System.Math.PI / 180.0;
                double visible = 2.0 * d * System.Math.Tan(halfFov);
                Assert.AreEqual(stature * PortraitPose.FramedFraction, visible, 1e-4,
                    $"framing wrong at stature {stature}");
            }
        }

        [Test]
        public void AChildIsFramedLikeAnAdultRatherThanFromTheShouldersDown()
        {
            // Both the eye line and the framed slice scale with stature, so the
            // head occupies the same fraction of the picture at any size. This
            // is the property that makes one portrait rig work for a village
            // containing four-year-olds.
            float adult = PortraitPose.CameraDistance(1.75f, CharacterPortrait.FovDeg)
                          / PortraitPose.EyeHeight(1.75f);
            float child = PortraitPose.CameraDistance(0.98f, CharacterPortrait.FovDeg)
                          / PortraitPose.EyeHeight(0.98f);
            Assert.AreEqual(adult, child, 1e-5f);
        }

        [Test]
        public void EyeHeightUsesTheDocumentedConstant()
        {
            Assert.AreEqual(1.75f * HumanMesh.EyeHeightFraction,
                            PortraitPose.EyeHeight(1.75f), 1e-6f);
        }

        [Test]
        public void ADegenerateFieldOfViewDoesNotDivideByZero()
        {
            float d = PortraitPose.CameraDistance(1.75f, 0f);
            Assert.IsFalse(float.IsNaN(d));
            Assert.IsFalse(float.IsInfinity(d));
        }
    }
}
