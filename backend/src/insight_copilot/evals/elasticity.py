"""Naive versus DAG-specified marketing elasticity — the endogeneity demonstration.

The generator sets media budget as a share of revenue with a tactical overlay that
responds to last week's performance. That is simultaneity by construction, and it is
the reason a naive regression of log units on log adstocked spend recovers the wrong
number. Because the planted elasticity is known exactly, both estimates can be put
beside the truth rather than argued about.

Lives in the library rather than in the test suite because the eval report has to print
it, and a number the report quotes from a test file is a number nobody can recompute.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm

from insight_copilot.engine.attribute_why import newey_west_lags
from insight_copilot.engine.design import adstock, fourier_terms
from insight_copilot.ingest.warehouse import Warehouse

ADSTOCK_HALFLIFE_DAYS = 7.0
"""Carryover half-life for media. One week: long enough that a flight's effect outlives
its invoice, short enough not to blur two campaigns into one."""

FOURIER_HARMONICS = 2
"""Annual seasonality at two harmonics. More would start absorbing the media variation
this regression exists to measure."""

MIN_SPEND_FLOOR = 1.0
"""Logs need a positive argument. A week with no spend is a real observation, so it is
floored rather than dropped — dropping it would select on the regressor."""


@dataclass(frozen=True)
class ElasticityComparison:
    """Both estimates against the planted truth."""

    naive: float
    dag_specified: float
    truth: float
    observations: int

    @property
    def naive_error(self) -> float:
        """|naive - truth|."""
        return abs(self.naive - self.truth)

    @property
    def specified_error(self) -> float:
        """|DAG-specified - truth|."""
        return abs(self.dag_specified - self.truth)

    @property
    def improvement(self) -> float:
        """How many times closer the specified estimate is. Below 1 would be a failure."""
        return self.naive_error / max(self.specified_error, 1e-12)


def weekly_panel(warehouse: Warehouse) -> pd.DataFrame:
    """National weekly units, price, fill rate and media spend — whole weeks only.

    Partial weeks are excluded because a week with five days of sales and seven days of
    seasonality is not comparable to a full one, and including it puts a step change
    into the target that the regressors cannot explain.
    """
    revenue = warehouse.query(
        "SELECT iso_week, sum(units) AS units, "
        "sum(units * unit_price_net) / nullif(sum(units), 0) AS asp, "
        "count(DISTINCT date) AS days FROM gold.fct_revenue_daily GROUP BY 1 ORDER BY 1"
    )
    media = warehouse.query(
        "SELECT iso_week, sum(spend_inr) AS spend FROM gold.fct_marketing_weekly GROUP BY 1"
    )
    fill = warehouse.query(
        "SELECT iso_week, 100.0 * sum(units_shipped_ok) / nullif(sum(units_ordered), 0) AS fill "
        "FROM gold.fct_fulfilment_daily GROUP BY 1"
    )
    frame = revenue.merge(media, on="iso_week").merge(fill, on="iso_week")
    frame = frame[(frame["days"] == 7) & (frame["units"] > 0)]
    return frame.sort_values("iso_week").reset_index(drop=True)


def planted_blended_elasticity() -> float:
    """The truth, read from the world config rather than transcribed into a constant.

    A single blended marketing elasticity measures the SUM of the six per-channel
    elasticities, because the demand equation applies every channel's adstock term
    simultaneously. Reading it from the config means a change to the world cannot leave
    a stale answer key behind in an eval.
    """
    from insight_copilot.datagen.world.config import load_world_config

    return float(sum(channel.elasticity for channel in load_world_config().media.channels))


def media_elasticities(warehouse: Warehouse, *, truth: float | None = None) -> ElasticityComparison:
    """Fit both specifications and return them beside the planted value.

    The naive model regresses log units on log adstocked spend and nothing else — which
    is exactly what a dashboard does when it reports "ROAS". The specified model adds
    the controls the contract's driver DAG admits for a *total* effect: price, fill
    rate, trend and annual seasonality, with Newey-West standard errors because weekly
    demand errors are autocorrelated. Unit volume is deliberately absent: it mediates
    every driver, and conditioning on it would estimate a different quantity.
    """
    planted = planted_blended_elasticity() if truth is None else truth
    frame = weekly_panel(warehouse)
    target = np.log(frame["units"].to_numpy(dtype=float))
    index = np.arange(len(frame), dtype=float)
    carried = np.log(
        np.clip(
            adstock(frame["spend"].to_numpy(dtype=float) / 7.0, ADSTOCK_HALFLIFE_DAYS),
            MIN_SPEND_FLOOR,
            None,
        )
    )
    naive = sm.OLS(target, sm.add_constant(pd.DataFrame({"media": carried}))).fit()
    controls = pd.concat(
        [
            pd.DataFrame(
                {
                    "media": carried,
                    "price_index": np.log(frame["asp"].to_numpy(dtype=float)),
                    "fill_rate": np.log(
                        np.clip(frame["fill"].to_numpy(dtype=float), MIN_SPEND_FLOOR, None) / 100.0
                    ),
                    "trend": index / 52.0,
                }
            ),
            fourier_terms(index * 7.0, 365.25, FOURIER_HARMONICS),
        ],
        axis=1,
    )
    specified = sm.OLS(target, sm.add_constant(controls)).fit(
        cov_type="HAC", cov_kwds={"maxlags": newey_west_lags(len(frame))}
    )
    return ElasticityComparison(
        naive=float(naive.params["media"]),
        dag_specified=float(specified.params["media"]),
        truth=planted,
        observations=len(frame),
    )
