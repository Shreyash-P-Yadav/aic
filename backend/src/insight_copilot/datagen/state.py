"""Deterministic loop inputs and pre-allocated loop outputs.

Split out of ``simulate.py`` so the day loop reads as a sequence of steps rather than
as a sequence of steps interleaved with array bookkeeping.

``Precomputed`` is the contract that makes determinism checkable: it holds *every*
stochastic input, all of it drawn before the loop begins. If a value is not in here
and is not derived from the loop's own state, it does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from insight_copilot.datagen.decisions.assortment import Assortment
from insight_copilot.datagen.panel import SimulationPanel


@dataclass(frozen=True)
class Precomputed:
    """Deterministic inputs to the day loop. Assembled once, read many times.

    A frozen dataclass rather than a loose namespace: every field is typed, so a
    renamed array is a type error rather than an AttributeError three seconds into a
    simulation.
    """

    annual: np.ndarray
    """``(n_categories, n_regions, n_days)`` annual demand shape."""

    dow: np.ndarray
    """``(n_channels, n_days)`` day-of-week level multiplier."""

    weather: np.ndarray
    """``(n_regions, n_days)`` the composite weather driver."""

    company_shock: np.ndarray
    """``(n_days,)`` the company-wide AR(1) shock, in log space."""

    cell_noise: np.ndarray
    """``(n_cells, n_days)`` per-cell idiosyncratic noise, in log space."""

    round_uniforms: np.ndarray
    """``(n_cells, n_days)`` uniforms for unbiased stochastic rounding to whole units."""

    elasticity: np.ndarray
    """``(n_categories,)`` own-price elasticity."""

    cross_elasticity: np.ndarray
    """``(n_categories,)`` cross-price elasticity against the competitor index."""

    base_level: np.ndarray
    """``(n_cells,)`` steady-state daily demand for each listed cell."""

    lifecycle: np.ndarray
    """``(n_skus, n_days)`` slow lifecycle drift, launch curve included."""

    active: np.ndarray
    """``(n_skus, n_days)`` sellability: after launch, before discontinuation."""

    channel_price_premium: np.ndarray
    """``(n_channels,)`` structural price difference between routes to market."""

    return_rate: np.ndarray
    """``(n_categories,)`` share of sold units that come back."""


class Accumulators:
    """Pre-allocated output arrays, filled in place by the day loop."""

    def __init__(
        self,
        n_cells: int,
        n_days: int,
        n_warehouses: int,
        n_skus: int,
        n_regions: int,
        n_media: int,
    ) -> None:
        cell_shape = (n_cells, n_days)
        self.latent_demand = np.zeros(cell_shape)
        self.units = np.zeros(cell_shape)
        self.unit_price_net = np.zeros(cell_shape)
        self.list_price = np.zeros(cell_shape)
        self.availability = np.ones(cell_shape)
        self.promo_depth = np.zeros(cell_shape)
        self.returns_value = np.zeros(cell_shape)
        self.returned_units = np.zeros(cell_shape)
        self.cancelled_units = np.zeros(cell_shape)
        self.units_ordered = np.zeros((n_warehouses, n_skus, n_days))
        self.units_shipped_ok = np.zeros((n_warehouses, n_skus, n_days))
        self.on_hand = np.zeros((n_warehouses, n_skus, n_days))
        self.in_transit = np.zeros((n_warehouses, n_skus, n_days))
        self.media_spend = np.zeros((n_regions, n_media, n_days))
        self.media_adstock = np.zeros((n_regions, n_media, n_days))

    def to_panel(
        self,
        *,
        dates: pd.DatetimeIndex,
        assortment: Assortment,
        weather_index: np.ndarray,
        competitor_index: np.ndarray,
    ) -> SimulationPanel:
        """Freeze the accumulators into the immutable output panel."""
        return SimulationPanel(
            dates=dates,
            assortment=assortment,
            weather_index=weather_index,
            competitor_index=competitor_index,
            latent_demand=self.latent_demand,
            units=self.units,
            unit_price_net=self.unit_price_net,
            list_price=self.list_price,
            availability=self.availability,
            promo_depth=self.promo_depth,
            returns_value=self.returns_value,
            returned_units=self.returned_units,
            cancelled_units=self.cancelled_units,
            units_ordered=self.units_ordered,
            units_shipped_ok=self.units_shipped_ok,
            on_hand=self.on_hand,
            in_transit=self.in_transit,
            media_spend=self.media_spend,
            media_adstock=self.media_adstock,
        )
