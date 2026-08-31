"""Baselines: what the KPI would have been. Every anomaly is a gap against one of these.

Two implementations, and the choice between them is made by the data rather than by a
flag:

* :class:`MSTLBaseline` — multiple seasonal-trend decomposition on ``log(y)``, using
  only the periods :mod:`insight_copilot.engine.periods` confirmed. Logs because the
  world is multiplicative: a weekend dip is minus twenty percent of level, not a fixed
  number of units, and a baseline fitted on levels would over-predict the weekend of a
  big week and under-predict the weekend of a small one.
* :class:`PooledLaunchBaseline` — empirical-Bayes pooling over comparable launches, for
  a series too short to have a history of its own. A SKU eighteen days old has no
  seasonality to decompose; what it has is twelve prior launches in the same category
  whose shape it can borrow, shrunk towards the pool in proportion to how little of its
  own evidence there is.

Both answer the same question — ``predict(dates)`` — so the detector never knows which
it was handed, and the sparse-history path is a substitution rather than a special case.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np
from statsmodels.tsa.seasonal import MSTL

from insight_copilot.engine.periods import confirmed_periods
from insight_copilot.engine.series import MIN_POSITIVE, Series
from insight_copilot.errors import StatisticalError
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

TREND_WINDOW_DAYS = 56
"""How much of the fitted trend the extrapolation reads. Eight weeks is long enough to
average out a promotion and short enough that a regime change six months ago does not
set today's slope."""

MIN_FIT_DAYS = 28
"""Below four weeks there is not enough to decompose, and the contract's
``min_history_days_full_stats`` says the same thing. Below this the pooled baseline
takes over."""

POOL_PRIOR_STRENGTH = 14.0
"""Empirical-Bayes shrinkage weight, in days. A launch with fourteen days of its own
history is weighted equally against the pool; with three days the pool dominates. It
is the pooled curve's own half-life, so the shrinkage fades as the series earns its
independence."""


@dataclass
class BaselineFit:
    """What a fitted baseline knows, and what the evidence drawer shows."""

    method: str
    periods: list[int]
    n_train: int
    residual_sd: float
    detail: str = ""
    diagnostics: dict[str, float] = field(default_factory=dict)


class BaselineModel(ABC):
    """Predicts the counterfactual level of a series on given dates."""

    def __init__(self) -> None:
        self._fit: BaselineFit | None = None

    @property
    def fit_summary(self) -> BaselineFit:
        """The fit's provenance. Raises if the model has not been fitted."""
        if self._fit is None:
            raise StatisticalError(f"{type(self).__name__} has not been fitted")
        return self._fit

    @abstractmethod
    def fit(self, series: Series) -> BaselineFit:
        """Learn the level, trend and seasonality from a training series."""

    @abstractmethod
    def predict(self, dates: np.ndarray) -> np.ndarray:
        """The counterfactual level on each date. Same units as the training series."""

    def counterfactual(self, series: Series) -> np.ndarray:
        """Predicted level across a whole series' date axis."""
        return self.predict(series.dates)

    def residuals(self, series: Series) -> np.ndarray:
        """Observed minus predicted, in logs where the model works in logs."""
        residual: np.ndarray = series.values - self.predict(series.dates)
        return residual


