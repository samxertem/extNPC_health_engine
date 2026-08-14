"""
The Unity loader's column names, checked against a real export.
================================================================

The C# viewer in `unity/com.samal.extnpc` cannot be compiled or run from
pytest -- that needs a Unity installation. But the failure mode that actually
matters here is not a compile error, which the Unity editor would catch
immediately. It is a **column-name typo**: `RequireIndex("pedigree_F")` when
the engine writes `pedigree_f`. That compiles perfectly, and fails only at
runtime, only on a machine with Unity, only once someone loads a bundle.

Worse, it is a defect the C# side cannot diagnose. From Unity's point of view
the column is simply absent, and "absent" is indistinguishable from "the
engine stopped exporting it".

So this module reads the C# source as text, extracts every column name it
asks for, and asserts each one exists in an actual export. It is a contract
test across a language boundary, and it runs in the normal suite with no
Unity involved.

It also runs the other way: the four declared table schemas in
`export.FRAME_COLUMNS` and friends must all be *consumed* or at least
*present*, so a column the engine adds does not sit unnoticed forever.

WHAT THIS DOES NOT CHECK: that the C# compiles, that the parsing is correct,
or that the rendering is right. Those need Unity. This checks the one thing
that can be checked from here, and it is the thing most likely to be wrong.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Dict, Set

import pytest

from simulation import DemographyParams, World
from simulation import export as EX

warnings.filterwarnings("ignore")

UNITY_ROOT = Path(__file__).parent.parent / "unity" / "com.samal.extnpc"
LOADER = UNITY_ROOT / "Runtime" / "Data" / "WorldBundle.cs"

# Which file each loader method reads. The C# is one class with one method per
# table, so the column requests are grouped by method and can be attributed.
_METHOD_TO_TABLE = {
    "LoadFrames": "frames.csv",
    "LoadDemes": "demes.csv",
    "LoadFlows": "flows.csv",
    "LoadEvents": "events.csv",
    "LoadHistory": "history.csv",
    "LoadPeople": "people.csv",
    "LoadDiseases": "diseases.csv",
}

_REQUIRE = re.compile(r'RequireIndex\("([^"]+)"\)')
_GETRAW = re.compile(r'\bG\("([^"]+)"\)')
# Any static method, whatever its accessibility. It was `private static` only,
# which was enough while every rule here read a loader; the rounding rule reads
# a public one. Widening it can only make a slice TIGHTER -- the boundaries are
# method definitions and methods do not nest -- so the existing rules are
# unaffected, which the rest of this module's 176 checks confirm.
_METHOD = re.compile(r'(?:public|private|internal|protected) static '
                     r'\w[\w<>,\[\] ]* (\w+)\(')


_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"//[^\n]*")


def code_only(src: str) -> str:
    """`src` with comments removed.

    Every rule in this module scans source as text, and the first version
    scanned comments too -- so the doc comment *explaining* that
    `trait_height_cm` must not be used tripped the rule forbidding it. A
    checker that punishes its own documentation trains people to delete the
    documentation.

    Crude by design: it does not respect string literals, so a `//` inside a
    string would be truncated. There are none in this package, and the rules
    below only look for identifiers.
    """
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", src))


def _method_body(src: str, name: str) -> str:
    """Source of the named method.

    Split on the DEFINITION, not the first textual occurrence -- every loader
    is called from Load() before it is defined, so a naive `split(name)` lands
    on the call site and yields a few characters of the wrong thing. The first
    version of this helper did exactly that and the test failed loudly, which
    is the only reason it is a function now.
    """
    bounds = [(m.start(), m.group(1)) for m in _METHOD.finditer(src)]
    bounds.append((len(src), "__end__"))
    for (start, found), (end, _) in zip(bounds, bounds[1:]):
        if found == name:
            return src[start:end]
    raise AssertionError(f"method {name} not found in the loader source")


@pytest.fixture(scope="module")
def exported(tmp_path_factory) -> Path:
    """A real bundle with structure, so flows.csv and demes.csv are populated
    rather than header-only -- a contract check against an empty table would
    prove nothing."""
    w = World(n_founders=14, seed=11,
              params=DemographyParams(n_demes=3, migration_rate=0.10))
    for _ in range(25):
        w.step()
    return EX.export_world_dir(w, tmp_path_factory.mktemp("unity") / "world")


@pytest.fixture(scope="module")
def headers(exported) -> Dict[str, Set[str]]:
    out: Dict[str, Set[str]] = {}
    for csv_file in exported.glob("*.csv"):
        first = csv_file.read_text(encoding="utf-8").split("\n", 1)[0]
        out[csv_file.name] = set(first.split(",")) if first else set()
    return out


@pytest.fixture(scope="module")
def requested() -> Dict[str, Set[str]]:
    """Column names the C# loader asks for, grouped by the table it reads."""
    if not LOADER.exists():
        pytest.skip(f"Unity package not present at {LOADER}")

    src = LOADER.read_text(encoding="utf-8")
    out: Dict[str, Set[str]] = {}
    for method, table in _METHOD_TO_TABLE.items():
        body = _method_body(src, method)
        out[table] = set(_REQUIRE.findall(body)) | set(_GETRAW.findall(body))
    return out


def test_the_unity_package_is_where_the_plan_says_it_is():
    assert UNITY_ROOT.is_dir(), f"no Unity package at {UNITY_ROOT}"
    assert (UNITY_ROOT / "package.json").exists()
    assert LOADER.exists()


def test_the_loader_asks_for_columns_from_every_table(requested):
    """A guard on this test itself: if the regexes stop matching, every
    assertion below passes vacuously."""
    assert requested["frames.csv"], "no column requests parsed for frames.csv"
    assert requested["people.csv"], "no column requests parsed for people.csv"
    assert len(requested["frames.csv"]) >= 15, (
        f"only {len(requested['frames.csv'])} frame columns parsed -- the "
        f"source-scanning regex has probably stopped matching")


@pytest.mark.parametrize("table", sorted(_METHOD_TO_TABLE.values()))
def test_every_column_the_viewer_requires_exists_in_the_export(
        table, requested, headers):
    """The whole point. A typo here is invisible to C# and to the engine."""
    missing = sorted(requested[table] - headers[table])
    assert not missing, (
        f"unity/com.samal.extnpc asks {table} for column(s) {missing}, which "
        f"the engine does not export. Header is: "
        f"{sorted(headers[table])}")


def test_the_declared_schemas_match_the_exported_headers(headers):
    """export.py declares FRAME_COLUMNS etc. so an empty table still writes a
    header. That only holds if the declarations match reality."""
    for table, columns in (("frames.csv", EX.FRAME_COLUMNS),
                           ("demes.csv", EX.DEME_COLUMNS),
                           ("flows.csv", EX.FLOW_COLUMNS),
                           ("events.csv", EX.EVENT_COLUMNS),
                           ("diseases.csv", EX.DISEASE_COLUMNS)):
        assert headers[table] == set(columns), (
            f"{table} header does not match its declared schema")


