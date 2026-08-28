"""
Body composition and body segments: item E4, and the half of E5 with units.
===========================================================================

`lean_mass_fraction` and `sitting_height_ratio` are both dimensionless, and
`body_metrics.py` is what turns them into kilograms and centimetres. So the
things worth testing here are the CONVERSIONS and the IDENTITIES, not the
traits themselves, which `test_appended_traits.py` covers.

THE REGRESSION THIS FILE CARRIES. E4's first design modelled a fat-free mass
INDEX rather than a fraction, which is the more standard quantity and reads
better in a paper. It is also wrong for this engine: an index is a second mass
trait uncorrelated with `bmi`, so fat mass index = BMI minus FFMI goes negative
for 5.9% of villagers under the engine's own distributions. That is not a
rounding problem, it is one villager in seventeen with negative fat. The
fraction has no such failure mode by construction, and
`test_no_villager_can_have_negative_fat` is what keeps a future refactor from
walking back into it.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pytest

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from health_engine.body_metrics import (body_composition, body_segments,
                                        metrics_for)
from health_engine.npc import random_founder
from health_engine.phenotype_to_mhm import muscle_macro
from health_engine.traits import TRAIT_TABLE


# ----------------------------------------------------------------------
# the identities, which are exact and therefore worth asserting exactly
# ----------------------------------------------------------------------

def test_the_segments_add_back_to_stature():
    seg = body_segments(172.0, 0.52)
    assert seg["sitting_height_cm"] + seg["leg_length_cm"] == pytest.approx(
        seg["stature_cm"], abs=1e-12)
    assert seg["sitting_height_cm"] == pytest.approx(89.44)


def test_the_indices_add_back_to_bmi():
    """FFMI + FMI = BMI, VanItallie 1990. The reason composition is reported
    in indices as well as kilograms: the index is the form that composes with
    the trait the engine already calibrates."""
    comp = body_composition(bmi=24.5, lean_mass_fraction=0.75, height_cm=172.0)
    assert (comp["fat_free_mass_index"] + comp["fat_mass_index"]
            == pytest.approx(24.5, abs=1e-12))


def test_the_masses_add_back_to_body_mass():
    comp = body_composition(bmi=24.5, lean_mass_fraction=0.75, height_cm=172.0)
    assert (comp["lean_mass_kg"] + comp["fat_mass_kg"]
            == pytest.approx(comp["body_mass_kg"], abs=1e-12))


def test_body_mass_is_bmi_times_height_squared():
    """No new assumption is introduced: this is the definition of BMI
    rearranged, and the test says so in case anyone is tempted to add one."""
    comp = body_composition(bmi=22.0, lean_mass_fraction=0.8, height_cm=180.0)
    assert comp["body_mass_kg"] == pytest.approx(22.0 * 1.8 * 1.8)


# ----------------------------------------------------------------------
# the failure mode the fraction exists to avoid
# ----------------------------------------------------------------------

def test_no_villager_can_have_negative_fat():
    """The whole reason `lean_mass_fraction` is a fraction.

    Modelled as a fat-free mass INDEX, fat mass index = BMI minus FFMI is
    negative for about 6% of this engine's villagers. As a fraction of body
    mass both compartments are non-negative for any fraction in [0, 1], and
    the trait is clipped to [0.50, 0.95] on top of that.
    """
    rng = np.random.default_rng(3)
    negatives = 0
    for i in range(400):
        metrics = metrics_for(random_founder(f"N-{i}", rng).phenotype())
        assert metrics is not None
        if metrics["fat_mass_kg"] < 0 or metrics["lean_mass_kg"] < 0:
            negatives += 1
    assert negatives == 0


def test_the_trait_is_clipped_to_a_physiological_range():
    spec = TRAIT_TABLE["lean_mass_fraction"]
    assert spec.clip == (0.50, 0.95)
    rng = np.random.default_rng(21)
    values = [float(random_founder(f"K-{i}", rng).phenotype()
                    ["lean_mass_fraction"]) for i in range(300)]
    assert min(values) >= 0.50
    assert max(values) <= 0.95


def test_body_fat_percent_is_the_complement_of_the_fraction():
    comp = body_composition(bmi=24.5, lean_mass_fraction=0.72, height_cm=170.0)
    assert comp["body_fat_percent"] == pytest.approx(28.0)


def test_a_zero_height_is_refused_rather_than_dividing():
    with pytest.raises(ValueError, match="height_cm"):
        body_composition(bmi=24.5, lean_mass_fraction=0.75, height_cm=0.0)


# ----------------------------------------------------------------------
# metrics_for: all or nothing
# ----------------------------------------------------------------------

def test_a_phenotype_without_the_new_traits_gets_no_row():
    """A bundle exported before E4 and E5 existed is a legitimate input. It
    should get no row rather than an exception, and no HALF a row: half a
    composition beside a full one in the same table is worse than neither."""
    assert metrics_for({"height_cm": 170.0, "bmi": 24.5}) is None
    assert metrics_for({}) is None


def test_a_complete_phenotype_gets_every_field():
    rng = np.random.default_rng(8)
    metrics = metrics_for(random_founder("Full-1", rng).phenotype())
    for key in ("stature_cm", "sitting_height_cm", "leg_length_cm",
                "body_mass_kg", "lean_mass_kg", "fat_mass_kg",
                "fat_free_mass_index", "fat_mass_index", "body_fat_percent"):
        assert key in metrics


def test_derived_values_are_physiologically_plausible():
    """Loose bounds, and their job is to catch a unit error rather than to
    validate the model. A metre against centimetre slip puts mass out by
    10,000."""
    rng = np.random.default_rng(19)
    for i in range(100):
        m = metrics_for(random_founder(f"P-{i}", rng).phenotype())
        assert 25.0 < m["body_mass_kg"] < 160.0, m["body_mass_kg"]
        assert 5.0 < m["body_fat_percent"] < 55.0, m["body_fat_percent"]
        assert 40.0 < m["leg_length_cm"] < 120.0, m["leg_length_cm"]


# ----------------------------------------------------------------------
# the macro, whose DIRECTION was measured rather than assumed
# ----------------------------------------------------------------------

def test_a_leaner_villager_gets_a_higher_muscle_macro():
    assert muscle_macro({"lean_mass_fraction": 0.85}) > muscle_macro(
        {"lean_mass_fraction": 0.65})


def test_the_macro_is_neutral_at_the_population_mean():
    spec = TRAIT_TABLE["lean_mass_fraction"]
    assert muscle_macro({"lean_mass_fraction": spec.mean}) == pytest.approx(0.5)


def test_the_macro_is_clamped_not_wrapped():
    assert muscle_macro({"lean_mass_fraction": 0.0}) == 0.0
    assert muscle_macro({"lean_mass_fraction": 1.0}) == 1.0


def test_an_absent_trait_bakes_neutral_rather_than_failing():
    """Every body baked before E4 existed used the neutral value, and a
    phenotype with no E4 layer must still bake."""
    assert muscle_macro({"bmi": 24.5}) == pytest.approx(0.5)


def test_the_assumed_macro_direction_matches_the_measured_one():
    """The code assumes a HIGHER muscle macro is a leaner body. That is not
    the naive reading, which is that more muscle means more body, so it is
    held against the probe's recorded measurement rather than against
    anybody's intuition.

    `mpfb/probe_muscle.py` swept the macro and found enclosed mesh volume
    FALLS monotonically, because lean tissue is denser than fat (about 1.06
    against 0.9 g/cm3) so replacing fat with muscle at constant mass shrinks
    the body. If a future MPFB reverses that, this fails and the mapping in
    `muscle_macro` has to be reconsidered rather than quietly left inverted.
    """
    path = REPO / "outputs" / "mpfb" / "muscle.json"
    if not path.exists():
        pytest.skip("run mpfb/probe_muscle.py to record the measurement")
    measured = json.loads(path.read_text(encoding="utf-8"))
    for base, row in measured["bases"].items():
        assert row["volume_monotonic_falling"] is True, base
        assert row["volume_delta_pct"] < 0.0, base
        # And the finding that made this safe to wire at all: it is a shape
        # change, not a stature change, so it cannot disturb the measured
        # stature pipeline.
        assert abs(row["stature_delta_mm"]) < 0.001, base
