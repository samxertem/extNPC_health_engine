using System.Collections.Generic;
using ExtNPC.Data;
using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// Stage 3: the village, on screen.
    ///
    /// Renders one tick's worth of <see cref="FrameRow"/> as pooled primitives.
    /// It computes nothing: positions, colours, statures and settlement radii
    /// all arrive from the bundle. The only numbers invented here are cosmetic
    /// and named as such (body width, ring segment count).
    /// </summary>
    [AddComponentMenu("extNPC/World Renderer")]
    [RequireComponent(typeof(ExtNpcWorldLoader))]
    public sealed class WorldRenderer : MonoBehaviour
    {
        [Header("Projection")]
        [Tooltip("Unity metres per engine map unit. The engine map is " +
                 "100x100 units, so 1.0 gives a 100x100 m world.")]
        public float metresPerMapUnit = 1f;

        public float groundY = 0f;

        [Header("Appearance")]
        [Tooltip("Material for villagers. Leave empty for an auto-created " +
                 "URP/Standard Lit material; per-villager colour is applied " +
                 "through a MaterialPropertyBlock either way, so one material " +
                 "serves the whole village.")]
        public Material villagerMaterial;

        public Material ringMaterial;
        public bool showDemeRings = true;
        public bool showGround = true;

        [Header("Time")]
        [Tooltip("Tick to display. Stage 5 replaces this with a real clock.")]
        public int tick;

        /// <summary>Fires when a villager is clicked. Stage 4's inspector
        /// listens; nothing in Stage 3 consumes it.</summary>
        public event System.Action<FrameRow> VillagerSelected;

        private ExtNpcWorldLoader _loader;
        private WorldBundle _bundle;
        private Transform _villagerRoot, _demeRoot;
        private GameObject _ground;

        // Pooled by NAME, not by index. A villager's row position within a
        // frame is not stable across ticks (the engine iterates the living, and
        // the living change), so an index-keyed pool would make people swap
        // bodies whenever someone died earlier in the list.
        private readonly Dictionary<string, VillagerView> _views =
            new Dictionary<string, VillagerView>();
        private readonly List<VillagerView> _spares = new List<VillagerView>();
        private readonly HashSet<string> _seen = new HashSet<string>();
        private readonly List<DemeRingView> _rings = new List<DemeRingView>();

        private int _renderedTick = int.MinValue;

        public MapProjection Projection => new MapProjection
        {
            MetresPerUnit = metresPerMapUnit,
            GroundY = groundY,
        };

        /// <summary>Villagers currently on screen. The acceptance check for
        /// this stage compares it with history.csv's n_alive.</summary>
        public int VisibleCount { get; private set; }

        private void Awake()
        {
            _loader = GetComponent<ExtNpcWorldLoader>();
            _loader.Loaded += OnLoaded;

            _villagerRoot = new GameObject("Villagers").transform;
            _villagerRoot.SetParent(transform, false);
            _demeRoot = new GameObject("Demes").transform;
            _demeRoot.SetParent(transform, false);

            // Catch up if the bundle was already loaded before this component
            // existed -- an explicit Load() call, a renderer added at runtime,
            // or a component order that put the loader first. Subscribing to
            // an event that has already fired is a silent no-op, and the
            // symptom is an empty scene with a healthy-looking console.
            if (_loader.Bundle != null) OnLoaded(_loader.Bundle);
        }

        private void OnDestroy()
        {
            if (_loader != null) _loader.Loaded -= OnLoaded;
        }

        private void OnLoaded(WorldBundle bundle)
        {
            _bundle = bundle;
            EnsureMaterials();
            if (showGround) BuildGround();

            tick = bundle.LastTick;
            Render(tick);
            VerifyHeadcountAgainstHistory();
        }

        private void Update()
        {
            if (_bundle == null) return;
            if (tick != _renderedTick) Render(tick);
            if (InputCompat.LeftPressedThisFrame) TrySelect();
        }

        // ------------------------------------------------------------------
        // rendering
        // ------------------------------------------------------------------

        public void Render(int atTick)
        {
            if (_bundle == null) return;

            var projection = Projection;
            FrameRow[] frame = _bundle.FrameAt(atTick);

            _seen.Clear();
            foreach (var row in frame)
            {
                if (!_views.TryGetValue(row.Name, out var view))
                {
                    view = Rent();
                    _views[row.Name] = view;
                }
                view.SetVisible(true);
                view.Apply(row, projection);
                _seen.Add(row.Name);
            }

            // Anyone not in this frame is not alive at this tick. Frames hold
            // the living only, so a death is an absence -- the view retires the
            // body to the pool rather than leaving a ghost standing.
            _retire.Clear();
            foreach (var kv in _views)
            {
                if (!_seen.Contains(kv.Key)) _retire.Add(kv.Key);
            }
            foreach (string name in _retire)
            {
                var view = _views[name];
                view.SetVisible(false);
                _spares.Add(view);
                _views.Remove(name);
            }

            if (showDemeRings) RenderDemes(atTick, projection);

            VisibleCount = frame.Length;
            _renderedTick = atTick;
        }

        private readonly List<string> _retire = new List<string>();

        private void RenderDemes(int atTick, in MapProjection projection)
        {
            DemeRow[] demes = _bundle.Demes.TryGetValue(atTick, out var d)
                ? d
                : System.Array.Empty<DemeRow>();

            while (_rings.Count < demes.Length)
                _rings.Add(DemeRingView.Create(_demeRoot, ringMaterial));

            for (int i = 0; i < _rings.Count; i++)
            {
                bool used = i < demes.Length;
                _rings[i].SetVisible(used);
                if (used) _rings[i].Apply(demes[i], projection);
            }
        }

        private VillagerView Rent()
        {
            int last = _spares.Count - 1;
            if (last >= 0)
            {
                var v = _spares[last];
                _spares.RemoveAt(last);
                return v;
            }
            return VillagerView.Create(_villagerRoot, villagerMaterial);
        }

        // ------------------------------------------------------------------
        // the acceptance check for this stage
        // ------------------------------------------------------------------

        /// <summary>
        /// Villagers drawn must equal the population the engine recorded for
        /// this year. Two independent tables -- frames.csv and history.csv --
        /// have to agree, and a pooling bug, a dropped row or a CSV
        /// misparse breaks the agreement.
        ///
        /// It is logged as an error rather than thrown: a viewer that refuses
        /// to render is less useful than one that renders and says loudly that
        /// it does not trust itself. But it must never pass silently, because
        /// "roughly the right number of capsules" is not something an eye can
        /// check.
        /// </summary>
        public bool VerifyHeadcountAgainstHistory()
        {
            if (_bundle == null) return false;

            HistoryRow year = null;
            foreach (var h in _bundle.History)
            {
                if (h.Tick == _renderedTick) { year = h; break; }
            }
            if (year == null || !year.Has("n_alive"))
            {
                Debug.Log($"[extNPC] no history row for year {_renderedTick}; " +
                          $"headcount unchecked.");
                return false;
            }

            int expected = Mathf.RoundToInt(year.Get("n_alive"));
            if (expected != VisibleCount)
            {
                Debug.LogError(
                    $"[extNPC] headcount mismatch at year {_renderedTick}: " +
                    $"{VisibleCount} villagers drawn from frames.csv but " +
                    $"history.csv records n_alive={expected}. The viewer is " +
                    $"not showing the world the engine simulated.");
                return false;
            }

            Debug.Log($"[extNPC] year {_renderedTick}: {VisibleCount} villagers " +
                      $"drawn, matching history.csv n_alive={expected}.");
            return true;
        }

        // ------------------------------------------------------------------
        // selection
        // ------------------------------------------------------------------

        private void TrySelect()
        {
            var cam = Camera.main;
            if (cam == null) return;
            if (!Physics.Raycast(cam.ScreenPointToRay(InputCompat.MousePosition),
                                 out RaycastHit hit, 5000f)) return;

            var view = hit.collider.GetComponent<VillagerView>();
            if (view != null) VillagerSelected?.Invoke(view.Row);
        }

        // ------------------------------------------------------------------
        // scene furniture
        // ------------------------------------------------------------------

        private void EnsureMaterials()
        {
            if (villagerMaterial == null)
                villagerMaterial = CreateDefaultMaterial("extNPC/Villager");
            if (ringMaterial == null)
                ringMaterial = CreateDefaultMaterial("extNPC/Ring");
        }

        private static Material CreateDefaultMaterial(string name)
        {
            // URP first, then the built-in pipeline. Failing to find either is
            // reported rather than silently producing magenta objects, which is
            // the usual and confusing symptom.
            Shader shader = Shader.Find("Universal Render Pipeline/Lit")
                            ?? Shader.Find("Standard")
                            ?? Shader.Find("Sprites/Default");
            if (shader == null)
            {
                Debug.LogError("[extNPC] no usable shader found; assign " +
                               "villagerMaterial manually.");
                return null;
            }
            return new Material(shader) { name = name };
        }

        private void BuildGround()
        {
            if (_ground != null) return;

            _ground = GameObject.CreatePrimitive(PrimitiveType.Plane);
            _ground.name = "Ground";
            _ground.transform.SetParent(transform, false);

            // Unity's plane primitive is 10x10 units at scale 1.
            float side = MapProjection.MapSize * metresPerMapUnit;
            _ground.transform.localScale = new Vector3(side / 10f, 1f, side / 10f);
            _ground.transform.localPosition = new Vector3(0f, groundY, 0f);

            var r = _ground.GetComponent<MeshRenderer>();
            r.sharedMaterial = CreateDefaultMaterial("extNPC/Ground");
            if (r.sharedMaterial != null)
            {
                var c = new Color(0.16f, 0.17f, 0.19f);
                r.sharedMaterial.SetColor("_BaseColor", c);
                r.sharedMaterial.SetColor("_Color", c);
            }
        }
    }
}