def test_the_viewer_reads_age_expressed_stature_not_the_mature_trait():
    """A specific, checkable instance of invariant 6: `height` in frames.csv
    is the stature expressed at that age, while people.csv's
    `trait_height_cm` is the mature phenotype. A viewer that reached for the
    trait column would draw children adult-sized -- the exact defect session
    13 found in the dashboard's BMI readout."""
    frames = _method_body(code_only(LOADER.read_text(encoding="utf-8")), "LoadFrames")
    assert 'RequireIndex("height")' in frames
    assert "trait_height_cm" not in frames


def test_the_viewer_parses_the_lineage_colour_rather_than_recomputing_it():
    """Colour is defined once, in lineage.py, and travels in the data. A C#
    reimplementation of the HSV rule would be a second definition that can
    drift, and the two UIs would eventually colour a villager differently."""
    src = code_only((UNITY_ROOT / "Runtime" / "Data" / "CsvParse.cs").read_text(encoding="utf-8"))
    assert "TryParseHtmlString" in src, "colour is not parsed from the data"
    for invented in ("HSVToRGB", "HsvToRgb"):
        assert invented not in src, (
            f"{invented} in the viewer means the lineage colour rule has been "
            f"reimplemented in C#; it must be read from the data instead")


def test_the_map_projection_agrees_with_the_engines_map_size():
    """MapProjection.MapSize must equal community.MAP_SIZE or every villager
    is offset by half the difference -- a mirror-image world that looks
    plausible until you compare it with the dashboard."""
    from simulation.community import MAP_SIZE
    src = (UNITY_ROOT / "Runtime" / "Core" / "MapProjection.cs").read_text(
        encoding="utf-8")
    m = re.search(r"MapSize\s*=\s*([0-9.]+)f", src)
    assert m, "MapProjection.MapSize not found"
    assert float(m.group(1)) == float(MAP_SIZE), (
        f"MapProjection.MapSize={m.group(1)} but community.MAP_SIZE={MAP_SIZE}")


def test_the_viewer_refuses_a_schema_it_does_not_know():
    """A reshaped table parses 'successfully' into wrong values. Refusing is
    the only safe response, so the supported version must track the engine."""
    src = (UNITY_ROOT / "Runtime" / "Data" / "Manifest.cs").read_text(encoding="utf-8")
    m = re.search(r"SupportedSchema\s*=\s*(\d+)", src)
    assert m, "Manifest.SupportedSchema not found"
    assert int(m.group(1)) == EX.BUNDLE_SCHEMA, (
        f"viewer supports schema {m.group(1)} but export.BUNDLE_SCHEMA is "
        f"{EX.BUNDLE_SCHEMA}")


# ---------------------------------------------------------------------
# Locale safety, checked as a source-level rule
# ---------------------------------------------------------------------
# The owner's machine uses a comma decimal separator. That is not a
# hypothetical: the first in-editor run of the loader printed "4.111 rows"
# for 4,111 rows, because an interpolated $"{n:N0}" formats with the
# AMBIENT culture. The parsing side was already invariant, which is the only
# reason the load produced correct numbers at all -- under the ambient
# culture float.Parse("1.75") returns 175, and does not throw.
#
# So both directions are now a rule rather than a habit, enforced here
# because C# will never complain about either.

_CS_FILES = sorted(UNITY_ROOT.rglob("*.cs")) if UNITY_ROOT.is_dir() else []

# {value:N0}, {value:F2}, {value:P1}, {value:C} inside an interpolated string.
_INTERP_NUMERIC_FORMAT = re.compile(r'\$"[^"\n]*\{[^}\n]*:[NFPCnfpc]\d*[^}\n]*\}')

# float.Parse / double.TryParse / int.Parse ... but NOT Manifest.Parse.
_NUMERIC_PARSE = re.compile(r'\b(?:float|double|int|long|decimal)\.(?:Try)?Parse\s*\(')


def test_there_are_c_sharp_sources_to_check():
    """Guard: without this, every rule below passes vacuously."""
    assert _CS_FILES, f"no .cs files found under {UNITY_ROOT}"


@pytest.mark.parametrize("path", _CS_FILES, ids=lambda p: p.name)
def test_no_interpolated_string_uses_a_culture_sensitive_number_format(path):
    """$"{n:N0}" formats with CurrentCulture. Use string.Format with
    CultureInfo.InvariantCulture instead, so a diagnostic reads the same on
    every machine -- "4.111 rows" is four thousand on one and four-point-one
    on another, and people quote these lines at each other."""
    hits = _INTERP_NUMERIC_FORMAT.findall(code_only(path.read_text(encoding="utf-8")))
    assert not hits, (
        f"{path.name} interpolates a culture-sensitive numeric format: {hits}. "
        f"Use string.Format(CultureInfo.InvariantCulture, ...).")


@pytest.mark.parametrize("path", _CS_FILES, ids=lambda p: p.name)
def test_numeric_parsing_is_always_culture_invariant(path):
    """The engine writes 1.75 with a dot. Parsed under a comma-decimal
    culture that is 175 -- silently, with no exception. Every file that
    parses a number must therefore name InvariantCulture."""
    text = code_only(path.read_text(encoding="utf-8"))
    if not _NUMERIC_PARSE.search(text):
        return
    assert "InvariantCulture" in text, (
        f"{path.name} parses numbers without naming CultureInfo."
        f"InvariantCulture. On a comma-decimal machine this reads 1.75 as 175 "
        f"and does not throw.")


# ---------------------------------------------------------------------
# The determinism rule, enforced at the source level
# ---------------------------------------------------------------------
# UNITY_PLAN.md invariant 5: every number the viewer displays came from a
# file, and the visual layer is a pure function of the exported data.
#
# The tempting violation is small and looks harmless: a little positional
# jitter so villagers do not overlap, a random tint so a crowd reads better,
# a random pick among idle animations. Each one invents variance the engine
# did not model, and the invented variance is indistinguishable on screen
# from variance the simulation produced. A viewer whose scatter is partly
# real and partly decorative cannot be read as evidence of anything.
#
# The engine already went to some trouble here: community.person_map_offset
# derives an in-territory offset from a CRC32 of the NAME rather than from
# the RNG, precisely so that scatter is deterministic and does not perturb
# the genetic stream. Re-adding randomness in C# would throw that away.

_RUNTIME_DIR = UNITY_ROOT / "Runtime"
_RUNTIME_CS = sorted(_RUNTIME_DIR.rglob("*.cs")) if _RUNTIME_DIR.is_dir() else []

_RANDOMNESS = re.compile(
    r'\b(?:UnityEngine\.)?Random\s*\.'          # UnityEngine.Random.value etc.
    r'|\bnew\s+System\.Random\b'
    r'|\bGuid\.NewGuid\b')


