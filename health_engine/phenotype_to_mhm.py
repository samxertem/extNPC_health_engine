"""
Phenotype to `.mhm`: the engine's half of the body pipeline (UNITY_PLAN Stage 7).

A `.mhm` is MakeHuman's save file, a plain-text list of modifier names and
values, and MPFB2 loads them. That makes it a phenotype vector on disk, which
is why the integration boundary is a text file rather than a Python API call:
this engine writes `.mhm`, Blender reads `.mhm`, and neither imports the
other. The licence hygiene argument is in MPFB_UNITY_INVESTIGATION.md section
2 -- MPFB is GPLv3 and must never be importable from this package -- but the
reproducibility argument is the one that matters day to day. A `.mhm` is
diffable, committable, and can travel in the CSV bundle.

WHAT THIS MODULE IS ALLOWED TO DO. Nothing but arithmetic. No RNG, no Blender,
no file system, no clock. `phenotype_to_mhm(p, sex, age)` called twice with
equal inputs returns byte-identical text, and `tests/test_phenotype_to_mhm.py`
asserts exactly that against a committed golden file. That is the whole
acceptance criterion for this stage, and it is what lets the body bake be
re-run months later and produce the same villagers.

THE THREE MACROS THIS DELIBERATELY DOES NOT DRIVE, and why each is a refusal
rather than an omission. Invariant 5 forbids the viewer inventing variance,
and a macro driven from nothing is the viewer inventing variance in the one
place nobody would think to look for it.

  * `Height`. Pinned at the neutral 0.5. Not because stature does not vary --
    it is the best-predicted trait in the model, target_pgs_r2=0.40 after
    Yengo 2022 -- but because MakeHuman's height targets are SHAPE targets
    rather than a scale, and `HumanMesh` on the Unity side normalises every
    baked mesh to exactly 1 m so `VillagerView` can scale by `height_cm/100`.
    Stature therefore already arrives, to the millimetre, by a route that the
    probe verifies end to end. Driving the macro as well would apply the
    variation twice and break the one property Stage 3 bought: that what the
    inspector prints and what the ruler measures are the same number. 0.5 is
    additionally inside the measured dead band where no height target applies
    at all (`mpfb/blender_probe.py:probe_dead_band`), so it is the only value
    that adds no shape opinion whatsoever.

  * `BodyProportions`. Still pinned at 0.5, and the reason CHANGED once it was
    measured. It used to be pinned because the engine had no body-proportion
    trait. It now has one -- `sitting_height_ratio`, item E5, h2=0.80 -- and
    the macro stays pinned anyway, because `mpfb/probe_proportions.py` swept
    it 0 to 1 on fresh humans and found it is not that trait's axis:

      - its ENTIRE range moves the mesh's trunk fraction by 0.0211, which is
        1.00 sd of sitting height ratio. A trait lives in its tails, and a
        macro that cannot reach +/- 1 sd cannot carry one.
      - over the same sweep it changes shoulder span by 14.2% at the neutral
        base and 26% at a male caucasian one. That is a large visible reshape
        that NO modelled trait authorises, and driving it from SHR would put
        it on screen anyway.
      - at the neutral base it also moves stature by 7.79 mm. Worth noting
        against `blender_probe.probe_coupling`, which recorded proportions
        moving stature by exactly 0.00 mm: that finding is CONFIRMED at the
        male caucasian base it was measured at, and is base-dependent rather
        than general.

    So the refusal is now a measurement rather than an absence, which is the
    stronger position. The trait is real and travels in the phenotype, the
    inspector and the paper; what is missing is an MPFB axis honest enough to
    render it, and MakeHuman's own leg-length targets are where to look next.

  * The three ethnicity macros. Pinned to a fixed preset for the reason set
    out at length in MPFB_UNITY_INVESTIGATION.md section 3.3: the engine
    models founder-lineage ancestry, not continental ancestry, so there is no
    variable to drive them from. Session 22 measured what the CHOICE of preset
    costs, 18.18 mm of stature between even thirds and caucasian=1.0, which is
    why it is a parameter here and not a literal. It is item U5 and it wants
    deciding once and recording, because moving it later silently rescales
    every character ever baked.

WHAT DOES NOT BELONG IN A `.mhm` AT ALL. Pigmentation. `skin_tone`,
`hair_pigment` and `eye_color` are material parameters, not morph targets, so
they travel beside the file in `pigmentation()` and are applied by whatever
renders the body. Keeping them out of the `.mhm` is not tidiness: it keeps the
morph half of the pipeline byte-reproducible without dragging a material
library's version into the hash.
"""

