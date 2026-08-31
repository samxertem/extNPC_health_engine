using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// The HUD's coordinate space and its typeface: the two things that
    /// decide whether the viewer is readable on a screen that is not the
    /// author's.
    ///
    /// THE PROBLEM. IMGUI works in raw pixels and does not scale with display
    /// density. Every panel in this package is laid out in numbers that were
    /// chosen while looking at one monitor, so the same HUD that is correct
    /// there is a strip of unreadable grey on a 4K laptop and worse on a
    /// projector. That is not a taste problem, it is the difference between
    /// showing this work to somebody and apologising to them about it.
    ///
    /// WHY THE SCALE IS TAKEN FROM TWO THINGS AND NOT ONE. `Screen.dpi` is
    /// the honest signal and it is the one to trust when it is present, but
    /// it reports 0 on several platforms and is unreliable under remote
    /// desktop and capture. Resolution height is a cruder proxy that is
    /// always available. Taking the larger of the two means a screen that is
    /// dense, or tall, or both, is handled, and a screen that is neither
    /// still gets exactly 1.0 and the layout nobody asked to change.
    ///
    /// WHY IT IS ALSO OVERRIDABLE. A projector is low resolution and low DPI
    /// and still needs a bigger HUD, because the viewer is six metres away.
    /// No signal available to this code distinguishes that case from a small
    /// monitor, so it is a knob rather than a guess, and the automatic value
    /// is what the knob multiplies.
    ///
    /// HOW TO USE IT. Every <c>OnGUI</c> calls <see cref="Begin"/> first and
    /// <see cref="End"/> last, and uses <see cref="Width"/> and
    /// <see cref="Height"/> in place of <c>Screen.width</c> and
    /// <c>Screen.height</c>. The second half is not optional: the scale is a
    /// transform on the drawing matrix, so a panel positioned from
    /// <c>Screen.width</c> inside a scaled matrix lands off the right edge of
    /// a scaled screen.
    /// </summary>
    public static class HudScale
    {
        /// <summary>The density the layout numbers in this package were
        /// chosen at. Windows' own reference, and the value `Screen.dpi`
        /// reports on an unscaled desktop monitor.</summary>
        public const float ReferenceDpi = 96f;

        /// <summary>The height the layout numbers were chosen at.</summary>
        public const float ReferenceHeight = 1080f;

        /// <summary>Multiplies the automatic scale. Raise it for a projector
        /// or a demonstration across a room; 1 leaves the automatic value
        /// alone. Deliberately a plain field: it is a viewer preference, not
        /// a measurement, and nothing reads it back.</summary>
        public static float userScale = 1f;

        /// <summary>Hard bounds. Below 1 the HUD would be smaller than it was
        /// authored, which no display needs and which would make the frames
        /// sub-pixel; above 3 a panel stops fitting on its own screen.</summary>
        public const float MinScale = 1f;
        public const float MaxScale = 3f;

        private static float _matrixScale = 1f;
        private static Matrix4x4 _saved;
        private static Font _font;
        private static bool _fontSearched;

        /// <summary>
        /// The scale in force, computed fresh so that dragging the window
        /// between two monitors of different density is picked up.
        /// </summary>
        public static float Current
        {
            get
            {
                float byDpi = Screen.dpi > 1f ? Screen.dpi / ReferenceDpi : 1f;
                float byHeight = Screen.height > 0
                    ? Screen.height / ReferenceHeight : 1f;
                float auto = Mathf.Max(byDpi, byHeight);
                return Mathf.Clamp(auto * Mathf.Max(0.1f, userScale),
                                   MinScale, MaxScale);
            }
        }

        /// <summary>Screen width in the HUD's own units. Use instead of
        /// <c>Screen.width</c> inside a scaled block.</summary>
        public static float Width { get { return Screen.width / _matrixScale; } }

        /// <summary>Screen height in the HUD's own units. Use instead of
        /// <c>Screen.height</c> inside a scaled block.</summary>
        public static float Height { get { return Screen.height / _matrixScale; } }

        /// <summary>
        /// Enter the scaled space and install the HUD font. Pair with
        /// <see cref="End"/>.
        /// </summary>
        public static void Begin()
        {
            _matrixScale = Current;
            _saved = GUI.matrix;
            if (!Mathf.Approximately(_matrixScale, 1f))
                GUI.matrix = Matrix4x4.Scale(
                    new Vector3(_matrixScale, _matrixScale, 1f));

            Font font = HudFont;
            if (font != null && GUI.skin != null && GUI.skin.font != font)
                GUI.skin.font = font;
        }

        /// <summary>Leave the scaled space. Restores whatever matrix was in
        /// force rather than resetting to identity, so a caller that had its
        /// own transform is not quietly clobbered.</summary>
        public static void End()
        {
            GUI.matrix = _saved;
            _matrixScale = 1f;
        }

        /// <summary>
        /// The face the HUD is drawn in, or null to keep Unity's built-in.
        ///
        /// THREE TIERS, AND THE PACKAGE STILL SHIPS NO ASSETS. First a font a
        /// consuming project chose to drop in Resources; then a dynamic font
        /// built from whatever the operating system has; then nothing, and
        /// the built-in face stays. That order keeps the property
        /// <see cref="HumanMesh"/> and <see cref="EyeMaterials"/> both rely
        /// on, that this package builds a working viewer out of an empty
        /// scene and carries no binaries.
        ///
        /// WHY THE OS LIST IS IN THIS ORDER, AND WHY IT MATTERS MORE THAN
        /// TASTE. Unity's built-in font is a bitmap Arial with a narrow
        /// repertoire, and villagers in this simulation are given Turkish
        /// names -- Gulseren, Isik, Sengul. A face without the dotless i, the
        /// breve g and the cedilla s renders those as tofu, which is one of
        /// the three human checks the headless bridge cannot make and is
        /// listed as an open item for exactly that reason. Every face named
        /// here carries Latin Extended-A; the list is ordered by platform so
        /// the first hit is the native one.
        /// </summary>
        public static Font HudFont
        {
            get
            {
                if (_fontSearched) return _font;
                _fontSearched = true;

                _font = Resources.Load<Font>("extnpc/ui/hud");
                if (_font != null) return _font;

                try
                {
                    _font = Font.CreateDynamicFontFromOSFont(
                        new[]
                        {
                            "Segoe UI",         // Windows
                            "Inter",            // installed by choice, anywhere
                            "Helvetica Neue",   // macOS
                            "SF Pro Text",      // macOS
                            "DejaVu Sans",      // Linux
                            "Liberation Sans",  // Linux
                            "Arial",            // last resort, still Extended-A
                        }, 14);
                }
                catch (System.Exception e)
                {
                    // A platform with no font enumeration is a supported
                    // state, not a failure: the HUD keeps Unity's own face
                    // and stays legible, which is what it did before.
                    Debug.Log("[extNPC] no OS font available for the HUD (" +
                              e.Message + "); keeping the built-in face.");
                    _font = null;
                }
                return _font;
            }
        }

        /// <summary>Forget the resolved font, so one dropped into Resources
        /// is picked up without restarting. Mirrors
        /// <see cref="EyeMaterials.Forget"/>.</summary>
        public static void Forget()
        {
            _font = null;
            _fontSearched = false;
        }
    }
}
