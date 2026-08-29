"""Returns, arriving 7-21 days after the sale that generated them.

The lag is the point. Day-level revenue and returns do not net out within a day, so
the ops view of net revenue (order date) and the finance view (invoice date, returns
recognised when received) disagree by 1-3% — one of the designed disagreements the
reconciliation layer has to live with.
"""

from __future__ import annotations

import numpy as np

from insight_copilot.datagen.latent.noise import stochastic_round
from insight_copilot.datagen.world.seeds import SeedBook


def schedule_returns(
    *,
    returned_units: np.ndarray,
    returns_value: np.ndarray,
    seeds: SeedBook,
    day: int,
    units: np.ndarray,
    price: np.ndarray,
    rate: np.ndarray,
    lag_min: int,
    lag_max: int,
) -> None:
    """Book one day's returns into their future arrival days, in place.

    Both draws are keyed on the day alone, so they are content-addressed and
    unaffected by whether an event is present — which is what keeps a counterfactual
    re-run comparable.
    """
    # Whole units come back. Stochastic rounding keeps the aggregate return rate
    # exactly on its category target while individual cells return 0 or 1 units,
    # which is what the returns feed actually looks like.
    returned = stochastic_round(units * rate, seeds("return_rounding", day).random(len(units)))
    offsets = seeds("return_lag", day).integers(lag_min, lag_max + 1, size=len(units))
    arrival = day + offsets
    inside = arrival < returned_units.shape[1]
    rows = np.arange(len(units))[inside]
    np.add.at(returned_units, (rows, arrival[inside]), returned[inside])
    np.add.at(returns_value, (rows, arrival[inside]), (returned * price)[inside])