def test_there_are_runtime_sources_to_check():
    """Guard against the rule below passing vacuously."""
    assert _RUNTIME_CS, f"no runtime .cs files under {_RUNTIME_DIR}"
    assert len(_RUNTIME_CS) >= 5


@pytest.mark.parametrize("path", _RUNTIME_CS, ids=lambda p: p.name)
def test_the_visual_layer_draws_no_random_numbers(path):
    """No RNG anywhere in the viewer's runtime. See the note above."""
    hits = _RANDOMNESS.findall(code_only(path.read_text(encoding="utf-8")))
    assert not hits, (
        f"{path.name} uses randomness ({hits}). The viewer must be a pure "
        f"function of the exported data (UNITY_PLAN.md invariant 5): invented "
        f"variance is indistinguishable on screen from simulated variance.")


def test_the_renderer_draws_age_expressed_stature():
    """The same rule the loader is held to, now at the point it becomes a
    visible size. Using the mature trait renders every child adult-sized --
    which looks completely normal, and quietly deletes roadmap #13 from the
    picture."""
    view = UNITY_ROOT / "Runtime" / "View" / "VillagerView.cs"
    if not view.exists():
        pytest.skip("Stage 3 view not present")
    src = code_only(view.read_text(encoding="utf-8"))
    assert "HeightCm" in src, "VillagerView does not read the frame's height"
    assert "trait_height_cm" not in src
    assert "GetTrait" not in src, (
        "VillagerView reads a people.csv trait; frame stature is the "
        "age-expressed value and the two are different quantities")


@pytest.mark.parametrize("path", _RUNTIME_CS, ids=lambda p: p.name)
def test_no_runtime_file_recomputes_the_lineage_colour(path):
    """Colour is defined once, in lineage.py, and parsed from the data."""
    src = code_only(path.read_text(encoding="utf-8"))
    for invented in ("HSVToRGB", "HsvToRgb", "Color.HSVToRGB"):
        assert invented not in src, (
            f"{path.name} reconstructs a colour from HSV. The lineage rule "
            f"(hue=founder, saturation=purity, value=alive) lives in "
            f"simulation/lineage.py and travels in the data as #rrggbb.")


# ---------------------------------------------------------------------
# Input backend neutrality
# ---------------------------------------------------------------------
# A Unity project set to "Input System Package (New)" throws
# InvalidOperationException the instant anything reads UnityEngine.Input;
# a project on the old manager has no Mouse.current. Unity 6 defaults to the
# new backend, so a package that reaches for the legacy class works on the
# author's machine and throws on everyone else's -- which is exactly what
# happened here on first run.
#
# The fix is one compatibility shim. The rule is that it stays ONE: scattered
# #if ENABLE_INPUT_SYSTEM blocks are how a package ends up quietly supporting
# whichever backend its author happened to test.

_INPUT_COMPAT = UNITY_ROOT / "Runtime" / "View" / "InputCompat.cs"

# `Input.` / `UnityEngine.Input.` but NOT InputCompat., InputSystem., etc.
_LEGACY_INPUT = re.compile(r'(?<![A-Za-z0-9_.])(?:UnityEngine\.)?Input\s*\.')
_NEW_INPUT = re.compile(r'\b(?:Mouse|Keyboard|Gamepad)\.current\b')


def test_the_input_shim_exists_and_covers_both_backends():
    """Guard against the per-file rule below passing vacuously."""
    if not _INPUT_COMPAT.exists():
        pytest.skip("Stage 3 view not present")
    src = _INPUT_COMPAT.read_text(encoding="utf-8")
    assert "#if ENABLE_INPUT_SYSTEM" in src, "shim has no new-backend branch"
    assert "#else" in src, "shim has no legacy branch"
    code = code_only(src)
    assert _NEW_INPUT.search(code), "shim never reads the new backend"
    assert _LEGACY_INPUT.search(code), "shim never reads the legacy backend"


# ---------------------------------------------------------------------
# Stage 4: the inspector must describe a villager the way the dashboard does
# ---------------------------------------------------------------------
# UNITY_PLAN.md invariant 6 and the Stage 4 acceptance criterion: "a villager
# must not be described differently by the two UIs". The risk register rates
# this MEDIUM and names the mechanism -- drift. Nobody edits both files.
#
# The mitigation is that every label, threshold and rounding rule lives in one
# C# file, InspectorFormat.cs, each naming the Python line it mirrors. These
# tests are what make that a claim rather than a comment: they read BOTH
# sources as text and compare the numbers and the strings directly, so a
# threshold changed on one side and not the other is a red test rather than a
# quiet disagreement in a drawer nobody has open.

_INSPECTOR_PY = Path(__file__).parent.parent / "dashboard" / "inspector.py"
_PANELS_PY = Path(__file__).parent.parent / "dashboard" / "panels.py"
_FORMAT_CS = UNITY_ROOT / "Runtime" / "View" / "InspectorFormat.cs"
_INSPECTOR_CS = UNITY_ROOT / "Runtime" / "View" / "VillagerInspector.cs"

# (0.25, "full sib / parent-offspring"),   -- Python
_PY_LADDER = re.compile(r'\(\s*([0-9.]+)\s*,\s*"([^"]+)"\s*\)')
# (0.25f,    "full sib / parent-offspring"),   -- C#
_CS_LADDER = re.compile(r'\(\s*([0-9.]+)f\s*,\s*"([^"]+)"\s*\)')


def _stage4_present():
    return _FORMAT_CS.exists() and _INSPECTOR_CS.exists()


def _py_f_labels():
    """`_F_LABELS` out of dashboard/inspector.py, read as text.

    Deliberately not `from dashboard.inspector import _F_LABELS`: that module
    imports dash at the top, and a parity test that silently skips wherever
    dash is absent is a parity test that does not run on the machine most
    likely to have drifted.
    """
    src = _INSPECTOR_PY.read_text(encoding="utf-8")
    m = re.search(r"_F_LABELS[^=]*=\s*\[(.*?)\]", src, re.S)
    assert m, "_F_LABELS not found in dashboard/inspector.py"
    return [(float(t), lab) for t, lab in _PY_LADDER.findall(m.group(1))]


def _cs_f_labels():
    src = code_only(_FORMAT_CS.read_text(encoding="utf-8"))
    m = re.search(r"FLabels\s*=\s*\{(.*?)\};", src, re.S)
    assert m, "FLabels table not found in InspectorFormat.cs"
    return [(float(t), lab) for t, lab in _CS_LADDER.findall(m.group(1))]


def test_stage_four_sources_exist():
    """Guard: every parity rule below is vacuous without these two files."""
    if not _stage4_present():
        pytest.skip("Stage 4 inspector not present")
    assert _INSPECTOR_PY.exists(), "dashboard/inspector.py is the parity source"


