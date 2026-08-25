namespace ExtNPC.View
{
    /// <summary>
    /// The idle motion of a portrait head, and the framing that looks at it.
    ///
    /// WHY THIS IS A PURE STRUCT AND NOT PART OF THE COMPONENT. Everything here
    /// is arithmetic on a time and a name, so all of it is reachable from an
    /// EditMode test without a scene, a camera or a Play session. The component
    /// that owns the render texture is then thin enough to be judged by eye,
    /// which is the only way it can be judged.
    ///
    /// WHY THERE IS NO RANDOM NUMBER IN IT. UNITY_PLAN.md invariant 5 forbids
    /// the viewer inventing variance. An idle animation is presentation rather
    /// than data, so it does not carry a measurement, but two villagers swaying
    /// in perfect lockstep looks like a bug and <c>Random.value</c> would make
    /// the same villager animate differently on every run. The phase offsets
    /// are therefore derived from the villager's NAME, which is data: the same
    /// villager breathes the same way in every session, on every machine, and a
    /// screenshot taken at a given (name, time) is reproducible.
    /// </summary>
    public readonly struct PortraitPose
    {
        /// <summary>Degrees, positive turns the head to its own left.</summary>
        public readonly float Yaw;

        /// <summary>Degrees, positive lifts the chin.</summary>
        public readonly float Pitch;

        /// <summary>Metres of vertical travel, the breath.</summary>
        public readonly float Bob;

        /// <summary>0 eyes open, 1 fully closed.</summary>
        public readonly float Blink;

        public PortraitPose(float yaw, float pitch, float bob, float blink)
        {
            Yaw = yaw;
            Pitch = pitch;
            Bob = bob;
            Blink = blink;
        }

        // Amplitudes and periods. Chosen to read as "alive but not busy": the
        // portrait sits next to numbers a reader is trying to read, so the
        // motion has to be noticeable when looked at and ignorable when not.
        private const float YawSlowDeg = 13f, YawSlowPeriod = 7.3f;
        private const float YawFastDeg = 2.6f, YawFastPeriod = 2.9f;
        private const float PitchDeg = 3.4f, PitchPeriod = 5.7f;
        private const float BobMetres = 0.0055f, BobPeriod = 4.1f;

        // A glance is the thing that makes it read as a person rather than a
        // bobbing object: a longer beat that briefly breaks the sway.
        private const float GlanceDeg = 11f, GlancePeriod = 12.7f, GlanceWidth = 1.15f;

        private const float BlinkPeriod = 5.9f, BlinkDuration = 0.13f;

        /// <summary>
        /// The pose at <paramref name="seconds"/> for the villager identified by
        /// <paramref name="seed"/>.
        /// </summary>
        public static PortraitPose Idle(double seconds, uint seed)
        {
            // Four independent phase offsets from one seed, so the sway, the
            // nod, the breath and the glance do not all peak together.
            float p0 = Phase(seed, 0);
            float p1 = Phase(seed, 1);
            float p2 = Phase(seed, 2);
            float p3 = Phase(seed, 3);

            float yaw = YawSlowDeg * Sine(seconds, YawSlowPeriod, p0)
                        + YawFastDeg * Sine(seconds, YawFastPeriod, p1)
                        + GlanceDeg * Glance(seconds, p3);
            float pitch = PitchDeg * Sine(seconds, PitchPeriod, p2);
            float bob = BobMetres * Sine(seconds, BobPeriod, p1);
            float blink = Blinking(seconds, p2);
            return new PortraitPose(yaw, pitch, bob, blink);
        }

        private static float Sine(double seconds, float period, float phase)
        {
            double turns = seconds / period + phase;
            return (float)System.Math.Sin(turns * System.Math.PI * 2.0);
        }

        /// <summary>
        /// A brief look away and back: zero almost all the time, one smooth
        /// there-and-back excursion per <see cref="GlancePeriod"/>.
        /// </summary>
        private static float Glance(double seconds, float phase)
        {
            double t = Wrap(seconds / GlancePeriod + phase) * GlancePeriod;
            if (t > GlanceWidth) return 0f;
            // sin over a full turn gives out-and-back with zero slope at both
            // ends, so it joins the sway without a step.
            return (float)System.Math.Sin(t / GlanceWidth * System.Math.PI * 2.0);
        }

        private static float Blinking(double seconds, float phase)
        {
            double t = Wrap(seconds / BlinkPeriod + phase) * BlinkPeriod;
            if (t > BlinkDuration) return 0f;
            // Half a sine: shut and open again inside the duration.
            return (float)System.Math.Sin(t / BlinkDuration * System.Math.PI);
        }

        private static double Wrap(double turns) => turns - System.Math.Floor(turns);

        /// <summary>
        /// Phase offset in [0,1) for one channel of one villager.
        /// </summary>
        private static float Phase(uint seed, int channel)
        {
            uint mixed = Mix(seed ^ (0x9E3779B9u * (uint)(channel + 1)));
            return (mixed & 0xFFFFFFu) / (float)0x1000000u;
        }

        /// <summary>
        /// A stable 32-bit seed for a villager name.
        ///
        /// FNV-1a over the UTF-16 code units rather than
        /// <c>string.GetHashCode()</c>, which is explicitly NOT stable across
        /// .NET versions or runs and would make the animation unreproducible
        /// for exactly the reason the class docstring rules out
        /// <c>Random.value</c>.
        /// </summary>
        public static uint StableSeed(string name)
        {
            unchecked
            {
                uint hash = 2166136261u;
                if (name != null)
                {
                    for (int i = 0; i < name.Length; i++)
                    {
                        hash ^= name[i];
                        hash *= 16777619u;
                    }
                }
                return Mix(hash);
            }
        }

        private static uint Mix(uint x)
        {
            unchecked
            {
                x ^= x >> 16;
                x *= 0x7FEB352Du;
                x ^= x >> 15;
                x *= 0x846CA68Bu;
                x ^= x >> 16;
                return x;
            }
        }

        // ------------------------------------------------------------------
        // framing
        // ------------------------------------------------------------------

        /// <summary>
        /// How much of the body, vertically, the portrait shows, as a fraction
        /// of stature.
        ///
        /// An adult head is roughly one seventh and a half of stature; 0.21
        /// frames it with a little air above the crown and cuts around the
        /// collarbone. It is a fraction rather than a fixed number of metres so
        /// that a child, who is a scaled copy of the same mesh, is framed the
        /// same way instead of being shown from the shoulders down.
        /// </summary>
        public const float FramedFraction = 0.21f;

        /// <summary>
        /// How far below the eye line the portrait cuts, as a fraction of
        /// stature. Just under the collarbone, so the crop reads as a portrait
        /// rather than as a floating head.
        /// </summary>
        public const float BelowEyeFraction = 0.105f;

        /// <summary>Air left above the highest point of the head.</summary>
        public const float HeadroomFraction = 0.012f;

        /// <summary>
        /// Frame the head from its ACTUAL top down to below the collarbone,
        /// returning the focus height and the vertical span to fit.
        ///
        /// WHY THIS REPLACES A FIXED FRACTION OF STATURE. <see
        /// cref="FramedFraction"/> was chosen in session 22, when every body
        /// was bald, and it centres on the eye line. Hair does not fit in that
        /// frame: <see cref="HumanMesh"/> normalises a body so the UNDRESSED
        /// crown is at 1 m, deliberately, so hair and shoes stand proud of it.
        /// A bob comes out at about 1.03, so the top of the villager's head
        /// was being cropped off and the key light, which rides the focus, sat
        /// level with the crown and blew it out. It looked like a rendering
        /// fault and was a framing one, and it only became obvious once hair
        /// stopped being the same colour as the face.
        ///
        /// `unitTop` is the mesh's own local bounds maximum, which is 1.0 for
        /// a bald body and more for a dressed one. Read rather than assumed:
        /// how far a hairstyle stands proud is a property of whichever asset
        /// the villager drew, and a constant here would be right for one
        /// hairstyle in ten.
        /// </summary>
        public static void FrameHead(float statureM, float unitTop,
                                     out float focusHeightM, out float spanM)
        {
            float tallest = unitTop > 1f ? unitTop : 1f;
            float top = tallest * statureM * (1f + HeadroomFraction);
            float bottom = EyeHeight(statureM) - BelowEyeFraction * statureM;
            if (top <= bottom) top = bottom + 0.01f;
            spanM = top - bottom;
            focusHeightM = 0.5f * (top + bottom);
        }

        /// <summary>
        /// Metres from the focus to the camera, for a perspective camera of
        /// `verticalFovDeg` that must fit `spanM` vertically.
        /// </summary>
        public static float DistanceForSpan(float spanM, float verticalFovDeg)
        {
            double halfFov = verticalFovDeg * 0.5 * System.Math.PI / 180.0;
            double tan = System.Math.Tan(halfFov);
            if (tan <= 1e-6) return spanM;
            return (float)(spanM * 0.5 / tan);
        }

        /// <summary>
        /// Metres from the eye line to the camera, for a perspective camera of
        /// <paramref name="verticalFovDeg"/> looking at a body of
        /// <paramref name="statureM"/>.
        /// </summary>
        public static float CameraDistance(float statureM, float verticalFovDeg)
        {
            float framed = statureM * FramedFraction;
            double halfFov = verticalFovDeg * 0.5 * System.Math.PI / 180.0;
            double tan = System.Math.Tan(halfFov);
            if (tan <= 1e-6) return framed;          // degenerate fov
            return (float)(framed * 0.5 / tan);
        }

        /// <summary>
        /// Height of the eye line above the soles, in metres.
        /// </summary>
        public static float EyeHeight(float statureM) =>
            statureM * HumanMesh.EyeHeightFraction;
    }
}
