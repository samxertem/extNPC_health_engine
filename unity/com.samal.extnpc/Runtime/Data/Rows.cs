using UnityEngine;

namespace ExtNPC.Data
{
    /// <summary>
    /// One living villager at one tick, from frames.csv.
    ///
    /// A struct, and laid out to be small: a 600-person, 600-year world is
    /// ~360,000 of these. Strings are pooled by the loader, so `Name` and
    /// `Lineage` cost a reference each rather than an allocation.
    ///
    /// THREE LIMITS inherited from simulation/snapshots.py, which the viewer
    /// must not paper over:
    ///   * frames hold the LIVING only -- a death is a disappearance, not a row;
    ///   * the engine's snapshot ring is capped, so a long run loses its
    ///     earliest years. Check Manifest.Frames.Truncated before labelling a
    ///     timeline as starting at year 0;
    ///   * these ~18 scalars are all there is. There are no genomes here, so a
    ///     dead villager's genetic character sheet is not recoverable. That is
    ///     a deliberate engine decision, not an omission to work around.
    /// </summary>
    public struct FrameRow
    {
        public int Tick;
        public string Name;
        public float X, Y;              // engine map units, 0..MAP_SIZE
        public Color32 Color;           // lineage colour, parsed not recomputed
        public bool IsFemale;
        public int Age;
        public int Deme;
        public string Lineage;          // dominant founder
        public float Purity;            // that founder's ancestry fraction
        public int Generation;
        public int Children;
        public float Stress;            // inflammation state
        public float EpiAccel;          // epigenetic age acceleration
        public float Aerobic;
        public int Conditions;
        public float PedigreeF;
        public float Viability;
        public int Cnv;

        /// <summary>Stature EXPRESSED AT THIS AGE (cm), not the mature value.
        /// snapshots.py draws this distinction on purpose -- a child must not
        /// be rendered adult-sized. people.csv's trait_height_cm is the mature
        /// phenotype and is a different quantity.</summary>
        public float HeightCm;

        public string LifeStage;
    }

    /// <summary>One settlement at one tick, from demes.csv.</summary>
    public struct DemeRow
    {
        public int Tick;
        public int Deme;
        public float X, Y;
        public float Radius;
        public int Count;
        public float MeanStress, MaxStress;
        public string Dominant;         // dominant bloodline
        public float Dominance;         // its share, 0..1
        public Color32 DominantColor;
    }

    /// <summary>One active migration route at one tick, from flows.csv.
    /// Legitimately empty in a single-deme world -- there is nowhere to go.</summary>
    public struct FlowRow
    {
        public int Tick;
        public float X0, Y0, X1, Y1;
        public float Weight;
    }

    /// <summary>One notable moment, from events.csv: shocks, plagues,
    /// bottlenecks. The timeline's markers.</summary>
    public struct EventRow
    {
        public int Tick;
        public string Kind;
        public string Label;
    }

    /// <summary>
    /// One simulated year of population scalars, from history.csv.
    ///
    /// Held as a name-indexed float row rather than a fixed struct because the
    /// engine's metrics table grows between sessions and a viewer must not
    /// need recompiling to keep loading worlds. Charts belong in the dashboard;
    /// the viewer reads a handful of these for on-screen overlays.
    /// </summary>
    public sealed class HistoryRow
    {
        public int Tick;
        public readonly System.Collections.Generic.Dictionary<string, float> Values =
            new System.Collections.Generic.Dictionary<string, float>();

        public float Get(string key, float fallback = float.NaN) =>
            Values.TryGetValue(key, out float v) ? v : fallback;

        public bool Has(string key) => Values.ContainsKey(key);
    }

    /// <summary>
    /// One individual who has ever lived, from people.csv.
    ///
    /// CROSS-SECTIONAL: each row is the person as they are now, or as they were
    /// at death. The dead are included deliberately -- dropping them conditions
    /// any analysis on survival. Held with a raw-field dictionary alongside the
    /// typed essentials so the 25 trait_* columns stay reachable without this
    /// struct having to enumerate them.
    /// </summary>
    public sealed class PersonRow
    {
        public string Name;
        public string GivenName;
        public bool IsFemale;
        public int Age;
        public bool Alive;
        public int Generation;
        public string LifeStage;
        public string Mother, Father;
        public int Deme;
        public string DemeLabel;
        public float PedigreeF;
        public float RealisedF;
        public float RelativeViability;
        public string[] MendelianDiagnoses;
        public string[] MendelianCarrierOf;
        public string[] MedicalConditions;

        /// <summary>Every column as written, for the fields the inspector
        /// shows verbatim (trait_*, mito_haplogroup, and anything a later
        /// engine session adds).</summary>
        public System.Collections.Generic.Dictionary<string, string> Raw;

        public string GetRaw(string column) =>
            Raw != null && Raw.TryGetValue(column, out string v) ? v : null;

        public float GetTrait(string trait) =>
            CsvParse.Float(GetRaw("trait_" + trait), float.NaN);
    }
}
