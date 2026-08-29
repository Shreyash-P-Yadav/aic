"""Preparing the dimensional cube for Adtributor: actual against forecast per segment.

Adtributor needs a forecast for *every* segment, not just the total. Fitting a full
seasonal baseline per segment is possible and wrong: a segment with two hundred rows a
week has no reliable seasonality of its own, and a hundred separately-fitted baselines
disagree with the national one they are supposed to decompose.

So the segment forecast is the segment's own level over a comparable baseline window,
carried into the window under test by the **national** factor between the two. That
keeps the parts summing to something close to the national forecast, uses the national
series (which does have enough history to model) for the seasonal and trend movement,
and asks each segment only for its own level — the one thing a small segment can
estimate well.

The comparable window is whole weeks ending immediately before the window under test,
so day-of-week composition matches and no seasonal correction is needed for it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd

from insight_copilot.errors import StatisticalError

DEFAULT_BASELINE_WEEKS = 4
"""Four whole weeks before the window. Long enough to average out one bad Tuesday,
short enough that a segment's level has not drifted."""

DAYS_PER_WEEK = 7


@dataclass(frozen=True)
class CubeWindow:
    """The two windows a segment comparison needs."""

    test_start: dt.date
    test_end: dt.date
    baseline_start: dt.date
    baseline_end: dt.date

    @classmethod
    def ending_before(
        cls, test_start: dt.date, test_end: dt.date, *, weeks: int = DEFAULT_BASELINE_WEEKS
    ) -> CubeWindow:
        """Whole comparable weeks immediately before the window under test."""
        baseline_end = test_start - dt.timedelta(days=1)
        return cls(
            test_start=test_start,
            test_end=test_end,
            baseline_start=baseline_end - dt.timedelta(days=weeks * DAYS_PER_WEEK - 1),
            baseline_end=baseline_end,
        )

    @property
    def test_days(self) -> int:
        """Length of the window under test, in days."""
        return (self.test_end - self.test_start).days + 1

    @property
    def baseline_days(self) -> int:
        """Length of the comparable window, in days."""
        return (self.baseline_end - self.baseline_start).days + 1


def segment_actual_forecast(
    cube: pd.DataFrame,
    window: CubeWindow,
    *,
    dimensions: list[str],
    measure: str,
    national_factor: float,
    date_column: str = "date",
) -> pd.DataFrame:
    """One row per segment with its actual and its forecast over the test window.

    ``national_factor`` is the national counterfactual for the test window divided by
    the national actual over the comparable window — the seasonal and trend movement
    the baseline model has already estimated on the series that can support one.
    """
    stamps = pd.to_datetime(cube[date_column]).dt.date
    test = cube.loc[(stamps >= window.test_start) & (stamps <= window.test_end)]
    base = cube.loc[(stamps >= window.baseline_start) & (stamps <= window.baseline_end)]
    if test.empty or base.empty:
        raise StatisticalError(
            "cube window is empty",
            detail=f"test rows {len(test)}, baseline rows {len(base)}",
        )

    actual = test.groupby(dimensions, observed=True)[measure].sum().rename("actual")
    counts = test.groupby(dimensions, observed=True).size().rename("observations")
    baseline = base.groupby(dimensions, observed=True)[measure].sum().rename("_base")
    joined = pd.concat([actual, baseline, counts], axis=1).fillna(0.0)
    # Scale the comparable window to the test window's length before applying the
    # national factor, so a five-day window is not compared against four whole weeks.
    per_day = joined["_base"] / window.baseline_days
    joined["forecast"] = per_day * window.test_days * national_factor
    return joined.drop(columns=["_base"]).reset_index()


def national_factor(
    counterfactual_total: float, baseline_actual_total: float, window: CubeWindow
) -> float:
    """The per-day national movement between the comparable window and the test one."""
    if baseline_actual_total <= 0.0:
        raise StatisticalError("comparable window has no national volume to scale from")
    per_day_base = baseline_actual_total / window.baseline_days
    per_day_test = counterfactual_total / window.test_days
    return float(per_day_test / per_day_base)
