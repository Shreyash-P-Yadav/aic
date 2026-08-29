"""I1 — the order management system. The highest-quality feed, and still not clean.

Three legitimate distortions, none of them defects:

* **A midnight cut-off.** Orders placed near midnight IST land on whichever side of
  the boundary the exporting system decided, which is why OMS units and WMS units
  disagree by half a percent even when nothing is wrong.
* **Cancellations post-date their orders.** A line cancelled on the 11th belongs to
  the 9th's order, so a same-day view of "units sold" is always slightly optimistic.
* **Returns are recognised on receipt, not on sale.** The 7-21 day lag is why the ops
  definition of net revenue and the finance definition differ by 1-3%.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from insight_copilot.datagen.projection.base import ProjectionContext, SourceProjector

MIDNIGHT_SPILL_FRACTION = 0.006
"""Share of each day's units the export stamps to the following day.

Small, structural, and the reason the OMS-vs-WMS reconciliation has a floor it can
never get below — which is what makes a *designed* tolerance meaningful rather than
an admission of sloppiness.
"""


class OMSProjector(SourceProjector):
    """Order lines at date x SKU x region x channel."""

    def project(self, context: ProjectionContext) -> pd.DataFrame:
        panel = context.panel
        frame = panel.sales_frame(context.config, context.catalog)

        frame = frame.rename(columns={"date": "order_date"})
        frame["order_id"] = _order_ids(frame)
        frame["ordered_at_ts"] = _order_timestamps(frame, context)

        # The midnight cut-off: a slice of each day's units is stamped to the next.
        # Applied to the timestamp only, so `order_date` and the timestamp disagree
        # exactly as a real export's do.
        spill = frame["units"] * MIDNIGHT_SPILL_FRACTION
        frame["ordered_at_ts"] = frame["ordered_at_ts"] + pd.to_timedelta(
            (spill > 0.5).astype(int) * 23, unit="h"
        )

        frame["customer_segment"] = _customer_segment(frame, context)
        frame["cancelled_units"] = np.round(frame["cancelled_units"]).astype("int64")
        frame["units"] = np.round(frame["units"]).astype("int64")
        return frame[
            [
                "order_date",
                "order_id",
                "product_sku",
                "region",
                "channel",
                "customer_segment",
                "units",
                "unit_price_net",
                "list_price",
                "returns_value",
                "cancelled_units",
                "ordered_at_ts",
            ]
        ]


def _order_ids(frame: pd.DataFrame) -> pd.Series:
    """Stable synthetic order ids.

    Derived from the row's own business key rather than from a counter, so
    regenerating the world produces the same ids and a diff of two exports is
    readable.
    """
    dates = pd.to_datetime(frame["order_date"]).dt.strftime("%Y%m%d")
    suffix = (
        frame["product_sku"].astype(str).str.slice(4)
        + frame["region"].astype(str).str.slice(0, 1)
        + frame["channel"].astype(str).str.slice(0, 2)
    )
    ids: pd.Series = "ORD-" + dates + "-" + suffix
    return ids


def _order_timestamps(frame: pd.DataFrame, context: ProjectionContext) -> pd.Series:
    """Intra-day order times, deterministic per row.

    Spread across the day with an evening peak, because a flat distribution would
    make the midnight cut-off effect either zero or total rather than a small,
    realistic sliver.
    """
    seeds = context.simulator.seeds
    offsets = seeds("oms_order_time").integers(0, 24 * 60, size=len(frame))
    evening = seeds("oms_order_evening").integers(0, 5 * 60, size=len(frame))
    minutes = np.minimum(offsets + evening, 24 * 60 - 1)
    stamps: pd.Series = pd.to_datetime(frame["order_date"]) + pd.to_timedelta(minutes, unit="m")
    return stamps


def _customer_segment(frame: pd.DataFrame, context: ProjectionContext) -> pd.Series:
    """New / repeat / subscription, with a small UNKNOWN bucket.

    UNKNOWN is not a defect here: identity resolution genuinely fails for a slice of
    guest checkouts, and the mix analysis has to cope with it rather than assume it
    away.
    """
    seeds = context.simulator.seeds
    draws = seeds("oms_segment").random(len(frame))
    segments = np.where(draws < 0.34, "new", np.where(draws < 0.86, "repeat", "subscription"))
    segments = np.where(draws > 0.985, "UNKNOWN", segments)
    return pd.Series(segments, index=frame.index)
