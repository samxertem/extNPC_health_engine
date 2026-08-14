using System.Globalization;
using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// The timeline's and the KPI strip's wording, in ONE place, each entry
    /// naming the Python line it mirrors.
    ///
    /// Same contract as <see cref="InspectorFormat"/> and for the same reason
    /// (UNITY_PLAN.md invariant 6): where the dashboard and the viewer both
    /// show something, one definition governs both. Stage 5 puts five of the
    /// dashboard's own stat tiles on screen -- ALIVE, DIVERSITY H, F_ST,
    /// INBREEDING F and LOAD B(t) -- and a tile that agreed on the number but
    /// disagreed on the label, the decimals or the em-dash rule would be a
    /// quiet second version of the deck.
    ///
    /// THE EM-DASH RULES ARE THE POINT OF THIS FILE. Two of the five are not
    /// always measurable, and the dashboard prints an em-dash rather than a
    /// zero in both cases, because a displayed 0.000 asserts "this was
    /// measured and came out zero" -- a different claim from "there was
    /// nothing to measure":
    ///
    ///   * F_ST with a single deme (panels.py:376). There is no partition to
    ///     estimate over. The engine's manifest reports it as null for the
    ///     same reason.
    ///   * LOAD B(t) before the load layer has a measurement (panels.py:413),
    ///     e.g. an empty world or a bundle whose early years predate it.
    ///
    /// WHAT THIS IS NOT. Nothing here computes a KPI. Every value is read from
    /// history.csv at the displayed year; these functions decide only how it is
    /// printed and when it cannot honestly be printed at all.
    ///
    /// WHICH YEAR, AND A DELIBERATE DIFFERENCE FROM THE DASHBOARD. The Dash
    /// tiles always show the LIVE year (`_last(cols, ...)`), while this HUD
    /// shows the year on screen -- that is the whole point of a scrub bar. The
    /// two therefore print different numbers when scrubbed, which is not drift:
    /// the formats are shared, and the HUD labels the year it is describing.
    /// </summary>
    public static class TimelineFormat
    {
        private static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        // ------------------------------------------------------------------
        // the five tiles -- dashboard/panels.py:345 kpi_data
        // ------------------------------------------------------------------

        public const string AliveLabel = "ALIVE";                 // panels.py:358
        public const string HeterozygosityLabel = "DIVERSITY H";  // panels.py:367
        public const string FstLabel = "F_ST";                    // panels.py:376
        public const string InbreedingLabel = "INBREEDING F";     // panels.py:397
        public const string LoadLabel = "LOAD B(t)";              // panels.py:413

        /// <summary>What the dashboard prints where a quantity is not
        /// measurable: an em dash (U+2014), never a zero. panels.py:377, 415.</summary>
        public const string Unmeasurable = "—";

        /// <summary>f"{int(...)}" -- panels.py:358. int() truncates toward
        /// zero, and so does the C# cast; n_alive is integral in every row the
        /// engine writes, but the two agree even if it ever is not.</summary>
        public static string Alive(double nAlive) =>
            ((int)nAlive).ToString(Inv);

        /// <summary>f"{v:.3f}" -- panels.py:368.</summary>
        public static string Heterozygosity(double h) =>
            InspectorFormat.PyRound(h, 3).ToString("F3", Inv);

        /// <summary>
        /// f"{v:.3f}" or an em dash -- panels.py:376.
        ///
        /// The condition is the DEME COUNT, not the value: an F_ST of 0.000 in
        /// a three-deme world is a real measurement of no differentiation,
        /// while in a one-deme world there is no partition to estimate over at
        /// all. The deme count comes from manifest.json's params, so the viewer
        /// reads the same fact the dashboard reads off its own params object.
        /// </summary>
        public static string Fst(double fst, int nDemes) =>
            nDemes > 1 ? InspectorFormat.PyRound(fst, 3).ToString("F3", Inv)
                       : Unmeasurable;

        /// <summary>f"{v:.4f}" -- panels.py:398. Four decimals, matching the
        /// deck: mean F in a village is a small number and three would round
        /// distinct pedigrees together.</summary>
        public static string Inbreeding(double f) =>
            InspectorFormat.PyRound(f, 4).ToString("F4", Inv);

        /// <summary>
        /// f"{v:.3f}" or an em dash -- panels.py:413.
        ///
        /// Morton's B re-measured from the living each year. The engine writes
        /// 0.0 when it has no measurement, and the dashboard's `> 0.0` test is
        /// mirrored exactly rather than turned into a tolerance: a genuine B of
        /// zero would mean a population with no recessive load at all, which
        /// the load layer cannot produce.
        /// </summary>
        public static string Load(double b) =>
            b > 0.0 ? InspectorFormat.PyRound(b, 3).ToString("F3", Inv)
                   : Unmeasurable;

        // ------------------------------------------------------------------
        // timeline state -- dashboard/app.py:2008 render_timeline_state
        // ------------------------------------------------------------------

        /// <summary>app.py:2010, in GOOD.</summary>
        public const string LiveState = "● LIVE";

        /// <summary>app.py:2012, in WARN. The wording is the dashboard's,
        /// including the em dash and the button's name.</summary>
        public static string ScrubState(int year) =>
            string.Format(Inv, "⏱ VIEWING YEAR {0} — press Live to return", year);

        public static Color LiveColor => InspectorFormat.Good;
        public static Color ScrubColor => InspectorFormat.Warn;

        /// <summary>One event, as the dashboard's timeline note spells it:
        /// f"y{e['tick']} {e['label']}" -- app.py:2019.</summary>
        public static string EventEntry(int tick, string label) =>
            string.Format(Inv, "y{0} {1}", tick, label);

        /// <summary>The note's prefix and separator -- app.py:2018. The
        /// dashboard shows the LAST SIX events; so does the HUD.</summary>
        public const string EventNotePrefix = "events:  ";
        public const string EventNoteSeparator = "   ";
        public const int EventNoteCount = 6;

        /// <summary>Shown when the run logged nothing -- app.py:2015, with the
        /// dashboard's second sentence dropped because it names Dash panels
        /// that do not exist here.</summary>
        public const string NoEventsNote = "Drag to replay the run.";

        /// <summary>Event markers are CRIT on the dashboard's slider
        /// (app.py:1976) and CRIT here.</summary>
        public static Color EventMarkerColor => InspectorFormat.Crit;

        /// <summary>
        /// THE ICONS ARE DELIBERATELY NOT MIRRORED.
        ///
        /// The dashboard marks events with ☣ / 🌾 / ⧗ / ◆ (app.py:1971) in a
        /// browser, which has fonts for them. Unity's built-in IMGUI font does
        /// not: a biohazard sign renders as a tofu box and an emoji sheaf
        /// renders as two. A marker nobody can read is a worse disagreement
        /// than a shape, so the HUD draws a CRIT rule at the event's year and
        /// prints the event's LABEL -- which is the text the engine wrote, and
        /// is identical on both sides.
        ///
        /// The kind is still carried, for a tooltip and for anyone who wants
        /// to restore glyphs once the package ships a font.
        /// </summary>
        public const string MarkerGlyphNote =
            "event markers are drawn as rules rather than the dashboard's " +
            "icons: the built-in font has no glyph for them";

        // ------------------------------------------------------------------
        // the cosmetic-motion disclaimer
        // ------------------------------------------------------------------

        /// <summary>
        /// Shown while playback is interpolating.
        ///
        /// UNITY_PLAN.md Stage 5 names this the one place a viewer can imply
        /// biology that did not happen. The engine simulated year N and year
        /// N+1 and nothing in between, so a villager sliding between two
        /// settlements is the viewer's motion, not the simulation's -- and
        /// since map position is a pure function of deme and name, a slide is
        /// only ever a migration that the engine recorded as instantaneous.
        /// </summary>
        public const string CosmeticMotionNote =
            "inter-tick motion is cosmetic — a villager does not exist between years";

        /// <summary>Playback speed, e.g. "4.0 yr/s". Not a dashboard quantity:
        /// nothing in the engine has a rate in real seconds.</summary>
        public static string Speed(float yearsPerSecond) =>
            string.Format(Inv, "{0:F1} yr/s",
                          InspectorFormat.PyRound(yearsPerSecond, 1));

        /// <summary>"year 40 of 12–90", the timeline's own range readout. The
        /// low end is the FIRST RETAINED year, which is not necessarily zero:
        /// the engine's snapshot ring is capped and a long run drops its
        /// earliest years.</summary>
        public static string Range(int year, int first, int last) =>
            string.Format(Inv, "year {0} of {1}–{2}", year, first, last);
    }
}
