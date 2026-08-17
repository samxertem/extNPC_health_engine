using ExtNPC.View;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;

namespace ExtNPC.Tests
{
    /// <summary>
    /// The body-mesh normalisation, on synthetic meshes.
    ///
    /// WHY IT MATTERS ENOUGH TO TEST. Session 22 measured, in a running Unity,
    /// that an MPFB FBX leaves its mesh datablock in CENTIMETRES with Blender's
    /// Z still acting as the up axis: a 1.754592 m character's
    /// <c>mesh.bounds.size</c> reads <c>(0.0114, 0.0048, 0.0175)</c>, and Unity
    /// hangs the correction on the imported hierarchy's transform instead.
    /// <see cref="HumanMesh.Bake"/> exists to fold that transform into the
    /// vertices, and <see cref="HumanMesh.Normalise"/> is the half of it that
    /// can be checked without shipping an FBX into the repository.
    ///
    /// The contract being pinned is the one <see cref="VillagerView"/> relies
    /// on: soles exactly on y=0, exactly 1 m tall, centred in x and z. Get any
    /// of the three wrong and the village is buried, the wrong size, or leaning
    /// off its own feet, and only the second is obvious in a screenshot.
    /// </summary>
    public class HumanMeshTests
    {
        private static Mesh Box(Vector3 lo, Vector3 hi)
        {
            var mesh = new Mesh
            {
                vertices = new[]
                {
                    new Vector3(lo.x, lo.y, lo.z), new Vector3(hi.x, lo.y, lo.z),
                    new Vector3(lo.x, hi.y, lo.z), new Vector3(hi.x, hi.y, lo.z),
                    new Vector3(lo.x, lo.y, hi.z), new Vector3(hi.x, lo.y, hi.z),
                    new Vector3(lo.x, hi.y, hi.z), new Vector3(hi.x, hi.y, hi.z),
                },
            };
            mesh.RecalculateBounds();
            return mesh;
        }

        private static void Extents(Mesh mesh, out Vector3 lo, out Vector3 hi)
        {
            Vector3[] v = mesh.vertices;
            lo = v[0];
            hi = v[0];
            for (int i = 1; i < v.Length; i++)
            {
                lo = Vector3.Min(lo, v[i]);
                hi = Vector3.Max(hi, v[i]);
            }
        }

        [Test]
        public void NormaliseStandsTheBodyOnTheOriginAtUnitHeight()
        {
            // Deliberately off in every axis at once: not centred, not on the
            // ground, and not 1 m tall.
            Mesh mesh = Box(new Vector3(-0.4f, 0.35f, 1.2f),
                            new Vector3(0.9f, 2.10f, 1.7f));

            HumanMesh.Normalise(mesh, out float authored);

            Assert.AreEqual(1.75f, authored, 1e-5f,
                "the pre-normalisation stature is the number a scale check cites");

            Extents(mesh, out Vector3 lo, out Vector3 hi);
            Assert.AreEqual(0f, lo.y, 1e-5f, "soles must sit on y=0");
            Assert.AreEqual(1f, hi.y - lo.y, 1e-5f, "must be exactly 1 m tall");
            Assert.AreEqual(0f, (lo.x + hi.x) * 0.5f, 1e-5f, "must be centred in x");
            Assert.AreEqual(0f, (lo.z + hi.z) * 0.5f, 1e-5f, "must be centred in z");
        }

        [Test]
        public void ProportionsSurviveNormalisation()
        {
            // Normalising must not squash: only a uniform scale is allowed,
            // because VillagerView then applies a uniform scale of its own and
            // two non-uniform scales would compound into a distorted body.
            Mesh mesh = Box(new Vector3(-0.55f, 0f, -0.2f),
                            new Vector3(0.55f, 1.6f, 0.2f));
            HumanMesh.Normalise(mesh, out _);

            Extents(mesh, out Vector3 lo, out Vector3 hi);
            Assert.AreEqual(1.10f / 1.6f, hi.x - lo.x, 1e-5f);
            Assert.AreEqual(0.40f / 1.6f, hi.z - lo.z, 1e-5f);
        }

        [Test]
        public void ScalingAUnitBodyByStatureReproducesTheAuthoredHeight()
        {
            // The round trip VillagerView performs, stated as an assertion:
            // normalise, then scale by height_cm/100, and you are back to the
            // stature the exporter authored. This is the Unity half of Stage
            // 6's acceptance criterion, in a test rather than in a screenshot.
            const float authoredHeight = 1.754592f;
            Mesh mesh = Box(new Vector3(-0.57f, 0.13f, -0.24f),
                            new Vector3(0.57f, 0.13f + authoredHeight, 0.24f));

            HumanMesh.Normalise(mesh, out float authored);
            Assert.AreEqual(authoredHeight, authored, 1e-5f);

            Extents(mesh, out Vector3 lo, out Vector3 hi);
            float rendered = (hi.y - lo.y) * authoredHeight;
            Assert.AreEqual(authoredHeight, rendered, 1e-4f);
        }

        [Test]
        public void AFlatMeshDoesNotDivideByZero()
        {
            // A mesh with no height is malformed input rather than an expected
            // one, but it must not produce NaN vertices: those propagate into
            // the bounds, and a NaN bound makes the whole village vanish from
            // culling with no error in the console.
            Mesh mesh = Box(new Vector3(-1f, 0.5f, -1f), new Vector3(1f, 0.5f, 1f));
            HumanMesh.Normalise(mesh, out float authored);

            Assert.AreEqual(0f, authored);
            foreach (Vector3 v in mesh.vertices)
            {
                Assert.IsFalse(float.IsNaN(v.x) || float.IsNaN(v.y) || float.IsNaN(v.z));
            }
        }

        [Test]
        public void AnEmptyMeshIsSurvivable()
        {
            var mesh = new Mesh();
            Assert.DoesNotThrow(() => HumanMesh.Normalise(mesh, out _));
        }

        [Test]
        public void BakingNothingReportsRatherThanCrashes()
        {
            // The absence of a body is a SUPPORTED state, not a failure: the
            // package ships no assets by design. Bake must return null so
            // VillagerView falls back to primitives.
            LogAssert.Expect(UnityEngine.LogType.Warning, new System.Text.RegularExpressions.Regex("no mesh to bake"));
            var empty = new GameObject("empty");
            try
            {
                Assert.IsNull(HumanMesh.Bake(empty, out float authored));
                Assert.AreEqual(0f, authored);
            }
            finally
            {
                Object.DestroyImmediate(empty);
            }
        }

        [Test]
        public void BakingNullIsSurvivable()
        {
            Assert.IsNull(HumanMesh.Bake(null, out float authored));
            Assert.AreEqual(0f, authored);
        }

        [Test]
        public void TheEyeHeightConstantIsPlausibleAndDocumentedAsAConstant()
        {
            // Not engine data, and the test says so: the engine models stature
            // alone, so there is no per-person eye height to read. What can be
            // pinned is that the number stays anthropometrically sane, because
            // the portrait camera aims at it.
            Assert.Greater(HumanMesh.EyeHeightFraction, 0.90f);
            Assert.Less(HumanMesh.EyeHeightFraction, 0.96f);
        }
    }
}
