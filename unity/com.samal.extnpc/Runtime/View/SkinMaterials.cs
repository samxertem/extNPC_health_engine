using System.Collections.Generic;
using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// Skin as a TEXTURED surface whose TONE is still the engine's number.
    ///
    /// WHY SKIN NEEDED THIS AND WHY IT IS NOT THE EYE FIX AGAIN. The eyes
    /// were textured because an eyeball is not one colour, and painting the
    /// submesh with `eye_color` painted the sclera the colour of the iris.
    /// Skin fails differently: a flat tone is the right AVERAGE and the wrong
    /// SURFACE. Lips, nail beds, the shading under a brow, the darkening
    /// where a limb folds -- none of it exists in one colour, and a face
    /// rendered flat is the strongest remaining "not a person" signal left in
    /// the viewer.
    ///
    /// THE CONSTRAINT. `skin` is a MEASURED channel. `bodies.json` records it
    /// as "measured: skin_tone on the Del Bino skin locus, ITA per Chardon
    /// 1991", and the viewer's standing property is that what the inspector
    /// prints is what the screen shows. A MakeHuman skin has an artist's tone
    /// baked into it, so using one as authored would replace the engine's
    /// measured colour with somebody else's -- the flat-colour bug arriving
    /// from the opposite direction, and a quieter defect than the one it
    /// replaced.
    ///
    /// SO THE TEXTURE CARRIES NO TONE. `install_to_unity.py` reduces each
    /// source skin to its linear-light luminance, divides by the median of
    /// that luminance and clamps, which leaves the RATIO of every pixel to
    /// flat skin and nothing else. URP's Lit shader computes
    /// `_BaseMap * _BaseColor`, and <see cref="VillagerView"/> puts the
    /// engine's colour in `_BaseColor` through a property block, so the
    /// engine still decides the tone and the texture only darkens where real
    /// skin darkens.
    ///
    /// WHAT THAT COSTS, MEASURED. The median pixel is 1.0 by construction, so
    /// the commonest patch of skin renders at exactly the engine's colour.
    /// The mean lands below 1.0, so an average patch renders slightly darker;
    /// the six installed maps measure 0.860 to 0.925, and the installer
    /// refuses any map below 0.85 rather than shipping one that would move a
    /// villager's measured skin colour. The numbers are written to
    /// `skins.json` beside the textures.
    ///
    /// COST ON SCREEN. One material per (age band, sex), so SIX for a village
    /// of any size, exactly as the eyes are three for any village.
    /// </summary>
    public static class SkinMaterials
    {
        /// <summary>Where `install_to_unity.py` puts the detail maps.</summary>
        public const string ResourceFolder = "extnpc/skin";

        /// <summary>
        /// MakeHuman's own three age bands, and the ages it switches at.
        ///
        /// Mirrors `install_to_unity.skin_band_for_age`, and the two are
        /// pinned equal by a test rather than shared through a file: this
        /// side has to resolve a band with no Python in the process, which is
        /// the same reason <see cref="EyeMaterials.FallbackLabel"/> restates
        /// the engine's fallback instead of importing it.
        /// </summary>
        public static string BandForAge(float ageYears)
        {
            if (ageYears >= 65f) return "old";
            if (ageYears >= 45f) return "middleage";
            return "young";
        }

        private static readonly Dictionary<string, Material> _byKey =
            new Dictionary<string, Material>();

        /// <summary>Keys whose map is not installed, remembered so a missing
        /// file costs one failed Resources.Load and not one per villager per
        /// frame. Same reasoning as <see cref="EyeMaterials"/>.</summary>
        private static readonly HashSet<string> _absent = new HashSet<string>();

        private static bool _warned;

        /// <summary>
        /// The shared skin material for one villager's age and sex, or null
        /// when no map is installed for it.
        ///
        /// Null is a supported state and not an error: the package ships no
        /// assets, so a project that never ran `install_to_unity.py` has no
        /// skin maps and the caller then draws skin as the flat tone it drew
        /// before. Degrading to the old look is right; drawing an untextured
        /// body in a material that expects a texture is not.
        /// </summary>
        public static Material For(float ageYears, bool female)
        {
            return For(BandForAge(ageYears), female ? "female" : "male");
        }

        /// <summary>The band-and-sex form, for callers that already have both
        /// and for the tests.</summary>
        public static Material For(string band, string sex)
        {
            if (string.IsNullOrEmpty(band) || string.IsNullOrEmpty(sex))
                return null;
            string key = band.ToLowerInvariant() + "_" + sex.ToLowerInvariant();

            Material cached;
            if (_byKey.TryGetValue(key, out cached)) return cached;
            if (_absent.Contains(key)) return null;

            var texture = Resources.Load<Texture2D>(ResourceFolder + "/" + key);
            if (texture == null)
            {
                _absent.Add(key);
                if (!_warned)
                {
                    _warned = true;
                    Debug.Log("[extNPC] no skin detail maps under Resources/" +
                              ResourceFolder + "; skin stays a flat tone. " +
                              "`python install_to_unity.py <bundle>` writes them.");
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

            var material = new Material(shader) { name = "extNPC/Skin " + key };
            // Both names: URP's Lit calls it _BaseMap, the built-in Standard
            // calls it _MainTex, and the package works under either.
            material.SetTexture("_BaseMap", texture);
            material.SetTexture("_MainTex", texture);
            // WHITE, and this is the load-bearing line. The material must not
            // hold a tone of its own, because the tone arrives per submesh
            // from the property block carrying the engine's measured colour.
            // A tint here would be a second definition of skin colour, which
            // is the thing this whole class exists to avoid.
            material.SetColor("_BaseColor", Color.white);
            material.SetColor("_Color", Color.white);
            BodyMaterials.ApplySurface(material, BodyMaterials.SkinSmoothness);
            _byKey[key] = material;
            return material;
        }

        /// <summary>Drop every cached material, so a reinstalled texture set is
        /// picked up without restarting the editor. Mirrors
        /// <see cref="EyeMaterials.Forget"/> and exists for the same reason:
        /// a cached negative result looks exactly like a broken install.</summary>
        public static void Forget()
        {
            _byKey.Clear();
            _absent.Clear();
            _warned = false;
        }
    }
}