from __future__ import annotations

from typing import Dict, Mapping, Optional, Sequence, Tuple

__all__ = [
    "ETHNICITY_PRESETS",
    "DEFAULT_ETHNICITY",
    "age_to_macro",
    "bmi_to_weight_macro",
    "muscle_macro",
    "phenotype_to_macros",
    "pigmentation",
    "macros_to_mhm",
    "phenotype_to_mhm",
    "COSMETIC_BODYPARTS",
    "CONVENTION_BODYPARTS",
    "CITED_BODYPARTS",
    "EYE_MESH_QUALITY",
    "bodypart_lines",
    "bodypart_choices",
    "bodypart_channels",
]


# ----------------------------------------------------------------------
# the fixed choices
# ----------------------------------------------------------------------

# Mirrors `mpfb/blender_probe.py:ETHNICITY_PRESETS`. Duplicated rather than
# imported on purpose: that module only runs inside Blender, and this one must
# import in a bare pytest process with no Blender anywhere. The duplication is
# guarded by `test_ethnicity_presets_match_the_blender_side`.
ETHNICITY_PRESETS: Dict[str, Dict[str, float]] = {
    "even_thirds": {"African": 0.33, "Asian": 0.33, "Caucasian": 0.33},
    "african": {"African": 1.0, "Asian": 0.0, "Caucasian": 0.0},
    "asian": {"African": 0.0, "Asian": 1.0, "Caucasian": 0.0},
    "caucasian": {"African": 0.0, "Asian": 0.0, "Caucasian": 1.0},
}

# U5 is undecided at the time of writing, so the default is MPFB's own, which
# is what the two shipped bodies were baked with. Changing this constant
# changes every stature by 18.18 mm and invalidates every previously baked
# body, so it is a one-line change with a re-bake attached.
DEFAULT_ETHNICITY = "even_thirds"

# The neutral vector, MakeHuman's own. Anything this module does not drive
# stays here.
NEUTRAL_MACROS: Dict[str, float] = {
    "Gender": 0.5,
    "Age": 0.5,
    "Muscle": 0.5,
    "Weight": 0.5,
    "Height": 0.5,
    "BodyProportions": 0.5,
}

# Modifier group prefixes, and the emission order. Fixed order is not
# cosmetic: it is half of why the output is byte-reproducible.
_MODIFIER_PATHS: Tuple[Tuple[str, str], ...] = (
    ("macrodetails", "Gender"),
    ("macrodetails", "Age"),
    ("macrodetails", "African"),
    ("macrodetails", "Asian"),
    ("macrodetails", "Caucasian"),
    ("macrodetails-universal", "Muscle"),
    ("macrodetails-universal", "Weight"),
    ("macrodetails-height", "Height"),
    ("macrodetails-proportions", "BodyProportions"),
)


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else float(x))


# ----------------------------------------------------------------------
# the mappings, one function each so each can be tested and argued with
# ----------------------------------------------------------------------

# MakeHuman's age macro is piecewise linear in YEARS, not linear in the
# macro: 0.0 is 1 year, 0.5 is 25 years, 1.0 is 90 years. The two halves
# therefore have different slopes, 48 years per unit below 0.5 and 130 above.
#
# STATUS: ASSUMED, NOT MEASURED. This is read from MakeHuman's documented
# convention rather than from MPFB's own code, which makes it exactly the kind
# of number this project has a standing rule about. `run_mpfb_probe.py` needs
# a round-trip check that loads a generated `.mhm` into MPFB and reads the
# macro back; until that check has run and passed, treat every age-driven body
# as provisional. The constants are named so the probe can assert on them.
_AGE_YEARS_AT_ZERO = 1.0
_AGE_YEARS_AT_HALF = 25.0
_AGE_YEARS_AT_ONE = 90.0


