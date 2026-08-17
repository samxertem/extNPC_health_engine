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

        [Tooltip("Survey grid on the ground, one line every 10 MAP units. " +
                 "Scale reference only; nothing about it comes from the data.")]
        public bool showGroundGrid = true;

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

        // Which villager the inspector is describing, by NAME rather than by
        // view: the views are pooled and the name is what survives a death.
        private string _selected;
        private GameObject _selectionRing;

        // Pooled by NAME, not by index. A villager's row position within a
        // frame is not stable across ticks (the engine iterates the living, and
        // the living change), so an index-keyed pool would make people swap
        // bodies whenever someone died earlier in the list.
        private readonly Dictionary<string, VillagerView> _views =
            new Dictionary<string, VillagerView>();
        private readonly List<VillagerView> _spares = new List<VillagerView>();
        private readonly HashSet<string> _seen = new HashSet<string>();

        // The scene half of the acceptance check, reused so a per-year
        // comparison over a few hundred names allocates nothing.
        private readonly HashSet<string> _drawn = new HashSet<string>();
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

        /// <summary>How many of those checks were able to include the scene
        /// half. Reported separately on purpose: the scene comparison only
        /// applies to the year actually on screen, and a guard that silently
        /// skipped every time would leave the check as blind as it was before
        /// while still reporting a rising tally.</summary>
        public int SceneChecks { get; private set; }

        /// <summary>
        /// Bodies the SCENE actually has, as opposed to rows the DATA claims.
        ///
        /// WHY THIS IS NOT <see cref="VisibleCount"/>. VisibleCount is
        /// `frame.Length`, a number read out of frames.csv. Comparing it with
        /// history.csv's n_alive tests that the two exported tables agree with
        /// each other, which is worth testing and does fail when they do not.
        /// But it is a claim about the DATA, and it cannot fail when the
        /// renderer draws the wrong bodies.
        ///
        /// A pooling bug is exactly that failure, and it is the first one named
        /// in CheckHeadcount's own doc comment and in UNITY_PLAN.md's Stage 3
        /// acceptance ("villager count on screen equals n_alive"). Session 21
        /// hid a living villager with SetActive(false) in play mode and
        /// CheckHeadcount still returned true. The claim was broader than the
        /// check for three sessions.
        ///
        /// This is the missing third source, so the year can be agreed on by
        /// history.csv, frames.csv AND the scene graph rather than by two
        /// readings of the same export.
        ///
        /// Called once per year visited, never per frame: an allocation-free
        /// walk over at most a few hundred pooled transforms.
        /// </summary>
        public int DrawnBodyCount()
        {
            int n = 0;
            foreach (Transform t in _villagerRoot)
            {
                if (t.gameObject.activeSelf) n++;
            }
            return n;
        }

        /// <summary>
        /// The NAMES of the bodies currently standing, written into
        /// <paramref name="into"/> rather than returned, so the per-year check
        /// reuses one set instead of allocating.
        ///
        /// Read off the scene graph, where <see cref="VillagerView.Apply"/> stamps
        /// `gameObject.name` with the row's name, and therefore independent of
        /// the `_views` dictionary the pool keeps. That independence is the
        /// point: a pool that hands back the wrong view corrupts its own
        /// bookkeeping and the scene together, so asking the pool would get
        /// the same wrong answer twice.
        ///
        /// A SET, not a count, because the interesting failure preserves the
        /// count: a body left standing under a name no row has this year, while
        /// the villager who should be there is missing, keeps the tally exactly
        /// right and shows the wrong person. Verified in play mode; a bare
        /// count passes it and the set does not.
        ///
        /// One failure the set deliberately does NOT catch, because it cannot
        /// occur: a pure permutation of names among the correct bodies.
        /// <see cref="VillagerView.Apply"/> writes the name and every visible
        /// property from the same row, so no state exists in which a body wears
        /// one villager's name and another's appearance.
        /// </summary>
        public void DrawnBodyNames(HashSet<string> into)
        {
            into.Clear();
            foreach (Transform t in _villagerRoot)
            {
                if (t.gameObject.activeSelf) into.Add(t.name);
            }
        }

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

            // After Render, so a villager who died this year has already been
            // retired and the ring goes out with them in the same frame rather
            // than hanging over an empty patch of ground for one.
            UpdateSelectionRing();
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
        /// this year. THREE sources have to agree, not two:
        ///
        ///   history.csv's n_alive  ==  frames.csv's row count  ==  the bodies
        ///   standing in the scene.
        ///
        /// The first pair catches a dropped row or a CSV misparse. The second
        /// pair catches a pooling bug, and only the second pair does, which is
        /// the correction session 21 made. Until then the method compared two
        /// numbers that had both been read out of the export and reported the
        /// result as "villagers drawn", so hiding a living villager left it
        /// passing. See <see cref="DrawnBodyNames"/>.
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

            // HALF ONE: the DATA agreeing with itself. Both numbers come out
            // of the export, so this catches a dropped row, a CSV misparse or a
            // frames/history disagreement, and says nothing whatever about what
            // is on screen.
            if (expected != VisibleCount)
            {
                HeadcountMismatches++;
                Debug.LogError(
                    $"[extNPC] headcount mismatch at year {atTick}: " +
                    $"frames.csv has {VisibleCount} rows but history.csv " +
                    $"records n_alive={expected}. The two exported tables " +
                    $"disagree; the bundle does not describe one world.");
                return false;
            }

            // HALF TWO: the SCENE agreeing with the data. This is the half
            // that was missing until session 21: hiding a living villager with
            // SetActive(false) left the check above returning true, because
            // VisibleCount is `frame.Length` and never looked at the scene. The
            // pooling failure this class's own comments claim to cover was
            // therefore uncovered.
            //
            // `_seen` is built straight from the frame rows in Render(), never
            // from the pool, so it is an independent expectation rather than
            // the pool restating itself. It includes the villagers rising for
            // next year, and so does the scene, so the two remain comparable
            // mid-blend.
            //
            // Guarded on the rendered year because a caller may ask about any
            // tick and the scene only ever shows one; SceneChecks records how
            // often the guard let it through, so a version that always skipped
            // could not hide behind a healthy HeadcountChecks tally.
            if (atTick == _renderedTick)
            {
                SceneChecks++;
                DrawnBodyNames(_drawn);
                if (!_drawn.SetEquals(_seen))
                {
                    HeadcountMismatches++;
                    Debug.LogError(
                        $"[extNPC] scene/data mismatch at year {atTick}: " +
                        $"{_drawn.Count} bodies standing for {_seen.Count} " +
                        $"expected. {DescribeSetDifference(_seen, _drawn)} " +
                        $"The data is consistent, so this is the renderer: " +
                        $"the viewer is not showing the world it loaded.");
                    return false;
                }
            }

            if (verbose)
                Debug.Log($"[extNPC] year {atTick}: {VisibleCount} villagers " +
                          $"drawn, matching history.csv n_alive={expected}.");
            return true;
        }

        /// <summary>
        /// Name the first few villagers on each side of a disagreement.
        ///
        /// A bare count tells you something is wrong; the names tell you which
        /// shape of wrong. "missing" with nothing extra is a body that failed to
        /// be shown; matched missing-and-extra counts are two people wearing
        /// each other's identity, which is the failure a count alone cannot see
        /// and the reason this comparison is a set.
        /// </summary>
        private static string DescribeSetDifference(
            HashSet<string> expected, HashSet<string> actual)
        {
            var missing = new List<string>();
            var extra = new List<string>();
            foreach (string name in expected)
            {
                if (!actual.Contains(name) && missing.Count < 4) missing.Add(name);
            }
            foreach (string name in actual)
            {
                if (!expected.Contains(name) && extra.Count < 4) extra.Add(name);
            }
            string m = missing.Count == 0 ? "none" : string.Join(", ", missing);
            string e = extra.Count == 0 ? "none" : string.Join(", ", extra);
            return $"Expected but not drawn: {m}. Drawn but not expected: {e}.";
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
            if (view == null) return;

            _selected = view.Row.Name;
            VillagerSelected?.Invoke(view.Row);
        }

        /// <summary>
        /// A ring on the ground under the selected villager, moved each frame.
        ///
        /// WHY THIS EXISTS. Clicking a villager filled a panel on the far side
        /// of the screen and changed nothing where the cursor was, so in a
        /// crowd there was no way to tell which capsule the panel was
        /// describing, and no way to find them again after orbiting. The ring
        /// is the answer to "which one is this".
        ///
        /// It follows the body rather than being parented to it, because the
        /// body is POOLED: parenting would hand the ring to whoever inherited
        /// that view when the selected villager died, and it would sink into
        /// the ground with them during a death blend.
        ///
        /// Deliberately NOT a colour on the villager. Colour is spoken for by
        /// lineage (lineage.py:105) and tinting the selected body would
        /// overwrite the one channel that carries ancestry, which is the same
        /// reason Stage 3 encoded sex as a shape.
        /// </summary>
        private void UpdateSelectionRing()
        {
            bool has = _selected != null &&
                       _views.TryGetValue(_selected, out VillagerView view) &&
                       view.gameObject.activeSelf;

            if (!has)
            {
                if (_selectionRing != null) _selectionRing.SetActive(false);
                return;
            }

            if (_selectionRing == null)
            {
                _selectionRing = DemeRingView.CreateMarker(
                    transform, ringMaterial, "Selection");
            }

            _selectionRing.SetActive(true);
            Vector3 p = _views[_selected].transform.position;
            _selectionRing.transform.position =
                new Vector3(p.x, groundY + 0.04f, p.z);
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

            if (showGroundGrid) BuildGroundGrid(side);
        }

        /// <summary>
        /// A survey grid on the ground, one line every ten MAP units.
        ///
        /// WHY IT IS WORTH THE LINES. The map is 100x100 arbitrary units and
        /// every position on it comes from `community.person_map_offset`, but
        /// on a bare plane there is nothing to judge distance or drift against:
        /// two demes twenty units apart and forty units apart look much the
        /// same from an orbiting camera. The grid gives the eye a ruler, which
        /// is the difference between a scene and an instrument.
        ///
        /// IT IS NOT DATA, and it is spaced in MAP units rather than metres on
        /// purpose, so a reader counting squares is counting the engine's own
        /// coordinate system rather than a rendering convenience. Nothing here
        /// is read from the bundle and nothing is derived from it.
        ///
        /// One mesh with one draw call, built once. A line renderer per line
        /// would be twenty two components for a static backdrop.
        /// </summary>
        private void BuildGroundGrid(float side)
        {
            var go = new GameObject("Ground Grid");
            go.transform.SetParent(transform, false);
            // A hair above the plane: coplanar geometry z-fights, and the
            // artefact only appears at grazing camera angles, which is exactly
            // where an orbit camera spends its time.
            go.transform.localPosition = new Vector3(0f, groundY + 0.02f, 0f);

            const int cells = 10;                  // every 10 map units
            float half = side * 0.5f;
            float step = side / cells;

            var verts = new List<Vector3>((cells + 1) * 4);
            var indices = new List<int>((cells + 1) * 4);
            for (int i = 0; i <= cells; i++)
            {
                float p = -half + i * step;
                indices.Add(verts.Count); verts.Add(new Vector3(p, 0f, -half));
                indices.Add(verts.Count); verts.Add(new Vector3(p, 0f, half));
                indices.Add(verts.Count); verts.Add(new Vector3(-half, 0f, p));
                indices.Add(verts.Count); verts.Add(new Vector3(half, 0f, p));
            }

            var mesh = new Mesh { name = "extNPC Ground Grid" };
            mesh.SetVertices(verts);
            mesh.SetIndices(indices.ToArray(), MeshTopology.Lines, 0);
            mesh.RecalculateBounds();

            go.AddComponent<MeshFilter>().sharedMesh = mesh;
            var mr = go.AddComponent<MeshRenderer>();
            mr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            mr.receiveShadows = false;
            mr.sharedMaterial = CreateDefaultMaterial("extNPC/Grid");
            if (mr.sharedMaterial != null)
            {
                // Faint: a grid that competes with the villagers has replaced
                // the thing it was drawn to help read.
                var c = new Color(0.30f, 0.32f, 0.35f);
                mr.sharedMaterial.SetColor("_BaseColor", c);
                mr.sharedMaterial.SetColor("_Color", c);
            }
        }
    }
}
