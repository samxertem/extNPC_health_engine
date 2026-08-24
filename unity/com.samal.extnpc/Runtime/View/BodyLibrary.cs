using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// Per-villager bodies: the Stage 8 upgrade to <see cref="HumanMesh"/>.
    ///
    /// Stage 6 gave the village ONE shared human mesh, scaled per person by
    /// stature. That is genuinely all Stage 6 asked for, and it is also the
    /// reason a screenshot of it cannot answer the question Stage 8 exists to
    /// ask: everyone being the same body at different sizes is a recolour of
    /// one person by construction, so no amount of looking at it tells you
    /// whether the genetics produces visible variation.
    ///
    /// This class resolves a villager NAME to the body baked from that
    /// villager's own genome. The engine writes one `.mhm` per person
    /// (`export_bodies.py`), Blender bakes one FBX per `.mhm`
    /// (`mpfb/bake_bodies.py`), and the result is dropped into
    /// <c>Assets/Resources/extnpc/bodies/</c>. Absence is a supported state at
    /// every level: no bodies folder gives Stage 6's shared mesh, and no
    /// shared mesh gives Stage 3's capsules.
    ///
    /// WHY THE NAME-TO-FILE MAP IS READ RATHER THAN RECOMPUTED. The Python
    /// side sanitises a villager name into a filename stem. Reimplementing
    /// that sanitisation here would create a second definition of the same
    /// rule, which is the defect invariant 6 exists to prevent and which the
    /// package already avoids for lineage colour. So `bodies.json` carries the
    /// name-to-stem mapping and C# only ever looks it up. The day the Python
    /// rule changes, nothing here needs to know.
    ///
    /// WHAT IS STILL SHARED, and it matters for reading the picture. Every
    /// baked body comes off the same fixed-topology base mesh, so the vertex
    /// count is identical for all of them; only the positions differ. The
    /// morphs that vary are sex, age and body mass. Stature deliberately does
    /// NOT vary in the mesh, because <see cref="HumanMesh.Bake"/> normalises
    /// every body to 1 m and <see cref="VillagerView"/> scales by
    /// <c>height_cm/100</c>. Anyone reading variation off a screenshot should
    /// know that stature arrives by the scale and everything else by the mesh.
    /// </summary>
    public static class BodyLibrary
    {
        /// <summary>Where a consuming project drops the per-villager FBX files.</summary>
        public const string ResourceFolder = "extnpc/bodies";

        /// <summary>The manifest filename, inside the bundle's `bodies/` folder.</summary>
        public const string ManifestName = "bodies.json";

        private static readonly Dictionary<string, string> _stems =
            new Dictionary<string, string>();

        /// <summary>
        /// Stem to the baked BODY's height in metres, as Blender measured it.
        ///
        /// Read rather than recomputed, for the reason the name-to-stem map
        /// above is read rather than recomputed. Once an FBX carries hair or
        /// clothes, its combined mesh is taller than the person, and a
        /// villager who measured themselves would shrink by the height of a
        /// hairstyle that <c>cosmetic.py</c> picked from their NAME. Blender
        /// measures the basemesh alone during the bake; this is that number
        /// arriving intact. Missing entries mean an older bundle and fall back
        /// to measuring, which is exactly right for a body with no assets on
        /// it.
        /// </summary>
        private static readonly Dictionary<string, float> _statures =
            new Dictionary<string, float>();
        private static readonly Dictionary<string, Mesh> _cache =
            new Dictionary<string, Mesh>();

        /// <summary>Stems looked up and found absent, so the miss costs one
        /// dictionary probe rather than a Resources.Load per villager per
        /// frame. A negative result is cached as deliberately as a positive
        /// one; the village re-renders every tick.</summary>
        private static readonly HashSet<string> _absent = new HashSet<string>();

        /// <summary>Villagers named by the manifest, whether or not their FBX
        /// is installed.</summary>
        public static int Declared { get { return _stems.Count; } }

        /// <summary>How many distinct bodies have actually been loaded so far.
        /// Grows as villagers come on screen, so read it after a frame, not
        /// before.</summary>
        public static int Loaded { get { return _cache.Count; } }

        /// <summary>Empty when the body set matches the world it is drawn
        /// over, otherwise a human-readable description of the mismatch.
        /// See <see cref="CheckProvenance"/>.</summary>
        public static string ProvenanceWarning { get; private set; }

        /// <summary>
        /// Forget the manifest and every cached mesh.
        ///
        /// Same reason <see cref="HumanMesh.Forget"/> exists: the negative
        /// cache above means newly imported bodies would otherwise not appear
        /// until the next domain reload, which looks exactly like the bake
        /// having failed.
        /// </summary>
        public static void Forget()
        {
            _stems.Clear();
            _statures.Clear();
            _cache.Clear();
            _absent.Clear();
            ProvenanceWarning = null;
        }

        /// <summary>
        /// Read `bodies.json`. Safe to call with null or malformed text: the
        /// village falls back to the shared body rather than failing to draw.
        /// </summary>
        public static void LoadManifest(string json)
        {
            Forget();
            if (string.IsNullOrEmpty(json)) return;

            JObject root;
            try { root = JObject.Parse(json); }
            catch (System.Exception e)
            {
                Debug.LogWarning("[extNPC] bodies.json is not readable, falling back " +
                                 "to the shared body: " + e.Message);
                return;
            }

            var bodies = root["bodies"] as JArray;
            if (bodies == null) return;

            foreach (var entry in bodies)
            {
                string name = (string)entry["name"];
                string stem = (string)entry["stem"];
                if (string.IsNullOrEmpty(name) || string.IsNullOrEmpty(stem))
                    continue;
                _stems[name] = stem;

                // Absent in a bundle baked before the key existed, and absent
                // is a supported state rather than an error: those bodies wear
                // nothing, so measuring them gives the same answer.
                var stature = entry["body_stature_m"];
                if (stature != null)
                {
                    float metres = (float)stature;
                    if (metres > 0f) _statures[stem] = metres;
                }
            }

            // A DRESSED bundle whose bodies carry no recorded stature is a
            // specific, recoverable mistake with a silent symptom, so it gets
            // named. `export_bodies.py` rewrites bodies.json from scratch and
            // does not know the statures; only `bake_bodies.py` does. Run the
            // exporter after the bake and the keys are gone, Bake falls back to
            // measuring the whole mesh, and every villager loses their hair's
            // height again with nothing in the log.
            var channels = root["appearance_channels"];
            bool dressed = channels != null && (bool?)channels["dressed"] == true;
            if (dressed && _statures.Count < _stems.Count)
            {
                Debug.LogWarning(
                    "[extNPC] bodies.json says these bodies are dressed but " +
                    (_stems.Count - _statures.Count) + " of " + _stems.Count +
                    " carry no body_stature_m, so they will be normalised by " +
                    "their own hair and shoes and come out short. This is what " +
                    "running export_bodies.py after bake_bodies.py looks like: " +
                    "re-run the bake to stamp the statures back in.");
            }

            _manifestSeed = (int?)root["seed"] ?? -1;
            _manifestCommit = (string)root["git_commit"] ?? "";
            _manifestEthnicity = (string)root["ethnicity_preset"] ?? "";
        }

        private static int _manifestSeed = -1;
        private static string _manifestCommit = "";
        private static string _manifestEthnicity = "";

        /// <summary>The fixed ethnicity macro these bodies were baked with
        /// (item U5). Surfaced rather than hidden: it is worth about 18 mm of
        /// stature and is not derived from any villager's genome, so a picture
        /// of these bodies is a picture taken under this setting.</summary>
        public static string EthnicityPreset { get { return _manifestEthnicity; } }

        /// <summary>
        /// Compare the body set's provenance against the world being drawn.
        ///
        /// This WARNS rather than refuses, and the choice is deliberate. A
        /// mismatch usually means the bodies were baked from a different run
        /// of the same world, which produces a village of the right people
        /// with subtly wrong bodies -- the exact failure that is invisible in
        /// a screenshot. Refusing to draw would hide it behind an empty scene;
        /// drawing with a loud warning puts it where someone will read it.
        /// </summary>
        public static void CheckProvenance(int worldSeed, string worldCommit)
        {
            if (_stems.Count == 0) { ProvenanceWarning = null; return; }

            var problems = new List<string>();
            if (_manifestSeed >= 0 && _manifestSeed != worldSeed)
                problems.Add(string.Format("seed {0} vs the world's {1}",
                                           _manifestSeed, worldSeed));
            if (!string.IsNullOrEmpty(_manifestCommit) &&
                !string.IsNullOrEmpty(worldCommit) &&
                _manifestCommit != worldCommit)
                problems.Add(string.Format("commit {0} vs the world's {1}",
                                           _manifestCommit, worldCommit));

            ProvenanceWarning = problems.Count == 0
                ? null
                : "bodies.json was baked from " + string.Join(", ", problems.ToArray());

            if (ProvenanceWarning != null)
                Debug.LogWarning("[extNPC] " + ProvenanceWarning +
                                 ". The village will draw, but these bodies belong " +
                                 "to a different run.");
        }

        /// <summary>
        /// This villager's own body, or the shared one for their sex, or null.
        ///
        /// Returns a UNIT body -- 1 m tall with soles on the origin -- in every
        /// case, so the caller's scaling is identical whichever tier answered.
        /// </summary>
        public static Mesh UnitBodyFor(string villagerName, bool female)
        {
            string stem;
            if (villagerName == null || !_stems.TryGetValue(villagerName, out stem))
                return HumanMesh.UnitBody(female);

            Mesh cached;
            if (_cache.TryGetValue(stem, out cached)) return cached;
            if (_absent.Contains(stem)) return HumanMesh.UnitBody(female);

            var model = Resources.Load<GameObject>(ResourceFolder + "/" + stem);
            if (model == null)
            {
                _absent.Add(stem);
                return HumanMesh.UnitBody(female);
            }

            float known;
            if (!_statures.TryGetValue(stem, out known)) known = 0f;

            float authored;
            Mesh baked = HumanMesh.Bake(model, known, out authored);
            if (baked == null)
            {
                // Bake returns null for a non-readable mesh, which is an import
                // setting rather than a missing file. HumanMesh already logs
                // the specific fix, so this only records that the fallback
                // happened and does not retry every frame.
                _absent.Add(stem);
                return HumanMesh.UnitBody(female);
            }

            baked.name = "extnpc_body_" + stem;
            _cache[stem] = baked;
            return baked;
        }
    }
}