def test_the_relationship_ladder_is_identical_on_both_sides():
    """
    The wording AND the thresholds, in order.

    Pedigree F is meaningless to most readers as a bare number, so both UIs
    label it with the mating that produces it. If Unity said "first cousins"
    where the dashboard said "uncle-niece", the two would be making different
    claims about the same villager's parents -- which is a scientific
    disagreement wearing the clothes of a formatting bug.
    """
    if not _stage4_present():
        pytest.skip("Stage 4 inspector not present")
    py, cs = _py_f_labels(), _cs_f_labels()
    assert py, "no ladder parsed from inspector.py -- the regex has rotted"
    assert cs == py, (
        f"the relationship ladders disagree.\n"
        f"  dashboard/inspector.py : {py}\n"
        f"  InspectorFormat.cs     : {cs}")


def test_the_relationship_ladder_is_descending():
    """A guard on the ladder itself: the scan returns the FIRST match, so an
    out-of-order entry silently shadows every threshold below it."""
    if not _stage4_present():
        pytest.skip("Stage 4 inspector not present")
    thresholds = [t for t, _ in _cs_f_labels()]
    assert thresholds == sorted(thresholds, reverse=True), (
        f"C# ladder is not descending: {thresholds}. The first match wins, so "
        f"an out-of-order row makes the rows under it unreachable.")


def test_the_inbreeding_colour_thresholds_match_the_dashboard():
    """`_f_color` marks first cousins (0.0625) critical and second cousins
    (0.015625) warning. Two UIs colouring the same F differently is the
    version of drift a reader is least likely to notice and most likely to
    quote."""
    if not _stage4_present():
        pytest.skip("Stage 4 inspector not present")

    py_src = code_only(_INSPECTOR_PY.read_text(encoding="utf-8"))
    m = re.search(r"def _f_color.*?(?=\ndef )", py_src, re.S)
    assert m, "_f_color not found in dashboard/inspector.py"
    py_thresholds = sorted(float(x) for x in re.findall(r"[0-9]*\.[0-9]+",
                                                        m.group(0)))

    cs_src = code_only(_FORMAT_CS.read_text(encoding="utf-8"))
    # `(double f)` since Stage 5: the display path parses at binary64 so the
    # two UIs hold the same number. The THRESHOLDS this rule compares are
    # unchanged, and are still written with an f suffix because 0.0625 and
    # 0.015625 are exact in both widths.
    m = re.search(r"FColor\s*\((?:float|double) f\)\s*\{(.*?)\n        \}",
                  cs_src, re.S)
    assert m, "FColor not found in InspectorFormat.cs"
    cs_thresholds = sorted(float(x) for x in re.findall(r"([0-9]*\.[0-9]+)f",
                                                        m.group(1)))

    assert cs_thresholds == py_thresholds, (
        f"_f_color thresholds {py_thresholds} but FColor uses {cs_thresholds}")


def test_the_palette_hexes_match_the_dashboard():
    """Colours are named in InspectorFormat as hex STRINGS precisely so this
    comparison is possible; an (r,g,b) triple could not be checked against
    '#d03b3b' without a human doing the conversion."""
    if not _stage4_present():
        pytest.skip("Stage 4 inspector not present")

    panels = _PANELS_PY.read_text(encoding="utf-8")
    cs = _FORMAT_CS.read_text(encoding="utf-8")

    for py_name, cs_name in (("INK", "InkHex"), ("INK2", "Ink2Hex"),
                             ("MUTED", "MutedHex"), ("GRID", "GridHex"),
                             ("SURFACE", "SurfaceHex"), ("PLANE", "PlaneHex"),
                             ("GOOD", "GoodHex"), ("CRIT", "CritHex"),
                             ("WARN", "WarnHex"), ("ACCENT", "AccentHex")):
        m = re.search(rf'^{py_name}\s*=\s*"(#[0-9a-fA-F]{{6}})"', panels, re.M)
        assert m, f"{py_name} not found in dashboard/panels.py"
        expected = m.group(1).lower()

        m2 = re.search(rf'{cs_name}\s*=\s*"(#[0-9a-fA-F]{{6}})"', cs)
        assert m2, f"{cs_name} not found in InspectorFormat.cs"
        assert m2.group(1).lower() == expected, (
            f"{py_name} is {expected} in the dashboard but {cs_name} is "
            f"{m2.group(1)} in the viewer")


def test_the_viewer_never_formats_a_percentage_with_the_dotnet_specifier():
    """
    A parity trap with no symptom.

    Python's f"{p:.0%}" gives "50%". C#'s ToString("P0", InvariantCulture)
    gives "50 %" -- invariant culture's percent pattern inserts a space. Both
    look right in isolation, and the acceptance criterion for this stage is a
    CHARACTER-FOR-CHARACTER match, so the near-miss is the whole failure.
    Percentages are formatted as F0 on a x100 value instead.
    """
    if not _stage4_present():
        pytest.skip("Stage 4 inspector not present")

    # BOTH spellings, because the first version of this rule only caught the
    # composite one and a deliberate sabotage using ToString("P0", Inv) --
    # much the likelier way to write it -- sailed straight through.
    composite = re.compile(r'\{\s*\d+\s*:\s*[Pp]\d*\s*\}')   # "{0:P0}"
    direct = re.compile(r'ToString\s*\(\s*"[Pp]\d*"')        # ToString("P0", ..)

    for path in (_FORMAT_CS, _INSPECTOR_CS):
        src = code_only(path.read_text(encoding="utf-8"))
        hits = composite.findall(src) + direct.findall(src)
        assert not hits, (
            f"{path.name} formats with the .NET percent specifier {hits}. "
            f"That renders '50 %' where the dashboard renders '50%'.")


def test_the_inspector_does_not_rebuild_the_settlement_name_table():
    """`community.deme_label` maps an id onto a fixed name table. A copy of
    that table in C# is a second definition that goes stale the moment a name
    is appended -- so the label travels in demes.csv instead."""
    if not _stage4_present():
        pytest.skip("Stage 4 inspector not present")
    from simulation.community import DEME_NAMES

    src = code_only(_INSPECTOR_CS.read_text(encoding="utf-8"))
    for name in DEME_NAMES[:6]:
        assert f'"{name}"' not in src, (
            f"VillagerInspector.cs contains the settlement name '{name}'. "
            f"Read demes.csv's `label` column instead of rebuilding "
            f"community.DEME_NAMES in C#.")


def test_the_settlement_label_is_actually_exported(headers):
    """The other half of the rule above: forbidding the C# copy is only
    reasonable if the column really is there to read."""
    assert "label" in headers["demes.csv"], (
        "demes.csv has no `label` column, so the viewer has no way to name a "
        "settlement without reimplementing community.deme_label")


