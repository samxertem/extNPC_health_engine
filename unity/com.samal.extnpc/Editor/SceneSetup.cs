using ExtNPC.View;
using UnityEditor;
using UnityEngine;

namespace ExtNPC.Editor
{
    /// <summary>
    /// Build a working viewer in one click.
    ///
    /// Hand-wiring four components is where a package loses people, and every
    /// minute spent on it is a minute not spent looking at the village.
    /// </summary>
    public static class SceneSetup
    {
        [MenuItem("GameObject/extNPC/World Viewer", false, 10)]
        public static void CreateViewer()
        {
            // HumanMesh caches the result of its Resources lookup, including a
            // negative one. Dropping an MPFB body into Assets/Resources/extnpc/
            // and then building a viewer would otherwise give capsules until
            // the next domain reload, which looks like the body pack not
            // working rather than like a stale cache.
            HumanMesh.Forget();

            var root = new GameObject("extNPC World");
            var loader = root.AddComponent<ExtNpcWorldLoader>();
            var renderer = root.AddComponent<WorldRenderer>();
            // Added by default rather than left as an option: the renderer
            // already raises VillagerSelected, so without this the villagers
            // are clickable and clicking them appears to do nothing.
            root.AddComponent<VillagerInspector>();

            // Stage 5. The clock drives the renderer's year; the HUD is also
            // where manifest.json's `catalogue` becomes permanently visible,
            // which UNITY_PLAN.md §3.1 requires of any scene showing this data.
            // A viewer built without them would open on a single frozen year
            // and never say which model version produced it.
            root.AddComponent<WorldClock>();
            root.AddComponent<TimelineHud>();

            // Default to the engine repo's own export location, resolved
            // relative to the Unity project. Wrong as often as right, but it
            // makes the field's expected shape obvious at a glance.
            loader.absolutePathOverride = "";
            loader.worldName = "demo";

            var camGo = Camera.main != null
                ? Camera.main.gameObject
                : new GameObject("Main Camera", typeof(Camera), typeof(AudioListener));
            camGo.tag = "MainCamera";

            var orbit = camGo.GetComponent<OrbitCamera>();
            if (orbit == null) orbit = camGo.AddComponent<OrbitCamera>();
            orbit.FrameWorld(renderer.metresPerMapUnit);

            if (Object.FindObjectsByType<Light>(FindObjectsSortMode.None).Length == 0)
            {
                var lightGo = new GameObject("Directional Light");
                var light = lightGo.AddComponent<Light>();
                light.type = LightType.Directional;
                light.transform.rotation = Quaternion.Euler(50f, -30f, 0f);
            }

            Selection.activeGameObject = root;
            EditorGUIUtility.PingObject(root);

            Debug.Log("[extNPC] World Viewer created. Set the loader's " +
                      "'Absolute Path Override' to an exported bundle " +
                      "(python export_for_unity.py) and press Play.");
        }
    }
}
