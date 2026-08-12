using System.IO;
using ExtNPC.Data;
using UnityEngine;

namespace ExtNPC
{
    /// <summary>
    /// Stage 2 deliverable: find a bundle, load it, and say what it is.
    ///
    /// Deliberately does no rendering. Stage 3 adds the villagers; this
    /// component's only job is to prove the data contract works end to end and
    /// to hold the loaded <see cref="WorldBundle"/> for everything that comes
    /// after.
    /// </summary>
    [AddComponentMenu("extNPC/World Loader")]
    public sealed class ExtNpcWorldLoader : MonoBehaviour
    {
        [Tooltip("Folder under StreamingAssets/extnpc/ holding the bundle " +
                 "(manifest.json, people.csv, frames.csv, ...).")]
        public string worldName = "demo";

        [Tooltip("Absolute path, used instead of StreamingAssets when set. " +
                 "Convenient while iterating on exports from the engine.")]
        public string absolutePathOverride = "";

        [UnityEngine.Serialization.FormerlySerializedAs("loadOnAwake")]
        [Tooltip("Load in Start(), so views that subscribe in Awake() are " +
                 "listening in time.")]
        public bool loadOnStart = true;

        /// <summary>The loaded world. Null until Load() succeeds.</summary>
        public WorldBundle Bundle { get; private set; }

        /// <summary>Raised once a bundle is loaded, so views can build.</summary>
        public event System.Action<WorldBundle> Loaded;

        public string ResolvedPath =>
            string.IsNullOrEmpty(absolutePathOverride)
                ? Path.Combine(Application.streamingAssetsPath, "extnpc", worldName)
                : absolutePathOverride;

        // Loading happens in Start(), NOT Awake(), and the distinction is not
        // cosmetic: Unity runs every Awake() before any Start(), so a view that
        // subscribes to `Loaded` in its own Awake() is guaranteed to be
        // listening by the time this fires.
        //
        // The first version loaded in Awake() and the symptom was exactly as
        // bad as it was quiet -- the console printed a successful load and the
        // scene stayed empty, because WorldRenderer sat one component below in
        // the Awake order and subscribed after the event had already gone out.
        // No error, no warning, nothing to search for.
        //
        // Subscribers added even later are covered too: see
        // WorldRenderer.Awake, which checks `Bundle` and catches up.
        private void Start()
        {
            if (loadOnStart && Bundle == null) Load();
        }

        public bool Load()
        {
            string path = ResolvedPath;
            try
            {
                var sw = System.Diagnostics.Stopwatch.StartNew();
                Bundle = WorldBundle.Load(path);
                sw.Stop();

                Debug.Log($"[extNPC] {Bundle.Describe()} · {sw.ElapsedMilliseconds} ms");

                // The catalogue decides what these genotypes MEAN. Two exports
                // with the same seed under different catalogues are different
                // model versions, and nothing in the numbers says so -- so the
                // experimental one is called out rather than merely recorded.
                if (Bundle.Manifest.Catalogue == "empirical")
                {
                    Debug.LogWarning(
                        "[extNPC] This world was built with the EXPERIMENTAL " +
                        "'empirical' locus catalogue, which is not validated " +
                        "(see health_engine/loci.py). Do not read its numbers " +
                        "as model results.");
                }

                if (Bundle.Manifest.Frames.Truncated)
                {
                    Debug.LogWarning(
                        $"[extNPC] The engine's snapshot ring overflowed: the " +
                        $"earliest retained year is {Bundle.FirstTick}, not 0. " +
                        $"Any timeline must be labelled from {Bundle.FirstTick}.");
                }

                // "It loaded fine and I see nothing" is the single most likely
                // confusion with this component, and it has exactly one cause
                // worth checking first: the bundle arrived and no view was
                // listening. Say so, rather than reporting success into a void.
                if (Loaded == null)
                {
                    Debug.LogWarning(
                        "[extNPC] bundle loaded, but nothing is listening for " +
                        "it — so nothing will be drawn. Add a WorldRenderer " +
                        "component to this GameObject (or use " +
                        "GameObject → extNPC → World Viewer).", this);
                }

                Loaded?.Invoke(Bundle);
                return true;
            }
            catch (BundleFormatException e)
            {
                // Fail loudly and specifically. A viewer that half-loads a
                // malformed bundle shows numbers that are not in the world,
                // which is worse than showing nothing.
                Debug.LogError($"[extNPC] cannot load bundle at '{path}': {e.Message}");
                return false;
            }
            catch (IOException e)
            {
                Debug.LogError($"[extNPC] I/O error reading '{path}': {e.Message}");
                return false;
            }
        }
    }
}