def test_the_disease_panel_resolves_every_slug_people_csv_can_emit():
    """
    people.csv names disorders by slug; the dashboard shows the GENE and the
    display name (inspector.py:171). Neither is derivable from the slug, so
    diseases.csv has to carry every slug that can appear -- otherwise the
    viewer falls back to printing 'gjb2_deafness' at a reader who was promised
    'dx GJB2'.
    """
    from health_engine.diseases import DISEASES

    rows = EX.disease_rows()
    by_name = {r["name"]: r for r in rows}
    assert len(rows) == len(DISEASES)
    for d in DISEASES:
        assert d.spec.name in by_name, f"{d.spec.name} missing from diseases.csv"
        assert by_name[d.spec.name]["gene"] == d.spec.gene
        assert by_name[d.spec.name]["label"] == d.spec.label


def test_the_disease_table_records_both_frequencies():
    """q_lit and q_engine are both exported because they DISAGREE -- the
    engine's frequency for a disorder is its assigned spectrum locus's, and
    cystic fibrosis is a documented misfit. A table carrying only one of them
    would let a reader assume there was nothing to know."""
    rows = {r["name"]: r for r in EX.disease_rows()}
    cf = rows["cystic_fibrosis"]
    assert cf["q_lit"] > 0 and cf["q_engine"] > 0
    assert cf["q_lit"] != cf["q_engine"], (
        "q_lit == q_engine for cystic fibrosis, which contradicts the "
        "documented misfit in health_engine/diseases.py -- either the "
        "assignment changed or this column is not what it claims")


def test_every_people_column_the_inspector_reads_exists(headers):
    """
    The same rule the loader is held to, now for the panel.

    The inspector reaches into people.csv by name through GetRaw / GetTrait,
    which is exactly the failure this module was written for: `GetRaw
    ("hidden_load_allele")` compiles, and from C#'s side the absent column is
    indistinguishable from the engine having stopped exporting it.
    """
    if not _stage4_present():
        pytest.skip("Stage 4 inspector not present")
    src = code_only(_INSPECTOR_CS.read_text(encoding="utf-8"))

    wanted = set(re.findall(r'GetRaw\("([^"]+)"\)', src))
    wanted |= {"trait_" + t for t in re.findall(r'GetTrait\("([^"]+)"\)', src)}
    assert wanted, "no people.csv column requests parsed from the inspector"

    missing = sorted(wanted - headers["people.csv"])
    assert not missing, (
        f"VillagerInspector.cs reads people.csv column(s) {missing}, which the "
        f"engine does not export.")


def test_the_inspector_refuses_peoplecsv_in_historical_mode():
    """
    §2.1, the constraint snapshots.py imposes and the viewer inherits.

    people.csv is CROSS-SECTIONAL -- each row is the individual as they are
    NOW, or as they were at death. Joining it to a year-40 frame would
    describe a year-40 villager with year-90 genetics and show no seam at all.
    The guard is one method, so this asserts the guard is still in it.
    """
    if not _stage4_present():
        pytest.skip("Stage 4 inspector not present")
    src = code_only(_INSPECTOR_CS.read_text(encoding="utf-8"))
    m = re.search(r"PersonRow LivePerson\(\)\s*\{(.*?)\n        \}", src, re.S)
    assert m, "VillagerInspector.LivePerson not found"
    assert "IsHistorical" in m.group(1), (
        "LivePerson() no longer checks IsHistorical, so the inspector can "
        "join today's people.csv row onto a past tick's frame")


def test_the_inspector_marks_historical_mode_visibly():
    """Silent degradation is the failure mode: a thinner panel reads as a
    villager with less going on, not a year with less recorded."""
    if not _stage4_present():
        pytest.skip("Stage 4 inspector not present")
    src = _INSPECTOR_CS.read_text(encoding="utf-8")
    assert "historical view" in src, (
        "no historical-mode banner in VillagerInspector.cs")


def test_the_stature_cost_of_inbreeding_is_exported_not_recomputed(headers):
    """
    The engine's second cost of inbreeding, and a column rather than a
    calculation on purpose.

    `predicted_depression` is a model (Joshi 2015 directional dominance), not a
    formatting rule. A viewer that reproduced it in C# would be doing biology,
    which UNITY_PLAN.md invariant 5 forbids outright.
    """
    assert "stature_cost_cm" in headers["people.csv"]
    if not _stage4_present():
        return
    for path in (_FORMAT_CS, _INSPECTOR_CS):
        src = code_only(path.read_text(encoding="utf-8"))
        for forbidden in ("predicted_depression", "PredictedDepression",
                          "lethal_equivalents"):
            assert forbidden not in src, (
                f"{path.name} looks like it reimplements {forbidden}; the "
                f"value is exported as a column and must be read")


def test_the_stature_cost_is_zero_for_the_outbred_and_negative_otherwise():
    """A check on the column's meaning, not just its presence. Directional
    dominance makes inbred individuals SHORTER, so a positive value would mean
    the sign convention had flipped somewhere between the engine and the
    column."""
    assert EX._stature_cost(0.0) == 0.0
    assert EX._stature_cost(0.0625) < 0.0
    assert EX._stature_cost(0.25) < EX._stature_cost(0.0625), (
        "a more inbred individual must carry a larger stature cost")


@pytest.mark.parametrize("path", _RUNTIME_CS, ids=lambda p: p.name)
def test_only_the_shim_touches_an_input_backend_directly(path):
    """Everything else goes through InputCompat."""
    if path.name == "InputCompat.cs":
        return
    code = code_only(path.read_text(encoding="utf-8"))
    assert not _LEGACY_INPUT.search(code), (
        f"{path.name} reads UnityEngine.Input directly. That throws in any "
        f"project using the Input System package (Unity 6's default). Use "
        f"ExtNPC.View.InputCompat.")
    assert not _NEW_INPUT.search(code), (
        f"{path.name} reads the Input System directly. That is null in any "
        f"project on the legacy input manager. Use ExtNPC.View.InputCompat.")


# ---------------------------------------------------------------------
# Stage 5: the timeline, the KPI strip, and the width of a parsed number
# ---------------------------------------------------------------------
# Stage 5 puts five of the dashboard's own stat tiles on screen and gives the
# viewer a clock. Three new ways to disagree come with that, and each gets a
# rule here:
#
#   1. The TILES can drift -- a label, a decimal count, or (worst) one of the
#      two em-dash rules quietly becoming a 0.000 that claims a measurement
#      nobody made.
#   2. The CLOCK can invent biology. Interpolating a position between two
#      years is cosmetic and labelled; interpolating a stature would draw a
#      growth curve the engine did not compute, and it would look exactly like
#      roadmap #13's real one.
#   3. The PARSE WIDTH can put the two UIs on different numbers. This one is
#      not hypothetical: it was measured this session, see below.

