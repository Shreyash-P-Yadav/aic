"""The product catalog: 150 active SKUs across six categories, ~180 lifetime.

Three properties matter downstream:

* **Three SKUs launch inside the window**, one of them 18 days before the demo's
  "today". That is Scenario C — the sparse-history case where the engine must show
  restraint rather than fire on a day-18 dip.
* **Some SKUs are discontinued mid-history**, so the product master is a genuinely
  slowly-changing dimension rather than a static lookup.
* **A handful of SKUs are intermittent** — slow movers with many zero days. At least
  one exceeds 40% zero days, which is the Croston case in the adaptation matrix.

Every per-SKU attribute is drawn by content key, so adding a SKU to the catalog
does not perturb any existing SKU's parameters.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from functools import cached_property

import numpy as np
import pandas as pd

from insight_copilot.datagen.world.config import Launch, WorldConfig
from insight_copilot.datagen.world.seeds import SeedBook

_DISCONTINUED_FRACTION = 0.18
"""Share of lifetime SKUs retired during the window — ~180 lifetime for 150 active."""

_LIFECYCLE_TREND_SD = 0.00035
"""Per-day log-growth SD. Over 1,096 days this spreads SKU lifecycles by roughly
+/-40% end to end: some products grow, some decay, most drift."""

_LAUNCH_CURVE_HALF_LIFE_DAYS = 21.0
"""Launch promos and novelty decay with about a three-week half-life. The pooled
launch curve the sparse-history baseline borrows is this shape."""

_LAUNCH_PEAK_MULTIPLIER = 2.4
"""Day-1 velocity relative to the SKU's eventual steady state."""


@dataclass(frozen=True)
class Sku:
    """One product. ``base_units`` is its steady-state national daily demand."""

    sku_id: str
    name: str
    category: str
    base_units: float
    ref_price_inr: float
    unit_cost_inr: float
    pack_size_ml: int
    launch_date: dt.date
    discontinued_date: dt.date | None
    is_intermittent: bool
    is_in_window_launch: bool