def age_to_macro(age_years: float) -> float:
    """Years to MakeHuman's 0..1 age macro, piecewise linear about 25.

    Clamped at both ends. A newborn is not representable -- MakeHuman's
    youngest body is a one-year-old -- so ages below 1 return 0.0 and the
    caller gets a toddler rather than an error. That is a deliberate silent
    clamp: an infant villager is a rendering the base mesh cannot make, and
    failing the whole bake over one of them would be worse.
    """
    a = float(age_years)
    if a <= _AGE_YEARS_AT_HALF:
        span = _AGE_YEARS_AT_HALF - _AGE_YEARS_AT_ZERO
        return _clamp01(0.5 * (a - _AGE_YEARS_AT_ZERO) / span)
    span = _AGE_YEARS_AT_ONE - _AGE_YEARS_AT_HALF
    return _clamp01(0.5 + 0.5 * (a - _AGE_YEARS_AT_HALF) / span)


# How many trait standard deviations map to the end of the macro's range.
# 2.5 sd covers 98.8% of a normal population, so the macro saturates only for
# the genuinely extreme and the bulk of the village uses the middle of the
# slider where MPFB's targets are best behaved. Raising this compresses
# everyone toward neutral; lowering it clips more people to the ends.
_MACRO_SPREAD_SD = 2.5


def bmi_to_weight_macro(bmi: float, mean: float = 24.5, sd: float = 4.0) -> float:
    """`bmi` to MakeHuman's 0..1 weight macro, via the trait's own z-score.

    The defaults are `TRAIT_TABLE["bmi"]`'s calibrated mean and sd, passed in
    rather than imported so this stays arithmetic with no engine import. The
    z-score route is what keeps the mapping honest: a villager one sd above
    the population mean lands the same distance up the slider whatever the
    catalogue does to the absolute numbers.
    """
    z = (float(bmi) - mean) / sd
    return _clamp01(0.5 + 0.5 * z / _MACRO_SPREAD_SD)


def muscle_macro(phenotype: Mapping[str, object],
                 mean: float = 0.750, sd: float = 0.060) -> float:
    """MakeHuman's muscle macro, driven by `lean_mass_fraction` (item E4).

    THIS WAS PINNED NEUTRAL UNTIL THE TRAIT EXISTED, and the old reasoning is
    worth keeping because it is what kept a wrong body off the screen for
    three sessions: `bmi` and `adiposity` stood in for both fat and lean mass,
    there was no trait that meant musculature, and driving the macro from
    `aerobic_capacity` instead would have been a trait standing in for a trait
    it is not -- invisible in a screenshot and indefensible in a viva.

    `lean_mass_fraction` is now that trait, h2=0.60, and the mapping is the
    z-score route `bmi_to_weight_macro` uses, for the same reason: a villager
    one sd above the population mean lands the same distance up the slider
    whatever the catalogue does to the absolute numbers. Defaults are the
    trait's calibrated mean and sd, passed in rather than imported so this
    module stays pure arithmetic with no engine import.

    THE DIRECTION IS MEASURED, NOT ASSUMED, and it is the reason this docstring
    is long. `mpfb/probe_muscle.py` swept the macro 0 to 1 on fresh humans and
    found the enclosed mesh volume FALLS monotonically, by 13.4% at the neutral
    base and 15.1% at a male caucasian one, with stature unmoved at 0.000 mm at
    both. So a higher macro does not mean a bigger body; it means a leaner,
    more compact one at the same weight macro.

    That is the right direction for this trait rather than a problem with it,
    and the physics says why: lean tissue is denser than fat, roughly 1.06
    against 0.9 g/cm3, so replacing fat with muscle at constant MASS reduces
    VOLUME. A villager with a high fat-free fraction should be exactly that --
    tighter, not larger. Had the macro been wired from the naive reading that
    "more muscle means more body", every villager would have been rendered as
    the inverse of their own genome, and nothing on screen would have looked
    wrong.

    NOT BEING DRIVEN, and deliberately: `physiology.py` and `aerobic_capacity`
    do not consume this trait. They should -- lean mass is the tissue that
    consumes oxygen, and the final line says so -- but `aerobic_capacity` is a
    CALIBRATED trait, and feeding a new input into it changes its realised
    values, which churns every figure containing it and invalidates the frozen
    fixture. That is a recalibration with a decision attached, not a wiring
    job, and it is left for whoever accepts the churn.
    """
    lean = phenotype.get("lean_mass_fraction")
    if lean is None:
        # A phenotype with no E4 layer must still bake. Neutral is the honest
        # answer for an absent trait, and it is what every body baked before
        # this function had a trait to read.
        return NEUTRAL_MACROS["Muscle"]
    z = (float(lean) - mean) / sd
    return _clamp01(0.5 + 0.5 * z / _MACRO_SPREAD_SD)


