using UnityEditor;
using UnityEngine;

namespace ExtNPC.Editor
{
    /// <summary>
    /// Make extNPC body models readable on import.
    ///
    /// WHY THIS EXISTS, and it is not a convenience. Unity imports a model with
    /// <c>isReadable = false</c> by default: the mesh is uploaded to the GPU and
    /// the CPU copy is dropped. <see cref="ExtNPC.View.HumanMesh"/> has to read
    /// the vertices, because an imported FBX's mesh datablock is in the FBX's
    /// own centimetre Z-up space and the correction lives on the hierarchy
    /// transform, so the transform must be folded into the vertices before the
    /// mesh can be used.
    ///
    /// Without this, <c>Mesh.CombineMeshes</c> logs
    ///
    ///     Cannot combine mesh that does not allow access: Human_body
    ///
    /// and returns an EMPTY mesh. Every villager then gets a body with no
    /// geometry: present in the hierarchy, counted by the headcount check,
    /// selectable, and completely invisible. That is worse than falling back
    /// to capsules, and it is what shipped before this file existed.
    ///
    /// THE PART THAT MADE IT HARD TO CATCH. In a batch <c>-executeMethod</c>
    /// run the same call SUCCEEDS, because nothing has uploaded and discarded
    /// the mesh yet, so the CPU copy is still there. The body pipeline was
    /// verified that way and passed, reporting 14,517 vertices and an exact
    /// stature, while the identical code in Play mode produced nothing. A
    /// check that only runs before the first frame cannot see this.
    ///
    /// Scoped to Resources/extnpc/ rather than applied to every model in the
    /// project: making an unrelated 100k-vertex asset readable doubles its
    /// memory for no reason, and a package has no business doing that to a
    /// consumer's assets.
    /// </summary>
    public sealed class ExtNpcModelPostprocessor : AssetPostprocessor
    {
        /// <summary>Folder, in Unity's forward-slash asset-path form.</summary>
        public const string BodyFolder = "Resources/extnpc/";

        public static bool IsBodyAsset(string assetPath) =>
            !string.IsNullOrEmpty(assetPath) &&
            // DirectorySeparatorChar rather than a literal
            // backslash: Unity hands asset paths with forward
            // slashes already, and a backslash literal here is
            // one escaping mistake from a compile error.
            assetPath.Replace(System.IO.Path.DirectorySeparatorChar, '/')
                     .Contains(BodyFolder);

        private void OnPreprocessModel()
        {
            if (!IsBodyAsset(assetPath)) return;

            var importer = (ModelImporter)assetImporter;
            if (importer.isReadable) return;

            importer.isReadable = true;
            Debug.Log($"[extNPC] {System.IO.Path.GetFileName(assetPath)}: " +
                      "Read/Write enabled, which HumanMesh needs to fold the " +
                      "FBX's centimetre Z-up transform into the vertices.");
        }

        /// <summary>
        /// Catch bodies that arrive by being MOVED rather than imported.
        ///
        /// <see cref="OnPreprocessModel"/> only ever sees an asset Unity is
        /// importing, and a move is not an import: the .meta travels with the
        /// file, so an FBX first imported anywhere outside
        /// <see cref="BodyFolder"/> keeps <c>isReadable = false</c> for ever
        /// once it is dragged in.
        ///
        /// THE ROUTE THAT MADE THIS REAL, because it is not hypothetical and
        /// it is not a user doing something odd. The village screenshot
        /// harness (`mpfb/unity_village.py`) takes its A/B pair by moving
        /// <c>Assets/Resources/extnpc/</c> aside and back. Any body added
        /// between the two passes is therefore imported while it sits at
        /// <c>Assets/_parked_extnpc/</c>, where this postprocessor correctly
        /// ignores it, and is then moved into place already unreadable. The
        /// symptom is the one the class docstring warns about: a village that
        /// loads, counts and logs correctly and draws primitives.
        /// </summary>
        private static void OnPostprocessAllAssets(
            string[] imported, string[] deleted, string[] moved, string[] movedFrom)
        {
            if (moved == null) return;

            foreach (string path in moved)
            {
                if (!IsBodyAsset(path)) continue;

                var importer = AssetImporter.GetAtPath(path) as ModelImporter;
                if (importer == null || importer.isReadable) continue;

                importer.isReadable = true;
                importer.SaveAndReimport();
                Debug.Log($"[extNPC] {System.IO.Path.GetFileName(path)} was moved " +
                          "into the body folder already unreadable; Read/Write " +
                          "enabled and reimported.");
            }
        }
    }
}
