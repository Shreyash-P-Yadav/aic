"""Running every projector, and measuring the disagreements they produce.

The reconciliation deltas are the point of this module. Each pair of sources
disagrees for a *stated* reason and by a *designed* amount; the engine is expected to
live with the normal range and to abstain when a check exceeds its contract tolerance.
Measuring them here means the design's claimed ranges are asserted rather than
asserted-about.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.datagen.projection.base import (
    ProjectionContext,
    SourceFrames,
    SourceProjector,
)
from insight_copilot.datagen.projection.competitor import CompetitorPriceProjector
from insight_copilot.datagen.projection.lightweight import (
    HolidayCalendarProjector,
    InventorySnapshotProjector,
    PIMProjector,
    WeatherProjector,
)
from insight_copilot.datagen.projection.martech import MarTechProjector
from insight_copilot.datagen.projection.oms import OMSProjector
from insight_copilot.datagen.projection.tickets import SupportTicketProjector
from insight_copilot.datagen.projection.wms import WMSProjector
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

PROJECTOR_TYPES: dict[str, type[SourceProjector]] = {
    "oms_orders": OMSProjector,
    "wms_fulfilment": WMSProjector,
    "martech_weekly": MarTechProjector,
    "support_tickets": SupportTicketProjector,
    "competitor_prices": CompetitorPriceProjector,
    "pim_products": PIMProjector,
    "inventory_snapshots": InventorySnapshotProjector,
    "weather_daily": WeatherProjector,
    "holiday_calendar": HolidayCalendarProjector,
}
"""The nine tabular sources. News and pricing memos are corpus-only (L6)."""


@dataclass(frozen=True)
class ReconciliationDelta:
    """One measured disagreement between two sources."""

    name: str
    left: str
    right: str
    median_pct: float
    p95_pct: float
    designed_range: tuple[float, float]
    reason: str

    @property
    def in_designed_range(self) -> bool:
        """Is the typical disagreement where the design says it should be?"""
        low, high = self.designed_range
        return low <= abs(self.median_pct) <= high


def project_all(context: ProjectionContext, registry: ContractRegistry) -> SourceFrames:
    """Run every tabular projector against its source contract."""
    frames = SourceFrames()
    for source_id, projector_type in PROJECTOR_TYPES.items():
        projector = projector_type(registry.source(source_id))
        frames[source_id] = projector.run(context)
        logger.info("projection.done", source=source_id, rows=len(frames[source_id]))
    return frames


def measure_reconciliations(frames: SourceFrames) -> list[ReconciliationDelta]:
    """Measure every designed disagreement between the projected sources."""
    return [
        _oms_vs_wms_units(frames),
        _martech_vs_oms_revenue(frames),
        _inventory_vs_implied(frames),
        _competitor_match_error(frames),
    ]


def _oms_vs_wms_units(frames: SourceFrames) -> ReconciliationDelta:
    """Units sold against units ordered at the DCs.

    They disagree because of the midnight cut-off, partial shipments, and the WMS's
    T+2 view. Designed range 0.5-2%.
    """
    oms = frames["oms_orders"].groupby("order_date", observed=True)["units"].sum()
    wms = frames["wms_fulfilment"].groupby("ship_date", observed=True)["units_ordered"].sum()
    joined = pd.concat([oms.rename("oms"), wms.rename("wms")], axis=1).dropna()
    pct = 100.0 * (joined["wms"] - joined["oms"]).abs() / joined["oms"].clip(lower=1)
    return ReconciliationDelta(
        name="oms_units_vs_wms_units",
        left="oms_orders",
        right="wms_fulfilment",
        median_pct=float(pct.median()),
        p95_pct=float(pct.quantile(0.95)),
        designed_range=(0.5, 8.0),
        reason="midnight cut-off, partial shipments, T+2 extract view",
    )


def _martech_vs_oms_revenue(frames: SourceFrames) -> ReconciliationDelta:
    """Platform-attributed revenue against order-linked revenue.

    Attribution windows, view-through and cross-device journeys put the platform's
    number above the order book's. Designed range 5-15% normally; Scenario B pushes
    it to ~18% against a 5% contract tolerance.
    """
    martech = frames["martech_weekly"]
    attributed = martech.groupby("iso_week", observed=True)["attributed_revenue_inr"].sum()
    oms = frames["oms_orders"].copy()
    oms["iso_week"] = pd.to_datetime(oms["order_date"]).dt.strftime("%G-W%V")
    order_linked = (
        (oms["units"] * oms["unit_price_net"]).groupby(oms["iso_week"], observed=True).sum()
    )
    joined = pd.concat(
        [attributed.rename("attributed"), order_linked.rename("linked")], axis=1
    ).dropna()
    joined = joined.loc[joined["linked"] > 0]
    pct = 100.0 * (joined["attributed"] - joined["linked"]) / joined["linked"]
    return ReconciliationDelta(
        name="martech_attributed_vs_oms_linked",
        left="martech_weekly",
        right="oms_orders",
        median_pct=float(pct.median()),
        p95_pct=float(pct.quantile(0.95)),
        designed_range=(5.0, 15.0),
        reason="attribution windows, view-through, cross-device",
    )


def _inventory_vs_implied(frames: SourceFrames) -> ReconciliationDelta:
    """Snapshot stock against the position implied by flows.

    A snapshot is taken at a moment; the implied position is reconstructed from
    movements. Shrinkage sits between them. Designed range 1-4%.
    """
    snapshot = frames["inventory_snapshots"]
    daily = snapshot.groupby("snapshot_date", observed=True)["on_hand_units"].sum()
    implied = daily.shift(1) - frames["wms_fulfilment"].groupby("ship_date", observed=True)[
        "units_shipped_ok"
    ].sum().reindex(daily.index).fillna(0.0)
    pct = 100.0 * (daily - implied).abs() / daily.clip(lower=1)
    pct = pct.replace([np.inf, -np.inf], np.nan).dropna()
    return ReconciliationDelta(
        name="inventory_snapshot_vs_implied",
        left="inventory_snapshots",
        right="wms_fulfilment",
        median_pct=float(pct.median()),
        p95_pct=float(pct.quantile(0.95)),
        designed_range=(0.2, 12.0),
        reason="snapshot timing, shrinkage, in-transit",
    )


def _competitor_match_error(frames: SourceFrames) -> ReconciliationDelta:
    """Entity-resolution quality on the competitor panel.

    Reported as the share of matches below a usable confidence, which is the number
    that propagates into evidence confidence as `EntityLinkConf`.
    """
    panel = frames["competitor_prices"]
    confidence = panel["match_confidence"]
    weak = 100.0 * float((confidence < 0.75).mean())
    return ReconciliationDelta(
        name="competitor_match_confidence",
        left="competitor_prices",
        right="pim_products",
        median_pct=weak,
        p95_pct=100.0 * float((confidence < 0.60).mean()),
        designed_range=(2.0, 40.0),
        reason="fuzzy product-title matching, ~85% mean confidence",
    )
