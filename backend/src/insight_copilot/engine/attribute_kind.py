"""Rung 2 — what *kind* of move it was: price, volume, or mix.

The Bennet indicator, which is the only two-factor decomposition that is exact and
symmetric in the two periods:

``ΔR = Σ_i [ Δp_i · (q0_i + q1_i)/2 + Δq_i · (p0_i + p1_i)/2 ]``

Both terms use the *average* of the two periods, which is why the parts sum to the
whole with no residual term to explain away. The volume term is then split again into
the part every item would have got at an unchanged mix and the part that is the mix
shifting — also exactly, because the split is a rearrangement rather than a model.

Every function here asserts the identity. A decomposition whose parts do not sum to the
whole is not a decomposition, and discovering that in front of a judge is not the
moment to find out.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from insight_copilot.errors import StatisticalError

IDENTITY_TOLERANCE = 1e-6
"""Absolute tolerance on the sum-to-whole check, in the KPI's own units. This is an
arithmetic identity, not an estimate: the tolerance exists for floating point and is
never widened to accommodate a result."""


@dataclass(frozen=True)
class BennetPart:
    """One item's contribution, split into the three effects."""

    item: str
    price_effect: float
    own_volume_effect: float
    mix_effect: float
    revenue_before: float
    revenue_after: float

    @property
    def total(self) -> float:
        """This item's whole contribution to the revenue change."""
        return self.price_effect + self.own_volume_effect + self.mix_effect


@dataclass(frozen=True)
class BennetDecomposition:
    """The full price-volume-mix split of a revenue change."""

    parts: list[BennetPart]
    delta_revenue: float
    price_effect: float
    own_volume_effect: float
    mix_effect: float
    residual: float

    @property
    def dominant(self) -> str:
        """Which effect carries the most of the move, by absolute size."""
        effects = {
            "price": self.price_effect,
            "volume": self.own_volume_effect,
            "mix": self.mix_effect,
        }
        return max(effects, key=lambda name: abs(effects[name]))

    def top_items(self, limit: int = 5) -> list[BennetPart]:
        """The items moving the number most, largest absolute contribution first."""
        return sorted(self.parts, key=lambda part: abs(part.total), reverse=True)[:limit]

    @property
    def detail(self) -> str:
        """A sentence for the evidence drawer."""
        return (
            f"Bennet decomposition of a {self.delta_revenue:,.0f} change: "
            f"price {self.price_effect:,.0f}, volume {self.own_volume_effect:,.0f}, "
            f"mix {self.mix_effect:,.0f} (residual {self.residual:.2e})"
        )


def decompose(
    before: pd.DataFrame,
    after: pd.DataFrame,
    *,
    item_column: str,
    price_column: str,
    quantity_column: str,
) -> BennetDecomposition:
    """Split ``ΔR`` into price, own-volume and mix effects. Exact by construction."""
    joined = _align(before, after, item_column, price_column, quantity_column)
    p0, p1 = joined["price_before"].to_numpy(), joined["price_after"].to_numpy()
    q0, q1 = joined["qty_before"].to_numpy(), joined["qty_after"].to_numpy()

    delta_revenue = float(np.sum(p1 * q1) - np.sum(p0 * q0))
    price_effect = (p1 - p0) * (q0 + q1) / 2.0
    quantity_effect = (q1 - q0) * (p0 + p1) / 2.0

    total_before, total_after = float(q0.sum()), float(q1.sum())
    # Share of the *before* period. Splitting the quantity term into "what this item
    # would have got had the mix not moved" and "the rest" is a rearrangement, so the
    # two halves still sum to the quantity term exactly.
    share_before = q0 / total_before if total_before > 0 else np.zeros_like(q0)
    at_constant_mix = share_before * (total_after - total_before)
    own_volume_effect = at_constant_mix * (p0 + p1) / 2.0
    mix_effect = quantity_effect - own_volume_effect

    parts = [
        BennetPart(
            item=str(item),
            price_effect=float(price_effect[index]),
            own_volume_effect=float(own_volume_effect[index]),
            mix_effect=float(mix_effect[index]),
            revenue_before=float(p0[index] * q0[index]),
            revenue_after=float(p1[index] * q1[index]),
        )
        for index, item in enumerate(joined[item_column])
    ]
    totals = (
        float(price_effect.sum()),
        float(own_volume_effect.sum()),
        float(mix_effect.sum()),
    )
    residual = delta_revenue - sum(totals)
    scale = max(abs(delta_revenue), 1.0)
    if abs(residual) > IDENTITY_TOLERANCE * scale:
        raise StatisticalError(
            "Bennet parts do not sum to the revenue change",
            detail=(
                f"delta {delta_revenue:.6f} against parts {sum(totals):.6f}; "
                f"residual {residual:.6e}"
            ),
        )
    return BennetDecomposition(
        parts=parts,
        delta_revenue=delta_revenue,
        price_effect=totals[0],
        own_volume_effect=totals[1],
        mix_effect=totals[2],
        residual=float(residual),
    )


def _align(
    before: pd.DataFrame,
    after: pd.DataFrame,
    item_column: str,
    price_column: str,
    quantity_column: str,
) -> pd.DataFrame:
    """Outer-join the two periods on the item key, filling absences with zero.

    An item that sold in one period and not the other is a real and common case — a
    launch, a delisting — and dropping it would silently move its whole revenue into
    the residual the identity check is meant to catch.
    """
    for frame, label in ((before, "before"), (after, "after")):
        missing = {item_column, price_column, quantity_column} - set(frame.columns)
        if missing:
            raise StatisticalError(f"{label} period lacks columns {sorted(missing)}")

    left = (
        before.assign(_value=before[price_column] * before[quantity_column])
        .groupby(item_column, observed=True)
        .agg(qty_before=(quantity_column, "sum"), value_before=("_value", "sum"))
    )
    right = (
        after.assign(_value=after[price_column] * after[quantity_column])
        .groupby(item_column, observed=True)
        .agg(qty_after=(quantity_column, "sum"), value_after=("_value", "sum"))
    )
    joined = left.join(right, how="outer").fillna(0.0).reset_index()
    # Prices are recovered as value / quantity rather than averaged: the average of a
    # price is not the price of the average, and only the value-weighted form makes
    # ``p * q`` reproduce the revenue it came from.
    joined["price_before"] = np.where(
        joined["qty_before"] > 0, joined["value_before"] / joined["qty_before"].replace(0, 1), 0.0
    )
    joined["price_after"] = np.where(
        joined["qty_after"] > 0, joined["value_after"] / joined["qty_after"].replace(0, 1), 0.0
    )
    # An item absent from one period keeps the other period's price, so its whole move
    # lands in the volume term where it belongs rather than in a spurious price term.
    joined.loc[joined["qty_before"] == 0, "price_before"] = joined.loc[
        joined["qty_before"] == 0, "price_after"
    ]
    joined.loc[joined["qty_after"] == 0, "price_after"] = joined.loc[
        joined["qty_after"] == 0, "price_before"
    ]
    return joined
