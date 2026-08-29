"""P6 gate, the half that needs no warehouse.

Three behaviours are easier to demonstrate on data built to contain exactly one thing
than on a world that contains everything at once: a sustained shift with no point
anomaly, a segment ranking that is pure noise, and two regressors that are the same
regressor. Separating them keeps each assertion about one mechanism.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from insight_copilot.engine.attribute_where import Attributor
from insight_copilot.engine.detect import CusumDetector
from insight_copilot.engine.diagnostics import collinear_groups
from insight_copilot.engine.series import Series


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
