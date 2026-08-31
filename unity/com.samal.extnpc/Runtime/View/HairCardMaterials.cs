using System.Collections.Generic;
using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// Eyebrows and eyelashes, whose SHAPE lives in a texture's alpha channel
    /// rather than in their geometry.
    ///
    /// THE DEFECT, AND HOW IT WAS FOUND. Giving brows and lashes the
    /// villager's own `hair_pigment` was correct, and the first thing anyone
    /// said on seeing it was that the villagers looked like they were wearing
    /// mascara. They were. MakeHuman's brow and lash meshes are flat CARDS,
    /// and the individual hairs are cut out of them by the alpha channel of
    /// the texture that belongs to them. Painting a card with a flat opaque
    /// colour paints the whole rectangle.
    ///
    /// MEASURED on the assets these bundles use: 18.0 percent of
    /// `eyelashes02` is opaque, 7.7 percent of `eyebrow001`, 11.8 percent of
    /// `eyebrow003`. Between 82 and 92 percent of what was on screen should
    /// not have been drawn at all, which is five to thirteen times too much
    /// dark area around each eye. It had been that way the whole time and was
    /// invisible only because the cards were painted skin-coloured, so they
    /// disappeared into the face.
    ///
    /// THE THIRD TIME FOR THIS LESSON. The eyes needed MakeHuman's own
    /// texture because an eyeball is not one colour. The skin needed one
    /// because skin is not one colour. Brows need one because a brow is not
    /// one SHAPE. In each case the mesh is a carrier and the texture is the
    /// content, and in each case the fix was to use the asset the pack
    /// already ships instead of inferring what was missing.
    ///
    /// ALPHA CLIP RATHER THAN ALPHA BLEND. Cutout sorts correctly with no
    /// per-object ordering, costs nothing extra, and casts a real shadow.
    /// Blending several overlapping lash cards would need sorting that a
    /// crowd of 600 will not reliably get. Measured, it loses very little
    /// here: the alpha in these textures is nearly binary already, with a
    /// mean of 0.156 against an opaque-above-half fraction of 0.158.
    ///
    /// THE TEXTURE IS PURE SHAPE. `install_to_unity.py` replaces the RGB with
    /// white and keeps the alpha exactly, because the opaque pixels of the
    /// source average RGB (3, 1, 0): they are black and carry no colour worth
    /// keeping. Multiplying black by a villager's hair colour would give
    /// black whatever their hair does. White leaves `hair_pigment` free to
    /// colour the shape.
    ///
    /// SCALP HAIR IS NOT DRAWN THIS WAY AND THAT IS DELIBERATE. Measured at
    /// 38 to 100 percent coverage (`braid01` is a solid mesh with no cutout
    /// at all), so hair reads correctly as a volume; and `bob02`'s texture is
    /// a light blonde whose colour would be double-counted against the tint.
    /// Nothing installs a card for a hair asset, so hair falls through to the
    /// flat tint it already had.
    /// </summary>
    public static class HairCardMaterials
    {
        /// <summary>Where `install_to_unity.py` puts the cutouts, named by
        /// the bake's own source mesh name.</summary>
        public const string ResourceFolder = "extnpc/haircards";

        /// <summary>
        /// Where a pixel stops counting as hair.
        ///
        /// The alpha in these textures is close to binary, so anything from
        /// about 0.2 to 0.6 gives nearly the same picture. 0.35 sits below
        /// the middle on purpose: it keeps the softer pixels at the tip of
        /// each strand, which is where a lash tapers, and losing those is
        /// what makes a cutout look cut rather than grown.
        /// </summary>
        public const float AlphaCutoff = 0.35f;

        private static readonly Dictionary<string, Material> _byAsset =
            new Dictionary<string, Material>();

        /// <summary>Assets with no card installed, remembered so a miss costs
        /// one failed Resources.Load rather than one per villager per frame.
        /// Same reasoning as <see cref="EyeMaterials"/>.</summary>
        private static readonly HashSet<string> _absent = new HashSet<string>();

        private static bool _warned;

        /// <summary>
        /// Is there a cutout for this asset?
        ///
        /// GATES THE COLOUR, not just the material, and that is the point.
        /// A dark brow colour is only correct on a card that has its alpha:
        /// without one, the flat dark rectangle is worse than the
        /// skin-coloured rectangle it replaced. So
        /// <see cref="BodyLibrary"/> asks this before it hands eyebrows and
        /// eyelashes the villager's hair colour, and leaves them on the skin
        /// fallback when the answer is no. The two halves of this fix travel
        /// together or not at all.
        /// </summary>
        public static bool Has(string assetName)
        {
            return For(assetName) != null;
        }

        /// <summary>
        /// The shared cutout material for one brow or lash asset, or null
        /// when none is installed.
        ///
        /// One material per ASSET, not per villager: the twelve brows and
        /// four lashes in the pack are sixteen materials for a village of any
        /// size, and the tint arrives per submesh through the property block
        /// exactly as every other channel's does.
        /// </summary>
        public static Material For(string assetName)
        {
            if (string.IsNullOrEmpty(assetName)) return null;
            string key = assetName.ToLowerInvariant();

            Material cached;
            if (_byAsset.TryGetValue(key, out cached)) return cached;
            if (_absent.Contains(key)) return null;

            var texture = Resources.Load<Texture2D>(ResourceFolder + "/" + key);
            if (texture == null)
            {
                // Not a warning. Most assets that reach here are scalp hair,
                // which is not supposed to have a card, so a missing one is
                // the normal case rather than a problem.
                _absent.Add(key);
                return null;
            }

            Shader shader = Shader.Find("Universal Render Pipeline/Lit")
                            ?? Shader.Find("Standard");
            if (shader == null)
            {
                _absent.Add(key);
                return null;
            }

            var material = new Material(shader) { name = "extNPC/Card " + key };
            material.SetTexture("_BaseMap", texture);
            material.SetTexture("_MainTex", texture);
            // White, so the villager's own hair colour is what is seen. The
            // texture is a stencil and holds no colour of its own.
            material.SetColor("_BaseColor", Color.white);
            material.SetColor("_Color", Color.white);

            // Cutout, under either pipeline. Setting a property a shader does
            // not have is a no-op rather than an error, so writing both sets
            // is cheaper than asking which pipeline is loaded -- the same
            // reasoning the colour and smoothness names already use.
            material.SetFloat("_AlphaClip", 1f);      // URP
            material.SetFloat("_Mode", 1f);           // built-in: Cutout
            material.SetFloat("_Cutoff", AlphaCutoff);
            material.EnableKeyword("_ALPHATEST_ON");
            material.DisableKeyword("_ALPHABLEND_ON");
            material.DisableKeyword("_ALPHAPREMULTIPLY_ON");
            material.renderQueue = (int)UnityEngine.Rendering.RenderQueue.AlphaTest;

            BodyMaterials.ApplySurface(material, BodyMaterials.HairSmoothness);
            _byAsset[key] = material;

            if (!_warned)
            {
                _warned = true;
                Debug.Log("[extNPC] brow and lash cutouts in use from Resources/" +
                          ResourceFolder + ".");
            }
            return material;
        }

        /// <summary>Drop every cached material, so a reinstalled card set is
        /// picked up without restarting. Mirrors
        /// <see cref="EyeMaterials.Forget"/>.</summary>
        public static void Forget()
        {
            _byAsset.Clear();
            _absent.Clear();
            _warned = false;
        }
    }
}
