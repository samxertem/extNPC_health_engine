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

            // The controls are otherwise undiscoverable -- OrbitCamera reads
            // raw input with no on-screen prompt. Requires TimelineHud (added
            // below) on the same object so the legend can sit above the
            // transport bar instead of guessing where it ends.
            root.AddComponent<ControlsHud>();

            // Stage 5. The clock drives the renderer's year; the HUD is also
            // where manifest.json's `catalogue` becomes permanently visible,
            // which UNITY_PLAN.md §3.1 requires of any scene showing this data.
            // A viewer built without them would open on a single frozen year
            // and never say which model version produced it.
            root.AddComponent<WorldClock>();
            root.AddComponent<TimelineHud>();

            // The dashboard link (N1), added DISABLED. Present so it is one
            // tick away in the inspector rather than something to be found in
            // the docs, and off so that opening a scene never starts writing to
            // the user's home directory unasked. It is the only component here
            // that touches anything outside the project.
            var bridge = root.AddComponent<ExtNPC.Sync.SessionSyncBridge>();
            bridge.enabled = false;

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

            // A new scene's default is a bright procedural sky, which reads
            // as a broken combination against the dark instrument-grey
            // ground WorldRenderer builds -- the two were never designed to
            // sit in the same shot. Matching the camera's clear colour and
            // the ambient light to the ground/HUD palette makes the whole
            // scene read as one thing again, the way the ground's own
            // "instrument, not game" comment already argues for.
            var cam = camGo.GetComponent<Camera>();
            if (cam != null)
            {
                cam.clearFlags = CameraClearFlags.SolidColor;
                cam.backgroundColor = InspectorFormat.Surface;
            }
            RenderSettings.skybox = null;
            // AMBIENT AS A GRADIENT, NOT ONE COLOUR. Flat ambient adds the
            // same light to a villager's scalp, their cheek and the underside
            // of their jaw, which is the one lighting condition under which a
            // human head looks like a painted egg: nothing in it tells the
            // eye which way is up. A three-band ambient costs exactly the
            // same to render and gives every curved surface a free vertical
            // gradient.
            //
            // The three colours are the ONE surface colour lifted and
            // dropped, not three new hues, so the palette InspectorFormat
            // pins against the dashboard is untouched -- the same reasoning
            // HudChrome uses for adding alpha but never a hex.
            RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Trilight;
            RenderSettings.ambientSkyColor = InspectorFormat.Surface * 1.35f;
            RenderSettings.ambientEquatorColor = InspectorFormat.Surface;
            RenderSettings.ambientGroundColor = InspectorFormat.Surface * 0.55f;
            // Fog reads as a depth cue here, the same reasoning WorldRenderer
            // already uses to justify the ground survey grid: an orbiting
            // camera over a flat plane otherwise gives the eye nothing to
            // judge distance against past a hundred metres or so.
            RenderSettings.fog = true;
            RenderSettings.fogMode = FogMode.Linear;
            RenderSettings.fogColor = InspectorFormat.Surface;
            float mapSpan = MapProjection.MapSize * renderer.metresPerMapUnit;
            RenderSettings.fogStartDistance = mapSpan * 0.6f;
            RenderSettings.fogEndDistance = mapSpan * 2.2f;

            if (Object.FindObjectsByType<Light>(FindObjectsSortMode.None).Length == 0)
            {
                var lightGo = new GameObject("Directional Light");
                var light = lightGo.AddComponent<Light>();
                light.type = LightType.Directional;
                light.transform.rotation = Quaternion.Euler(50f, -30f, 0f);
            }

            // A FIXED sun lights whichever side of a villager happens to face
            // it, which is the wrong side as often as the right one on an
            // orbiting camera -- the reported symptom was literally "I can't
            // see them". A light PARENTED to the camera, at identity local
            // rotation, always points wherever the camera is currently
            // looking, so whatever is on screen is lit from the viewer's own
            // side of it. No shadows: it is a fill light standing in for
            // "can you see the person", not a second sun.
            if (camGo.transform.Find("Camera Light") == null)
            {
                var fillGo = new GameObject("Camera Light");
                fillGo.transform.SetParent(camGo.transform, false);
                fillGo.transform.localRotation = Quaternion.identity;
                var fill = fillGo.AddComponent<Light>();
                fill.type = LightType.Directional;
                fill.intensity = 0.9f;
                fill.shadows = LightShadows.None;
            }

            // A RIM LIGHT, and the problem it solves is separation rather
            // than visibility. The sun and the camera fill both come from in
            // front, so a villager and the ground behind them are lit by the
            // same light from the same side and end up at nearly the same
            // value. At any distance the silhouette stops resolving and the
            // village reads as a texture on the ground rather than as people
            // standing on it.
            //
            // Behind and above, aimed back at the camera, cool, and weak.
            // Cool because a real back light is sky rather than sun, and the
            // slight hue difference against the warm front is what actually
            // separates the edge; weak because this is an edge highlight, not
            // a third opinion about how bright a villager is. Parented to the
            // camera for the same reason the fill is: a fixed one rims
            // whichever side happens to face it, which is the wrong side as
            // often as the right one under an orbiting camera.
            //
            // The PORTRAIT already had a rig like this. This is the world
            // view catching up to it.
            if (camGo.transform.Find("Rim Light") == null)
            {
                var rimGo = new GameObject("Rim Light");
                rimGo.transform.SetParent(camGo.transform, false);
                rimGo.transform.localRotation = Quaternion.Euler(-25f, 155f, 0f);
                var rim = rimGo.AddComponent<Light>();
                rim.type = LightType.Directional;
                rim.intensity = 0.55f;
                rim.color = new Color(0.78f, 0.86f, 1f);
                rim.shadows = LightShadows.None;
            }

            Selection.activeGameObject = root;
            EditorGUIUtility.PingObject(root);

            Debug.Log("[extNPC] World Viewer created. Set the loader's " +
                      "'Absolute Path Override' to an exported bundle " +
                      "(python export_for_unity.py) and press Play.");
        }
    }
}
