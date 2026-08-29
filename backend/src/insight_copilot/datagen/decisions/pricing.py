"""Pricing and promotion policy.

Prices are not exogenous. A list price responds to competitor moves with partial
pass-through, and a promo depth deepens when inventory cover is high — both of which
create the confounding a real attribution problem has to survive.

**Design note on ordering.** The promo *schedule* (which SKU-region-weeks run a
promo, and for how long) is exogenous: it is set by the promo calendar from festival
proximity and a base weekly hazard, and it does not depend on inventory. Only the
promo *depth* responds to cover, inside the day loop. That split is deliberate: the
heteroscedastic noise scale needs the promo mask before the simulation starts, and a
schedule that depended on same-day inventory would make the noise scale
self-referential. Depth carries the endogeneity; the schedule carries the calendar.

One planted regime break lives here: a permanent list-price revision of about 6% part
way through the window, which is the changepoint case and the window the conformal
calibration must exclude.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np

from insight_copilot.datagen.world.calendar import Calendar
from insight_copilot.datagen.world.catalog import ProductCatalog
from insight_copilot.datagen.world.config import WorldConfig
from insight_copilot.datagen.world.seeds import SeedBook

COMPETITOR_PASS_THROUGH = 0.25
"""Fraction of a competitor's relative price move we follow. Partial, because
matching a competitor exactly would make the two price series collinear and the
cross-price elasticity unidentifiable — a modelling artefact, not a business fact."""

REGIME_BREAK_DATE = dt.date(2025, 7, 1)
"""P22: a permanent price-list revision. Excluded from conformal calibration windows."""

REGIME_BREAK_SIZE = 0.06
"""About +6% on list, across the board. Large enough for a changepoint detector to
find, small enough that it is not simply an outlier."""

COVER_DISCOUNT_MAX = 0.08
"""Deepest extra discount from overstock alone, before any planned promotion."""

COVER_DISCOUNT_TRIGGER_WEEKS = 8.0
"""Weeks of cover above which the commercial team starts discounting to clear."""


@dataclass(frozen=True)
class PricePlan:
    """Precomputed, inventory-independent parts of the pricing decision."""

    list_price: np.ndarray
    """``(n_skus, n_regions, n_days)`` list price before any promotion."""

    promo_depth: np.ndarray
    """``(n_skus, n_regions, n_days)`` planned discount depth in [0, 1)."""

    promo_active: np.ndarray
    """``(n_skus, n_regions, n_days)`` boolean mask of planned promotions."""

    competitor_index: np.ndarray
    """``(n_skus, n_regions, n_days)`` competitor price relative to our reference."""

    national_promo_intensity: np.ndarray
    """``(n_days,)`` share of the catalog on promotion — drives the volatility scale."""


def build_price_plan(
    config: WorldConfig, calendar: Calendar, catalog: ProductCatalog, seeds: SeedBook
) -> PricePlan:
    """Build every price and promo path that does not depend on inventory."""
    n_regions = len(config.regions)
    n_days = calendar.n_days

    competitor_index = _competitor_index(config, catalog, seeds, n_regions, n_days)
    promo_depth, promo_active = _promo_schedule(config, calendar, catalog, seeds, n_regions)
    list_price = _list_price(config, calendar, catalog, competitor_index)

    return PricePlan(
        list_price=list_price,
        promo_depth=promo_depth,
        promo_active=promo_active,
        competitor_index=competitor_index,
        national_promo_intensity=promo_active.mean(axis=(0, 1)),
    )


def _competitor_index(
    config: WorldConfig,
    catalog: ProductCatalog,
    seeds: SeedBook,
    n_regions: int,
    n_days: int,
) -> np.ndarray:
    """``(n_skus, n_regions, n_days)`` AR(1) competitor price index around 1.0.

    Persistent rather than white: competitors reprice in campaigns, not daily coin
    flips, and a white-noise competitor series would be trivially separable from our
    own slow-moving price path.
    """
    phi = config.competitor.price_index_ar1
    sigma = config.competitor.price_index_sigma
    index = np.empty((len(catalog.skus), n_regions, n_days), dtype=np.float64)
    for sku_row, sku in enumerate(catalog.skus):
        for region_row, region in enumerate(config.regions):
            innovations = sigma * seeds("competitor_price", sku.sku_id, region.id).standard_normal(
                n_days
            )
            level = 0.0
            series = np.empty(n_days, dtype=np.float64)
            for day in range(n_days):
                level = phi * level + innovations[day]
                series[day] = level
            index[sku_row, region_row] = np.exp(series)
    return index


def _promo_schedule(
    config: WorldConfig,
    calendar: Calendar,
    catalog: ProductCatalog,
    seeds: SeedBook,
    n_regions: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Promotion windows and depths, drawn per (sku, region, week) by content key."""
    n_skus = len(catalog.skus)
    n_days = calendar.n_days
    depth = np.zeros((n_skus, n_regions, n_days), dtype=np.float64)

    # A week is "festive" if any day in it sits inside a festival window: promotions
    # cluster there, which is one of the two planted heteroscedasticity sources.
    week_ids = calendar.iso_week
    unique_weeks, week_index = np.unique(week_ids, return_inverse=True)
    festive_week = np.zeros(len(unique_weeks), dtype=bool)
    np.logical_or.at(festive_week, week_index, calendar.in_festival_window)

    depth_choices = np.array(config.promo.depth_choices)
    durations = np.array(config.promo.duration_days)

    for sku_row, sku in enumerate(catalog.skus):
        for region_row, region in enumerate(config.regions):
            rng = seeds("promo_plan", sku.sku_id, region.id)
            hazards = rng.random(len(unique_weeks))
            picks = rng.integers(0, len(depth_choices), size=len(unique_weeks))
            spans = rng.integers(0, len(durations), size=len(unique_weeks))
            for week in range(len(unique_weeks)):
                threshold = (
                    config.promo.festival_weekly_probability
                    if festive_week[week]
                    else config.promo.base_weekly_probability
                )
                if hazards[week] >= threshold:
                    continue
                start = int(np.searchsorted(week_index, week))
                end = min(n_days, start + int(durations[spans[week]]))
                depth[sku_row, region_row, start:end] = depth_choices[picks[week]]
    return depth, depth > 0.0


