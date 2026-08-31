"""Regions, distribution centres and their cross-serving relationships.

The cross-serving map is what makes a warehouse outage a *partial* loss rather than
a total one: when DC-North fails, DC-West can cover part of North's demand at a
service penalty. That partial recovery is why the outage's effect on revenue is
smaller than its effect on fill rate, and separating those two is exactly what the
attribution ladder has to get right.
"""

from __future__ import annotations

from functools import cached_property

import numpy as np

from insight_copilot.datagen.world.config import WorldConfig
from insight_copilot.errors import SimulationError

CROSS_SERVE_PENALTY = 0.35
"""Fraction of demand a non-home DC can pick up. Cross-docking costs time and units:
covering another region's shortfall is possible but never free or complete."""


class Geography:
    """The region / warehouse / channel axes and the maps between them."""

    def __init__(self, config: WorldConfig) -> None:
        self._config = config

    @property
    def regions(self) -> list[str]:
        """Region ids in canonical (configuration) order."""
        return self._config.region_ids

    @property
    def warehouses(self) -> list[str]:
        """Warehouse ids in canonical order."""
        return self._config.warehouse_ids

    @property
    def channels(self) -> list[str]:
        """Channel ids in canonical order."""
        return self._config.channel_ids

    def region_index(self, region: str) -> int:
        """Position of a region on the region axis."""
        try:
            return self.regions.index(region)
        except ValueError as exc:
            raise SimulationError(f"unknown region {region!r}") from exc

    def warehouse_index(self, warehouse: str) -> int:
        """Position of a warehouse on the warehouse axis."""
        try:
            return self.warehouses.index(warehouse)
        except ValueError as exc:
            raise SimulationError(f"unknown warehouse {warehouse!r}") from exc

    @cached_property
    def home_warehouse_of_region(self) -> dict[str, str]:
        """Each region's primary DC — where its demand is served from by default."""
        mapping = {warehouse.home_region: warehouse.id for warehouse in self._config.warehouses}
        missing = set(self.regions) - set(mapping)
        for region in missing:
            # A region with no home DC is served by whichever DC lists it first.
            for warehouse in self._config.warehouses:
                if region in warehouse.serves:
                    mapping[region] = warehouse.id
                    break
        unserved = set(self.regions) - set(mapping)
        if unserved:
            raise SimulationError(f"regions with no serving DC: {sorted(unserved)}")
        return mapping

    @cached_property
    def service_matrix(self) -> np.ndarray:
        """``(n_warehouses, n_regions)`` capability weights.

        1.0 where the DC is the region's home, ``CROSS_SERVE_PENALTY`` where it can
        cross-serve, 0 otherwise. Rows are *not* normalised: this is capability, not
        an allocation, and the allocation is decided per day by what is on hand.
        """
        matrix = np.zeros((len(self.warehouses), len(self.regions)), dtype=np.float64)
        for warehouse in self._config.warehouses:
            row = self.warehouse_index(warehouse.id)
            for region in warehouse.serves:
                column = self.region_index(region)
                matrix[row, column] = (
                    1.0 if region == warehouse.home_region else CROSS_SERVE_PENALTY
                )
        return matrix

    @cached_property
    def region_weights(self) -> np.ndarray:
        """``(n_regions,)`` population weights, normalised to sum to 1."""
        weights = np.array([region.population_weight for region in self._config.regions])
        normalised: np.ndarray = weights / weights.sum()
        return normalised

    @cached_property
    def channel_weights(self) -> np.ndarray:
        """``(n_channels,)`` revenue shares, normalised to sum to 1."""
        weights = np.array([channel.revenue_share for channel in self._config.channels])
        normalised: np.ndarray = weights / weights.sum()
        return normalised

    @cached_property
    def dow_shape(self) -> np.ndarray:
        """``(n_channels, 7)`` day-of-week multipliers, each row normalised to mean 1.

        The national weekly cycle times each channel's deviation from it. Both are
        mean-1 normalised, so the day-of-week factor never silently changes a
        channel's annual level — the shape is about *distribution within a week*.

        WHY a shared national cycle and not channel patterns alone: modern trade is
        weekday-heavy and quick-commerce is weekend-heavy, and at national scale they
        very nearly cancel. A business with no weekly structure at all is not what a
        consumer company looks like, and it would leave the detector's period
        discovery with nothing to find at lag 7.
        """
        national = np.array(self._config.demand.national_dow_shape, dtype=np.float64)
        national = national / national.mean()
        raw = np.array([channel.dow_shape for channel in self._config.channels])
        deviation = raw / raw.mean(axis=1, keepdims=True)
        combined = deviation * national[None, :]
        normalised: np.ndarray = combined / combined.mean(axis=1, keepdims=True)
        return normalised

    @cached_property
    def dow_volatility(self) -> np.ndarray:
        """``(n_channels, 7)`` volatility multipliers, mean-1 normalised.

        Separate from the level shape: quick-commerce is not merely *bigger* at the
        weekend, it is *noisier*, which is one of the two planted heteroscedasticity
        sources.
        """
        raw = np.array([channel.dow_vol for channel in self._config.channels])
        normalised: np.ndarray = raw / raw.mean(axis=1, keepdims=True)
        return normalised
