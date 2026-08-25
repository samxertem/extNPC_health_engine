using UnityEngine;

namespace ExtNPC.View
{
    /// <summary>
    /// A live, moving head for the villager the inspector is describing.
    ///
    /// WHAT IT IS. A second camera, a copy of the shared body from
    /// <see cref="HumanMesh"/>, and a light, rendered into a
    /// <see cref="RenderTexture"/> that <see cref="VillagerInspector"/> blits
    /// into its panel. The head sways, nods, breathes and glances, so the panel
    /// shows a person rather than a mugshot.
    ///
    /// WHERE IT LIVES, AND WHY THAT IS NOT A LAYER. The obvious way to keep a
    /// portrait rig out of the main camera is a dedicated layer, but a package
    /// cannot add one: layers are a project setting, and requiring the consumer
    /// to create one would break the "empty scene to working viewer in one
    /// click" property that Editor/SceneSetup.cs exists to provide. So the rig
    /// sits <see cref="StageY"/> metres below the world instead, and the
    /// portrait camera's far plane is clipped to a couple of metres, which
    /// cannot reach the village even in principle. 2000 m rather than something
    /// dramatic like 10 km on purpose: float32 has about 0.2 mm of resolution
    /// at 2000 m and about 8 mm at 100 km, and 8 mm of quantisation is visible
    /// on a face.
    ///
    /// WHAT IT DOES NOT DO. It does not tint the skin. <c>skin_tone</c> is a
    /// real engine trait, but turning a unitless 0..1 into an albedo is a
    /// colour decision the engine has not made (the investigation memo §6.5
    /// proposes recasting it as ITA° precisely so that it could be), and
    /// inventing a ramp here would be the viewer inventing variance. The
    /// lineage colour is carried by the BACKDROP instead, where it identifies
    /// the villager without pretending to be their complexion.
    /// </summary>
    [AddComponentMenu("")]
    public sealed class CharacterPortrait : MonoBehaviour
    {
        /// <summary>How far below the world the portrait rig stands.</summary>
        public const float StageY = -2000f;

        /// <summary>Vertical field of view. Narrow, because a wide lens on a
        /// face at this distance gives the nose a caricature.</summary>
        public const float FovDeg = 26f;

        public const int TextureWidth = 232;
        public const int TextureHeight = 268;

        // A single neutral complexion for everyone, and a constant on purpose:
        // see the class docstring. Same reasoning as VillagerView.BodyWidthM.
        private static readonly Color SkinAlbedo = new Color(0.72f, 0.56f, 0.46f);

        /// <summary>Key and fill intensity. See the note in Build.</summary>
        public const float KeyIntensity = 0.88f;
        public const float FillIntensity = 0.13f;

        private static readonly int BaseColorId = Shader.PropertyToID("_BaseColor");
        private static readonly int ColorId = Shader.PropertyToID("_Color");
        private static readonly int SmoothnessId = Shader.PropertyToID("_Smoothness");
        private static readonly int GlossinessId = Shader.PropertyToID("_Glossiness");

        private Camera _camera;
        private RenderTexture _texture;
        private Transform _pivot;
        private MeshFilter _filter;
        private MeshRenderer _renderer;
        private MaterialPropertyBlock _block;
        private Light _key, _fill;
        private Material _skin;

        private string _name;
        private string _lifeStage;
        private bool _female;
        private float _statureM = 1.7f;
        private Color _lineage = Color.grey;
        private bool _hasSubject;

        /// <summary>True when a body asset is installed and a face can be
        /// drawn at all. False is a supported state; the inspector says so.</summary>
        public static bool BodyInstalled => HumanMesh.Available;

        /// <summary>The texture to blit, or null when there is nothing to show.</summary>
        public RenderTexture Texture => _hasSubject ? _texture : null;

        public static CharacterPortrait Create(Transform parent)
        {
            var go = new GameObject("Portrait");
            go.transform.SetParent(parent, false);
            var portrait = go.AddComponent<CharacterPortrait>();
            portrait.Build();
            return portrait;
        }

