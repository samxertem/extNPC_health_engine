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
