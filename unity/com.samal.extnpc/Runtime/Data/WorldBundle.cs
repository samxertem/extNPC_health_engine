using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEngine;

namespace ExtNPC.Data
{
    /// <summary>
    /// A world exported by <c>simulation.export.export_world_dir()</c>.
    ///
    /// Read-only, in every sense that matters. The viewer never writes into a
    /// bundle and never derives a biological quantity from one: if a number
    /// reaches the screen, there is a cell it came from. Anything the engine
    /// did not export is not available, and the correct response to that is to
    /// export it from the engine -- not to compute it here.
    /// </summary>
    public sealed class WorldBundle
    {
        public Manifest Manifest { get; private set; }

        /// <summary>Every individual who has ever lived, by name. Includes the
        /// dead on purpose: excluding them conditions any reading on survival.</summary>
        public Dictionary<string, PersonRow> People { get; private set; }

        /// <summary>Living villagers per retained tick, indexed by tick.</summary>
        public Dictionary<int, FrameRow[]> Frames { get; private set; }

        public Dictionary<int, DemeRow[]> Demes { get; private set; }
        public Dictionary<int, FlowRow[]> Flows { get; private set; }
        public List<EventRow> Events { get; private set; }
        public List<HistoryRow> History { get; private set; }

        /// <summary>Retained ticks, ascending. NOT necessarily starting at 0 --
        /// see <see cref="Manifest.FramesInfo.Truncated"/>.</summary>
        public int[] Ticks { get; private set; }

        public int FirstTick => Ticks.Length > 0 ? Ticks[0] : 0;
        public int LastTick => Ticks.Length > 0 ? Ticks[Ticks.Length - 1] : 0;

        private WorldBundle() { }

        /// <summary>
        /// Load from a directory (typically
        /// <c>Application.streamingAssetsPath/extnpc/&lt;world&gt;</c>).
        /// </summary>
        public static WorldBundle Load(string directory)
        {
            if (!Directory.Exists(directory))
                throw new BundleFormatException($"no bundle directory: {directory}");

            var b = new WorldBundle();

            string manifestPath = Path.Combine(directory, "manifest.json");
            if (!File.Exists(manifestPath))
                throw new BundleFormatException(
                    $"{directory} has no manifest.json -- refusing to guess at " +
                    $"a directory that may not be a world bundle.");

            b.Manifest = Manifest.Parse(File.ReadAllText(manifestPath));
            b.Manifest.RequireSupportedSchema();

            var pool = new CsvParse.StringPool();
            b.People = LoadPeople(Path.Combine(directory, "people.csv"));
            b.History = LoadHistory(Path.Combine(directory, "history.csv"));
            b.Frames = LoadFrames(Path.Combine(directory, "frames.csv"), pool);
            b.Demes = LoadDemes(Path.Combine(directory, "demes.csv"), pool);
            b.Flows = LoadFlows(Path.Combine(directory, "flows.csv"));
            b.Events = LoadEvents(Path.Combine(directory, "events.csv"));

            var ticks = new List<int>(b.Frames.Keys);
            ticks.Sort();
            b.Ticks = ticks.ToArray();
            return b;
        }

        /// <summary>The frame at <paramref name="tick"/>, or the nearest
        /// earlier one still retained -- matching the engine's own
        /// SnapshotBuffer.at() behaviour, so the viewer and the dashboard
        /// resolve a scrub position identically.</summary>
        public FrameRow[] FrameAt(int tick)
        {
            if (Frames.TryGetValue(tick, out var exact)) return exact;
            int best = -1;
            foreach (int t in Ticks)
            {
                if (t <= tick) best = t; else break;
            }
            return best >= 0 ? Frames[best] : Array.Empty<FrameRow>();
        }

        // ------------------------------------------------------------------
        // loaders
        // ------------------------------------------------------------------

