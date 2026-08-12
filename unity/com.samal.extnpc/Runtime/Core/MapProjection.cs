using UnityEngine;

namespace ExtNPC
{
    /// <summary>
    /// The one place engine map coordinates become Unity world coordinates.
    ///
    /// The engine's map is a MAP_SIZE x MAP_SIZE square (100 x 100 arbitrary
    /// units, see simulation/community.py) with +y "up" in a 2-D plan view.
    /// Unity is Y-up and left-handed, so the plan's y becomes Unity's z.
    ///
    /// This exists as a single function on purpose. Axis conversions written
    /// inline at call sites are how half a scene ends up mirrored: each site
    /// looks locally correct, and the disagreement only shows as villagers
    /// standing in the wrong settlement. One definition, used everywhere,
    /// cannot disagree with itself.
    /// </summary>
    public struct MapProjection
    {
        /// <summary>Engine map extent. Must match community.MAP_SIZE.</summary>
        public const float MapSize = 100f;

        /// <summary>Unity metres per engine map unit. At 1.0 the world is a
        /// 100 x 100 m square -- walkable scale.</summary>
        public float MetresPerUnit;

        /// <summary>Ground height. A terrain sampler can replace this later
        /// without any call site changing.</summary>
        public float GroundY;

        public static MapProjection Default => new MapProjection
        {
            MetresPerUnit = 1f,
            GroundY = 0f,
        };

        /// <summary>Map (x, y) to a Unity position, centred on the origin so a
        /// camera orbits the middle of the world rather than its corner.</summary>
        public Vector3 ToWorld(float mapX, float mapY)
        {
            float half = MapSize * 0.5f;
            return new Vector3(
                (mapX - half) * MetresPerUnit,
                GroundY,
                (mapY - half) * MetresPerUnit);
        }

        public Vector3 ToWorld(Data.FrameRow row) => ToWorld(row.X, row.Y);

        /// <summary>Inverse, for click-to-map-position.</summary>
        public Vector2 ToMap(Vector3 world)
        {
            float half = MapSize * 0.5f;
            return new Vector2(
                world.x / MetresPerUnit + half,
                world.z / MetresPerUnit + half);
        }

        /// <summary>A settlement radius in Unity metres.</summary>
        public float RadiusToWorld(float mapRadius) => mapRadius * MetresPerUnit;
    }
}
