using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// A minimal orbit camera, so the village can be looked at without wiring
    /// up an input system first.
    ///
    /// Drag to orbit, scroll to zoom, right-drag or WASD to pan. Deliberately
    /// uses the legacy Input class: it works in a default project with no
    /// package added, which is the point of a package that should be usable
    /// five minutes after cloning. Replace it with whatever the host project
    /// already uses.
    /// </summary>
    [AddComponentMenu("extNPC/Orbit Camera")]
    [RequireComponent(typeof(Camera))]
    public sealed class OrbitCamera : MonoBehaviour
    {
        public Vector3 pivot = Vector3.zero;
        public float distance = 90f;
        public float minDistance = 3f;
        public float maxDistance = 400f;

        [Range(5f, 89f)] public float pitch = 42f;
        public float yaw = 45f;

        public float orbitSpeed = 4f;
        public float zoomSpeed = 12f;
        public float panSpeed = 0.6f;

        private void Start() => Apply();

        private void LateUpdate()
        {
            // Left-drag alone is reserved for selection (WorldRenderer raycasts
            // on mouse-down), so orbiting needs alt or the right button. Middle
            // drag orbits too, for people used to DCC tools.
            bool orbiting = InputCompat.MiddleHeld ||
                            InputCompat.RightHeld ||
                            (InputCompat.LeftHeld && InputCompat.AltHeld);

            if (orbiting)
            {
                Vector2 delta = InputCompat.MouseDelta;
                yaw += delta.x * orbitSpeed;
                pitch = Mathf.Clamp(pitch - delta.y * orbitSpeed, 5f, 89f);
            }

            float scroll = InputCompat.Scroll;
            if (!Mathf.Approximately(scroll, 0f))
            {
                distance = Mathf.Clamp(
                    distance - scroll * zoomSpeed * Mathf.Max(distance * 0.1f, 1f),
                    minDistance, maxDistance);
            }

            Vector2 move = InputCompat.MoveAxis;
            if (move.sqrMagnitude > 0f)
            {
                Vector3 forward = Vector3.ProjectOnPlane(
                    transform.forward, Vector3.up).normalized;
                Vector3 right = Vector3.ProjectOnPlane(
                    transform.right, Vector3.up).normalized;
                pivot += (forward * move.y + right * move.x) *
                         (panSpeed * distance * Time.unscaledDeltaTime);
            }

            Apply();
        }

        private void Apply()
        {
            var rotation = Quaternion.Euler(pitch, yaw, 0f);
            transform.SetPositionAndRotation(
                pivot + rotation * new Vector3(0f, 0f, -distance),
                rotation);
        }

        /// <summary>Frame the whole engine map.</summary>
        public void FrameWorld(float metresPerMapUnit)
        {
            pivot = Vector3.zero;
            distance = MapProjection.MapSize * metresPerMapUnit * 0.9f;
        }
    }
}
