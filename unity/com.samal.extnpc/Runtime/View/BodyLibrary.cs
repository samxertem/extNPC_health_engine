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
    /// PER LIFE STAGE, since item U6. A bundle may carry several bodies for
    /// one person, keyed <c>Name@stage</c> (<c>Ada-16@child</c>), baked from
    /// the phenotype that person expressed at the middle of that stage. The
    /// engine bakes only the stages a frame actually recorded, so a founder
    /// who arrives aged 29 has no childhood body and needs none: the timeline
    /// cannot be scrubbed back to a year the run does not contain.
    ///
    /// Lookup falls back in a fixed order, and the order is the whole
    /// compatibility story: <c>Name@stage</c>, then <c>Name</c>, then the
    /// shared mesh for the sex. So a STAGED bundle read by this code gives
    /// per-stage bodies, a LEGACY bundle gives the one body per person it
    /// always gave, and neither needs to know which it is.
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

        /// <summary>Villager name to the stem of their MOST MATURE baked body,
        /// chosen by the `age` the manifest already records.
        ///
        /// This is what a caller with no life stage gets, and choosing it by
        /// age rather than by a stage name matters twice. It reproduces the
        /// pre-U6 semantic exactly -- `select_everyone` baked one body at the
        /// person's age now, or at death, which is their maximum -- and it
        /// needs no list of stage names in C#. The stage BOUNDARIES are solved
        /// from the fitted growth curve and differ by sex; a copy of even
        /// their ORDER here would be a second definition to keep in step.
        ///
        /// Without this a staged bundle would resolve nothing for any caller
        /// that has no stage to offer, and every such villager would silently
        /// fall back to the shared mesh. `mpfb/unity_lineup.py` is exactly
        /// that caller, and its whole verdict is "did anyone fall back".</summary>
        /// <summary>Stem to `channel -> colour`, from the manifest's `colors`.
        ///
        /// PER BODY, not per person, and the difference is real: the phenotype
        /// is read at the body's own age and `skin_tone` carries a nonzero
        /// v_gxe for UV exposure, so a villager's skin need not be the same
        /// colour at 5 as at 50.</summary>
        private static readonly Dictionary<string, Dictionary<string, Color>> _colors =
            new Dictionary<string, Dictionary<string, Color>>();

        /// <summary>Stem to `source mesh name -> channel`, from the manifest's
        /// `submeshes`, which the BAKE wrote because only it holds the real
        /// Blender objects and the manifest at the same moment. Never derived
        /// from a name here: hairstyles, suits and shoes are all just strings
        /// from whatever pack is installed.</summary>
        private static readonly Dictionary<string, Dictionary<string, string>> _channels =
            new Dictionary<string, Dictionary<string, string>>();

        /// <summary>Per-submesh colours, cached beside the baked mesh so a
        /// villager re-rendered every tick costs one dictionary probe.</summary>
        private static readonly Dictionary<string, Color[]> _submeshColors =
            new Dictionary<string, Color[]>();

        /// <summary>Which submesh index is the EYES channel, or -1. Cached
        /// alongside `_submeshColors` for the same reason, and kept separate
        /// from it because a submesh index is a rendering decision (which
        /// material slot gets the eye shader), not a colour.</summary>
        private static readonly Dictionary<string, int> _eyeIndex =
            new Dictionary<string, int>();

        /// <summary>Stem to the engine's categorical `eye_color` label, from
        /// the manifest's `pigmentation`. Read straight through, never
        /// derived: the label is a calibrated model output.</summary>
        private static readonly Dictionary<string, string> _eyeLabel =
            new Dictionary<string, string>();

        /// <summary>Per-submesh CHANNEL, parallel to `_submeshColors`.
        ///
        /// The colours alone are no longer enough to draw a villager:
        /// <see cref="BodyMaterials"/> needs to know that submesh 3 is hair
        /// in order to give it hair's surface rather than skin's. That is the
        /// same resolution <see cref="ResolveColors"/> already performs and
        /// used to discard, so it is kept rather than recomputed.</summary>
        private static readonly Dictionary<string, string[]> _submeshChannels =
            new Dictionary<string, string[]>();

        /// <summary>Per-submesh SOURCE MESH NAME, parallel to
        /// `_submeshChannels`: `eyebrow001`, `eyelashes02`, `afro01`.
        ///
        /// The channel says what a part IS; this says which asset it is, and
        /// eyebrows need both. Their shape lives in that specific asset's
        /// alpha channel, so `eyebrow001` and `eyebrow007` are not
        /// interchangeable the way two things that are both "eyebrows" would
        /// be. See <see cref="HairCardMaterials"/>.</summary>
        private static readonly Dictionary<string, string[]> _submeshAssets =
            new Dictionary<string, string[]>();

        /// <summary>Stem to the age and sex of THAT BODY, for
        /// <see cref="SkinMaterials"/>, which picks a detail map per age band
        /// and sex.
        ///
        /// Per body rather than per person, for the same reason `_colors` is:
        /// a staged bundle carries one entry per life stage, and a villager's
        /// skin at 5 is not the map that belongs on them at 70.</summary>
        private static readonly Dictionary<string, float> _bodyAge =
            new Dictionary<string, float>();
        private static readonly Dictionary<string, bool> _bodyFemale =
            new Dictionary<string, bool>();

        private static readonly Dictionary<string, string> _mature =
            new Dictionary<string, string>();
        private static readonly Dictionary<string, float> _matureAge =
            new Dictionary<string, float>();

        /// <summary>Stems looked up and found absent, so the miss costs one
        /// dictionary probe rather than a Resources.Load per villager per
        /// frame. A negative result is cached as deliberately as a positive
        /// one; the village re-renders every tick.</summary>
        private static readonly HashSet<string> _absent = new HashSet<string>();

        /// <summary>Villagers the manifest says were NEVER RENDERABLE, with
        /// the reason. On the measured village these are stillbirths from
        /// inbreeding depression: born and dead inside one tick, so they are
        /// in no frame and no body was baked.
        ///
        /// Held separately from a plain miss because the two need opposite
        /// treatment. A miss means the bundle is incomplete and the shared
        /// body is the best guess available. This means the person had no
        /// rendered form at all, and falling back to the shared ADULT mesh
        /// would draw a stillborn infant as a grown adult, which is item U6's
        /// defect arrived at from the other side.</summary>
        private static readonly Dictionary<string, string> _neverRendered =
            new Dictionary<string, string>();

        /// <summary>Why this villager was never rendered, or null if they
        /// were. Callers that show a portrait should show nothing and say
        /// this, rather than show a body that was never alive to have one.</summary>
        public static string NeverRenderedReason(string villagerName)
        {
            string why;
            if (villagerName != null &&
                _neverRendered.TryGetValue(villagerName, out why)) return why;
            return null;
        }

        /// <summary>True when this bundle carries per-life-stage bodies.</summary>
        public static bool Staged { get; private set; }

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
            _neverRendered.Clear();
            _mature.Clear();
            _matureAge.Clear();
            _colors.Clear();
            _channels.Clear();
            _submeshColors.Clear();
            _submeshChannels.Clear();
            _submeshAssets.Clear();
            _bodyAge.Clear();
            _bodyFemale.Clear();
            _eyeIndex.Clear();
            _eyeLabel.Clear();
            Staged = false;
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

                // `key` is `Name@stage` in a staged bundle and `Name` in every
                // older one. Falling back to `name` rather than skipping is
                // what lets schema 1 bundles keep working unchanged.
                string key = (string)entry["key"];
                if (string.IsNullOrEmpty(key)) key = name;
                _stems[key] = stem;

                // Ties and a missing age both resolve to "the first one seen",
                // which is stable because the exporter writes sorted entries.
                var colors = entry["colors"] as JObject;
                if (colors != null)
                {
                    var byChannel = new Dictionary<string, Color>();
                    foreach (var prop in colors.Properties())
                    {
                        // `colors` also carries the numbers that JUSTIFY the
                        // skin colour (its L*a*b* point, its ITA and class)
                        // and a provenance block. Only the hex strings are
                        // colours; everything else is evidence for a reader
                        // and is skipped rather than guessed at.
                        string hex = prop.Value.Type == JTokenType.String
                            ? (string)prop.Value : null;
                        Color c;
                        if (!string.IsNullOrEmpty(hex) && hex[0] == '#' &&
                            ColorUtility.TryParseHtmlString(hex, out c))
                            byChannel[prop.Name] = c;
                    }
                    if (byChannel.Count > 0) _colors[stem] = byChannel;
                }

                var subs = entry["submeshes"] as JObject;
                if (subs != null)
                {
                    var map = new Dictionary<string, string>();
                    foreach (var prop in subs.Properties())
                        map[prop.Name.ToLowerInvariant()] = (string)prop.Value;
                    if (map.Count > 0) _channels[stem] = map;
                }

                // The eye colour's LABEL, not its hex. Every other channel is
                // a colour because every other part is drawn as a flat tone;
                // the eyes are drawn from a real texture chosen by category
                // (see EyeTextures), so what this needs is the engine's own
                // categorical `eye_color` -- the HERC2 dominance outcome --
                // rather than the swatch that stood in for it.
                var pigmentation = entry["pigmentation"] as JObject;
                if (pigmentation != null)
                {
                    string label = (string)pigmentation["eye_color"];
                    if (!string.IsNullOrEmpty(label))
                        _eyeLabel[stem] = label.ToLowerInvariant();
                }

                float age = (float?)entry["age"] ?? 0f;

                // This BODY's own age and sex, for the skin detail map.
                // `sex` is the manifest's own word ("female"/"male"); a
                // missing or unrecognised one resolves to male, which is
                // SkinMaterials' behaviour for a missing map too, and is a
                // slightly wrong body rather than an absent one.
                _bodyAge[stem] = age;
                string sex = (string)entry["sex"];
                _bodyFemale[stem] = !string.IsNullOrEmpty(sex) &&
                    sex.ToLowerInvariant() == "female";

                float best;
                if (!_matureAge.TryGetValue(name, out best) || age > best)
                {
                    _matureAge[name] = age;
                    _mature[name] = stem;
                }

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

            Staged = (bool?)root["staged"] ?? false;

            var unrendered = root["never_rendered"] as JArray;
            if (unrendered != null)
            {
                foreach (var u in unrendered)
                {
                    string who = (string)u["name"];
                    if (string.IsNullOrEmpty(who)) continue;
                    string why = (string)u["reason"];
                    string cause = (string)u["death_cause"];
                    if (!string.IsNullOrEmpty(cause))
                        why = (why ?? "no body") + " (" + cause + ")";
                    _neverRendered[who] = why ?? "no body was baked";
                }
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

        /// <summary>The key a body is stored under: <c>Name@stage</c> when a
        /// stage is known, otherwise the bare name.
        ///
        /// This mirrors `BodyTarget.key` on the Python side, and it is the one
        /// piece of that side's naming this class does reproduce. It is a
        /// two-character join rather than a sanitisation rule: the stem, which
        /// IS a sanitisation, is still only ever read from the manifest.</summary>
        public static string KeyFor(string villagerName, string lifeStage)
        {
            if (string.IsNullOrEmpty(lifeStage)) return villagerName;
            return villagerName + "@" + lifeStage;
        }

        /// <summary>
        /// Which baked body answers for this villager at this stage, or null
        /// if none does. The resolution step of <see cref="UnitBodyFor"/>,
        /// separated out because it is the part with logic in it.
        ///
        /// FALLS BACK IN A FIXED ORDER: the staged body <c>Name@stage</c>,
        /// then the person's single body <c>Name</c>, then their most mature
        /// baked body, then null.
        ///
        /// The second step keeps every pre-U6 bundle working: the renderer
        /// now always passes a stage, so without it a schema 1 bundle would
        /// resolve nothing and the whole village would silently drop to the
        /// shared mesh. The third covers a stage that was never baked (a
        /// founder has no childhood in this run) and every caller that has no
        /// stage to offer at all.
        ///
        /// Public so an EditMode test can assert on it. Resolving a stem to a
        /// Mesh needs `Resources.Load` and an imported FBX, which a test has
        /// neither of, and a lookup that picked the wrong stem would still
        /// render a body and pass every count-based assertion.
        /// </summary>
        public static string StemFor(string villagerName, string lifeStage)
        {
            if (string.IsNullOrEmpty(villagerName)) return null;

            string stem;
            if (_stems.TryGetValue(KeyFor(villagerName, lifeStage), out stem))
                return stem;
            if (_stems.TryGetValue(villagerName, out stem))
                return stem;
            // Their most mature body. Reached when a staged bundle is asked
            // for a stage it did not bake -- a founder has no childhood in
            // the run -- and whenever the caller has no stage at all. Their
            // own body at the wrong age is a far better picture than the
            // shared mesh, which is nobody's body.
            if (_mature.TryGetValue(villagerName, out stem))
                return stem;
            return null;
        }

        /// <summary>
        /// The colour of every submesh of this villager's baked body, in
        /// submesh order, or null when the bundle carries no colours.
        ///
        /// Null rather than an array of white: a caller that gets colours
        /// paints them, and a caller that gets null must keep whatever the
        /// material already says. Handing back white would silently repaint
        /// every villager on a pre-colour bundle.
        /// </summary>
        public static Color[] SubmeshColorsFor(string villagerName,
                                               string lifeStage)
        {
            string stem = StemFor(villagerName, lifeStage);
            if (stem == null) return null;
            Color[] colors;
            return _submeshColors.TryGetValue(stem, out colors) ? colors : null;
        }

        /// <summary>
        /// Match each submesh to its channel, then to its colour.
        ///
        /// Submesh i came from source renderer i (see <see cref="HumanMesh"/>),
        /// so this is an index-free lookup by NAME and does not depend on the
        /// order Unity happened to walk the hierarchy in. The name Unity gives
        /// a child of an imported FBX is prefixed with the root's name
        /// (`Ada-16_adult.afro01_body`), so the prefix is stripped before the
        /// manifest is asked.
        ///
        /// AN UNKNOWN CHANNEL FALLS BACK TO SKIN rather than to white. The
        /// parts with no colour of their own -- teeth and tongue -- both read
        /// acceptably in skin tone and unacceptably in white, and a white
        /// tongue is a more visible error than a slightly-too-pink one.
        ///
        /// EYEBROWS AND EYELASHES USED TO BE IN THAT LIST AND ARE NOT NOW.
        /// They have no colour of their own in the manifest, so they fell
        /// back to skin along with the teeth, and skin-coloured eyebrows are
        /// not a slightly wrong tone: a face reads as wrong before a viewer
        /// can say why, and missing brows are most of the reason. They are
        /// made of hair, so they take `hair` -- the villager's own measured
        /// `hair_pigment`. This is a CITED trait driving a visible channel,
        /// which is what item A4 requires; inventing a brow colour from the
        /// name would not have been.
        ///
        /// AND THE HAIR COLOUR IS GATED ON THE CUTOUT BEING INSTALLED, which
        /// is the correction to the first version of that change. A brow is a
        /// flat CARD whose hairs are cut out of it by an alpha channel. Given
        /// the hair colour and no alpha, the whole card renders as a solid
        /// dark rectangle, and the reported symptom was that every villager
        /// appeared to be wearing mascara -- measurably so, since only 8 to 18
        /// percent of one of these cards should be drawn at all. Skin-coloured
        /// is a hidden defect; dark and solid is a visible one. So the colour
        /// travels with the shape or not at all: no card, no hair colour, back
        /// to the skin fallback the viewer used before.
        /// See <see cref="HairCardMaterials"/>.
        /// </summary>
        private static Color[] ResolveColors(string stem, string[] sourceNames,
                                             out int eyeIndex,
                                             out string[] submeshChannels,
                                             out string[] submeshAssets)
        {
            eyeIndex = -1;
            submeshChannels = null;
            submeshAssets = null;
            Dictionary<string, Color> byChannel;
            if (!_colors.TryGetValue(stem, out byChannel) || sourceNames == null)
                return null;

            Dictionary<string, string> byName;
            _channels.TryGetValue(stem, out byName);

            Color skin;
            if (!byChannel.TryGetValue("skin", out skin)) skin = Color.white;

            var out_ = new Color[sourceNames.Length];
            var channels = new string[sourceNames.Length];
            var assets = new string[sourceNames.Length];
            submeshChannels = channels;
            submeshAssets = assets;
            for (int i = 0; i < sourceNames.Length; i++)
            {
                out_[i] = skin;
                string raw = sourceNames[i];
                if (string.IsNullOrEmpty(raw)) continue;

                int dot = raw.LastIndexOf('.');
                string local = (dot >= 0 ? raw.Substring(dot + 1) : raw)
                    .ToLowerInvariant();
                if (local.EndsWith("_body"))
                    local = local.Substring(0, local.Length - 5);

                string channel;
                if (byName == null || !byName.TryGetValue(local, out channel))
                    continue;

                if (channel == "eyes") eyeIndex = i;
                channels[i] = channel;
                assets[i] = local;

                bool isCard = channel == "eyebrows" || channel == "eyelashes";

                Color c;
                // `suit` and `shoes` are separate channels in the engine but
                // the manifest names the garment colour `clothes`, so a suit
                // asks for `suit` first and settles for `clothes`. Eyebrows
                // and eyelashes have no colour of their own and are made of
                // hair, so they ask for `hair` -- but only if their cutout is
                // installed, because dark colour without the shape is the
                // mascara defect. Otherwise they keep the skin fallback
                // already sitting in `out_[i]`.
                if (byChannel.TryGetValue(channel, out c) ||
                    (channel == "suit" && byChannel.TryGetValue("clothes", out c)) ||
                    (isCard && HairCardMaterials.Has(local) &&
                     byChannel.TryGetValue("hair", out c)))
                    out_[i] = c;
            }
            return out_;
        }

        /// <summary>
        /// Each submesh's appearance channel, in submesh order, or null when
        /// the bundle carries none.
        ///
        /// Null rather than an array of nulls, for the same reason
        /// <see cref="SubmeshColorsFor"/> returns null: a caller that gets
        /// channels assigns surfaces from them, and a caller that gets null
        /// must draw every part as flesh, which is what the viewer did before
        /// <see cref="BodyMaterials"/> existed.
        /// </summary>
        public static string[] SubmeshChannelsFor(string villagerName,
                                                  string lifeStage)
        {
            string stem = StemFor(villagerName, lifeStage);
            if (stem == null) return null;
            string[] channels;
            return _submeshChannels.TryGetValue(stem, out channels) ? channels : null;
        }

        /// <summary>
        /// Each submesh's source mesh name, in submesh order, or null when the
        /// bundle carries none. `eyebrow001`, `eyelashes02`, `afro01`.
        ///
        /// Needed because a brow's shape is in ITS OWN asset's alpha channel,
        /// so knowing that a submesh is "eyebrows" is not enough to draw it.
        /// </summary>
        public static string[] SubmeshAssetsFor(string villagerName,
                                                string lifeStage)
        {
            string stem = StemFor(villagerName, lifeStage);
            if (stem == null) return null;
            string[] assets;
            return _submeshAssets.TryGetValue(stem, out assets) ? assets : null;
        }

        /// <summary>
        /// The skin detail map for this villager's body, or null when none is
        /// installed.
        ///
        /// Resolved HERE rather than in <see cref="VillagerView"/> because
        /// the age and the sex that pick it belong to the BODY, and the
        /// manifest is the only thing that knows which body a staged bundle
        /// handed back. Asking the CSV row instead would give the person's
        /// age this year, which for a staged bundle is not the age the body
        /// on screen was baked at.
        /// </summary>
        public static Material SkinMaterialFor(string villagerName,
                                               string lifeStage)
        {
            string stem = StemFor(villagerName, lifeStage);
            if (stem == null) return null;
            float age;
            if (!_bodyAge.TryGetValue(stem, out age)) return null;
            bool female;
            _bodyFemale.TryGetValue(stem, out female);
            return SkinMaterials.For(age, female);
        }

        /// <summary>Which submesh index is this villager's EYES channel, or
        /// -1 when there isn't one (no colours, or a bundle predating item
        /// E2). <see cref="VillagerView"/> uses this to give that one slot
        /// the eye-shaded material instead of the flat body colour.</summary>
        public static int EyeSubmeshIndexFor(string villagerName, string lifeStage)
        {
            string stem = StemFor(villagerName, lifeStage);
            if (stem == null) return -1;
            int idx;
            return _eyeIndex.TryGetValue(stem, out idx) ? idx : -1;
        }

        /// <summary>This villager's `eye_color` label, or null when the
        /// bundle does not carry one.</summary>
        public static string EyeLabelFor(string villagerName, string lifeStage)
        {
            string stem = StemFor(villagerName, lifeStage);
            if (stem == null) return null;
            string label;
            return _eyeLabel.TryGetValue(stem, out label) ? label : null;
        }

        /// <summary>
        /// This villager's own body, or the shared one for their sex, or null.
        ///
        /// Returns a UNIT body -- 1 m tall with soles on the origin -- in every
        /// case, so the caller's scaling is identical whichever tier answered.
        /// </summary>
        public static Mesh UnitBodyFor(string villagerName, bool female)
        {
            return UnitBodyFor(villagerName, null, female);
        }

        /// <summary>
        /// This villager's body AT A LIFE STAGE, so scrubbing the timeline
        /// back to their childhood draws a child rather than a small adult
        /// (item U6).
        ///
        /// Falls back in a fixed order, and every step of it is reachable in
        /// practice: <c>Name@stage</c> is the staged body; <c>Name</c> catches
        /// a legacy bundle, and also a staged bundle asked for a stage it did
        /// not bake; the shared mesh for the sex catches a villager with no
        /// body at all. Pass a null or empty stage to ask for the person's
        /// single body directly.
        ///
        /// Stature is NOT read from the stage. <see cref="VillagerView"/>
        /// scales by the frame's own <c>height_cm</c>, so a child is already
        /// the right height before this is called; what a stage body changes
        /// is proportion and face, which a uniform scale cannot produce.
        /// </summary>
        public static Mesh UnitBodyFor(string villagerName, string lifeStage,
                                       bool female)
        {
            string stem = StemFor(villagerName, lifeStage);
            if (stem == null) return HumanMesh.UnitBody(female);

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
            string[] sourceNames;
            Mesh baked = HumanMesh.Bake(model, known, out authored, out sourceNames);
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
            int eyeIdx;
            string[] channels, assets;
            _submeshColors[stem] = ResolveColors(stem, sourceNames, out eyeIdx,
                                                 out channels, out assets);
            _submeshChannels[stem] = channels;
            _submeshAssets[stem] = assets;
            _eyeIndex[stem] = eyeIdx;
            return baked;
        }
    }
}