        private static Dictionary<int, FrameRow[]> LoadFrames(
            string path, CsvParse.StringPool pool)
        {
            var byTick = new Dictionary<int, List<FrameRow>>();
            if (!File.Exists(path)) return Empty(byTick);

            using (var r = CsvReader.FromFile(path))
            {
                if (r.IsEmpty) return Empty(byTick);

                // Indices resolved once. Looking a column up by name inside the
                // row loop would be a dictionary hit per field per row -- ~7.5M
                // of them on a large world.
                int iTick = r.RequireIndex("tick");
                int iName = r.RequireIndex("name");
                int iX = r.RequireIndex("x"), iY = r.RequireIndex("y");
                int iColor = r.RequireIndex("color");
                int iSex = r.RequireIndex("sex");
                int iAge = r.RequireIndex("age");
                int iDeme = r.RequireIndex("deme");
                int iLin = r.RequireIndex("lineage");
                int iPur = r.RequireIndex("purity");
                int iGen = r.RequireIndex("generation");
                int iKids = r.RequireIndex("children");
                int iStress = r.RequireIndex("stress");
                int iEpi = r.RequireIndex("epi_accel");
                int iAero = r.RequireIndex("aerobic");
                int iCond = r.RequireIndex("conditions");
                int iF = r.RequireIndex("pedigree_f");
                int iViab = r.RequireIndex("viability");
                int iCnv = r.RequireIndex("cnv");
                int iH = r.RequireIndex("height");
                int iStage = r.RequireIndex("life_stage");

                var grey = new Color32(136, 136, 136, 255);
                while (r.ReadRow())
                {
                    var f = r.Current;
                    int tick = CsvParse.Int(f[iTick]);
                    var row = new FrameRow
                    {
                        Tick = tick,
                        Name = pool.Get(f[iName]),
                        X = CsvParse.Float(f[iX]),
                        Y = CsvParse.Float(f[iY]),
                        Color = CsvParse.Color(f[iColor], grey),
                        IsFemale = f[iSex] == "female",
                        Age = CsvParse.Int(f[iAge]),
                        Deme = CsvParse.Int(f[iDeme]),
                        Lineage = pool.Get(f[iLin]),
                        Purity = CsvParse.Float(f[iPur]),
                        Generation = CsvParse.Int(f[iGen]),
                        Children = CsvParse.Int(f[iKids]),
                        Stress = CsvParse.Float(f[iStress]),
                        EpiAccel = CsvParse.Float(f[iEpi]),
                        Aerobic = CsvParse.Float(f[iAero]),
                        Conditions = CsvParse.Int(f[iCond]),
                        PedigreeF = CsvParse.Float(f[iF]),
                        Viability = CsvParse.Float(f[iViab]),
                        Cnv = CsvParse.Int(f[iCnv]),
                        HeightCm = CsvParse.Float(f[iH]),
                        LifeStage = pool.Get(f[iStage]),
                    };
                    if (!byTick.TryGetValue(tick, out var list))
                        byTick[tick] = list = new List<FrameRow>();
                    list.Add(row);
                }
            }
            return Empty(byTick);
        }

        private static Dictionary<int, FrameRow[]> Empty(
            Dictionary<int, List<FrameRow>> src)
        {
            var outp = new Dictionary<int, FrameRow[]>(src.Count);
            foreach (var kv in src) outp[kv.Key] = kv.Value.ToArray();
            return outp;
        }

