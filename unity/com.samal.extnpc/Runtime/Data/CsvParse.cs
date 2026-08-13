using System;
using System.Collections.Generic;
using System.Globalization;
using UnityEngine;

namespace ExtNPC.Data
{
    /// <summary>
    /// Scalar conversions for engine-written CSV fields.
    ///
    /// Every parse here passes <see cref="CultureInfo.InvariantCulture"/>, and
    /// that is not defensive boilerplate. Python writes "1.75" with a dot. On a
    /// machine whose locale uses a comma decimal separator -- German, Turkish,
    /// French, most of Europe -- <c>float.Parse("1.75")</c> with the ambient
    /// culture returns <b>175</b>. It does not throw. A villager 175 metres
    /// tall is the *good* case, because you would notice; a 1.75 -> 175 on a
    /// stress or viability column is a plausible-looking wrong number.
    /// <see cref="CsvParseTests"/> pins this under a de-DE culture.
    ///
    /// Python's spellings are accepted where they differ from .NET's:
    /// "True"/"False" for booleans, "nan"/"inf"/"-inf" for non-finite floats.
    /// </summary>
    public static class CsvParse
    {
        private static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

        /// <summary>Empty means null/absent in the engine's dialect.</summary>
        public static bool IsBlank(string s) => string.IsNullOrEmpty(s);

        public static float Float(string s, float fallback = 0f)
        {
            if (IsBlank(s)) return fallback;
            if (float.TryParse(s, NumberStyles.Float, Inv, out float v)) return v;

            // Python writes nan / inf / -inf; .NET expects NaN / Infinity.
            switch (s.Trim().ToLowerInvariant())
            {
                case "nan": return float.NaN;
                case "inf":
                case "+inf":
                case "infinity": return float.PositiveInfinity;
                case "-inf":
                case "-infinity": return float.NegativeInfinity;
                default:
                    throw new BundleFormatException($"not a number: '{s}'");
            }
        }

        /// <summary>
        /// Non-throwing <see cref="Float"/>, for cells whose type is not known
        /// in advance.
        ///
        /// The inspector needs this: people.csv's trait_* columns are a mix of
        /// continuous values (height_cm, bmi) and categorical strings
        /// (eye_color, handedness), and the viewer must render a category
        /// verbatim rather than guess a number for it. Returns false — never
        /// throws — for blanks and for anything non-numeric, so "this is a
        /// word" is an answer rather than a load failure.
        /// </summary>
        public static bool TryFloat(string s, out float value)
        {
            value = 0f;
            if (IsBlank(s)) return false;
            if (float.TryParse(s, NumberStyles.Float, Inv, out value)) return true;
            switch (s.Trim().ToLowerInvariant())
            {
                case "nan": value = float.NaN; return true;
                case "inf":
                case "+inf":
                case "infinity": value = float.PositiveInfinity; return true;
                case "-inf":
                case "-infinity": value = float.NegativeInfinity; return true;
                default: return false;
            }
        }

        public static int Int(string s, int fallback = 0)
        {
            if (IsBlank(s)) return fallback;
            if (int.TryParse(s, NumberStyles.Integer, Inv, out int v)) return v;

            // Tolerate an integral value written as a float ("3.0"), which
            // happens wherever numpy widened a count.
            if (float.TryParse(s, NumberStyles.Float, Inv, out float f) &&
                Mathf.Approximately(f, Mathf.Round(f)))
            {
                return (int)Mathf.Round(f);
            }
            throw new BundleFormatException($"not an integer: '{s}'");
        }

        /// <summary>Python's csv writer emits bare True/False.</summary>
        public static bool Bool(string s, bool fallback = false)
        {
            if (IsBlank(s)) return fallback;
            switch (s.Trim().ToLowerInvariant())
            {
                case "true": case "1": case "yes": return true;
                case "false": case "0": case "no": return false;
                default:
                    throw new BundleFormatException($"not a boolean: '{s}'");
            }
        }

        /// <summary>"#rrggbb" as written by lineage.color_hex.
        ///
        /// Parsed, never recomputed. The HSV rule (hue = founder, saturation =
        /// lineage purity, value = alive/dead) lives in one place, in
        /// simulation/lineage.py, and travels in the data. Reimplementing it
        /// here would create a second definition that can drift, and the
        /// dashboard and the viewer would eventually colour the same villager
        /// differently.</summary>
        public static Color32 Color(string s, Color32 fallback)
        {
            if (IsBlank(s)) return fallback;
            if (ColorUtility.TryParseHtmlString(s, out Color c)) return c;
            return fallback;
        }

        /// <summary>Semicolon-joined list cell (mendelian_diagnoses,
        /// medical_conditions, mendelian_carrier_of). Empty cell -> empty
        /// array, never null.</summary>
        public static string[] List(string s)
        {
            if (IsBlank(s)) return Array.Empty<string>();
            return s.Split(';');
        }

        /// <summary>
        /// Interning pool for columns whose values repeat across every row.
        ///
        /// frames.csv repeats each villager's name and lineage once per year:
        /// 600 people x 600 years is 360,000 string allocations for ~600
        /// distinct values. Pooling collapses that to the distinct set and is
        /// the single largest memory win in the loader.
        /// </summary>
        public sealed class StringPool
        {
            private readonly Dictionary<string, string> _pool =
                new Dictionary<string, string>(StringComparer.Ordinal);

            public string Get(string s)
            {
                if (string.IsNullOrEmpty(s)) return string.Empty;
                if (_pool.TryGetValue(s, out string existing)) return existing;
                _pool[s] = s;
                return s;
            }

            public int Count => _pool.Count;
        }
    }
}
