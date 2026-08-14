"""
The dashboard's own output, frozen for the C# inspector to be checked against.
=============================================================================

`tests/test_unity_contract.py` compares the two sources as TEXT: same
thresholds, same label strings, same palette. That catches a table edited on
one side only, which is the likeliest drift.

It cannot catch the other half. A table can be correct and the formatter that
renders it wrong -- and the failures there are near-misses, which is exactly
what the Stage 4 acceptance criterion ("character-for-character") is about:

    Python  f"{p:.0%}"                      -> "50%"
    C#      ToString("P0", InvariantCulture) -> "50 %"

So this module runs `dashboard/inspector.py`'s REAL formatters over a grid of
values and writes what they produce into a generated C# file. A test in the
Unity package (`Tests/ParityFixtureTests.cs`) feeds the same inputs to
`InspectorFormat` and asserts the same strings come back. Neither side can
silently change what a villager's drawer says.

WHY A GENERATED FILE AND NOT A JSON READ AT RUNTIME. The Unity test then needs
no file IO and no path resolution inside a package, and the fixture lands in
`git diff` as text next to the code it constrains. The cost is that it must be
regenerated deliberately, which is the same trade `tests/test_export_golden.py`
makes and for the same reason.

REGENERATING. `EXTNPC_UPDATE_PARITY` must carry a reason of >= 12 characters;
a bare 1/true/yes is refused. The reason is written into the generated file's
header, so a re-cut lands in the diff next to the strings it excuses.
"""

from __future__ import annotations

import os
import re
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore")

pytest.importorskip("dash", reason="dashboard/inspector.py imports dash")

from dashboard.inspector import _f_color, _fmt_f, _norm, relationship_label
from dashboard.panels import kpi_data

GENERATED = (Path(__file__).parent.parent / "unity" / "com.samal.extnpc" /
             "Tests" / "ParityFixture.generated.cs")

_ENV = "EXTNPC_UPDATE_PARITY"


# ---------------------------------------------------------------------
# the grid
# ---------------------------------------------------------------------
# Chosen to sit ON the thresholds rather than near them. 0.0625 is a value F
# actually takes for a first-cousin child, not one it approaches, so an
# off-by-a-hair comparison on either side shows up here rather than in the
# field.

#
# The dyadic values below are also EXACT BINARY MIDPOINTS at the rounding
# position, and that is deliberate. Python rounds half to even; .NET's F
# formats round half away from zero, and they agree everywhere else -- so a
# grid of "realistic-looking" values would never have found it. 0.03125 at 4
# decimals and 0.125 as a percent are the two that actually caught it.
_F_VALUES = [0.0, 0.004, 0.015625, 0.03125, 0.0625, 0.078125, 0.10938,
             0.125, 0.25, 0.5]
# The last two of each are REAL VALUES from a 40-year export, picked because
# they are exact 3-decimal midpoints printed at two: snapshots.py rounds
# stress and aerobic to 3 dp and the drawer shows 2, so these are the
# ordinary case rather than the exotic one. They are in the grid because the
# viewer used to parse them as binary32 and print the other neighbour --
# "-1.38" against the dashboard's "-1.39" -- on 77 of 1323 villager-years.
_SIGNED2 = [0.0, 0.213, -0.213, 1.731, -0.687, 0.6, 0.61, -1.385, -0.725]
_FIXED2 = [0.0, 41.554, 4.6, 52.0, 39.305, 55.805, 44.695]
_FIXED3 = [0.9734, 0.9, 0.899, 1.071, 0.475]
_YEARS = [0.0, 1.24, -1.24, 3.0, 3.1]
#             ------- exact midpoints at .0% -------
_PERCENT = [0.0, 0.125, 0.375, 0.625, 0.875, 0.005, 0.015,
            0.167, 0.25, 0.5, 0.8734, 1.0]
_HEIGHTS = [(112.4, 171.2), (171.2, 171.2), (171.20, 171.23), (168.34, 168.34),
            (99.5, 180.4)]
