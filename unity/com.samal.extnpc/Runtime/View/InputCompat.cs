using UnityEngine;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
#endif

namespace ExtNPC.View
{
    /// <summary>
    /// The little bit of input this package needs, under either backend.
    ///
    /// A project set to "Input System Package (New)" throws
    /// <c>InvalidOperationException</c> the moment anything touches
    /// <c>UnityEngine.Input</c>, and a project on the old manager has no
    /// <c>Mouse.current</c>. Unity defines <c>ENABLE_INPUT_SYSTEM</c> and
    /// <c>ENABLE_LEGACY_INPUT_MANAGER</c> from Player Settings, and both can be
    /// on at once ("Both" mode), so the new path is preferred where available.
    ///
    /// Kept in one file so the rest of the package never mentions either API.
    /// A test in the engine repo fails if <c>UnityEngine.Input</c> appears
    /// anywhere else -- scattered <c>#if</c>s are how half a package ends up
    /// working on one backend only.
    /// </summary>
    public static class InputCompat
    {
#if ENABLE_INPUT_SYSTEM
        // The new backend reports mouse movement in PIXELS per frame, while
        // the legacy axis is pre-scaled to roughly 0.05-0.1 per pixel. Without
        // this factor the same orbitSpeed spins the camera ~20x faster under
        // the new backend, which reads as a broken camera rather than a units
        // mismatch.
        private const float DeltaToLegacyAxis = 0.05f;

        public static bool Available => Mouse.current != null;

        public static Vector2 MouseDelta =>
            Mouse.current == null
                ? Vector2.zero
                : Mouse.current.delta.ReadValue() * DeltaToLegacyAxis;

        public static Vector2 MousePosition =>
            Mouse.current == null ? Vector2.zero
                                  : Mouse.current.position.ReadValue();

        /// <summary>Normalised to the legacy scale (~0.1 per notch). Raw scroll
        /// is ±120 per notch on desktop but ±1 on some platforms, so it is
        /// normalised by magnitude rather than by a fixed divisor.</summary>
        public static float Scroll
        {
            get
            {
                if (Mouse.current == null) return 0f;
                float raw = Mouse.current.scroll.ReadValue().y;
                if (Mathf.Approximately(raw, 0f)) return 0f;
                return Mathf.Abs(raw) > 1.5f ? raw / 1200f : raw * 0.1f;
            }
        }

        public static bool LeftPressedThisFrame =>
            Mouse.current != null && Mouse.current.leftButton.wasPressedThisFrame;

        public static bool LeftHeld =>
            Mouse.current != null && Mouse.current.leftButton.isPressed;

        public static bool RightHeld =>
            Mouse.current != null && Mouse.current.rightButton.isPressed;

        public static bool MiddleHeld =>
            Mouse.current != null && Mouse.current.middleButton.isPressed;

        public static bool AltHeld =>
            Keyboard.current != null &&
            (Keyboard.current.leftAltKey.isPressed ||
             Keyboard.current.rightAltKey.isPressed);

        /// <summary>WASD / arrows as (x = right, y = forward), unsmoothed.</summary>
        public static Vector2 MoveAxis
        {
            get
            {
                var k = Keyboard.current;
                if (k == null) return Vector2.zero;
                float x = 0f, y = 0f;
                if (k.aKey.isPressed || k.leftArrowKey.isPressed) x -= 1f;
                if (k.dKey.isPressed || k.rightArrowKey.isPressed) x += 1f;
                if (k.sKey.isPressed || k.downArrowKey.isPressed) y -= 1f;
                if (k.wKey.isPressed || k.upArrowKey.isPressed) y += 1f;
                return new Vector2(x, y);
            }
        }

        /// <summary>Q/E as (down = -1, up = +1), for the pan plane's missing axis.</summary>
        public static float Vertical
        {
            get
            {
                var k = Keyboard.current;
                if (k == null) return 0f;
                float v = 0f;
                if (k.qKey.isPressed) v -= 1f;
                if (k.eKey.isPressed) v += 1f;
                return v;
            }
        }

        public static bool ShiftHeld =>
            Keyboard.current != null &&
            (Keyboard.current.leftShiftKey.isPressed ||
             Keyboard.current.rightShiftKey.isPressed);

        public static bool HKeyPressedThisFrame =>
            Keyboard.current != null && Keyboard.current.hKey.wasPressedThisFrame;
#else
        public static bool Available => true;

        public static Vector2 MouseDelta =>
            new Vector2(Input.GetAxis("Mouse X"), Input.GetAxis("Mouse Y"));

        public static Vector2 MousePosition => Input.mousePosition;

        public static float Scroll => Input.GetAxis("Mouse ScrollWheel");

        public static bool LeftPressedThisFrame => Input.GetMouseButtonDown(0);
        public static bool LeftHeld => Input.GetMouseButton(0);
        public static bool RightHeld => Input.GetMouseButton(1);
        public static bool MiddleHeld => Input.GetMouseButton(2);

        public static bool AltHeld =>
            Input.GetKey(KeyCode.LeftAlt) || Input.GetKey(KeyCode.RightAlt);

        public static Vector2 MoveAxis =>
            new Vector2(Input.GetAxisRaw("Horizontal"),
                        Input.GetAxisRaw("Vertical"));

        /// <summary>Q/E as (down = -1, up = +1), for the pan plane's missing axis.</summary>
        public static float Vertical
        {
            get
            {
                float v = 0f;
                if (Input.GetKey(KeyCode.Q)) v -= 1f;
                if (Input.GetKey(KeyCode.E)) v += 1f;
                return v;
            }
        }

        public static bool ShiftHeld =>
            Input.GetKey(KeyCode.LeftShift) || Input.GetKey(KeyCode.RightShift);

        public static bool HKeyPressedThisFrame => Input.GetKeyDown(KeyCode.H);
#endif
    }
}
