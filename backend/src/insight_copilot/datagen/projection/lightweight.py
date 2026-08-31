"""The four lightweight sources: PIM, inventory snapshots, weather, holidays.

Lightweight means the projection is close to a straight read of the truth. Each still
carries the one limitation that makes it realistic:

* **PIM** updates late, so a new SKU transacts before the master knows about it and
  lands in the `UNKNOWN` bucket. That is how Scenario C's launch appears without a
  category for its first few days.
* **Inventory** is a *snapshot*, not a ledger. Intra-day movement is unreconstructable,
  which is why the snapshot and the implied position disagree by a few percent.
* **Weather** is gridded to a region centroid — a real approximation, not a defect.
* **Holidays** are static and come from the `holidays` package, so movable festivals
  are correct rather than hard-coded.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from insight_copilot.datagen.projection.base import ProjectionContext, SourceProjector

PIM_UPDATE_LAG_DAYS = 9
"""How long the product master takes to learn about a new SKU. Long enough that a
launch transacts as UNKNOWN for over a week, which is the mechanism behind P13."""


class PIMProjector(SourceProjector):
    """The product master, as a slowly-changing dimension with late updates."""

    def project(self, context: ProjectionContext) -> pd.DataFrame:
        rows: list[dict[str, object]] = []
        for sku in context.catalog.skus:
            # A launched SKU enters the master LATE. Its first master row therefore
            # starts after it has already been selling, and everything before that is
            # an UNKNOWN category at silver.
            known_from = (
                sku.launch_date + dt.timedelta(days=PIM_UPDATE_LAG_DAYS)
                if sku.is_in_window_launch
                else context.config.horizon.start
            )
            rows.append(
                {
                    "product_sku": sku.sku_id,
                    "valid_from": known_from,
                    "product_name": sku.name,
                    "category": sku.category,
                    "pack_size_ml": sku.pack_size_ml,
                    "unit_cost": sku.unit_cost_inr,
                    "list_price": sku.ref_price_inr,
                    "launch_date": sku.launch_date,
                    "discontinued_date": sku.discontinued_date,
                }
            )
        return pd.DataFrame(rows)


class InventorySnapshotProjector(SourceProjector):
    """Daily closing stock at warehouse x SKU, as a snapshot rather than a ledger."""

    def project(self, context: ProjectionContext) -> pd.DataFrame:
        panel = context.panel
        config = context.config
        catalog = context.catalog
        calendar = context.calendar

        n_warehouses, n_skus, n_days = panel.on_hand.shape
        warehouse = np.repeat(np.arange(n_warehouses), n_skus * n_days)
        sku = np.tile(np.repeat(np.arange(n_skus), n_days), n_warehouses)
        day = np.tile(np.arange(n_days), n_warehouses * n_skus)

        daily_demand = panel.units_ordered.mean(axis=2, keepdims=True)
        cover = np.divide(
            panel.on_hand,
            np.maximum(daily_demand, 1e-6),
            out=np.zeros_like(panel.on_hand),
            where=daily_demand > 1e-6,
        )
        frame = pd.DataFrame(
            {
                "snapshot_date": calendar.dates.to_numpy()[day],
                "warehouse": pd.Categorical.from_codes(
                    warehouse, categories=pd.Index(config.warehouse_ids)
                ),
                "product_sku": pd.Categorical.from_codes(sku, categories=pd.Index(catalog.sku_ids)),
                "on_hand_units": panel.on_hand.ravel().astype("int64"),
                "in_transit_units": panel.in_transit.ravel().astype("int64"),
                "days_cover": np.clip(cover.ravel(), 0.0, 400.0).round(2),
            }
        )
        return frame.loc[frame["on_hand_units"] > 0].reset_index(drop=True)


class WeatherProjector(SourceProjector):
    """Region x day weather, gridded to a centroid."""

    def project(self, context: ProjectionContext) -> pd.DataFrame:
        calendar = context.calendar
        config = context.config
        seeds = context.simulator.seeds

        frames = []
        for row, region in enumerate(config.regions):
            monsoon = calendar.monsoon_intensity[row]
            heat = calendar.heat_intensity[row]
            noise = seeds("weather_noise", region.id).normal(0.0, 1.0, calendar.n_days)
            frames.append(
                pd.DataFrame(
                    {
                        "observation_date": calendar.dates,
                        "region": region.id,
                        "temp_max_c": np.clip(
                            22.0 + 16.0 * heat - 4.0 * monsoon + 1.8 * noise, -5.0, 50.0
                        ).round(1),
                        "rainfall_mm": np.clip(
                            monsoon * 34.0 * np.abs(noise) - 1.0, 0.0, 560.0
                        ).round(1),
                        "humidity_pct": np.clip(
                            42.0 + 40.0 * monsoon + 3.0 * noise, 5.0, 100.0
                        ).round(1),
                        "monsoon_active": monsoon > 0.5,
                    }
                )
            )
        return pd.concat(frames, ignore_index=True)


class HolidayCalendarProjector(SourceProjector):
    """Festival dates and their demand relevance, from the `holidays` package."""

    def project(self, context: ProjectionContext) -> pd.DataFrame:
        config = context.config
        rows: list[dict[str, object]] = []
        for window in context.calendar.festival_windows:
            shape = config.festivals.demand_relevant[window.name]
            for region in window.regions:
                rows.append(
                    {
                        "holiday_date": window.peak,
                        "region": region,
                        "holiday_name": window.name,
                        "demand_relevant": True,
                        "pre_build_days": shape.pre_build_days,
                        "post_lull_days": shape.post_lull_days,
                    }
                )
        return pd.DataFrame(rows)
