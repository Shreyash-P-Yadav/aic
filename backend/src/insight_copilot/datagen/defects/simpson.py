"""P23 — Simpson's paradox, in its own module because it needs both halves.

The injection and the detection are inseparable here: the point is not that margin
moved, it is that it moved in *opposite directions* at two levels of aggregation.
Getting the injection slightly wrong produces ordinary aggregation rather than a
reversal, and a detector that accepts ordinary aggregation would let an engine that
only ever looks at the total off the hook.
"""

from __future__ import annotations

import datetime as dt
from typing import ClassVar

import numpy as np
import pandas as pd

from insight_copilot.datagen.defects.base import DefectEvidence, DefectInjector
from insight_copilot.datagen.projection.base import ProjectionContext, SourceFrames


class SimpsonsParadox(DefectInjector):
    """P23 — margin flat nationally while both segments decline.

    Premium mix rises enough to hold the blended margin steady while margin falls
    *within* both the premium and the mass segment. Reporting only the national number
    would say nothing is wrong; the nested-segment reversal check is what catches it.
    """

    code: ClassVar[str] = "P23"
    title: ClassVar[str] = "Simpson's paradox"
    complexity: ClassVar[str] = "Simpson's paradox"
    exercises: ClassVar[str] = "Adtributor nested-segment reversal check"
    demo_moment: ClassVar[str] = "Analyst view"

    WINDOW: ClassVar[tuple[dt.date, dt.date]] = (dt.date(2025, 4, 1), dt.date(2025, 7, 31))
    PREMIUM_PRICE_FLOOR: ClassVar[float] = 600.0
    """SKUs above this reference price count as premium for the mix shift."""

    def apply(self, frames: SourceFrames, context: ProjectionContext) -> SourceFrames:
        if "oms_orders" not in frames:
            return frames
        frame = frames["oms_orders"].copy()
        dates = pd.to_datetime(frame["order_date"]).dt.date
        inside = (dates >= self.WINDOW[0]) & (dates <= self.WINDOW[1])

        premium_skus = {
            sku.sku_id
            for sku in context.catalog.skus
            if sku.ref_price_inr >= self.PREMIUM_PRICE_FLOOR
        }
        is_premium = frame["product_sku"].astype(str).isin(premium_skus)

        # Discount deepens within BOTH segments (margin falls in each) while premium
        # volume grows (mix lifts the blend). The two effects cancel in the total.
        # Discount deepens within BOTH segments, so margin falls in each. Premium
        # volume then grows enough that the richer mix more than offsets it in the
        # blend, so the national number moves the OTHER WAY. Anything short of a sign
        # reversal is ordinary aggregation, not Simpson's paradox, and would let a
        # detector that only checks the total off the hook.
        frame.loc[inside, "unit_price_net"] = (frame.loc[inside, "unit_price_net"] * 0.972).round(2)
        lift = inside & is_premium
        frame.loc[lift, "units"] = np.ceil(frame.loc[lift, "units"] * 2.6).astype("int64")
        result = frames.copy()
        result["oms_orders"] = frame
        return result

    def detect(self, frames: SourceFrames, context: ProjectionContext) -> DefectEvidence:
        frame = frames["oms_orders"]
        costs = {sku.sku_id: sku.unit_cost_inr for sku in context.catalog.skus}
        premium_skus = {
            sku.sku_id
            for sku in context.catalog.skus
            if sku.ref_price_inr >= self.PREMIUM_PRICE_FLOOR
        }
        dates = pd.to_datetime(frame["order_date"]).dt.date
        inside = (dates >= self.WINDOW[0]) & (dates <= self.WINDOW[1])
        before = (dates >= self.WINDOW[0] - dt.timedelta(days=120)) & (dates < self.WINDOW[0])

        sku_ids = frame["product_sku"].astype(str)
        cost = sku_ids.map(costs).fillna(0.0)
        revenue = frame["units"] * frame["unit_price_net"]
        profit = frame["units"] * (frame["unit_price_net"] - cost)
        premium = sku_ids.isin(premium_skus)

        def margin(mask: pd.Series) -> float:
            total = float(revenue[mask].sum())
            return float(profit[mask].sum()) / total if total else 0.0

        national = margin(inside) - margin(before)
        within_premium = margin(inside & premium) - margin(before & premium)
        within_mass = margin(inside & ~premium) - margin(before & ~premium)
        # A genuine reversal: both segments fall, the total does not.
        reversed_sign = within_premium < 0 and within_mass < 0 and national >= 0
        return (
            self._found(
                f"national margin moves {national:+.4f} while premium moves "
                f"{within_premium:+.4f} and mass moves {within_mass:+.4f} - "
                f"both segments decline and the total does not",
                national=national,
                premium=within_premium,
                mass=within_mass,
            )
            if reversed_sign
            else self._missing(
                f"no reversal: national {national:+.4f}, premium {within_premium:+.4f}, "
                f"mass {within_mass:+.4f}",
                national=national,
                premium=within_premium,
                mass=within_mass,
            )
        )
