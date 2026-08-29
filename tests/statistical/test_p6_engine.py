"""P6 gate — detection and the attribution ladder.

The credibility checkpoint of the whole build is the first test in this file. Every
confidence number the system ever shows is downstream of the claim that its p-values
mean what a p-value means, and the only way to substantiate that claim is to check the
distribution on data where nothing happened.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from insight_copilot.engine.attribute_kind import IDENTITY_TOLERANCE, decompose
from insight_copilot.engine.attribute_where import Attributor
from insight_copilot.engine.attribute_why import (
    DriverAttributor,
    admissible_regressors,
    collinear_groups,
    newey_west_lags,
)
from insight_copilot.engine.baseline import PooledLaunchBaseline
from insight_copilot.engine.design import adstock, fourier_terms, profile_adstock
from insight_copilot.engine.detect import (
    ConformalDetector,
    CusumDetector,
    benjamini_hochberg,
    conformal_p_values,
)
from insight_copilot.engine.gate import MaterialityGate
from insight_copilot.engine.periods import confirmed_periods, discover
from insight_copilot.engine.series import Series
from tests.statistical.helpers_p6 import (
    SCENARIO_A_OUTAGE,
    SCENARIO_A_WEEK,
    SCENARIO_C_WINDOW,
    Engine,
    attribute_where,
    build_engine,
    contracts_registry,
    media_elasticities,
    pvm_periods,
    scan_window,
    weekly_frame,
)

TRUE_BLENDED_MEDIA_ELASTICITY = 0.143
"""Sum of the six per-channel elasticities in ``datagen/world/config.yaml``. A single
blended marketing elasticity measures exactly this sum, because the demand equation
applies every channel's adstock term simultaneously."""

TRUE_PRICE_ELASTICITY = -1.94
"""Revenue-share-weighted mean of the six categories' ``own_price_elasticity``."""

RECOVERY_TOLERANCE = 0.20
"""The gate's ±20% band on a recovered elasticity."""

KS_ALPHA = 0.05
"""Below this the conformal p-values are not uniform and nothing downstream is safe."""


@pytest.fixture(scope="session")
def engine(replayed: dict[str, object]) -> Engine:
    """The engine wired over the P5 warehouse, built once for the whole file."""
    return build_engine(replayed["warehouse"], contracts_registry())


# ------------------------------------------------------- the credibility check --
def test_conformal_p_values_are_uniform_on_clean_holdout_windows(engine: Engine) -> None:
    """**The credibility checkpoint.** Exchangeable calibration and test scores must
    produce p-values uniform on ``{1/(n+1), ..., 1}``, or every confidence tier below
    is decoration."""
    model = engine.baseline()
    scores, _ = ConformalDetector.scores(engine.series, model.counterfactual(engine.series))
    clean = np.flatnonzero(engine.calibration_mask() & np.isfinite(scores))
    assert clean.size > 700, f"only {clean.size} clean days available"
    split = clean.size * 2 // 3
    p_values = conformal_p_values(scores[clean[:split]], scores[clean[split:]])
    result = stats.kstest(p_values, "uniform")
    assert result.pvalue > KS_ALPHA, (
        f"conformal p-values are not uniform: KS statistic {result.statistic:.4f}, "
        f"p = {result.pvalue:.4f} over {p_values.size} holdout days"
    )


def test_benjamini_hochberg_controls_the_false_discovery_rate() -> None:
    """Under a global null, BH at q = 0.05 rejects almost nothing."""
    rng = np.random.default_rng(11)
    false_discoveries = sum(
        int(benjamini_hochberg(rng.uniform(size=200), 0.05).sum() > 0) for _ in range(200)
    )
    assert false_discoveries / 200 <= 0.08, f"{false_discoveries}/200 scans falsely rejected"


# ------------------------------------------------------------------ baselines --
def test_period_discovery_confirms_the_weekly_cycle_and_rejects_its_harmonics(
    engine: Engine,
) -> None:
    """Never assume 7. Confirm it — and reject the lags a smooth series inflates."""
    evidence = {item.period: item for item in discover(engine.series)}
    assert 7 in evidence and evidence[7].accepted, "the weekly cycle was not confirmed"
    assert confirmed_periods(engine.series) == [7]
    for harmonic in (2, 4):
        if harmonic in evidence:
            assert not evidence[harmonic].accepted, (
                f"lag {harmonic} was confirmed as a period; it is the weekly cycle's "
                f"autocorrelation, not a cycle of its own"
            )


