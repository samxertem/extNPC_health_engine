"""
Scientific-accuracy tests for the dashboard.

The engine's own laws are tested elsewhere. The question here is different and
narrower: **does the dashboard tell the truth about the engine?** A panel can
be beautiful, never raise, and still be wrong -- a bar that omits half the
population, a percentage divided by the wrong denominator, an axis that clips
the interesting half of the data, a "0.000" printed where nothing was
measured.

So every test recomputes the quantity independently from the engine objects
and compares it to what the figure actually carries. Where a panel claims a
textbook signature (Wright's island model, hemizygosity, strict maternal
mtDNA, parent-of-origin expression, Morton's regression), the signature
itself is asserted rather than assumed.
"""

import warnings

import numpy as np
import pytest

from dashboard import genetics_panels as gp, inspector, panels
from simulation import DemographyParams, World
import simulation.metrics as M

warnings.filterwarnings("ignore")


@pytest.fixture(scope="module")
def world():
    """One shared mid-sized world with real structure: several generations,
    deaths, couples, and enough people for the distributions to mean something."""
    w = World(n_founders=18, seed=11)
    for _ in range(35):
        w.step()
    return w


@pytest.fixture(scope="module")
def cols(world):
    return world.history_columns()


def _hist(fig, idx=0):
    return np.asarray(fig.data[idx].x, dtype=float)


# =====================================================================
# 1. The KPI row must equal the engine's own history
# =====================================================================

def test_every_kpi_tile_matches_the_history_row_it_claims_to_show(world, cols):
    tiles = {t["key"]: t for t in panels.kpi_data(cols, world.params)}
    last = world.history[-1]

    assert tiles["n_alive"]["value"] == str(int(last["n_alive"]))
    assert tiles["max_generation"]["value"] == str(int(last["max_generation"]))
    assert tiles["n_couples"]["value"] == str(int(last["n_couples"]))
    assert tiles["heterozygosity"]["value"] == f"{last['heterozygosity']:.3f}"
    assert tiles["mean_relatedness"]["value"] == f"{last['mean_relatedness']:.3f}"


def test_the_alive_tile_equals_the_actual_number_of_living_people(world, cols):
    tiles = {t["key"]: t for t in panels.kpi_data(cols, world.params)}
    assert int(tiles["n_alive"]["value"]) == len(world.living)


def test_kpi_delta_is_the_change_over_the_last_ten_recorded_years(world, cols):
    tiles = {t["key"]: t for t in panels.kpi_data(cols, world.params)}
    series = cols["heterozygosity"]
    expected = series[-1] - (series[-11] if len(series) > 11 else series[0])
    assert tiles["heterozygosity"]["delta"] == pytest.approx(expected)


def test_fst_is_reported_as_undefined_without_population_structure(world, cols):
    """One deme means no partition to estimate over. Printing 0.000 would
    assert a measurement that was never made."""
    assert world.params.n_demes == 1
    tiles = {t["key"]: t for t in panels.kpi_data(cols, world.params)}
    assert tiles["fst"]["value"] == "—"


# =====================================================================
# 2. Allele frequencies, heterozygosity, trait distributions
# =====================================================================

def test_allele_spectrum_plots_real_frequencies_in_the_unit_interval(world):
    fig = gp.allele_spectrum_figure(world)
    p = _hist(fig)
    dosage = np.array([n.genome.dosage for n in world.living], dtype=float)
    expected = dosage.mean(axis=0) / 2.0
    assert p.size == expected.size == dosage.shape[1]
    assert np.allclose(np.sort(p), np.sort(expected))
    assert p.min() >= 0.0 and p.max() <= 1.0, "an allele frequency outside [0,1]"


def test_allele_spectrum_title_counts_lost_and_fixed_loci_correctly(world):
    fig = gp.allele_spectrum_figure(world)
    dosage = np.array([n.genome.dosage for n in world.living], dtype=float)
    p = dosage.mean(axis=0) / 2.0
    lost, fixed = int(np.sum(p <= 0.001)), int(np.sum(p >= 0.999))
    assert f"{lost} lost, {fixed} fixed" in fig.layout.title.text


