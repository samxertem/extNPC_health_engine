"""
Tests for the dashboard's pure view functions (dashboard/).

The dashboard has carried ~1,900 untested lines since session 8. This file
does not try to close that in one go; it pins the functions touched while
closing out the session-11 handoff, in the same spirit as the engine tests --
assert the *claim the view makes*, not the pixels.

The recurring theme is honesty of an empty or not-yet-meaningful reading.
A dashboard that prints 0.000 where it has measured nothing is making a
claim, and these tests are what stop that regressing.
"""

import pytest

from dashboard import inspector, panels
from dashboard.app import params_from_controls
from simulation import World


class _Params:
    """Minimal stand-in for DemographyParams -- kpi_data only reads n_demes."""

    def __init__(self, n_demes=1):
        self.n_demes = n_demes


def _text(node) -> str:
    """Flatten a Dash component tree to its visible text."""
    if node is None or isinstance(node, (int, float)):
        return str(node) if node is not None else ""
    if isinstance(node, str):
        return node
    if isinstance(node, (list, tuple)):
        return " ".join(_text(n) for n in node)
    return _text(getattr(node, "children", None))


def _tile(cols, params, key="fst"):
    return next(t for t in panels.kpi_data(cols, params) if t["key"] == key)


# ---------------------------------------------------------------------
# F_ST is undefined without population structure
# ---------------------------------------------------------------------

def test_fst_tile_reads_as_undefined_in_a_single_deme_world():
    """
    With one deme there is no partition to estimate over. The tile must not
    print 0.000, which asserts "no differentiation was measured" -- a
    different and stronger claim than "there is nothing to measure".
    """
    tile = _tile({"tick": [1], "fst": [0.0]}, _Params(n_demes=1))
    assert tile["value"] == "—"
    assert tile["delta"] == 0.0          # no trend arrow on a non-measurement
    assert "single-deme" in tile["glossary"]


def test_fst_tile_reports_the_estimate_once_there_is_structure():
    tile = _tile({"tick": [1, 2], "fst": [0.01, 0.042]}, _Params(n_demes=4))
    assert tile["value"] == "0.042"
    assert tile["fmt"] == "f3"


def test_fst_tile_survives_a_params_object_without_n_demes():
    """The snapshot ring outlives schema changes; the drawer must not crash
    on a frame or params object captured before a field existed."""
    assert _tile({"tick": [1], "fst": [0.02]}, object())["value"] == "—"


def test_fst_figure_hides_its_axes_when_there_is_nothing_to_measure():
    """A drawn -1..6 axis pair with no trace on it reads as a flat zero."""
    fig = panels.fst_figure({"tick": [1], "fst": [0.0]}, n_demes=1)
    assert fig.layout.xaxis.visible is False
    assert not fig.data                       # no trace, only the annotation
    assert "no differentiation to measure" in fig.layout.annotations[0].text

    live = panels.fst_figure({"tick": [1, 2], "fst": [0.01, 0.04]}, n_demes=4)
    assert live.data


# ---------------------------------------------------------------------
# Controls -> params mapping (roadmap #31's knob)
# ---------------------------------------------------------------------

def test_inbreeding_depression_slider_reaches_the_params():
    p = params_from_controls(150, 0.42, 1.0, 0.4, 1.0, 1.0, 0.0, 0.5,
                             1, 0.0, 1.0, 0.0, 0.0, 1.0, depression=0.0)
    assert p.inbreeding_depression == 0.0

    p2 = params_from_controls(150, 0.42, 1.0, 0.4, 1.0, 1.0, 0.0, 0.5,
                              1, 0.0, 1.0, 0.0, 0.0, 1.0, depression=1.7)
    assert p2.inbreeding_depression == pytest.approx(1.7)


def test_depression_defaults_to_the_calibrated_strength():
    """Callers written before #31 landed must still produce the params they
    always did -- 1.0 is the calibrated 1.4 lethal equivalents, not 'off'."""
    p = params_from_controls(150, 0.42, 1.0, 0.4, 1.0, 1.0, 0.0, 0.5,
                             1, 0.0, 1.0, 0.0, 0.0, 1.0)
    assert p.inbreeding_depression == 1.0


# ---------------------------------------------------------------------
# Plain-language reading of a pedigree F
# ---------------------------------------------------------------------

@pytest.mark.parametrize("F, expected", [
    (0.25, "full sib / parent–offspring"),
    (0.125, "uncle–niece / double first cousin"),
    (0.0625, "first cousins"),
    (0.03125, "first cousins once removed"),
    (0.015625, "second cousins"),
    (0.001, "distant kin"),
    (0.0, "outbred"),
])
def test_relationship_label_lands_on_the_textbook_coefficients(F, expected):
    """Each threshold is a standard pedigree value, so the boundary itself
    must map to its own label rather than the tier below it."""
    assert inspector.relationship_label(F) == expected