_TIMELINE_CS = UNITY_ROOT / "Runtime" / "View" / "TimelineFormat.cs"
_HUD_CS = UNITY_ROOT / "Runtime" / "View" / "TimelineHud.cs"
_CLOCK_CS = UNITY_ROOT / "Runtime" / "View" / "WorldClock.cs"
_RIBBON_CS = UNITY_ROOT / "Runtime" / "View" / "FlowRibbonView.cs"
_RENDERER_CS = UNITY_ROOT / "Runtime" / "View" / "WorldRenderer.cs"
_APP_PY = Path(__file__).parent.parent / "dashboard" / "app.py"

# key in history.csv -> (dashboard label, C# constant, C# formatter)
_KPI_TILES = {
    "n_alive": ("ALIVE", "AliveLabel", "Alive"),
    "heterozygosity": ("DIVERSITY H", "HeterozygosityLabel", "Heterozygosity"),
    "fst": ("F_ST", "FstLabel", "Fst"),
    "mean_inbreeding": ("INBREEDING F", "InbreedingLabel", "Inbreeding"),
    "lethal_equivalents": ("LOAD B(t)", "LoadLabel", "Load"),
}


def _stage5_present():
    return _TIMELINE_CS.exists() and _HUD_CS.exists() and _CLOCK_CS.exists()


def test_stage_five_sources_exist():
    """Guard: every rule below is vacuous without these three files."""
    if not _stage5_present():
        pytest.skip("Stage 5 timeline not present")
    assert _RIBBON_CS.exists(), "flow ribbons are part of this stage"
    assert _APP_PY.exists(), "dashboard/app.py is the timeline's parity source"


def test_the_kpi_labels_are_the_dashboards_own():
    """
    The five tiles the plan names, spelled as the deck spells them.

    A tile reading "DIVERSITY" in one UI and "DIVERSITY H" in the other is a
    small thing that costs a reader a minute every time they compare the two,
    and there is no mechanism that would ever correct it.
    """
    if not _stage5_present():
        pytest.skip("Stage 5 timeline not present")

    panels = _PANELS_PY.read_text(encoding="utf-8")
    cs = code_only(_TIMELINE_CS.read_text(encoding="utf-8"))

    for key, (label, const, _) in _KPI_TILES.items():
        m = re.search(rf'key="{re.escape(key)}",\s*label="([^"]+)"', panels)
        assert m, f"panels.py has no kpi tile for {key}"
        assert m.group(1) == label, (
            f"the dashboard now labels {key} '{m.group(1)}', not '{label}' -- "
            f"update TimelineFormat.{const} in the same commit")
        assert re.search(rf'{const}\s*=\s*"{re.escape(label)}"', cs), (
            f"TimelineFormat.{const} is not '{label}'")


def test_the_two_em_dash_rules_are_intact_on_both_sides():
    """
    The rule with teeth on this panel.

    F_ST with a single deme and B(t) with no measurement are printed as an em
    dash, not a zero, because a displayed 0.000 asserts "this was measured and
    came out zero" -- a different claim from "there was nothing to measure".
    Both are one edit from becoming a plausible-looking number.
    """
    if not _stage5_present():
        pytest.skip("Stage 5 timeline not present")

    panels = _PANELS_PY.read_text(encoding="utf-8")
    # The dashboard's own conditions, as written.
    assert '_n_demes(params) > 1 else "—"' in panels, (
        "panels.py no longer prints an em dash for F_ST in a single-deme "
        "world; TimelineFormat.Fst must follow")
    assert '_last(cols, "lethal_equivalents", 0.0) > 0.0 else "—"' in panels, (
        "panels.py no longer prints an em dash for an unmeasurable B(t); "
        "TimelineFormat.Load must follow")

    cs = code_only(_TIMELINE_CS.read_text(encoding="utf-8"))
    assert re.search(r'Unmeasurable\s*=\s*"—"', cs), (
        "TimelineFormat.Unmeasurable is not an em dash (U+2014). A hyphen "
        "looks almost identical and is a silent parity break.")

    fst = re.search(r"string Fst\(double fst, int nDemes\) =>(.*?);", cs, re.S)
    assert fst, "TimelineFormat.Fst not found"
    assert "nDemes > 1" in fst.group(1), (
        "Fst no longer decides on the DEME COUNT. Deciding on the value "
        "instead would print an em dash for a real, measured F_ST of zero.")
    assert "Unmeasurable" in fst.group(1)

    load = re.search(r"string Load\(double b\) =>(.*?);", cs, re.S)
    assert load, "TimelineFormat.Load not found"
    assert "b > 0.0" in load.group(1) and "Unmeasurable" in load.group(1)


def test_every_history_column_the_hud_prints_exists(headers):
    """
    The same rule the loader and the inspector are held to.

    `Get("mean_inbreeding")` against a column the engine calls something else
    returns the fallback silently, and a HUD confidently printing 0.0000 for
    the mean inbreeding of a consanguineous village is worse than one that
    fails to draw.
    """
    if not _stage5_present():
        pytest.skip("Stage 5 timeline not present")
    src = code_only(_HUD_CS.read_text(encoding="utf-8"))

    wanted = set(re.findall(r'\.Get\("([^"]+)"', src))
    assert wanted, "no history.csv column requests parsed from the HUD"

    missing = sorted(wanted - headers["history.csv"])
    assert not missing, (
        f"TimelineHud.cs reads history.csv column(s) {missing}, which the "
        f"engine does not export.")

    # ...and it prints the five the plan names, no more: the HUD is numbers
    # only, and a sixth series creeping in is how a viewer starts becoming a
    # second, worse dashboard (UNITY_PLAN.md 0.1).
    assert wanted == set(_KPI_TILES), (
        f"the HUD reads {sorted(wanted)}; Stage 5 specifies exactly "
        f"{sorted(_KPI_TILES)}. Charts belong in the dashboard.")


def test_the_timeline_state_wording_matches_the_dashboards():
    """The LIVE / VIEWING YEAR banner is app.py:2010-2012. Both UIs tell the
    reader the same thing about where they are in time."""
    if not _stage5_present():
        pytest.skip("Stage 5 timeline not present")

    app = _APP_PY.read_text(encoding="utf-8")
    cs = _TIMELINE_CS.read_text(encoding="utf-8")

    assert "● LIVE" in app and "● LIVE" in cs
    m = re.search(r'f"(⏱ VIEWING YEAR \{scrub\}[^"]*)"', app)
    assert m, "the dashboard's scrub-state string has changed shape"
    expected = m.group(1).replace("{scrub}", "{0}")
    assert expected in cs, (
        f"the dashboard says '{expected}' and TimelineFormat does not")

    # The event note, app.py:2018-2019.
    assert "f\"y{e['tick']} {e['label']}\"" in app
    assert '"y{0} {1}"' in cs, "the HUD spells an event differently"
    m = re.search(r'note = \("([^"]+)', app)
    assert m, "the dashboard's no-events note has changed shape"
    m2 = re.search(r'NoEventsNote\s*=\s*"([^"]+)"', cs)
    assert m2, "TimelineFormat.NoEventsNote not found"
    assert m.group(1).startswith(m2.group(1)), (
        f"the viewer's no-events note '{m2.group(1)}' is not the opening of "
        f"the dashboard's '{m.group(1)}'")