def phenotype_to_macros(phenotype: Mapping[str, object],
                        sex: str,
                        age_years: float,
                        ethnicity: str = DEFAULT_ETHNICITY) -> Dict[str, float]:
    """The full macro vector for one villager. Pure arithmetic.

    `phenotype` should be the output of `NPC.phenotype_at_age(age)`, not
    `NPC.phenotype()`. The mature phenotype is age-blind by construction, so
    feeding it here would produce a village where every child is a small
    adult, which is the defect this stage exists to fix.
    """
    if ethnicity not in ETHNICITY_PRESETS:
        raise ValueError(
            f"unknown ethnicity preset {ethnicity!r}; "
            f"expected one of {sorted(ETHNICITY_PRESETS)}")
    if sex not in ("male", "female"):
        raise ValueError(f"sex must be 'male' or 'female', got {sex!r}")

    macros = dict(NEUTRAL_MACROS)
    macros.update(ETHNICITY_PRESETS[ethnicity])

    macros["Gender"] = 1.0 if sex == "male" else 0.0
    macros["Age"] = age_to_macro(age_years)
    macros["Muscle"] = muscle_macro(phenotype)

    bmi = phenotype.get("bmi")
    if bmi is not None:
        macros["Weight"] = bmi_to_weight_macro(float(bmi))

    return macros


def pigmentation(phenotype: Mapping[str, object]) -> Dict[str, object]:
    """The material half, which travels beside the `.mhm` rather than inside it.

    Returned rather than written: whoever renders the body decides whether
    these become shader parameters, a skin texture choice or nothing at all.
    `skin_tone` is unitless 0=light..1=dark today, which is item E2 -- it wants
    to be ITA degrees before anything drives an albedo from it honestly, since
    a 0..1 number mapped to a colour ramp is a ramp somebody invented.
    """
    out: Dict[str, object] = {}
    for key in ("skin_tone", "hair_pigment", "hair_curl", "hair_thickness"):
        if key in phenotype:
            out[key] = float(phenotype[key])  # type: ignore[arg-type]
    if "eye_color" in phenotype:
        out["eye_color"] = phenotype["eye_color"]
    return out


# ----------------------------------------------------------------------
# bodyparts: which channels are modelled, and which are dressing
# ----------------------------------------------------------------------

# Families picked from the villager's NAME and nothing else. Each of these is
# a real visual difference between two people that the engine does not model,
# so it is invented on purpose, reproducibly, and labelled wherever it shows.
# `cosmetic.cosmetic_choice` is the only route to them.
COSMETIC_BODYPARTS: Tuple[str, ...] = ("eyebrows", "eyelashes",
                                       "teeth", "clothes")

