"""Detection. Four detectors, one interface, and a false-discovery correction over all
of them.

* :class:`ConformalDetector` — the primary. ``p = (1 + #{calib >= today}) / (n + 1)``,
  which is exact and distribution-free under exchangeability. That property is the
  reason it is here rather than a z-score: it needs no normality assumption, and this
  world's residuals are deliberately not normal.
* :class:`CusumDetector` — tabular CUSUM for a *drift* too small to trip a point test,
  with a persistence requirement so a single excursion is not a shift.
* :class:`MahalanobisDetector` — robust (``MinCovDet``) distance on the joint residual
  vector across KPIs, which catches a move that is unremarkable in each series alone.
* Benjamini-Hochberg over the whole KPI x segment scan, because a hundred segments
  tested at alpha = 0.01 produce one false alarm a day by construction.

Calibration windows exclude known anomalies and regime breaks. That exclusion is not
tuning: including a planted outage in the calibration set makes the outage look normal,
which is exactly the failure the exchangeability assumption warns about.
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np
from sklearn.covariance import MinCovDet

from insight_copilot.engine.residuals import Whitened, standardise, whiten
from insight_copilot.engine.series import MIN_POSITIVE, Series
from insight_copilot.errors import StatisticalError

MIN_CALIBRATION = 60
"""Below sixty clean days the smallest achievable conformal p-value is 1/61, which is
already above a 0.01 threshold — the test cannot fire, and saying so is better than
returning a number that looks like a p-value and is not."""

CUSUM_K = 0.5
"""Reference value in sigma units: the CUSUM is tuned to detect a half-sigma shift,
the standard choice when the shift of interest is small relative to the noise."""

CUSUM_H = 4.5
"""Decision interval in sigma units. With k = 0.5 this gives an in-control average run
length of a few hundred observations — roughly one false alarm a year on daily data."""

CUSUM_PERSISTENCE_DAYS = 3
"""A drift must stay above the interval for this many days. One day above it is a
point anomaly, which the conformal test already owns."""

LOG_SCALE_COVERAGE = 0.9
"""Above this share of usable days a measure is treated as multiplicative and modelled
in logs, with the unusable days marked missing rather than clipped."""

DEFAULT_FDR_Q = 0.05
"""Benjamini-Hochberg level. Overridden per KPI by the contract's ``materiality.fdr_q``."""


@dataclass(frozen=True)
class Detection:
    """One flagged observation, with everything needed to judge it."""

    kpi_id: str
    segment: str
    day: dt.date
    observed: float
    expected: float
    method: str
    p_value: float
    statistic: float
    detail: str
    passed_fdr: bool = False

    @property
    def delta(self) -> float:
        """Observed minus counterfactual, in the KPI's own units."""
        return self.observed - self.expected

    @property
    def delta_pct(self) -> float:
        """The move as a percentage of the counterfactual."""
        return 100.0 * self.delta / self.expected if self.expected else 0.0


@dataclass
class DetectionScan:
    """Every detection from one scan, plus the diagnostics behind them."""

    detections: list[Detection] = field(default_factory=list)
    whitening: dict[str, Whitened] = field(default_factory=dict)
    calibration_days: dict[str, int] = field(default_factory=dict)

    def significant(self) -> list[Detection]:
        """Detections surviving the false-discovery correction, worst p first."""
        return sorted(
            (item for item in self.detections if item.passed_fdr), key=lambda item: item.p_value
        )


class Detector(ABC):
    """Scores a series against a counterfactual and returns what it flags."""

    @abstractmethod
    def scan(
        self,
        *,
        kpi_id: str,
        segment: str,
        series: Series,
        expected: np.ndarray,
        calibration_mask: np.ndarray,
        test_mask: np.ndarray,
    ) -> list[Detection]:
        """Flag observations inside ``test_mask``, calibrating on ``calibration_mask``."""


def conformal_p_values(calibration: np.ndarray, test: np.ndarray) -> np.ndarray:
    """``p = (1 + #{calib >= t}) / (n + 1)`` for each test statistic.

    Exact and distribution-free: under exchangeability of calibration and test scores
    these p-values are uniform on ``{1/(n+1), ..., 1}``. That uniformity is what the P6
    gate's KS test checks, and it is the credibility checkpoint of the whole build —
    every confidence number downstream is only as honest as this one.
    """
    clean = calibration[np.isfinite(calibration)]
    if clean.size == 0:
        raise StatisticalError("conformal p-values need a non-empty calibration set")
    # ``searchsorted`` on the sorted calibration scores counts, for each test score,
    # how many calibration scores are >= it — the same count as a nested loop, in n log n.
    ordered = np.sort(clean)
    at_or_above = clean.size - np.searchsorted(ordered, test, side="left")
    p_values: np.ndarray = (1.0 + at_or_above) / (clean.size + 1.0)
    return p_values


