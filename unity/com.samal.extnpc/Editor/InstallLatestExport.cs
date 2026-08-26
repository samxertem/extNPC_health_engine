using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using Debug = UnityEngine.Debug;

namespace ExtNPC.Editor
{
    /// <summary>
    /// The last-mile step `install_to_unity.py`'s own docstring says nothing
    /// can do for you automatically: find the newest export, copy it in, and
    /// point the scene's loader at it.
    ///
    /// WHY THIS IS SAFE TO DO FROM INSIDE A RUNNING EDITOR WHEN THE SCRIPT'S
    /// OWN DOCSTRING WARNS AGAINST IT. `install_to_unity.py` warns that
    /// `worldName` is a serialised field on a GameObject and writing to the
    /// `.unity` file behind a running editor risks the editor's unsaved
    /// state. That warning is about editing the FILE on disk. This sets the
    /// field through the live GameObject, the same as dragging a value in
    /// the Inspector, so there is no file underneath the editor to fight.
    /// </summary>
    public static class InstallLatestExport
    {
        [MenuItem("Tools/extNPC/Install Latest Export", false, 1)]
        public static void Run()
        {
            // NO HARDCODED HOME PATH. This file ships inside the package, so
            // a literal `C:\Users\<someone>\...` fallback would bake one
            // machine's layout into everybody's copy. The env var is the
            // supported answer; the Desktop guess below is a convenience for
            // the common local layout and is allowed to miss.
            string repo = Environment.GetEnvironmentVariable("EXTNPC_REPO");
            if (string.IsNullOrEmpty(repo))
            {
                repo = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
                    "extNPC_health_engine");
            }
            if (!Directory.Exists(repo))
            {
                Debug.LogError($"[extNPC] engine repo not found at '{repo}'. Set the " +
                                "EXTNPC_REPO environment variable to the repo's root " +
                                "(the folder holding install_to_unity.py) and try again.");
                return;
            }

            string exportsDir = Path.Combine(repo, "outputs", "unity");
            if (!Directory.Exists(exportsDir))
            {
                Debug.LogError($"[extNPC] no exports at '{exportsDir}'. Run the " +
                                "dashboard's Controls tab -> Export for Unity first.");
                return;
            }

            var bundle = new DirectoryInfo(exportsDir)
                .GetDirectories()
                .Where(d => File.Exists(Path.Combine(d.FullName, "manifest.json")))
                .OrderByDescending(d => d.LastWriteTimeUtc)
                .FirstOrDefault();
            if (bundle == null)
            {
                Debug.LogError($"[extNPC] '{exportsDir}' has no exported bundle " +
                                "(a folder with manifest.json in it). Export a " +
                                "world first.");
                return;
            }

            // This project, not whatever install_to_unity.py's own default or
            // EXTNPC_UNITY_PROJECT would pick -- the whole point of running
            // this from inside the editor is that "which project" is already
            // answered by which editor it is.
            string thisProject = Directory.GetParent(Application.dataPath).FullName;

            Debug.Log($"[extNPC] installing '{bundle.Name}' into {thisProject} ...");
            var psi = new ProcessStartInfo("python",
                $"install_to_unity.py \"{bundle.FullName}\" --project \"{thisProject}\"")
            {
                WorkingDirectory = repo,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
            };

            string stdout, stderr;
            int exitCode;
            try
            {
                using var proc = Process.Start(psi);
                stdout = proc.StandardOutput.ReadToEnd();
                stderr = proc.StandardError.ReadToEnd();
                proc.WaitForExit();
                exitCode = proc.ExitCode;
            }
            catch (Exception e)
            {
                Debug.LogError($"[extNPC] could not run install_to_unity.py: {e.Message} " +
                                "(is 'python' on PATH?)");
                return;
            }

            if (!string.IsNullOrWhiteSpace(stdout)) Debug.Log("[extNPC install]\n" + stdout);
            if (exitCode != 0)
            {
                Debug.LogError($"[extNPC] install_to_unity.py exited {exitCode}:\n{stderr}");
                return;
            }

            AssetDatabase.Refresh();

            var loader = UnityEngine.Object.FindFirstObjectByType<ExtNpcWorldLoader>();
            if (loader == null)
            {
                Debug.LogWarning("[extNPC] installed, but no ExtNpcWorldLoader is in the " +
                                  "open scene (GameObject > extNPC > World Viewer creates " +
                                  "one). Set its World Name to '" + bundle.Name +
                                  "' once it exists.");
                return;
            }

            Undo.RecordObject(loader, "Point loader at latest export");
            loader.worldName = bundle.Name;
            loader.absolutePathOverride = "";
            EditorUtility.SetDirty(loader);

            Debug.Log($"[extNPC] '{bundle.Name}' installed and the scene's loader now " +
                       "points at it. Press Play.");
        }
    }
}
