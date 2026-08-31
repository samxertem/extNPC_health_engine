using System.Collections.Generic;
using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// Which SURFACE each part of a villager is, as distinct from which
    /// COLOUR it is.
    ///
    /// THE DEFECT THIS FIXES. Until now every submesh of a villager pointed
    /// at one shared material and differed only in the colour arriving
    /// through a property block. Colour is per-submesh; SMOOTHNESS and
    /// METALLIC are not, they are properties of the material. So hair, wool,
    /// teeth and skin were all rendered as the same physical substance with
    /// different tints, which is why hair read as painted plastic and a suit
    /// read as vinyl. Nothing was wrong with the colours. The surface was
    /// wrong, and one material can only describe one surface.
    ///
    /// WHAT IT COSTS. Three shared materials instead of one, plus the eye and
    /// skin materials that already existed. That is three extra draw-call
    /// batches for the WHOLE VILLAGE, not per villager: colour still arrives
    /// through <c>SetPropertyBlock(block, index)</c>, so 600 villagers in
    /// nine colours each still share these same few material assets.
    ///
    /// WHY THE NUMBERS ARE WHAT THEY ARE. These are rendering values and the
    /// engine measures none of them, so they are declared here as the
    /// cosmetic constants they are rather than dressed up as derived. Skin is
    /// slightly glossy because it is; wool and cotton are nearly matte; hair
    /// sits between the two because a real hair highlight is anisotropic and
    /// URP's Lit shader cannot draw one, so a moderate isotropic smoothness
    /// is the closest honest approximation. Metallic is zero on all of them:
    /// nothing on a villager is a metal.
    ///
    /// WHY TEETH DO NOT GET THE SKIN TEXTURE. <see cref="SkinMaterials"/>
    /// carries a detail map whose UVs belong to the BODY mesh. Teeth, tongue
    /// and the rest are separate meshes with their own unrelated UVs, so
    /// sampling the body's map on them would paint a lip crease across a
    /// molar. They get <see cref="Flesh"/> instead: the same surface, no map.
    /// This is the same class of mistake as the generated eye mask recorded
    /// in <see cref="EyeMaterials"/>, and it is avoided here by construction
    /// rather than discovered later.
    /// </summary>
    public static class BodyMaterials
    {
        public const float SkinSmoothness = 0.35f;
        public const float HairSmoothness = 0.50f;
        public const float ClothSmoothness = 0.12f;

        /// <summary>Which surface a submesh's appearance channel is drawn as.</summary>
        public enum Surface
        {
            /// <summary>The body itself: the one part that takes the detail map.</summary>
            Skin,
            /// <summary>Skin's surface with no map: teeth, tongue, and anything
            /// whose channel this build has never heard of.</summary>
            Flesh,
            /// <summary>Hair, and the two parts made of it.</summary>
            Hair,
            /// <summary>Woven and worn.</summary>
            Cloth,
            /// <summary>Handled by <see cref="EyeMaterials"/>, listed so that a
            /// caller switching on this enum cannot silently forget it.</summary>
            Eyes,
        }

        /// <summary>
        /// The bake's channel vocabulary, mapped to a surface.
        ///
        /// The channels are the ones `mpfb/bake_bodies.py` writes into
        /// `bodies.json` under `submeshes`, and they are matched by NAME
        /// rather than by index for the reason <see cref="BodyLibrary"/>
        /// gives. An unknown channel is <see cref="Surface.Flesh"/>, which
        /// mirrors the colour side's decision to fall back to skin: a new
        /// channel arriving from a future bake should render as a slightly
        /// wrong human, never as a chrome sphere.
        /// </summary>
        public static Surface SurfaceOf(string channel)
        {
            if (string.IsNullOrEmpty(channel)) return Surface.Flesh;
            switch (channel.ToLowerInvariant())
            {
                case "skin": return Surface.Skin;
                case "eyes": return Surface.Eyes;
                // Eyebrows and eyelashes ARE hair, and item 4 of the viewer
                // pass moved their colour to `hair_pigment` for exactly this
                // reason. Their surface follows their colour.
                case "hair":
                case "eyebrows":
                case "eyelashes": return Surface.Hair;
                case "suit":
                case "clothes":
                case "shoes": return Surface.Cloth;
                default: return Surface.Flesh;
            }
        }

        /// <summary>The three variants derived from one base material.</summary>
        private sealed class Surfaces
        {
            public Material Flesh, Hair, Cloth;
        }

        /// <summary>
        /// Variants CACHED PER BASE MATERIAL, and that is not premature
        /// generality.
        ///
        /// There are two callers with two different base materials:
        /// <see cref="WorldRenderer"/> passes its `villagerMaterial` and
        /// <see cref="CharacterPortrait"/> passes its own portrait skin. A
        /// single remembered base would be invalidated by whichever of them
        /// drew second, so the two would rebuild three materials each, every
        /// frame, forever, and the profiler would blame the wrong thing.
        ///
        /// The base is a key rather than a parameter to the constructor
        /// because <c>WorldRenderer.villagerMaterial</c> is a public field a
        /// consuming project may assign at any time. Deriving from whatever
        /// it currently is keeps that project's shader choice and changes
        /// only the one property this class exists to vary.
        /// </summary>
        private static readonly Dictionary<Material, Surfaces> _byBase =
            new Dictionary<Material, Surfaces>();

        /// <summary>Null is a real key here: it means "no base material was
        /// supplied", which the tests hit and which resolves to a found
        /// shader. Dictionary cannot take a null key, so it gets its own
        /// slot.</summary>
        private static Surfaces _unbased;

        private static Surfaces SurfacesFor(Material baseMaterial)
        {
            if (baseMaterial == null)
                return _unbased ?? (_unbased = Build(null));
            Surfaces set;
            if (!_byBase.TryGetValue(baseMaterial, out set))
            {
                set = Build(baseMaterial);
                _byBase[baseMaterial] = set;
            }
            return set;
        }

        private static Surfaces Build(Material baseMaterial)
        {
            return new Surfaces
            {
                Flesh = Variant(baseMaterial, "Flesh", SkinSmoothness),
                Hair = Variant(baseMaterial, "Hair", HairSmoothness),
                Cloth = Variant(baseMaterial, "Cloth", ClothSmoothness),
            };
        }

        /// <summary>Skin's surface with no detail map.</summary>
        public static Material Flesh(Material baseMaterial)
        {
            return SurfacesFor(baseMaterial).Flesh;
        }

        public static Material Hair(Material baseMaterial)
        {
            return SurfacesFor(baseMaterial).Hair;
        }

        public static Material Cloth(Material baseMaterial)
        {
            return SurfacesFor(baseMaterial).Cloth;
        }

        /// <summary>
        /// Set a material's surface properties under either render pipeline.
        ///
        /// Both names, for the same reason <see cref="VillagerView"/> sets
        /// both colour names: URP's Lit calls it `_Smoothness`, the built-in
        /// Standard calls it `_Glossiness`, and setting a property a shader
        /// does not have is a no-op rather than an error, so writing both is
        /// cheaper than asking which pipeline is loaded.
        /// </summary>
        public static void ApplySurface(Material material, float smoothness)
        {
            if (material == null) return;
            material.SetFloat("_Smoothness", smoothness);
            material.SetFloat("_Glossiness", smoothness);
            material.SetFloat("_Metallic", 0f);
        }

        private static Material Variant(Material baseMaterial, string label,
                                        float smoothness)
        {
            Material material;
            if (baseMaterial != null)
            {
                material = new Material(baseMaterial) { name = "extNPC/" + label };
            }
            else
            {
                // Reached only when nothing configured this, which in
                // practice means a test. Falling back to a found shader
                // rather than returning null keeps a caller from having to
                // special-case the untested path.
                Shader shader = Shader.Find("Universal Render Pipeline/Lit")
                                ?? Shader.Find("Standard")
                                ?? Shader.Find("Sprites/Default");
                if (shader == null) return null;
                material = new Material(shader) { name = "extNPC/" + label };
            }
            ApplySurface(material, smoothness);
            return material;
        }

        /// <summary>
        /// One material per submesh, given each submesh's channel.
        ///
        /// A renderer draws only as many submeshes as it has materials, so
        /// the returned array is always <paramref name="count"/> long even
        /// when the channels are unknown. A nine-submesh body on a one-slot
        /// renderer loses eight of its parts and renders as hair alone; that
        /// is the failure this length contract exists to prevent, and it is
        /// not a crash.
        /// </summary>
        /// <param name="channels">Per-submesh channel names, or null when the
        /// bundle predates the `submeshes` block. Null means every slot is
        /// <see cref="Flesh"/>, which is what the viewer drew before this
        /// class existed.</param>
        /// <param name="skin">The textured skin material, or null to draw skin
        /// as flat <see cref="Flesh"/>.</param>
        /// <param name="eyes">The eye material, or null to leave the eye slot
        /// as flat colour rather than as a white eyeball.</param>
        /// <param name="baseMaterial">The renderer's own villager material,
        /// which the three surfaces are derived from.</param>
        /// <param name="assets">Per-submesh source mesh name, or null. Used
        /// only to find a brow or lash cutout: a hair-surfaced part whose own
        /// asset ships an alpha card is drawn with that card instead of with
        /// the flat hair material, because its shape is in the alpha. Scalp
        /// hair has no card installed and falls through unchanged.</param>
        public static Material[] SlotsFor(int count, IList<string> channels,
                                          IList<string> assets,
                                          Material baseMaterial,
                                          Material skin, Material eyes)
        {
            Surfaces set = SurfacesFor(baseMaterial);
            var slots = new Material[count];
            for (int i = 0; i < count; i++)
            {
                string channel = channels != null && i < channels.Count
                    ? channels[i] : null;
                string asset = assets != null && i < assets.Count
                    ? assets[i] : null;
                switch (SurfaceOf(channel))
                {
                    case Surface.Skin: slots[i] = skin ?? set.Flesh; break;
                    case Surface.Hair:
                        // A cutout when this asset has one, the flat hair
                        // material when it does not. `??` rather than a
                        // channel test on purpose: whether a part needs its
                        // alpha is a property of the ASSET, and asking the
                        // asset store is the same question with no second
                        // list to keep in step.
                        slots[i] = HairCardMaterials.For(asset) ?? set.Hair;
                        break;
                    case Surface.Cloth: slots[i] = set.Cloth; break;
                    case Surface.Eyes: slots[i] = eyes ?? set.Flesh; break;
                    default: slots[i] = set.Flesh; break;
                }
            }
            return slots;
        }

        /// <summary>Drop the derived materials, so a changed villager material
        /// or a reinstalled texture set is picked up. Mirrors
        /// <see cref="EyeMaterials.Forget"/>.</summary>
        public static void Forget()
        {
            _byBase.Clear();
            _unbased = null;
        }
    }
}
