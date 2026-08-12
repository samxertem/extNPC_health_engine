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
            var root = new GameObject("extNPC World");
            var loader = root.AddComponent<ExtNpcWorldLoader>();
            var renderer = root.AddComponent<WorldRenderer>();

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
