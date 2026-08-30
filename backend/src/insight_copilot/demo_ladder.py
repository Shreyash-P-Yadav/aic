"""Rungs 2 and 3 of the ladder for the scripted demo.

Rung 1 answers *where*. On its own that is a dashboard filter with better statistics
behind it. What makes the ladder worth walking is that the next two rungs answer
different questions about the same movement — *what kind* of change it was, and *which
drivers* moved — and that each is a smaller, harder, more falsifiable claim than the
one above it.

Kept out of ``demo.py`` because that module is already the length it should be, and
because these two rungs are the ones most likely to be reused by a scheduled scan.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

from insight_copilot.contracts.models import KPIContract
from insight_copilot.engine.attribute_kind import BennetDecomposition, decompose
from insight_copilot.engine.attribute_why import DriverAttributor, WhyResult, admissible_regressors
from insight_copilot.engine.design import adstock, fourier_terms
from insight_copilot.errors import StatisticalError
from insight_copilot.ingest.warehouse import Warehouse
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

ADSTOCK_HALFLIFE_DAYS = 7.0
"""Media carryover, matching the eval suite's specification so the coefficient the demo
shows and the coefficient the eval reports are the same quantity."""

FOURIER_HARMONICS = 2
"""Annual seasonality. More harmonics start absorbing the driver variation."""

MEDIATOR = "unit_volume"
"""The estimand's mediator. Excluded from the design so the estimates are TOTAL effects:
control for volume and the marketing coefficient collapses, because you have conditioned
away the channel the effect travels through."""

LOG_FLOOR = 1.0
"""Logs need a positive argument; a zero week is floored, never dropped."""


@dataclass(frozen=True)
class LadderRungs:
    """What rungs 2 and 3 found, and what the bundle needs from them."""

    bennet: BennetDecomposition | None
    why: WhyResult | None

    reference_revenue: float | None = None
    """Revenue in the window the Bennet split compares against."""

    comparison_revenue: float | None = None
    """Revenue in the window being decomposed."""

    label: str = ""
    """The two windows, in words."""

    @property
    def price_effect(self) -> float | None:
        """Rung 2's price term, in rupees."""
        return self.bennet.price_effect if self.bennet else None

    @property
    def volume_effect(self) -> float | None:
        """Rung 2's own-volume term."""
        return self.bennet.own_volume_effect if self.bennet else None

    @property
    def mix_effect(self) -> float | None:
        """Rung 2's mix term. The three sum to ΔR exactly; that is an identity."""
        return self.bennet.mix_effect if self.bennet else None


def build_rungs(
    warehouse: Warehouse, contract: KPIContract, window: tuple[dt.date, dt.date]
) -> LadderRungs:
    """Run both rungs, degrading each independently.

    A failure in one rung must not remove the other from the screen: they answer
    different questions, and a driver regression that will not converge says nothing
    about whether the price/volume/mix split is valid.
    """
    bennet, reference, comparison, label = _bennet(warehouse, window)
    return LadderRungs(
        bennet=bennet,
        why=_why(warehouse, contract),
        reference_revenue=reference,
        comparison_revenue=comparison,
        label=label,
    )


def _bennet(
    warehouse: Warehouse, window: tuple[dt.date, dt.date]
) -> tuple[BennetDecomposition | None, float | None, float | None, str]:
    """Rung 2: the price / own-volume / mix split against the preceding window.

    Returns the decomposition together with the two revenue totals it compares, because
    those totals — not the counterfactual — are what the waterfall must anchor on. The
    three Bennet terms sum to ``comparison - reference`` exactly; anchoring anywhere
    else invents a residual that a reader would take for model error.
    """
    start, end = window
    span = (end - start).days + 1
    reference_start = start - dt.timedelta(days=span)
    reference_end = start - dt.timedelta(days=1)
    try:
        before = _sku_period(warehouse, reference_start, reference_end)
        after = _sku_period(warehouse, start, end)
        if before.empty or after.empty:
            return None, None, None, ""
        decomposition = decompose(
            before, after, item_column="product_sku", price_column="price", quantity_column="units"
        )
    except StatisticalError as exc:
        logger.warning("demo.bennet_failed", error=str(exc))
        return None, None, None, ""
    reference = float((before["price"] * before["units"]).sum())
    comparison = float((after["price"] * after["units"]).sum())
    label = f"{start:%d %b} to {end:%d %b} against {reference_start:%d %b} to {reference_end:%d %b}"
    return decomposition, reference, comparison, label


def _why(warehouse: Warehouse, contract: KPIContract) -> WhyResult | None:
    """Rung 3: driver coefficients at national weekly grain, with two estimators.

    ``hac`` leads on this target rather than the state-space model. The target is a log
    level with a trend regressor, the errors are autocorrelated, and Newey-West is
    consistent under any autocorrelation up to the bandwidth without having to specify
    the error process correctly — which, measured on this world, the state-space fits
    disagree with each other about.
    """
    frame = _weekly_panel(warehouse)
    if len(frame) < 52:
        logger.warning("demo.why_skipped", weeks=len(frame))
        return None
    index = np.arange(len(frame), dtype=float)
    design = pd.concat(
        [
            pd.DataFrame(
                {
                    "marketing_adstock": np.log(
                        np.clip(
                            adstock(
                                frame["spend"].to_numpy(dtype=float) / 7.0, ADSTOCK_HALFLIFE_DAYS
                            ),
                            LOG_FLOOR,
                            None,
                        )
                    ),
                    "price_index": np.log(frame["asp"].to_numpy(dtype=float)),
                    "fill_rate": np.log(
                        np.clip(frame["fill"].to_numpy(dtype=float), LOG_FLOOR, None) / 100.0
                    ),
                    "trend": index / 52.0,
                }
            ),
            fourier_terms(index * 7.0, 365.25, FOURIER_HARMONICS),
        ],
        axis=1,
    )
    admissible = [
        name for name in admissible_regressors(contract, MEDIATOR) if name in design.columns
    ]
    target = np.log(frame["revenue"].to_numpy(dtype=float))
    try:
        return DriverAttributor(primary="hac").attribute(
            target, design, driver_names=admissible or list(design.columns[:3])
        )
    except StatisticalError as exc:
        logger.warning("demo.why_failed", error=str(exc))
        return None


def _sku_period(warehouse: Warehouse, start: dt.date, end: dt.date) -> pd.DataFrame:
    """SKU-level units and realised price over one window."""
    return warehouse.query(
        "SELECT product_sku, sum(units) AS units, "
        "sum(units * unit_price_net) / nullif(sum(units), 0) AS price "
        "FROM gold.fct_revenue_daily WHERE date BETWEEN $start AND $end "
        "GROUP BY 1 HAVING sum(units) > 0",
        {"start": start, "end": end},
    )


def _weekly_panel(warehouse: Warehouse) -> pd.DataFrame:
    """National weekly revenue, units, price, fill and spend — whole weeks only."""
    revenue = warehouse.query(
        "SELECT iso_week, sum(units * unit_price_net) AS revenue, sum(units) AS units, "
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
    frame = frame[(frame["days"] == 7) & (frame["revenue"] > 0)]
    return frame.sort_values("iso_week").reset_index(drop=True)
