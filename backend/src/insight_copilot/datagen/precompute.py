"""Assembling the deterministic inputs the day loop reads.

Every stochastic input to the simulation is drawn here, before the loop begins. That
is the structural guarantee behind determinism: if a value is not in
:class:`Precomputed` and is not derived from the loop's own state, it does not exist,
so "re-run without event E" can differ from the factual run in exactly one place.
"""

from __future__ import annotations

import numpy as np

from insight_copilot.datagen.decisions.assortment import Assortment
from insight_copilot.datagen.decisions.pricing import PricePlan
from insight_copilot.datagen.latent import noise as noise_lib
from insight_copilot.datagen.latent import seasonality
from insight_copilot.datagen.state import Precomputed
from insight_copilot.datagen.world.calendar import Calendar
from insight_copilot.datagen.world.catalog import ProductCatalog
from insight_copilot.datagen.world.config import WorldConfig
from insight_copilot.datagen.world.geography import Geography
from insight_copilot.datagen.world.seeds import SeedBook


def build_precomputed(
    *,
    config: WorldConfig,
    calendar: Calendar,
    catalog: ProductCatalog,
    geography: Geography,
    cells: Assortment,
    price_plan: PricePlan,
    seeds: SeedBook,
) -> Precomputed:
    """Every deterministic array the loop reads. No randomness after this point."""
    n_days = calendar.n_days

    annual = seasonality.annual_shape(config, calendar)
    dow = seasonality.day_of_week_shape(geography.dow_shape, calendar.day_of_week)
    dow_vol = seasonality.day_of_week_shape(geography.dow_volatility, calendar.day_of_week)
    weather = seasonality.weather_index(calendar)

    # The company shock's volatility scale uses a revenue-weighted day-of-week
    # volatility, since the shock is national and not channel-specific.
    national_dow_vol = geography.channel_weights @ dow_vol
    scale = noise_lib.volatility_scale(
        promo_active=price_plan.national_promo_intensity
        > price_plan.national_promo_intensity.mean(),
        in_festival_window=calendar.in_festival_window,
        dow_volatility=national_dow_vol,
        promo_multiplier=config.noise.promo_vol_multiplier,
        festival_multiplier=config.noise.festival_vol_multiplier,
    )
    shock = noise_lib.company_shock(
        seeds,
        n_days,
        phi=config.noise.company_ar1_phi,
        sigma0=config.noise.company_sigma0,
        scale=scale,
    )

    sigma = noise_lib.idiosyncratic_sigma(
        catalog.base_units,
        sigma_large=config.noise.idiosyncratic_sigma_large,
        sigma_small=config.noise.idiosyncratic_sigma_small,
        threshold=config.noise.small_cell_units_threshold,
    )
    cell_noise = np.empty((cells.n_cells, n_days), dtype=np.float64)
    round_uniforms = np.empty((cells.n_cells, n_days), dtype=np.float64)
    for row, (sku_id, region, channel) in enumerate(cells.keys):
        cell_sigma = sigma[cells.sku_index[row]]
        draws = seeds("demand_noise", sku_id, region, channel).standard_normal(n_days)
        cell_noise[row] = cell_sigma * draws - 0.5 * cell_sigma**2
        round_uniforms[row] = seeds("unit_rounding", sku_id, region, channel).random(n_days)

    # Constant-elasticity price and competitor terms, per cell.
    elasticity = np.array([c.own_price_elasticity for c in config.categories])
    cross_elasticity = np.array([c.cross_price_elasticity for c in config.categories])

    # A SKU's national demand is split across the region x channel cells it is
    # actually listed in. Normalising by the SKU's OWN listed weight (rather than
    # by a global listing ratio) keeps every SKU's national total equal to its
    # catalog base, whatever assortment it happens to have drawn - so changing the
    # listing grid changes the MIX, not the size of the company.
    cell_weight = (
        geography.region_weights[cells.region_index]
        * geography.channel_weights[cells.channel_index]
    )
    listed_weight = np.zeros(len(catalog.skus), dtype=np.float64)
    np.add.at(listed_weight, cells.sku_index, cell_weight)
    share = np.divide(
        cell_weight,
        listed_weight[cells.sku_index],
        out=np.zeros_like(cell_weight),
        where=listed_weight[cells.sku_index] > 0,
    )
    base_level = catalog.base_units[cells.sku_index] * share * config.demand_scale

    return Precomputed(
        annual=annual,
        dow=dow,
        weather=weather,
        company_shock=shock,
        cell_noise=cell_noise,
        elasticity=elasticity,
        cross_elasticity=cross_elasticity,
        base_level=base_level,
        round_uniforms=round_uniforms,
        lifecycle=catalog.lifecycle_trend(n_days, config.horizon.start),
        active=catalog.active_mask(n_days, config.horizon.start),
        channel_price_premium=np.array([c.price_premium for c in config.channels]),
        return_rate=np.array([c.return_rate for c in config.categories]),
    )
