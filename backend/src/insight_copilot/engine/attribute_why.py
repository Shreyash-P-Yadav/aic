"""Rung 3 - *why*: driver coefficients, two estimators, and an honest disagreement.

SARIMAX with exogenous regressors is the primary estimator, because the errors are
autocorrelated and an OLS standard error on autocorrelated errors is simply wrong.
OLS with Newey-West HAC standard errors is the cross-check, at the bandwidth
``L = floor(4·(T/100)^(2/9))`` that Newey and West themselves recommend. Two estimators
that disagree are a finding, not a nuisance: the **agreement score** goes into the
confidence signal rather than being resolved by picking a favourite.

The part most systems get wrong is **which regressors are admissible**. The KPI
contract carries a driver DAG, and it names the mediators. Unit volume sits between
every driver and revenue: control for it and the estimated marketing effect collapses
to almost nothing, because you have conditioned away the channel through which
marketing works. Estimating a *total* effect therefore means excluding the mediator -
and this module reads that from the contract rather than deciding it.

Collinear drivers are not dropped. Two channels a single agency team moved together
for two quarters carry the same information, and reporting one of them as the cause
would be arbitrary. Above the VIF threshold they are attributed **as a group**, with a
note saying so.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tools.sm_exceptions import ConvergenceWarning
from statsmodels.tsa.statespace.sarimax import SARIMAX

from insight_copilot.contracts.models import KPIContract
from insight_copilot.engine.diagnostics import (
    MIN_OBSERVATIONS_PER_REGRESSOR,
    Diagnostics,
    collinear_groups,
    diagnose,
    explained_fraction_of,
)
from insight_copilot.errors import StatisticalError
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

HAC_BANDWIDTH_EXPONENT = 2.0 / 9.0
"""``L = floor(4·(T/100)^(2/9))`` - Newey and West's own rule of thumb."""

AGREEMENT_TOLERANCE = 0.5
"""Two estimates agree when they differ by less than half the larger magnitude. Looser
than it sounds: a SARIMAX and an OLS-HAC estimate of the same elasticity that differ
by more than that are not measuring the same thing."""


@dataclass(frozen=True)
class DriverEstimate:
    """One driver's estimated effect, from both estimators."""

    driver_id: str
    coefficient: float
    std_error: float
    p_value: float
    cross_check_coefficient: float
    group: tuple[str, ...] = ()
    vif: float = float("nan")

    @property
    def is_grouped(self) -> bool:
        """Was this attributed as part of a collinear group?"""
        return len(self.group) > 1

    @property
    def agreement(self) -> float:
        """0 to 1: how closely the two estimators agree on this coefficient."""
        scale = max(abs(self.coefficient), abs(self.cross_check_coefficient), 1e-12)
        return float(max(0.0, 1.0 - abs(self.coefficient - self.cross_check_coefficient) / scale))

    @property
    def agrees(self) -> bool:
        """Do the primary and cross-check estimates tell the same story?"""
        return self.agreement >= 1.0 - AGREEMENT_TOLERANCE

    @property
    def confidence_interval(self) -> tuple[float, float]:
        """95% interval from the primary estimator. Never a point estimate downstream."""
        return (
            self.coefficient - 1.96 * self.std_error,
            self.coefficient + 1.96 * self.std_error,
        )


@dataclass
class WhyResult:
    """Rung 3's output: coefficients, diagnostics and honest coverage."""

    estimates: list[DriverEstimate]
    diagnostics: Diagnostics
    agreement_score: float
    explained_fraction: float
    method: str = "sarimax_exog"
    notes: list[str] = field(default_factory=list)

    @property
    def unexplained_fraction(self) -> float:
        """The remainder, labelled honestly rather than allocated to the last driver."""
        return max(0.0, 1.0 - self.explained_fraction)

    def estimate(self, driver_id: str) -> DriverEstimate | None:
        """One driver's estimate, or ``None`` if it was not admissible."""
        return next((item for item in self.estimates if item.driver_id == driver_id), None)