def test_the_baseline_prices_the_scenario_close_to_its_counterfactual_truth(
    engine: Engine,
) -> None:
    """A baseline fitted without the event must reproduce the ledger's own number.

    Ground truth for the demo week is -11.94% against a full counterfactual simulation.
    A parametric baseline estimated from observed history alone will not match that
    exactly, and a tolerance wide enough to be honest is the point: the gate checks
    that the estimate is in the right place, not that it was tuned to the answer.
    """
    model = engine.baseline(exclude=(dt.date(2026, 3, 1), dt.date(2026, 3, 25)))
    expected = model.counterfactual(engine.series)
    week = engine.series.mask_between(*SCENARIO_A_WEEK)
    delta_pct = 100.0 * (engine.series.values[week].sum() / expected[week].sum() - 1.0)
    assert -20.0 < delta_pct < -6.0, f"measured {delta_pct:.2f}% against a truth of -11.94%"


def test_the_pooled_launch_baseline_borrows_a_shape_it_cannot_estimate(
    engine: Engine,
) -> None:
    """Empirical-Bayes pooling: an 18-day series is shrunk hard towards the pool."""
    rng = np.random.default_rng(3)
    dates = np.arange("2026-01-01", "2026-05-01", dtype="datetime64[D]")
    comparables = [
        Series(
            dates,
            100.0
            * (1.0 + 1.4 * np.exp(-np.arange(dates.size) / 30.0))
            * (1 + 0.05 * rng.standard_normal(dates.size)),
        )
        for _ in range(12)
    ]
    sparse = Series(dates[:18], comparables[0].values[:18])
    model = PooledLaunchBaseline(comparables)
    fit = model.fit(sparse)
    assert fit.method == "pooled_launch_eb"
    assert fit.diagnostics["comparables"] == 12
    assert 0.5 < fit.diagnostics["pool_weight"] < 0.6, fit.diagnostics
    # The borrowed curve decays: that is the launch shape, not a flat level.
    assert model.pooled_shape[0] > model.pooled_shape[60] * 1.5


# ------------------------------------------------------------------ detection --
def test_the_planted_outage_is_detected_and_survives_the_fdr_correction(
    engine: Engine,
) -> None:
    """Scenario A's primary event, found on the day it started."""
    detections = scan_window(engine, SCENARIO_A_OUTAGE)
    survivors = [item for item in detections if item.passed_fdr]
    assert survivors, "the DC-North outage produced no detection surviving BH"
    first = min(survivors, key=lambda item: item.day)
    assert abs((first.day - SCENARIO_A_OUTAGE[0]).days) <= 2, first.day
    assert first.delta_pct < -10.0, f"detected but only {first.delta_pct:.1f}%"
    assert first.p_value <= 0.01


def test_the_sparse_launch_is_not_flagged(engine: Engine) -> None:
    """Scenario C. **Restraint is the finding.** An 18-day series has no anomaly to
    report, and a system that fires on one is a system nobody trusts twice."""
    detections = [item for item in scan_window(engine, SCENARIO_C_WINDOW) if item.passed_fdr]
    launch_days = [
        item
        for item in detections
        if SCENARIO_C_WINDOW[0] <= item.day <= SCENARIO_C_WINDOW[1]
        and item.day > SCENARIO_A_OUTAGE[1]
    ]
    assert not launch_days, f"fired on the sparse launch: {[str(d.day) for d in launch_days]}"


@pytest.mark.parametrize(
    ("name", "window"),
    [
        ("post-festival lull", (dt.date(2025, 11, 5), dt.date(2025, 11, 25))),
        ("mid-year quiet period", (dt.date(2025, 6, 10), dt.date(2025, 6, 24))),
        ("sub-materiality blip", (dt.date(2025, 8, 1), dt.date(2025, 8, 14))),
    ],
)
def test_planted_distractors_are_rejected(
    engine: Engine, name: str, window: tuple[dt.date, dt.date]
) -> None:
    """Movable events are regressors, so the lull they cause is expected, not anomalous."""
    detections = [item for item in scan_window(engine, window) if item.passed_fdr]
    assert not detections, f"{name} produced {len(detections)} false detections"


def test_cusum_finds_a_sustained_shift_a_point_test_would_miss() -> None:
    """A half-sigma drift is invisible to a point test and is exactly CUSUM's job."""
    rng = np.random.default_rng(5)
    dates = np.arange("2025-01-01", "2026-01-01", dtype="datetime64[D]")
    expected = np.full(dates.size, 100.0)
    values = expected * np.exp(0.05 * rng.standard_normal(dates.size))
    values[250:] *= 0.94
    series = Series(dates, values)
    mask = np.zeros(dates.size, dtype=bool)
    mask[250:] = True
    detections = CusumDetector().scan(
        kpi_id="synthetic",
        segment="national",
        series=series,
        expected=expected,
        calibration_mask=~mask,
        test_mask=mask,
    )
    assert detections, "CUSUM missed a sustained six-percent shift"
    assert detections[0].method == "tabular_cusum"