def test_the_event_markers_are_the_dashboards_colour():
    """app.py:1976 marks events in CRIT. The glyphs are deliberately not
    mirrored -- the built-in font has no biohazard sign -- but the colour and
    the position carry the same claim and cost nothing to keep."""
    if not _stage5_present():
        pytest.skip("Stage 5 timeline not present")
    app = _APP_PY.read_text(encoding="utf-8")
    m = re.search(r'marks\[t\] = \{"label": icons\.get\(e\["kind"\], "[^"]+"\),\s*'
                  r'"style": \{"color": (\w+)', app)
    assert m, "the dashboard's event marker style has changed shape"
    assert m.group(1) == "CRIT"
    cs = code_only(_TIMELINE_CS.read_text(encoding="utf-8"))
    assert re.search(r"EventMarkerColor\s*=>\s*InspectorFormat\.Crit", cs), (
        "the viewer's event markers are no longer CRIT")


# ---------------------------------------------------------------------
# The interpolation rule
# ---------------------------------------------------------------------
# UNITY_PLAN.md Stage 5 names inter-tick motion as "the one place a viewer can
# imply biology that did not happen". Position is the agreed exception and is
# labelled on screen. Every other frame field is a MEASUREMENT: a stature that
# eased between two years would draw a growth curve the engine did not compute
# and would be indistinguishable from roadmap #13's real one; an eased stress
# level would invent a physiological trajectory outright.

_FRAME_MEASUREMENTS = ("HeightCm", "Stress", "EpiAccel", "Aerobic", "PedigreeF",
                       "Viability", "Purity", "Age", "Children", "Conditions",
                       "Cnv", "Generation")
_MEASUREMENT_REF = re.compile(r"\.(" + "|".join(_FRAME_MEASUREMENTS) + r")\b")
_LERP_CALL = re.compile(r"\bLerp\s*\(")


def _lerp_endpoints(src: str):
    """The first two arguments of every `Lerp(` call in `src`.

    THE FIRST VERSION OF THIS RULE WAS A ONE-LINE REGEX and a deliberate
    sabotage walked straight past it. It required the field to follow `Lerp(`
    immediately -- `Lerp(row.HeightCm, ...)` -- and the sabotage wrote
    `Lerp((float)row.HeightCm, ...)`, which is not a clever evasion but the
    LIKELIER spelling: the display fields are doubles since this session and
    Mathf.Lerp takes floats, so a cast is what anyone would actually type.

    Only the first two arguments are scanned, and that is deliberate too. A
    field in the THIRD argument is a ramp -- DemeRingView tints a ring by its
    dominance share exactly that way -- which is reading a value, not
    inventing one. Interpolating BETWEEN TWO MEASUREMENTS is the forbidden
    thing, and it lives in arguments one and two.
    """
    out = []
    for m in _LERP_CALL.finditer(src):
        i, depth, args, start = m.end(), 0, [], m.end()
        while i < len(src) and len(args) < 2:
            c = src[i]
            if c in "([{":
                depth += 1
            elif c in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif c == "," and depth == 0:
                args.append(src[start:i])
                start = i + 1
            elif c == ";":
                break
            i += 1
        out.append(" ".join(args))
    return out


@pytest.mark.parametrize("path", _RUNTIME_CS, ids=lambda p: p.name)
def test_no_biological_quantity_is_interpolated_between_years(path):
    hits = []
    for endpoints in _lerp_endpoints(code_only(path.read_text(encoding="utf-8"))):
        hits += _MEASUREMENT_REF.findall(endpoints)
    assert not hits, (
        f"{path.name} interpolates {hits} between two ticks. Only POSITION may "
        f"be blended, and only while playback is running: the engine simulated "
        f"year N and year N+1 and nothing in between, so an eased measurement "
        f"is a number the simulation never produced.")


def test_the_cosmetic_motion_disclaimer_reaches_the_screen():
    """A cosmetic blend that is not labelled is just a wrong picture. The
    string has to exist AND be drawn -- a constant nobody renders is a comment
    with extra steps."""
    if not _stage5_present():
        pytest.skip("Stage 5 timeline not present")
    fmt = _TIMELINE_CS.read_text(encoding="utf-8")
    assert "cosmetic" in fmt.lower(), "no cosmetic-motion note in TimelineFormat"
    hud = code_only(_HUD_CS.read_text(encoding="utf-8"))
    assert "CosmeticMotionNote" in hud, (
        "TimelineHud never draws the cosmetic-motion note")


def test_the_clock_only_ever_shows_an_exported_year():
    """The displayed year is read out of the bundle's tick array, never
    computed by adding one to a year. The retained range does not have to
    start at zero -- the snapshot ring is capped -- so an arithmetic timeline
    would mislabel a truncated run."""
    if not _stage5_present():
        pytest.skip("Stage 5 timeline not present")
    src = code_only(_CLOCK_CS.read_text(encoding="utf-8"))

    # The ASSIGNMENT, not the presence of the token. The first version of this
    # rule asked whether "_bundle.Ticks[" appeared anywhere in the file, and a
    # sabotage that replaced the year lookup with `FirstTick + Index`
    # arithmetic sailed through it -- because Ticks is still indexed elsewhere,
    # in NextYear and SeekYear. A rule that a two-line change can satisfy
    # without doing the thing is not a rule.
    assert re.search(r"int year\s*=\s*_bundle\.Ticks\[", src), (
        "WorldClock's displayed year is no longer read out of "
        "WorldBundle.Ticks. Adding an index to FirstTick assumes the retained "
        "range is contiguous from the first year, which a capped snapshot ring "
        "does not promise.")


def test_the_headcount_check_counts_the_years_own_frame():
    """
    The acceptance criterion, protected.

    Stage 5 previews next year's newborns rising out of the ground during a
    blend. Counting them would inflate the population by the year's births and
    break the one check that ties the picture to history.csv.
    """
    if not _stage5_present():
        pytest.skip("Stage 5 timeline not present")
    src = code_only(_RENDERER_CS.read_text(encoding="utf-8"))
    assert "VisibleCount = frame.Length;" in src, (
        "VisibleCount is no longer the displayed year's own frame length")
    assert "EmergingCount" in src, (
        "the emerging (next-year) villagers are no longer counted separately")