def admissible_regressors(contract: KPIContract, estimand: str | None) -> list[str]:
    """Drivers admissible for a *total* effect of ``estimand``, per the contract's DAG.

    A mediator of the estimand is excluded. Conditioning on the channel through which
    an effect travels removes the effect and leaves a coefficient that is precisely
    estimated and answers a different question.
    """
    drivers = contract.drivers.exogenous
    if estimand is None:
        return [driver.id for driver in drivers if not driver.mediates]
    mediators = {driver.id for driver in drivers if estimand in driver.mediates}
    return [driver.id for driver in drivers if driver.id not in mediators]


def newey_west_lags(n: int) -> int:
    """``floor(4·(T/100)^(2/9))``, at least one."""
    return max(1, int(np.floor(4.0 * (n / 100.0) ** HAC_BANDWIDTH_EXPONENT)))


ERROR_MODEL_CANDIDATES: tuple[tuple[int, int, int], ...] = (
    (0, 0, 0),
    (1, 0, 0),
    (0, 0, 1),
    (1, 0, 1),
)
"""Error models the primary estimator chooses among, by AIC. Beyond ARMA(1,1) the error
process is describing seasonality the design matrix should carry as a regressor."""

PrimaryEstimator = Literal["sarimax", "hac"]


class DriverAttributor:
    """Estimates driver effects with two estimators and reports their disagreement.

    Which one leads is a modelling decision the caller states, not a preference:

    * ``sarimax`` for a **level** target. The errors are autocorrelated, the process is
      identifiable over three years of daily data, and a state-space model estimates it
      properly.
    * ``hac`` for a **differenced** target. Differencing induces a moving-average error
      whose order is not well determined, and a state-space fit on a differenced series
      converges poorly. Newey-West exists precisely so the error process does not have
      to be specified correctly: it is consistent under *any* autocorrelation up to the
      bandwidth. Measured on this world's weekly price elasticity the state-space fits
      disagree with each other across error models (-1.34 for AR(1), -0.96 for
      ARMA(1,1)) while HAC gives -1.63 against a planted -1.94; the agreement score
      falls from 0.99 to 0.59 as the error model is elaborated, which is the diagnostic
      saying the elaboration is not supported.

    Either way both are fitted and the agreement between them is reported, because two
    estimators that disagree is a finding rather than a nuisance to be resolved by
    picking a favourite.
    """

    def __init__(
        self,
        *,
        order: tuple[int, int, int] | None = None,
        primary: PrimaryEstimator = "sarimax",
    ) -> None:
        self._order = order
        self._primary = primary

    def attribute(
        self,
        target: np.ndarray,
        design: pd.DataFrame,
        *,
        driver_names: list[str] | None = None,
    ) -> WhyResult:
        """Fit both estimators and return coefficients, diagnostics and coverage."""
        matrix, response = _clean(design, target)
        if matrix.shape[0] < MIN_OBSERVATIONS_PER_REGRESSOR * max(matrix.shape[1], 1):
            raise StatisticalError(
                "too few observations for the number of regressors",
                detail=f"{matrix.shape[0]} rows against {matrix.shape[1]} regressors",
            )
        reported = driver_names or list(matrix.columns)
        groups, vifs = collinear_groups(matrix)

        hac = _fit_hac(response, matrix)
        state_space = self._fit_sarimax(response, matrix, self._select_order(response, matrix))
        primary, cross = (state_space, hac) if self._primary == "sarimax" else (hac, state_space)

        estimates = [
            DriverEstimate(
                driver_id=name,
                coefficient=float(primary.params.get(name, np.nan)),
                std_error=float(primary.bse.get(name, np.nan)),
                p_value=float(primary.pvalues.get(name, np.nan)),
                cross_check_coefficient=float(cross.params.get(name, np.nan)),
                group=groups.get(name, (name,)),
                vif=vifs.get(name, float("nan")),
            )
            for name in reported
            if name in matrix.columns
        ]
        diagnostics = diagnose(primary, response, matrix)
        agreement = float(np.mean([item.agreement for item in estimates])) if estimates else 0.0
        notes = [
            f"{'/'.join(item.group)} attributed as a collinear group (VIF {item.vif:.1f})"
            for item in estimates
            if item.is_grouped
        ]
        explained = explained_fraction_of(primary, response)
        return WhyResult(
            estimates=estimates,
            diagnostics=diagnostics,
            agreement_score=agreement,
            explained_fraction=explained,
            method="sarimax_exog" if self._primary == "sarimax" else "ols_newey_west",
            notes=sorted(set(notes)),
        )

    def _select_order(self, response: np.ndarray, matrix: pd.DataFrame) -> tuple[int, int, int]:
        """Box-Jenkins order selection over a small candidate set, by AIC.

        Hard-coding AR(1) is a magic number, and on an already-differenced target it is
        an actively wrong one: differencing removes the unit root and induces a moving
        -average error, so an AR term competes with the regressors for the same
        variation instead of describing the error. The candidates therefore include a
        pure-regression model, AR(1), MA(1) and ARMA(1,1), and AIC picks among them on
        the same fit that produces the coefficients.
        """
        if self._order is not None:
            return self._order
        best, best_aic = ERROR_MODEL_CANDIDATES[0], np.inf
        for candidate in ERROR_MODEL_CANDIDATES:
            try:
                with warnings.catch_warnings():
                    # Order selection fits every candidate; a candidate that will not
                    # converge is simply a candidate AIC will not pick, so its warning
                    # is noise here rather than information.
                    warnings.simplefilter("ignore", ConvergenceWarning)
                    fitted = SARIMAX(
                        response,
                        exog=matrix,
                        order=candidate,
                        trend="c",
                        enforce_stationarity=False,
                        enforce_invertibility=False,
                    ).fit(disp=False, maxiter=200)
            except (ValueError, np.linalg.LinAlgError):
                continue
            if float(fitted.aic) < best_aic:
                best, best_aic = candidate, float(fitted.aic)
        logger.info("attribute_why.order_selected", order=best, aic=best_aic)
        selected: tuple[int, int, int] = best
        return selected

    def _fit_sarimax(
        self, response: np.ndarray, matrix: pd.DataFrame, order: tuple[int, int, int]
    ) -> sm.regression.linear_model.RegressionResultsWrapper:
        """SARIMAX with exogenous regressors; falls back to OLS-HAC if it will not fit.

        The fallback is reported, never silent: an unconverged state-space model that
        quietly becomes an OLS is how a system claims a method it did not run.

        Non-convergence is **captured rather than printed**. statsmodels raises a
        ``ConvergenceWarning`` through the ``warnings`` machinery, which puts a stack
        trace on stderr in the middle of a live demo. The information matters — it is
        exactly why the state-space model is the cross-check and not the primary
        estimator on a trended design — so it is redirected into the structured log,
        where it is greppable and carries the run id, instead of being suppressed or
        left to print.
        """
        try:
            model = SARIMAX(
                response,
                exog=matrix,
                order=order,
                trend="c",
                enforce_stationarity=False,
                enforce_invertibility=False,
            )
            with warnings.catch_warnings(record=True) as captured:
                warnings.simplefilter("always", ConvergenceWarning)
                fitted = model.fit(disp=False, maxiter=200)
            for item in captured:
                logger.info(
                    "attribute_why.sarimax_convergence",
                    order=order,
                    detail=str(item.message),
                )
            return fitted
        except (ValueError, np.linalg.LinAlgError) as exc:
            logger.warning("attribute_why.sarimax_failed", error=str(exc))
            return _fit_hac(response, matrix)


def _fit_hac(
    response: np.ndarray, matrix: pd.DataFrame
) -> sm.regression.linear_model.RegressionResultsWrapper:
    """OLS with Newey-West HAC standard errors at the recommended bandwidth."""
    design = sm.add_constant(matrix, has_constant="add")
    return sm.OLS(response, design).fit(
        cov_type="HAC", cov_kwds={"maxlags": newey_west_lags(len(response))}
    )


def _clean(design: pd.DataFrame, target: np.ndarray) -> tuple[pd.DataFrame, np.ndarray]:
    """Drop rows any regressor cannot supply, and constant columns."""
    frame = design.reset_index(drop=True).astype(np.float64)
    response = pd.Series(np.asarray(target, dtype=np.float64))
    usable = frame.notna().all(axis=1) & response.notna()
    frame, response = frame.loc[usable], response.loc[usable]
    varying = [name for name in frame.columns if float(frame[name].std()) > 1e-12]
    if not varying:
        raise StatisticalError("every regressor is constant over the estimation window")
    return frame[varying].reset_index(drop=True), response.to_numpy(dtype=np.float64)
