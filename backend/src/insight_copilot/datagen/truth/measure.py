"""Measuring the difference between a factual and a counterfactual world.

Kept separate from the machinery that *produces* counterfactual panels, because
"what changed" is a question with several right answers — national revenue, revenue
in the affected region, units, fill rate — and the ledger records more than one.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np

from insight_copilot.datagen.decisions.assortment import Assortment
from insight_copilot.datagen.events.models import Event, EventScope
from insight_copilot.datagen.panel import SimulationPanel
from insight_copilot.datagen.world.catalog import ProductCatalog
from insight_copilot.datagen.world.config import WorldConfig

MEASUREMENT_TAIL_DAYS = 21
"""Days past an event's end over which its effect is still accumulated.

Adstock and inventory both carry an event's influence beyond its window. Measuring
only inside the window would attribute a media cut's tail to nothing at all.
"""


@dataclass(frozen=True)
class EffectMeasurement:
    """One event's measured causal contribution over its measurement window."""

    event_id: str
    window_start: dt.date
    window_end: dt.date
    factual_revenue: float
    counterfactual_revenue: float
    revenue_delta: float
    revenue_delta_pct: float
    scoped_delta_pct: float
    """The same effect measured only over the cells the event actually touches.

    This, not the national percentage, is what determines whether the event is
    *detectable*. An event confined to Haircare in the North moves about 5% of the
    company, so a 25% hit inside its own scope is barely over 1% nationally — and the
    engine scans KPI x segment, so it sees the 25%. Recording only the national
    number would make the calibration corpus look like 440 immaterial events.
    """

    scoped_factual_revenue: float
    scoped_counterfactual_revenue: float
    units_delta: float
    top_region: str | None
    top_region_share: float
    top_category: str | None
    top_category_share: float

    @property
    def is_material(self) -> bool:
        """Material inside its own scope — which is where the engine would see it."""
        return abs(self.scoped_delta_pct) >= 2.0


def measurement_window(event: Event, horizon_start: dt.date, n_days: int) -> slice:
    """The day slice over which an event's effect is accumulated."""
    first = max(0, (event.window.start - horizon_start).days)
    last = min(n_days, (event.window.end - horizon_start).days + MEASUREMENT_TAIL_DAYS + 1)
    return slice(first, max(first, last))


def scope_mask(
    scope: EventScope, cells: Assortment, config: WorldConfig, catalog: ProductCatalog
) -> np.ndarray:
    """``(n_cells,)`` boolean: which listed cells does this scope touch?

    An empty member list means "every member" on that dimension, matching the scope
    semantics everywhere else. Warehouses are resolved to the regions they serve,
    since the fact table has no warehouse column.
    """
    mask = np.ones(cells.n_cells, dtype=bool)
    if scope.regions:
        wanted = {config.region_ids.index(region) for region in scope.regions}
        mask &= np.isin(cells.region_index, list(wanted))
    if scope.warehouses:
        served = {
            region
            for warehouse in config.warehouses
            if warehouse.id in scope.warehouses
            for region in warehouse.serves
        }
        wanted = {config.region_ids.index(region) for region in served}
        mask &= np.isin(cells.region_index, list(wanted))
    if scope.categories:
        wanted = {config.category_ids.index(category) for category in scope.categories}
        mask &= np.isin(cells.category_index, list(wanted))
    if scope.channels:
        wanted = {config.channel_ids.index(channel) for channel in scope.channels}
        mask &= np.isin(cells.channel_index, list(wanted))
    if scope.skus:
        positions = {
            index for index, sku in enumerate(catalog.skus) if sku.sku_id in set(scope.skus)
        }
        mask &= np.isin(cells.sku_index, list(positions))
    return mask


def measure_effect(
    *,
    event: Event,
    factual: SimulationPanel,
    counterfactual: SimulationPanel,
    cells: Assortment,
    config: WorldConfig,
    catalog: ProductCatalog,
    horizon_start: dt.date,
) -> EffectMeasurement:
    """Difference the two worlds over the event's measurement window.

    Sign convention: ``revenue_delta`` is factual minus counterfactual, so a harmful
    event is negative. That matches how a business states an impact ("the outage cost
    us Rs 49 lakh") and how the engine reports a gap.
    """
    window = measurement_window(event, horizon_start, factual.n_days)

    factual_cell_revenue = (factual.units[:, window] * factual.unit_price_net[:, window]).sum(
        axis=1
    ) - factual.returns_value[:, window].sum(axis=1)
    counter_cell_revenue = (
        counterfactual.units[:, window] * counterfactual.unit_price_net[:, window]
    ).sum(axis=1) - counterfactual.returns_value[:, window].sum(axis=1)
    delta_by_cell = factual_cell_revenue - counter_cell_revenue

    factual_total = float(factual_cell_revenue.sum())
    counter_total = float(counter_cell_revenue.sum())
    delta = factual_total - counter_total

    top_region, region_share = _top_member(
        delta_by_cell, cells.region_index, config.region_ids, delta
    )
    top_category, category_share = _top_member(
        delta_by_cell, cells.category_index, config.category_ids, delta
    )
    units_delta = float(factual.units[:, window].sum() - counterfactual.units[:, window].sum())

    inside = scope_mask(event.scope, cells, config, catalog)
    scoped_factual = float(factual_cell_revenue[inside].sum())
    scoped_counter = float(counter_cell_revenue[inside].sum())

    return EffectMeasurement(
        event_id=event.event_id,
        window_start=horizon_start + dt.timedelta(days=window.start),
        window_end=horizon_start + dt.timedelta(days=window.stop - 1),
        factual_revenue=factual_total,
        counterfactual_revenue=counter_total,
        revenue_delta=delta,
        revenue_delta_pct=100.0 * delta / counter_total if counter_total else 0.0,
        scoped_delta_pct=(
            100.0 * (scoped_factual - scoped_counter) / scoped_counter if scoped_counter else 0.0
        ),
        scoped_factual_revenue=scoped_factual,
        scoped_counterfactual_revenue=scoped_counter,
        units_delta=units_delta,
        top_region=top_region,
        top_region_share=region_share,
        top_category=top_category,
        top_category_share=category_share,
    )


def _top_member(
    delta_by_cell: np.ndarray, index: np.ndarray, members: list[str], total: float
) -> tuple[str | None, float]:
    """Which member of a dimension carried most of the effect, and what share.

    This is the *true* segment the Adtributor is scored against. Reporting the share
    as well as the name matters: a diffuse event has no true top segment, and the
    calibration corpus needs those cases to spread the attribution-stability signal.
    """
    if total == 0.0:
        return None, 0.0
    totals = np.zeros(len(members), dtype=np.float64)
    np.add.at(totals, index, delta_by_cell)
    position = int(np.argmax(np.abs(totals)))
    return members[position], float(totals[position] / total)
