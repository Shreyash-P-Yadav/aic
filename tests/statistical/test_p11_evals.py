"""P11 — the metrics themselves, the tier derivation, and the ledger's window truth.

These are the tests that keep the eval suite honest. A metric that can be nudged by a
change to the thing it measures is not a measurement, so every one of them is checked
against a case whose answer is known by construction.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from insight_copilot.contracts.governance import ConfidencePolicy
from insight_copilot.engine.calibration import IsotonicCalibrator
from insight_copilot.engine.tiers import TIER_RELIABILITY_TARGETS, TierBoundaries, derive_boundaries
from insight_copilot.errors import StatisticalError
from insight_copilot.evals.metrics import (
    DetectionCounts,
    brier_score,
    expected_calibration_error,
    kendall_tau,
    mean_relative_error,
    reliability_curve,
)
from insight_copilot.evals.models import Measurement
from insight_copilot.evals.truth import LedgerTruth

POLICY = ConfidencePolicy(min_history_days_full_stats=180, abstain_below=0.35, hedge_below=0.60)


def test_a_perfect_forecaster_has_zero_calibration_error() -> None:
    """The identity case: predict 0 for every miss and 1 for every hit."""
    scores = np.array([0.0, 0.0, 1.0, 1.0])
    outcomes = np.array([0.0, 0.0, 1.0, 1.0])
    assert expected_calibration_error(scores, outcomes) == pytest.approx(0.0)
    assert brier_score(scores, outcomes) == pytest.approx(0.0)


def test_a_confidently_wrong_forecaster_has_maximal_calibration_error() -> None:
    """Predicting 1.0 on everything that failed is an ECE of exactly 1."""
    scores = np.ones(20)
    outcomes = np.zeros(20)
    assert expected_calibration_error(scores, outcomes) == pytest.approx(1.0)


def test_a_constant_at_the_base_rate_is_well_calibrated_and_useless() -> None:
    """The property that makes ECE insufficient on its own — and why AUC is reported.

    A forecaster that predicts the base rate for everything has a near-zero ECE while
    telling the reader nothing. This is the exact failure mode the discrimination floor
    in the eval suite exists to catch, so it is pinned here.
    """
    rng = np.random.default_rng(11)
    outcomes = (rng.random(400) < 0.3).astype(float)
    scores = np.full(400, float(outcomes.mean()))
    assert expected_calibration_error(scores, outcomes) < 0.02


def test_empty_bins_do_not_count_as_well_calibrated() -> None:
    """A bin nobody landed in is not evidence of anything."""
    scores = np.full(50, 0.05)
    outcomes = np.zeros(50)
    curve = reliability_curve(scores, outcomes, bins=10)
    populated = [item for item in curve if item.n]
    assert len(populated) == 1
    assert sum(item.n for item in curve) == 50


def test_reliability_curve_bins_carry_their_counts() -> None:
    """Every bin reports ``n`` — the spec asks for the per-tier table with counts."""
    scores = np.linspace(0.0, 1.0, 100)
    outcomes = (scores > 0.5).astype(float)
    curve = reliability_curve(scores, outcomes, bins=10)
    assert len(curve) == 10
    assert sum(item.n for item in curve) == 100
    assert all(item.n > 0 for item in curve)


def test_mean_relative_error_is_scale_free() -> None:
    """A 10% error on a crore and on a lakh are the same error."""
    assert mean_relative_error(np.array([1.1e7, 1.1e5]), np.array([1e7, 1e5])) == pytest.approx(0.1)


def test_kendall_tau_is_one_for_an_identical_ranking() -> None:
    """And -1 when the order is exactly reversed."""
    assert kendall_tau(["a", "b", "c"], ["a", "b", "c"]) == pytest.approx(1.0)
    assert kendall_tau(["c", "b", "a"], ["a", "b", "c"]) == pytest.approx(-1.0)


def test_kendall_tau_refuses_a_ranking_it_cannot_compare() -> None:
    """Fewer than two shared items is a typed error, never a fabricated 0."""
    with pytest.raises(StatisticalError):
        kendall_tau(["x"], ["a", "b", "c"])


def test_detection_counts_are_undefined_rather_than_zero_when_nothing_was_flagged() -> None:
    """Precision over an empty flag set is ``nan``. Reporting 0 would be a claim."""
    counts = DetectionCounts(true_positive=0, false_positive=0, false_negative=5)
    assert np.isnan(counts.precision)
    assert counts.recall == pytest.approx(0.0)


def test_tier_boundaries_come_from_the_curve_not_from_a_round_number() -> None:
    """A steeper curve reaches each promised hit rate sooner, and the bands follow."""
    shallow = _calibrator_through(lambda score: 0.55 * score)
    steep = _calibrator_through(lambda score: min(1.0, 1.15 * score))
    shallow_bands = derive_boundaries(shallow, POLICY)
    steep_bands = derive_boundaries(steep, POLICY)
    assert steep_bands.high_above < shallow_bands.high_above
    assert steep_bands.derived and "derived from the fitted curve" in steep_bands.detail


def test_an_unreachable_tier_collapses_rather_than_lowering_its_promise() -> None:
    """If nothing in the backtest earned 90%, "High" admits nothing — it is not relaxed."""
    weak = _calibrator_through(lambda score: 0.4 * score)
    bands = derive_boundaries(weak, POLICY)
    assert bands.high_above >= 1.0
    assert bands.tier_for(0.999) != "High"
    assert "unreachable" in bands.detail


def test_the_contract_floor_is_never_argued_past_downward() -> None:
    """A generous curve cannot publish below the contract's abstention boundary."""
    generous = _calibrator_through(lambda score: min(1.0, 4.0 * score))
    bands = derive_boundaries(generous, POLICY)
    assert bands.abstain_below >= POLICY.abstain_below
    assert bands.tier_for(POLICY.abstain_below - 0.01) == "Insufficient"


