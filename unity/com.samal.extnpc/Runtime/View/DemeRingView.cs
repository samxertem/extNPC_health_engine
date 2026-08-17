using ExtNPC.Data;
using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// A settlement's territory ring.
    ///
    /// The radius is the engine's own: `community.territory_radius` sets it to
    /// ~45% of the nearest-neighbour spacing, capped so no territory overhangs
    /// the map. It is drawn rather than invented so the ring means the same
    /// thing here as it does on the dashboard's canvas map.
    /// </summary>
    [AddComponentMenu("")]
    public sealed class DemeRingView : MonoBehaviour
    {
        private const int Segments = 64;

        private LineRenderer _line;

        public DemeRow Row { get; private set; }

        public static DemeRingView Create(Transform parent, Material shared)
        {
            var go = new GameObject("deme");
            go.transform.SetParent(parent, false);

            var v = go.AddComponent<DemeRingView>();
            v._line = go.AddComponent<LineRenderer>();
            v._line.useWorldSpace = false;
            v._line.loop = true;
            v._line.positionCount = Segments;
            v._line.widthMultiplier = 0.25f;
            v._line.sharedMaterial = shared;
            v._line.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            v._line.receiveShadows = false;
            return v;
        }

        /// <summary>
        /// A plain ring of fixed radius, for marking a place rather than a
        /// territory.
        ///
        /// Shares this class's circle geometry and material so a marker cannot
        /// end up looking like a different kind of object than a deme ring, but
        /// carries no <see cref="DemeRow"/>: it stands for nothing the engine
        /// measured, which is why it is a separate constructor rather than an
        /// Apply overload with a fabricated row.
        /// </summary>
        public static GameObject CreateMarker(Transform parent, Material shared,
                                              string name)
        {
            // Sized against a BODY, not against the map. A villager is 0.38 m
            // wide and up to ~1.9 m tall, and the first version used a 0.85 m
            // ring at 0.06 width, which measured correctly and was invisible:
            // from an orbit camera 80 m up it came to a few faint pixels under
            // one capsule among seventy. A marker that has to be hunted for is
            // not a marker.
            const float radius = 1.9f;
            const float stemHeight = 3.4f;

            var go = new GameObject(name);
            go.transform.SetParent(parent, false);

            var ring = MakeLine(go.transform, shared, Segments, true, 0.14f);
            for (int i = 0; i < Segments; i++)
            {
                float t = (float)i / Segments * Mathf.PI * 2f;
                ring.SetPosition(i, new Vector3(
                    Mathf.Cos(t) * radius, 0f, Mathf.Sin(t) * radius));
            }

            // A stem out of the ring, so the selection is findable from any
            // camera angle and over the heads of a crowded settlement. Purely a
            // pointer: it has no length in any quantity the engine models, and
            // is deliberately taller than the tallest villager so it cannot be
            // read as a stature.
            var stem = MakeLine(go.transform, shared, 2, false, 0.05f);
            stem.SetPosition(0, new Vector3(0f, 0f, 0f));
            stem.SetPosition(1, new Vector3(0f, stemHeight, 0f));

            return go;
        }

        private static LineRenderer MakeLine(Transform parent, Material shared,
                                             int points, bool loop, float width)
        {
            var go = new GameObject("line");
            go.transform.SetParent(parent, false);

            var line = go.AddComponent<LineRenderer>();
            line.useWorldSpace = false;
            line.loop = loop;
            line.positionCount = points;
            line.widthMultiplier = width;
            line.sharedMaterial = shared;
            line.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            line.receiveShadows = false;

            // White, and the only white lines in the scene. Deme rings are
            // tinted by their dominant bloodline, so a selection marker in any
            // lineage colour would read as a claim about ancestry.
            line.startColor = Color.white;
            line.endColor = Color.white;
            return line;
        }

        public void Apply(in DemeRow row, in MapProjection projection)
        {
            Row = row;

            Vector3 centre = projection.ToWorld(row.X, row.Y);
            float radius = projection.RadiusToWorld(row.Radius);

            transform.localPosition = centre + new Vector3(0f, 0.02f, 0f);

            for (int i = 0; i < Segments; i++)
            {
                float t = (float)i / Segments * Mathf.PI * 2f;
                _line.SetPosition(i, new Vector3(
                    Mathf.Cos(t) * radius, 0f, Mathf.Sin(t) * radius));
            }

            // Tinted by the settlement's DOMINANT bloodline, at the dominance
            // share the engine measured. A near-even settlement reads faint, a
            // lineage-captured one reads strong -- the same signal the
            // dashboard's dominance heatmap carries, from the same column.
            Color c = row.DominantColor;
            c.a = Mathf.Lerp(0.18f, 0.75f, Mathf.Clamp01(row.Dominance));
            _line.startColor = c;
            _line.endColor = c;

            gameObject.name = $"deme {row.Deme} (n={row.Count})";
        }

        public void SetVisible(bool visible)
        {
            if (gameObject.activeSelf != visible) gameObject.SetActive(visible);
        }
    }
}
