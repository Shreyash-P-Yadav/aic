"""The simulation's output: the complete, perfectly-known business reality (L3).

No source system sees this. Each of the eleven feeds in L4 is a lossy projection of
it, and the disagreements between those projections are where the reconciliation half
of the brief actually lives.

Everything here is stored on the flat cell axis (listed SKU x region x channel) by
day, and converted to long tables only on demand. Keeping the arrays rectangular is
what makes the windowed counterfactual a slice rather than a re-derivation.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

from insight_copilot.datagen.decisions.assortment import Assortment
from insight_copilot.datagen.world.catalog import ProductCatalog
from insight_copilot.datagen.world.config import WorldConfig


@dataclass(frozen=True)
class SimulationPanel:
    """Every quantity the simulation produced, on the cell x day grid."""

    dates: pd.DatetimeIndex
    assortment: Assortment

    latent_demand: np.ndarray
    """``(n_cells, n_days)`` demand before availability censoring — the L1 truth."""

    units: np.ndarray
    """``(n_cells, n_days)`` units actually sold, after censoring and substitution."""

    unit_price_net: np.ndarray
    """``(n_cells, n_days)`` realised selling price after discount."""

    list_price: np.ndarray
    """``(n_cells, n_days)`` price before discount."""

    availability: np.ndarray
    """``(n_cells, n_days)`` fraction of demand that could be served, in [0, 1]."""

    promo_depth: np.ndarray
    """``(n_cells, n_days)`` discount depth applied."""

    returns_value: np.ndarray
    """``(n_cells, n_days)`` value of returns *arriving* on this day, 7-21 days after
    the sale that generated them. The lag is real, so day-level revenue and returns
    do not net out within a day, which is one of the OMS-vs-ERP disagreements."""

    returned_units: np.ndarray
    """``(n_cells, n_days)`` units arriving back on this day."""

    cancelled_units: np.ndarray
    """``(n_cells, n_days)`` units cancelled after ordering."""

    units_ordered: np.ndarray
    """``(n_warehouses, n_skus, n_days)`` units requested of each DC."""

    units_shipped_ok: np.ndarray
    """``(n_warehouses, n_skus, n_days)`` units shipped complete and on time."""

    on_hand: np.ndarray
    """``(n_warehouses, n_skus, n_days)`` closing stock position."""

    in_transit: np.ndarray
    """``(n_warehouses, n_skus, n_days)`` units ordered and not yet received."""

    media_spend: np.ndarray
    """``(n_regions, n_media_channels, n_days)`` daily-paced media spend."""

    media_adstock: np.ndarray
    """``(n_regions, n_media_channels, n_days)`` the adstock state the demand saw."""

    weather_index: np.ndarray
    """``(n_regions, n_days)`` the composite weather driver."""

    competitor_index: np.ndarray
    """``(n_skus, n_regions, n_days)`` competitor price relative to our reference."""

    # ------------------------------------------------------------------ views --
    @property
    def n_days(self) -> int:
        """Length of the date axis."""
        return len(self.dates)

    def net_revenue_by_day(self) -> np.ndarray:
        """``(n_days,)`` national net revenue: gross less returns arriving that day."""
        revenue: np.ndarray = (self.units * self.unit_price_net).sum(
            axis=0
        ) - self.returns_value.sum(axis=0)
        return revenue

    def national_fill_rate(self) -> np.ndarray:
        """``(n_days,)`` units shipped complete over units ordered, across all DCs."""
        ordered = self.units_ordered.sum(axis=(0, 1))
        shipped = self.units_shipped_ok.sum(axis=(0, 1))
        rate: np.ndarray = np.divide(
            shipped, ordered, out=np.full_like(shipped, np.nan), where=ordered > 0
        )
        return rate

    def sales_frame(
        self, config: WorldConfig, catalog: ProductCatalog, *, drop_zero_rows: bool = True
    ) -> pd.DataFrame:
        """The daily sales fact at (date, sku, region, channel).

        Zero-sales rows are dropped by default, matching the contract's null policy
        ("no sales row = 0 revenue"). The calendar spine at silver is what makes the
        resulting gaps explicit rather than invisible.
        """
        n_cells, n_days = self.units.shape
        cell = np.repeat(np.arange(n_cells), n_days)
        day = np.tile(np.arange(n_days), n_cells)

        frame = pd.DataFrame(
            {
                "date": self.dates.to_numpy()[day],
                "product_sku": pd.Categorical.from_codes(
                    self.assortment.sku_index[cell], categories=pd.Index(catalog.sku_ids)
                ),
                "region": pd.Categorical.from_codes(
                    self.assortment.region_index[cell], categories=pd.Index(config.region_ids)
                ),
                "channel": pd.Categorical.from_codes(
                    self.assortment.channel_index[cell], categories=pd.Index(config.channel_ids)
                ),
                "units": self.units.ravel(),
                "unit_price_net": self.unit_price_net.ravel(),
                "list_price": self.list_price.ravel(),
                "returns_value": self.returns_value.ravel(),
                "returned_units": self.returned_units.ravel(),
                "cancelled_units": self.cancelled_units.ravel(),
                "latent_demand": self.latent_demand.ravel(),
                "availability": self.availability.ravel(),
                "promo_depth": self.promo_depth.ravel(),
            }
        )
        frame["unit_cost"] = catalog.unit_cost[self.assortment.sku_index[cell]]
        if drop_zero_rows:
            keep = (frame["units"] > 0) | (frame["returned_units"] > 0)
            frame = frame.loc[keep].reset_index(drop=True)
        return frame

    def fulfilment_frame(self, config: WorldConfig, catalog: ProductCatalog) -> pd.DataFrame:
        """The daily fulfilment fact at (date, warehouse, sku)."""
        n_warehouses, n_skus, n_days = self.units_ordered.shape
        warehouse = np.repeat(np.arange(n_warehouses), n_skus * n_days)
        sku = np.tile(np.repeat(np.arange(n_skus), n_days), n_warehouses)
        day = np.tile(np.arange(n_days), n_warehouses * n_skus)

        frame = pd.DataFrame(
            {
                "date": self.dates.to_numpy()[day],
                "warehouse": pd.Categorical.from_codes(
                    warehouse, categories=pd.Index(config.warehouse_ids)
                ),
                "product_sku": pd.Categorical.from_codes(sku, categories=pd.Index(catalog.sku_ids)),
                "units_ordered": self.units_ordered.ravel(),
                "units_shipped_ok": self.units_shipped_ok.ravel(),
                "on_hand_units": self.on_hand.ravel(),
                "in_transit_units": self.in_transit.ravel(),
            }
        )
        frame["units_short"] = frame["units_ordered"] - frame["units_shipped_ok"]
        return frame.loc[frame["units_ordered"] > 0].reset_index(drop=True)

    def media_frame(self, config: WorldConfig, iso_week: np.ndarray) -> pd.DataFrame:
        """Weekly media spend at (iso_week, region, media channel)."""
        n_regions, n_channels, n_days = self.media_spend.shape
        region = np.repeat(np.arange(n_regions), n_channels * n_days)
        channel = np.tile(np.repeat(np.arange(n_channels), n_days), n_regions)
        day = np.tile(np.arange(n_days), n_regions * n_channels)
        frame = pd.DataFrame(
            {
                "iso_week": iso_week[day],
                "region": pd.Categorical.from_codes(region, categories=pd.Index(config.region_ids)),
                "media_channel": pd.Categorical.from_codes(
                    channel, categories=pd.Index([c.id for c in config.media.channels])
                ),
                "spend_inr": self.media_spend.ravel(),
            }
        )
        grouped = frame.groupby(["iso_week", "region", "media_channel"], observed=True)
        return grouped["spend_inr"].sum().reset_index()

    def checksum(self) -> str:
        """A stable digest of every numeric array, for the determinism tests.

        Hashing the raw bytes rather than a rounded summary is deliberate: the
        determinism guarantee is bit-level, and a tolerance would hide exactly the
        RNG-position bug this is here to catch.
        """
        from hashlib import sha256

        digest = sha256()
        for name in sorted(
            (
                "latent_demand",
                "units",
                "unit_price_net",
                "list_price",
                "availability",
                "promo_depth",
                "returns_value",
                "returned_units",
                "cancelled_units",
                "units_ordered",
                "units_shipped_ok",
                "on_hand",
                "in_transit",
                "media_spend",
                "media_adstock",
                "weather_index",
                "competitor_index",
            )
        ):
            array: np.ndarray = getattr(self, name)
            digest.update(name.encode())
            digest.update(np.ascontiguousarray(array, dtype=np.float64).tobytes())
        return digest.hexdigest()

    def window(self, start: dt.date, end: dt.date) -> slice:
        """Day-axis slice for a date range, clipped to the panel."""
        first = self.dates[0].date()
        lo = max(0, (start - first).days)
        hi = min(self.n_days, (end - first).days + 1)
        return slice(lo, max(lo, hi))
