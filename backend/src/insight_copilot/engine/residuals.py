"""Turning a residual into something a p-value can be computed from.

Two problems stand between "observed minus baseline" and a defensible test statistic,
and both are properties this world was deliberately built to have:

* **Autocorrelation.** The company shock is AR(1) with phi = 0.35. A plain z-score on
  autocorrelated residuals understates the variance and over-flags — the classic way a
  monitoring system earns its reputation for crying wolf. So residuals are whitened by
  an AR(p) fit whose order is chosen by AIC, and the whitening is *verified* by
  Ljung-Box rather than assumed to have worked.
* **Heteroscedasticity.** Variance clusters around promotions, festivals and weekends.
  A single pooled sigma makes a quiet Tuesday look extreme and a noisy Saturday look
  normal. So the scale is an EWMA of squared innovations, floored by a day-of-week
  stratified MAD so a run of quiet days cannot drive the scale to zero and manufacture
  an anomaly out of the next ordinary wobble.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.tsa.ar_model import AutoReg

MAX_AR_ORDER = 7
"""One week of lags. Beyond that an AR term is fitting the seasonality the baseline
has already removed, and the order-selection would reward it for doing so."""

LJUNG_BOX_LAGS = 14
"""Two weeks of lags for the whiteness check — long enough to catch a weekly residue."""

LJUNG_BOX_ALPHA = 0.05
"""Below this the whitening is reported as having failed. It is reported, not hidden:
a residual that is still autocorrelated makes every p-value below it optimistic, and
the confidence layer needs to know."""

EWMA_LAMBDA = 0.94
"""RiskMetrics' decay. About a month of effective memory: fast enough to track a
regime change, slow enough not to chase a single spike."""

MAD_TO_SIGMA = 1.4826
"""Consistency constant making the median absolute deviation an estimator of sigma
under normality. Used for the floor, not for the scale itself."""

VARIANCE_FLOOR_FRACTION = 0.5
"""The EWMA scale may not fall below half the day-of-week MAD. Without a floor a quiet
fortnight shrinks the scale until an ordinary wobble reads as a six-sigma event."""

MIN_WHITENING_OBSERVATIONS = 30
"""Below this an AR fit is estimating more than the data supports; the residuals are
passed through unwhitened and that fact is recorded."""


@dataclass(frozen=True)
class Whitened:
    """Whitened innovations plus the evidence that the whitening worked."""

    innovations: np.ndarray
    order: int
    coefficients: np.ndarray
    ljung_box_p: float
    aic: float

    @property
    def is_white(self) -> bool:
        """Did Ljung-Box fail to reject whiteness? If not, every p-value is optimistic."""
        return self.ljung_box_p > LJUNG_BOX_ALPHA

    @property
    def detail(self) -> str:
        """A sentence for the evidence drawer."""
        return (
            f"AR({self.order}) whitening selected by AIC ({self.aic:.1f}); "
            f"Ljung-Box p = {self.ljung_box_p:.3f} "
            f"({'residuals are white' if self.is_white else 'autocorrelation remains'})"
        )


def whiten(residuals: np.ndarray) -> Whitened:
    """Fit AR(p) by AIC, return the innovations and the Ljung-Box verdict."""
    values = np.asarray(residuals, dtype=np.float64)
    observed = np.isfinite(values)
    finite = values[observed]
    if finite.size < MIN_WHITENING_OBSERVATIONS:
        return Whitened(
            innovations=values,
            order=0,
            coefficients=np.array([]),
            ljung_box_p=float("nan"),
            aic=float("nan"),
        )

    best_order, best_aic, best_model = 0, np.inf, None
    for order in range(MAX_AR_ORDER + 1):
        try:
            model = AutoReg(finite, lags=order).fit()
        except (ValueError, np.linalg.LinAlgError):
            continue
        if float(model.aic) < best_aic:
            best_order, best_aic, best_model = order, float(model.aic), model

    if best_model is None:
        return Whitened(values, 0, np.array([]), float("nan"), float("nan"))

    fitted = np.asarray(best_model.resid, dtype=np.float64)
    if best_order > 0:
        # ``resid`` drops the first ``order`` observations; pad so the innovation array
        # stays aligned to the observations it was fitted on. Padding with NaN rather
        # than zero keeps the unusable head out of every downstream statistic instead of
        # biasing it towards zero.
        fitted = np.concatenate([np.full(best_order, np.nan), fitted])
    # Scatter back onto the original axis. Days the caller marked unobserved stay NaN,
    # so an innovation array is always the same length as the dates it describes and
    # every downstream mask lines up without a silent off-by-one.
    innovations = np.full(values.shape, np.nan)
    innovations[observed] = fitted

    usable = innovations[np.isfinite(innovations)]
    lags = min(LJUNG_BOX_LAGS, max(1, usable.size // 5))
    ljung = acorr_ljungbox(usable, lags=[lags], return_df=True)
    return Whitened(
        innovations=innovations,
        order=best_order,
        coefficients=np.asarray(best_model.params[1:], dtype=np.float64),
        ljung_box_p=float(ljung["lb_pvalue"].iloc[0]),
        aic=best_aic,
    )


def ewma_scale(innovations: np.ndarray, day_of_week: np.ndarray) -> np.ndarray:
    """A per-observation scale: EWMA of squared innovations, floored by day-of-week MAD.

    The scale at ``t`` uses information up to ``t-1`` only. A scale that included the
    day it is standardising would shrink towards the very observation under test and
    quietly deflate every extreme value it was built to find.
    """
    values = np.asarray(innovations, dtype=np.float64)
    floor = _dow_floor(values, day_of_week)
    scale = np.empty_like(values)
    variance = float(np.nanvar(values)) if np.isfinite(values).any() else 1.0
    if not np.isfinite(variance) or variance <= 0.0:
        variance = 1.0
    for index in range(values.size):
        scale[index] = max(np.sqrt(variance), floor[index])
        observed = values[index]
        if np.isfinite(observed):
            variance = EWMA_LAMBDA * variance + (1.0 - EWMA_LAMBDA) * observed * observed
    return scale


def standardise(innovations: np.ndarray, day_of_week: np.ndarray) -> np.ndarray:
    """Innovations divided by their own one-step-ahead scale."""
    standardised: np.ndarray = innovations / ewma_scale(innovations, day_of_week)
    return standardised


def _dow_floor(values: np.ndarray, day_of_week: np.ndarray) -> np.ndarray:
    """Per-observation variance floor from the MAD of its own weekday."""
    floor = np.zeros_like(values)
    for weekday in range(7):
        selected = (day_of_week == weekday) & np.isfinite(values)
        if selected.sum() < 3:
            continue
        subset = values[selected]
        mad = float(np.median(np.abs(subset - np.median(subset))))
        floor[day_of_week == weekday] = VARIANCE_FLOOR_FRACTION * MAD_TO_SIGMA * mad
    typed: np.ndarray = floor
    return typed