def test_heterozygosity_histogram_shows_every_living_individual(world):
    fig = gp.heterozygosity_hist_figure(world)
    h = _hist(fig)
    expected = np.array([n.heterozygosity() for n in world.living])
    assert h.size == len(world.living)
    assert np.allclose(np.sort(h), np.sort(expected))
    assert (h >= 0).all() and (h <= 1).all()


def test_the_heterozygosity_mean_line_sits_on_the_actual_mean(world):
    fig = gp.heterozygosity_hist_figure(world)
    expected = float(np.mean([n.heterozygosity() for n in world.living]))
    line = [s for s in fig.layout.shapes if s.type == "line"][0]
    assert float(line.x0) == pytest.approx(expected)
    assert f"{expected:.3f}" in fig.layout.annotations[0].text


def test_population_heterozygosity_kpi_equals_the_mean_of_the_individuals(world, cols):
    """The diversity line is a single number summarising the histogram beside
    it; if they disagree, one of the two panels is lying."""
    tiles = {t["key"]: t for t in panels.kpi_data(cols, world.params)}
    individual_mean = float(np.mean([n.heterozygosity() for n in world.living]))
    assert tiles["heterozygosity"]["value"] == f"{individual_mean:.3f}"


@pytest.mark.parametrize("trait", ["height_cm", "bmi"])
def test_trait_distribution_plots_the_real_phenotypes_split_by_sex(world, trait):
    fig = gp.trait_distribution_figure(world, trait)
    by_sex = {tr.name: np.sort(np.asarray(tr.x, dtype=float)) for tr in fig.data}
    for sex in ("female", "male"):
        expected = np.sort(np.array([n.phenotype()[trait]
                                     for n in world.living if n.sex == sex]))
        if expected.size:
            assert np.allclose(by_sex[sex], expected)
    assert sum(len(v) for v in by_sex.values()) == len(world.living)


# =====================================================================
# 3. Demography
# =====================================================================

def test_age_pyramid_accounts_for_every_living_person_exactly_once(world):
    fig = gp.age_pyramid_figure(world)
    female = -np.asarray(fig.data[0].x, dtype=float)   # drawn negative
    male = np.asarray(fig.data[1].x, dtype=float)
    assert female.sum() + male.sum() == len(world.living)
    assert female.sum() == sum(1 for n in world.living if n.sex == "female")
    assert male.sum() == sum(1 for n in world.living if n.sex == "male")


def test_age_pyramid_bins_match_the_engine_metric(world):
    labels, f, m = M.age_pyramid(world.living, bin_width=10, max_age=100)
    fig = gp.age_pyramid_figure(world)
    assert list(fig.data[0].y) == list(labels)
    assert np.allclose(-np.asarray(fig.data[0].x, dtype=float), f)
    assert np.allclose(np.asarray(fig.data[1].x, dtype=float), m)


def test_deme_headcounts_sum_to_the_living_population(world):
    fig = panels.deme_bar_figure(world)
    assert sum(np.asarray(fig.data[0].y, dtype=float)) == len(world.living)


def test_population_chart_matches_the_recorded_headcount(world, cols):
    fig = panels.population_figure(cols)
    assert list(fig.data[0].y) == list(cols["n_alive"])
    assert fig.data[0].y[-1] == len(world.living)


# =====================================================================
# 4. The parallel inheritance layers
# =====================================================================

def test_mito_chart_counts_every_carrier_and_nobody_else(world):
    fig = gp.mito_haplogroup_figure(world)
    counts = dict(zip(fig.data[0].x, np.asarray(fig.data[0].y, dtype=int)))
    carriers = [n for n in world.living if n.mito is not None]
    expected = {}
    for n in carriers:
        expected[n.mito.haplogroup] = expected.get(n.mito.haplogroup, 0) + 1
    assert counts == expected
    assert sum(counts.values()) == len(carriers)


