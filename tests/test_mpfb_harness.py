"""The MPFB harness, tested where it has already been wrong.

WHY THIS FILE EXISTS. `mpfb/` and `run_mpfb_probe.py` are measurement
harnesses, and a harness that is wrong does not fail loudly: it reports a
number. Session 22 shipped two bugs of exactly that shape in one evening.

  * `verdicts`-adjacent code compared a C# `bool` against Python's `"True"`,
    so a working body pipeline reported FAIL twice.
  * The portrait check read `pixels[0]` as the backdrop. `GetPixels32` starts
    at the BOTTOM-left, which on a portrait is shoulder, so it reported a white
    sky and a meaningless 98% subject fraction.

Neither was caught by anything except reading the output and disbelieving it.
Both live in pure Python that needs no Blender, no Unity and no FBX, which is
what this file covers. What it deliberately does NOT cover is anything that
needs those three: that is what `run_mpfb_probe.py` is for, and pretending
otherwise here would be the fake-verification pattern this project already has
a rule about.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import run_mpfb_probe  # noqa: E402
from mpfb import unity_measure  # noqa: E402


# ---------------------------------------------------------------------
# the log parser
# ---------------------------------------------------------------------

def test_parser_groups_by_subject():
    log = """
irrelevant editor chatter
[MEASURE] BEGIN alpha.fbx
[MEASURE] useFileScale=True
[MEASURE] vertex_span=1.140080,1.754592,0.476798
[MEASURE] END
[MEASURE] BEGIN beta.fbx
[MEASURE] vertex_span=0.1,0.2,0.3
[MEASURE] END
more chatter
"""
    got = unity_measure._parse(log)
    assert set(got) == {"alpha.fbx", "beta.fbx"}
    assert got["alpha.fbx"]["vertex_span"] == [1.140080, 1.754592, 0.476798]
    assert got["beta.fbx"]["vertex_span"] == [0.1, 0.2, 0.3]


def test_parser_keeps_scalars_as_floats_and_flags_as_strings():
    got = unity_measure._parse(
        "[MEASURE] BEGIN a\n[MEASURE] fileScale=0.01\n"
        "[MEASURE] useFileScale=True\n[MEASURE] END\n")
    assert got["a"]["fileScale"] == pytest.approx(0.01)
    # A bool stays a string, which is exactly the seam that produced the
    # "True" vs "true" bug: the comparison has to be case-insensitive.
    assert isinstance(got["a"]["useFileScale"], str)


def test_parser_accepts_an_alternative_marker():
    log = "[BODYCHECK] BEGIN female\n[BODYCHECK] unit_height=1.0\n[BODYCHECK] END\n"
    assert unity_measure._parse(log) == {}, "the default marker must not match"
    got = unity_measure._parse(log, marker="[BODYCHECK]")
    assert got["female"]["unit_height"] == pytest.approx(1.0)


def test_parser_ignores_lines_outside_a_subject():
    got = unity_measure._parse("[MEASURE] stray=1.0\n[MEASURE] BEGIN a\n"
                               "[MEASURE] real=2.0\n[MEASURE] END\n"
                               "[MEASURE] after=3.0\n")
    assert got == {"a": {"real": 2.0}}


def test_parser_survives_an_unterminated_subject():
    # A crashed editor writes BEGIN and then nothing. Losing the whole file
    # because of it would hide the very failure being investigated.
    got = unity_measure._parse("[MEASURE] BEGIN a\n[MEASURE] partial=1.0\n")
    assert got["a"]["partial"] == pytest.approx(1.0)


def test_parser_handles_negative_and_exponent_scalars():
    got = unity_measure._parse("[MEASURE] BEGIN a\n[MEASURE] v=-0.000338\n"
                               "[MEASURE] e=1.5e-07\n[MEASURE] END\n")
    assert got["a"]["v"] == pytest.approx(-0.000338)
    assert got["a"]["e"] == pytest.approx(1.5e-07)


def test_parser_handles_a_negative_vector():
    got = unity_measure._parse(
        "[MEASURE] BEGIN a\n[MEASURE] vertex_min=-0.570040,-0.000338,-0.097963\n"
        "[MEASURE] END\n")
    assert got["a"]["vertex_min"] == [-0.570040, -0.000338, -0.097963]


# ---------------------------------------------------------------------
# the three pipeline rules
# ---------------------------------------------------------------------

AUTHORED = 1.754592


def _unity(baked=AUTHORED, rigged=1.665890, norig=0.004230):
    def span(y):
        return {"vertex_span": [1.0, y, 0.4]}
    return {
        "mpfb_baked.fbx": span(baked),
        "mpfb_gamerig.fbx": span(rigged),
        "mpfb_norig.fbx": span(norig),
    }


def test_the_three_rules_pass_on_the_real_measurements():
    got = run_mpfb_probe.verdicts({"export_stature_m": AUTHORED}, _unity())
    assert [ok for ok, _ in got] == [True, True, True]


def test_the_baked_rule_fails_when_the_scale_drifts():
    # 0.02 mm, twice the stated tolerance. A rule that could not see this
    # would let a unit-conversion regression through.
    got = run_mpfb_probe.verdicts({"export_stature_m": AUTHORED},
                                  _unity(baked=AUTHORED + 0.00002))
    assert got[0][0] is False


def test_the_baked_rule_still_passes_inside_tolerance():
    got = run_mpfb_probe.verdicts({"export_stature_m": AUTHORED},
                                  _unity(baked=AUTHORED + 0.000005))
    assert got[0][0] is True


def test_the_trap_rules_fail_when_the_trap_stops_being_real():
    # Rules 2 and 3 are asserted as expected FAILURES. If MPFB or Unity ever
    # starts handling those cases correctly, the script must say so rather
    # than keep warning about a trap that no longer exists. This is the test
    # that makes that claim true.
    fixed = run_mpfb_probe.verdicts({"export_stature_m": AUTHORED},
                                    _unity(rigged=AUTHORED, norig=AUTHORED))
    assert fixed[1][0] is False, "an un-baked FBX that now measures right"
    assert fixed[2][0] is False, "an un-rigged FBX that now measures right"
    assert "NO LONGER TRUE" in fixed[1][1]
    assert "NO LONGER TRUE" in fixed[2][1]


def test_missing_measurements_fail_rather_than_pass_quietly():
    got = run_mpfb_probe.verdicts({"export_stature_m": AUTHORED}, {})
    assert [ok for ok, _ in got] == [False, False, False]
    assert all("no vertices" in message for _, message in got)


# ---------------------------------------------------------------------
# the ethnicity presets, which are a calibration decision
# ---------------------------------------------------------------------

def test_the_ethnicity_presets_are_normalised_choices():
    # Imported from the source text rather than from the module: blender_probe
    # imports bpy at module scope and cannot be imported outside Blender, which
    # is itself asserted below.
    source = (REPO / "mpfb" / "blender_probe.py").read_text(encoding="utf-8")
    namespace: dict = {}
    start = source.index("ETHNICITY_PRESETS = {")
    end = source.index("}", start) + 1
    exec(source[start:end], namespace)  # noqa: S102 -- our own literal
    presets = namespace["ETHNICITY_PRESETS"]

    assert "even_thirds" in presets, "the shipped default must exist"
    for name, macros in presets.items():
        assert set(macros) == {"african", "asian", "caucasian"}, name
        assert all(0.0 <= v <= 1.0 for v in macros.values()), name


def test_blender_probe_cannot_be_imported_outside_blender():
    # mpfb/__init__.py documents this as deliberate: importing bpy at module
    # scope means a pytest run fails loudly instead of silently measuring
    # nothing. The claim is worth an assertion because it is the kind of thing
    # a later refactor "tidies up".
    with pytest.raises(ImportError):
        import mpfb.blender_probe  # noqa: F401


# ---------------------------------------------------------------------
# source rules over the generated C#
# ---------------------------------------------------------------------
#
# The C# in mpfb/*.py is a string literal, so nothing above can reach it, and
# the backdrop bug lived exactly there: a sabotage that restored `pixels[0]`
# passed every test in this file. These are source rules in the same spirit as
# tests/test_unity_contract.py, which is already how this repository pins C# it
# cannot execute from pytest. They prove what the code SAYS, never what it
# does; the doing is what run_mpfb_probe.py checks.

def _source(name: str) -> str:
    return (REPO / "mpfb" / name).read_text(encoding="utf-8")


def test_the_portrait_probe_samples_the_top_corner_for_its_backdrop():
    src = _source("unity_measure.py")
    assert "pixels[(rt.height - 1) * rt.width]" in src, (
        "GetPixels32 starts at the BOTTOM-left, which on a portrait is "
        "shoulder. Sampling pixels[0] as the backdrop reported a white sky "
        "and a 98% subject fraction on a working render.")
    assert "Color32 backdrop = pixels[0];" not in src


def test_every_generated_probe_formats_floats_with_invariant_culture():
    # This machine is tr-TR. A C# float formatted with the ambient culture
    # comes out as "2,662778", and the Python side either throws or reads a
    # thousands separator. Session 20's "4.111 rows" was this bug.
    for name in ("unity_measure.py", "unity_village.py", "unity_perf.py"):
        src = _source(name)
        if "ToString(" not in src:
            continue
        assert "InvariantCulture" in src, name


def test_the_perf_probe_waits_for_the_gpu():
    # Camera.Render only submits. Timing it alone reported real human meshes
    # as FASTER than primitives, with a ratio that was not monotone in N.
    src = _source("unity_perf.py")
    assert "RenderAndSync" in src
    assert "ReadPixels" in src, "without a readback the timing is submission only"


def test_the_village_probe_invokes_awake_because_editmode_does_not():
    # Awake runs only on ExecuteAlways classes, and WorldRenderer is not one.
    # Without this the shot is an empty field and the log looks healthy.
    src = _source("unity_village.py")
    assert 'Invoke(renderer, "Awake")' in src


def test_the_village_probe_qualifies_the_packages_scene_setup():
    # UnityEditor.SceneManagement also has a SceneSetup; the ambiguity is a
    # compile error, which is at least loud, but it cost a run.
    src = _source("unity_village.py")
    assert "ExtNPC.Editor.SceneSetup.CreateViewer()" in src