        private void Build()
        {
            transform.localPosition = new Vector3(0f, StageY, 0f);

            _pivot = new GameObject("Subject").transform;
            _pivot.SetParent(transform, false);

            var body = new GameObject("Body");
            body.transform.SetParent(_pivot, false);
            _filter = body.AddComponent<MeshFilter>();
            _renderer = body.AddComponent<MeshRenderer>();
            _renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            _renderer.receiveShadows = false;

            Shader shader = Shader.Find("Universal Render Pipeline/Lit")
                            ?? Shader.Find("Standard")
                            ?? Shader.Find("Sprites/Default");
            if (shader != null)
            {
                _skin = new Material(shader) { name = "extNPC/PortraitSkin" };
                _skin.SetColor(BaseColorId, SkinAlbedo);
                _skin.SetColor(ColorId, SkinAlbedo);
                // Skin is not a mirror. Both names are set for the same reason
                // VillagerView sets two colour names: URP and built-in differ.
                if (_skin.HasProperty(SmoothnessId)) _skin.SetFloat(SmoothnessId, 0.18f);
                if (_skin.HasProperty(GlossinessId)) _skin.SetFloat(GlossinessId, 0.18f);
                _renderer.sharedMaterial = _skin;
            }

            var camGo = new GameObject("PortraitCamera");
            camGo.transform.SetParent(transform, false);
            _camera = camGo.AddComponent<Camera>();
            _camera.fieldOfView = FovDeg;
            _camera.clearFlags = CameraClearFlags.SolidColor;
            _camera.nearClipPlane = 0.02f;
            // Tight, so the camera cannot see the village 2000 m above it even
            // if someone moves the rig.
            _camera.farClipPlane = 6f;
            _camera.enabled = false;          // rendered explicitly, once a frame
            _camera.allowHDR = false;
            _camera.allowMSAA = true;

            // Three-quarter key plus a soft fill: one light makes half the face
            // black at this fov, and a flat frontal light makes it a passport
            // photo. Both are children of the rig so they cannot light the
            // village, and neither is a directional light for that reason.
            // Positions are set every frame in RenderFrame, where the eye line
            // is known; these are placeholders until the first subject.
            //
            // The intensities are low because the lights are CLOSE. A point
            // light falls off with the square of distance, and these sit about
            // 0.8 m from the face, so 3.1 puts roughly five times full white on
            // the cheek: the first render came back as a white silhouette with
            // eyes. These were tuned against actual pixels, not guessed.
            _key = MakeLight("KeyLight", KeyIntensity, new Color(1f, 0.96f, 0.90f));
            _fill = MakeLight("FillLight", FillIntensity, new Color(0.72f, 0.78f, 0.95f));

            _texture = new RenderTexture(TextureWidth, TextureHeight, 24)
            {
                name = "extNPC/Portrait",
                antiAliasing = 2,
                filterMode = FilterMode.Bilinear,
            };
            _texture.Create();
            _camera.targetTexture = _texture;
        }

        private Light MakeLight(string name, float intensity, Color colour)
        {
            var go = new GameObject(name);
            go.transform.SetParent(transform, false);
            var light = go.AddComponent<Light>();
            // Point rather than directional on purpose: a directional light has
            // no position and would spill onto the village 2000 m above.
            light.type = LightType.Point;
            light.intensity = intensity;
            light.color = colour;
            light.range = 4f;
            light.shadows = LightShadows.None;
            return light;
        }

        /// <summary>
        /// Point the portrait at a villager. Cheap to call every frame with the
        /// same arguments; the mesh is only swapped when the subject changes.
        /// </summary>
        public void SetSubject(string villagerName, bool female, double heightCm,
                               Color lineage)
        {
            SetSubject(villagerName, null, female, heightCm, lineage);
        }