def test_mito_chart_is_bars_of_strictly_maternal_lines(world):
    """
    The panel claims female-line descent (#3). If transmission were not
    strictly maternal the bars would not be lineages at all -- so assert the
    mechanism on the actual pedigree the chart is drawn from.
    """
    checked = 0
    for n in world.living:
        if not n.parents or n.mito is None:
            continue
        mother = world.people.get(n.parents[0])
        if mother is None or mother.mito is None:
            continue
        assert n.mito.haplogroup == mother.mito.haplogroup, \
            f"{n.name} broke maternal transmission"
        checked += 1
    assert checked > 5, "not enough parent-child pairs to make the test mean anything"


def test_sex_linked_percentages_match_an_independent_recomputation(world):
    fig = gp.sex_linked_figure(world)
    shown = {tr.name: np.asarray(tr.y, dtype=float) for tr in fig.data}
    people = [n for n in world.living if n.sex_chromosomes is not None]
    for sex in ("female", "male"):
        grp = [n for n in people if n.sex == sex]
        d = max(len(grp), 1)
        ph = [n.x_linked_phenotype() for n in grp]
        expected = [
            100.0 * sum(1 for p in ph if p.get("color_vision") != "normal") / d,
            100.0 * sum(1 for p in ph if float(p.get("g6pd_activity", 1.0)) < 0.4) / d,
            100.0 * sum(1 for p in ph if p.get("pattern_baldness")) / d,
        ]
        assert np.allclose(shown[sex], expected)


def test_sex_linked_percentages_are_percentages(world):
    fig = gp.sex_linked_figure(world)
    for tr in fig.data:
        y = np.asarray(tr.y, dtype=float)
        assert (y >= 0).all() and (y <= 100).all()


def test_hemizygosity_signature_males_exceed_females(world):
    """
    X-linked recessives appear at ~q in males but ~q^2 in females. Nothing in
    the panel computes that ratio -- it falls out of males carrying a single
    X -- so it is a real prediction the chart either shows or does not.
    """
    fig = gp.sex_linked_figure(world)
    shown = {tr.name: np.asarray(tr.y, dtype=float) for tr in fig.data}
    cb_f, cb_m = shown["female"][0], shown["male"][0]
    if cb_f == 0 and cb_m == 0:
        pytest.skip("no colour-vision variants segregating in this world")
    assert cb_m >= cb_f, f"males {cb_m:.1f}% should not fall below females {cb_f:.1f}%"


def test_imprinting_chart_partitions_the_population_with_no_double_counting(world):
    from health_engine.imprint import parent_of_origin_report
    fig = gp.imprinting_figure(world)
    counts = np.asarray(fig.data[0].y, dtype=int)
    assert counts.sum() == len(world.living)

    expected = [0, 0, 0, 0]
    for n in world.living:
        r = parent_of_origin_report(n.genome, "IGF2")
        if r["dosage"] == 0:
            expected[0] += 1
        elif r["dosage"] == 2:
            expected[3] += 1
        elif r["expressed_allele"] == 1:
            expected[2] += 1
        else:
            expected[1] += 1
    assert list(counts) == expected


def test_imprinting_separates_the_two_heterozygote_classes(world):
    """The middle two bars are both genotypic heterozygotes; that they are
    counted separately at all IS the parent-of-origin mechanism."""
    fig = gp.imprinting_figure(world)
    labels = list(fig.data[0].x)
    assert "mother" in labels[1] and "father" in labels[2]
    het_total = int(fig.data[0].y[1]) + int(fig.data[0].y[2])
    from health_engine.imprint import parent_of_origin_report
    real_hets = sum(1 for n in world.living
                    if parent_of_origin_report(n.genome, "IGF2")["dosage"] == 1)
    assert het_total == real_hets