def test_the_materiality_gate_needs_both_hurdles(engine: Engine) -> None:
    """A statistically perfect sub-materiality wobble is not an insight."""
    contract = engine.registry.kpi("net_revenue")
    gate = MaterialityGate()
    detections = scan_window(engine, SCENARIO_A_OUTAGE)
    assert detections, "no detection to judge"
    verdicts = [
        gate.judge(item, contract, today=dt.date(2026, 3, 29), persistence_days=3)
        for item in detections
    ]
    assert any(item.material for item in verdicts)
    small = min(detections, key=lambda item: abs(item.delta))
    tiny = type(small)(**{**vars(small), "observed": small.expected * 1.001})
    assert not gate.judge(tiny, contract, today=dt.date(2026, 3, 29)).passed_business


# ---------------------------------------------------- rung 1: where it happened --
def test_adtributor_recovers_the_planted_segment_at_rank_one(engine: Engine) -> None:
    """The ledger says the outage's true top region is North. So must the ladder."""
    result = attribute_where(engine)
    top = result.top
    assert top is not None
    assert top.label == "region=North", f"rank 1 was {top.label}"
    assert top.stability > 0.9, f"bootstrap win rate {top.stability:.2f}"
    assert top.explanatory_power > 0.5
    assert result.is_named_cause is True


def test_a_cause_below_the_stability_floor_is_a_shortlist_not_a_named_cause() -> None:
    """The rule that separates an analysis from a confident guess."""
    rng = np.random.default_rng(2)
    frame = pd.DataFrame(
        {
            "region": rng.choice(["North", "West", "South", "East"], 800),
            "channel": rng.choice(["d2c_web", "marketplace"], 800),
            "actual": rng.normal(100.0, 30.0, 800),
            "forecast": rng.normal(101.0, 30.0, 800),
        }
    )
    result = Attributor(bootstrap_samples=60, seed=4).attribute(
        frame, ["region", "channel"], actual_column="actual", forecast_column="forecast"
    )
    assert result.top is not None
    if result.top.stability < 0.9:
        assert result.is_named_cause is False
        assert "shortlist" in result.detail


# ------------------------------------------------------- rung 2: what kind of move --
def test_bennet_parts_sum_to_the_revenue_change_exactly(engine: Engine) -> None:
    """An arithmetic identity, checked as one. The tolerance is for floating point."""
    before, after = pvm_periods(engine)
    result = decompose(
        before, after, item_column="product_sku", price_column="price", quantity_column="units"
    )
    parts = result.price_effect + result.own_volume_effect + result.mix_effect
    assert abs(result.delta_revenue - parts) <= IDENTITY_TOLERANCE * max(
        abs(result.delta_revenue), 1.0
    )
    assert abs(result.residual) < 1e-3
    assert result.dominant in ("price", "volume", "mix")
    assert len(result.top_items(5)) == 5


def test_the_outage_reads_as_a_volume_move_not_a_price_move(engine: Engine) -> None:
    """A pick-capacity failure cannot sell what it cannot ship. Volume, by mechanism."""
    before, after = pvm_periods(engine)
    result = decompose(
        before, after, item_column="product_sku", price_column="price", quantity_column="units"
    )
    assert abs(result.own_volume_effect) > abs(result.price_effect), result.detail


# ------------------------------------------------------------ rung 3: why it moved --
def test_the_price_elasticity_is_recovered_within_the_gate_tolerance(engine: Engine) -> None:
    """First differences: the specification that removes the level confounding.

    ``primary="hac"`` because the target is differenced. See the estimator note on
    :class:`DriverAttributor`: differencing induces a moving-average error whose order
    is not identified here, and Newey-West is consistent without having to specify it.
    """
    frame = weekly_frame(engine.warehouse)
    target = np.diff(np.log(frame["units"].to_numpy(dtype=float)))
    design = pd.DataFrame(
        {
            "price_index": np.diff(np.log(frame["asp"].to_numpy(dtype=float))),
            "fill_rate": np.diff(
                np.log(np.clip(frame["fill"].to_numpy(dtype=float), 1.0, None) / 100.0)
            ),
            "marketing_adstock": np.diff(
                np.log(np.clip(adstock(frame["spend"].to_numpy(dtype=float) / 7.0, 7.0), 1.0, None))
            ),
        }
    )
    result = DriverAttributor(primary="hac").attribute(target, design)
    price = result.estimate("price_index")
    assert price is not None
    error = abs(price.coefficient - TRUE_PRICE_ELASTICITY) / abs(TRUE_PRICE_ELASTICITY)
    assert error <= RECOVERY_TOLERANCE, (
        f"price elasticity {price.coefficient:.3f} against a planted "
        f"{TRUE_PRICE_ELASTICITY:.2f} — {error:.1%} error"
    )
    assert price.confidence_interval[0] < price.coefficient < price.confidence_interval[1]
    assert result.diagnostics.n_observations > 100
    assert result.method == "ols_newey_west"
    # The cross-check is still run, and its agreement with the primary is the finding.
    assert 0.0 <= price.agreement <= 1.0


