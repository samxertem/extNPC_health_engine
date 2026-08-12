using System.IO;
using ExtNPC.Data;
using UnityEditor;
using UnityEngine;

namespace ExtNPC.Editor
{
    /// <summary>
    /// Inspect a world bundle without entering play mode.
    ///
    /// Exists because the most common confusion when wiring this up is not a
    /// code error but a provenance one: which export is this, which engine
    /// commit produced it, which locus catalogue do its genotypes mean
    /// anything under, and does frames.csv actually start at year 0. All of
    /// that is in manifest.json and none of it is visible from the filesystem.
    /// </summary>
    public sealed class BundleInspectorWindow : EditorWindow
    {
        private string _path = "";
        private WorldBundle _bundle;
        private string _error;
        private Vector2 _scroll;

        [MenuItem("Window/extNPC/Bundle Inspector")]
        public static void Open() =>
            GetWindow<BundleInspectorWindow>("extNPC Bundle");

        private void OnGUI()
        {
            EditorGUILayout.LabelField("World bundle", EditorStyles.boldLabel);

            using (new EditorGUILayout.HorizontalScope())
            {
                _path = EditorGUILayout.TextField(_path);
                if (GUILayout.Button("…", GUILayout.Width(28)))
                {
                    string picked = EditorUtility.OpenFolderPanel(
                        "Select a world bundle directory", _path, "");
                    if (!string.IsNullOrEmpty(picked)) _path = picked;
                }
            }

            using (new EditorGUI.DisabledScope(string.IsNullOrEmpty(_path)))
            {
                if (GUILayout.Button("Load")) LoadBundle();
            }

            if (!string.IsNullOrEmpty(_error))
            {
                EditorGUILayout.HelpBox(_error, MessageType.Error);
                return;
            }
            if (_bundle == null) return;

            _scroll = EditorGUILayout.BeginScrollView(_scroll);
            var m = _bundle.Manifest;

            EditorGUILayout.Space();
            EditorGUILayout.LabelField("Provenance", EditorStyles.boldLabel);
            Row("Engine commit", m.GitCommit);
            Row("Seed", m.Seed.ToString());
            Row("Final year", m.Tick.ToString());
            Row("Exported", m.ExportedAt);
            if (!string.IsNullOrEmpty(m.Note)) Row("Note", m.Note);
            Row("Bundle schema", m.BundleSchema.ToString());

            // Never let the catalogue be a quiet field. Two exports with the
            // same seed under different catalogues are different MODELS, and
            // nothing in the numbers themselves says which one you are looking at.
            Row("Locus catalogue", m.Catalogue);
            if (m.Catalogue == "empirical")
            {
                EditorGUILayout.HelpBox(
                    "EXPERIMENTAL catalogue. The empirical (1000G EUR) locus " +
                    "frequencies are not validated — see health_engine/loci.py. " +
                    "Do not read this world's numbers as model results.",
                    MessageType.Warning);
            }

            EditorGUILayout.Space();
            EditorGUILayout.LabelField("Contents", EditorStyles.boldLabel);
            Row("People (ever lived)", _bundle.People.Count.ToString());
            Row("History years", _bundle.History.Count.ToString());
            Row("Retained frames", _bundle.Ticks.Length.ToString());
            Row("Frame range",
                _bundle.Ticks.Length > 0
                    ? $"year {_bundle.FirstTick} … {_bundle.LastTick}"
                    : "none");
            Row("Events", _bundle.Events.Count.ToString());

            if (m.Frames.Truncated)
            {
                EditorGUILayout.HelpBox(
                    $"frames.csv is TRUNCATED. The engine retains at most " +
                    $"{m.Frames.MaxFrames} yearly frames, so this bundle begins " +
                    $"at year {_bundle.FirstTick}, not 0. Label any timeline " +
                    $"from {_bundle.FirstTick}.", MessageType.Warning);
            }

            EditorGUILayout.Space();
            EditorGUILayout.LabelField("Caveats from the engine",
                EditorStyles.boldLabel);
            foreach (string c in m.Caveats)
            {
                EditorGUILayout.LabelField("• " + c, EditorStyles.wordWrappedMiniLabel);
            }

            EditorGUILayout.EndScrollView();
        }

        private static void Row(string label, string value)
        {
            using (new EditorGUILayout.HorizontalScope())
            {
                EditorGUILayout.LabelField(label, GUILayout.Width(150));
                EditorGUILayout.SelectableLabel(value ?? "—",
                    GUILayout.Height(EditorGUIUtility.singleLineHeight));
            }
        }

        private void LoadBundle()
        {
            _error = null;
            _bundle = null;
            try
            {
                _bundle = WorldBundle.Load(_path);
            }
            catch (BundleFormatException e)
            {
                _error = e.Message;
            }
            catch (IOException e)
            {
                _error = "I/O error: " + e.Message;
            }
        }
    }
}