def _list_price(
    config: WorldConfig,
    calendar: Calendar,
    catalog: ProductCatalog,
    competitor_index: np.ndarray,
) -> np.ndarray:
    """``(n_skus, n_regions, n_days)`` list price.

    Reference price, times a regional premium, times partial competitor pass-through,
    times the step at the planted regime break.
    """
    n_days = calendar.n_days
    reference = catalog.ref_price[:, None, None]
    pass_through = competitor_index**COMPETITOR_PASS_THROUGH

    break_offset = (REGIME_BREAK_DATE - config.horizon.start).days
    regime = np.ones(n_days, dtype=np.float64)
    if 0 <= break_offset < n_days:
        regime[break_offset:] = 1.0 + REGIME_BREAK_SIZE

    # Regional price differences are small and structural (freight, local taxes).
    regional = np.array([1.0 + 0.012 * (index - 2) for index in range(len(config.regions))])
    price: np.ndarray = reference * regional[None, :, None] * pass_through * regime[None, None, :]
    return price


def cover_discount(days_cover: np.ndarray) -> np.ndarray:
    """Extra discount driven by overstock. Pure function of weeks of cover.

    This is the endogenous half of pricing: a decision that responds to the state of
    the business, so price and demand are jointly determined and a naive regression
    of volume on price is biased. The engine's job is to handle that, not to be
    handed a clean experiment.
    """
    weeks_cover = days_cover / 7.0
    excess = np.clip(weeks_cover - COVER_DISCOUNT_TRIGGER_WEEKS, 0.0, None)
    return COVER_DISCOUNT_MAX * (1.0 - np.exp(-excess / 4.0))