def test_tier_bands_are_ordered_and_cover_the_unit_interval() -> None:
    """No score can fall between two bands, and no band overlaps a stronger one."""
    bands = derive_boundaries(_calibrator_through(lambda score: score), POLICY)
    assert bands.low_above <= bands.moderate_above <= bands.high_above
    tiers = {bands.tier_for(value) for value in np.linspace(0.0, 1.0, 201)}
    assert tiers <= {name for name, _ in TIER_RELIABILITY_TARGETS} | {"Insufficient"}


def test_the_contract_fallback_is_used_when_there_is_no_curve() -> None:
    """An unfitted system says so and uses the bands its contract shipped with."""
    bands = TierBoundaries.from_policy(POLICY)
    assert bands.derived is False
    assert bands.abstain_below == pytest.approx(POLICY.abstain_below)
    assert bands.moderate_above == pytest.approx(POLICY.hedge_below)


def test_window_truth_prorates_a_long_event_to_the_days_it_touches() -> None:
    """A six-month price change must not dominate the week a one-week outage owns.

    This is the defect that made the first backtest score at chance: without
    pro-rating, the largest total in the ledger wins every window it overlaps, and the
    answer key stops describing the week being graded.
    """
    ledger = pd.DataFrame(
        [
            {
                "window_start": dt.date(2026, 3, 1),
                "window_end": dt.date(2026, 8, 31),
                "isolated_delta_inr": -5.0e7,
                "true_top_region": "West",
                "true_top_category": "Skincare",
            },
            {
                "window_start": dt.date(2026, 3, 6),
                "window_end": dt.date(2026, 3, 12),
                "isolated_delta_inr": -8.0e6,
                "true_top_region": "North",
                "true_top_category": "Haircare",
            },
        ]
    )
    truth = LedgerTruth(ledger)
    week = truth.for_window(dt.date(2026, 3, 6), dt.date(2026, 3, 12))
    assert week.dominant["region"] == "North"
    assert week.contributors == 2
    assert 0.0 < week.share["region"] <= 1.0

    half_year = truth.for_window(dt.date(2026, 3, 1), dt.date(2026, 8, 31))
    assert half_year.dominant["region"] == "West"


def test_window_truth_is_undecided_when_nothing_was_planted() -> None:
    """A quiet window has no dominant cause, and says so rather than picking one."""
    ledger = pd.DataFrame(
        [
            {
                "window_start": dt.date(2026, 3, 1),
                "window_end": dt.date(2026, 3, 7),
                "isolated_delta_inr": -1.0e6,
                "true_top_region": "West",
                "true_top_category": "Skincare",
            }
        ]
    )
    quiet = LedgerTruth(ledger).for_window(dt.date(2025, 1, 1), dt.date(2025, 1, 7))
    assert quiet.is_decided is False


def test_a_measurement_with_no_data_is_never_a_pass() -> None:
    """``n = 0`` fails a target rather than silently passing it."""
    unmeasured = Measurement(name="x", value=float("nan"), target=0.1, n=0)
    assert unmeasured.measured is False
    assert unmeasured.passed is False
    assert unmeasured.verdict == "FAIL"


def test_an_informational_measurement_has_no_verdict() -> None:
    """A metric with no target is reported, not graded."""
    informational = Measurement(name="x", value=0.5, n=10)
    assert informational.passed is None
    assert informational.verdict == "—"


def _calibrator_through(shape: object) -> IsotonicCalibrator:
    """An isotonic calibrator fitted to follow a given monotone shape."""
    grid = np.linspace(0.0, 1.0, 200)
    values = np.array([min(1.0, max(0.0, shape(float(point)))) for point in grid])  # type: ignore[operator]
    return IsotonicCalibrator().fit(grid, values)