class MSTLBaseline(BaselineModel):
    """Multiple seasonal-trend decomposition on ``log(y)``, with a linear trend carry."""

    def __init__(self, *, periods: list[int] | None = None) -> None:
        super().__init__()
        self._requested = periods
        self._periods: list[int] = []
        self._seasonal: dict[int, np.ndarray] = {}
        self._origin: np.datetime64 | None = None
        self._trend_offsets: np.ndarray = np.array([])
        self._trend_values: np.ndarray = np.array([])
        self._slope = 0.0
        self._logged = False
        self._interpolated_days = 0

    def fit(self, series: Series) -> BaselineFit:
        """Decompose, then keep the pieces needed to project the decomposition forward."""
        if len(series) < MIN_FIT_DAYS:
            raise StatisticalError(
                f"{series.name}: {len(series)} days is too few to decompose",
                detail=f"need at least {MIN_FIT_DAYS}",
            )
        usable, self._interpolated_days = _interpolate_nonpositive(series.values)
        self._logged = bool(np.all(usable > MIN_POSITIVE))
        target = np.log(usable) if self._logged else usable
        self._periods = (
            self._requested if self._requested is not None else confirmed_periods(series)
        )
        self._periods = [period for period in self._periods if 2 * period < len(series)]
        self._origin = series.dates[0]

        if self._periods:
            result = MSTL(target, periods=self._periods).fit()
            seasonal = np.atleast_2d(np.asarray(result.seasonal).T)
            trend = np.asarray(result.trend)
            for index, period in enumerate(self._periods):
                self._seasonal[period] = _phase_profile(
                    seasonal[index], series.dates, self._origin, period
                )
        else:
            # No confirmed period: the baseline is trend plus level, which is the
            # honest answer for a series with no seasonality rather than a fabricated
            # weekly shape.
            trend = _moving_average(target, window=7)

        self._store_trend(trend, series.dates)
        fitted = self.predict(series.dates)
        residual = series.values - fitted
        self._fit = BaselineFit(
            method="mstl_log" if self._logged else "mstl_level",
            periods=list(self._periods),
            n_train=len(series),
            residual_sd=float(np.std(residual, ddof=1)) if residual.size > 1 else 0.0,
            detail=(
                f"MSTL on {'log ' if self._logged else ''}{series.name} with periods "
                f"{self._periods or 'none confirmed'}; trend carried forward at "
                f"{self._slope:.3e} per day from the last {TREND_WINDOW_DAYS} days"
                + (
                    f"; {self._interpolated_days} non-positive day(s) interpolated for the fit"
                    if self._interpolated_days
                    else ""
                )
            ),
            diagnostics={
                "trend_slope_per_day": self._slope,
                "interpolated_days": float(self._interpolated_days),
            },
        )
        return self._fit

    def _store_trend(self, trend: np.ndarray, dates: np.ndarray) -> None:
        """Keep the fitted trend and the slope that carries it past the fit range."""
        offsets = (dates - self._origin).astype("timedelta64[D]").astype(np.int64)
        finite = np.isfinite(trend)
        self._trend_offsets = offsets[finite].astype(np.float64)
        self._trend_values = trend[finite]
        self._slope = _tail_slope(self._trend_offsets, self._trend_values)

    def predict(self, dates: np.ndarray) -> np.ndarray:
        """Trend plus every confirmed seasonal component, back on the original scale.

        Inside the fitted range the trend is *interpolated*, not replaced by a straight
        line. That matters twice over: in sample it keeps the residual small enough to
        be a residual rather than a mis-specification, and across a held-out event
        window it interpolates through the hole — which is exactly the counterfactual
        question, "what would the level have been had nothing happened?".
        """
        if self._origin is None or self._trend_values.size == 0:
            raise StatisticalError("MSTLBaseline has not been fitted")
        offsets = (dates - self._origin).astype("timedelta64[D]").astype(np.int64).astype(float)
        first, last = self._trend_offsets[0], self._trend_offsets[-1]
        predicted = np.interp(offsets, self._trend_offsets, self._trend_values)
        predicted = np.where(
            offsets > last, self._trend_values[-1] + self._slope * (offsets - last), predicted
        )
        predicted = np.where(
            offsets < first, self._trend_values[0] + self._slope * (offsets - first), predicted
        )
        for period, profile in self._seasonal.items():
            predicted = predicted + profile[(offsets.astype(np.int64) % period)]
        result: np.ndarray = np.exp(predicted) if self._logged else predicted
        return result


class PooledLaunchBaseline(BaselineModel):
    """Empirical-Bayes pooling over comparable launches, for a sparse series.

    The pooled curve is the mean *shape* of the comparables — each normalised by its own
    day-one level so that a big launch and a small one contribute the same curve — and
    the sparse series contributes its own observed shape, weighted by how many days it
    has. Nothing here invents a level: the level always comes from the series itself.
    """

    def __init__(self, comparables: list[Series], *, horizon_days: int = 120) -> None:
        super().__init__()
        self._horizon = horizon_days
        self._pool = _pooled_shape(comparables, horizon_days)
        self._n_comparables = len(comparables)
        self._level = 0.0
        self._shape = self._pool.copy()
        self._origin: np.datetime64 | None = None

    @property
    def pooled_shape(self) -> np.ndarray:
        """The borrowed curve, indexed by days since launch. Shown in the drawer."""
        return self._pool

    def fit(self, series: Series) -> BaselineFit:
        """Shrink the series' own shape towards the pool in proportion to its length."""
        if len(series) == 0:
            raise StatisticalError("PooledLaunchBaseline needs at least one observation")
        if self._n_comparables == 0:
            raise StatisticalError(
                "PooledLaunchBaseline needs comparable launches to pool over",
                detail="with no comparables the pooled curve would be an assertion",
            )
        self._origin = series.dates[0]
        self._level = float(np.mean(series.values[: min(7, len(series))]))
        own = _normalised_shape(series, self._horizon)
        weight = len(series) / (len(series) + POOL_PRIOR_STRENGTH)
        observed = ~np.isnan(own)
        self._shape = self._pool.copy()
        self._shape[observed] = weight * own[observed] + (1.0 - weight) * self._pool[observed]

        fitted = self.predict(series.dates)
        residual = series.values - fitted
        self._fit = BaselineFit(
            method="pooled_launch_eb",
            periods=[],
            n_train=len(series),
            residual_sd=float(np.std(residual, ddof=1)) if residual.size > 1 else 0.0,
            detail=(
                f"empirical-Bayes pooling over {self._n_comparables} comparable launches; "
                f"own shape weighted {weight:.2f} against the pool at n={len(series)}"
            ),
            diagnostics={"pool_weight": weight, "comparables": float(self._n_comparables)},
        )
        return self._fit

    def predict(self, dates: np.ndarray) -> np.ndarray:
        """Level times the shrunk launch curve at each day since launch."""
        if self._origin is None:
            raise StatisticalError("PooledLaunchBaseline has not been fitted")
        offsets = (dates - self._origin).astype("timedelta64[D]").astype(np.int64)
        clipped = np.clip(offsets, 0, self._horizon - 1)
        predicted: np.ndarray = self._level * self._shape[clipped]
        return predicted


