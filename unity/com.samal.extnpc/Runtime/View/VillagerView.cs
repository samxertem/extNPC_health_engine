using ExtNPC.Data;
using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// One villager on the map.
    ///
    /// Stage 3 draws a primitive, not a body — bodies are Phase B. What matters
    /// here is that every visual property is a *pure function of a frame row*,
    /// with no randomness and no derivation. A jitter or a random tint would
    /// invent variance the engine did not model, and the whole point of the
    /// viewer is that what you see is what the simulation produced.
    /// </summary>
    [AddComponentMenu("")]      // created in code, not from the Add Component menu
    public sealed class VillagerView : MonoBehaviour
    {
        /// <summary>Body width in metres. Not from the engine — there is no
        /// breadth trait — so it is a constant rather than a fabricated
        /// per-person value. See the note in <see cref="Apply"/>.</summary>
        public const float BodyWidthM = 0.38f;

        // Both names are set: URP's Lit shader uses _BaseColor, the built-in
        // pipeline's Standard uses _Color. Setting both means the package works
        // in either without the caller configuring anything.
        private static readonly int BaseColorId = Shader.PropertyToID("_BaseColor");
        private static readonly int ColorId = Shader.PropertyToID("_Color");

        private MeshFilter _filter;
        private MeshRenderer _renderer;
        private CapsuleCollider _collider;
        private MaterialPropertyBlock _block;

        /// <summary>The row this view last drew. Read by selection/inspection.</summary>
        public FrameRow Row { get; private set; }

        public string VillagerName => Row.Name;

        public static VillagerView Create(Transform parent, Material shared)
        {
            var go = new GameObject("villager");
            go.transform.SetParent(parent, false);
            go.layer = parent.gameObject.layer;

            var v = go.AddComponent<VillagerView>();
            v._filter = go.AddComponent<MeshFilter>();
            v._renderer = go.AddComponent<MeshRenderer>();
            v._renderer.sharedMaterial = shared;
            v._renderer.shadowCastingMode =
                UnityEngine.Rendering.ShadowCastingMode.Off;   // hundreds of these
            v._collider = go.AddComponent<CapsuleCollider>();
            v._block = new MaterialPropertyBlock();
            return v;
        }

        /// <summary>
        /// Draw <paramref name="row"/>.
        ///
        /// TWO RULES, both enforced by tests in the engine repo because both are
        /// invisible when broken:
        ///
        /// 1. <b>Height is <c>row.HeightCm</c>, the stature expressed AT THIS
        ///    AGE</b> — never people.csv's mature <c>trait_height_cm</c>.
        ///    Reaching for the mature value renders every child adult-sized,
        ///    which looks entirely normal until you notice the village has no
        ///    children in it. simulation/snapshots.py draws this distinction on
        ///    purpose; undoing it here would throw away the whole of roadmap #13.
        ///
        /// 2. <b>Colour is <c>row.Color</c>, parsed from the data.</b> The rule
        ///    that produced it — hue by founder lineage, saturation by ancestry
        ///    purity, value by alive/dead — lives once, in
        ///    simulation/lineage.py. Recomputing it here would create a second
        ///    definition, and the dashboard and the viewer would eventually
        ///    colour the same villager differently.
        /// </summary>
        public void Apply(in FrameRow row, in MapProjection projection)
        {
            Row = row;

            float heightM = Mathf.Max(row.HeightCm, 1f) * 0.01f;

            // Sex is encoded as SHAPE, not colour: colour is spoken for by
            // lineage, and a second meaning on the same channel makes both
            // unreadable. Capsule and cylinder are both body-shaped and tell
            // apart from directly above, which is the usual camera angle.
            _filter.sharedMesh = row.IsFemale
                ? PrimitiveMeshes.Capsule
                : PrimitiveMeshes.Cylinder;

            // Both primitives are 2 units tall and 1 unit wide at scale 1.
            // Width is a constant: the engine models stature, not breadth, and
            // scaling girth by BMI here would be a body measurement the
            // simulation never made. Phase B gets real bodies from MPFB; until
            // then an honest cylinder beats an invented one.
            transform.localScale = new Vector3(
                BodyWidthM, heightM * 0.5f, BodyWidthM);

            Vector3 ground = projection.ToWorld(row.X, row.Y);
            transform.localPosition = ground + new Vector3(0f, heightM * 0.5f, 0f);

            // Collider in local space; the transform scale above sizes it.
            _collider.height = 2f;
            _collider.radius = 0.5f;
            _collider.center = Vector3.zero;

            _renderer.GetPropertyBlock(_block);
            Color c = row.Color;
            _block.SetColor(BaseColorId, c);
            _block.SetColor(ColorId, c);
            _renderer.SetPropertyBlock(_block);

            gameObject.name = row.Name;
        }

        public void SetVisible(bool visible)
        {
            if (gameObject.activeSelf != visible) gameObject.SetActive(visible);
        }
    }
}