def benjamini_hochberg(p_values: np.ndarray, q: float) -> np.ndarray:
    """Boolean mask of the hypotheses BH rejects at false-discovery rate ``q``."""
    values = np.asarray(p_values, dtype=np.float64)
    n = values.size
    if n == 0:
        return np.zeros(0, dtype=bool)
    order = np.argsort(values)
    thresholds = q * (np.arange(1, n + 1) / n)
    below = values[order] <= thresholds
    rejected = np.zeros(n, dtype=bool)
    if below.any():
        cutoff = int(np.max(np.flatnonzero(below)))
        rejected[order[: cutoff + 1]] = True
    return rejected


class ConformalDetector(Detector):
    """Point anomalies by conformal p-value on whitened, standardised residuals."""

    def __init__(self, *, alpha: float = 0.01) -> None:
        self._alpha = alpha
        self.last_whitening: Whitened | None = None
        self.last_calibration_size = 0

    def scan(
        self,
        *,
        kpi_id: str,
        segment: str,
        series: Series,
        expected: np.ndarray,
        calibration_mask: np.ndarray,
        test_mask: np.ndarray,
    ) -> list[Detection]:
        """Score every test day against the calibration distribution."""
        scores, whitened = self.scores(series, expected)
        self.last_whitening = whitened
        calibration = scores[calibration_mask & np.isfinite(scores)]
        self.last_calibration_size = int(calibration.size)
        if calibration.size < MIN_CALIBRATION:
            return []
        indices = np.flatnonzero(test_mask & np.isfinite(scores))
        if indices.size == 0:
            return []
        p_values = conformal_p_values(calibration, scores[indices])
        return [
            Detection(
                kpi_id=kpi_id,
                segment=segment,
                day=series.dates[index].astype(object),
                observed=float(series.values[index]),
                expected=float(expected[index]),
                method="conformal_ar_innovation",
                p_value=float(p_value),
                statistic=float(scores[index]),
                detail=(
                    f"|standardised innovation| {scores[index]:.2f} against "
                    f"{calibration.size} calibration days; {whitened.detail}"
                ),
            )
            for index, p_value in zip(indices, p_values, strict=True)
            if p_value <= self._alpha
        ]

    @staticmethod
    def scores(series: Series, expected: np.ndarray) -> tuple[np.ndarray, Whitened]:
        """Absolute standardised innovations — the conformal non-conformity score."""
        residual = _residual(series, expected)
        whitened = whiten(residual)
        return np.abs(standardise(whitened.innovations, series.day_of_week)), whitened


class CusumDetector(Detector):
    """Tabular CUSUM for a persistent small drift the point test cannot see."""

    def __init__(self, *, k: float = CUSUM_K, h: float = CUSUM_H) -> None:
        self._k = k
        self._h = h

    def scan(
        self,
        *,
        kpi_id: str,
        segment: str,
        series: Series,
        expected: np.ndarray,
        calibration_mask: np.ndarray,
        test_mask: np.ndarray,
    ) -> list[Detection]:
        """Flag the first day of any run that stays outside the decision interval."""
        # CUSUM runs on the *standardised residual*, not on the AR innovations. The
        # whitening that makes a point test honest is exactly wrong here: it removes
        # the persistence, and persistence is the whole signal a CUSUM accumulates. A
        # sustained fifteen-percent shift has small innovations after its first day.
        residual = _residual(series, expected)
        scores = standardise(residual, series.day_of_week)
        scale = np.nanstd(scores[calibration_mask]) if calibration_mask.any() else 1.0
        if not np.isfinite(scale) or scale <= 0:
            scale = 1.0
        normalised = np.nan_to_num(scores / scale, nan=0.0)

        high, low = 0.0, 0.0
        run = 0
        detections: list[Detection] = []
        for index in range(normalised.size):
            high = max(0.0, high + normalised[index] - self._k)
            low = max(0.0, low - normalised[index] - self._k)
            excursion = max(high, low)
            if excursion <= self._h:
                run = 0
                continue
            run += 1
            if run != CUSUM_PERSISTENCE_DAYS or not test_mask[index]:
                continue
            detections.append(
                Detection(
                    kpi_id=kpi_id,
                    segment=segment,
                    day=series.dates[index].astype(object),
                    observed=float(series.values[index]),
                    expected=float(expected[index]),
                    method="tabular_cusum",
                    p_value=float(np.exp(-excursion)),
                    statistic=float(excursion),
                    detail=(
                        f"CUSUM {excursion:.2f} above h={self._h} for "
                        f"{CUSUM_PERSISTENCE_DAYS} consecutive days (k={self._k})"
                    ),
                )
            )
            high, low, run = 0.0, 0.0, 0
        return detections