def test_relationship_label_is_robust_to_float_error():
    """1/16 built by arithmetic is not always bit-identical to 0.0625."""
    assert inspector.relationship_label(1 / 2 ** 4) == "first cousins"
    assert inspector.relationship_label(0.0625 - 1e-12) == "first cousins"


# ---------------------------------------------------------------------
# Age-expressed phenotypes (roadmap #13) in the drawer
# ---------------------------------------------------------------------

@pytest.fixture(scope="module")
def grown_world():
    """A world run far enough to contain both children and adults."""
    w = World(n_founders=20, seed=11)
    for _ in range(30):
        w.step()
    return w


def _split_by_growth(world):
    growing, mature = [], []
    for npc in world.living:
        target = npc.phenotype()["height_cm"]
        (growing if abs(npc.height_at_age() - target) > 0.05
         else mature).append(npc.name)
    return growing, mature


def test_the_world_contains_someone_still_growing(grown_world):
    growing, mature = _split_by_growth(grown_world)
    assert growing and mature, "need both to test the two display branches"


def test_a_growing_individual_shows_both_current_and_adult_height(grown_world):
    growing, _ = _split_by_growth(grown_world)
    text = _text(inspector.summary_card(grown_world, growing[0]))
    assert "adult" in text, "the genetic endpoint should sit beside the height"


def test_bmi_is_labelled_as_an_endpoint_while_still_growing(grown_world):
    """
    #13 models stature only -- Preece-Baines is a height curve and there is
    no body-mass trajectory -- so the BMI shown for a child is the MATURE
    value. Printing it bare put "BMI 24.4" against a three-year-old, which is
    not a possible toddler value (~15-16) and read as a measurement.
    """
    growing, mature = _split_by_growth(grown_world)
    assert "at maturity" in _text(inspector.summary_card(grown_world, growing[0]))
    # ...and an adult, whose BMI *is* current, must not carry the caveat.
    assert "at maturity" not in _text(inspector.summary_card(grown_world, mature[0]))


# ---------------------------------------------------------------------
# Directional dominance in the inspector (session 15)
# ---------------------------------------------------------------------

@pytest.fixture(scope="module")
def inbred_world():
    """A world run long enough for someone's parents to be related."""
    w = World(n_founders=12, seed=5)
    for _ in range(60):
        w.step()
    return w


def _most_inbred(world):
    return max(world.living, key=lambda p: world.inbreeding_of(p.name))


def test_an_inbred_individual_shows_the_stature_cost(inbred_world):
    """The engine's second cost of inbreeding has to be visible, or the
    mechanism exists only in the test suite."""
    from health_engine.inbreeding import predicted_depression

    npc = _most_inbred(inbred_world)
    F = inbred_world.inbreeding_of(npc.name)
    assert F > 1e-9, "fixture failed to produce a consanguineous birth"
    text = _text(inspector.summary_card(inbred_world, npc.name))
    assert "stature cost" in text
    # the number shown is the closed form, not a re-derivation
    assert f"{predicted_depression('height_cm', F):+.2f}" in text


def test_an_outbred_individual_claims_no_stature_cost(inbred_world):
    """At F = 0 the expected cost is exactly zero, and a row reading
    '-0.00 cm' would be a claim where there is nothing to claim."""
    outbred = [p for p in inbred_world.living
               if inbred_world.inbreeding_of(p.name) <= 1e-9]
    if not outbred:
        pytest.skip("no outbred individuals alive in this world")
    assert "stature cost" not in _text(
        inspector.summary_card(inbred_world, outbred[0].name))


def test_the_two_costs_of_inbreeding_are_shown_side_by_side(inbred_world):
    """Viability and stature are separate mechanisms from separate
    literatures; the character sheet must not let one stand in for both."""
    from dashboard import app as dash_app

    npc = _most_inbred(inbred_world)
    # `_inbreeding_section` reads the module-level WORLD, so it has to be
    # swapped -- and put back, or every later test in this pytest session
    # inherits our fixture's world.
    previous = dash_app.WORLD
    try:
        dash_app.WORLD = inbred_world
        text = _text(dash_app._inbreeding_section(npc.name, npc))
    finally:
        dash_app.WORLD = previous
    assert "relative viability" in text
    assert "expected stature cost" in text
    assert "expected lung cost" in text


def test_the_inbreeding_chart_carries_the_stature_cost_on_hover(inbred_world):
    """The predicted cost is a linear rescale of the mean-F line, so it rides
    in customdata rather than as a redundant trace -- but it must be there,
    and it must match the closed form."""
    from health_engine.inbreeding import predicted_depression

    cols = inbred_world.history_columns()
    fig = panels.inbreeding_figure(cols)
    trace = next(t for t in fig.data if t.name == "mean F")
    assert trace.customdata is not None
    for f, cost in zip(cols["mean_inbreeding"], trace.customdata):
        assert cost == pytest.approx(predicted_depression("height_cm", f))