_BMI = [(24.42, True), (24.42, False), (15.6, True)]
_SIGNED4 = [0.0, 0.07014, -0.0123, 0.25]
_STATURE = [-1.312, -0.75, -0.938, -0.4]
# The two ranges the drawer actually meters on, kept as two NAMED cases rather
# than a range encoded into the function name -- the C# side would otherwise
# have to parse floats back out of a string to replay them.
_NORM_STRESS = [-1.5, 2.5, 0.0, -9.0, 9.0, 0.213]        # inspector.py:325/344
_NORM_HET = [0.0, 0.412, 0.6, 0.9]                       # inspector.py:323

# ---------------------------------------------------------------------
# Stage 5: the KPI strip the Unity HUD prints
# ---------------------------------------------------------------------
# These are NOT copied f-strings. `_kpi` below calls dashboard/panels.py's real
# `kpi_data` and reads the tile it produces, so what lands in the fixture is
# what the stat-tile deck actually renders.
#
# The em-dash cases are the reason this section exists. Two of the five tiles
# print "—" rather than a number when the quantity is not measurable -- F_ST in
# a single-deme world, and Morton's B before the load layer has a measurement --
# and both rules are one edit away from becoming a 0.000 that asserts something
# the engine never claimed. A number is easy to notice when it changes; an em
# dash quietly turning into "0.000" is not.
_KPI_ALIVE = [0.0, 1.0, 36.0, 127.0]
#              ---- exact midpoints at .3f / .4f ----
_KPI_HET = [0.0, 0.412, 0.0625, 0.5, 0.4738]
_KPI_FST = [0.0, 0.019, 0.1032, 0.0625]
_KPI_F = [0.0, 0.03125, 0.0625, 0.10938, 0.0009]
_KPI_LOAD = [0.0, 1.4, 1.3755, 0.0004]


def _kpi(key: str, value: float, n_demes: int = 1) -> str:
    """The stat tile's rendered value, from the dashboard's own `kpi_data`.

    Calling the real function rather than copying its f-string is the whole
    point: a tile whose format changes -- or whose em-dash condition changes --
    fails the comparison in this module and forces InspectorFormat's Stage 5
    sibling to be updated in the same commit.

    `params` is a stub because `_n_demes` reads it with getattr; building a real
    DemographyParams here would drag the simulation package into a formatting
    test for one integer.
    """
    from types import SimpleNamespace

    cols = {key: [float(value)]}
    for tile in kpi_data(cols, SimpleNamespace(n_demes=n_demes)):
        if tile["key"] == key:
            return tile["value"]
    raise AssertionError(f"kpi_data produced no tile for {key!r}")


def _cases():
    """(function, arg a, arg b, expected string) as the DASHBOARD renders it.

    Where inspector.py exposes the formatter it is called directly
    (`relationship_label`, `_fmt_f`, `_f_color`, `_norm`). Where the drawer
    formats inline, the f-string is copied from the line named in the comment
    -- that copy is the thing this fixture pins.
    """
    out = []
    for f in _F_VALUES:
        out.append(("FmtF", f, 0.0, _fmt_f(f)))                  # :116
        out.append(("RelationshipLabel", f, 0.0, relationship_label(f)))  # :108
        out.append(("FColor", f, 0.0, _f_color(f)))              # :120
    for v in _SIGNED2:
        out.append(("Signed2", v, 0.0, f"{v:+.2f}"))             # :332
    for v in _FIXED2:
        out.append(("Fixed2", v, 0.0, f"{v:.2f}"))               # :333
    for v in _FIXED3:
        out.append(("Fixed3", v, 0.0, f"{v:.3f}"))               # :339
    for v in _YEARS:
        out.append(("SignedYears", v, 0.0, f"{v:+.1f} y"))       # :334
    for v in _PERCENT:
        out.append(("Percent0", v, 0.0, f"{v:.0%}"))             # :260
    for v in _SIGNED4:
        out.append(("Signed4", v, 0.0, f"{v:+.4f}"))             # :152
    for v in _STATURE:
        out.append(("StatureCost", v, 0.0, f"{v:+.2f} cm"))      # :158
    for cm in (168.34, 99.5, 180.0):
        out.append(("Height", cm, 0.0, f"{cm:.1f} cm"))          # :330
    for now, mature in _HEIGHTS:
        # inspector.py:284-291 -- both statures while still growing
        growing = abs(now - mature) > 0.05
        expected = (f"{now:.1f} cm  → {mature:.0f} adult" if growing
                    else f"{now:.1f} cm")
        out.append(("HeightLive", now, mature, expected))
    for bmi, growing in _BMI:
        out.append(("Bmi", bmi, 1.0 if growing else 0.0,         # :300
                    f"{bmi:.1f} at maturity" if growing else f"{bmi:.1f}"))
    # _norm returns a float; compared as a rounded string so the C# side is
    # checked on the VALUE and not on float-to-text formatting.
    for v in _NORM_STRESS:
        out.append(("NormStress", v, 0.0, f"{_norm(v, -1.5, 2.5):.6f}"))
    for v in _NORM_HET:
        out.append(("NormHeterozygosity", v, 0.0, f"{_norm(v, 0.0, 0.6):.6f}"))

    # Stage 5 -- the KPI strip, straight out of panels.kpi_data.
    for v in _KPI_ALIVE:
        out.append(("KpiAlive", v, 0.0, _kpi("n_alive", v)))
    for v in _KPI_HET:
        out.append(("KpiHeterozygosity", v, 0.0, _kpi("heterozygosity", v)))
    for v in _KPI_FST:
        # BOTH worlds, because the tile's rule is about the world's shape and
        # not about the value: one deme means "nothing to measure" whatever
        # number sits in the column.
        out.append(("KpiFst", v, 1.0, _kpi("fst", v, n_demes=1)))
        out.append(("KpiFst", v, 3.0, _kpi("fst", v, n_demes=3)))
    for v in _KPI_F:
        out.append(("KpiInbreeding", v, 0.0, _kpi("mean_inbreeding", v)))
    for v in _KPI_LOAD:
        out.append(("KpiLoad", v, 0.0, _kpi("lethal_equivalents", v)))
    return out


