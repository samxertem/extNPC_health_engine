using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// The flat ring a villager stands in, carrying their lineage colour.
    ///
    /// WHY LINEAGE CAME OFF THE SKIN (item A5). Lineage colour used to be
    /// written straight into the body's albedo. On a capsule that reads as an
    /// encoding, which is what it is. On a clothed human it reads as a mistake,
    /// and worse than that it is opaque: once a villager is uniformly magenta,
    /// their hair, their suit, their build and their age are all the same
    /// colour, so every bit of variation the genome produced becomes invisible
    /// at exactly the moment it starts existing.
    ///
    /// The portrait solved this first, by putting lineage on the backdrop and
    /// leaving the face alone. This is the same decision for the map.
    ///
    /// WHY NOT TINT THE CLOTHES INSTEAD, which is the other obvious answer.
    /// <see cref="HumanMesh.Bake"/> calls <c>CombineMeshes</c> with
    /// mergeSubMeshes true, so body, hair and clothes arrive as ONE submesh
    /// with one material. Tinting the garment alone would mean keeping
    /// submeshes, which multiplies draw calls per villager at a point where the
    /// 600-at-60 budget is already owed a re-measurement. A ring is one extra
    /// instanced draw of a mesh every villager shares.
    ///
    /// WHY A MESH AND NOT A LineRenderer. <see cref="DemeRingView"/> uses a
    /// LineRenderer, which is right for one territory ring and wrong for six
    /// hundred villagers: each one rebuilds geometry on the CPU and none of
    /// them batch. This is a static annulus built once and shared, so the ring
    /// costs what the body costs and the colour rides in a property block.
    ///
    /// IT MEASURES NOTHING, and it is the same size for everyone. Not a
    /// territory, not a personal space, and deliberately NOT scaled by stature:
    /// a ring that grew with height would put a second and wrong reading of the
    /// engine's best-predicted trait on the floor next to the right one, and
    /// would make a toddler harder to pick out than an adult for no reason a
    /// reader could name.
    /// </summary>
    public static class LineageRing
    {
        /// <summary>
        /// Outer and inner radius in METRES, constant for every villager.
        ///
        /// SIZED TO BE SEEN FROM THE MAP CAMERA, which is the whole job now
        /// that the body no longer carries lineage. The first version was 0.34
        /// m outer and 0.10 m thick, which is correct at arm's length and
        /// invisible from an orbit camera 80 m up: the villagers went neutral
        /// and the family colouring simply disappeared.
        ///
        /// <see cref="DemeRingView.CreateMarker"/> had already learned this and
        /// written it down, having shipped a 0.85 m ring at 0.06 m width that
        /// "measured correctly and was invisible". THICKNESS carries further
        /// than radius: a thin circle antialiases away to nothing while a broad
        /// band survives as a few solid pixels. Hence 0.40 m of band rather
        /// than a wider hairline.
        ///
        /// The cost, stated rather than discovered: at 600 villagers in a
        /// settlement these overlap into a carpet. That is legible as family
        /// CLUSTERS and illegible as individuals, and if it becomes a problem
        /// the answer is to shrink with density, not to put colour back on the
        /// skin.
        /// </summary>
        private const float OuterRadius = 0.95f;
        private const float InnerRadius = 0.55f;
        private const int Segments = 32;

        /// <summary>
        /// Sits just above the ground so it does not z-fight the terrain, and
        /// far enough below the ankle that it never reads as part of the body.
        /// </summary>
        public const float HeightAboveGroundM = 0.02f;

        private static Mesh _shared;

        /// <summary>
        /// A flat annulus in the XZ plane, facing up. Built once, shared by
        /// every villager.
        /// </summary>
        public static Mesh SharedMesh()
        {
            if (_shared != null) return _shared;

            // DOUBLE SIDED, and that is not belt and braces. A single-winding
            // annulus is backface-culled from one side, and which side depends
            // on how the winding maps onto Unity's handedness: the first
            // version measured perfectly -- enabled, 1.90 m across, at y=0.02,
            // carrying the right colour -- and drew nothing, because the map
            // camera happened to be on the culled side. There is no camera
            // angle from which a ground marker should disappear, so the mesh
            // carries both windings and the question stops existing. It costs
            // 64 triangles.
            var vertices = new Vector3[Segments * 4];
            var normals = new Vector3[Segments * 4];
            var triangles = new int[Segments * 12];

            for (int i = 0; i < Segments; i++)
            {
                float t = (float)i / Segments * Mathf.PI * 2f;
                float cos = Mathf.Cos(t), sin = Mathf.Sin(t);
                var inner = new Vector3(cos * InnerRadius, 0f, sin * InnerRadius);
                var outer = new Vector3(cos * OuterRadius, 0f, sin * OuterRadius);

                vertices[i * 2] = inner;
                vertices[i * 2 + 1] = outer;
                normals[i * 2] = Vector3.up;
                normals[i * 2 + 1] = Vector3.up;

                int under = Segments * 2 + i * 2;
                vertices[under] = inner;
                vertices[under + 1] = outer;
                normals[under] = Vector3.down;
                normals[under + 1] = Vector3.down;
            }

            for (int i = 0; i < Segments; i++)
            {
                int next = (i + 1) % Segments;
                int o = i * 6;
                triangles[o] = i * 2;
                triangles[o + 1] = i * 2 + 1;
                triangles[o + 2] = next * 2 + 1;
                triangles[o + 3] = i * 2;
                triangles[o + 4] = next * 2 + 1;
                triangles[o + 5] = next * 2;

                // The same two triangles wound the other way.
                int b = Segments * 2;
                int p = Segments * 6 + i * 6;
                triangles[p] = b + next * 2 + 1;
                triangles[p + 1] = b + i * 2 + 1;
                triangles[p + 2] = b + i * 2;
                triangles[p + 3] = b + next * 2;
                triangles[p + 4] = b + next * 2 + 1;
                triangles[p + 5] = b + i * 2;
            }

            _shared = new Mesh { name = "extnpc_lineage_ring" };
            _shared.vertices = vertices;
            _shared.normals = normals;
            _shared.triangles = triangles;
            _shared.RecalculateBounds();
            return _shared;
        }

        /// <summary>
        /// Drop the cached mesh. Same reason <see cref="HumanMesh.Forget"/>
        /// exists: a mesh built in one domain is destroyed by a reload and a
        /// stale reference draws nothing.
        /// </summary>
        public static void Forget()
        {
            _shared = null;
        }

        /// <summary>
        /// The colour a villager's BODY is drawn in once lineage has moved to
        /// the ring.
        ///
        /// A NEUTRAL CONSTANT, and deliberately not derived from
        /// <c>skin_tone</c>. The trait exists and is modelled, but turning a
        /// unitless 0..1 into an albedo is a colour decision the engine has not
        /// made; the investigation memo proposes recasting it as ITA degrees so
        /// that one day it could be. Inventing a ramp here would be the viewer
        /// inventing variance, which is the one thing invariant 5 forbids, and
        /// it would be inventing it in the channel a reader is most likely to
        /// read as biology. Same constant for everyone until the trait can
        /// honestly drive it.
        /// </summary>
        public static readonly Color NeutralBody = new Color(0.86f, 0.79f, 0.72f);
    }
}