class MahalanobisDetector(Detector):
    """Robust joint-residual distance across KPIs.

    A day on which revenue is mildly low, fill rate mildly low and returns mildly high
    is unremarkable in each series and unmistakable in all three. ``MinCovDet`` rather
    than the sample covariance because the covariance must be estimated from data that
    contains the very outliers being looked for.
    """

    def __init__(self, *, support_fraction: float = 0.75, alpha: float = 0.01) -> None:
        self._support = support_fraction
        self._alpha = alpha

    def scan(
        self,
        *,
        kpi_id: str,
        segment: str,
        series: Series,
        expected: np.ndarray,
        calibration_mask: np.ndarray,
        test_mask: np.ndarray,
    ) -> list[Detection]:
        """Single-series form is a no-op; use :meth:`scan_joint`."""
        del kpi_id, segment, series, expected, calibration_mask, test_mask
        return []

    def scan_joint(
        self,
        *,
        dates: np.ndarray,
        residuals: np.ndarray,
        labels: list[str],
        calibration_mask: np.ndarray,
        test_mask: np.ndarray,
    ) -> list[Detection]:
        """Flag days whose joint residual vector is far from the robust centre."""
        usable = np.all(np.isfinite(residuals), axis=1)
        train = calibration_mask & usable
        if train.sum() < 5 * residuals.shape[1]:
            return []
        estimator = MinCovDet(support_fraction=self._support, random_state=0).fit(residuals[train])
        distances = np.full(residuals.shape[0], np.nan)
        distances[usable] = estimator.mahalanobis(residuals[usable])
        calibration = distances[train]
        indices = np.flatnonzero(test_mask & usable)
        if indices.size == 0 or calibration.size < MIN_CALIBRATION:
            return []
        p_values = conformal_p_values(calibration, distances[indices])
        return [
            Detection(
                kpi_id="joint",
                segment="+".join(labels),
                day=dates[index].astype(object),
                observed=float(distances[index]),
                expected=float(np.median(calibration)),
                method="robust_mahalanobis",
                p_value=float(p_value),
                statistic=float(distances[index]),
                detail=(
                    f"robust Mahalanobis distance {distances[index]:.1f} across "
                    f"{len(labels)} KPIs against a calibration median of "
                    f"{float(np.median(calibration)):.1f}"
                ),
            )
            for index, p_value in zip(indices, p_values, strict=True)
            if p_value <= self._alpha
        ]


def apply_fdr(detections: list[Detection], q: float = DEFAULT_FDR_Q) -> list[Detection]:
    """Mark which detections survive Benjamini-Hochberg across the whole scan."""
    if not detections:
        return []
    rejected = benjamini_hochberg(
        np.array([item.p_value for item in detections], dtype=np.float64), q
    )
    return [
        Detection(**{**vars(item), "passed_fdr": bool(flag)})
        for item, flag in zip(detections, rejected, strict=True)
    ]


def _residual(series: Series, expected: np.ndarray) -> np.ndarray:
    """Residuals in logs where both sides are positive, on levels otherwise.

    Logs because the world is multiplicative: a residual of minus one lakh means
    something different on a two-crore day and a twenty-lakh day, and only the log
    residual has the same meaning on both.

    A day whose observed value is zero is **not** a residual of ``log(0)``. It is a day
    the feed did not deliver, and forcing it through the log gives a residual of about
    minus thirty-eight — which then sits in the EWMA variance for months and inflates
    the scale by more than an order of magnitude, so that every genuine anomaly after
    it standardises to nothing. That failure is silent, it looks exactly like a quiet
    period, and it is why unobserved days are marked NaN here rather than clipped.
    """
    values = np.asarray(series.values, dtype=np.float64)
    predicted = np.asarray(expected, dtype=np.float64)
    usable = (
        np.isfinite(values)
        & np.isfinite(predicted)
        & (values > MIN_POSITIVE)
        & (predicted > MIN_POSITIVE)
    )
    if usable.mean() >= LOG_SCALE_COVERAGE:
        residual = np.full(values.shape, np.nan)
        residual[usable] = np.log(values[usable]) - np.log(predicted[usable])
        return residual
    # A measure that is legitimately non-positive much of the time — a margin, a net
    # change — is modelled on levels, where zero is an ordinary value.
    return values - predicted
