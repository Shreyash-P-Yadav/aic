"""Regression diagnostics: whether the assumptions survived contact with the data.

Split from the estimator because these are what a reader checks *before* believing a
coefficient, and because the evidence drawer renders them verbatim. A diagnostic that
failed is the reason a number is not to be trusted, and it belongs somewhere it can be
read without wading through the fitting code.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.diagnostic import acorr_ljungbox, het_breuschpagan
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.stats.stattools import durbin_watson

MIN_OBSERVATIONS_PER_REGRESSOR = 12
"""A year of weekly variation per coefficient. Below it the fit is interpolation."""

VIF_GROUPING_THRESHOLD = 5.0
"""Above this a regressor's variance is inflated fivefold by its correlation with the
others, which is the conventional line between 'noisy' and 'not separately
identifiable'. Grouped, not dropped."""

HOLDOUT_FRACTION = 0.15
"""Tail of the sample held out for the MAPE diagnostic. A model that fits the sample and
cannot predict the last few months is describing history, not a mechanism."""


@dataclass
class Diagnostics:
    """Whether the regression's assumptions survived contact with the data."""

    ljung_box_p: float
    breusch_pagan_p: float
    durbin_watson: float
    holdout_mape: float
    max_vif: float
    n_observations: int

    @property
    def residuals_white(self) -> bool:
        """Ljung-Box failed to reject whiteness."""
        return self.ljung_box_p > 0.05

    @property
    def homoscedastic(self) -> bool:
        """Breusch-Pagan failed to reject constant variance."""
        return self.breusch_pagan_p > 0.05

    @property
    def detail(self) -> str:
        """The diagnostics block the evidence drawer renders verbatim."""
        return (
            f"n={self.n_observations}; Ljung-Box p={self.ljung_box_p:.3f}; "
            f"Breusch-Pagan p={self.breusch_pagan_p:.3f}; "
            f"Durbin-Watson={self.durbin_watson:.2f}; "
            f"holdout MAPE={self.holdout_mape:.1%}; max VIF={self.max_vif:.1f}"
        )


def collinear_groups(
    design: pd.DataFrame, threshold: float = VIF_GROUPING_THRESHOLD
) -> tuple[dict[str, tuple[str, ...]], dict[str, float]]:
    """Group regressors whose VIF exceeds the threshold, and report every VIF."""
    if design.shape[1] < 2:
        return {name: (name,) for name in design.columns}, dict.fromkeys(design.columns, 1.0)
    matrix = sm.add_constant(design, has_constant="add").to_numpy(dtype=np.float64)
    vifs: dict[str, float] = {}
    for position, name in enumerate(design.columns, start=1):
        try:
            vifs[name] = float(np.asarray(variance_inflation_factor(matrix, position)))
        except (ValueError, ZeroDivisionError, np.linalg.LinAlgError):
            vifs[name] = float("inf")

    inflated = [name for name, value in vifs.items() if value > threshold]
    correlation = design[inflated].corr().abs() if len(inflated) > 1 else pd.DataFrame()
    groups: dict[str, tuple[str, ...]] = {name: (name,) for name in design.columns}
    assigned: set[str] = set()
    for name in inflated:
        if name in assigned:
            continue
        partners = [
            other
            for other in inflated
            if other != name and float(str(correlation.loc[name, other])) > 0.7
        ]
        members = tuple(sorted([name, *partners]))
        for member in members:
            groups[member] = members
            assigned.add(member)
    return groups, vifs


ERROR_MODEL_CANDIDATES: tuple[tuple[int, int, int], ...] = (
    (0, 0, 0),
    (1, 0, 0),
    (0, 0, 1),
    (1, 0, 1),
)
"""Error models the primary estimator chooses among, by AIC. Beyond ARMA(1,1) the error
process is describing seasonality the design matrix should carry as a regressor."""


def diagnose(result: object, response: np.ndarray, matrix: pd.DataFrame) -> Diagnostics:
    """Run every diagnostic the contract's evidence drawer promises."""
    residuals = np.asarray(getattr(result, "resid", np.zeros_like(response)), dtype=np.float64)
    residuals = residuals[np.isfinite(residuals)]
    lags = min(14, max(1, residuals.size // 5))
    ljung = float(acorr_ljungbox(residuals, lags=[lags], return_df=True)["lb_pvalue"].iloc[0])
    exog = sm.add_constant(matrix, has_constant="add").to_numpy(dtype=np.float64)
    trimmed = exog[-residuals.size :] if residuals.size <= exog.shape[0] else exog
    try:
        breusch = float(het_breuschpagan(residuals, trimmed)[1])
    except (ValueError, np.linalg.LinAlgError):
        breusch = float("nan")
    _, vifs = collinear_groups(matrix)
    return Diagnostics(
        ljung_box_p=ljung,
        breusch_pagan_p=breusch,
        durbin_watson=float(durbin_watson(residuals)),
        holdout_mape=holdout_mape(response, matrix),
        max_vif=max(vifs.values()) if vifs else float("nan"),
        n_observations=int(response.size),
    )


def holdout_mape(response: np.ndarray, matrix: pd.DataFrame) -> float:
    """Refit on the head, predict the tail. The only out-of-sample number here.

    Undefined — and reported as such — for a target centred on zero. A differenced
    series has no meaningful percentage error: dividing by an observation that is
    itself near zero produces a number in the hundreds of percent that says nothing
    about fit, and printing it in an evidence drawer would be worse than printing
    nothing.
    """
    if abs(float(np.mean(response))) < 0.25 * float(np.std(response)):
        return float("nan")
    n = response.size
    split = int(n * (1.0 - HOLDOUT_FRACTION))
    if split < MIN_OBSERVATIONS_PER_REGRESSOR * max(matrix.shape[1], 1):
        return float("nan")
    train = sm.add_constant(matrix.iloc[:split], has_constant="add")
    test = sm.add_constant(matrix.iloc[split:], has_constant="add")
    fitted = sm.OLS(response[:split], train).fit()
    predicted = np.asarray(fitted.predict(test), dtype=np.float64)
    actual = response[split:]
    denominator = np.where(np.abs(actual) > 1e-9, np.abs(actual), np.nan)
    return float(np.nanmean(np.abs(predicted - actual) / denominator))


def explained_fraction_of(result: object, response: np.ndarray) -> float:
    """Share of the target's variance the model accounts for. Clipped at zero."""
    residuals = np.asarray(getattr(result, "resid", np.zeros_like(response)), dtype=np.float64)
    residuals = residuals[np.isfinite(residuals)]
    if residuals.size == 0:
        return 0.0
    centred = response[-residuals.size :] - np.mean(response[-residuals.size :])
    total = float(np.dot(centred, centred))
    return max(0.0, 1.0 - float(np.dot(residuals, residuals)) / total) if total > 0 else 0.0