# Channels conditioned on a MODELLED variable by a convention that is not
# modelled, mapped to the variable. The third category, and `hair` left
# COSMETIC_BODYPARTS above to arrive here the day hairstyle stopped being a
# function of the name alone.
#
# The distinction is not pedantry. A cosmetic channel carries no information
# and a reader can be told to ignore it. A conditioned channel carries REAL
# information -- these villagers are drawn from different distributions
# because of a genetically determined variable -- while the shape of that
# dependence is invented. A caption that files it under either of the other
# two headings is wrong in a different direction each time, so it gets its
# own heading. `hair_convention.py` holds the table itself.
CONVENTION_BODYPARTS: Dict[str, str] = {"hair": "sex"}

# Families driven by a modelled trait, mapped to the trait that drives them.
# Currently one entry, and it is a presence rather than a choice: whether a
# villager wears hair at all is `pattern_baldness`, the sex-limited
# androgenetic-alopecia phenotype from the AR locus at Xq12 (roadmap #2,
# `sexchrom.py`). Which of the ten styles a non-bald villager wears is not
# modelled and stays in COSMETIC_BODYPARTS above.
#
# WHY THIS ONE IS WORTH THE COMPLICATION. The X-linked layer is validated and
# already has a figure, but until now it was only ever a number in a panel.
# Citing it here makes sex-limited inheritance visible in the lineup: the bald
# men are bald because of the X they got from their mother, and a reader can
# check that against her other sons. That is a claim the pedigree can be
# audited against, which is the opposite of a cosmetic choice.
CITED_BODYPARTS: Dict[str, str] = {"hair_presence": "pattern_baldness"}

# The eyes family is POLY COUNT, not eye colour: the CC0 pack ships
# `High-poly` and `Low-poly` and nothing else. Eye colour is a material and
# leaves through `pigmentation()` with the rest of it. So this is a rendering
# budget decision and not a phenotype at all, and it is a constant rather than
# a cosmetic channel because varying it between villagers would vary their
# vertex count for no reason a reader could name.
#
# Low-poly by default because the shipped budget is 600 villagers at 60 fps
# and an eyeball is a couple of pixels at village range. A portrait that wants
# the detail can pass the other one.
EYE_MESH_QUALITY = "Low-poly"


def _clothing_for(sex: str) -> Tuple[str, str]:
    """The two clothes families a villager draws from: a suit, and shoes.

    The CC0 pack labels its suits `Male ...` and `Female ...`, so respecting
    that is reading the asset's own metadata rather than the engine asserting
    anything about who wears what. Shoes are unlabelled and shared. The
    fedoras are deliberately not offered: they are headwear, they collide with
    every hairstyle in the pack, and one villager in twenty wearing a hat that
    intersects their own hair reads as a bug in the bake.
    """
    return ("Male " if str(sex).lower().startswith("m") else "Female "), "Shoes"


def bodypart_choices(villager_name: str,
                     phenotype: Mapping[str, object],
                     sex: str,
                     catalogue,
                     eye_quality: str = EYE_MESH_QUALITY
                     ) -> Tuple[Tuple[str, str, str], ...]:
    """`(channel, family, key)` for every part this villager wears.

    THE SINGLE PLACE THE CHOICES ARE MADE. `bodypart_lines` renders these to
    `.mhm` text and `bodypart_channels` renders them to a name-to-channel map
    for the renderer; both delegate here, so the file the bake reads and the
    map the viewer colours by cannot disagree about who is wearing what.

    CHANNEL IS FINER THAN FAMILY, and that difference is the reason this
    exists. A suit and a pair of shoes are both `clothes` to MPFB and must be
    two different colours on screen, so the channel splits them. Nothing
    downstream may recover that from an asset NAME: hairstyles, suits and
    shoes are all just strings from the installed pack, and a viewer matching
    on `afro` or `Shoes` would hold a second, silent copy of a rule that
    lives here.
    """
    from .cosmetic import conventional_choice, cosmetic_choice
    from .hair_convention import hair_weights

    out = []
    out.append(("eyes", "eyes", eye_quality))

    bald = bool(phenotype.get("pattern_baldness", False))
    if not bald:
        # Conditioned on sex, which IS modelled, by a table which is NOT. The
        # weights live in `hair_convention.py` rather than here, both because
        # this module may hold no asset literals and because the distinction
        # deserves a file that argues for it. See `cosmetic.CONVENTION_CHANNELS`.
        styles = catalogue.keys("hair")
        out.append(("hair", "hair",
                    conventional_choice(villager_name, styles,
                                        hair_weights(styles, sex),
                                        channel="hair")))

    for family in ("eyebrows", "eyelashes", "teeth"):
        out.append((family, family,
                    cosmetic_choice(villager_name, catalogue.keys(family),
                                    channel=family)))

    tongues = catalogue.keys("tongue")
    if tongues:
        out.append(("tongue", "tongue", tongues[0]))

    suit_prefix, shoe_prefix = _clothing_for(sex)
    everything = catalogue.keys("clothes")
    suits = tuple(k for k in everything if k.startswith(suit_prefix))
    shoes = tuple(k for k in everything if k.startswith(shoe_prefix))
    for options, channel in ((suits, "suit"), (shoes, "shoes")):
        if not options:
            continue
        out.append((channel, "clothes",
                    cosmetic_choice(villager_name, options, channel=channel)))
    return tuple(out)


