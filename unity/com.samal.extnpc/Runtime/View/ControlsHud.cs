using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// A one-line reminder of how to move, for whoever is not the person who
    /// wrote <see cref="OrbitCamera"/>.
    ///
    /// WHY THIS EXISTS AS ITS OWN COMPONENT. The controls are undiscoverable
    /// by design — OrbitCamera reads raw input with no on-screen prompt, which
    /// is fine while iterating alone and is the first thing a live demo trips
    /// over. This is chrome, not analysis: it names no quantity and derives
    /// nothing, so it carries none of TimelineHud's provenance obligations and
    /// does not need to mirror the dashboard.
    ///
    /// BOTTOM-LEFT, JUST ABOVE THE TRANSPORT BAR. TimelineHud owns the
    /// top-left world panel and the bottom transport bar; VillagerInspector
    /// owns the right edge. This reads TimelineHud's own barHeight, when
    /// there is one on the same object, so the two never overlap even if
    /// that field is retuned later.
    /// </summary>
    [AddComponentMenu("extNPC/Controls HUD")]
    public sealed class ControlsHud : MonoBehaviour
    {
        [Tooltip("H toggles this at runtime; this is only the state at load.")]
        public bool show = true;

        private const string Hint =
            "drag/alt+drag orbit · scroll zoom · WASD+QE move " +
            "· shift boost · click select · H hide this";

        private TimelineHud _timeline;
        private GUIStyle _style;

        private void Awake() => _timeline = GetComponent<TimelineHud>();

        private void Update()
        {
            if (InputCompat.HKeyPressedThisFrame) show = !show;
        }

        private void OnGUI()
        {
            if (!show) return;
            if (_style == null)
            {
                _style = new GUIStyle(GUI.skin.label)
                {
                    fontSize = 10,
                    normal = { textColor = InspectorFormat.Ink2 },
                };
            }

            // Laid out in the HUD's own units, not display pixels. See HudScale.
            HudScale.Begin();
            try
            {
                float clearance = (_timeline != null && _timeline.show
                    ? _timeline.barHeight + 12f
                    : 0f) + 12f;
                var content = new GUIContent(Hint);
                Vector2 size = _style.CalcSize(content);
                var area = new Rect(12f, HudScale.Height - clearance - size.y - 12f,
                                     size.x + 16f, size.y + 12f);
                HudChrome.Panel(area);
                GUI.Label(new Rect(area.x + 8f, area.y + 6f, size.x + 4f, size.y),
                          content, _style);
            }
            finally { HudScale.End(); }
        }
    }
}