# ------------------------------------------------------------------- helpers --
def _phase_profile(
    component: np.ndarray, dates: np.ndarray, origin: np.datetime64, period: int
) -> np.ndarray:
    """Average the seasonal component by phase, so it can be projected forward."""
    offsets = (dates - origin).astype("timedelta64[D]").astype(np.int64) % period
    profile = np.zeros(period)
    for phase in range(period):
        selected = component[offsets == phase]
        profile[phase] = float(selected.mean()) if selected.size else 0.0
    centred: np.ndarray = profile - profile.mean()
    return centred


def _tail_slope(offsets: np.ndarray, values: np.ndarray) -> float:
    """Slope per day over the last ``TREND_WINDOW_DAYS``, used only to extrapolate.

    Eight weeks is long enough to average out a promotion and short enough that a
    regime change six months ago does not set today's slope.
    """
    if offsets.size < 2:
        return 0.0
    tail = offsets >= max(offsets.max() - TREND_WINDOW_DAYS, offsets.min())
    if tail.sum() < 2:
        return 0.0
    slope, _ = np.polyfit(offsets[tail], values[tail], 1)
    return float(slope)


def _interpolate_nonpositive(values: np.ndarray) -> tuple[np.ndarray, int]:
    """Replace non-positive days by interpolation, and say how many there were.

    A national KPI at exactly zero for one day is a feed that did not arrive, not a day
    on which the company sold nothing. Treating it as an observation would drag the
    trend down and, worse, block the log transform this multiplicative world needs.
    Treating it as unknown and interpolating is the honest reading, and the count is
    reported in the fit so nobody has to take it on trust.
    """
    working = np.asarray(values, dtype=np.float64).copy()
    bad = ~(working > MIN_POSITIVE) | ~np.isfinite(working)
    if not bad.any() or bad.all():
        return working, 0
    index = np.arange(working.size, dtype=np.float64)
    working[bad] = np.interp(index[bad], index[~bad], working[~bad])
    return working, int(bad.sum())


def _moving_average(values: np.ndarray, window: int) -> np.ndarray:
    """Centred moving average, edge-padded. The trend when there is no seasonality."""
    if values.size < window:
        return np.full_like(values, float(values.mean()))
    kernel = np.ones(window) / window
    padded = np.pad(values, (window // 2, window // 2), mode="edge")
    return np.convolve(padded, kernel, mode="valid")[: values.size]


def _normalised_shape(series: Series, horizon: int) -> np.ndarray:
    """A launch curve normalised by its own first-week level. NaN where unobserved."""
    shape = np.full(horizon, np.nan)
    base = float(np.mean(series.values[: min(7, len(series))]))
    if base <= 0.0:
        return shape
    take = min(len(series), horizon)
    shape[:take] = series.values[:take] / base
    return shape


def _pooled_shape(comparables: list[Series], horizon: int) -> np.ndarray:
    """Mean normalised launch curve across comparables, forward-filled past coverage."""
    if not comparables:
        return np.ones(horizon)
    stacked = np.vstack([_normalised_shape(item, horizon) for item in comparables])
    with np.errstate(invalid="ignore"):
        pooled = np.nanmean(stacked, axis=0)
    pooled = np.where(np.isfinite(pooled), pooled, np.nan)
    last = 1.0
    for index in range(horizon):
        if np.isnan(pooled[index]):
            pooled[index] = last
        else:
            last = float(pooled[index])
    return pooled