def bodypart_channels(villager_name: str,
                      phenotype: Mapping[str, object],
                      sex: str,
                      catalogue,
                      eye_quality: str = EYE_MESH_QUALITY) -> Dict[str, str]:
    """`{written token: channel}`, which is how a renderer identifies a part.

    Keyed on the TOKEN, not the key, because the token is what is written to
    the `.mhm`, what MPFB names the object, and therefore what survives the
    FBX round trip into the mesh name the viewer can see. A key with a space
    in it (`Male casualsuit02`) is written as its token and only the token is
    recoverable downstream.

    The body itself is included under the name MPFB gives the base mesh, so a
    consumer has one map covering every part rather than one map plus a
    special case for the only part that matters most.
    """
    out = {"body": "skin"}
    for channel, family, key in bodypart_choices(
            villager_name, phenotype, sex, catalogue, eye_quality):
        out[catalogue.token(key)] = channel
    return out


def bodypart_lines(villager_name: str,
                   phenotype: Mapping[str, object],
                   sex: str,
                   catalogue,
                   eye_quality: str = EYE_MESH_QUALITY) -> Tuple[str, ...]:
    """The `.mhm` bodypart and clothes lines for one villager.

    PURE, and that is load-bearing rather than tidy. `catalogue` is passed in
    rather than loaded here so this module keeps the property its whole
    docstring rests on: no filesystem, no RNG, no clock, and therefore the same
    villager gets the same body in a year's time. `mhm_assets.load_catalogue()`
    is the impure half and lives in its own file.

    EVERY NAME COMES FROM THE CATALOGUE. Not one asset name is written down in
    this module. The catalogue is probed out of the installed MPFB, and asking
    it for something absent raises. That is not defensive style: MPFB's
    bodypart matcher, when it cannot match name AND uuid, falls back to
    comparing each candidate against ITSELF and returns the first
    self-consistent one, so a hardcoded name that went stale would put some
    other asset on the villager and log nothing. `mhm_assets` quotes the
    source.
    """
    return tuple(
        catalogue.line(family, key)
        for _channel, family, key in bodypart_choices(
            villager_name, phenotype, sex, catalogue, eye_quality))


# ----------------------------------------------------------------------
# the format
# ----------------------------------------------------------------------

# MakeHuman writes six decimals. Matching it exactly is what makes a generated
# file diffable against a hand-saved one.
_VALUE_FORMAT = "{:.6f}"

MHM_VERSION = "v1.2.0"