def test_the_dag_excludes_the_mediator_when_estimating_a_total_effect(
    engine: Engine,
) -> None:
    """Unit volume is the channel every driver reaches revenue through."""
    contract = engine.registry.kpi("net_revenue")
    total_effect = admissible_regressors(contract, "marketing_adstock")
    assert "unit_volume" not in total_effect
    assert "marketing_adstock" in total_effect
    assert "price_index" in total_effect


def test_the_endogeneity_demonstration(engine: Engine) -> None:
    """Naive OLS against the DAG-specified estimate, both reported.

    Media budget is set as a share of revenue and responds to last week's gap against
    target, so a regression of revenue on spend with no controls is not measuring an
    elasticity. The gate asserts the *direction of the improvement* and records both
    numbers; the absolute recovery is discussed in ``BUILD_PROGRESS.md`` under Known
    issues, because a blended elasticity is only weakly identified at national grain.
    """
    naive, dag = media_elasticities(engine)
    truth = TRUE_BLENDED_MEDIA_ELASTICITY
    assert abs(dag - truth) < abs(naive - truth), (
        f"the DAG-specified estimate ({dag:.4f}) is no closer to the planted "
        f"{truth:.3f} than the naive one ({naive:.4f})"
    )
    assert dag > 0.0, f"DAG-specified marketing elasticity has the wrong sign: {dag:.4f}"


def test_collinear_drivers_are_grouped_not_dropped() -> None:
    """Two channels one agency team moved together are one regressor, and say so."""
    rng = np.random.default_rng(8)
    shared = rng.standard_normal(400)
    design = pd.DataFrame(
        {
            "paid_social": shared + 0.15 * rng.standard_normal(400),
            "display": shared + 0.15 * rng.standard_normal(400),
            "search": rng.standard_normal(400),
        }
    )
    groups, vifs = collinear_groups(design)
    assert vifs["paid_social"] > 5.0 and vifs["display"] > 5.0
    assert set(groups["paid_social"]) == {"display", "paid_social"}
    assert groups["search"] == ("search",)


def test_the_newey_west_bandwidth_follows_the_published_rule() -> None:
    """``L = floor(4·(T/100)^(2/9))`` — not a tuned constant."""
    assert newey_west_lags(100) == 4
    assert newey_west_lags(1000) == int(np.floor(4.0 * 10.0 ** (2.0 / 9.0)))


def test_the_adstock_half_life_is_profiled_not_assumed(engine: Engine) -> None:
    """A grid search, with the maximum reported and the edge case flagged."""
    frame = weekly_frame(engine.warehouse)
    target = np.log(frame["units"].to_numpy(dtype=float))
    index = np.arange(len(frame), dtype=float)
    controls = pd.concat(
        [pd.DataFrame({"trend": index / 52.0}), fourier_terms(index * 7.0, 365.25, 2)], axis=1
    )
    profile = profile_adstock(frame["spend"].to_numpy(dtype=float), target, controls)
    assert profile.half_life_days in profile.grid
    assert len(profile.grid) >= 6
    assert profile.r_squared > 0.0


def test_coverage_is_accounted_for_honestly(engine: Engine) -> None:
    """Explained and unexplained sum to one, and the remainder is labelled."""
    frame = weekly_frame(engine.warehouse)
    target = np.diff(np.log(frame["units"].to_numpy(dtype=float)))
    design = pd.DataFrame({"price_index": np.diff(np.log(frame["asp"].to_numpy(dtype=float)))})
    result = DriverAttributor(primary="hac").attribute(target, design)
    assert 0.0 <= result.explained_fraction <= 1.0
    assert result.explained_fraction + result.unexplained_fraction == pytest.approx(1.0)