        private static Dictionary<int, DemeRow[]> LoadDemes(
            string path, CsvParse.StringPool pool)
        {
            var byTick = new Dictionary<int, List<DemeRow>>();
            if (File.Exists(path))
            {
                using (var r = CsvReader.FromFile(path))
                {
                    if (!r.IsEmpty)
                    {
                        int iTick = r.RequireIndex("tick"), iDeme = r.RequireIndex("deme");
                        int iX = r.RequireIndex("x"), iY = r.RequireIndex("y");
                        int iR = r.RequireIndex("r"), iN = r.RequireIndex("n");
                        int iMean = r.RequireIndex("mean_stress");
                        int iMax = r.RequireIndex("max_stress");
                        int iDom = r.RequireIndex("dominant");
                        int iShare = r.RequireIndex("dominance");
                        int iCol = r.RequireIndex("dominant_color");
                        var grey = new Color32(136, 136, 136, 255);

                        while (r.ReadRow())
                        {
                            var f = r.Current;
                            int tick = CsvParse.Int(f[iTick]);
                            var row = new DemeRow
                            {
                                Tick = tick,
                                Deme = CsvParse.Int(f[iDeme]),
                                X = CsvParse.Float(f[iX]),
                                Y = CsvParse.Float(f[iY]),
                                Radius = CsvParse.Float(f[iR]),
                                Count = CsvParse.Int(f[iN]),
                                MeanStress = CsvParse.Float(f[iMean]),
                                MaxStress = CsvParse.Float(f[iMax]),
                                Dominant = pool.Get(f[iDom]),
                                Dominance = CsvParse.Float(f[iShare]),
                                DominantColor = CsvParse.Color(f[iCol], grey),
                            };
                            if (!byTick.TryGetValue(tick, out var list))
                                byTick[tick] = list = new List<DemeRow>();
                            list.Add(row);
                        }
                    }
                }
            }
            var outp = new Dictionary<int, DemeRow[]>(byTick.Count);
            foreach (var kv in byTick) outp[kv.Key] = kv.Value.ToArray();
            return outp;
        }

        private static Dictionary<int, FlowRow[]> LoadFlows(string path)
        {
            var byTick = new Dictionary<int, List<FlowRow>>();
            if (File.Exists(path))
            {
                using (var r = CsvReader.FromFile(path))
                {
                    // A header with no rows is the normal single-deme case:
                    // with one settlement there is nowhere to migrate. That is
                    // a correct empty, not a missing file.
                    if (!r.IsEmpty)
                    {
                        int iTick = r.RequireIndex("tick");
                        int iX0 = r.RequireIndex("x0"), iY0 = r.RequireIndex("y0");
                        int iX1 = r.RequireIndex("x1"), iY1 = r.RequireIndex("y1");
                        int iW = r.RequireIndex("w");
                        while (r.ReadRow())
                        {
                            var f = r.Current;
                            int tick = CsvParse.Int(f[iTick]);
                            var row = new FlowRow
                            {
                                Tick = tick,
                                X0 = CsvParse.Float(f[iX0]), Y0 = CsvParse.Float(f[iY0]),
                                X1 = CsvParse.Float(f[iX1]), Y1 = CsvParse.Float(f[iY1]),
                                Weight = CsvParse.Float(f[iW]),
                            };
                            if (!byTick.TryGetValue(tick, out var list))
                                byTick[tick] = list = new List<FlowRow>();
                            list.Add(row);
                        }
                    }
                }
            }
            var outp = new Dictionary<int, FlowRow[]>(byTick.Count);
            foreach (var kv in byTick) outp[kv.Key] = kv.Value.ToArray();
            return outp;
        }

        private static List<EventRow> LoadEvents(string path)
        {
            var rows = new List<EventRow>();
            if (!File.Exists(path)) return rows;
            using (var r = CsvReader.FromFile(path))
            {
                if (r.IsEmpty) return rows;
                int iTick = r.RequireIndex("tick");
                int iKind = r.RequireIndex("kind");
                int iLabel = r.RequireIndex("label");
                while (r.ReadRow())
                {
                    var f = r.Current;
                    rows.Add(new EventRow
                    {
                        Tick = CsvParse.Int(f[iTick]),
                        Kind = f[iKind],
                        Label = f[iLabel],
                    });
                }
            }
            return rows;
        }

