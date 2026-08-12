using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// Unity's built-in primitive meshes, fetched once.
    ///
    /// <c>GameObject.CreatePrimitive</c> is the only public way to get at them,
    /// and it builds a whole GameObject with a collider to do it. Doing that
    /// per villager would be hundreds of throwaway objects at load; doing it
    /// once and keeping the mesh costs two.
    /// </summary>
    public static class PrimitiveMeshes
    {
        private static Mesh _capsule;
        private static Mesh _cylinder;
        private static Mesh _quad;

        public static Mesh Capsule => _capsule ??= Extract(PrimitiveType.Capsule);
        public static Mesh Cylinder => _cylinder ??= Extract(PrimitiveType.Cylinder);
        public static Mesh Quad => _quad ??= Extract(PrimitiveType.Quad);

        private static Mesh Extract(PrimitiveType type)
        {
            var temp = GameObject.CreatePrimitive(type);
            var mesh = temp.GetComponent<MeshFilter>().sharedMesh;
            if (Application.isPlaying) Object.Destroy(temp);
            else Object.DestroyImmediate(temp);
            return mesh;
        }
    }
}
