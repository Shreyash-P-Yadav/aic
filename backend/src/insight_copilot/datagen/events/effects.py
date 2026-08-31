"""Turning ledger events into the per-day effects the simulator applies.

This is the only translation from "an event happened" to "the world was different".
Keeping it in one place is what makes a counterfactual trustworthy: dropping an event
from the ledger removes exactly its effect and touches nothing else.

Effects are cached per day. A typical day has no events; a scenario day has three.
Rebuilding the arrays on every access would dominate the day loop.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache

import numpy as np

from insight_copilot.datagen.decisions.assortment import Assortment
from insight_copilot.datagen.events.models import Event
from insight_copilot.datagen.events.overlay import EMPTY_DAY, DayEffects, EventOverlay
from insight_copilot.datagen.world.catalog import ProductCatalog
from insight_copilot.datagen.world.config import WorldConfig


class LedgerOverlay(EventOverlay):
    """Applies a set of events to the simulation, day by day.

    WHY it takes an explicit event list rather than reading a ledger: the Shapley
    computation builds overlays for every *subset* of an interacting group, and a
    subset is just a shorter list. Nothing else about the run changes.
    """

    def __init__(
        self,
        events: list[Event],
        *,
        config: WorldConfig,
        catalog: ProductCatalog,
        cells: Assortment,
        horizon_start: dt.date,
    ) -> None:
        self._events = list(events)
        self._config = config
        self._catalog = catalog
        self._cells = cells
        self._start = horizon_start
        self._n_skus = len(catalog.skus)
        self._n_regions = len(config.region_ids)
        self._n_channels = len(config.channel_ids)
        self._n_warehouses = len(config.warehouse_ids)
        self._n_media = len(config.media.channels)
        self._by_id = {event.event_id: event for event in self._events}
        self._by_day = self._index_by_day()

    # ------------------------------------------------------------------- api --
    def effects_on(self, day_index: int) -> DayEffects:
        """Combined effects of every event in force on this day."""
        active = self._by_day.get(day_index)
        if not active:
            return EMPTY_DAY
        return self._build(active)

    def describe(self) -> str:
        """Name the overlay for the run log."""
        if not self._events:
            return "empty ledger"
        return f"{len(self._events)} event(s)"

    @property
    def events(self) -> list[Event]:
        """The events this overlay applies, in ledger order."""
        return list(self._events)

    def without(self, event_ids: set[str]) -> LedgerOverlay:
        """A sibling overlay with some events removed — the counterfactual world."""
        return LedgerOverlay(
            [event for event in self._events if event.event_id not in event_ids],
            config=self._config,
            catalog=self._catalog,
            cells=self._cells,
            horizon_start=self._start,
        )

    # --------------------------------------------------------------- indexing --
    def _index_by_day(self) -> dict[int, tuple[str, ...]]:
        """Map day offset -> ids of the events in force.

        Ids rather than events because the per-day effect arrays are cached on this
        key, and a pydantic model carrying list fields is not hashable.
        """
        index: dict[int, list[str]] = {}
        for event in self._events:
            first = (event.window.start - self._start).days
            last = (event.window.end - self._start).days
            for day in range(first, last + 1):
                if day >= 0:
                    index.setdefault(day, []).append(event.event_id)
        return {day: tuple(ids) for day, ids in index.items()}

    # ---------------------------------------------------------------- masks ---
    def _sku_mask(self, event: Event) -> np.ndarray:
        """``(n_skus,)`` boolean: is this SKU in scope?"""
        scope = event.scope
        if not scope.skus and not scope.categories:
            return np.ones(self._n_skus, dtype=bool)
        mask = np.zeros(self._n_skus, dtype=bool)
        if scope.skus:
            wanted = set(scope.skus)
            for row, sku in enumerate(self._catalog.skus):
                if sku.sku_id in wanted:
                    mask[row] = True
        if scope.categories:
            wanted_categories = set(scope.categories)
            for row, sku in enumerate(self._catalog.skus):
                if sku.category in wanted_categories:
                    mask[row] = True
        return mask

    def _axis_mask(self, members: list[str], universe: list[str]) -> np.ndarray:
        """``(n,)`` boolean over one dimension; empty scope means every member."""
        if not members:
            return np.ones(len(universe), dtype=bool)
        wanted = set(members)
        return np.array([member in wanted for member in universe], dtype=bool)

    # ---------------------------------------------------------------- build ---
    @lru_cache(maxsize=512)  # noqa: B019 - bounded, and discarded with the overlay
    def _build(self, event_ids: tuple[str, ...]) -> DayEffects:
        """Assemble one day's arrays from the events in force.

        Cached on the exact tuple of event ids, so a scenario window of thirty
        identical days builds its arrays once. The cache is bounded and lives with the
        overlay, which is itself discarded after a run.
        """
        events = tuple(self._by_id[event_id] for event_id in event_ids)
        availability: np.ndarray | None = None
        price: np.ndarray | None = None
        media: np.ndarray | None = None
        demand: np.ndarray | None = None
        bulk: np.ndarray | None = None

        for event in events:
            sku_mask = self._sku_mask(event)
            region_mask = self._axis_mask(event.scope.regions, self._config.region_ids)
            channel_mask = self._axis_mask(event.scope.channels, self._config.channel_ids)
            magnitude = event.magnitude

            if magnitude.kind == "outage":
                warehouse_mask = self._axis_mask(event.scope.warehouses, self._config.warehouse_ids)
                if availability is None:
                    availability = np.ones((self._n_warehouses, self._n_skus))
                cap = np.where(
                    warehouse_mask[:, None] & sku_mask[None, :], magnitude.pick_capacity, 1.0
                )
                availability = np.minimum(availability, cap)

            elif magnitude.kind == "price_change":
                if price is None:
                    price = np.ones((self._n_skus, self._n_regions))
                price = price * np.where(
                    sku_mask[:, None] & region_mask[None, :], magnitude.price_multiplier, 1.0
                )

            elif magnitude.kind == "media_shift":
                media_mask = self._axis_mask(
                    event.scope.media_channels, [c.id for c in self._config.media.channels]
                )
                if media is None:
                    media = np.ones(self._n_media)
                media = media * np.where(media_mask, magnitude.spend_multiplier, 1.0)

            elif magnitude.kind == "demand_shock":
                if demand is None:
                    demand = np.ones((self._n_skus, self._n_regions, self._n_channels))
                selector = (
                    sku_mask[:, None, None]
                    & region_mask[None, :, None]
                    & channel_mask[None, None, :]
                )
                demand = demand * np.where(selector, magnitude.demand_multiplier, 1.0)

            elif magnitude.kind == "bulk_order":
                if bulk is None:
                    bulk = np.zeros((self._n_skus, self._n_regions, self._n_channels))
                selector = (
                    sku_mask[:, None, None]
                    & region_mask[None, :, None]
                    & channel_mask[None, None, :]
                )
                # The order is split evenly across the cells it names, so scoping it
                # to one SKU-region-channel gives the whole order to that cell.
                share = magnitude.units / max(int(selector.sum()), 1)
                bulk = bulk + np.where(selector, share, 0.0)

        return DayEffects(
            availability_cap=availability,
            price_multiplier=price,
            media_multiplier=media,
            demand_multiplier=demand,
            bulk_units=bulk,
        )
