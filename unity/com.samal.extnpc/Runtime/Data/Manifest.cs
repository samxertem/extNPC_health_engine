using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace ExtNPC.Data
{
    /// <summary>
    /// Provenance for a run: what produced these numbers, exactly.
    ///
    /// Read first, always, and surfaced in the UI rather than hidden. Two
    /// exports with the same seed and a different <see cref="Catalogue"/> are
    /// different model versions and nothing in the numbers themselves says so
    /// -- that is precisely why the engine records it.
    ///
    /// Parsed with Newtonsoft rather than JsonUtility: `params` and `summary`
    /// are free-form nested objects and JsonUtility handles neither those nor
    /// dictionaries. Non-finite floats need care too -- Python's json writes a
    /// bare NaN, which is not valid strict JSON, so FloatParseHandling is set
    /// accordingly instead of letting the load fail on an extinct world.
    /// </summary>
    public sealed class Manifest
    {
        public int BundleSchema;
        public string ExportedAt;
        public string Note;
        public string GitCommit;
        public string Python;
        public string Platform;
        public int Seed;
        public int Tick;

        /// <summary>"synthetic" (the default, calibrated model) or "empirical"
        /// (the experimental 1000G-EUR core frequencies). NOT interchangeable.</summary>
        public string Catalogue;

        public FramesInfo Frames = new FramesInfo();
        public JObject Params;
        public JObject Summary;
        public List<string> Caveats = new List<string>();

        /// <summary>What frames.csv actually covers.</summary>
        public sealed class FramesInfo
        {
            public int NFrames;
            public int FirstTick;
            public int LastTick;
            public int MaxFrames;

            /// <summary>True when the engine's snapshot ring overflowed and the
            /// earliest years were dropped. A timeline that assumed year 0
            /// would be mislabelled -- say so in the UI instead.</summary>
            public bool Truncated;
        }

        /// <summary>Highest bundle schema this build knows how to read.</summary>
        public const int SupportedSchema = 1;

        public static Manifest Parse(string json)
        {
            JObject o;
            try
            {
                o = JsonConvert.DeserializeObject<JObject>(json,
                    new JsonSerializerSettings
                    {
                        FloatParseHandling = FloatParseHandling.Double
                    });
            }
            catch (JsonException e)
            {
                throw new BundleFormatException("manifest.json is not valid JSON", e);
            }
            if (o == null) throw new BundleFormatException("manifest.json is empty");

            var m = new Manifest
            {
                BundleSchema = (int?)o["bundle_schema"] ?? 0,
                ExportedAt = (string)o["exported_at"],
                Note = (string)o["note"],
                GitCommit = (string)o["git_commit"],
                Python = (string)o["python"],
                Platform = (string)o["platform"],
                Seed = (int?)o["seed"] ?? 0,
                Tick = (int?)o["tick"] ?? 0,
                Catalogue = (string)o["catalogue"] ?? "unknown",
                Params = o["params"] as JObject,
                Summary = o["summary"] as JObject,
            };

            if (o["frames"] is JObject f)
            {
                m.Frames.NFrames = (int?)f["n_frames"] ?? 0;
                m.Frames.FirstTick = (int?)f["first_tick"] ?? 0;
                m.Frames.LastTick = (int?)f["last_tick"] ?? 0;
                m.Frames.MaxFrames = (int?)f["max_frames"] ?? 0;
                m.Frames.Truncated = (bool?)f["truncated"] ?? false;
            }

            if (o["caveats"] is JArray arr)
            {
                foreach (var c in arr) m.Caveats.Add((string)c);
            }

            return m;
        }

        /// <summary>
        /// Refuse a bundle this build would misread.
        ///
        /// A schema the viewer does not know is not a warning: a reshaped table
        /// parses "successfully" into wrong values, and a viewer showing wrong
        /// numbers with no error is worse than one that will not open.
        /// </summary>
        public void RequireSupportedSchema()
        {
            if (BundleSchema > SupportedSchema)
            {
                throw new BundleFormatException(
                    $"bundle_schema {BundleSchema} is newer than this viewer " +
                    $"supports ({SupportedSchema}). Update the package rather " +
                    $"than loading a bundle it may misread.");
            }
            if (BundleSchema < 1)
            {
                throw new BundleFormatException(
                    "manifest.json has no bundle_schema -- it predates the " +
                    "world-viewer contract and its column meanings are unknown.");
            }
        }

        /// <summary>One line naming the run, for the console and the UI. The
        /// catalogue is in here deliberately: it must never be invisible.</summary>
        public override string ToString() =>
            $"seed {Seed} · year {Tick} · catalogue {Catalogue} · " +
            $"commit {(GitCommit != null && GitCommit.Length > 7 ? GitCommit.Substring(0, 7) : GitCommit)}";
    }
}
