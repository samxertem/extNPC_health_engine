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

        // The shared 1x1 now lives in HudChrome; these are the button-state
        // backgrounds, which are this component's own and are released with it.
        private readonly List<Texture2D> _owned = new List<Texture2D>();
        private GUIStyle _key, _val, _small, _state, _section, _warn, _button;
        private GUIStyle _slider, _sliderThumb;
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
            foreach (Texture2D t in _owned) if (t != null) Destroy(t);
            _owned.Clear();
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
        /// <summary>
        /// The panel's height is MEASURED, not guessed.
        ///
        /// The content is not a fixed number of lines: the provenance string
        /// wraps at one width and not another, and two warnings appear only for
        /// worlds that earn them (an experimental catalogue, an overflowed
        /// snapshot ring). A hardcoded height clipped the headcount verdict off
        /// the bottom, which is the one line on the panel that reports whether
        /// the viewer trusts itself, so the failure hid exactly the wrong thing.
        ///
        /// IMGUI cannot know the height before laying the content out, so the
        /// layout runs inside a generously tall area (nothing is ever clipped)
        /// and the frame is drawn at the height the PREVIOUS frame measured. It
        /// converges in one frame and is stable thereafter.
        /// </summary>
        private const float PanelPad = 10f;
        private float _worldPanelHeight = 258f;

        private void DrawProvenanceAndKpis()
        {
            const float w = 268f;
            var area = new Rect(12f, 12f, w, _worldPanelHeight);
            HudChrome.Panel(area);

            GUILayout.BeginArea(new Rect(area.x + 12f, area.y + PanelPad,
                                         area.width - 24f,
                                         Screen.height - area.y - PanelPad));

            Section("WORLD");
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

            HistoryRow year = HistoryAt(_clock.Year);
            Section(TimelineFormat.Range(_clock.Year, _bundle.FirstTick,
                                         _bundle.LastTick));

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

            if (Event.current.type == EventType.Repaint)
            {
                // Inside a BeginArea, GetLastRect is relative to the area, so
                // yMax IS the content height.
                float content = GUILayoutUtility.GetLastRect().yMax;
                _worldPanelHeight = content + PanelPad * 2f;
            }

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
                // "1 years checked" is the kind of thing that makes a reader
                // trust the rest of the panel slightly less.
                int n = _renderer.HeadcountChecks;
                GUILayout.Label(
                    "headcount agrees with history.csv (" +
                    InspectorFormat.Int(n) + (n == 1 ? " year" : " years") +
                    " checked, " + InspectorFormat.Int(_renderer.SceneChecks) +
                    " against the scene)", _small);
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
            HudChrome.Panel(area);

            GUILayout.BeginArea(new Rect(area.x + 14f, area.y + 10f,
                                         area.width - 28f, area.height - 20f));

            // ---- transport row -------------------------------------------
            GUILayout.BeginHorizontal();

            if (GUILayout.Button(_clock.playing ? "PAUSE" : "PLAY", _button,
                                 GUILayout.Width(76f), GUILayout.Height(22f)))
            {
                _clock.TogglePlay();
            }
            GUILayout.Space(4f);
            // The dashboard's "⏮ Live" (app.py:1338), same job: return to the
            // export's own last year.
            if (GUILayout.Button("LIVE", _button,
                                 GUILayout.Width(58f), GUILayout.Height(22f)))
            {
                _clock.GoLive();
            }

            GUILayout.Space(12f);

            // The state reads as a lamp on an instrument rather than a line of
            // text: the same words, in the same colour, inside a tinted pill so
            // it is findable without being read.
            string state = _clock.IsLive ? TimelineFormat.LiveState
                                         : TimelineFormat.ScrubState(_clock.Year);
            Color stateColor = _clock.IsLive ? TimelineFormat.LiveColor
                                             : TimelineFormat.ScrubColor;
            var stateContent = new GUIContent(state);
            float stateW = _state.CalcSize(stateContent).x + 18f;
            Rect statePill = GUILayoutUtility.GetRect(
                stateW, 22f, GUILayout.Width(stateW), GUILayout.Height(22f));
            HudChrome.Pill(statePill, stateColor);
            GUI.Label(new Rect(statePill.x + 9f, statePill.y + 3f,
                               statePill.width, statePill.height),
                      state, StateStyle(stateColor));

            GUILayout.FlexibleSpace();

            GUILayout.Label(TimelineFormat.Speed(_clock.yearsPerSecond), _small,
                            GUILayout.Width(70f));
            _clock.yearsPerSecond = GUILayout.HorizontalSlider(
                _clock.yearsPerSecond, 0.5f, 30f, _slider, _sliderThumb,
                GUILayout.Width(110f), GUILayout.Height(20f));

            GUILayout.EndHorizontal();
            GUILayout.Space(8f);

            // ---- scrub bar ------------------------------------------------
            Rect track = GUILayoutUtility.GetRect(10f, 22f, GUILayout.ExpandWidth(true));

            int count = _clock.Count;
            float fraction = count > 1 ? (float)_clock.Index / (count - 1) : 0f;
            HudChrome.ScrubTrack(track, fraction,
                                 _bundle.FirstTick, _bundle.LastTick);
            DrawEventMarkers(track);
            HudChrome.Playhead(track, fraction);

            if (count > 1)
            {
                // An invisible slider over the drawn track. GUIStyle.none on
                // both parts means IMGUI still does the dragging, the hit
                // testing and the keyboard focus, while none of its own chrome
                // lands on top of the ruler above.
                float wanted = GUI.HorizontalSlider(track, _clock.Index, 0f,
                                                    count - 1,
                                                    GUIStyle.none, GUIStyle.none);
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
            if (_bundle.Events == null || _bundle.Events.Count == 0) return;

            int lo = _bundle.FirstTick, hi = _bundle.LastTick;
            if (hi <= lo) return;

            foreach (EventRow e in _bundle.Events)
            {
                if (e.Tick < lo || e.Tick > hi) continue;
                float t = (float)(e.Tick - lo) / (hi - lo);
                float x = track.x + t * track.width;

                // A rule through the groove plus a flag above it. The rule
                // alone was easy to lose against the elapsed fill once the
                // track gained a colour; the flag sits clear of both.
                Fill(new Rect(x - 1f, track.y + 2f, 2f, track.height - 4f),
                     TimelineFormat.EventMarkerColor);
                Fill(new Rect(x - 3f, track.y, 7f, 3f),
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

        /// <summary>
        /// One KPI: label, dotted leader, value.
        ///
        /// The leader is measured from the two labels rather than stretched
        /// across a fixed gap, so it stops where the value begins whatever the
        /// value's width. A leader that runs under its own number is worse than
        /// no leader at all.
        /// </summary>
        private void Row(string key, string value)
        {
            GUILayout.BeginHorizontal();
            GUILayout.Label(key, _key);
            GUILayout.FlexibleSpace();
            GUILayout.Label(value, _val);
            GUILayout.EndHorizontal();

            if (Event.current.type == EventType.Repaint)
            {
                Rect line = GUILayoutUtility.GetLastRect();
                float keyEnd = line.x + _key.CalcSize(new GUIContent(key)).x + 6f;
                float valStart = line.xMax -
                                 _val.CalcSize(new GUIContent(value)).x - 6f;
                if (valStart > keyEnd)
                {
                    HudChrome.Leader(new Rect(keyEnd, line.y + line.height * 0.62f,
                                              valStart - keyEnd, 1f));
                }
            }

            GUILayout.Space(3f);
        }

        /// <summary>A section header with its own strip behind it.</summary>
        private void Section(string title)
        {
            Rect r = GUILayoutUtility.GetRect(10f, 15f, GUILayout.ExpandWidth(true));
            HudChrome.SectionBar(r);
            GUI.Label(new Rect(r.x + 6f, r.y + 1f, r.width - 8f, r.height),
                      title, _section);
            GUILayout.Space(5f);
        }

        private GUIStyle StateStyle(Color c)
        {
            _state.normal.textColor = c;
            return _state;
        }

        private void Rule()
        {
            Rect r = GUILayoutUtility.GetRect(10f, 1f, GUILayout.ExpandWidth(true));
            HudChrome.Hairline(r);
        }

        private static void Fill(Rect r, Color c) => HudChrome.Fill(r, c);

        private void EnsureStyles()
        {
            if (_stylesReady) return;

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

            // Flat transport buttons. Unity's default button is a rounded grey
            // gel that belongs to the editor's own chrome, and next to a
            // measurement panel it reads as a leftover. Built from the label
            // style rather than the button style so none of that survives; the
            // background is painted by HudChrome under it.
            _button = new GUIStyle(GUI.skin.label)
            {
                fontSize = 11,
                fontStyle = FontStyle.Bold,
                alignment = TextAnchor.MiddleCenter,
                border = new RectOffset(1, 1, 1, 1),
            };
            _button.normal.textColor = InspectorFormat.Ink2;
            _button.hover.textColor = InspectorFormat.Ink;
            _button.active.textColor = InspectorFormat.Accent;
            _button.normal.background = SolidTexture(InspectorFormat.Plane);
            _button.hover.background = SolidTexture(
                Color.Lerp(InspectorFormat.Plane, InspectorFormat.Accent, 0.22f));
            _button.active.background = SolidTexture(
                Color.Lerp(InspectorFormat.Plane, InspectorFormat.Accent, 0.40f));

            // The speed slider, in the same language as the scrub track: a flat
            // groove and a solid accent thumb. Unity's default is the same grey
            // gel as its button, and leaving one styled control next to one
            // unstyled one looks more unfinished than leaving both alone.
            _slider = new GUIStyle
            {
                fixedHeight = 4f,
                margin = new RectOffset(0, 0, 8, 8),
            };
            _slider.normal.background = SolidTexture(InspectorFormat.Plane);

            _sliderThumb = new GUIStyle
            {
                fixedWidth = 9f,
                fixedHeight = 14f,
                border = new RectOffset(0, 0, 0, 0),
            };
            _sliderThumb.normal.background = SolidTexture(InspectorFormat.Ink2);
            _sliderThumb.hover.background = SolidTexture(InspectorFormat.Ink);
            _sliderThumb.active.background = SolidTexture(InspectorFormat.Accent);

            _stylesReady = true;
        }

        /// <summary>
        /// A 1x1 texture for a button state.
        ///
        /// Held by the style for the component's life, so it is created once in
        /// EnsureStyles and never per frame. HideAndDontSave keeps it out of
        /// the scene and out of any save; the three of them are released in
        /// OnDestroy with the styles that own them.
        /// </summary>
        private Texture2D SolidTexture(Color c)
        {
            var t = new Texture2D(1, 1) { hideFlags = HideFlags.HideAndDontSave };
            t.SetPixel(0, 0, c);
            t.Apply();
            _owned.Add(t);
            return t;
        }
    }
}
