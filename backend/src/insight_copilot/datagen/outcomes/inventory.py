"""The inventory state machine: on-hand, in-transit, receipts, shrinkage.

Kept separate from the demand and fulfilment logic so that "what does the warehouse
have" is answerable independently of "what did we sell". That separation is what lets
the inventory *snapshot* projection disagree with the *implied* position by 1-4%: the
snapshot is taken at a moment, the implied position is reconstructed from flows, and
shrinkage sits between them.
"""

from __future__ import annotations

import numpy as np

from insight_copilot.datagen.world.seeds import SeedBook


class InventoryState:
    """On-hand and scheduled receipts for every (warehouse, SKU).

    Receipts are held as a ``(n_warehouses, n_skus, horizon)`` schedule rather than a
    queue: a windowed counterfactual can then start mid-history by replaying the
    schedule, and there is no hidden ordering to get wrong.
    """

    def __init__(self, n_warehouses: int, n_skus: int, n_days: int, *, opening: np.ndarray):
        if opening.shape != (n_warehouses, n_skus):
            raise ValueError(f"opening stock must be ({n_warehouses}, {n_skus})")
        self._on_hand = opening.astype(np.float64).copy()
        self._receipts = np.zeros((n_warehouses, n_skus, n_days + 60), dtype=np.float64)
        self._n_days = n_days

    @property
    def on_hand(self) -> np.ndarray:
        """``(n_warehouses, n_skus)`` units physically present right now."""
        return self._on_hand

    def in_transit(self, day_index: int) -> np.ndarray:
        """``(n_warehouses, n_skus)`` units ordered and not yet received."""
        pending: np.ndarray = self._receipts[:, :, day_index + 1 :].sum(axis=2)
        return pending

    def schedule_receipt(self, warehouse_row: int, quantity: np.ndarray, arrival_day: int) -> None:
        """Book an inbound delivery. Arrivals beyond the horizon are simply lost."""
        if arrival_day < self._receipts.shape[2]:
            self._receipts[warehouse_row, :, arrival_day] += quantity

    def receive(self, day_index: int) -> np.ndarray:
        """Take today's deliveries into stock and return what arrived."""
        arriving = self._receipts[:, :, day_index].copy()
        self._on_hand += arriving
        return arriving

    def pick(self, warehouse_row: int, units: np.ndarray) -> np.ndarray:
        """Remove units, never below zero. Returns what was actually picked."""
        available = self._on_hand[warehouse_row]
        picked: np.ndarray = np.minimum(units, available)
        self._on_hand[warehouse_row] = available - picked
        return picked

    def apply_shrinkage(self, seeds: SeedBook, *, day_index: int, rate: float) -> np.ndarray:
        """Lose a small random fraction of stock: damage, miscount, theft.

        This is the wedge between the snapshot and the implied position. Without it,
        the two reconcile exactly and the "inventory snapshot is not a ledger"
        limitation would be a claim rather than a measurable disagreement.
        """
        if rate <= 0.0:
            return np.zeros_like(self._on_hand)
        draws = seeds("shrinkage", day_index).random(self._on_hand.shape)
        lost = np.floor(self._on_hand * rate * draws * 2.0)
        self._on_hand -= lost
        return lost

    def days_cover(self, daily_demand: np.ndarray) -> np.ndarray:
        """``(n_warehouses, n_skus)`` weeks-of-cover input for the discount decision."""
        cover: np.ndarray = self._on_hand / np.maximum(daily_demand, 1e-6)
        return cover
