using System.Collections.Generic;
using ExtNPC.Data;
using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// Stage 4: click a villager, see who they are — in the dashboard's own
    /// words.
    ///
    /// THE RULE THIS COMPONENT EXISTS TO KEEP. A villager must not be
    /// described differently by the two UIs (UNITY_PLAN.md invariant 6). Every
    /// label, unit, rounding rule and colour threshold below comes from
    /// <see cref="InspectorFormat"/>, which mirrors dashboard/inspector.py line
    /// by line. Nothing here formats a number inline, and nothing here derives
    /// one.
    ///
    /// LIVE vs HISTORICAL, and why the distinction is loud. The engine's
    /// snapshot ring stores ~18 scalars per person per tick, not genomes — so
    /// for a past year you can see who was alive, where they stood and their
    /// headline stats, but the full genetic character sheet does not exist to
    /// be shown. simulation/snapshots.py says so itself, and the dashboard
    /// marks the same distinction. A viewer that silently rendered a thinner
    /// panel at year 40 would look like a villager with less going on rather
    /// than a year with less recorded.
    ///
    /// IMGUI on purpose. The package has no uGUI or UI Toolkit dependency and
    /// ships no prefabs or assets, which is what lets Editor/SceneSetup.cs
    /// build a working viewer from an empty scene in one click. A diagnostic
    /// panel is the case OnGUI is actually good at.
    /// </summary>
    [AddComponentMenu("extNPC/Villager Inspector")]
    [RequireComponent(typeof(WorldRenderer))]
    public sealed class VillagerInspector : MonoBehaviour
    {
        [Tooltip("Panel width in pixels.")]
        public float panelWidth = 350f;

        [Tooltip("Hide the panel without removing the component.")]
        public bool show = true;

        [Tooltip("Show the 25 trait_* columns from people.csv. Live tick only " +
                 "— they are the MATURE phenotype and the history buffer does " +
                 "not keep them.")]
        public bool showTraits = true;

        [Tooltip("Show a live, moving head at the top of the panel. Needs a " +
                 "body asset in Resources/extnpc/ — see HumanMesh. With none " +
                 "installed the panel says so instead.")]
        public bool showPortrait = true;

        private CharacterPortrait _portrait;

        private WorldRenderer _renderer;
        private ExtNpcWorldLoader _loader;
        private WorldBundle _bundle;

        // The NAME is the selection, not the row. A row is a person at one
        // tick; scrubbing to another year must follow the same individual, and
        // must be able to report that they were not alive there.
        private string _selected;

        private Vector2 _scroll;
        private GUIStyle _key, _val, _valSmall, _name, _sub, _pill, _banner, _section;
        private bool _stylesReady;

        /// <summary>The villager currently inspected, or null.</summary>
        public string SelectedName => _selected;

        /// <summary>
        /// True when a portrait head is being rendered right now.
        ///
        /// Exposed for the play-mode capture harness, which otherwise cannot
        /// tell "the portrait drew nothing" apart from "no villager is
        /// selected" or "no body pack is installed": all three show the same
        /// empty card, and the first is a bug while the other two are not.
        /// </summary>
        public bool PortraitIsLive => _portrait != null && _portrait.Texture != null;

        /// <summary>The portrait's render target, or null. Read-only, and
        /// exposed for the same harness: capturing the Game view needs a real
        /// Game view, which a batch editor does not have.</summary>
        public Texture PortraitTexture => _portrait != null ? _portrait.Texture : null;

        public void Select(string name) => _selected = name;
        public void ClearSelection() => _selected = null;

        private void Awake()
        {
            _renderer = GetComponent<WorldRenderer>();
            _loader = GetComponent<ExtNpcWorldLoader>();
            _renderer.VillagerSelected += OnVillagerSelected;
            if (_loader != null)
            {
                _loader.Loaded += OnLoaded;
                // Catch up if the bundle arrived before this component existed
                // — subscribing to an event that has already fired is a silent
                // no-op, and the symptom is an empty panel next to a healthy
                // console. WorldRenderer.Awake does the same for the same
                // reason.
                if (_loader.Bundle != null) OnLoaded(_loader.Bundle);
            }
        }

        private void OnDestroy()
        {
            // Named handlers rather than lambdas precisely so they can be
            // removed: a lambda cannot be unsubscribed, and would keep this
            // component alive through the loader's event for as long as the
            // loader lives.
            if (_renderer != null) _renderer.VillagerSelected -= OnVillagerSelected;
            if (_loader != null) _loader.Loaded -= OnLoaded;
        }

        private void OnLoaded(WorldBundle bundle) => _bundle = bundle;

        private void OnVillagerSelected(FrameRow row) => _selected = row.Name;

        // ------------------------------------------------------------------
        // the portrait
        // ------------------------------------------------------------------

        /// <summary>
        /// Point the portrait at the selection and render one frame.
        ///
        /// IN UPDATE, NOT IN OnGUI. OnGUI runs several times per frame, once
        /// for layout and once per repaint event, so rendering the portrait
        /// camera there would cost it two or three times over and make the
        /// animation speed depend on how many event passes Unity happened to
        /// send. Update runs exactly once, so the motion is a function of wall
        /// clock and nothing else.
        /// </summary>
        private void Update()
        {
            // `show` as well as `showPortrait`: with the panel hidden there is
            // nothing to blit the texture into, and rendering a camera every
            // frame for an invisible picture is the kind of cost that is
            // invisible until someone profiles a build.
            if (!show || !showPortrait || !CharacterPortrait.BodyInstalled)
            {
                _portrait?.ClearSubject();
                return;
            }
            if (_bundle == null || string.IsNullOrEmpty(_selected))
            {
                _portrait?.ClearSubject();
                return;
            }

            FrameRow[] frame = _bundle.FrameAt(_renderer.tick);
            for (int i = 0; i < frame.Length; i++)
            {
                if (frame[i].Name != _selected) continue;
                _portrait ??= CharacterPortrait.Create(transform);
                _portrait.SetSubject(frame[i].Name, frame[i].LifeStage,
                                     frame[i].IsFemale,
                                     frame[i].HeightCm, frame[i].Color);
                // Time.timeAsDouble rather than Time.time: a session left open
                // long enough loses animation resolution in a float, and the
                // pose is defined on a double for that reason.
                _portrait.RenderFrame(Time.timeAsDouble);
                return;
            }

            // Selected but not alive at this year. The panel already says so in
            // words; showing the last face they had would contradict it.
            _portrait?.ClearSubject();
        }

        // ------------------------------------------------------------------
        // mode
        // ------------------------------------------------------------------

        /// <summary>
        /// True when the displayed year is earlier than the export's own last
        /// year. In that mode people.csv must not be read: it is
        /// CROSS-SECTIONAL — each row is the individual as they are now, or as
        /// they were at death — so joining it to a past frame would describe a
        /// year-40 villager with year-90 genetics and show no seam.
        /// </summary>
        public bool IsHistorical =>
            _bundle != null && _renderer != null && _renderer.tick < _bundle.LastTick;

        // ------------------------------------------------------------------
        // GUI
        // ------------------------------------------------------------------

        private void OnGUI()
        {
            if (!show || _bundle == null) return;
            EnsureStyles();

            float margin = 12f;
            var area = new Rect(Screen.width - panelWidth - margin, margin,
                                panelWidth, Screen.height - margin * 2f);

            // Same chrome as the timeline HUD, from the same place, so the two
            // panels cannot drift into looking like two different tools.
            HudChrome.Panel(area);

            GUILayout.BeginArea(new Rect(area.x + 14f, area.y + 12f,
                                         area.width - 28f, area.height - 24f));
            _scroll = GUILayout.BeginScrollView(_scroll, false, false);

            Section("INSPECTOR");
            GUILayout.Space(8f);

            if (string.IsNullOrEmpty(_selected)) DrawEmpty();
            else DrawVillager();

            GUILayout.EndScrollView();
            GUILayout.EndArea();
        }

        private void DrawEmpty()
        {
            // inspector.py:210 — the same invitation, in the same place.
            Label("Click any villager to inspect them here.", _sub);
            GUILayout.Space(10f);
            Rule();
            GUILayout.Space(10f);
            Label("The dashboard holds the full character sheet: genetics, " +
                  "health, mind and family tree. This panel is the viewer's " +
                  "echo of it, not a replacement.", _sub);
        }

        private void DrawVillager()
        {
            FrameRow[] frame = _bundle.FrameAt(_renderer.tick);
            bool found = false;
            FrameRow row = default;
            for (int i = 0; i < frame.Length; i++)
            {
                if (frame[i].Name == _selected) { row = frame[i]; found = true; break; }
            }

            if (!found)
            {
                // inspector.py:227 — absence from a frame means not alive at
                // that tick, and saying so is better than an empty panel.
                Label(InspectorFormat.GivenName(_selected) +
                      " was not alive at this point in the timeline.",
                      _banner);
                GUILayout.Space(8f);
                if (GUILayout.Button("clear selection")) ClearSelection();
                return;
            }

            DrawIdentity(row);

            if (IsHistorical)
            {
                // The banner is not decoration. It is the difference between
                // "this villager has no genetics" and "this year has no
                // genetics recorded".
                // The clock glyph is gone from both UIs; see
                // TimelineFormat.ScrubState. "historical view" was already
                // carrying the meaning, so nothing replaces it here.
                Label("historical view — year " +
                      InspectorFormat.Int(row.Tick), _banner);
                GUILayout.Space(6f);
            }

            DrawHeadline(row);
            GUILayout.Space(8f);
            Rule();
            GUILayout.Space(8f);
            Meter("stress load",
                  (float)InspectorFormat.Norm(row.Stress,
                                              InspectorFormat.StressMeterLo,
                                              InspectorFormat.StressMeterHi),
                  InspectorFormat.Crit,
                  InspectorFormat.Signed2(row.Stress));

            if (IsHistorical)
            {
                GUILayout.Space(10f);
                Label("Full genetic sheet is available at the live year only — " +
                      "the history buffer keeps headline stats, not genomes.",
                      _sub);
            }
            else
            {
                DrawDeepSheet(row);
            }

            GUILayout.Space(10f);
            GUILayout.BeginHorizontal();
            // "go to" before "clear", because it is the one people want. The
            // default camera frames the whole 100 m map, where a 1.7 m villager
            // is under 2% of the frame: without this the only way to actually
            // look at the body you just selected is to scroll-zoom and hunt.
            if (GUILayout.Button("go to villager")) FocusCameraOn(row);
            if (GUILayout.Button("clear selection")) ClearSelection();
            GUILayout.EndHorizontal();
            GUILayout.Space(6f);
        }

        /// <summary>
        /// Move the orbit camera to stand next to this villager.
        ///
        /// Reaches for the camera through Camera.main rather than holding a
        /// reference: the package does not own the camera, SceneSetup only adds
        /// an OrbitCamera if the scene has none, and a host project may have
        /// replaced it. Absent or replaced, this button does nothing rather
        /// than throwing.
        /// </summary>
        private void FocusCameraOn(in FrameRow row)
        {
            Camera main = Camera.main;
            OrbitCamera orbit = main != null ? main.GetComponent<OrbitCamera>() : null;
            if (orbit == null) return;
            Vector3 ground = _renderer.Projection.ToWorld(row.X, row.Y);
            orbit.Focus(ground, (float)(System.Math.Max(row.HeightCm, 1.0) * 0.01));
        }

        // ---- identity ----------------------------------------------------

        /// <summary>Portrait card size in points. 0.866 aspect, matching
        /// <see cref="CharacterPortrait"/>'s render texture, so the face is
        /// never stretched.</summary>
        private const float PortraitW = 132f, PortraitH = 152f;

        private void DrawIdentity(in FrameRow row)
        {
            GUILayout.BeginHorizontal();

            if (showPortrait) DrawPortrait(row);

            GUILayout.BeginVertical();
            GUILayout.BeginHorizontal();
            Swatch(row.Color, 18f);
            GUILayout.Space(8f);
            GUILayout.BeginVertical();
            Label(InspectorFormat.GivenName(row.Name), _name);
            // inspector.py:253 — "female · age 34 · gen 3"
            Label(InspectorFormat.Sex(row.IsFemale) +
                  " · age " + InspectorFormat.Int(row.Age) +
                  " · gen " + InspectorFormat.Int(row.Generation), _sub);
            GUILayout.EndVertical();
            GUILayout.EndHorizontal();
            GUILayout.Space(8f);

            // inspector.py:260 — lineage pill carries the purity as a percent.
            Pill(InspectorFormat.GivenName(row.Lineage) + " " +
                 InspectorFormat.Percent0(row.Purity));
            Pill(DemeLabel(row.Deme, row.Tick));
            GUILayout.FlexibleSpace();
            GUILayout.EndVertical();

            GUILayout.EndHorizontal();
            GUILayout.Space(10f);
        }

        /// <summary>
        /// The live head, or an honest note about why there is not one.
        ///
        /// The absent case is deliberately a sentence and not a blank box. The
        /// package ships no assets by design, so "no body installed" is a
        /// SUPPORTED state rather than a failure, and the reader needs to be
        /// told the difference between that and a villager who cannot be drawn.
        /// </summary>
        private void DrawPortrait(in FrameRow row)
        {
            Rect card = GUILayoutUtility.GetRect(PortraitW, PortraitH,
                GUILayout.Width(PortraitW), GUILayout.Height(PortraitH));

            RenderTexture face = _portrait != null ? _portrait.Texture : null;
            if (face != null)
            {
                GUI.DrawTexture(card, face, ScaleMode.ScaleToFit, false);
            }
            else
            {
                Fill(card, CharacterPortrait.Backdrop(row.Color));
                var text = new Rect(card.x + 8f, card.y + 8f,
                                    card.width - 16f, card.height - 16f);
                GUI.Label(text, CharacterPortrait.BodyInstalled
                        ? "no face at this year"
                        : "no body pack installed\n\n" +
                          "python run_mpfb_probe.py --export-bodies\n\n" +
                          "then drop the FBX files in\nAssets/Resources/extnpc/",
                    _sub);
            }

            // The lineage colour again, as a hairline frame, so the portrait is
            // tied to the same identity the map dot carries.
            Outline(card, row.Color);
            GUILayout.Space(10f);
        }

        /// <summary>
        /// The settlement's name, READ from demes.csv rather than rebuilt.
        ///
        /// simulation/community.deme_label maps an id onto a fixed name table;
        /// reimplementing that table in C# would be a second definition that
        /// silently goes stale the moment a name is added. When the column is
        /// absent — an older bundle — the id is shown plainly rather than
        /// guessed at.
        /// </summary>
        private string DemeLabel(int deme, int tick)
        {
            if (_bundle.Demes.TryGetValue(tick, out var rows))
            {
                for (int i = 0; i < rows.Length; i++)
                {
                    if (rows[i].Deme == deme && !string.IsNullOrEmpty(rows[i].Label))
                        return rows[i].Label;
                }
            }
            return "deme " + InspectorFormat.Int(deme);
        }

        // ---- headline stats, available in BOTH modes ---------------------

        private void DrawHeadline(in FrameRow row)
        {
            PersonRow person = LivePerson();

            // Height. At the live year people.csv also carries the mature
            // endpoint, so a growing individual shows both — exactly as the
            // dashboard does (inspector.py:290). Historically only the
            // age-expressed value exists, and inventing the endpoint from it
            // is not possible, which is the honest answer.
            if (person != null)
            {
                double mature = person.GetTrait("height_cm");
                Row("height", double.IsNaN(mature)
                        ? InspectorFormat.Height(row.HeightCm)
                        : InspectorFormat.HeightLive(row.HeightCm, mature));
            }
            else
            {
                Row("height", InspectorFormat.Height(row.HeightCm));
            }

            Row("life stage", string.IsNullOrEmpty(row.LifeStage) ? "—" : row.LifeStage);
            Row("stress", InspectorFormat.Signed2(row.Stress),
                InspectorFormat.StressColor(row.Stress));
            Row("VO₂", InspectorFormat.Fixed2(row.Aerobic));
            Row("age acceleration", InspectorFormat.SignedYears(row.EpiAccel),
                InspectorFormat.EpiAccelColor(row.EpiAccel));
            Row("conditions", InspectorFormat.Int(row.Conditions));
            Row("children", InspectorFormat.Int(row.Children));

            Row("pedigree F", InspectorFormat.FmtF(row.PedigreeF),
                InspectorFormat.FColor(row.PedigreeF));
            if (row.PedigreeF > 1e-9)
            {
                // inspector.py:150 — F is meaningless to most readers as a bare
                // number, so it is always labelled with the mating that
                // produces it.
                Row("parents were", InspectorFormat.RelationshipLabel(row.PedigreeF),
                    InspectorFormat.FColor(row.PedigreeF), small: true);
            }
            Row("viability", InspectorFormat.Fixed3(row.Viability),
                InspectorFormat.ViabilityColor(row.Viability));
            if (row.Cnv > 0) Row("CNVs", InspectorFormat.Int(row.Cnv),
                                 InspectorFormat.Warn);
        }

        // ---- the deep sheet, live year only ------------------------------

        private void DrawDeepSheet(in FrameRow row)
        {
            PersonRow p = LivePerson();
            if (p == null)
            {
                GUILayout.Space(10f);
                Label("No people.csv row for this villager.", _sub);
                return;
            }

            GUILayout.Space(10f);
            Rule();
            GUILayout.Space(8f);
            Section("GENETIC LOAD");
            GUILayout.Space(6f);

            // Pedigree F and realised F are both shown on purpose: the first
            // is an EXPECTATION over meioses, the second is what this genome
            // actually got, and they differ because meiosis is a lottery
            // (inspector.py:136).
            Row("realised F", InspectorFormat.Signed4(p.RealisedF),
                InspectorFormat.FColor(System.Math.Max(p.RealisedF, 0.0)));

            double statureCost = Num(p.GetRaw("stature_cost_cm"));
            if (row.PedigreeF > 1e-9 && !double.IsNaN(statureCost))
            {
                // The engine's OTHER cost of inbreeding. Recessive load decides
                // survival; directional dominance decides height; they are
                // independent, and a viewer that showed only viability would
                // re-hide half of what the engine measures.
                Row("stature cost", InspectorFormat.StatureCost(statureCost),
                    InspectorFormat.StatureCostColor(statureCost));
            }

            double carried = Num(p.GetRaw("hidden_load_alleles"));
            if (!double.IsNaN(carried))
                Row("hidden load", InspectorFormat.Int((int)carried) + " alleles",
                    small: true);

            double expressed = Num(p.GetRaw("expressed_load_homozygotes"));
            if (!double.IsNaN(expressed) && expressed > 0)
                Row("expressed load", InspectorFormat.Int((int)expressed) + " loci",
                    InspectorFormat.Crit);

            // Named Mendelian recessives. The dashboard prints the GENE as the
            // key and the disorder's display name as the value
            // (inspector.py:171); both come from the bundle's diseases.csv, so
            // the panel's wording has exactly one definition, in
            // health_engine/diseases.py.
            foreach (string slug in p.MendelianDiagnoses)
            {
                if (string.IsNullOrEmpty(slug)) continue;
                DiseaseRow d = _bundle.Disease(slug);
                Row("dx " + (d != null ? d.Gene : slug),
                    d != null ? d.Label : slug,
                    InspectorFormat.Crit, small: true);
            }

            if (p.MendelianCarrierOf.Length > 0)
            {
                var genes = new List<string>(p.MendelianCarrierOf.Length);
                foreach (string slug in p.MendelianCarrierOf)
                {
                    if (string.IsNullOrEmpty(slug)) continue;
                    DiseaseRow d = _bundle.Disease(slug);
                    genes.Add(d != null ? d.Gene : slug);
                }
                if (genes.Count > 0)
                    Row("carrier of", string.Join(", ", genes), small: true);
            }

            double het = Num(p.GetRaw("heterozygosity"));
            if (!double.IsNaN(het))
            {
                GUILayout.Space(6f);
                Meter("heterozygosity", (float)InspectorFormat.Norm(het, 0.0, 0.6),
                      InspectorFormat.Accent, InspectorFormat.Fixed3(het));
            }

            // ---- health --------------------------------------------------
            GUILayout.Space(8f);
            Rule();
            GUILayout.Space(8f);
            Section("HEALTH");
            GUILayout.Space(6f);

            double bmi = p.GetTrait("bmi");
            double mature = p.GetTrait("height_cm");
            if (!double.IsNaN(bmi))
                Row("BMI", InspectorFormat.Bmi(
                        bmi, InspectorFormat.IsGrowing(row.HeightCm, mature)));

            // Names, not a count: "conditions: 2" makes the reader go looking
            // for WHAT the individual has (inspector.py:310).
            Row("conditions",
                p.MedicalConditions.Length == 0
                    ? "none"
                    : string.Join(", ", Humanise(p.MedicalConditions)),
                p.MedicalConditions.Length > 0
                    ? InspectorFormat.Crit : InspectorFormat.Ink,
                small: p.MedicalConditions.Length > 0);

            string mito = p.GetRaw("mito_haplogroup");
            if (!string.IsNullOrEmpty(mito)) Row("mito haplogroup", mito, small: true);

            string partner = p.GetRaw("partner");
            Row("partner", string.IsNullOrEmpty(partner)
                    ? "—" : InspectorFormat.GivenName(partner));

            // ---- traits --------------------------------------------------
            if (showTraits) DrawTraits(p);
        }

        private void DrawTraits(PersonRow p)
        {
            if (p.Raw == null) return;

            GUILayout.Space(8f);
            Rule();
            GUILayout.Space(8f);
            Section("TRAITS · MATURE PHENOTYPE");
            GUILayout.Space(4f);
            Label("The genetic endpoint, not the value expressed at this age.",
                  _sub);
            GUILayout.Space(6f);

            // Sorted so the list is stable between villagers; the export order
            // of a dictionary is not something to rely on for a UI.
            var keys = new List<string>();
            foreach (var kv in p.Raw)
                if (kv.Key.StartsWith("trait_")) keys.Add(kv.Key);
            keys.Sort(System.StringComparer.Ordinal);

            foreach (string key in keys)
            {
                string raw = p.Raw[key];
                if (string.IsNullOrEmpty(raw)) continue;

                // Categorical traits (eye_color, handedness) are strings and
                // are shown verbatim. Mapping them to anything here would be
                // inventing a vocabulary the engine did not write.
                string shown = CsvParse.TryDouble(raw, out double v)
                    ? InspectorFormat.Fixed2(v)
                    : raw;
                Row(key.Substring(6).Replace('_', ' '), shown, small: true);
            }
        }

        // ------------------------------------------------------------------
        // helpers
        // ------------------------------------------------------------------

        /// <summary>people.csv's row for the selection, but ONLY at the live
        /// year. See <see cref="IsHistorical"/> for why this returns null
        /// otherwise.</summary>
        private PersonRow LivePerson()
        {
            if (IsHistorical || _selected == null) return null;
            return _bundle.People.TryGetValue(_selected, out var p) ? p : null;
        }

        /// <summary>
        /// A raw cell as a number, or NaN.
        ///
        /// Takes the VALUE, not the column name, and that shape is deliberate.
        /// The earlier signature was Num(person, "hidden_load_alleles"), which
        /// hid the column name behind a helper — and tests/test_unity_contract
        /// .py checks column names by scanning this source for GetRaw("...").
        /// A literal passed through a wrapper is invisible to that scan, so the
        /// typo it exists to catch sailed straight through a deliberate
        /// sabotage. Keeping every column name at a GetRaw call site is what
        /// makes the guard able to see them.
        /// </summary>
        private static double Num(string raw) =>
            CsvParse.TryDouble(raw, out double v) ? v : double.NaN;

        /// <summary>
        /// Condition names as the drawer prints them: underscores to spaces,
        /// de-duplicated, sorted — inspector.py:313 is `sorted({...})`, a SET
        /// comprehension. The export writes `";".join(sorted(...))` without
        /// de-duplicating, so an individual carrying the same condition twice
        /// would be listed twice here and once in the dashboard. Small, but
        /// the acceptance criterion for this stage is that the two never
        /// describe a villager differently.
        /// </summary>
        private static string[] Humanise(string[] names)
        {
            var seen = new List<string>(names.Length);
            foreach (string n in names)
            {
                string pretty = n.Replace('_', ' ');
                if (!seen.Contains(pretty)) seen.Add(pretty);
            }
            seen.Sort(System.StringComparer.Ordinal);
            return seen.ToArray();
        }

        // ---- IMGUI primitives --------------------------------------------

        private void Row(string key, string value) => Row(key, value, InspectorFormat.Ink);

        private void Row(string key, string value, Color color, bool small = false)
        {
            GUILayout.BeginHorizontal();
            GUILayout.Label(key, _key);
            GUILayout.FlexibleSpace();
            var style = small ? _valSmall : _val;
            var prev = style.normal.textColor;
            style.normal.textColor = color;
            GUILayout.Label(value, style);
            style.normal.textColor = prev;
            GUILayout.EndHorizontal();
            GUILayout.Space(3f);
        }

        private void Row(string key, string value, bool small) =>
            Row(key, value, InspectorFormat.Ink, small);

        private void Label(string text, GUIStyle style) => GUILayout.Label(text, style);

        /// <summary>A section header, drawn the same way the timeline HUD draws
        /// one. Two panels of the same instrument should not label their
        /// sections in two different visual languages.</summary>
        private void Section(string title)
        {
            Rect r = GUILayoutUtility.GetRect(10f, 15f, GUILayout.ExpandWidth(true));
            HudChrome.SectionBar(r);
            GUI.Label(new Rect(r.x + 6f, r.y + 1f, r.width - 8f, r.height),
                      title, _section);
            GUILayout.Space(5f);
        }

        private void Meter(string label, float frac, Color color, string hint)
        {
            GUILayout.BeginHorizontal();
            GUILayout.Label(label, _key);
            GUILayout.FlexibleSpace();
            GUILayout.Label(hint, _valSmall);
            GUILayout.EndHorizontal();

            Rect bar = GUILayoutUtility.GetRect(10f, 6f, GUILayout.ExpandWidth(true));
            Fill(bar, InspectorFormat.Plane);
            Fill(new Rect(bar.x, bar.y, bar.width * Mathf.Clamp01(frac), bar.height),
                 color);
            // A hairline cap on the filled end, so a bar at 3% still reads as a
            // measurement rather than as an empty trough.
            Fill(new Rect(bar.x + bar.width * Mathf.Clamp01(frac) - 1f, bar.y - 1f,
                          2f, bar.height + 2f), color);
            GUILayout.Space(6f);
        }

        private void Rule()
        {
            Rect r = GUILayoutUtility.GetRect(10f, 1f, GUILayout.ExpandWidth(true));
            HudChrome.Hairline(r);
        }

        private void Swatch(Color c, float size)
        {
            Rect r = GUILayoutUtility.GetRect(size, size,
                GUILayout.Width(size), GUILayout.Height(size));
            Fill(r, c);
        }

        private void Pill(string text)
        {
            GUILayout.Label(text, _pill);
            GUILayout.Space(4f);
        }

        private static void Fill(Rect r, Color c) => HudChrome.Fill(r, c);

        private static void Outline(Rect r, Color c) => HudChrome.Outline(r, c);

        private void EnsureStyles()
        {
            if (_stylesReady) return;


            _key = new GUIStyle(GUI.skin.label)
            { fontSize = 12, wordWrap = false };
            _key.normal.textColor = InspectorFormat.Muted;

            _val = new GUIStyle(GUI.skin.label)
            { fontSize = 12, fontStyle = FontStyle.Bold, alignment = TextAnchor.MiddleRight };
            _val.normal.textColor = InspectorFormat.Ink;

            _valSmall = new GUIStyle(_val) { fontSize = 11, fontStyle = FontStyle.Normal };

            _name = new GUIStyle(GUI.skin.label)
            { fontSize = 17, fontStyle = FontStyle.Bold };
            _name.normal.textColor = InspectorFormat.Ink;

            _sub = new GUIStyle(GUI.skin.label) { fontSize = 11, wordWrap = true };
            _sub.normal.textColor = InspectorFormat.Muted;

            _pill = new GUIStyle(GUI.skin.box) { fontSize = 11 };
            _pill.normal.textColor = InspectorFormat.Ink2;

            _banner = new GUIStyle(GUI.skin.label)
            { fontSize = 11, fontStyle = FontStyle.Bold, wordWrap = true };
            _banner.normal.textColor = InspectorFormat.Warn;

            _section = new GUIStyle(GUI.skin.label)
            { fontSize = 10, fontStyle = FontStyle.Bold };
            _section.normal.textColor = InspectorFormat.Accent;

            _stylesReady = true;
        }
    }
}