def test_mutation_load_excludes_founders_and_matches_the_real_counts(world):
    fig = gp.mutation_load_figure(world)
    gens = [int(g.split()[1]) for g in fig.data[0].x]
    means = np.asarray(fig.data[0].y, dtype=float)
    assert 0 not in gens, "founders carry no de novo mutations by construction"

    by_gen = {}
    for n in world.living:
        if n.generation > 0:
            by_gen.setdefault(n.generation, []).append(float(n.de_novo_mutations))
    assert gens == sorted(by_gen)
    assert np.allclose(means, [np.mean(by_gen[g]) for g in gens])


def test_founders_really_do_carry_no_de_novo_mutations(world):
    founders = [n for n in world.people.values() if n.generation == 0]
    assert founders
    assert all(n.de_novo_mutations == 0 for n in founders)


# =====================================================================
# 5. Inbreeding: Morton's law, and the axis that used to hide it
# =====================================================================

def test_mean_pedigree_F_never_exceeds_the_maximum(world, cols):
    fig = panels.inbreeding_figure(cols)
    series = {tr.name: np.asarray(tr.y, dtype=float) for tr in fig.data}
    assert (series["mean F"] <= series["max F"] + 1e-12).all()


def test_inbreeding_axes_bracket_the_data_they_plot(world, cols):
    """
    Regression test for the session-12 bug: relative viability can legitimately
    exceed 1.0, and a hard ceiling chopped the line into fragments. Every
    series must lie inside its own axis.
    """
    fig = panels.inbreeding_figure(cols)
    for tr in fig.data:
        y = np.asarray(tr.y, dtype=float)
        y = y[~np.isnan(y)]
        if not y.size:
            continue
        axis = fig.layout.yaxis2 if tr.yaxis == "y2" else fig.layout.yaxis
        lo, hi = axis.range
        assert lo <= y.min() and y.max() <= hi, \
            f"{tr.name} spans {y.min():.4f}..{y.max():.4f} outside axis {lo}..{hi}"


def test_pedigree_F_series_matches_the_engine(world, cols):
    fig = panels.inbreeding_figure(cols)
    series = {tr.name: list(np.asarray(tr.y, dtype=float)) for tr in fig.data}
    assert series["mean F"] == pytest.approx(list(cols["mean_inbreeding"]))
    assert series["max F"] == pytest.approx(list(cols["max_inbreeding"]))


def test_displayed_pedigree_F_equals_the_malecot_coefficient(world):
    """The directory and drawer read pedigree F off a snapshot frame; it must
    equal what `World.inbreeding_of` computes from the pedigree."""
    frame = world.frame_at(None)
    checked = 0
    for p in frame["people"][:40]:
        assert p["pedigree_f"] == pytest.approx(world.inbreeding_of(p["name"]))
        checked += 1
    assert checked > 10


def test_the_relationship_label_matches_the_F_it_is_attached_to(world):
    """Every displayed F carries a plain-language mating label; the label must
    not overstate how close the parents were."""
    thresholds = {"full sib / parent–offspring": 0.25,
                  "uncle–niece / double first cousin": 0.125,
                  "first cousins": 0.0625,
                  "first cousins once removed": 0.03125,
                  "second cousins": 0.015625}
    for p in world.frame_at(None)["people"]:
        F = p["pedigree_f"]
        label = inspector.relationship_label(F)
        if label in thresholds:
            assert F >= thresholds[label] - 1e-9


def test_consanguinity_share_uses_the_conventional_threshold(world, cols):
    """Consanguinity studies count from F >= 1/64 (second cousins)."""
    expected = 100.0 * sum(1 for n in world.living
                           if world.inbreeding_of(n.name) >= 1 / 64) / \
        max(len(world.living), 1)
    assert cols["pct_inbred"][-1] == pytest.approx(expected, abs=1e-6)


# =====================================================================
# 6. Population structure: Wright's island model
# =====================================================================

