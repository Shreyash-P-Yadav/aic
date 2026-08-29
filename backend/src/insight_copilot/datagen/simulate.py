"""The simulator: one sequential day loop over vectorised cell arrays.

Layers L0-L3 are assembled here. The loop is sequential because the interesting
parts are *feedback*: replenishment responds to a forecast of demand, availability
censors demand, censored demand leaks to substitutes, and media budget responds to
last week's revenue. Precomputing those would be precomputing away the confounding
the whole analytical design exists to handle.

Everything inside a day is vectorised over the ~1,800 listed cells, so 1,096
iterations of small NumPy operations is the whole cost.

**Determinism.** Every stochastic input is drawn before the loop starts, addressed by
content key and indexed by day offset. The loop itself contains no randomness at all.
That is what makes "re-run without event E" differ from the factual run in exactly
one place — the overlay — and nowhere else.
"""

from __future__ import annotations

import numpy as np

from insight_copilot.datagen.decisions.assortment import Assortment, build_assortment
from insight_copilot.datagen.decisions.media import MediaPlan
from insight_copilot.datagen.decisions.pricing import PricePlan, build_price_plan, cover_discount
from insight_copilot.datagen.decisions.replenishment import (
    demand_forecast,
    order_quantity,
    order_up_to_level,
    sample_lead_time,
)
from insight_copilot.datagen.events.overlay import EventOverlay, NoEvents
from insight_copilot.datagen.latent import noise as noise_lib
from insight_copilot.datagen.latent.demand import latent_demand
from insight_copilot.datagen.outcomes.fulfilment import fulfil_day
from insight_copilot.datagen.outcomes.inventory import InventoryState
from insight_copilot.datagen.outcomes.returns import schedule_returns
from insight_copilot.datagen.panel import SimulationPanel
from insight_copilot.datagen.precompute import build_precomputed
from insight_copilot.datagen.state import Accumulators, Precomputed
from insight_copilot.datagen.world.calendar import Calendar
from insight_copilot.datagen.world.catalog import ProductCatalog
from insight_copilot.datagen.world.config import WorldConfig, load_world_config
from insight_copilot.datagen.world.geography import Geography
from insight_copilot.datagen.world.seeds import SeedBook
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

OPENING_STOCK_WEEKS = 5.0
"""Weeks of cover the warehouses start with, so the first review cycle is not a
cold start that would show up as a spurious level shift in the first fortnight."""

CANCELLATION_RATE = 0.011
"""Share of ordered units cancelled after the fact. Cancellations post-date their
orders, which is one of the OMS's known issues and a real cut-off problem."""

TRAILING_WINDOW = 28
"""Days of demand history the replenishment forecast averages over."""


