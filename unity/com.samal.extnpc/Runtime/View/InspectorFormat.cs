using System.Globalization;
using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// Every label, unit, rounding rule and colour threshold the inspector
    /// uses, in ONE place, each one naming the Python line it mirrors.
    ///
    /// WHY A TABLE AND NOT INLINE FORMATTING. UNITY_PLAN.md invariant 6: the
    /// viewer and the dashboard must never describe the same villager
    /// differently. That is not enforceable when `F.ToString("F4")` is written
    /// at nine call sites -- eight get updated and the ninth becomes a quiet
    /// disagreement. Concentrating them here makes drift a diff in one file,
    /// and lets tests/test_unity_contract.py compare these numbers with
    /// dashboard/inspector.py's directly.
    ///
    /// WHAT THIS IS NOT. Nothing here derives a biological quantity. Every
    /// function takes a value the engine exported and decides how to *print*
    /// it. `RelationshipLabel` is the one that looks like an exception and is
    /// not: it is a lookup that turns an exported F into the dashboard's own
    /// wording, exactly as inspector.relationship_label does, and it invents
    /// no number.
    /// </summary>
    public static class InspectorFormat
    {
        private static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        /// <summary>
        /// Round the way Python does, because .NET does not.
        ///
        /// Python's format spec rounds **half to even** (banker's rounding);
        /// .NET's "F"/"0.00" formats round **half away from zero**. On any
        /// value that is not an exact midpoint the two agree, which is why
        /// this went unnoticed until the generated parity fixture ran:
        ///
        ///     F = 0.03125   Python "0.0312"   .NET "0.0313"
        ///     purity 0.125  Python "12%"      .NET "13%"
        ///     purity 0.375  Python "38%"      .NET "38%"   (agree)
        ///
        /// That third line is the tell — a rounding-MODE difference, not a
        /// precision one.
        ///
        /// And these are not contrived values. Pedigree F and lineage purity
        /// are dyadic rationals (sums of 2^-k), so exact midpoints are the
        /// normal case rather than the exotic one: 0.03125 is the ladder's own
        /// "first cousins once removed" threshold, and 0.125 is a plain one
        /// eighth of ancestry. A villager could have been described as 13%
        /// Elira in Unity and 12% Elira in the dashboard.
        ///
        /// Applied through EVERY fixed-decimal formatter below. Rounding at
        /// some of them would be worse than rounding at none: the failures
        /// would then depend on which field you were looking at.
        ///
        /// PUBLIC because Stage 5's <see cref="TimelineFormat"/> mirrors
        /// dashboard/panels.py's KPI tiles and needs the identical rule. A
        /// second copy of it would be a second rounding mode, which is the
        /// failure this method exists to have fixed once.
        /// </summary>
        /// THE TWO WRONG IMPLEMENTATIONS, both of which this package shipped.
        /// Recorded because each one looks obviously right and each one was
        /// caught only by running the C# suite against the generated fixture.
        ///
        /// 1. `Math.Round(value, digits, ToEven)`. Math.Round(double, int, ...)
        ///    SCALES BY A POWER OF TEN and rounds the product, so it decides
        ///    midpoints on a number that is not the one being formatted:
        ///    -1.385 is stored as -1.38500000000000000888..., strictly past the
        ///    midpoint, so Python prints -1.39 -- but -1.385 * 100 rounds to
        ///    exactly -138.5, a midpoint the value never had, and ToEven then
        ///    picks -1.38.
        ///
        /// 2. Leaving the value alone and letting .NET's formatter round it.
        ///    That is correct on .NET Core 3.0+, whose formatter converts the
        ///    exact binary value. UNITY'S MONO DOES NOT: it rounds to about 15
        ///    significant digits first, so -0.72499999999999997779 becomes
        ///    "-0.725" and then goes half-away-from-zero to -0.73, where Python
        ///    gives -0.72. Fixing (1) turned three failures into three
        ///    different ones.
        ///
        /// Each was right four times in five, which is the worst failure shape
        /// there is: a rule that looks correct with a bad input. So the
        /// rounding is done here, exactly, on the value's own bits, and the
        /// formatter is only ever handed a number that is already at `digits`
        /// decimals.
        /// </summary>
        public static double PyRound(double value, int digits)
        {
            if (double.IsNaN(value) || double.IsInfinity(value)) return value;
            if (digits < 0 || digits > 15) return value;

            double scale = Pow10(digits);
            double scaled = value * scale;
            if (System.Math.Abs(scaled) > 9.007199254740992E15) return value;

            // FAST PATH, and it is the path taken by nearly every value. The
            // scaled product carries a relative error around 1e-16, so a
            // fractional part further than 1e-6 from the midpoint is on the
            // side it appears to be on, and no exact arithmetic is needed. This
            // matters: the inspector formats a few dozen numbers per frame and
            // the exact path below allocates.
            double frac = scaled - System.Math.Floor(scaled);
            if (System.Math.Abs(frac - 0.5) > 1e-6)
                return System.Math.Floor(scaled + 0.5) / scale;

            return ExactHalfEven(value, digits, scale);
        }

        /// <summary>
        /// Round to <paramref name="digits"/> decimals, half to even, decided
        /// on the value's EXACT binary expansion -- which is what Python's
        /// format spec does and what neither Math.Round nor Mono's formatter
        /// does.
        ///
        /// A double is m * 2^e exactly. Rounding it at d decimals is therefore
        /// an exact question about the integer ratio (m * 10^d) / 2^-e, and
        /// BigInteger answers it without a rounding step of its own. Ties go to
        /// even, which is the only case where Python and .NET's formatter
        /// genuinely differ by design -- and it is not exotic here: pedigree F
        /// and lineage purity are sums of 2^-k, so for those fields an exact
        /// midpoint (0.125 -> "12%", 0.03125 -> "0.0312") is the ordinary case.
        /// </summary>
        private static double ExactHalfEven(double value, int digits, double scale)
        {
            long bits = System.BitConverter.DoubleToInt64Bits(value);
            int sign = bits < 0 ? -1 : 1;
            int biased = (int)((bits >> 52) & 0x7FF);
            long mantissa = bits & 0xFFFFFFFFFFFFFL;

            int exponent;
            if (biased == 0) { exponent = -1074; }                 // subnormal
            else { mantissa |= 1L << 52; exponent = biased - 1075; }

            var num = new System.Numerics.BigInteger(mantissa)
                      * System.Numerics.BigInteger.Pow(10, digits);
            System.Numerics.BigInteger n;

            if (exponent >= 0)
            {
                // No fractional part at all: the scaled value is an integer.
                n = num << exponent;
            }
            else
            {
                System.Numerics.BigInteger den = System.Numerics.BigInteger.One << -exponent;
                n = System.Numerics.BigInteger.DivRem(num, den,
                        out System.Numerics.BigInteger rem);
                int cmp = (rem << 1).CompareTo(den);
                if (cmp > 0 || (cmp == 0 && !n.IsEven)) n += 1;
            }

            return sign * (double)n / scale;
        }

        private static double Pow10(int digits)
        {
            double p = 1.0;
            for (int i = 0; i < digits; i++) p *= 10.0;
            return p;
        }

        private static double Py(double value, int digits) => PyRound(value, digits);

        // ------------------------------------------------------------------
        // palette -- dashboard/panels.py:26-44
        // ------------------------------------------------------------------
        // Held as hex strings so they are greppable against the Python source
        // and comparable by a test. A colour written as an (r,g,b) triple here
        // could not be checked against "#d03b3b" without a human converting it.

        public const string InkHex = "#ffffff";      // panels.py:28  INK
        public const string Ink2Hex = "#d3d2c9";     // panels.py:29  INK2
        public const string MutedHex = "#a5a39c";    // panels.py:35  MUTED
        public const string GridHex = "#2c2c2a";     // panels.py:36  GRID
        public const string SurfaceHex = "#1a1a19";  // panels.py:26  SURFACE
        public const string PlaneHex = "#0d0d0d";    // panels.py:27  PLANE
        public const string GoodHex = "#0ca30c";     // panels.py:41  GOOD
        public const string CritHex = "#d03b3b";     // panels.py:42  CRIT
        public const string WarnHex = "#c98500";     // panels.py:43  WARN
        public const string AccentHex = "#4ea3ff";   // panels.py:44  ACCENT

        public static readonly Color Ink = Hex(InkHex);
        public static readonly Color Ink2 = Hex(Ink2Hex);
        public static readonly Color Muted = Hex(MutedHex);
        public static readonly Color Grid = Hex(GridHex);
        public static readonly Color Surface = Hex(SurfaceHex);
        public static readonly Color Plane = Hex(PlaneHex);
        public static readonly Color Good = Hex(GoodHex);
        public static readonly Color Crit = Hex(CritHex);
        public static readonly Color Warn = Hex(WarnHex);
        public static readonly Color Accent = Hex(AccentHex);

        private static Color Hex(string s) =>
            ColorUtility.TryParseHtmlString(s, out Color c) ? c : Color.magenta;

        // ------------------------------------------------------------------
        // pedigree F -- inspector.py:99-125
        // ------------------------------------------------------------------

        /// <summary>
        /// The relationship ladder, verbatim from inspector.py:99 `_F_LABELS`.
        ///
        /// The label is the CLOSEST standard mating at or below the observed
        /// F, so it reads as "at least this close". Order matters: the scan
        /// returns the first match, descending.
        /// </summary>
        private static readonly (float Threshold, string Label)[] FLabels =
        {
            (0.25f,     "full sib / parent–offspring"),
            (0.125f,    "uncle–niece / double first cousin"),
            (0.0625f,   "first cousins"),
            (0.03125f,  "first cousins once removed"),
            (0.015625f, "second cousins"),
        };

        /// <summary>Plain-language reading of a pedigree inbreeding
        /// coefficient. Mirrors inspector.relationship_label (inspector.py:108),
        /// including its 1e-9 tolerances.</summary>
        public static string RelationshipLabel(double f)
        {
            foreach (var (threshold, label) in FLabels)
            {
                if (f >= threshold - 1e-9) return label;
            }
            return f <= 1e-9 ? "outbred" : "distant kin";
        }

        /// <summary>inspector.py:116 `_fmt_f` -- four decimals, but a bare "0"
        /// at zero. Four matters: a first-cousin child (0.0625) and a
        /// second-cousin child (0.0156) are indistinguishable at two, and
        /// telling them apart is the entire point of showing F.</summary>
        public static string FmtF(double f) =>
            f == 0.0 ? "0" : Py(f, 4).ToString("F4", Inv);

        /// <summary>inspector.py:120 `_f_color`. Thresholds are the standard
        /// consanguinity marks: first cousins (0.0625) critical, second
        /// cousins (0.015625) warning.</summary>
        public static Color FColor(double f)
        {
            if (f >= 0.0625f) return Crit;
            if (f >= 0.015625f) return Warn;
            return Ink;
        }

        // ------------------------------------------------------------------
        // the other thresholds the drawer applies -- inspector.py:328-345
        // ------------------------------------------------------------------

        /// <summary>Viability below 0.9 is shown critical (inspector.py:340).</summary>
        public static Color ViabilityColor(double v) => v < 0.9 ? Crit : Ink;

        /// <summary>Epigenetic age acceleration above 3 years is critical
        /// (inspector.py:304, 306).</summary>
        public static Color EpiAccelColor(double years) => years > 3.0 ? Crit : Ink;

        /// <summary>Inflammation above 0.6 is critical (inspector.py:308).</summary>
        public static Color StressColor(double s) => s > 0.6 ? Crit : Ink;

        /// <summary>inspector.py:88 `_norm` -- clamp into [0,1] for a meter,
        /// handling signed liabilities.</summary>
        public static double Norm(double value, double lo, double hi)
        {
            if (hi <= lo) return 0.0;
            double t = (value - lo) / (hi - lo);
            return t < 0.0 ? 0.0 : (t > 1.0 ? 1.0 : t);
        }

        /// <summary>The stress meter's range, from inspector.py:325/344
        /// `_norm(stress, -1.5, 2.5)`. Named rather than repeated so the
        /// viewer's meter cannot end up on a different scale to the
        /// dashboard's.</summary>
        public const double StressMeterLo = -1.5;
        public const double StressMeterHi = 2.5;

        // ------------------------------------------------------------------
        // number and name formatting
        // ------------------------------------------------------------------
        //
        // Every one of these goes through InvariantCulture, and the *format
        // strings* are spelled to match Python's output rather than to use the
        // nearest-named .NET specifier. The trap that motivates the comment:
        // Python's f"{p:.0%}" gives "50%", while C#'s ToString("P0",
        // InvariantCulture) gives "50 %" -- invariant culture's percent
        // pattern puts a space before the sign. Mirroring a formatter means
        // mirroring its OUTPUT, not calling the method with a similar name.

        /// <summary>f"{v:.1f} cm" -- inspector.py:330.</summary>
        public static string Height(double cm) =>
            string.Format(Inv, "{0:F1} cm", Py(cm, 1));

        /// <summary>f"{v:+.2f}" -- stress, inspector.py:332.</summary>
        public static string Signed2(double v) =>
            string.Format(Inv, "{0:+0.00;-0.00;+0.00}", Py(v, 2));

        /// <summary>f"{v:.2f}" -- VO2, inspector.py:333.</summary>
        public static string Fixed2(double v) => Py(v, 2).ToString("F2", Inv);

        /// <summary>f"{v:.3f}" -- viability, inspector.py:339.</summary>
        public static string Fixed3(double v) => Py(v, 3).ToString("F3", Inv);

        /// <summary>f"{v:+.1f} y" -- age acceleration, inspector.py:334.</summary>
        public static string SignedYears(double v) =>
            string.Format(Inv, "{0:+0.0;-0.0;+0.0} y", Py(v, 1));

        /// <summary>f"{p:.0%}" -- lineage purity pill, inspector.py:260.
        /// Written as F0 on a x100 value, NOT as "P0"; see the note above.
        /// Python multiplies by 100 and THEN rounds, so an eighth of ancestry
        /// is 12.5 at the rounding step -- an exact midpoint, and the reason
        /// this goes through Py().</summary>
        public static string Percent0(double fraction) =>
            string.Format(Inv, "{0:F0}%", Py(fraction * 100.0, 0));

        public static string Int(int v) => v.ToString(Inv);

        /// <summary>
        /// The headline height row, mirroring inspector.py:290.
        ///
        /// While an individual is still growing, BOTH figures are shown: the
        /// stature expressed at this age and the mature endpoint it is growing
        /// toward. Showing only the mature value is the defect roadmap #13
        /// exists to prevent -- it renders a five-year-old at adult stature and
        /// looks entirely normal.
        ///
        /// The two-space gap before the arrow is the dashboard's, and is
        /// reproduced rather than tidied: acceptance for this stage is a
        /// character-for-character match.
        /// </summary>
        public static string HeightLive(double nowCm, double matureCm)
        {
            return IsGrowing(nowCm, matureCm)
                ? string.Format(Inv, "{0:F1} cm  → {1:F0} adult",
                                Py(nowCm, 1), Py(matureCm, 0))
                : string.Format(Inv, "{0:F1} cm", Py(nowCm, 1));
        }

        /// <summary>inspector.py:285 -- "still growing" is a 0.05 cm gap
        /// between expressed and mature stature.</summary>
        public static bool IsGrowing(double nowCm, double matureCm) =>
            System.Math.Abs(nowCm - matureCm) > 0.05;

        /// <summary>
        /// BMI, mirroring inspector.py:300.
        ///
        /// Labelled "at maturity" while the individual is still growing,
        /// because it IS the mature value: #13 models stature only --
        /// Preece-Baines is a height curve and the engine has no body-mass
        /// trajectory -- so there is nothing to age-express BMI with. The bare
        /// number put "BMI 24.4" against a three-year-old, which is not a
        /// possible value for a toddler (~15-16) and reads as a measurement
        /// rather than an endpoint.
        /// </summary>
        public static string Bmi(double bmi, bool growing) =>
            growing ? string.Format(Inv, "{0:F1} at maturity", Py(bmi, 1))
                    : string.Format(Inv, "{0:F1}", Py(bmi, 1));

        /// <summary>f"{v:+.4f}" -- realised F, inspector.py:152.</summary>
        public static string Signed4(double v) =>
            string.Format(Inv, "{0:+0.0000;-0.0000;+0.0000}", Py(v, 4));

        /// <summary>f"{v:+.2f} cm" -- the stature cost of inbreeding,
        /// inspector.py:158. Critical at or below -1 cm, warning otherwise;
        /// the row appears at all only when F > 0.</summary>
        public static string StatureCost(double cm) =>
            string.Format(Inv, "{0:+0.00;-0.00;+0.00} cm", Py(cm, 2));

        public static Color StatureCostColor(double cm) => cm <= -1.0 ? Crit : Warn;

        /// <summary>The display name. The engine's key is "Given-NNNN"; every
        /// dashboard surface shows the part before the first dash
        /// (inspector.py:252, 435, 548).</summary>
        public static string GivenName(string key)
        {
            if (string.IsNullOrEmpty(key)) return "";
            int dash = key.IndexOf('-');
            return dash < 0 ? key : key.Substring(0, dash);
        }

        /// <summary>"female" / "male", as frames.csv writes it and the drawer
        /// prints it (inspector.py:253).</summary>
        public static string Sex(bool isFemale) => isFemale ? "female" : "male";
    }
}