def macros_to_mhm(macros: Mapping[str, float],
                  name: str = "extnpc",
                  skeleton: str = "game_engine.mhskel",
                  subdivide: bool = False,
                  bodyparts: Sequence[str] = (),
                  asymmetry: Sequence[Tuple[str, float]] = ()) -> str:
    """A macro vector to `.mhm` text. Deterministic, LF line endings.

    The skeleton default is not arbitrary: `game_engine` is the rig the probe
    measured as the one that survives the FBX round trip. With no rig the mesh
    loses the unit conversion and the Z-up to Y-up correction and arrives in
    Unity 100x small and lying down, which `run_mpfb_probe.py` asserts as a
    failure on purpose.
    """
    lines = [
        "# Written by extNPC health_engine.phenotype_to_mhm",
        f"version {MHM_VERSION}",
        f"name {name}",
        "tags",
        "camera 0.0 0.0 0.0 0.0 0.0 1.0",
    ]
    for group, key in _MODIFIER_PATHS:
        if key not in macros:
            raise KeyError(f"macro vector is missing {key!r}")
        lines.append(
            f"modifier {group}/{key} {_VALUE_FORMAT.format(float(macros[key]))}")
    # Bodyparts sit between the modifiers and the skeleton, which is where
    # MakeHuman itself writes them. Emitted in the order given rather than
    # sorted here: `bodypart_lines` already fixes the order, and sorting a
    # second time would put the tie-break in two places.
    # Item E6. Asymmetry targets are ordinary modifier lines in a group named
    # after their directory, which is how MPFB's own loader resolves them:
    # `translate_mhm_target_line_to_target_fragment` strips the prefix at the
    # slash and `target_full_path` finds the file. Measured end to end by
    # `mpfb/probe_asymmetry.py` rather than inferred from that reading.
    #
    # AFTER the macros, because they are corrections to the shape the macros
    # produce, and in the order `asymmetry.target_weights` fixed, so the file
    # stays byte-reproducible.
    for target, weight in asymmetry:
        lines.append(
            f"modifier asym/{target} {_VALUE_FORMAT.format(float(weight))}")
    lines.extend(bodyparts)
    lines.append(f"skeleton {skeleton}")
    lines.append(f"subdivide {subdivide}")
    return "\n".join(lines) + "\n"


def phenotype_to_mhm(phenotype: Mapping[str, object],
                     sex: str,
                     age_years: float,
                     name: str = "extnpc",
                     ethnicity: str = DEFAULT_ETHNICITY,
                     skeleton: str = "game_engine.mhskel",
                     catalogue=None,
                     villager_name: str = "",
                     asymmetry: Optional[Mapping[str, float]] = None,
                     stress_factor: float = 1.0) -> str:
    """One villager's phenotype to one `.mhm` file's text. The Stage 7 entry point.

    Pass `catalogue` (from `mhm_assets.load_catalogue()`) to dress the body in
    eyes, hair, brows, teeth and clothes. Omitting it yields the bare body this
    function has always produced, which is still what the golden fixture pins,
    so the dressed and undressed paths stay separately checkable rather than
    becoming one path with a flag buried in it.

    `villager_name` is the cosmetic seed, and it is deliberately separate from
    `name`, which is only the `.mhm`'s own internal label. They are usually the
    same string; when they are not, cosmetics must follow the PERSON, because
    two exports of one villager under different file labels have to produce the
    same haircut or nothing downstream is reproducible.
    """
    macros = phenotype_to_macros(phenotype, sex, age_years, ethnicity=ethnicity)
    parts: Tuple[str, ...] = ()
    if catalogue is not None:
        parts = bodypart_lines(villager_name or name, phenotype, sex, catalogue)

    asym_lines: Tuple[Tuple[str, float], ...] = ()
    if asymmetry:
        # Imported here rather than at module top so this module keeps its
        # promise of being pure arithmetic with no engine import on the path
        # the golden fixture walks.
        from .asymmetry import scale_asymmetry, target_weights
        instability = phenotype.get("developmental_instability", 0.0)
        asym_lines = target_weights(
            scale_asymmetry(asymmetry, float(instability), stress_factor))

    return macros_to_mhm(macros, name=name, skeleton=skeleton, bodyparts=parts,
                         asymmetry=asym_lines)
