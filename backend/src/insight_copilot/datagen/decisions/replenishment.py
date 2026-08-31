"""Replenishment policy, driven by a forecast that is wrong in realistic ways.

A periodic-review order-up-to policy. The order-up-to level is built from a *forecast*
of demand over the protection interval (lead time plus review period) plus safety
stock — and that forecast is deliberately imperfect: biased slightly high, and noisy.

WHY the forecast matters more than the policy: a perfect forecast produces a fill
rate that only ever falls when an event forces it, which makes stockouts a pure
function of the event ledger. An imperfect forecast produces a *baseline* stockout
rate with its own texture, so the outage in Scenario A has to be separated from
ordinary supply noise rather than being the only thing that ever happens.
"""

from __future__ import annotations

import numpy as np

from insight_copilot.datagen.world.config import WorldConfig
from insight_copilot.datagen.world.seeds import SeedBook

FORECAST_TRAILING_DAYS = 28
"""Four weeks of history, which is what a planner in this business would actually
use: long enough to cover a full weekly cycle, short enough to track a trend."""

MIN_ORDER_UNITS = 6.0
"""Below this the order is not worth raising; it accumulates to the next review.
Without a minimum, slow movers generate a trickle of one-unit orders and their
inventory never runs down, which would erase the intermittency we planted."""


def demand_forecast(
    trailing_demand: np.ndarray,
    seeds: SeedBook,
    *,
    config: WorldConfig,
    warehouse: str,
    day_index: int,
) -> np.ndarray:
    """``(n_skus,)`` forecast daily demand over the protection interval.

    Trailing mean, tilted by ``forecast_bias`` and perturbed by a multiplicative
    error with coefficient of variation ``forecast_noise_cv``. Both are drawn by
    content key on (warehouse, review day), so a counterfactual re-run sees the same
    forecast error and only the demand differs.
    """
    supply = config.supply
    mean_demand = trailing_demand.mean(axis=-1) if trailing_demand.ndim > 1 else trailing_demand
    error = np.exp(
        supply.forecast_noise_cv
        * seeds("replenishment_forecast", warehouse, day_index).standard_normal(
            mean_demand.shape[0]
        )
        - 0.5 * supply.forecast_noise_cv**2
    )
    forecast: np.ndarray = np.maximum(mean_demand * supply.forecast_bias * error, 0.0)
    return forecast


def order_up_to_level(
    forecast_daily: np.ndarray, *, config: WorldConfig, lead_time_days: float
) -> np.ndarray:
    """``(n_skus,)`` target position: protection-interval demand plus safety stock."""
    supply = config.supply
    protection_days = lead_time_days + supply.review_period_days
    safety_days = supply.safety_stock_weeks * 7.0
    return forecast_daily * (protection_days + safety_days)


def order_quantity(on_hand: np.ndarray, in_transit: np.ndarray, target: np.ndarray) -> np.ndarray:
    """``(n_skus,)`` whole units to order this review. Pure arithmetic, no state.

    Rounded up: a purchase order is placed in cases, never in fractions, and keeping
    inventory integral is what lets the fulfilment layer ship whole units.
    """
    gap = target - (on_hand + in_transit)
    return np.where(gap >= MIN_ORDER_UNITS, np.ceil(gap), 0.0)


def _lead_time_from(rng: np.random.Generator, mean: float = 9.0, sd: float = 2.5) -> int:
    sigma = np.sqrt(np.log1p((sd / mean) ** 2))
    mu = np.log(mean) - 0.5 * sigma**2
    return int(np.clip(np.round(rng.lognormal(mu, sigma)), 1, 45))


def sample_lead_time(
    seeds: SeedBook, config: WorldConfig, *, warehouse: str, day_index: int
) -> int:
    """Lead time using the configured mean and standard deviation."""
    lead = config.supply.lead_time_days
    return _lead_time_from(
        seeds("replenishment_lead", warehouse, day_index), mean=lead.mean, sd=lead.sd
    )