class Simulator:
    """Builds the complete business reality for one world and one event overlay.

    Collaborators are injected rather than constructed internally: the counterfactual
    machinery in P3 reuses the *same* calendar, catalog, price plan and seed book and
    varies only the overlay, which is what keeps a counterfactual honest.
    """

    def __init__(
        self,
        config: WorldConfig,
        seeds: SeedBook,
        *,
        calendar: Calendar | None = None,
        catalog: ProductCatalog | None = None,
        assortment: Assortment | None = None,
        price_plan: PricePlan | None = None,
    ) -> None:
        self.config = config
        self.seeds = seeds
        self.calendar = calendar or Calendar(config, seeds)
        self.catalog = catalog or ProductCatalog(config, seeds)
        self.geography = Geography(config)
        self.assortment = assortment or build_assortment(config, self.catalog, seeds)
        self.price_plan = price_plan or build_price_plan(config, self.calendar, self.catalog, seeds)
        self.media = MediaPlan(config, self.calendar, seeds)

    @classmethod
    def from_defaults(cls, seed: int) -> Simulator:
        """Build a simulator over the shipped world config."""
        return cls(load_world_config(), SeedBook(seed))

    # =============================================================== run ======
    def run(self, overlay: EventOverlay | None = None) -> SimulationPanel:
        """Simulate the whole horizon under ``overlay``."""
        events = overlay or NoEvents()
        pre = build_precomputed(
            config=self.config,
            calendar=self.calendar,
            catalog=self.catalog,
            geography=self.geography,
            cells=self.assortment,
            price_plan=self.price_plan,
            seeds=self.seeds,
        )
        logger.debug(
            "datagen.simulate.start",
            days=self.calendar.n_days,
            cells=self.assortment.n_cells,
            overlay=events.describe(),
        )
        panel = self._loop(pre, events)
        logger.debug(
            "datagen.simulate.done",
            revenue_cr=round(float(panel.net_revenue_by_day().sum()) / 1e7, 1),
            fill_rate=round(float(np.nanmean(panel.national_fill_rate())), 4),
        )
        return panel

    # ============================================================== loop ======
    def _loop(self, pre: Precomputed, events: EventOverlay) -> SimulationPanel:
        """The sequential day loop. Contains no randomness of its own."""
        config, calendar, catalog = self.config, self.calendar, self.catalog
        cells = self.assortment
        n_days, n_cells = calendar.n_days, cells.n_cells
        n_skus = len(catalog.skus)
        n_warehouses = len(config.warehouse_ids)
        n_regions = len(config.region_ids)
        n_media = len(config.media.channels)

        out = Accumulators(n_cells, n_days, n_warehouses, n_skus, n_regions, n_media)
        inventory = InventoryState(
            n_warehouses,
            n_skus,
            n_days,
            opening=self._opening_stock(n_warehouses, n_skus),
        )
        home_row = np.array(
            [
                self.geography.warehouse_index(self.geography.home_warehouse_of_region[region])
                for region in config.region_ids
            ]
        )
        service = self.geography.service_matrix
        adstock_ref = self._adstock_reference(n_regions, n_media)
        media_elasticity = np.array([c.elasticity for c in config.media.channels])
        media_decay = np.array(
            [0.5 ** (1.0 / c.adstock_half_life_days) for c in config.media.channels]
        )
        media_carry = adstock_ref.copy()

        trailing = np.zeros((n_warehouses, n_skus, TRAILING_WINDOW), dtype=np.float64)
        substitution_carry = np.zeros(n_cells, dtype=np.float64)
        week_revenue: dict[str, float] = {}
        current_week = ""
        weekly_spend = np.zeros(n_media)
        daily_pacing = np.full((n_media, 7), 1.0 / 7.0)
        previous_week = ""

        for day in range(n_days):
            effects = events.effects_on(day)
            week = str(calendar.iso_week[day])
            if week != current_week:
                previous_week, current_week = current_week, week
                weekly_spend = self.media.spend_for_week(week, week_revenue.get(previous_week))
                daily_pacing = self.media.daily_share(week)

            # --- media: pace the week's budget, then advance the adstock state ----
            spend_today = weekly_spend * daily_pacing[:, calendar.day_of_week[day]]
            if effects.media_multiplier is not None:
                spend_today = spend_today * effects.media_multiplier
            regional_spend = np.outer(self.geography.region_weights, spend_today)
            media_carry = regional_spend + media_decay[None, :] * media_carry
            out.media_spend[:, :, day] = regional_spend
            out.media_adstock[:, :, day] = media_carry
            media_lift = np.exp(
                (
                    media_elasticity[None, :] * np.log(np.maximum(media_carry / adstock_ref, 1e-6))
                ).sum(axis=1)
            )

            # --- price: list price, planned promo, plus the overstock discount -----
            list_price = self.price_plan.list_price[cells.sku_index, cells.region_index, day]
            list_price = list_price * pre.channel_price_premium[cells.channel_index]
            depth = self.price_plan.promo_depth[cells.sku_index, cells.region_index, day]
            cover = inventory.days_cover(np.maximum(trailing.mean(axis=2), 1e-6))
            extra_discount = cover_discount(cover)[home_row[cells.region_index], cells.sku_index]
            total_depth = np.clip(depth + extra_discount, 0.0, 0.75)
            if effects.price_multiplier is not None:
                # A price change moves the *list* price and the realised price follows,
                # because that is what a price change is. Multiplying only the realised
                # price would let a rise push it above list, which is not a price rise —
                # it is a negative discount, and no order book can represent one.
                list_price = (
                    list_price * effects.price_multiplier[cells.sku_index, cells.region_index]
                )
            price = list_price * (1.0 - total_depth)

            # --- latent demand ------------------------------------------------------
            demand = latent_demand(
                pre=pre,
                cells=cells,
                day=day,
                price=price,
                depth=total_depth,
                media_lift=media_lift,
                festival_multiplier=calendar.festival_multiplier,
                competitor_index=self.price_plan.competitor_index,
                reference_price=catalog.ref_price,
                depth_choices=config.promo.depth_choices,
                lift_at_depth=config.promo.lift_at_depth,
                effects=effects,
            )
            demand = demand + substitution_carry
            if effects.bulk_units is not None:
                demand = (
                    demand
                    + effects.bulk_units[cells.sku_index, cells.region_index, cells.channel_index]
                )
            out.latent_demand[:, day] = demand

            # --- discretise: orders are whole units --------------------------------
            # Unbiased stochastic rounding, using uniforms drawn per cell before the
            # loop. Everything downstream — fulfilment, inventory, returns — then
            # works in whole units, as a real order book does.
            demand = noise_lib.stochastic_round(demand, pre.round_uniforms[:, day])

            # --- fulfilment ---------------------------------------------------------
            inventory.receive(day)
            served, ordered_by_dc, shipped_by_dc = fulfil_day(
                demand=demand,
                cells=cells,
                inventory=inventory,
                home_row=home_row,
                service=service,
                effects=effects,
            )
            availability = np.divide(served, demand, out=np.ones_like(demand), where=demand > 1e-9)
            units = served

            # --- book the day -------------------------------------------------------
            out.units[:, day] = units
            out.unit_price_net[:, day] = price
            out.list_price[:, day] = list_price
            out.availability[:, day] = availability
            out.promo_depth[:, day] = total_depth
            out.units_ordered[:, :, day] = ordered_by_dc
            out.units_shipped_ok[:, :, day] = shipped_by_dc

            cancelled = units * CANCELLATION_RATE
            out.cancelled_units[:, day] = cancelled
            schedule_returns(
                returned_units=out.returned_units,
                returns_value=out.returns_value,
                seeds=self.seeds,
                day=day,
                units=units - cancelled,
                price=price,
                rate=pre.return_rate[cells.category_index],
                lag_min=config.returns.lag_days.min,
                lag_max=config.returns.lag_days.max,
            )

            # --- substitution: censored demand comes back tomorrow on a substitute --
            substitution_carry = self._substitution(demand - served)

            # --- replenishment ------------------------------------------------------
            trailing[:, :, day % TRAILING_WINDOW] = ordered_by_dc
            if day % config.supply.review_period_days == 0:
                self._replenish(inventory, trailing, day)
            inventory.apply_shrinkage(self.seeds, day_index=day, rate=config.supply.shrinkage_rate)
            out.on_hand[:, :, day] = inventory.on_hand
            out.in_transit[:, :, day] = inventory.in_transit(day)

            revenue_today = float((units * price).sum())
            week_revenue[week] = week_revenue.get(week, 0.0) + revenue_today

        return out.to_panel(
            dates=calendar.dates,
            assortment=cells,
            weather_index=pre.weather,
            competitor_index=self.price_plan.competitor_index,
        )

    # ======================================================== components ======
    def _substitution(self, censored: np.ndarray) -> np.ndarray:
        """Redistribute part of unmet demand to substitutes in the same category/region.

        Arrives on the *next* day: a customer who cannot buy their SKU today either
        walks or comes back, and same-day perfect substitution would erase the
        revenue effect of a stockout entirely. The leak is what makes the mix term
        move during the outage scenario.
        """
        cells = self.assortment
        leak = self.config.supply.substitution_leak * censored
        if not leak.any():
            return np.zeros_like(censored)
        n_categories = len(self.config.categories)
        n_regions = len(self.config.regions)
        pool = np.zeros((n_categories, n_regions), dtype=np.float64)
        np.add.at(pool, (cells.category_index, cells.region_index), leak)
        weights = self._substitution_weights
        leaked: np.ndarray = pool[cells.category_index, cells.region_index] * weights
        return leaked

    @property
    def _substitution_weights(self) -> np.ndarray:
        """``(n_cells,)`` share of a category-region substitution pool each cell takes."""
        if not hasattr(self, "_sub_weights_cache"):
            cells = self.assortment
            size = self.catalog.base_units[cells.sku_index]
            totals = np.zeros((len(self.config.categories), len(self.config.regions)))
            np.add.at(totals, (cells.category_index, cells.region_index), size)
            denominator = totals[cells.category_index, cells.region_index]
            self._sub_weights_cache = np.divide(
                size, denominator, out=np.zeros_like(size), where=denominator > 0
            )
        weights: np.ndarray = self._sub_weights_cache
        return weights

    def _replenish(self, inventory: InventoryState, trailing: np.ndarray, day: int) -> None:
        """Place a periodic-review order-up-to replenishment at every DC."""
        for warehouse_row, warehouse in enumerate(self.config.warehouse_ids):
            forecast = demand_forecast(
                trailing[warehouse_row],
                self.seeds,
                config=self.config,
                warehouse=warehouse,
                day_index=day,
            )
            lead_time = sample_lead_time(
                self.seeds, self.config, warehouse=warehouse, day_index=day
            )
            target = order_up_to_level(forecast, config=self.config, lead_time_days=lead_time)
            quantity = order_quantity(
                inventory.on_hand[warehouse_row], inventory.in_transit(day)[warehouse_row], target
            )
            inventory.schedule_receipt(warehouse_row, quantity, day + lead_time)

    def _opening_stock(self, n_warehouses: int, n_skus: int) -> np.ndarray:
        """Weeks of cover at day zero, so the first review is not a cold start."""
        share = np.zeros((n_warehouses, n_skus), dtype=np.float64)
        for region_row, region in enumerate(self.config.region_ids):
            home = self.geography.warehouse_index(self.geography.home_warehouse_of_region[region])
            share[home] += self.catalog.base_units * self.geography.region_weights[region_row]
        return np.ceil(share * OPENING_STOCK_WEEKS * 7.0)

    def _adstock_reference(self, n_regions: int, n_media: int) -> np.ndarray:
        """``(n_regions, n_media)`` steady-state adstock at planned average spend.

        Normalising the adstock by its own steady state makes the media term exactly
        ``(A/A_ref)^beta`` — a constant-elasticity form, so the driver regression on
        ``log(y)`` recovers ``beta`` directly rather than something proportional to it.
        """
        config = self.config
        annual = config.company.target_annual_net_revenue_inr * (
            config.media.annual_spend_share_of_revenue
        )
        daily = annual / 365.25
        shares = np.array([c.budget_share for c in config.media.channels])
        decay = np.array([0.5 ** (1.0 / c.adstock_half_life_days) for c in config.media.channels])
        steady = daily * shares / (1.0 - decay)
        reference: np.ndarray = np.outer(self.geography.region_weights, steady)
        if reference.shape != (n_regions, n_media):
            raise ValueError("adstock reference shape disagrees with the configured world")
        return reference