# ---------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------

def _cs_string(s: str) -> str:
    r"""A C# string literal, non-ASCII escaped as \uXXXX.

    The labels contain an en dash (U+2013) and the growing-stature row an
    arrow (U+2192). Escaping them keeps the generated file pure ASCII, so it
    cannot be broken by an editor writing a BOM or by a checkout that
    re-encodes -- and the diff shows a changed codepoint rather than a
    character that looks identical to the one it replaced.
    """
    out = []
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif 32 <= ord(ch) < 127:
            out.append(ch)
        else:
            out.append(f"\\u{ord(ch):04x}")
    return '"' + "".join(out) + '"'


def _render(reason: str = "") -> str:
    lines = [
        "// GENERATED FILE -- do not edit by hand.",
        "//",
        "// Produced by tests/test_unity_parity_fixture.py from the REAL",
        "// formatters in dashboard/inspector.py. Every string here is what the",
        "// dashboard drawer actually prints for the given input; ",
        "// Tests/ParityFixtureTests.cs asserts InspectorFormat prints the same.",
        "//",
        "// Regenerate with EXTNPC_UPDATE_PARITY=\"<reason, >=12 chars>\".",
    ]
    if reason:
        lines.append(f"// recut_reason: {reason}")
    lines += [
        "",
        "namespace ExtNPC.Tests",
        "{",
        "    internal static class ParityFixture",
        "    {",
        "        internal struct Case",
        "        {",
        "            public string Fn;",
        # DOUBLE, not float. The C# side must be handed the SAME number the
        # dashboard formatted, or the fixture would compare two formatters
        # over two different values and report the difference as a formatting
        # bug -- which is exactly how the binary32 parse hid for two sessions.
        "            public double A;",
        "            public double B;",
        "            public string Expected;",
        "        }",
        "",
        "        internal static readonly Case[] Cases =",
        "        {",
    ]
    for fn, a, b, expected in _cases():
        lines.append(
            f"            new Case {{ Fn = {_cs_string(fn)}, "
            f"A = {a!r}, B = {b!r}, Expected = {_cs_string(str(expected))} }},")
    lines += [
        "        };",
        "    }",
        "}",
        "",
    ]
    return "\n".join(lines)


def _strip_reason(text: str) -> str:
    """The file minus its recut_reason line, so a re-cut for a stated reason
    does not read as a content change."""
    return re.sub(r"^// recut_reason:.*\n", "", text, flags=re.M)


# ---------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------

