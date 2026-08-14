using System.Collections.Generic;
using ExtNPC.Data;
using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// Stage 5's on-screen furniture: the transport, the scrub bar, and the
    /// five KPI numbers for the year being shown.
    ///
    /// NUMBERS ONLY, NO CHARTS. UNITY_PLAN.md is explicit that the dashboard
    /// stays the analysis instrument (§0.1, §4.5): a time series drawn here
    /// would be a second, worse version of a Plotly panel, built on the same
    /// data, and the first time the two disagreed nobody would know which to
    /// believe. So the HUD prints the five values the plan names —
    /// `n_alive`, `heterozygosity`, `fst`, `mean_inbreeding`,
    /// `lethal_equivalents` — reads every one of them out of history.csv, and
    /// formats them through <see cref="TimelineFormat"/>, which mirrors the
    /// dashboard's own tiles.
    ///
    /// THE PROVENANCE LINE IS NOT DECORATION. §3.1 requires the catalogue to be
    /// visible in the Unity UI AT ALL TIMES: two exports with the same seed and
    /// different catalogues are different model versions and nothing in the
    /// numbers says so. Until this stage the catalogue only appeared in a
    /// console line at load, which is not "at all times" — the requirement is
    /// met here.
    ///
    /// IMGUI for the same reason the inspector is: no uGUI dependency, no
    /// prefabs, no assets, so the package still builds a working viewer from an
    /// empty scene in one click.
    /// </summary>
    [AddComponentMenu("extNPC/Timeline HUD")]
    [RequireComponent(typeof(WorldClock))]
    public sealed class TimelineHud : MonoBehaviour
    {
        [Tooltip("Hide the HUD without removing the component.")]
        public bool show = true;

        [Tooltip("Pixels kept clear on the right for the villager inspector.")]
        public float reservedRight = 386f;

        [Tooltip("Height of the transport bar.")]
        public float barHeight = 96f;

        private WorldClock _clock;
        private WorldRenderer _renderer;
        private ExtNpcWorldLoader _loader;
        private WorldBundle _bundle;

        private Texture2D _px;
        private GUIStyle _key, _val, _small, _state, _section, _warn;
        private bool _stylesReady;

        private void Awake()
        {
            _clock = GetComponent<WorldClock>();
            _renderer = GetComponent<WorldRenderer>();
            _loader = GetComponent<ExtNpcWorldLoader>();
            if (_loader != null)
            {
                _loader.Loaded += OnLoaded;
                if (_loader.Bundle != null) OnLoaded(_loader.Bundle);
            }
        }

        private void OnDestroy()
        {
            if (_loader != null) _loader.Loaded -= OnLoaded;
            if (_px != null) Destroy(_px);
        }

        private void OnLoaded(WorldBundle bundle) => _bundle = bundle;

        // ------------------------------------------------------------------
        // GUI
        // ------------------------------------------------------------------

        private void OnGUI()
        {
            if (!show || _bundle == null || _clock == null) return;
            EnsureStyles();

            DrawProvenanceAndKpis();
            DrawTransport();
        }

        /// <summary>Top-left: which run this is, and what it looked like in the
        /// year on screen.</summary>
        private void DrawProvenanceAndKpis()
        {
            const float w = 268f;
            var area = new Rect(12f, 12f, w, 250f);
            Fill(area, InspectorFormat.Surface);
            Outline(area, InspectorFormat.Grid);

            GUILayout.BeginArea(new Rect(area.x + 12f, area.y + 10f,
                                         area.width - 24f, area.height - 20f));

            GUILayout.Label("WORLD", _section);
            GUILayout.Space(4f);
            // Manifest.ToString() carries seed, year, catalogue and commit. The
            // catalogue is in it deliberately and must never be dropped.
            GUILayout.Label(_bundle.Manifest.ToString(), _small);
            if (_bundle.Manifest.Catalogue == "empirical")
            {
                GUILayout.Label("EXPERIMENTAL catalogue — not validated", _warn);
            }
            if (_bundle.Manifest.Frames.Truncated)
            {
                GUILayout.Label(
                    "snapshot ring overflowed: this timeline starts at year " +
                    InspectorFormat.Int(_bundle.FirstTick) + ", not 0", _warn);
            }

            GUILayout.Space(8f);
            Rule();
            GUILayout.Space(8f);

            HistoryRow year = HistoryAt(_clock.Year);
            GUILayout.Label(TimelineFormat.Range(_clock.Year, _bundle.FirstTick,
                                                 _bundle.LastTick), _section);
            GUILayout.Space(6f);

            if (year == null)
            {
                // A frame with no history row is a real state — say so rather
                // than printing five em-dashes that read as five unmeasurable
                // quantities.
                GUILayout.Label("history.csv has no row for this year.", _small);
            }
            else
            {
                // Every one of these is READ. Nothing on this panel is derived.
                Row(TimelineFormat.AliveLabel,
                    TimelineFormat.Alive(year.Get("n_alive", 0.0)));
                Row(TimelineFormat.HeterozygosityLabel,
                    TimelineFormat.Heterozygosity(year.Get("heterozygosity", 0.0)));
                Row(TimelineFormat.FstLabel,
                    TimelineFormat.Fst(year.Get("fst", 0.0),
                                       _bundle.Manifest.ParamInt("n_demes", 1)));
                Row(TimelineFormat.InbreedingLabel,
                    TimelineFormat.Inbreeding(year.Get("mean_inbreeding", 0.0)));
                Row(TimelineFormat.LoadLabel,
                    TimelineFormat.Load(year.Get("lethal_equivalents", 0.0)));
            }

            GUILayout.Space(8f);
            DrawHeadcountVerdict();

            GUILayout.EndArea();
        }

        /// <summary>
        /// The acceptance criterion, on screen.
        ///
        /// Stage 3 checked once at load that the villagers drawn equal
        /// history.csv's n_alive; a scrub bar makes that a claim about every
        /// year, so the renderer re-checks each one and this reports the tally.
        /// A check whose result never reaches a human is a check that has
        /// stopped being evidence.
        /// </summary>
        private void DrawHeadcountVerdict()
        {
            if (_renderer == null) return;

            if (_renderer.HeadcountMismatches > 0)
            {
                GUILayout.Label(
                    "HEADCOUNT MISMATCH in " +
                    InspectorFormat.Int(_renderer.HeadcountMismatches) +
                    " of " + InspectorFormat.Int(_renderer.HeadcountChecks) +
                    " years — see the console", _warn);
            }
            else
            {
                GUILayout.Label(
                    "headcount agrees with history.csv (" +
                    InspectorFormat.Int(_renderer.HeadcountChecks) +
                    " years checked)", _small);
            }
        }

        /// <summary>Bottom: play/pause, speed, the scrub bar and its event
        /// markers.</summary>
        private void DrawTransport()
        {
            float width = Screen.width - reservedRight - 24f;
            if (width < 260f) width = Mathf.Max(260f, Screen.width - 24f);

            var area = new Rect(12f, Screen.height - barHeight - 12f,
                                width, barHeight);
            Fill(area, InspectorFormat.Surface);
            Outline(area, InspectorFormat.Grid);

            GUILayout.BeginArea(new Rect(area.x + 12f, area.y + 8f,
                                         area.width - 24f, area.height - 16f));

            // ---- transport row -------------------------------------------
            GUILayout.BeginHorizontal();

            if (GUILayout.Button(_clock.playing ? "PAUSE" : "PLAY",
                                 GUILayout.Width(74f)))
            {
                _clock.TogglePlay();
            }
            // The dashboard's "⏮ Live" (app.py:1338), same job: return to the
            // export's own last year.
            if (GUILayout.Button("Live", GUILayout.Width(56f))) _clock.GoLive();

            GUILayout.Space(10f);
            GUILayout.Label(
                _clock.IsLive ? TimelineFormat.LiveState
                              : TimelineFormat.ScrubState(_clock.Year),
                _clock.IsLive ? StateStyle(TimelineFormat.LiveColor)
                              : StateStyle(TimelineFormat.ScrubColor));

            GUILayout.FlexibleSpace();

            GUILayout.Label(TimelineFormat.Speed(_clock.yearsPerSecond), _small,
                            GUILayout.Width(70f));
            _clock.yearsPerSecond = GUILayout.HorizontalSlider(
                _clock.yearsPerSecond, 0.5f, 30f, GUILayout.Width(110f));

            GUILayout.EndHorizontal();
            GUILayout.Space(6f);

            // ---- scrub bar ------------------------------------------------
            Rect track = GUILayoutUtility.GetRect(10f, 18f, GUILayout.ExpandWidth(true));
            DrawEventMarkers(track);

            int count = _clock.Count;
            if (count > 1)
            {
                float wanted = GUI.HorizontalSlider(track, _clock.Index, 0f,
                                                    count - 1);
                int index = Mathf.RoundToInt(wanted);
                if (index != _clock.Index)
                {
                    // Scrubbing lands ON a year: SeekIndex drops the cosmetic
                    // inter-tick fraction, so a dragged bar always shows a frame
                    // the engine actually exported.
                    _clock.SeekIndex(index);
                }
            }

            // ---- notes ----------------------------------------------------
            GUILayout.Space(2f);
            GUILayout.BeginHorizontal();
            GUILayout.Label(EventNote(), _small);
            GUILayout.FlexibleSpace();
            if (_clock.playing && _clock.interpolateMotion)
            {
                // Only while it is actually happening. A permanent disclaimer
                // is one people stop reading; this one appears exactly when the
                // scene is showing something the engine did not compute.
                GUILayout.Label(TimelineFormat.CosmeticMotionNote, _small);
            }
            GUILayout.EndHorizontal();

            GUILayout.EndArea();
        }

        /// <summary>
        /// Event markers on the track.
        ///
        /// Rules, not the dashboard's ☣/🌾/⧗ icons — see
        /// <see cref="TimelineFormat.MarkerGlyphNote"/>. The colour is the
        /// dashboard's CRIT and the position is the event's own year, so the
        /// two timelines mark the same places in the same colour.
        /// </summary>
        private void DrawEventMarkers(Rect track)
        {
            Fill(new Rect(track.x, track.center.y - 1f, track.width, 2f),
                 InspectorFormat.Plane);

            if (_bundle.Events == null || _bundle.Events.Count == 0) return;

            int lo = _bundle.FirstTick, hi = _bundle.LastTick;
            if (hi <= lo) return;

            foreach (EventRow e in _bundle.Events)
            {
                if (e.Tick < lo || e.Tick > hi) continue;
                float t = (float)(e.Tick - lo) / (hi - lo);
                float x = track.x + t * track.width;
                Fill(new Rect(x - 1f, track.y, 2f, track.height),
                     TimelineFormat.EventMarkerColor);
            }
        }

        /// <summary>The dashboard's own note (app.py:2018): the last six
        /// events, each as "y{tick} {label}".</summary>
        private string EventNote()
        {
            var events = _bundle.Events;
            if (events == null || events.Count == 0)
                return TimelineFormat.NoEventsNote;

            int from = Mathf.Max(0, events.Count - TimelineFormat.EventNoteCount);
            var parts = new List<string>(events.Count - from);
            for (int i = from; i < events.Count; i++)
                parts.Add(TimelineFormat.EventEntry(events[i].Tick, events[i].Label));

            return TimelineFormat.EventNotePrefix +
                   string.Join(TimelineFormat.EventNoteSeparator, parts);
        }

        private HistoryRow HistoryAt(int tick)
        {
            foreach (HistoryRow h in _bundle.History)
                if (h.Tick == tick) return h;
            return null;
        }

        // ------------------------------------------------------------------
        // IMGUI primitives (same shapes as VillagerInspector's)
        // ------------------------------------------------------------------

        private void Row(string key, string value)
        {
            GUILayout.BeginHorizontal();
            GUILayout.Label(key, _key);
            GUILayout.FlexibleSpace();
            GUILayout.Label(value, _val);
            GUILayout.EndHorizontal();
            GUILayout.Space(2f);
        }

        private GUIStyle StateStyle(Color c)
        {
            _state.normal.textColor = c;
            return _state;
        }

        private void Rule()
        {
            Rect r = GUILayoutUtility.GetRect(10f, 1f, GUILayout.ExpandWidth(true));
            Fill(r, InspectorFormat.Grid);
        }

        private void Fill(Rect r, Color c)
        {
            if (Event.current.type != EventType.Repaint) return;
            Color prev = GUI.color;
            GUI.color = c;
            GUI.DrawTexture(r, _px);
            GUI.color = prev;
        }

        private void Outline(Rect r, Color c)
        {
            Fill(new Rect(r.x, r.y, r.width, 1f), c);
            Fill(new Rect(r.x, r.yMax - 1f, r.width, 1f), c);
            Fill(new Rect(r.x, r.y, 1f, r.height), c);
            Fill(new Rect(r.xMax - 1f, r.y, 1f, r.height), c);
        }

        private void EnsureStyles()
        {
            if (_stylesReady) return;

            _px = new Texture2D(1, 1) { hideFlags = HideFlags.HideAndDontSave };
            _px.SetPixel(0, 0, Color.white);
            _px.Apply();

            _key = new GUIStyle(GUI.skin.label) { fontSize = 11 };
            _key.normal.textColor = InspectorFormat.Muted;

            _val = new GUIStyle(GUI.skin.label)
            { fontSize = 12, fontStyle = FontStyle.Bold,
              alignment = TextAnchor.MiddleRight };
            _val.normal.textColor = InspectorFormat.Ink;

            _small = new GUIStyle(GUI.skin.label) { fontSize = 10, wordWrap = true };
            _small.normal.textColor = InspectorFormat.Muted;

            _state = new GUIStyle(GUI.skin.label)
            { fontSize = 11, fontStyle = FontStyle.Bold };

            _section = new GUIStyle(GUI.skin.label)
            { fontSize = 10, fontStyle = FontStyle.Bold };
            _section.normal.textColor = InspectorFormat.Accent;

            _warn = new GUIStyle(GUI.skin.label)
            { fontSize = 10, fontStyle = FontStyle.Bold, wordWrap = true };
            _warn.normal.textColor = InspectorFormat.Warn;

            _stylesReady = true;
        }
    }
}
