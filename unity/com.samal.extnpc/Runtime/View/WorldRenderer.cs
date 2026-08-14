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

        [Tooltip("Draw migration routes from flows.csv. Empty in a single-deme " +
                 "world — with one settlement there is nowhere to migrate.")]
        public bool showFlows = true;

        [Header("Time")]
        [Tooltip("Year to display. Driven by WorldClock when one is attached; " +
                 "settable by hand otherwise.")]
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
        private readonly List<FlowRibbonView> _ribbons = new List<FlowRibbonView>();

        // Stage 5. The next retained year and how far toward it the display is
        // blended -- COSMETIC, position only, and zero unless a clock is
        // actively playing. See WorldClock.
        private int _nextTick;
        private float _alpha;

        // Reused so a 60 fps blend does not allocate a dictionary per frame.
        private readonly Dictionary<string, FrameRow> _nextByName =
            new Dictionary<string, FrameRow>();

        private int _renderedTick = int.MinValue;
        private float _renderedAlpha = -1f;

        public MapProjection Projection => new MapProjection
        {
            MetresPerUnit = metresPerMapUnit,
            GroundY = groundY,
        };

        /// <summary>Villagers the DISPLAYED YEAR has. The acceptance check for
        /// Stage 3 compares it with history.csv's n_alive, and Stage 5 re-runs
        /// that check at every year the scrub bar lands on — so this counts the
        /// year's own frame and deliberately excludes anyone who is only being
        /// previewed rising out of the ground for the year after.</summary>
        public int VisibleCount { get; private set; }

        /// <summary>Villagers born in the NEXT year, part-risen during a
        /// playback blend. Never counted as population: they are not alive in
        /// the year on screen.</summary>
        public int EmergingCount { get; private set; }

        /// <summary>Years whose headcount has been checked against
        /// history.csv, and how many disagreed. Surfaced by the HUD, because a
        /// check nobody can see the result of is a check nobody runs.</summary>
        public int HeadcountChecks { get; private set; }

        public int HeadcountMismatches { get; private set; }

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
            if (tick != _renderedTick || !Mathf.Approximately(_alpha, _renderedAlpha))
                Render(tick);
            if (InputCompat.LeftPressedThisFrame) TrySelect();
        }

        /// <summary>
        /// What to draw: a year, the year after it, and how far between them.
        ///
        /// Called by <see cref="WorldClock"/> every frame. `alpha` is COSMETIC
        /// and moves POSITIONS ONLY — see <see cref="Render"/>. A scene with no
        /// clock never calls this and simply sets <see cref="tick"/>, which
        /// leaves alpha at zero and shows exported frames exactly.
        /// </summary>
        public void SetTime(int year, int nextYear, float alpha)
        {
            tick = year;
            _nextTick = nextYear;
            _alpha = Mathf.Clamp01(alpha);
        }

        // ------------------------------------------------------------------
        // rendering
        // ------------------------------------------------------------------

        /// <summary>
        /// Draw the year, optionally blended toward the next one.
        ///
        /// THE ONE RULE IN THIS METHOD. Everything a villager IS comes from
        /// `frame`, the year on screen: stature, colour, stress, viability, F.
        /// The blend toward `next` touches the GROUND POSITION and nothing
        /// else. A stature that eased between two years would draw a growth
        /// curve the engine did not compute and would be indistinguishable
        /// from roadmap #13's real one; a stress level that eased would invent
        /// a physiological trajectory outright. tests/test_unity_contract.py
        /// forbids interpolating any frame field but x and y.
        ///
        /// And the blend animates less than it sounds: a villager's map
        /// position is `deme centre + person_map_offset(name)`
        /// (snapshots.py:66), a pure function of their deme and their name, so
        /// the only thing that ever moves between two years is somebody who
        /// migrated — an event the engine records as instantaneous.
        /// </summary>
        public void Render(int atTick)
        {
            if (_bundle == null) return;

            var projection = Projection;
            FrameRow[] frame = _bundle.FrameAt(atTick);

            bool blending = _alpha > 0f && _nextTick != atTick;
            _nextByName.Clear();
            if (blending)
            {
                foreach (var row in _bundle.FrameAt(_nextTick))
                    _nextByName[row.Name] = row;
            }

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

                if (!blending) continue;

                if (_nextByName.TryGetValue(row.Name, out FrameRow ahead))
                {
                    // Position only. Both endpoints are exported coordinates.
                    view.CosmeticBlendGround(Vector3.Lerp(
                        projection.ToWorld(row.X, row.Y),
                        projection.ToWorld(ahead.X, ahead.Y), _alpha));
                }
                else
                {
                    // Absent from the next frame: this villager dies during the
                    // year being played through. Sink rather than blink out.
                    view.CosmeticSetEmergence(1f - _alpha);
                }
            }

            // Born into the NEXT year: rise out of the ground as it arrives.
            // Drawn from their own row, so their stature is theirs and not an
            // interpolation, and counted separately — they are not alive in the
            // year on screen and must not enter the headcount.
            EmergingCount = 0;
            if (blending)
            {
                foreach (var kv in _nextByName)
                {
                    if (_seen.Contains(kv.Key)) continue;
                    if (!_views.TryGetValue(kv.Key, out var view))
                    {
                        view = Rent();
                        _views[kv.Key] = view;
                    }
                    view.SetVisible(true);
                    view.Apply(kv.Value, projection);
                    view.CosmeticSetEmergence(_alpha);
                    _seen.Add(kv.Key);
                    EmergingCount++;
                }
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
            if (showFlows) RenderFlows(atTick, projection);

            VisibleCount = frame.Length;

            // `first` keeps the tally honest: OnLoaded renders and then runs
            // the LOUD check itself, and counting both would report two checks
            // for one year.
            bool first = _renderedTick == int.MinValue;
            bool newYear = atTick != _renderedTick;
            _renderedTick = atTick;
            _renderedAlpha = _alpha;

            // Stage 3's acceptance check, re-run at every year the timeline
            // lands on rather than once at load. Silent while it agrees: a log
            // line per year would bury the mismatch it exists to surface. The
            // HUD shows the running tally instead.
            if (newYear && !first) CheckHeadcount(atTick, verbose: false);
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

        /// <summary>
        /// Migration routes for this year.
        ///
        /// The weight is normalised against the largest route IN THIS FRAME,
        /// which is the dashboard's own rule (panels.py:789 `wmax`). Normalising
        /// against the run's global maximum instead would make a quiet decade's
        /// routes invisible and would say something different from the map next
        /// to it.
        /// </summary>
        private void RenderFlows(int atTick, in MapProjection projection)
        {
            FlowRow[] flows = _bundle.Flows.TryGetValue(atTick, out var f)
                ? f
                : System.Array.Empty<FlowRow>();

            float maxWeight = 0f;
            for (int i = 0; i < flows.Length; i++)
                if (flows[i].Weight > maxWeight) maxWeight = flows[i].Weight;

            while (_ribbons.Count < flows.Length)
                _ribbons.Add(FlowRibbonView.Create(_demeRoot, ringMaterial));

            for (int i = 0; i < _ribbons.Count; i++)
            {
                bool used = i < flows.Length;
                _ribbons[i].SetVisible(used);
                if (used) _ribbons[i].Apply(flows[i], maxWeight, projection);
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
        public bool VerifyHeadcountAgainstHistory() =>
            CheckHeadcount(_renderedTick, verbose: true);

        /// <summary>
        /// The check itself, run at every year the timeline visits.
        ///
        /// `verbose` distinguishes the one-shot at load — which says out loud
        /// that it ran, because a check with no output is indistinguishable
        /// from no check — from the per-year run behind a scrub bar, which
        /// stays quiet while it agrees and shouts when it does not. A log line
        /// per year would bury the mismatch in ninety successes.
        ///
        /// A mismatch is logged as an error, not thrown: a viewer that renders
        /// and says loudly that it does not trust itself is more useful than
        /// one that refuses. The HUD carries the tally so a disagreement is
        /// visible on screen and not only in a console nobody has open.
        /// </summary>
        public bool CheckHeadcount(int atTick, bool verbose)
        {
            if (_bundle == null) return false;

            HistoryRow year = null;
            foreach (var h in _bundle.History)
            {
                if (h.Tick == atTick) { year = h; break; }
            }
            if (year == null || !year.Has("n_alive"))
            {
                if (verbose)
                    Debug.Log($"[extNPC] no history row for year {atTick}; " +
                              $"headcount unchecked.");
                return false;
            }

            HeadcountChecks++;
            int expected = (int)System.Math.Round(year.Get("n_alive"));
            if (expected != VisibleCount)
            {
                HeadcountMismatches++;
                Debug.LogError(
                    $"[extNPC] headcount mismatch at year {atTick}: " +
                    $"{VisibleCount} villagers drawn from frames.csv but " +
                    $"history.csv records n_alive={expected}. The viewer is " +
                    $"not showing the world the engine simulated.");
                return false;
            }

            if (verbose)
                Debug.Log($"[extNPC] year {atTick}: {VisibleCount} villagers " +
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
