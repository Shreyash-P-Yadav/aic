"""I2 — the warehouse management system. Vendor-hosted, T+2, and occasionally silent.

The T+2 latency is the interesting part. Fill rate is a *leading* indicator of
revenue, and it arrives two days after the revenue it predicts — so any insight built
on it has to be labelled "as of T-2", and the freshness-aware join is not optional.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from insight_copilot.datagen.projection.base import ProjectionContext, SourceProjector

EXTRACT_LATENCY_DAYS = 2
"""The contract's declared T+2. The extract for day T is stamped as run on T+2."""

SUPPLIERS = (
    "Kaveri Polymers",
    "Sahyadri Packaging",
    "Nilgiri Chemicals",
    "Deccan Botanicals",
    "Konkan Glassworks",
)
"""Fictional suppliers. Commercially sensitive, hence masked for junior roles."""


class WMSProjector(SourceProjector):
    """Fulfilment at ship date x warehouse x SKU."""

    def project(self, context: ProjectionContext) -> pd.DataFrame:
        panel = context.panel
        frame = panel.fulfilment_frame(context.config, context.catalog)
        frame = frame.rename(columns={"date": "ship_date"})

        seeds = context.simulator.seeds
        # Inbound delay is a property of the SKU's supply chain, not of the day, so
        # it is drawn per SKU and then perturbed daily. A purely daily draw would
        # make it white noise and the driver regression would find nothing.
        sku_codes = frame["product_sku"].cat.codes.to_numpy()
        base_delay = seeds("wms_supplier_delay").integers(0, 6, size=len(context.catalog.skus))
        jitter = seeds("wms_delay_jitter").integers(0, 4, size=len(frame))
        frame["inbound_delay_days"] = (base_delay[sku_codes] + jitter).astype("int64")

        frame["supplier_name"] = np.array(SUPPLIERS)[sku_codes % len(SUPPLIERS)]
        frame["extracted_at_ts"] = pd.to_datetime(frame["ship_date"]) + pd.Timedelta(
            days=EXTRACT_LATENCY_DAYS, hours=5
        )
        for column in ("units_ordered", "units_shipped_ok", "units_short"):
            frame[column] = np.round(frame[column]).astype("int64")

        return frame[
            [
                "ship_date",
                "warehouse",
                "product_sku",
                "units_ordered",
                "units_shipped_ok",
                "units_short",
                "inbound_delay_days",
                "supplier_name",
                "extracted_at_ts",
            ]
        ]
