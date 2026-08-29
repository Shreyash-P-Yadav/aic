"""Serving demand from distribution centres, with cross-serving at a penalty.

A warehouse outage is modelled as a **cap on picking**, not as a stockout: the units
are physically there, they cannot move. That distinction matters analytically —
cross-serving recovers part of the loss, which is why an outage's effect on revenue
is materially smaller than its effect on the affected DC's fill rate, and separating
those two is exactly what the attribution ladder has to get right.

Pure function: it mutates only the inventory it is handed, and returns everything it
computed rather than writing into shared state.
"""

from __future__ import annotations

import numpy as np

from insight_copilot.datagen.decisions.assortment import Assortment
from insight_copilot.datagen.events.overlay import DayEffects
from insight_copilot.datagen.outcomes.inventory import InventoryState
from insight_copilot.datagen.world.geography import CROSS_SERVE_PENALTY


def fulfil_day(
    *,
    demand: np.ndarray,
    cells: Assortment,
    inventory: InventoryState,
    home_row: np.ndarray,
    service: np.ndarray,
    effects: DayEffects,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Serve one day's demand. Returns (units sold, units ordered, units shipped).

    ``units_ordered`` and ``units_shipped_ok`` are per (warehouse, SKU), which is the
    grain the fill-rate KPI is defined at. Cross-served units are booked as ordered
    *and* shipped at the covering DC, so the failing DC's fill rate falls while the
    customer's order is still partly met — which is what actually happens.
    """
    n_warehouses, n_skus = inventory.on_hand.shape
    cap = effects.availability_cap

    region_demand = np.zeros((len(home_row), n_skus), dtype=np.float64)
    np.add.at(region_demand, (cells.region_index, cells.sku_index), demand)

    ordered = np.zeros((n_warehouses, n_skus), dtype=np.float64)
    shipped = np.zeros((n_warehouses, n_skus), dtype=np.float64)
    served_region = np.zeros_like(region_demand)

    for region in range(len(home_row)):
        wanted = region_demand[region]
        if not wanted.any():
            continue
        home = int(home_row[region])
        ordered[home] += wanted
        # The cap is on THROUGHPUT: how much of today's demand this site can move.
        # Stock is untouched by an outage, so capping a fraction of on-hand would be
        # inert at any normal level of cover.
        servable = wanted if cap is None else np.floor(wanted * cap[home])
        picked = inventory.pick(home, np.minimum(servable, inventory.on_hand[home]))
        shipped[home] += picked
        shortfall = wanted - picked

        for other in range(n_warehouses):
            if other == home or service[other, region] <= 0.0 or not shortfall.any():
                continue
            # Whole units transfer between DCs, so the inventory ledger stays
            # integral rather than accumulating fractional drift.
            allowed = np.floor(shortfall * CROSS_SERVE_PENALTY)
            if cap is not None:
                allowed = np.floor(allowed * cap[other])
            transferred = inventory.pick(other, np.minimum(allowed, inventory.on_hand[other]))
            ordered[other] += allowed
            shipped[other] += transferred
            shortfall = shortfall - transferred
        served_region[region] = wanted - shortfall

    ratio = np.divide(
        served_region,
        region_demand,
        out=np.ones_like(region_demand),
        where=region_demand > 1e-9,
    )
    # Whole units ship. Flooring only bites when the region was short, and it keeps
    # the sold quantity integral all the way through to the fact table.
    served: np.ndarray = np.floor(demand * ratio[cells.region_index, cells.sku_index])
    return served, ordered, shipped