        /// <summary>
        /// Point the portrait at a villager AS THEY WERE at the displayed
        /// tick. The inspector opens on whatever year the timeline is at, so
        /// a portrait that ignored the stage would show a 60-year-old face
        /// above a panel of childhood statistics.
        /// </summary>
        public void SetSubject(string villagerName, string lifeStage, bool female,
                               double heightCm, Color lineage)
        {
            // THIS VILLAGER'S OWN BODY, not the shared one for their sex.
            //
            // The portrait was built in session 22, before per-villager bodies
            // existed, so it asked HumanMesh for the shared male or female mesh
            // and every woman in the village had the same face as every other
            // woman. That is the one place it matters most: the panel opens
            // BECAUSE somebody clicked a particular person, and it was showing
            // them a stand-in.
            //
            // UnitBodyFor falls back to exactly the old shared mesh when the
            // villager has no baked body, so a bundle with no bodies installed
            // behaves as it did before rather than losing its portrait.
            Mesh body = BodyLibrary.UnitBodyFor(villagerName, lifeStage, female);
            if (body == null)
            {
                _hasSubject = false;
                return;
            }

            // The stage joins the change test. Without it the portrait keeps
            // the mesh it first loaded while the timeline is scrubbed across
            // a birthday, which looks exactly like staging not working.
            bool changed = villagerName != _name || female != _female ||
                           lifeStage != _lifeStage;
            _lifeStage = lifeStage;
            _name = villagerName;
            _female = female;
            _lineage = lineage;
            _statureM = (float)(System.Math.Max(heightCm, 1.0) * 0.01);
            if (changed || _filter.sharedMesh != body) _filter.sharedMesh = body;
            ApplyPartColors(body, villagerName, lifeStage);
            _hasSubject = true;
        }

        /// <summary>
        /// Give the portrait one material slot per submesh and paint each.
        ///
        /// THE BUG THIS FIXES, because it is not obvious from the symptom. A
        /// renderer draws only as many submeshes as it has materials. Since
        /// bodies stopped being merged into one submesh so that skin, hair,
        /// eyes and clothes could take different colours, a body arrives here
        /// with nine submeshes; on the portrait's single-slot renderer eight
        /// of them silently vanish and the panel shows a fragment of a person.
        /// <see cref="VillagerView"/> got the same treatment at the same time
        /// and this one was missed, which is why the village looked right and
        /// the inspector did not.
        ///
        /// One material, N slots: colour arrives through
        /// <c>SetPropertyBlock(block, index)</c>, so there is still exactly
        /// one portrait material.
        /// </summary>
        private void ApplyPartColors(Mesh body, string villagerName,
                                     string lifeStage)
        {
            if (_renderer == null || body == null) return;

            int subs = Mathf.Max(1, body.subMeshCount);
            if (_renderer.sharedMaterials.Length != subs)
            {
                var slots = new Material[subs];
                for (int i = 0; i < subs; i++) slots[i] = _skin;
                _renderer.sharedMaterials = slots;
            }

            if (_block == null) _block = new MaterialPropertyBlock();

            Color[] parts = BodyLibrary.SubmeshColorsFor(villagerName, lifeStage);
            for (int i = 0; i < subs; i++)
            {
                // No colours in this bundle: clear any block left from a
                // previous subject so the material's own skin tone shows
                // through, rather than leaving the last villager's hair
                // colour on this one's face.
                _renderer.GetPropertyBlock(_block, i);
                Color c = (parts != null && parts.Length == subs)
                    ? parts[i] : SkinAlbedo;
                _block.SetColor(BaseColorId, c);
                _block.SetColor(ColorId, c);
                _renderer.SetPropertyBlock(_block, i);
            }
        }

        public void ClearSubject() => _hasSubject = false;

