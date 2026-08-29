"""A parametric counterfactual: trend, seasonality, movable events, exogenous controls.

This is the primary baseline, and the reason is the one the design states: **movable
events must be regressors, not fixed-lag seasonality.** Diwali moves by six weeks
between years. A decomposition that models it as "day 296 of the year" mis-forecasts
the pre-build and then mis-forecasts the lull, and both errors land in the residual
where a detector will read them as anomalies.

The second reason is subtler and matters more for the counterfactual. A local smoother
— an STL trend, a rolling median — follows a two-week outage *down*, because from its
point of view the outage is the level. Its residual over the event is then small and
the event invisible. A parametric trend cannot chase a local dip, so the gap it leaves
is the gap that actually happened. Measured on this world's flagship scenario the
difference is -7.3% against -14.0%, where the counterfactual ground truth is -11.9%.

Fitting excludes any window under test, so the baseline never learns the event it is
being asked to price.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import statsmodels.api as sm

from insight_copilot.engine.baseline import (
    MIN_FIT_DAYS,
    BaselineFit,
    BaselineModel,
    _interpolate_nonpositive,
)
from insight_copilot.engine.periods import confirmed_periods
from insight_copilot.engine.series import Series
from insight_copilot.errors import StatisticalError

EVENT_LEAD_DAYS = 12
"""Days *before* a movable event that carry their own coefficient. The world's
festivals have a ten-day pre-build; twelve gives the fit room to find the edge."""

EVENT_LAG_DAYS = 8
"""Days after. The post-festival lull runs about a week and is the trap a fixed-lag
seasonal model walks into: it forecasts the peak and misses the collapse behind it."""

ANNUAL_HARMONICS = 3
"""Three harmonics of the annual cycle. Enough to bend around a monsoon and a festive
quarter; few enough that it cannot absorb a two-week event."""

WEEKLY_HARMONICS = 3
"""Three harmonics reproduce any seven-level weekly shape and stay orthogonal to the
annual terms, which day-of-week dummies do not once holidays delete weekdays unevenly."""

DAYS_PER_YEAR = 365.25


class RegressionBaseline(BaselineModel):
    """Counterfactual level from a parametric model of everything but the event."""

    def __init__(
        self,
        *,
        events: pd.DataFrame | None = None,
        controls: pd.DataFrame | None = None,
        date_column: str = "date",
        event_column: str = "is_holiday",
    ) -> None:
        super().__init__()
        self._events = events
        self._controls = controls
        self._date_column = date_column
        self._event_column = event_column
        self._params: pd.Series | None = None
        self._columns: list[str] = []
        self._origin: np.datetime64 | None = None
        self._logged = False
        self._periods: list[int] = []

    def fit(self, series: Series) -> BaselineFit:
        """Fit on the supplied series. Exclude the window under test before calling."""
        if len(series) < MIN_FIT_DAYS:
            raise StatisticalError(
                f"{series.name}: {len(series)} days is too few for a parametric baseline",
                detail=f"need at least {MIN_FIT_DAYS}",
            )
        self._origin = series.dates[0]
        self._periods = confirmed_periods(series)
        values, interpolated = _interpolate_nonpositive(series.values)
        self._logged = bool(np.all(values > 0))
        target = np.log(values) if self._logged else values

        design = self.design_matrix(series.dates)
        self._columns = list(design.columns)
        fitted = sm.OLS(target, sm.add_constant(design, has_constant="add")).fit()
        self._params = fitted.params

        residual = series.values - self.predict(series.dates)
        self._fit = BaselineFit(
            method="regression_events" + ("_log" if self._logged else ""),
            periods=list(self._periods),
            n_train=len(series),
            residual_sd=float(np.std(residual, ddof=1)) if residual.size > 1 else 0.0,
            detail=(
                f"OLS on {'log ' if self._logged else ''}{series.name}: linear trend, "
                f"{WEEKLY_HARMONICS} weekly and {ANNUAL_HARMONICS} annual Fourier pairs, "
                f"movable-event window [-{EVENT_LEAD_DAYS}, +{EVENT_LAG_DAYS}] days, "
                f"{len(self._control_columns())} exogenous control(s); R^2 "
                f"{float(fitted.rsquared):.3f}"
                + (f"; {interpolated} non-positive day(s) interpolated" if interpolated else "")
            ),
            diagnostics={
                "r_squared": float(fitted.rsquared),
                "n_regressors": float(design.shape[1]),
                "interpolated_days": float(interpolated),
            },
        )
        return self._fit

    def predict(self, dates: np.ndarray) -> np.ndarray:
        """The counterfactual level on each date, back on the original scale."""
        if self._params is None:
            raise StatisticalError("RegressionBaseline has not been fitted")
        design = sm.add_constant(self.design_matrix(dates), has_constant="add")
        predicted = np.asarray(design[self._params.index] @ self._params, dtype=np.float64)
        return np.exp(predicted) if self._logged else predicted

    # ----------------------------------------------------------------- design --
    def design_matrix(self, dates: np.ndarray) -> pd.DataFrame:
        """Trend, Fourier terms, movable-event windows and aligned exogenous controls."""
        if self._origin is None:
            raise StatisticalError("RegressionBaseline has not been fitted")
        offsets = (dates - self._origin).astype("timedelta64[D]").astype(np.int64).astype(float)
        columns: dict[str, np.ndarray] = {"trend": offsets / DAYS_PER_YEAR}
        for harmonic in range(1, WEEKLY_HARMONICS + 1):
            angle = 2.0 * np.pi * harmonic * offsets / 7.0
            columns[f"week_sin_{harmonic}"] = np.sin(angle)
            columns[f"week_cos_{harmonic}"] = np.cos(angle)
        for harmonic in range(1, ANNUAL_HARMONICS + 1):
            angle = 2.0 * np.pi * harmonic * offsets / DAYS_PER_YEAR
            columns[f"year_sin_{harmonic}"] = np.sin(angle)
            columns[f"year_cos_{harmonic}"] = np.cos(angle)
        columns.update(self._event_columns(dates))
        columns.update(self._control_values(dates))
        return pd.DataFrame(columns)

    def _event_columns(self, dates: np.ndarray) -> dict[str, np.ndarray]:
        """One column per offset from a movable event, from lead to lag."""
        if self._events is None or self._event_column not in self._events.columns:
            return {}
        flags = self._aligned(self._events, [self._event_column], dates)[self._event_column]
        indicator = np.nan_to_num(flags.to_numpy(dtype=np.float64), nan=0.0)
        return {
            f"event_{offset:+d}": _shift(indicator, offset)
            for offset in range(-EVENT_LAG_DAYS, EVENT_LEAD_DAYS + 1)
        }

    def _control_columns(self) -> list[str]:
        """Exogenous control names, excluding the join key."""
        if self._controls is None:
            return []
        return [name for name in self._controls.columns if name != self._date_column]

    def _control_values(self, dates: np.ndarray) -> dict[str, np.ndarray]:
        """Exogenous controls aligned to the date axis, gaps filled with the mean.

        Filling with the column mean rather than dropping the row keeps the design
        matrix rectangular over a prediction window a control has not reached yet — a
        weather feed that is two days behind must not shorten the counterfactual.
        """
        names = self._control_columns()
        if not names:
            return {}
        aligned = self._aligned(self._controls, names, dates)
        return {
            name: aligned[name].fillna(aligned[name].mean()).to_numpy(dtype=np.float64)
            for name in names
        }

    def _aligned(
        self, frame: pd.DataFrame | None, names: list[str], dates: np.ndarray
    ) -> pd.DataFrame:
        """Reindex a date-keyed frame onto the series' own date axis."""
        if frame is None:
            raise StatisticalError("no frame to align")
        working = frame.copy()
        working[self._date_column] = pd.to_datetime(working[self._date_column])
        indexed = working.set_index(self._date_column)[names]
        indexed = indexed[~indexed.index.duplicated(keep="last")]
        return indexed.reindex(pd.DatetimeIndex(dates))


def _shift(values: np.ndarray, offset: int) -> np.ndarray:
    """Shift an indicator by ``offset`` days; positive is *earlier* in the series.

    ``event_+3`` therefore marks the three days *before* an event, which is the
    pre-build window, and ``event_-3`` marks the three days after it, which is the lull.
    """
    shifted = np.zeros_like(values)
    if offset > 0:
        shifted[:-offset] = values[offset:]
    elif offset < 0:
        shifted[-offset:] = values[:offset]
    else:
        shifted = values.copy()
    return shifted


def calendar_events(calendar: pd.DataFrame, *, date_column: str = "date") -> pd.DataFrame:
    """The movable-event indicator the baseline consumes, from the calendar spine."""
    if "is_holiday" not in calendar.columns:
        raise StatisticalError("calendar spine carries no is_holiday column")
    events = calendar[[date_column, "is_holiday"]].copy()
    events["is_holiday"] = events["is_holiday"].astype(bool).astype(float)
    return events


def window_mask(dates: np.ndarray, start: dt.date, end: dt.date) -> np.ndarray:
    """Boolean mask of a date window, for excluding an event from the fit."""
    return (dates >= np.datetime64(start, "D")) & (dates <= np.datetime64(end, "D"))
