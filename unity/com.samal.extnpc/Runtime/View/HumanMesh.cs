using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// The optional shared human body, and the trap that makes loading one
    /// harder than it looks.
    ///
    /// Stage 6's last item is "replace capsules with one shared human mesh".
    /// The package still ships NO assets, because that is what lets
    /// Editor/SceneSetup.cs build a working viewer from an empty scene, and
    /// because MPFB's output is a build-time artifact that lives outside this
    /// repository. So the body is looked up at run time and its absence is a
    /// supported state: with no asset present every villager stays a capsule
    /// and nothing else changes.
    ///
    /// Drop an MPFB export at <c>Assets/Resources/extnpc/human_female</c> and
    /// <c>.../human_male</c> (or a single <c>.../human</c> for both) and the
    /// village becomes people. <c>mpfb/export_bodies.py</c> in the engine repo
    /// produces exactly those files.
    ///
    /// THE TRAP, measured rather than assumed (session 22). You cannot take
    /// the <c>Mesh</c> off an imported FBX and use it directly. Unity leaves
    /// the mesh datablock in the FBX's own CENTIMETRE, Z-UP space and puts the
    /// correction on the imported hierarchy's TRANSFORM. A 1.7546 m character's
    /// mesh reports <c>bounds.size = (0.0114, 0.0048, 0.0175)</c>, so a naive
    /// <c>meshFilter.sharedMesh = model.GetComponentInChildren&lt;MeshFilter&gt;()
    /// .sharedMesh</c> yields a 1.7 cm body lying on its side. This class bakes
    /// the hierarchy transform into the vertices once, which is also why every
    /// villager can stay a cheap MeshFilter instead of becoming a
    /// SkinnedMeshRenderer with 53 bones.
    ///
    /// WHAT IS NORMALISED AND WHY. The baked mesh is translated so the soles
    /// sit at y=0 and scaled so it is exactly 1 m tall, so
    /// <see cref="VillagerView"/> can scale by <c>height_cm/100</c> and get a
    /// body whose measured stature is the exported stature. That keeps Stage 3's
    /// property intact: what the inspector prints and what the ruler measures
    /// are the same number.
    /// </summary>
    public static class HumanMesh
    {
        /// <summary>Where a consuming project may drop the bodies.</summary>
        public const string ResourcePathFemale = "extnpc/human_female";
        public const string ResourcePathMale = "extnpc/human_male";
        public const string ResourcePathShared = "extnpc/human";

        private static bool _searched;
        private static Mesh _female, _male;
        private static float _femaleAuthoredM, _maleAuthoredM;

        /// <summary>
        /// A 1 m tall body standing on y=0, or null when no asset is installed.
        /// </summary>
        public static Mesh UnitBody(bool female)
        {
            EnsureSearched();
            return female ? _female : _male;
        }

        /// <summary>
        /// The stature the source FBX was authored at, in metres, or 0 when no
        /// asset is installed. Reported rather than used: it is the number a
        /// scale check compares against, and it is the only evidence that the
        /// centimetre/Z-up correction above actually happened.
        /// </summary>
        public static float AuthoredStature(bool female)
        {
            EnsureSearched();
            return female ? _femaleAuthoredM : _maleAuthoredM;
        }

        /// <summary>True when at least one body is installed.</summary>
        public static bool Available
        {
            get { EnsureSearched(); return _female != null || _male != null; }
        }

        /// <summary>
        /// Forget what was found, so a newly imported asset is picked up.
        /// Called by the editor's scene setup; harmless at run time.
        /// </summary>
        public static void Forget()
        {
            _searched = false;
            _female = _male = null;
            _femaleAuthoredM = _maleAuthoredM = 0f;
        }

        private static void EnsureSearched()
        {
            if (_searched) return;
            _searched = true;

            var shared = Resources.Load<GameObject>(ResourcePathShared);
            var femaleModel = Resources.Load<GameObject>(ResourcePathFemale) ?? shared;
            var maleModel = Resources.Load<GameObject>(ResourcePathMale) ?? shared;

            // Same model for both is the documented "everyone identical" case
            // UNITY_PLAN.md Stage 6 asks for; bake it once and share it.
            if (femaleModel != null && femaleModel == maleModel)
            {
                _female = _male = Bake(femaleModel, out _femaleAuthoredM);
                _maleAuthoredM = _femaleAuthoredM;
                return;
            }
            if (femaleModel != null) _female = Bake(femaleModel, out _femaleAuthoredM);
            if (maleModel != null) _male = Bake(maleModel, out _maleAuthoredM);
        }

        /// <summary>
        /// Flatten an imported model hierarchy into one mesh, in metres, Y-up,
        /// soles on y=0, exactly 1 m tall and centred in x/z.
        /// </summary>
        /// <param name="authoredStatureM">
        /// The height the model had before normalisation. 0 if nothing usable
        /// was found.
        /// </param>
        internal static Mesh Bake(GameObject model, out float authoredStatureM)
        {
            return Bake(model, 0f, out authoredStatureM);
        }

        /// <summary>
        /// Flatten and normalise, dividing by a stature the caller already
        /// knows. See <see cref="Normalise(Mesh, float, out float, out float)"/>
        /// for why a body carrying hair cannot measure itself.
        /// </summary>
        internal static Mesh Bake(GameObject model, float bodyStatureM,
                                  out float authoredStatureM)
        {
            authoredStatureM = 0f;
            if (model == null) return null;

            var combines = new System.Collections.Generic.List<CombineInstance>();
            Matrix4x4 rootInverse = model.transform.worldToLocalMatrix;

            foreach (var skinned in model.GetComponentsInChildren<SkinnedMeshRenderer>(true))
            {
                if (skinned.sharedMesh == null) continue;
                if (!Readable(skinned.sharedMesh, model)) return null;
                combines.Add(new CombineInstance
                {
                    mesh = skinned.sharedMesh,
                    transform = rootInverse * skinned.transform.localToWorldMatrix,
                });
            }
            foreach (var filter in model.GetComponentsInChildren<MeshFilter>(true))
            {
                if (filter.sharedMesh == null) continue;
                if (!Readable(filter.sharedMesh, model)) return null;
                combines.Add(new CombineInstance
                {
                    mesh = filter.sharedMesh,
                    transform = rootInverse * filter.transform.localToWorldMatrix,
                });
            }

            if (combines.Count == 0)
            {
                Debug.LogWarning($"[extNPC] '{model.name}' has no mesh to bake; " +
                                 "villagers stay primitives.");
                return null;
            }

            var baked = new Mesh { name = "extNPC/" + model.name };
            // 32-bit indices: an MPFB body is ~14.5k vertices before any
            // clothing, and a shared model plus assets can pass 65k.
            baked.indexFormat = UnityEngine.Rendering.IndexFormat.UInt32;
            baked.CombineMeshes(combines.ToArray(), true, true, false);

            float combinedExtentM;
            Normalise(baked, bodyStatureM, out authoredStatureM,
                      out combinedExtentM);
            baked.RecalculateBounds();

            // A combine that failed still returns a Mesh, just an empty one,
            // and an empty mesh on a villager is INVISIBLE rather than wrong:
            // present in the hierarchy, counted by the headcount check,
            // selectable, and not there. Capsules are a far better failure.
            if (baked.vertexCount == 0)
            {
                Debug.LogError($"[extNPC] '{model.name}' baked to an empty mesh; " +
                               "villagers fall back to primitives. See the console " +
                               "above for what Unity refused.");
                authoredStatureM = 0f;
                return null;
            }
            return baked;
        }

        /// <summary>
        /// Refuse to combine a mesh whose CPU copy Unity has thrown away.
        ///
        /// Unity imports models with <c>isReadable = false</c>, uploads them and
        /// drops the CPU copy. <c>Mesh.CombineMeshes</c> then logs "Cannot
        /// combine mesh that does not allow access" and hands back an EMPTY
        /// mesh, which is the invisible-villager failure above.
        ///
        /// <c>ExtNpcModelPostprocessor</c> sets the flag on import so this
        /// should never fire. It is here because when it did fire, the symptom
        /// was a village that loaded, counted correctly, logged
        /// "69 villagers drawn" and showed nothing, and the only clue was a
        /// warning three screens up the console.
        /// </summary>
        private static bool Readable(Mesh mesh, GameObject model)
        {
            if (mesh.isReadable) return true;
            Debug.LogError(
                $"[extNPC] '{model.name}' has Read/Write disabled, so its mesh " +
                "cannot be baked and villagers stay primitives. Tick Read/Write " +
                "on the model importer, or reimport it now that the package's " +
                "ExtNpcModelPostprocessor is present (right-click the asset, " +
                "Reimport).");
            return false;
        }

        /// <summary>
        /// Translate to soles-on-origin and scale to unit height, in place.
        /// Separated from <see cref="Bake"/> so the arithmetic is reachable
        /// from a test without an FBX.
        /// </summary>
        internal static void Normalise(Mesh mesh, out float authoredStatureM)
        {
            float ignored;
            Normalise(mesh, 0f, out authoredStatureM, out ignored);
        }

        /// <summary>
        /// Normalise, dividing by a stature the caller already knows.
        ///
        /// WHY THE CALLER HAS TO TELL US. This scales by the BODY's height, and
        /// once the FBX carries hair or clothes the mesh in front of us is no
        /// longer only a body. Hair sits above the crown, so the combined
        /// y-extent is taller than the person is, and dividing by it would
        /// shrink the body until hair-tip-to-sole measured 1 m. Every villager
        /// would then lose height according to their HAIRSTYLE, which
        /// <see cref="ExtNPC"/>'s cosmetic layer picks from their NAME: a
        /// deliberately non-genetic channel would be modulating the
        /// best-predicted trait in the model, and the village would still look
        /// entirely plausible.
        ///
        /// Blender measures the basemesh alone during the bake and records it
        /// per villager in `bodies.json`, so the number exists and is not
        /// guessable from here. Passing 0 keeps the old behaviour -- measure
        /// the whole mesh -- which is correct for the shared bodies, which have
        /// no manifest entry and carry no assets.
        ///
        /// SOLES, NOT HEELS. The origin still comes from the combined mesh's
        /// lowest point, so shoes land on the ground rather than sinking into
        /// it. The divisor and the origin answer two different questions on
        /// purpose: `height_cm` is barefoot stature, so the BODY is what must
        /// measure it, while what touches the floor is whatever is lowest.
        /// </summary>
        /// <param name="bodyStatureM">
        /// The body's own height in metres, or 0 to measure the whole mesh.
        /// </param>
        /// <param name="authoredStatureM">The divisor actually used.</param>
        /// <param name="combinedExtentM">
        /// The whole mesh's y-extent before scaling. Equal to
        /// <paramref name="authoredStatureM"/> for a bare body and larger when
        /// assets stick out past it; SMALLER is impossible, because the body is
        /// part of the mesh being measured, and is reported as an error rather
        /// than quietly used.
        /// </param>
        internal static void Normalise(Mesh mesh, float bodyStatureM,
                                       out float authoredStatureM,
                                       out float combinedExtentM)
        {
            Vector3[] vertices = mesh.vertices;
            authoredStatureM = 0f;
            combinedExtentM = 0f;
            if (vertices.Length == 0) return;

            Vector3 lo = vertices[0], hi = vertices[0];
            for (int i = 1; i < vertices.Length; i++)
            {
                lo = Vector3.Min(lo, vertices[i]);
                hi = Vector3.Max(hi, vertices[i]);
            }

            combinedExtentM = hi.y - lo.y;
            float stature = combinedExtentM;

            if (bodyStatureM > 0f)
            {
                // The body cannot be taller than a mesh it is part of. If it
                // reads that way the manifest belongs to a different bake, and
                // trusting it would scale every villager by a wrong constant --
                // the exact failure this parameter exists to prevent, arriving
                // through the fix instead of through the defect.
                if (combinedExtentM > 0f &&
                    bodyStatureM > combinedExtentM * 1.001f)
                {
                    Debug.LogError(
                        "[extNPC] bodies.json says this body is " +
                        bodyStatureM.ToString("0.0000") + " m but its mesh is only " +
                        combinedExtentM.ToString("0.0000") + " m tall, which is " +
                        "impossible. The manifest and the FBX are from different " +
                        "bakes; re-run the bake, or re-install both together. " +
                        "Falling back to measuring the mesh, so this villager's " +
                        "height is whatever the FBX says rather than what the " +
                        "engine says.");
                }
                else
                {
                    stature = bodyStatureM;
                }
            }

            authoredStatureM = stature;
            if (stature <= 0f) return;

            float inv = 1f / stature;
            // x/z centred on the body's own midline, y measured from the soles.
            var origin = new Vector3((lo.x + hi.x) * 0.5f, lo.y, (lo.z + hi.z) * 0.5f);
            for (int i = 0; i < vertices.Length; i++)
            {
                vertices[i] = (vertices[i] - origin) * inv;
            }
            mesh.vertices = vertices;
        }

        /// <summary>
        /// Where the eyes are, as a fraction of stature measured from the
        /// soles. Used only to aim the portrait camera.
        ///
        /// NOT engine data and not pretending to be. 0.935 is the standard
        /// anthropometric eye-height ratio for an adult, it is a CONSTANT for
        /// every villager, and the engine models stature alone: there is no
        /// per-person eye height to read. Same decision, and same reasoning, as
        /// <see cref="VillagerView.BodyWidthM"/>.
        /// </summary>
        public const float EyeHeightFraction = 0.935f;
    }
}
