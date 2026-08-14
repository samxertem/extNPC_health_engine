using ExtNPC.Data;
using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// A migration route between two settlements, from flows.csv.
    ///
    /// One row is one active route at one year: the engine's own
    /// `world.map_flows()` endpoints and a weight, which is recent gene flow
    /// along that route. Nothing is derived here -- the endpoints are deme
    /// centres the engine placed and the weight is a number it measured.
    ///
    /// LEGITIMATELY EMPTY. The default world has one deme, and with one
    /// settlement there is nowhere to migrate: flows.csv is then a header with
    /// no rows, which is a correct answer and not a missing file. A viewer that
    /// drew nothing and said nothing would leave the reader unable to tell
    /// those apart, so the HUD reports the route count rather than the ribbons
    /// silently being absent.
    ///
    /// WIDTH IS THE DASHBOARD'S RULE. panels.py:794 draws each route at
    /// `1 + 5 * weight / wmax`, where wmax is the largest weight IN THAT FRAME
    /// -- a relative encoding, so a quiet year's routes are not hairlines.
    /// The same profile is used here and only the unit differs (pixels there,
    /// metres here, through one named constant). Copying the numbers rather
    /// than inventing a nicer curve is what stops the two maps from ranking
    /// the same two routes differently.
    /// </summary>
    [AddComponentMenu("")]
    public sealed class FlowRibbonView : MonoBehaviour
    {
        /// <summary>Metres per unit of the dashboard's pixel-width profile.
        /// Purely a scale choice: the profile itself is panels.py's.</summary>
        public const float WidthUnitM = 0.12f;

        /// <summary>Height above the ground plane, so a ribbon does not
        /// z-fight with it. Cosmetic; the engine's map is flat.</summary>
        private const float LiftM = 0.05f;

        private LineRenderer _line;

        public FlowRow Row { get; private set; }

        /// <summary>panels.py:794 -- `width=1 + 5 * f["weight"] / wmax`.
        /// A route with no weight, or a frame whose maximum is zero, gets the
        /// baseline rather than a division by zero.</summary>
        public static float WidthProfile(float weight, float maxWeight) =>
            1f + 5f * (maxWeight > 0f ? Mathf.Clamp01(weight / maxWeight) : 0f);

        public static FlowRibbonView Create(Transform parent, Material shared)
        {
            var go = new GameObject("flow");
            go.transform.SetParent(parent, false);

            var v = go.AddComponent<FlowRibbonView>();
            v._line = go.AddComponent<LineRenderer>();
            v._line.useWorldSpace = false;
            v._line.positionCount = 2;
            v._line.sharedMaterial = shared;
            v._line.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            v._line.receiveShadows = false;
            return v;
        }

        public void Apply(in FlowRow row, float maxWeight, in MapProjection projection)
        {
            Row = row;

            Vector3 a = projection.ToWorld(row.X0, row.Y0) + Vector3.up * LiftM;
            Vector3 b = projection.ToWorld(row.X1, row.Y1) + Vector3.up * LiftM;

            transform.localPosition = Vector3.zero;
            _line.SetPosition(0, a);
            _line.SetPosition(1, b);
            _line.widthMultiplier = WidthUnitM * WidthProfile(row.Weight, maxWeight);

            // ACCENT at half opacity, exactly as the dashboard draws a route
            // (panels.py:793, `_rgba(ACCENT, 0.5)`). Whether the transparency
            // survives depends on the material's blend mode, which the package
            // does not dictate; the hue does not.
            Color c = InspectorFormat.Accent;
            c.a = 0.5f;
            _line.startColor = c;
            _line.endColor = c;

            gameObject.name = "flow " + row.Weight.ToString("F2",
                System.Globalization.CultureInfo.InvariantCulture);
        }

        public void SetVisible(bool visible)
        {
            if (gameObject.activeSelf != visible) gameObject.SetActive(visible);
        }
    }
}