@pytest.fixture(scope="module")
def isolated_islands():
    p = DemographyParams(carrying_capacity=220, n_demes=4, migration_rate=0.0)
    w = World(n_founders=24, seed=5, params=p)
    for _ in range(40):
        w.step()
    return w


@pytest.fixture(scope="module")
def melting_pot():
    p = DemographyParams(carrying_capacity=220, n_demes=4, migration_rate=0.25)
    w = World(n_founders=24, seed=5, params=p)
    for _ in range(40):
        w.step()
    return w


def test_isolation_raises_FST_above_heavy_migration(isolated_islands, melting_pot):
    """
    Wright 1931: F_ST ~ 1/(4*N*m + 1). More gene flow, less differentiation.
    This is the single strongest scientific claim the Community tab makes, and
    it is an emergent one -- nothing in the code sets F_ST.
    """
    iso = isolated_islands.history[-1]["fst"]
    mix = melting_pot.history[-1]["fst"]
    assert iso > mix, f"isolated {iso:.4f} should exceed melting pot {mix:.4f}"
    assert mix < 0.05, f"heavy migration should keep F_ST near zero, got {mix:.4f}"


def test_the_fst_chart_shows_the_estimate_once_there_is_structure(isolated_islands):
    cols = isolated_islands.history_columns()
    fig = panels.fst_figure(cols, isolated_islands.params.n_demes)
    assert fig.data, "a structured world must actually draw the F_ST series"
    assert list(fig.data[0].y) == pytest.approx(list(cols["fst"]))
    assert "Weir & Cockerham" in fig.layout.title.text


def test_the_fst_axis_is_not_clamped_at_zero(isolated_islands):
    """The W&C estimator is unbiased and can legitimately go negative;
    clamping would hide exactly the scatter that shows it working."""
    cols = isolated_islands.history_columns()
    fig = panels.fst_figure(cols, 4)
    assert fig.layout.yaxis.rangemode != "tozero"


def test_deme_headcounts_sum_correctly_with_several_demes(isolated_islands):
    fig = panels.deme_bar_figure(isolated_islands)
    assert sum(np.asarray(fig.data[0].y, dtype=float)) == len(isolated_islands.living)
    assert len(fig.data[0].x) == isolated_islands.params.n_demes


def test_migration_actually_moves_people_between_demes(melting_pot):
    assert melting_pot.history[-1]["n_migrations"] >= 0
    assert sum(r["n_migrations"] for r in melting_pot.history) > 0


# =====================================================================
# 7. Time-series chart semantics
# =====================================================================

def test_trait_chart_starts_every_series_at_zero_change(cols):
    """The y axis is 'change from the founding mean in phenotypic SD', so
    every trace must begin at exactly 0 or the baseline is wrong."""
    fig = panels.traits_figure(cols)
    for tr in fig.data:
        y = np.asarray(tr.y, dtype=float)
        if y.size:
            assert y[0] == pytest.approx(0.0)


def test_trait_chart_is_standardised_not_raw(cols):
    """Standardising by phenotypic SD is what stops a near-zero-mean liability
    trait producing +2000% swings. Height in SD units must be far smaller than
    height in centimetres."""
    from health_engine.traits import TRAIT_TABLE
    fig = panels.traits_figure(cols)
    series = {tr.name: np.asarray(tr.y, dtype=float) for tr in fig.data}
    raw = np.asarray(cols["trait_height_cm"], dtype=float)
    sd = float(TRAIT_TABLE["height_cm"].sd)
    assert np.allclose(series["height_cm"], (raw - raw[0]) / sd)
    assert np.abs(series["height_cm"]).max() < np.abs(raw - raw[0]).max()


def test_candlestick_obeys_the_ohlc_invariants(cols):
    fig = panels.candlestick_figure(cols)
    tr = fig.data[0]
    o, h, l, c = (np.asarray(v, dtype=float)
                  for v in (tr.open, tr.high, tr.low, tr.close))
    assert (l <= np.minimum(o, c) + 1e-9).all(), "low must not exceed open/close"
    assert (h >= np.maximum(o, c) - 1e-9).all(), "high must not fall below open/close"
    assert (h >= l).all()


