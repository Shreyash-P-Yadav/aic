"""Seasonal shape: day-of-week, category x region annual cycle, weather response.

All effects are *multiplicative* and mean-1 normalised where a level is not intended.
A weekend dip is -20% of level, not a fixed number of units — which is why the engine
models ``log(y)``, and the data has to be built the same way or the modelling choice
looks arbitrary.

The annual shape is **category x region**, not national: Surface Care peaks with the
monsoon in the West before it peaks in the North, because monsoon onset differs by
region and varies year to year. That is what stops the annual cycle from being
perfectly recoverable from the day of year, which is the realistic case.
"""

from __future__ import annotations

import numpy as np

from insight_copilot.datagen.world.calendar import Calendar
from insight_copilot.datagen.world.config import WorldConfig


def annual_shape(config: WorldConfig, calendar: Calendar) -> np.ndarray:
    """``(n_categories, n_regions, n_days)`` annual demand multiplier.

    Three additive-in-log components: a smooth annual cosine peaking on the
    category's ``annual_peak_doy``, the region's monsoon intensity scaled by the
    category's monsoon sensitivity, and the region's heat intensity scaled by heat
    sensitivity. Each is centred so the annual mean stays close to 1.
    """
    n_categories = len(config.categories)
    n_regions = len(config.regions)
    shape = np.empty((n_categories, n_regions, calendar.n_days), dtype=np.float64)

    monsoon = calendar.monsoon_intensity  # (n_regions, n_days)
    heat = calendar.heat_intensity  # (n_regions, n_days)
    day_of_year = calendar.day_of_year.astype(np.float64)

    for index, category in enumerate(config.categories):
        phase = 2.0 * np.pi * (day_of_year - category.annual_peak_doy) / 365.25
        seasonal = category.annual_amplitude * np.cos(phase)  # mean ~0 in log space
        weather = category.monsoon_sensitivity * (monsoon - monsoon.mean(axis=1, keepdims=True))
        heat_term = category.heat_sensitivity * (heat - heat.mean(axis=1, keepdims=True))
        shape[index] = np.exp(seasonal[None, :] + weather + heat_term)
    return shape


def day_of_week_shape(dow_multipliers: np.ndarray, day_of_week: np.ndarray) -> np.ndarray:
    """``(n_channels, n_days)`` from a ``(n_channels, 7)`` table and the date axis.

    Pure lookup, kept as a named function because the same expansion is needed for
    the volatility table and duplicating an index expression is how axes get swapped.
    """
    return dow_multipliers[:, day_of_week]


def weather_index(calendar: Calendar) -> np.ndarray:
    """``(n_regions, n_days)`` composite weather driver exported to the weather feed.

    The engine sees this as an exogenous regressor. It is a genuine driver here, so
    recovering its coefficient is a real recovery rather than a tautology.
    """
    return 0.65 * calendar.monsoon_intensity + 0.35 * calendar.heat_intensity


def adstock(spend: np.ndarray, half_life_days: float) -> np.ndarray:
    """Geometric adstock along the last axis: ``A[t] = spend[t] + lambda * A[t-1]``.

    ``lambda = 0.5 ** (1 / half_life)``. This is the transform the engine profiles a
    grid over; planting it exactly means the profile likelihood has a true optimum to
    find rather than a shape it merely fits.
    """
    if half_life_days <= 0:
        raise ValueError(f"adstock half-life must be positive, got {half_life_days}")
    decay = 0.5 ** (1.0 / half_life_days)
    out = np.empty_like(spend, dtype=np.float64)
    carry = np.zeros(spend.shape[:-1], dtype=np.float64)
    for day in range(spend.shape[-1]):
        carry = spend[..., day] + decay * carry
        out[..., day] = carry
    return out


def promo_lift(
    depth: np.ndarray, depth_choices: list[float], lift_at_depth: list[float]
) -> np.ndarray:
    """Map promotional depth to a demand multiplier by piecewise-linear interpolation.

    Lift is depth-dependent (1.4x-2.6x over the configured depths) rather than a
    single flat "promo on" factor, so the price and promo terms are separately
    identifiable in the driver regression instead of collapsing into one dummy.
    """
    lift: np.ndarray = np.interp(
        depth, depth_choices, lift_at_depth, left=1.0, right=lift_at_depth[-1]
    )
    return lift