def test_the_flow_ribbon_uses_the_dashboards_width_profile():
    """1 + 5 * weight / wmax (panels.py:794), normalised per FRAME on both
    sides. A different profile would rank the same two migration routes
    differently on the two maps."""
    if not _stage5_present():
        pytest.skip("Stage 5 timeline not present")
    panels = _PANELS_PY.read_text(encoding="utf-8")
    m = re.search(r'width=([0-9.]+) \+ ([0-9.]+) \* f\["weight"\] / wmax', panels)
    assert m, "the dashboard's flow width rule has changed shape"

    cs = code_only(_RIBBON_CS.read_text(encoding="utf-8"))
    m2 = re.search(r"WidthProfile\(float weight, float maxWeight\) =>\s*"
                   r"([0-9.]+)f \+ ([0-9.]+)f \*", cs)
    assert m2, "FlowRibbonView.WidthProfile not found"
    assert (float(m2.group(1)), float(m2.group(2))) == \
           (float(m.group(1)), float(m.group(2))), (
        f"the dashboard draws routes at {m.group(1)}+{m.group(2)}*w/wmax and "
        f"the viewer at {m2.group(1)}+{m2.group(2)}*w/wmax")


# ---------------------------------------------------------------------
# Parse width: the defect Stage 5 found, and the rule that keeps it fixed
# ---------------------------------------------------------------------
# MEASURED, on a 40-year export: parsing the display columns as binary32 made
# the viewer print a different number from the dashboard for 77 of 1323
# `stress` values and 64 of 1323 `aerobic` values --
#
#     stress "-1.385"  ->  float64 -1.39   float32 -1.38
#     aerobic "39.305" ->  float64  39.30  float32  39.31
#
# -- because snapshots.py rounds those columns to three decimals and the drawer
# prints two, so an exact 3-dp midpoint is the ordinary case. Both numbers look
# right. The formatters were correct on both sides; they were being handed
# DIFFERENT NUMBERS, which is why the parity fixture could not see it.
#
# Parsing the same decimal text to binary64 on both sides is bit-identical, so
# the rule is that every column the viewer PRINTS is parsed as a double.
# Geometry (x, y) stays float: it is never shown as text.

_DOUBLE_PARSED = {
    "LoadFrames": ("Purity", "Stress", "EpiAccel", "Aerobic", "PedigreeF",
                   "Viability", "HeightCm"),
    "LoadPeople": ("PedigreeF", "RealisedF", "RelativeViability"),
}


@pytest.mark.parametrize("method,fields", sorted(_DOUBLE_PARSED.items()),
                         ids=lambda v: v if isinstance(v, str) else "")
def test_displayed_columns_are_parsed_at_double_width(method, fields):
    src = code_only(LOADER.read_text(encoding="utf-8"))
    body = _method_body(src, method)
    for field in fields:
        m = re.search(rf"\b{field}\s*=\s*CsvParse\.(\w+)\(", body)
        assert m, f"{method} no longer assigns {field}"
        assert m.group(1) == "Double", (
            f"{method} parses {field} with CsvParse.{m.group(1)}. Displayed "
            f"columns must be parsed as double or the viewer prints a "
            f"different number from the dashboard at every rounding boundary.")


def test_history_and_traits_are_parsed_at_double_width():
    """The other two display paths: history.csv's KPI values and people.csv's
    trait_* cells."""
    loader = code_only(LOADER.read_text(encoding="utf-8"))
    assert "double.TryParse" in _method_body(loader, "LoadHistory"), (
        "history.csv values are not parsed as double; the KPI strip would "
        "then print different text from the dashboard's stat tiles")

    rows = code_only((UNITY_ROOT / "Runtime" / "Data" / "Rows.cs")
                     .read_text(encoding="utf-8"))
    assert re.search(r"double GetTrait\(string trait\) =>\s*"
                     r"CsvParse\.TryDouble", rows), (
        "PersonRow.GetTrait no longer returns a double")


# ---------------------------------------------------------------------
# The two ways this package's C# tests stop being evidence
# ---------------------------------------------------------------------
# Both of these were true at once, and neither is visible from anything the
# C# suite itself asserts -- the first because it stops the suite existing,
# the second because it is what the suite was getting wrong.

def test_the_test_assembly_is_editor_only():
    """
    ExtNPC.Tests must declare `includePlatforms: ["Editor"]`.

    THIS IS NOT STYLE. With an empty includePlatforms the assembly is an
    all-platforms one, and Unity's Test Runner matches it against PLAYMODE.
    An EditMode run then finds nothing and reports

        <test-run testcasecount="0" ... result="Passed">

    -- zero tests, exit code 0, green. It compiles the whole time, so
    ExtNPC.Tests.dll sits in Library/ScriptAssemblies looking healthy. The
    package shipped in that state for two sessions: the "34 passing" and
    "53 passing" badges were counted by hand from [Test] attributes, and the
    number a Test Runner would have shown was 0.

    (It is also simply correct. These are formatter and cursor tests, and an
    all-platforms test assembly gets compiled into player builds.)
    """
    import json

    asmdef = json.loads((UNITY_ROOT / "Tests" / "ExtNPC.Tests.asmdef")
                        .read_text(encoding="utf-8"))
    assert asmdef.get("includePlatforms") == ["Editor"], (
        f"ExtNPC.Tests.asmdef has includePlatforms="
        f"{asmdef.get('includePlatforms')!r}. Anything but [\"Editor\"] makes "
        f"the suite invisible to an EditMode run, which reports zero tests "
        f"AND PASSES. Run `python run_unity_tests.py` to see the real count.")


def test_the_python_rounding_rule_is_not_delegated():
    """
    InspectorFormat must not round through `Math.Round(value, digits, ...)`,
    and must not simply hand the raw value to the formatter.

    Both were tried and both were wrong, in opposite directions, and each was
    right four times in five:

      * Math.Round(double, int, ...) scales by a power of TEN and rounds the
        product, so it judges midpoints on a number that is not the one being
        printed. -1.385 is stored as -1.38500000000000000888..., past the
        midpoint, so Python gives -1.39 -- but -1.385 * 100 rounds to exactly
        -138.5 and ToEven picks -1.38.
      * Deferring to the formatter is correct on .NET Core 3.0+ and wrong on
        Unity's Mono, which rounds to ~15 significant digits first:
        -0.72499999999999997779 prints as -0.73 where Python gives -0.72.

    The C# fixture covers this with real values, but only when someone runs
    Unity. This is the four-second version.
    """
    src = code_only(_FORMAT_CS.read_text(encoding="utf-8"))

    body = _method_body(src, "PyRound")
    assert not re.search(r"Math\.Round\s*\([^)]*,\s*digits", body), (
        "PyRound rounds through Math.Round(value, digits, ...), which decides "
        "midpoints on value*10^digits rather than on the value. See the "
        "-1.385 case in the parity fixture.")
    assert "ExactHalfEven" in body, (
        "PyRound no longer routes near-midpoint values through an exact "
        "half-to-even path; Unity's Mono formatter cannot be trusted to round "
        "the binary value, so the rounding must happen before it.")
