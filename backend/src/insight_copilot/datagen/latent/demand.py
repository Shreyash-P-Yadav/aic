"""The multiplicative demand equation (DataLayer 4.1).

A pure function: arrays in, an array out. No I/O, no globals, no hidden state — which
is what makes it testable in isolation and what makes the determinism guarantee
checkable by inspection.

Multiplicative, not additive: a weekend dip is -20% of level, not a fixed number of
units. That is why the engine models ``log(y)``, and the data has to be built the same
way or the modelling choice looks arbitrary.
"""

from __future__ import annotations

import numpy as np

from insight_copilot.datagen.decisions.assortment import Assortment
from insight_copilot.datagen.events.overlay import DayEffects
from insight_copilot.datagen.latent import seasonality
from insight_copilot.datagen.state import Precomputed


def residual_promo_lift(
    depth: np.ndarray,
    own_elasticity: np.ndarray,
    depth_choices: list[float],
    lift_at_depth: list[float],
) -> np.ndarray:
    """The NON-price part of a promotion's lift.

    Promo lift is configured as the TOTAL effect at a given depth. The price term
    already delivers ``(1-d)**elasticity`` of it, so applying the configured lift as
    well would double-count — and, worse, would make the price elasticity
    unidentifiable from the promo dummy, because the two would carry the same
    information. What is left over is display, bundling and shelf visibility.
    """
    total = seasonality.promo_lift(depth, depth_choices, lift_at_depth)
    price_component = np.power(np.maximum(1.0 - depth, 1e-6), own_elasticity)
    residual: np.ndarray = np.maximum(total / np.maximum(price_component, 1e-6), 1.0)
    return residual


def latent_demand(
    *,
    pre: Precomputed,
    cells: Assortment,
    day: int,
    price: np.ndarray,
    depth: np.ndarray,
    media_lift: np.ndarray,
    festival_multiplier: np.ndarray,
    competitor_index: np.ndarray,
    reference_price: np.ndarray,
    depth_choices: list[float],
    lift_at_depth: list[float],
    effects: DayEffects,
) -> np.ndarray:
    """``(n_cells,)`` uncensored demand for one day.

    Availability is deliberately NOT applied here: this is the L1 latent truth, the
    demand that existed before supply censored it. The gap between this and units
    sold is what makes a stockout's revenue cost measurable.
    """
    own_elasticity = pre.elasticity[cells.category_index]
    cross_elasticity = pre.cross_elasticity[cells.category_index]
    price_ratio = price / reference_price[cells.sku_index]
    competitor = competitor_index[cells.sku_index, cells.region_index, day]

    demand = np.asarray(
        pre.base_level
        * pre.lifecycle[cells.sku_index, day]
        * pre.dow[cells.channel_index, day]
        * pre.annual[cells.category_index, cells.region_index, day]
        * festival_multiplier[cells.region_index, day]
        * np.power(np.maximum(price_ratio, 1e-6), own_elasticity)
        * np.power(
            np.maximum(competitor, 1e-6),
            cross_elasticity,
        )
        * media_lift[cells.region_index]
        * residual_promo_lift(depth, own_elasticity, depth_choices, lift_at_depth)
        * np.exp(pre.company_shock[day] + pre.cell_noise[:, day])
        * pre.active[cells.sku_index, day],
        dtype=np.float64,
    )
    if effects.demand_multiplier is not None:
        demand = (
            demand
            * effects.demand_multiplier[cells.sku_index, cells.region_index, cells.channel_index]
        )
    clipped: np.ndarray = np.maximum(demand, 0.0)
    return clipped