def test_candlestick_decades_open_and_close_on_the_right_years(cols):
    fig = panels.candlestick_figure(cols)
    tr = fig.data[0]
    ticks = np.asarray(cols["tick"], dtype=float)
    vals = np.asarray(cols["n_alive"], dtype=float)
    for i, label in enumerate(tr.x):
        decade = int(str(label).rstrip("s"))
        mask = (ticks // 10 * 10) == decade
        assert tr.open[i] == vals[mask][0]
        assert tr.close[i] == vals[mask][-1]
        assert tr.high[i] == vals[mask].max()
        assert tr.low[i] == vals[mask].min()


def test_history_spiral_winds_at_twelve_years_per_revolution(cols):
    fig = panels.spiral_figure(cols)
    t = np.asarray(cols["tick"], dtype=float)
    assert np.allclose(np.asarray(fig.data[0].theta, dtype=float), (t * 30.0) % 360.0)
    assert np.allclose(np.asarray(fig.data[0].r, dtype=float), t)


def test_diversity_axis_contains_the_series_and_the_drift_threshold(cols):
    fig = panels.diversity_figure(cols)
    y = np.asarray(fig.data[0].y, dtype=float)
    lo, hi = fig.layout.yaxis.range
    assert lo <= y.min() and y.max() <= hi
    assert lo <= 0.33 <= hi, "the drift-loss threshold line must be visible"


def test_couple_kinship_chart_marks_the_first_cousin_line(cols):
    fig = panels.relatedness_figure(cols)
    lines = [s for s in fig.layout.shapes if s.type == "line"]
    assert any(float(s.y0) == pytest.approx(0.0625) for s in lines)
    assert list(fig.data[0].y) == pytest.approx(list(cols["mean_relatedness"]))


def test_reproductive_skew_is_a_gini_coefficient(cols):
    """Gini lives in [0,1]; anything outside means the metric is broken."""
    y = np.asarray(cols["reproductive_skew"], dtype=float)
    assert (y >= 0).all() and (y <= 1).all()


def test_crash_markers_only_appear_on_real_crashes(cols):
    """The population chart annotates years that fell >= 20%. A marker on a
    year that did not crash would be a false alarm on the headline panel."""
    fig = panels.population_figure(cols)
    n = np.asarray(cols["n_alive"], dtype=float)
    t = list(cols["tick"])
    crash_years = {t[i] for i in range(1, len(n))
                   if n[i - 1] > 0 and (n[i] - n[i - 1]) / n[i - 1] <= -0.20}
    marked = {tr.x[0] for tr in fig.data[1:]}
    assert marked == crash_years


# =====================================================================
# 8. The genetic map and the individual views
# =====================================================================

def test_the_dot_cloud_plots_every_living_individual_once(world):
    fig = panels.scatter_figure(world)
    plotted = sum(len(tr.x) for tr in fig.data if tr.name in ("female", "male"))
    assert plotted == len(world.living)


def test_dot_cloud_coordinates_are_finite(world):
    fig = panels.scatter_figure(world)
    for tr in fig.data:
        xy = np.concatenate([np.asarray(tr.x, dtype=float),
                             np.asarray(tr.y, dtype=float)])
        assert np.isfinite(xy).all()


def test_selecting_someone_adds_a_highlight_without_duplicating_them(world):
    name = world.living[0].name
    plain = panels.scatter_figure(world)
    picked = panels.scatter_figure(world, name)
    assert len(picked.data) == len(plain.data) + 1
    body = sum(len(tr.x) for tr in picked.data if tr.name in ("female", "male"))
    assert body == len(world.living)


def test_age_expressed_height_never_exceeds_the_mature_endpoint(world):
    """#13: nobody is ever taller than the adult stature they are growing
    toward, at any age."""
    for n in world.living:
        assert n.height_at_age() <= n.phenotype()["height_cm"] + 1e-6


def test_young_adults_sit_exactly_on_their_genetic_endpoint(world):
    """`stature_fraction` reaches exactly 1.0 by age 20, so a grown adult who
    has not begun to shrink must be at their endpoint to the millimetre."""
    checked = 0
    for n in world.living:
        if 20 <= n.age < 40:
            assert n.height_at_age() == pytest.approx(
                n.phenotype()["height_cm"], abs=0.05)
            checked += 1
    if not checked:
        pytest.skip("no adults aged 20-40 in this world")


def test_stature_declines_after_forty_at_the_sorkin_rate(world):
    """
    The gap between an older adult's height and their endpoint is not an
    error -- it is modelled senescence: stature falls ~1 cm per decade from
    about 40, accelerating (Sorkin, Muller & Andres 1999, *Am. J. Epidemiol.*
    150:969). This test exists because the naive expectation (adult height ==
    mature height forever) looks like a bug when you first see it in the
    inspector.
    """
    n = next((p for p in world.living if p.age >= 55), None)
    if n is None:
        pytest.skip("nobody old enough to have lost measurable height")
    mature = n.phenotype()["height_cm"]

    at_30 = n.height_at_age(age=30)
    at_40 = n.height_at_age(age=40)
    at_60 = n.height_at_age(age=60)
    at_80 = n.height_at_age(age=80)

    assert at_30 == pytest.approx(mature, abs=0.05), "no loss before 40"
    assert at_40 <= at_30 + 1e-9
    assert at_60 < at_40, "stature must fall after 40"
    assert at_80 < at_60, "and keep falling"

    loss_per_decade = (at_40 - at_60) / 2.0
    assert 0.3 <= loss_per_decade <= 2.5, \
        f"{loss_per_decade:.2f} cm/decade is outside the published range"
    # accelerating: the second two decades must cost more than the first two
    assert (at_60 - at_80) > (at_40 - at_60) - 1e-9, "loss should accelerate"


def test_growth_is_monotone_with_age(world):
    """Height must not go backwards as a child ages, or the growth curve is
    not a growth curve."""
    n = next((p for p in world.living if p.life_stage() == "child"), None)
    if n is None:
        pytest.skip("no child alive in this world")
    heights = [n.height_at_age(age=a) for a in range(1, 19)]
    assert heights == sorted(heights)


def test_the_drawer_shows_the_height_the_engine_computes(world):
    frame = world.frame_at(None)
    for p in frame["people"][:30]:
        npc = world.people[p["name"]]
        assert p["height"] == pytest.approx(npc.height_at_age(), abs=0.05)


def test_compare_relatedness_is_symmetric(world):
    a, b = world.living[0].name, world.living[1].name
    assert _relatedness_from_compare(world, a, b) == \
        pytest.approx(_relatedness_from_compare(world, b, a), abs=1e-12)


def test_self_relatedness_is_one_plus_F_not_exactly_one(world):
    """
    The compare panel's measured r is the GCTA estimator (Yang et al. 2010),
    whose DIAGONAL has expectation 1 + F -- not 1. It is also anchored to the
    FOUNDING allele frequencies, so it drifts as the population does. Anyone
    reading r as a bounded [0,1] coefficient will misread the panel; this test
    pins the actual scale.
    """
    a = world.living[0].name
    self_r = _relatedness_from_compare(world, a, a)
    assert 0.7 < self_r < 1.4, f"self-relatedness {self_r:.3f} is off-scale"
    others = [_relatedness_from_compare(world, a, n.name)
              for n in world.living[1:20] if n.name != a]
    assert self_r > max(others), "nobody may be more related to a than a is"


def test_parent_offspring_relatedness_centres_on_one_half(world):
    """
    The headline claim of the compare panel. Parent-offspring is exactly half
    the genome every time, so the MEAN over many pairs must sit near 0.5 --
    and must be clearly above the relatedness of random pairs, or the panel's
    'parent-offspring or full sibs' label means nothing.
    """
    pairs = []
    for n in world.living:
        for pname in (n.parents or ()):
            if pname in world.people:
                pairs.append(_relatedness_from_compare(world, n.name, pname))
    if len(pairs) < 8:
        pytest.skip("not enough surviving parent-child pairs")

    mean_po = float(np.mean(pairs))
    rng = np.random.default_rng(0)
    names = [n.name for n in world.living]
    randoms = []
    for _ in range(60):
        x, y = rng.choice(names, 2, replace=False)
        randoms.append(_relatedness_from_compare(world, x, y))
    mean_rand = float(np.mean(randoms))

    assert 0.35 < mean_po < 0.75, f"parent-offspring mean r = {mean_po:.3f}"
    assert mean_po > mean_rand + 0.2, \
        f"parent-offspring {mean_po:.3f} vs random {mean_rand:.3f}"


def _relatedness_from_compare(world, a, b):
    from health_engine.mating import genomic_relatedness
    return genomic_relatedness(world.people[a], world.people[b])


def test_compare_bars_are_z_scores_against_the_living_population(world):
    """An individual at the population mean must sit at zero, or the axis
    label 'SD from population mean' is false."""
    fig = panels.compare_bars_figure(world, world.living[0].name, None)
    keys = ["insulin_sensitivity", "bp_set_point", "lipid_profile",
            "lung_capacity", "immune_reactivity", "inflammation_tone"]
    pop = [n.phenotype() for n in world.living]
    p = world.people[world.living[0].name].phenotype()
    expected = []
    for k in keys:
        vals = np.array([float(q[k]) for q in pop])
        sd = vals.std() if vals.std() > 1e-9 else 1.0
        expected.append((float(p[k]) - vals.mean()) / sd)
    assert np.allclose(np.asarray(fig.data[0].y, dtype=float), expected)


def test_population_radar_is_the_mean_of_the_individual_scores(world):
    fig = panels.population_radar_figure(world)
    traits = panels._OCEAN + panels._BODY
    phes = [n.phenotype() for n in world.living]
    expected = [float(np.mean([panels._to_score(t, p[t]) for p in phes]))
                for t in traits]
    # the radar closes the polygon by repeating the first point
    assert np.allclose(np.asarray(fig.data[0].r, dtype=float)[:-1], expected)


def test_leaderboards_are_actually_ordered_by_the_field_they_name(world):
    frame = world.frame_at(None)
    for key, _label, field, _fmt, reverse in inspector.BOARDS:
        rows = inspector.leaderboard_entries(frame, key, top=5)
        vals = [r.get(field, 0) for r in rows]
        assert vals == sorted(vals, reverse=reverse), f"board {key} misordered"


def test_the_frail_board_is_the_only_ascending_one(world):
    """Frailty is the one board where the interesting end is the bottom."""
    ascending = [b[0] for b in inspector.BOARDS if not b[4]]
    assert ascending == ["frail"]
    frame = world.frame_at(None)
    rows = inspector.leaderboard_entries(frame, "frail", top=3)
    everyone = sorted(frame["people"], key=lambda p: p.get("viability", 1.0))
    assert [r["name"] for r in rows] == [p["name"] for p in everyone[:3]]


def test_bloodline_sizes_sum_to_no_more_than_the_population(world):
    frame = world.frame_at(None)
    sizes = inspector.lineage_sizes(frame, top=100)
    assert sum(n for _, n, _ in sizes) == len(frame["people"])


def test_map_payload_positions_agree_with_the_snapshot_frame(world):
    from dashboard.app import build_mapdata
    frame = world.frame_at(None)
    d = build_mapdata(world, None, frame=frame)
    by_name = {p["name"]: p for p in frame["people"]}
    for p in d["people"]:
        assert p["x"] == by_name[p["name"]]["x"]
        assert p["y"] == by_name[p["name"]]["y"]
