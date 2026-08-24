using ExtNPC.View;
using UnityEngine;

namespace ExtNPC.Sync
{
    /// <summary>
    /// Keeps this viewer and the dashboard pointed at the same villager and
    /// the same year (item N1).
    ///
    /// Publishes when the user clicks a villager or moves the timeline here,
    /// and applies what the dashboard publishes there. Selection and year
    /// travel together because they are one question, "what am I looking at",
    /// and they change together when you click a villager in a past year.
    ///
    /// OFF BY DEFAULT. A package that starts writing to the user's home
    /// directory because a scene was opened would be doing something the user
    /// did not ask for. <see cref="enabled"/> the component to switch it on,
    /// or tick it in the inspector; <see cref="SceneSetup"/> adds it disabled.
    ///
    /// THROTTLED, and that is not premature. `WorldClock` fires YearChanged
    /// every simulated year, which at the default 4 years per second is four
    /// file writes a second during playback, each one a create-write-delete-
    /// move in the user's home directory. The dashboard only needs to know
    /// where the scrub bar ended up, so writes coalesce.
    /// </summary>
    [AddComponentMenu("")]
    public sealed class SessionSyncBridge : MonoBehaviour
    {
        /// <summary>Seconds between polls. Four times a second is under a
        /// frame's worth of work and is well below the rate at which a person
        /// notices a click not being mirrored.</summary>
        public float pollIntervalSeconds = 0.25f;

        /// <summary>Minimum seconds between our own writes. See the class note
        /// on playback.</summary>
        public float publishIntervalSeconds = 0.2f;

        private SessionSync _sync;
        private ExtNpcWorldLoader _loader;
        private WorldClock _clock;
        private VillagerInspector _inspector;
        private WorldRenderer _renderer;

        private float _nextPoll;
        private float _nextPublish;

        // What we last told the other side, so an unchanged state is not
        // republished and a state we RECEIVED is not immediately echoed back.
        private string _publishedSelection;
        private int? _publishedYear;
        private bool _hasPublished;

        // Set while applying an incoming payload, so the events that fire as a
        // result do not bounce straight back out. Without it, receiving a
        // selection makes us publish it, which the dashboard then hears as a
        // fresh message from us: the classic two-way binding loop, and the same
        // one `slider-echo` guards against inside the dashboard itself.
        private bool _applying;

        private void Awake()
        {
            _loader = GetComponent<ExtNpcWorldLoader>();
            _clock = GetComponent<WorldClock>();
            _inspector = GetComponent<VillagerInspector>();
            _renderer = GetComponent<WorldRenderer>();
        }

        private void OnEnable()
        {
            string world = _loader != null ? _loader.worldName : "";
            _sync = new SessionSync(SessionSync.SourceUnity, world);

            if (_renderer != null) _renderer.VillagerSelected += OnVillagerSelected;
            if (_clock != null) _clock.YearChanged += OnYearChanged;
        }

        private void OnDisable()
        {
            if (_renderer != null) _renderer.VillagerSelected -= OnVillagerSelected;
            if (_clock != null) _clock.YearChanged -= OnYearChanged;
        }

        private void OnVillagerSelected(Data.FrameRow row)
        {
            if (_applying) return;
            RequestPublish();
        }

        private void OnYearChanged(int year)
        {
            if (_applying) return;
            RequestPublish();
        }

        // Set by an event, acted on in Update, so a burst of events in one
        // frame becomes one write rather than one write each. It must NOT
        // reset the throttle deadline: doing that would let a fast enough
        // stream of events publish on every frame, which is the thing the
        // throttle exists to prevent.
        private bool _pendingPublish;

        private void RequestPublish()
        {
            _pendingPublish = true;
        }

        private void Update()
        {
            float now = Time.realtimeSinceStartup;

            if (_pendingPublish && now >= _nextPublish)
            {
                PublishNow();
                _nextPublish = now + publishIntervalSeconds;
                _pendingPublish = false;
            }

            if (now >= _nextPoll)
            {
                _nextPoll = now + pollIntervalSeconds;
                PollNow();
            }
        }

        private void PublishNow()
        {
            if (_sync == null) return;

            string selection = _inspector != null ? _inspector.SelectedName : null;
            int? year = _clock != null ? (int?)_clock.Year : null;

            // Nothing to say. Worth checking because YearChanged also fires
            // when the clock is re-pushed without moving.
            if (_hasPublished && selection == _publishedSelection
                && year.Equals(_publishedYear))
                return;

            if (_sync.Publish(selection, year))
            {
                _publishedSelection = selection;
                _publishedYear = year;
                _hasPublished = true;
            }
        }

        private void PollNow()
        {
            if (_sync == null) return;

            SessionSync.State state;
            if (!_sync.TryPoll(out state)) return;

            _applying = true;
            try
            {
                // Year first. Selecting a villager who is not alive in the year
                // on screen is a state the inspector already handles and says
                // so in the panel, but arriving at it by applying the two in
                // the wrong order would flash that message for one frame every
                // time the dashboard moved both at once.
                if (state.Year.HasValue && _clock != null
                    && _clock.Year != state.Year.Value)
                    _clock.SeekYear(state.Year.Value);

                if (_inspector != null)
                {
                    if (string.IsNullOrEmpty(state.Selected)) _inspector.ClearSelection();
                    else _inspector.Select(state.Selected);
                }

                // Record it as ours so the next publish does not send it back.
                _publishedSelection = state.Selected;
                _publishedYear = state.Year;
                _hasPublished = true;
            }
            finally
            {
                _applying = false;
            }
        }
    }
}