def test_the_grid_actually_covers_the_formatters():
    """Guard: without this, an empty grid makes the comparison below pass
    vacuously."""
    cases = _cases()
    assert len(cases) >= 60, f"only {len(cases)} parity cases"
    functions = {fn for fn, _, _, _ in cases}
    for required in ("FmtF", "RelationshipLabel", "FColor", "Percent0",
                     "HeightLive", "Bmi", "Signed2", "StatureCost",
                     "NormStress", "NormHeterozygosity", "Height", "Fixed2",
                     "Fixed3", "SignedYears", "Signed4",
                     # Stage 5
                     "KpiAlive", "KpiHeterozygosity", "KpiFst",
                     "KpiInbreeding", "KpiLoad"):
        assert required in functions, f"{required} is not covered"


def test_the_kpi_grid_covers_both_em_dash_cases():
    """
    A guard on the grid rather than on the code.

    The two tiles that can print "—" are the two a well-meaning edit turns into
    "0.000", so a grid that happened to contain only measurable values would
    leave the interesting half of each rule unchecked -- and would pass.
    """
    expected = {(fn, exp) for fn, _, _, exp in _cases()
                if fn in ("KpiFst", "KpiLoad")}
    assert ("KpiFst", "—") in expected, "no single-deme F_ST case in the grid"
    assert ("KpiLoad", "—") in expected, "no unmeasurable B(t) case in the grid"
    # ...and the measurable half, or the rule could be "always an em dash".
    assert any(fn == "KpiFst" and exp != "—" for fn, exp in expected)
    assert any(fn == "KpiLoad" and exp != "—" for fn, exp in expected)


def test_the_generated_fixture_matches_the_dashboards_current_output():
    """
    The fixture is the dashboard's output, frozen. If inspector.py changes how
    it renders anything, this fails and names it -- and the C# side has to be
    updated in the same commit rather than drifting until someone compares two
    screenshots.
    """
    reason = os.environ.get(_ENV, "").strip()
    if reason:
        if reason.lower() in {"1", "true", "yes", "y", "on"} or len(reason) < 12:
            pytest.fail(
                f"{_ENV} must be a REASON of at least 12 characters, not "
                f"'{reason}'. It is written into the generated file, so a "
                f"re-cut appears in git diff next to the strings it excuses.")
        GENERATED.parent.mkdir(parents=True, exist_ok=True)
        GENERATED.write_text(_render(reason), encoding="ascii", newline="\n")
        pytest.skip(f"parity fixture regenerated: {reason}")

    assert GENERATED.exists(), (
        f"{GENERATED} is missing. Regenerate with {_ENV}='<reason>'.")

    current = _render()
    committed = GENERATED.read_text(encoding="ascii")
    if _strip_reason(committed) != _strip_reason(current):
        # Name the first differing case rather than dumping two files.
        old = _strip_reason(committed).splitlines()
        new = _strip_reason(current).splitlines()
        first = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b),
                     min(len(old), len(new)))
        pytest.fail(
            f"the C# parity fixture no longer matches dashboard/inspector.py.\n"
            f"  first difference at line {first + 1}:\n"
            f"    committed: {old[first] if first < len(old) else '<eof>'}\n"
            f"    dashboard: {new[first] if first < len(new) else '<eof>'}\n"
            f"  If the dashboard's wording changed on purpose, update "
            f"InspectorFormat.cs to match and regenerate with "
            f"{_ENV}='<reason>'.")


def test_the_fixture_is_pure_ascii():
    """Non-ASCII is escaped so the file cannot be broken by an editor writing
    a BOM, and so a changed codepoint shows in the diff rather than hiding as
    a character that looks the same."""
    if not GENERATED.exists():
        pytest.skip("fixture not generated yet")
    raw = GENERATED.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "fixture has a UTF-8 BOM"
    non_ascii = [b for b in raw if b > 127]
    assert not non_ascii, "fixture contains raw non-ASCII bytes"


def test_the_en_dash_in_the_relationship_labels_survived_the_round_trip():
    """A specific one, because it is the character most likely to be quietly
    replaced with a hyphen by an editor or a copy-paste -- and 'full sib /
    parent-offspring' vs 'parent–offspring' is a silent parity break."""
    assert "–" in relationship_label(0.25), (
        "inspector.py's ladder no longer uses an en dash; InspectorFormat.cs "
        "and the fixture must follow")
    if GENERATED.exists():
        assert "\\u2013" in GENERATED.read_text(encoding="ascii")
