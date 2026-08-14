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
    ///
    /// FLOAT FOR GEOMETRY, DOUBLE FOR ANYTHING PRINTED. x and y only ever
    /// become a position, so binary32 is plenty. Every field the inspector
    /// SHOWS is a double, because Python holds these values as binary64 and
    /// formats from that -- parsing the same text to binary32 here made the two
    /// UIs print different text for 77 of 1323 `stress` values on a real
    /// export. See CsvParse.Double for the measurement and the mechanism. The
    /// cost is ~28 bytes a row, about 10 MB on a 600x600 world, against a
    /// 300 MB budget.
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
        public double Purity;           // that founder's ancestry fraction
        public int Generation;
        public int Children;
        public double Stress;           // inflammation state
        public double EpiAccel;         // epigenetic age acceleration
        public double Aerobic;
        public int Conditions;
        public double PedigreeF;
        public double Viability;
        public int Cnv;

        /// <summary>Stature EXPRESSED AT THIS AGE (cm), not the mature value.
        /// snapshots.py draws this distinction on purpose -- a child must not
        /// be rendered adult-sized. people.csv's trait_height_cm is the mature
        /// phenotype and is a different quantity.</summary>
        public double HeightCm;

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

        /// <summary>The settlement's name, as simulation/community.deme_label
        /// spells it. Carried in the data rather than rebuilt in C#: the
        /// mapping is a fixed name table, and a copy of it here would go stale
        /// the moment a name is added. Empty on bundles exported before the
        /// column existed.</summary>
        public string Label;
    }

    /// <summary>
    /// One entry of the Mendelian disease panel, from diseases.csv.
    ///
    /// A REFERENCE table, not per-person data: nine rows describing the
    /// disorders health_engine/diseases.py models, joined to an individual
    /// through the slugs in people.csv's mendelian_diagnoses /
    /// mendelian_carrier_of columns.
    ///
    /// It exists because people.csv carries only the slug ("gjb2_deafness")
    /// while the dashboard shows the gene and the disorder's display name
    /// ("dx GJB2" -> "GJB2 nonsyndromic deafness"). Deriving one from the other
    /// is not possible, and hardcoding the panel in C# would be a second
    /// definition of a catalogue that is explicitly append-only.
    /// </summary>
    public sealed class DiseaseRow
    {
        public string Name;             // snake_case slug, the join key
        public string Label;            // display name
        public string Gene;
        public string Omim;             // phenotype MIM number
        public string Onset;            // infancy | childhood | adult
        public float QLit;              // literature allele frequency
        public float QEngine;           // the frequency this run actually used
        public float SLit;              // untreated homozygote fitness cost
        public string Citation;
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

        /// <summary>Double, not float: these five are the HUD's KPI strip and
        /// are printed against the dashboard's own tiles. See CsvParse.Double.</summary>
        public readonly System.Collections.Generic.Dictionary<string, double> Values =
            new System.Collections.Generic.Dictionary<string, double>();

        public double Get(string key, double fallback = double.NaN) =>
            Values.TryGetValue(key, out double v) ? v : fallback;

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
        public double PedigreeF;
        public double RealisedF;
        public double RelativeViability;
        public string[] MendelianDiagnoses;
        public string[] MendelianCarrierOf;
        public string[] MedicalConditions;

        /// <summary>Every column as written, for the fields the inspector
        /// shows verbatim (trait_*, mito_haplogroup, and anything a later
        /// engine session adds).</summary>
        public System.Collections.Generic.Dictionary<string, string> Raw;

        public string GetRaw(string column) =>
            Raw != null && Raw.TryGetValue(column, out string v) ? v : null;

        /// <summary>
        /// A trait_* column as a number, or NaN if it is absent or categorical.
        ///
        /// TryFloat rather than Float on purpose. Not every exported trait is
        /// continuous — eye_color, handedness and chronotype are strings — and
        /// the throwing parser turned "this trait is a category" into a
        /// BundleFormatException, i.e. a whole-panel failure triggered by
        /// asking an ordinary question about an ordinary villager.
        /// </summary>
        public double GetTrait(string trait) =>
            CsvParse.TryDouble(GetRaw("trait_" + trait), out double v)
                ? v : double.NaN;
    }
}
