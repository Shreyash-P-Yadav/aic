"""Assortment: which SKUs are listed in which region and channel.

Not every SKU sells everywhere. Modern trade carries a narrower range than a
marketplace; a premium serum is not listed in every region. Modelling the listing
decision does three things at once:

* It brings the fact table to a realistic density (~1,050 selling rows a day rather
  than a dense 3,000-cell grid), which is what the volume estimate in the design
  assumes.
* It makes the dimensional attribution search a genuine *search* — segments have
  ragged coverage, so a naive "biggest absolute drop" heuristic picks the wrong slice.
* It creates honest missing-ness. A SKU-region pair with no listing has no rows at
  all, which is different from a listing with zero sales, and the calendar spine at
  silver has to make that distinction explicit.

Listing probability rises with SKU size: the top sellers are listed nearly
everywhere, the tail is not. Every draw is addressed by (sku, region, channel), so
adding a SKU never re-rolls another SKU's listings.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from insight_copilot.datagen.world.catalog import ProductCatalog
from insight_copilot.datagen.world.config import WorldConfig
from insight_copilot.datagen.world.seeds import SeedBook

LISTING_FLOOR = 0.30
"""Listing probability for the smallest SKU in a category."""

LISTING_CEILING = 0.94
"""Listing probability for the largest. Never 1.0: even a hero SKU misses a channel."""

CHANNEL_BREADTH = {
    # Marketplaces list almost anything; modern trade fights for shelf space.
    "marketplace": 1.12,
    "d2c_web": 1.05,
    "quick_commerce": 0.92,
    "modern_trade": 0.72,
}


@dataclass(frozen=True)
class Assortment:
    """The listed (SKU, region, channel) cells, flattened to a single axis.

    The simulator works on this flat cell axis rather than a dense 3-D grid: it is
    an order of magnitude less arithmetic per day, and it makes every per-cell noise
    vector exactly as long as it needs to be.
    """

    sku_index: np.ndarray
    """``(n_cells,)`` position on the SKU axis."""

    region_index: np.ndarray
    """``(n_cells,)`` position on the region axis."""

    channel_index: np.ndarray
    """``(n_cells,)`` position on the channel axis."""

    category_index: np.ndarray
    """``(n_cells,)`` position on the category axis, derived from the SKU."""

    keys: list[tuple[str, str, str]]
    """``(n_cells,)`` (sku_id, region, channel) — the content keys for per-cell draws."""

    @property
    def n_cells(self) -> int:
        """How many listed cells the simulation carries."""
        return len(self.keys)


def build_assortment(config: WorldConfig, catalog: ProductCatalog, seeds: SeedBook) -> Assortment:
    """Decide the listing grid and flatten it to the cell axis."""
    sizes = catalog.base_units
    # Rank within the whole catalog, so listing breadth tracks commercial importance
    # rather than category-relative size.
    rank = np.argsort(np.argsort(sizes)) / max(len(sizes) - 1, 1)
    listing_probability = LISTING_FLOOR + (LISTING_CEILING - LISTING_FLOOR) * rank

    sku_rows: list[int] = []
    region_rows: list[int] = []
    channel_rows: list[int] = []
    keys: list[tuple[str, str, str]] = []

    for sku_row, sku in enumerate(catalog.skus):
        for region_row, region in enumerate(config.regions):
            for channel_row, channel in enumerate(config.channels):
                breadth = CHANNEL_BREADTH.get(channel.id, 1.0)
                threshold = min(listing_probability[sku_row] * breadth, 0.99)
                draw = float(seeds("assortment", sku.sku_id, region.id, channel.id).random())
                if draw >= threshold:
                    continue
                sku_rows.append(sku_row)
                region_rows.append(region_row)
                channel_rows.append(channel_row)
                keys.append((sku.sku_id, region.id, channel.id))

    sku_index = np.array(sku_rows, dtype=np.int64)
    return Assortment(
        sku_index=sku_index,
        region_index=np.array(region_rows, dtype=np.int64),
        channel_index=np.array(channel_rows, dtype=np.int64),
        category_index=catalog.category_of_sku[sku_index],
        keys=keys,
    )
