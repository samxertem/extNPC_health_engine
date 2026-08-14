using ExtNPC.Data;
using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// A cursor over the retained ticks: which index, and how far past it.
    ///
    /// Split out of <see cref="WorldClock"/> as a plain struct so the timeline
    /// arithmetic can be tested without a scene, a bundle or a frame loop --
    /// Tests/WorldClockTests.cs drives it directly. Every off-by-one a scrub
    /// bar can have (running past the last year, rewinding below the first,
    /// swallowing a year on a long frame) is in here rather than in a
    /// MonoBehaviour that needs Unity running to exercise.
    ///
    /// INDEX, NOT YEAR. The cursor walks positions in
    /// <see cref="WorldBundle.Ticks"/> rather than counting years, because the
    /// retained range does not have to start at zero: the engine's snapshot
    /// ring is capped, and a long run drops its earliest years
    /// (manifest.frames.truncated). Indexing the array cannot mislabel a
    /// timeline; adding one to a year can.
    /// </summary>
    public struct TimelineCursor
    {
        /// <summary>Position in the tick array. Always a real, exported year.</summary>
        public int Index;

        /// <summary>Fraction of the way to the NEXT retained tick, [0,1).
        ///
        /// COSMETIC ONLY. The engine simulated year N and year N+1; it did not
        /// simulate anything in between, and nothing biological may be
        /// interpolated across this value. See WorldRenderer.Render.</summary>
        public float Alpha;

        /// <summary>Move forward by <paramref name="years"/> (may exceed 1 on a
        /// long frame). Returns true if the end was reached and the cursor
        /// parked on the last tick.</summary>
        public bool Advance(float years, int count, bool loop)
        {
            if (count <= 1)
            {
                Index = 0;
                Alpha = 0f;
                return true;
            }

            float last = count - 1;
            float pos = Index + Alpha + years;

            if (pos >= last)
            {
                if (!loop)
                {
                    // Park exactly ON the final year with no residual alpha, so
                    // a finished playback shows the last exported frame rather
                    // than a blend toward a year that does not exist.
                    Index = count - 1;
                    Alpha = 0f;
                    return true;
                }
                pos = Mathf.Repeat(pos, last);
            }
            if (pos < 0f) pos = 0f;

            Index = Mathf.FloorToInt(pos);
            Alpha = pos - Index;
            return false;
        }

        /// <summary>Jump to a tick index. Alpha is dropped: a scrub lands on a
        /// year the engine actually computed, never between two.</summary>
        public void Seek(int index, int count)
        {
            Index = count <= 0 ? 0 : Mathf.Clamp(index, 0, count - 1);
            Alpha = 0f;
        }
    }

    /// <summary>
    /// Stage 5: the timeline. Play, pause, scrub, and hand the renderer a year.
    ///
    /// WHAT IT IS NOT ALLOWED TO BE. A clock is where a viewer starts inventing
    /// history: a smoothed population curve, an eased birth, a villager
    /// drifting between two settlements as though the walk were simulated.
    /// UNITY_PLAN.md invariant 5 is the line -- every number displayed came
    /// from a file -- so this component owns exactly one derived quantity,
    /// <see cref="TimelineCursor.Alpha"/>, it is used for POSITION ONLY, and
    /// the HUD says so on screen for as long as it is non-zero.
    ///
    /// PAUSED MEANS EXACT. Alpha is forced to zero whenever playback is not
    /// running, so a paused or scrubbed scene is a frame the engine exported
    /// and not a blend of two. The only moment the viewer shows anything the
    /// simulation did not produce is while the run is visibly playing.
    /// </summary>
    [AddComponentMenu("extNPC/World Clock")]
    [RequireComponent(typeof(WorldRenderer))]
    public sealed class WorldClock : MonoBehaviour
    {
        [Tooltip("Simulated years per real second while playing.")]
        public float yearsPerSecond = 4f;

        [Tooltip("Advance the year automatically.")]
        public bool playing;

        [Tooltip("Blend villager POSITIONS between two years while playing. " +
                 "Cosmetic: a villager does not exist between years, and the " +
                 "only motion it can ever animate is a migration, because map " +
                 "position is a pure function of deme and name.")]
        public bool interpolateMotion = true;

        [Tooltip("Restart at the earliest retained year on reaching the last.")]
        public bool loop;

        private WorldRenderer _renderer;
        private ExtNpcWorldLoader _loader;
        private WorldBundle _bundle;
        private TimelineCursor _cursor;

        /// <summary>The displayed year. Always an entry of
        /// <see cref="WorldBundle.Ticks"/>.</summary>
        public int Year { get; private set; }

        /// <summary>Retained years available to scrub over.</summary>
        public int Count => _bundle == null ? 0 : _bundle.Ticks.Length;

        public int Index => _cursor.Index;

        /// <summary>Cosmetic inter-tick fraction; zero unless playing with
        /// interpolation on.</summary>
        public float Alpha => _cursor.Alpha;

        /// <summary>True when the displayed year is the export's own last one --
        /// the state the dashboard calls "LIVE".</summary>
        public bool IsLive => _bundle != null && Year >= _bundle.LastTick;

        /// <summary>Raised when the displayed year changes, so a HUD can
        /// refresh without polling.</summary>
        public event System.Action<int> YearChanged;

        private void Awake()
        {
            _renderer = GetComponent<WorldRenderer>();
            _loader = GetComponent<ExtNpcWorldLoader>();
            if (_loader != null)
            {
                _loader.Loaded += OnLoaded;
                // Catch up if the bundle arrived first; subscribing to an event
                // that has already fired is a silent no-op and the symptom is a
                // scrub bar with no years in it. Same reason as
                // WorldRenderer.Awake.
                if (_loader.Bundle != null) OnLoaded(_loader.Bundle);
            }
        }

        private void OnDestroy()
        {
            if (_loader != null) _loader.Loaded -= OnLoaded;
        }

        private void OnLoaded(WorldBundle bundle)
        {
            _bundle = bundle;
            GoLive();
        }

        private void Update()
        {
            if (_bundle == null || Count == 0) return;

            if (playing)
            {
                bool ended = _cursor.Advance(Time.deltaTime * Mathf.Max(yearsPerSecond, 0f),
                                             Count, loop);
                if (ended && !loop) playing = false;
            }
            else
            {
                // Not playing means exactly on a year. See the class comment.
                _cursor.Alpha = 0f;
            }

            Push();
        }

        // ------------------------------------------------------------------
        // transport
        // ------------------------------------------------------------------

        public void Play() => playing = true;
        public void Pause() => playing = false;
        public void TogglePlay() => playing = !playing;

        /// <summary>Jump to a tick INDEX (what a scrub bar produces).</summary>
        public void SeekIndex(int index)
        {
            _cursor.Seek(index, Count);
            Push();
        }

        /// <summary>Jump to a YEAR, snapped to the nearest retained tick at or
        /// below it -- the same resolution rule as
        /// <see cref="WorldBundle.FrameAt"/>, so the scrub bar and the frame
        /// lookup can never disagree about which year is on screen.</summary>
        public void SeekYear(int year)
        {
            if (_bundle == null) return;
            int[] ticks = _bundle.Ticks;
            int best = 0;
            for (int i = 0; i < ticks.Length; i++)
            {
                if (ticks[i] <= year) best = i; else break;
            }
            SeekIndex(best);
        }

        /// <summary>Return to the export's last year -- the dashboard's
        /// "⏮ Live" button (app.py:1338).</summary>
        public void GoLive()
        {
            _cursor.Seek(Count - 1, Count);
            Push();
        }

        /// <summary>The next retained year, or the current one at the end. The
        /// renderer blends toward it; nothing else may.</summary>
        public int NextYear
        {
            get
            {
                if (_bundle == null || Count == 0) return Year;
                int next = Mathf.Min(_cursor.Index + 1, Count - 1);
                return _bundle.Ticks[next];
            }
        }

        private void Push()
        {
            if (_bundle == null || Count == 0) return;

            int year = _bundle.Ticks[Mathf.Clamp(_cursor.Index, 0, Count - 1)];
            bool changed = year != Year;
            Year = year;

            float alpha = interpolateMotion ? _cursor.Alpha : 0f;
            if (_renderer != null) _renderer.SetTime(Year, NextYear, alpha);

            if (changed) YearChanged?.Invoke(Year);
        }
    }
}
