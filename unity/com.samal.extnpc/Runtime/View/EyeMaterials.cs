using System.Collections.Generic;
using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// The one part of a villager drawn from a TEXTURE rather than a flat
    /// tone, and the measurement that forced it.
    ///
    /// WHY EYES ARE THE EXCEPTION. Every other channel -- skin, hair, teeth,
    /// clothes -- is one flat colour on one shared material, which is what
    /// keeps 600 villagers inside the frame budget and is a deliberate
    /// choice, not a shortcut. It fails for exactly one part: an eyeball is
    /// not one colour. Painting the whole eye submesh with `eye_color` paints
    /// the SCLERA the colour of the iris, so the eye reads as a coloured ball
    /// rather than as an eye. That was the reported defect.
    ///
    /// WHY MAKEHUMAN'S OWN TEXTURE AND NOT A GENERATED MASK. The first
    /// attempt generated an iris/pupil/sclera mask procedurally and tinted
    /// it, assuming the eye mesh's UVs ran radially out from the middle of
    /// the square. MEASURED, they do not: MakeHuman's low-poly eye mesh maps
    /// BOTH eyeballs diagonally across one 1024x1024 sheet, so UV (0.5, 0.5)
    /// is the empty grey gap BETWEEN the two eyeballs and the visible front
    /// of each eye lands nowhere near the middle. The generated mask put the
    /// black pupil region over the whole visible surface and the villagers
    /// ended up with dark empty sockets -- worse than the flat colour it
    /// replaced. The textures MakeHuman ships are already UV-matched to this
    /// exact mesh, so using them removes the assumption rather than
    /// correcting it.
    ///
    /// LICENCE. These are the CC0 `makehuman_system_assets` textures the
    /// asset pack already installs (item A2), so they travel as freely as
    /// the rest of the pack's output. See MPFB_UNITY_INVESTIGATION.md.
    ///
    /// COST. One material and one texture PER LABEL, not per villager --
    /// three of each for the engine's three `eye_color` categories -- so a
    /// village of any size still shares them.
    /// </summary>
    public static class EyeMaterials
    {
        /// <summary>Where `install_to_unity.py` puts the textures.</summary>
        public const string ResourceFolder = "extnpc/eyes";

        /// <summary>Mirrors `appearance_color.eye_color`, which falls back to
        /// hazel for an unknown label rather than raising, "because a
        /// villager with no eyes is a worse failure than a villager with the
        /// middle colour". The same fallback has to live here or the viewer
        /// and the dashboard would disagree about an unknown label, which is
        /// the thing UNITY_PLAN.md invariant 6 forbids.</summary>
        public const string FallbackLabel = "hazel";

        private static readonly Dictionary<string, Material> _byLabel =
            new Dictionary<string, Material>();

        /// <summary>Labels whose texture is not installed, remembered so a
        /// missing file costs one failed Resources.Load and not one per
        /// villager per frame.</summary>
        private static readonly HashSet<string> _absent = new HashSet<string>();

        private static bool _warned;

        /// <summary>
        /// The shared material for one `eye_color` label, or null when no
        /// texture is installed for it.
        ///
        /// Null is a supported state and not an error: the package ships no
        /// assets, so a project that never ran `install_to_unity.py` has no
        /// eye textures, and the caller then leaves the eyes as the flat tone
        /// they were before. Degrading to the old look is right; drawing a
        /// white or magenta eyeball is not.
        /// </summary>
        public static Material For(string label)
        {
            string key = string.IsNullOrEmpty(label)
                ? FallbackLabel : label.ToLowerInvariant();

            Material cached;
            if (_byLabel.TryGetValue(key, out cached)) return cached;
            if (_absent.Contains(key)) return null;

            var texture = Resources.Load<Texture2D>(ResourceFolder + "/" + key);
            if (texture == null && key != FallbackLabel)
            {
                // An unmapped label falls back before it gives up, so a new
                // engine category renders as eyes rather than as nothing.
                _absent.Add(key);
                return For(FallbackLabel);
            }
            if (texture == null)
            {
                _absent.Add(key);
                if (!_warned)
                {
                    _warned = true;
                    Debug.Log("[extNPC] no eye textures under Resources/" +
                              ResourceFolder + "; eyes stay a flat tone. " +
                              "`python install_to_unity.py <bundle>` copies them.");
                }
                return null;
            }

            Shader shader = Shader.Find("Universal Render Pipeline/Lit")
                            ?? Shader.Find("Standard");
            if (shader == null)
            {
                _absent.Add(key);
                return null;
            }

            var material = new Material(shader) { name = "extNPC/Eye " + key };
            // Both names, for the same reason VillagerView sets both colour
            // names: URP's Lit calls it _BaseMap, the built-in Standard
            // calls it _MainTex, and the package works under either.
            material.SetTexture("_BaseMap", texture);
            material.SetTexture("_MainTex", texture);
            // White base, so the texture is what is seen. The eye is the one
            // channel whose colour is IN the texture rather than applied to
            // it, and a tint here would be a second definition of it.
            material.SetColor("_BaseColor", Color.white);
            material.SetColor("_Color", Color.white);
            // Eyes are wet and the rest of the body is not, but a specular
            // highlight is a rendering flourish rather than anything the
            // engine measured, so smoothness stays at the body's own value.
            _byLabel[key] = material;
            return material;
        }

        /// <summary>Drop every cached material, so a reinstalled texture set
        /// is picked up without restarting the editor. Mirrors
        /// <see cref="HumanMesh.Forget"/>, and exists for the same reason:
        /// a cached negative result looks exactly like a broken install.</summary>
        public static void Forget()
        {
            _byLabel.Clear();
            _absent.Clear();
            _warned = false;
        }
    }
}