        private static List<HistoryRow> LoadHistory(string path)
        {
            var rows = new List<HistoryRow>();
            if (!File.Exists(path)) return rows;
            using (var r = CsvReader.FromFile(path))
            {
                if (r.IsEmpty) return rows;
                int iTick = r.RequireIndex("tick");
                string[] cols = r.Columns;
                while (r.ReadRow())
                {
                    var f = r.Current;
                    var row = new HistoryRow { Tick = CsvParse.Int(f[iTick]) };
                    for (int i = 0; i < cols.Length && i < f.Count; i++)
                    {
                        if (i == iTick || CsvParse.IsBlank(f[i])) continue;
                        // history.csv is all-numeric by construction; a column
                        // that is not is skipped rather than crashing the load.
                        if (float.TryParse(f[i], NumberStyles.Float,
                                CultureInfo.InvariantCulture, out float v))
                        {
                            row.Values[cols[i]] = v;
                        }
                    }
                    rows.Add(row);
                }
            }
            return rows;
        }

        private static Dictionary<string, PersonRow> LoadPeople(string path)
        {
            var people = new Dictionary<string, PersonRow>(StringComparer.Ordinal);
            if (!File.Exists(path)) return people;

            using (var r = CsvReader.FromFile(path))
            {
                if (r.IsEmpty) return people;
                string[] cols = r.Columns;
                int iName = r.RequireIndex("name");

                while (r.ReadRow())
                {
                    var f = r.Current;
                    var raw = new Dictionary<string, string>(cols.Length,
                        StringComparer.Ordinal);
                    for (int i = 0; i < cols.Length && i < f.Count; i++)
                        raw[cols[i]] = f[i];

                    string G(string c) => raw.TryGetValue(c, out string v) ? v : "";

                    var p = new PersonRow
                    {
                        Name = f[iName],
                        GivenName = G("given_name"),
                        IsFemale = G("sex") == "female",
                        Age = CsvParse.Int(G("age")),
                        Alive = CsvParse.Bool(G("alive")),
                        Generation = CsvParse.Int(G("generation")),
                        LifeStage = G("life_stage"),
                        Mother = G("mother"),
                        Father = G("father"),
                        Deme = CsvParse.Int(G("deme")),
                        DemeLabel = G("deme_label"),
                        PedigreeF = CsvParse.Float(G("pedigree_f")),
                        RealisedF = CsvParse.Float(G("realised_f")),
                        RelativeViability = CsvParse.Float(G("relative_viability")),
                        MendelianDiagnoses = CsvParse.List(G("mendelian_diagnoses")),
                        MendelianCarrierOf = CsvParse.List(G("mendelian_carrier_of")),
                        MedicalConditions = CsvParse.List(G("medical_conditions")),
                        Raw = raw,
                    };
                    people[p.Name] = p;
                }
            }
            return people;
        }

        /// <summary>One line for the console. Says the catalogue and the commit
        /// because a scene that cannot name the engine build that produced its
        /// world is not a scientific instrument.
        ///
        /// Formatted with InvariantCulture for the same reason the parsing is.
        /// The first run of this method on a comma-decimal machine printed
        /// "4.111 rows", which reads as four-point-one-one-one. Diagnostics
        /// that change shape with the operator's locale are diagnostics people
        /// misread and then quote at each other.</summary>
        public string Describe()
        {
            int living = 0;
            foreach (var p in People.Values) if (p.Alive) living++;

            int frameRows = 0;
            foreach (var kv in Frames) frameRows += kv.Value.Length;

            string truncated = Manifest.Frames.Truncated
                ? $" (TRUNCATED: earliest retained year is {FirstTick}, not 0)"
                : "";

            var inv = CultureInfo.InvariantCulture;
            return string.Format(inv,
                "loaded {0:N0} people ({1:N0} living) · {2:N0} years · " +
                "{3:N0} frames / {4:N0} rows{5} · {6}",
                People.Count, living, History.Count, Ticks.Length,
                frameRows, truncated, Manifest);
        }
    }
}