class ProductCatalog:
    """The SKU master and the per-SKU arrays the demand layer consumes."""

    def __init__(self, config: WorldConfig, seeds: SeedBook) -> None:
        self._config = config
        self._seeds = seeds

    # ------------------------------------------------------------------ skus --
    @cached_property
    def skus(self) -> list[Sku]:
        """Every SKU, active and discontinued, in a stable order."""
        config = self._config
        horizon = config.horizon
        launches_by_category: dict[str, list[Launch]] = {}
        for launch in config.launches:
            launches_by_category.setdefault(launch.category, []).append(launch)

        skus: list[Sku] = []
        for category in config.categories:
            # Category revenue share divided across its SKUs, then spread by a
            # lognormal so a few SKUs carry most of the volume, as they really do.
            rng = self._seeds("sku_sizes", category.id)
            sizes = rng.lognormal(mean=0.0, sigma=0.85, size=category.sku_count)
            sizes = sizes / sizes.sum()
            category_units = (
                config.company.target_annual_net_revenue_inr
                * category.revenue_share
                / 365.25
                / float(np.mean(category.ref_price_inr))
            )
            in_window = launches_by_category.get(category.id, [])

            for position in range(category.sku_count):
                sku_id = f"SKU-{len(skus) + 1:04d}"
                seed_key = ("sku_attrs", sku_id)
                attrs = self._seeds(*seed_key)
                price_low, price_high = category.ref_price_inr
                ref_price = float(attrs.uniform(price_low, price_high))
                base_units = float(sizes[position] * category_units)

                launch_date = horizon.start
                is_in_window_launch = False
                if in_window and position == 0:
                    launch = in_window.pop(0)
                    launch_date = launch.launch_date
                    is_in_window_launch = True
                    base_units *= launch.velocity_ratio

                discontinued = None
                if not is_in_window_launch and attrs.random() < _DISCONTINUED_FRACTION:
                    # Retire somewhere in the middle two-thirds of the window.
                    offset = int(attrs.integers(horizon.n_days // 6, horizon.n_days * 5 // 6))
                    discontinued = horizon.start + dt.timedelta(days=offset)

                skus.append(
                    Sku(
                        sku_id=sku_id,
                        name=self._name_for(sku_id, category.id, is_in_window_launch),
                        category=category.id,
                        base_units=base_units,
                        ref_price_inr=round(ref_price, 2),
                        unit_cost_inr=round(ref_price * (1.0 - category.gross_margin), 2),
                        pack_size_ml=int(attrs.choice([50, 100, 150, 200, 250, 400, 500])),
                        launch_date=launch_date,
                        discontinued_date=discontinued,
                        is_intermittent=False,
                        is_in_window_launch=is_in_window_launch,
                    )
                )
        return self._mark_intermittent(skus)

    def _mark_intermittent(self, skus: list[Sku]) -> list[Sku]:
        """Make the N smallest continuing SKUs genuinely slow-moving.

        WHY pick the smallest rather than tag arbitrary SKUs: intermittency has to be
        a *consequence* of low volume, so that the near-Poisson counting noise the
        latent layer applies actually produces long runs of zero days. Forcing a
        high-volume SKU to be intermittent would produce zeros that no demand model
        could justify, and the Croston case in the adaptation matrix would be a
        label rather than a fact.
        """
        wanted = self._config.noise.intermittent_sku_count
        eligible = sorted(
            (sku for sku in skus if not sku.is_in_window_launch and sku.discontinued_date is None),
            key=lambda sku: sku.base_units,
        )
        # A hard volume cap on top of "smallest": at these levels a day with no
        # order at all is the common case rather than an outlier.
        chosen = {sku.sku_id for sku in eligible[:wanted]}
        return [
            (
                sku
                if sku.sku_id not in chosen
                else Sku(
                    **{
                        **sku.__dict__,
                        "base_units": min(sku.base_units, 1.4),
                        "is_intermittent": True,
                    }
                )
            )
            for sku in skus
        ]

    def _name_for(self, sku_id: str, category: str, is_launch: bool) -> str:
        """A plausible fictional product name. Real brands are never referenced."""
        if is_launch:
            for launch in self._config.launches:
                if launch.category == category:
                    return launch.sku_name
        rng = self._seeds("sku_name", sku_id)
        prefix = str(rng.choice(["Meridian", "Aurora", "PureCare", "Verdant", "Lumen", "Saral"]))
        form = {
            "Haircare": ["Hair Oil", "Shampoo", "Conditioner", "Serum"],
            "Skincare": ["Face Cream", "Cleanser", "Serum", "Sunscreen"],
            "Bodycare": ["Body Lotion", "Body Wash", "Soap Bar", "Scrub"],
            "Home Fragrance": ["Room Mist", "Diffuser", "Candle", "Incense"],
            "Surface Care": ["Floor Cleaner", "Dish Gel", "Glass Spray", "Disinfectant"],
            "Baby": ["Baby Lotion", "Baby Wash", "Baby Oil", "Baby Balm"],
        }[category]
        return f"{prefix} {rng.choice(form)}"

    # ---------------------------------------------------------------- arrays --
    @property
    def sku_ids(self) -> list[str]:
        """SKU ids in catalog order — the canonical SKU axis."""
        return [sku.sku_id for sku in self.skus]

    @cached_property
    def category_of_sku(self) -> np.ndarray:
        """``(n_skus,)`` integer index into the category axis."""
        order = {category: index for index, category in enumerate(self._config.category_ids)}
        return np.array([order[sku.category] for sku in self.skus], dtype=np.int64)

    @cached_property
    def base_units(self) -> np.ndarray:
        """``(n_skus,)`` steady-state national daily demand."""
        return np.array([sku.base_units for sku in self.skus], dtype=np.float64)

    @cached_property
    def ref_price(self) -> np.ndarray:
        """``(n_skus,)`` reference price. Price elasticity is measured against this."""
        return np.array([sku.ref_price_inr for sku in self.skus], dtype=np.float64)

    @cached_property
    def unit_cost(self) -> np.ndarray:
        """``(n_skus,)`` standard cost, from the category's gross-margin target."""
        return np.array([sku.unit_cost_inr for sku in self.skus], dtype=np.float64)

    @cached_property
    def is_intermittent(self) -> np.ndarray:
        """``(n_skus,)`` mask of the slow movers that get near-Poisson counting noise."""
        return np.array([sku.is_intermittent for sku in self.skus], dtype=bool)

    def active_mask(self, n_days: int, horizon_start: dt.date) -> np.ndarray:
        """``(n_skus, n_days)`` mask: is this SKU sellable on this day?

        A SKU is inactive before its launch and after its discontinuation. This is
        what makes the product master a slowly-changing dimension and what produces
        the sparse-history case rather than merely asserting it.
        """
        mask = np.zeros((len(self.skus), n_days), dtype=bool)
        for row, sku in enumerate(self.skus):
            start = max(0, (sku.launch_date - horizon_start).days)
            end = n_days
            if sku.discontinued_date is not None:
                end = min(n_days, (sku.discontinued_date - horizon_start).days)
            if start < end:
                mask[row, start:end] = True
        return mask

    def lifecycle_trend(self, n_days: int, horizon_start: dt.date) -> np.ndarray:
        """``(n_skus, n_days)`` slow multiplicative lifecycle, launch curve included.

        Two components: a per-SKU log-linear drift (some products grow, some decay)
        and, for in-window launches, a decaying novelty curve. The launch curve is
        the shape the pooled empirical-Bayes baseline borrows for a sparse series.
        """
        day_index = np.arange(n_days, dtype=np.float64)
        trend = np.empty((len(self.skus), n_days), dtype=np.float64)
        for row, sku in enumerate(self.skus):
            slope = float(self._seeds("sku_trend", sku.sku_id).normal(0.0, _LIFECYCLE_TREND_SD))
            trend[row] = np.exp(slope * day_index)
            if sku.is_in_window_launch:
                since_launch = day_index - (sku.launch_date - horizon_start).days
                novelty = 1.0 + (_LAUNCH_PEAK_MULTIPLIER - 1.0) * np.exp(
                    -np.maximum(since_launch, 0.0) * np.log(2.0) / _LAUNCH_CURVE_HALF_LIFE_DAYS
                )
                trend[row] *= np.where(since_launch >= 0, novelty, 1.0)
        return trend

    def to_frame(self) -> pd.DataFrame:
        """The product master as a table — the source of the PIM projection."""
        return pd.DataFrame(
            [
                {
                    "product_sku": sku.sku_id,
                    "product_name": sku.name,
                    "category": sku.category,
                    "pack_size_ml": sku.pack_size_ml,
                    "unit_cost": sku.unit_cost_inr,
                    "list_price": sku.ref_price_inr,
                    "launch_date": sku.launch_date,
                    "discontinued_date": sku.discontinued_date,
                    "is_intermittent": sku.is_intermittent,
                }
                for sku in self.skus
            ]
        )
