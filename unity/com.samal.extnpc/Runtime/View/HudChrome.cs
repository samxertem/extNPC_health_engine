using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// The HUD's drawing primitives, in one place so the two panels cannot
    /// drift into looking like two different products.
    ///
    /// WHAT THIS IS ALLOWED TO DO. Chrome only: frames, rules, ticks, pills,
    /// bars. Nothing here formats a value, names a quantity or picks a
    /// semantic colour. Those live in <see cref="InspectorFormat"/> and
    /// <see cref="TimelineFormat"/>, which mirror the dashboard, and a
    /// decoration helper that started deciding what "high" looks like would be
    /// the second definition UNITY_PLAN.md invariant 6 forbids.
    ///
    /// EVERY COLOUR IS THE DASHBOARD'S. The palette hexes in InspectorFormat
    /// are pinned against `dashboard/panels.py` by a test. What this file adds
    /// is ALPHA and GEOMETRY, which are not colour decisions: a shadow is
    /// black at 25%, a tint is Accent at 12%. No new hex is introduced, so
    /// there is nothing here for the palette to disagree with.
    ///
    /// WHY IT LOOKS LIKE AN INSTRUMENT. The viewer is not a game UI; it is the
    /// readout of a simulation whose numbers a thesis rests on. Corner ticks,
    /// hairlines and dotted leaders are the visual language of measurement,
    /// and they cost nothing but geometry. The alternative, rounded cards and
    /// gradients, reads as a product and quietly invites the numbers to be
    /// taken less seriously.
    /// </summary>
    public static class HudChrome
    {
        private static Texture2D _px;

        /// <summary>A 1x1 white texture, shared by every panel.
        ///
        /// One per domain rather than one per component: the two panels used to
        /// allocate and destroy their own, which is two textures for a job that
        /// needs one and a lifetime bug waiting for whichever of them was
        /// destroyed first while the other still referenced it.</summary>
        public static Texture2D Pixel
        {
            get
            {
                if (_px == null)
                {
                    _px = new Texture2D(1, 1)
                    { hideFlags = HideFlags.HideAndDontSave };
                    _px.SetPixel(0, 0, Color.white);
                    _px.Apply();
                }
                return _px;
            }
        }

        // ------------------------------------------------------------------
        // atoms
        // ------------------------------------------------------------------

        public static void Fill(Rect r, Color c)
        {
            if (Event.current.type != EventType.Repaint) return;
            Color prev = GUI.color;
            GUI.color = c;
            GUI.DrawTexture(r, Pixel);
            GUI.color = prev;
        }

        public static void Outline(Rect r, Color c)
        {
            Fill(new Rect(r.x, r.y, r.width, 1f), c);
            Fill(new Rect(r.x, r.yMax - 1f, r.width, 1f), c);
            Fill(new Rect(r.x, r.y, 1f, r.height), c);
            Fill(new Rect(r.xMax - 1f, r.y, 1f, r.height), c);
        }

        /// <summary>A hairline at 40% of the grid colour. Full-strength rules
        /// between every KPI row turn a panel into a table with too many
        /// borders; the eye needs the separation, not the emphasis.</summary>
        public static void Hairline(Rect r)
        {
            Color c = InspectorFormat.Grid;
            c.a = 0.4f;
            Fill(r, c);
        }

        /// <summary>
        /// The dotted leader between a label and its value.
        ///
        /// The oldest trick in tabular typesetting, and it earns its place on a
        /// panel this narrow: with a bare gap the eye loses the row on the way
        /// across and reads the wrong number against the wrong label, which on
        /// this particular panel means misreading F_ST as inbreeding F.
        /// </summary>
        public static void Leader(Rect r)
        {
            if (Event.current.type != EventType.Repaint) return;
            Color c = InspectorFormat.Grid;
            c.a = 0.55f;
            for (float x = r.x; x < r.xMax; x += 4f)
                Fill(new Rect(x, r.y, 1f, 1f), c);
        }

        // ------------------------------------------------------------------
        // panels
        // ------------------------------------------------------------------

        /// <summary>
        /// A panel: shadow, ground, frame, and a tick at each corner.
        ///
        /// The corner ticks are the whole idea. A continuous rectangle reads as
        /// a box; four short marks read as a registered instrument window, and
        /// they do it with sixteen filled rects and no texture.
        /// </summary>
        public static void Panel(Rect area)
        {
            // Shadow first, offset down and right, so the panel sits ABOVE the
            // scene rather than being painted onto it. Two passes rather than a
            // blurred texture: cheap, and at this size indistinguishable.
            var shadow = new Color(0f, 0f, 0f, 0.28f);
            Fill(new Rect(area.x + 3f, area.y + 3f, area.width, area.height), shadow);
            Fill(new Rect(area.x + 6f, area.y + 6f, area.width, area.height),
                 new Color(0f, 0f, 0f, 0.14f));

            Fill(area, InspectorFormat.Surface);
            Outline(area, InspectorFormat.Grid);
            CornerTicks(area, 9f, InspectorFormat.Accent);
        }

        /// <summary>Short bright marks at the four corners, over the frame.</summary>
        public static void CornerTicks(Rect a, float len, Color c)
        {
            c.a = 0.75f;
            // top-left
            Fill(new Rect(a.x, a.y, len, 1f), c);
            Fill(new Rect(a.x, a.y, 1f, len), c);
            // top-right
            Fill(new Rect(a.xMax - len, a.y, len, 1f), c);
            Fill(new Rect(a.xMax - 1f, a.y, 1f, len), c);
            // bottom-left
            Fill(new Rect(a.x, a.yMax - 1f, len, 1f), c);
            Fill(new Rect(a.x, a.yMax - len, 1f, len), c);
            // bottom-right
            Fill(new Rect(a.xMax - len, a.yMax - 1f, len, 1f), c);
            Fill(new Rect(a.xMax - 1f, a.yMax - len, 1f, len), c);
        }

        /// <summary>
        /// A section header: the title's own strip, with a rule under it.
        ///
        /// Drawn rather than laid out because GUILayout cannot paint behind the
        /// label it is placing.
        /// </summary>
        public static void SectionBar(Rect r)
        {
            Color tint = InspectorFormat.Accent;
            tint.a = 0.10f;
            Fill(r, tint);
            Color edge = InspectorFormat.Accent;
            edge.a = 0.55f;
            Fill(new Rect(r.x, r.yMax - 1f, r.width, 1f), edge);
            // The accent block at the head of the strip, so the eye finds the
            // start of a section before it reads the word.
            Fill(new Rect(r.x, r.y, 2f, r.height), InspectorFormat.Accent);
        }

        /// <summary>A filled pill behind a short status word.</summary>
        public static void Pill(Rect r, Color c)
        {
            Color bg = c;
            bg.a = 0.16f;
            Fill(r, bg);
            Color edge = c;
            edge.a = 0.5f;
            Outline(r, edge);
        }

        // ------------------------------------------------------------------
        // the scrub track
        // ------------------------------------------------------------------

        /// <summary>
        /// The timeline's own ruler: a groove, the years already played, a tick
        /// every ten years and a taller one at each end.
        ///
        /// The elapsed fill is the part that makes it read as a transport
        /// rather than a slider. It is drawn from the FIRST RETAINED year, not
        /// from zero, because a capped snapshot ring means the timeline does
        /// not necessarily start at the world's first year and a bar that
        /// implied otherwise would misstate the run's length.
        /// </summary>
        public static void ScrubTrack(Rect track, float fraction,
                                      int firstYear, int lastYear)
        {
            float mid = track.center.y;
            var groove = new Rect(track.x, mid - 2f, track.width, 4f);
            Fill(groove, InspectorFormat.Plane);

            Color filled = InspectorFormat.Accent;
            filled.a = 0.85f;
            Fill(new Rect(groove.x, groove.y,
                          groove.width * Mathf.Clamp01(fraction), groove.height),
                 filled);

            int span = lastYear - firstYear;
            if (span <= 0) return;

            // Brighter than the Grid hairlines used inside the panels: these sit
            // on the Plane groove rather than on Surface, and at Grid strength
            // they were invisible against it.
            Color tick = Color.Lerp(InspectorFormat.Grid, InspectorFormat.Ink2, 0.35f);
            int step = span > 400 ? 100 : span > 160 ? 50 : span > 40 ? 10 : 5;
            for (int y = firstYear; y <= lastYear; y++)
            {
                if (y % step != 0) continue;
                float t = (float)(y - firstYear) / span;
                float x = track.x + t * track.width;
                bool decade = y % (step * 5) == 0;
                float h = decade ? 7f : 4f;
                Fill(new Rect(x, mid + 4f, 1f, h), tick);
            }
        }

        /// <summary>The playhead: a bright vertical bar with a cap, so the
        /// current year is findable at a glance against the event markers,
        /// which are the same width and a different colour.</summary>
        public static void Playhead(Rect track, float fraction)
        {
            float x = track.x + track.width * Mathf.Clamp01(fraction);
            Fill(new Rect(x - 1f, track.y, 3f, track.height),
                 InspectorFormat.Ink);
            Fill(new Rect(x - 4f, track.y, 9f, 3f), InspectorFormat.Ink);
        }
    }
}