        /// <summary>
        /// Advance the idle animation and render one frame.
        ///
        /// Driven from <see cref="VillagerInspector"/>'s Update rather than
        /// from OnGUI: OnGUI runs several times per frame for layout and
        /// repaint, and rendering a camera in each of those passes would cost
        /// the portrait several times over and make the motion frame-rate
        /// dependent.
        /// </summary>
        public void RenderFrame(double seconds)
        {
            if (!_hasSubject || _camera == null) return;

            // The body is a UNIT mesh: 1 m tall, soles on the pivot. Scaling
            // uniformly by stature is what makes the framing below correct for
            // a child as well as an adult.
            _pivot.localScale = Vector3.one * _statureM;

            PortraitPose pose = PortraitPose.Idle(seconds, PortraitPose.StableSeed(_name));
            _pivot.localRotation = Quaternion.Euler(0f, 180f + pose.Yaw, 0f);
            _pivot.localPosition = new Vector3(0f, pose.Bob, 0f);

            // Framed from the mesh's OWN top, not from a fixed fraction of
            // stature: a hairstyle stands proud of the 1 m unit body by
            // however much that asset happens to be, and the old constant
            // cropped the crown off and put the key light level with it.
            float unitTop = 1f;
            if (_filter != null && _filter.sharedMesh != null)
                unitTop = _filter.sharedMesh.bounds.max.y;

            float focusHeight, span;
            PortraitPose.FrameHead(_statureM, unitTop, out focusHeight, out span);
            float distance = PortraitPose.DistanceForSpan(span, FovDeg);

            // The camera ORBITS the eye line rather than tilting in place. A
            // camera that pitches where it stands swings the face out of frame;
            // one that swings around the focus keeps the face centred and reads
            // as the head nodding, which is the intent.
            var focus = new Vector3(0f, focusHeight + pose.Bob, 0f);
            Quaternion swing = Quaternion.Euler(pose.Pitch, 0f, 0f);
            Vector3 offset = swing * new Vector3(0f, 0f, -distance);
            _camera.transform.localPosition = focus + offset;
            _camera.transform.localRotation = Quaternion.LookRotation(-offset, Vector3.up);

            // Lights ride the focus and sit on the camera's side of the head.
            _key.transform.localPosition = focus + new Vector3(0.42f, 0.34f, -0.62f);
            _fill.transform.localPosition = focus + new Vector3(-0.5f, 0.06f, -0.5f);

            _camera.backgroundColor = Backdrop(_lineage);
            _camera.Render();
        }

        /// <summary>The HUD's own dark neutral, which the backdrop fades toward.</summary>
        private static readonly Color BackdropFloor = new Color(0.06f, 0.07f, 0.09f);

        /// <summary>How far toward that floor. High, because a face has to read
        /// against it and a saturated lineage hue at full strength does not.</summary>
        private const float BackdropFade = 0.80f;

        /// <summary>
        /// The lineage colour, taken down to something a face reads against.
        ///
        /// A STRAIGHT LERP, and not the obvious HSV version, which is what this
        /// was first written as. `tests/test_unity_contract.py` forbids
        /// `HSVToRGB` anywhere in the runtime and caught it: the lineage rule
        /// IS an HSV rule (hue by founder, saturation by ancestry purity, value
        /// by alive or dead) and it lives once, in simulation/lineage.py. Any
        /// C# that reassembles a colour out of hue and saturation is a second
        /// place that rule could come to exist, whatever the author meant by
        /// it, and the point of a bright line is that it does not need
        /// case-by-case judgement.
        ///
        /// A lerp toward a fixed neutral cannot be mistaken for a colour rule.
        /// It darkens and desaturates in one step, and the result differs from
        /// the HSV version by a couple of levels per channel.
        /// </summary>
        public static Color Backdrop(Color lineage) =>
            Color.Lerp(lineage, BackdropFloor, BackdropFade);

        private void OnDestroy()
        {
            if (_camera != null) _camera.targetTexture = null;
            if (_texture != null)
            {
                _texture.Release();
                if (Application.isPlaying) Destroy(_texture); else DestroyImmediate(_texture);
            }
            if (_skin != null)
            {
                if (Application.isPlaying) Destroy(_skin); else DestroyImmediate(_skin);
            }
        }
    }
}
