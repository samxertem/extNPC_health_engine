using ExtNPC.View;
using NUnit.Framework;
using UnityEngine;

namespace ExtNPC.Tests
{
    /// <summary>
    /// The lineage ring (item A5), and the two ways it was wrong before it drew.
    ///
    /// Both failures measured perfectly and rendered nothing, which is the
    /// house failure mode: the ring reported enabled, the right size, at the
    /// right height, carrying the right colour, and was not on screen.
    /// </summary>
    public class LineageRingTests
    {
        [TearDown]
        public void Cleanup()
        {
            LineageRing.Forget();
        }

        [Test]
        public void TheRingIsDoubleSided()
        {
            // FAILURE 1. A single-winding annulus is backface-culled from one
            // side, and which side depends on how the winding lands in Unity's
            // handedness. The first version was culled from exactly the angle
            // the map camera uses, so the village went neutral and the family
            // colouring simply vanished. There is no camera position from which
            // a ground marker should disappear.
            Mesh mesh = LineageRing.SharedMesh();

            int up = 0, down = 0;
            foreach (Vector3 n in mesh.normals)
            {
                if (n.y > 0.5f) up++;
                else if (n.y < -0.5f) down++;
            }

            Assert.Greater(up, 0, "no upward-facing triangles");
            Assert.Greater(down, 0, "no downward-facing triangles, so the ring " +
                                    "is invisible from one side");
            Assert.AreEqual(up, down, "the two faces must cover the same ring");
        }

        [Test]
        public void TheRingIsWideEnoughToSurviveTheMapCamera()
        {
            // FAILURE 2. The first radius was 0.34 m with a 0.10 m band, which
            // is right at arm's length and a sub-pixel smudge from an orbit
            // camera 80 m up. DemeRingView had already recorded this lesson
            // after shipping a ring that "measured correctly and was
            // invisible". Thickness carries further than radius, so the band is
            // what this asserts on.
            Mesh mesh = LineageRing.SharedMesh();
            Bounds b = mesh.bounds;

            Assert.GreaterOrEqual(b.size.x, 1.5f,
                "a ring narrower than this vanishes at map range");

            float outer = b.size.x * 0.5f;
            float inner = float.MaxValue;
            foreach (Vector3 v in mesh.vertices)
            {
                float r = new Vector2(v.x, v.z).magnitude;
                if (r < inner) inner = r;
            }
            Assert.GreaterOrEqual(outer - inner, 0.3f,
                "the band must be broad enough to survive antialiasing");
        }

        [Test]
        public void TheRingIsFlat()
        {
            // It lies on the ground. Any thickness in y would make it a tube
            // that intersects the ankles.
            Assert.AreEqual(0f, LineageRing.SharedMesh().bounds.size.y, 1e-5f);
        }

        [Test]
        public void TheRingSitsAboveTheGroundButBelowTheAnkle()
        {
            Assert.Greater(LineageRing.HeightAboveGroundM, 0f,
                "coplanar with the ground would z-fight");
            Assert.Less(LineageRing.HeightAboveGroundM, 0.05f,
                "any higher and it cuts across the feet");
        }

        [Test]
        public void TheSharedMeshIsShared()
        {
            // One mesh for every villager: 600 rings must not be 600 meshes.
            Assert.AreSame(LineageRing.SharedMesh(), LineageRing.SharedMesh());
        }

        [Test]
        public void TheNeutralBodyColourIsNotDerivedFromAnything()
        {
            // It is a constant on purpose. `skin_tone` is modelled, but mapping
            // a unitless 0..1 to an albedo is a colour decision the engine has
            // not made, and inventing the ramp here would be the viewer
            // inventing variance in the channel a reader is most likely to read
            // as biology.
            Color c = LineageRing.NeutralBody;
            Assert.Greater(c.r, 0.5f);
            Assert.Greater(c.g, 0.5f);
            Assert.Greater(c.b, 0.5f);
            Assert.AreEqual(1f, c.a, 1e-5f);
        }
    }
}
