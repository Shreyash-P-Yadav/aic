"""Structural noise, built to be hostile to naive methods.

Two properties are planted on purpose, because the whole analytical design is
justified by them:

* **Autocorrelation (phi ~ 0.35).** A plain z-score on autocorrelated residuals
  understates variance and over-flags. This is what justifies AR whitening before
  scoring, and the recovered coefficient is asserted in the P2 gate.
* **Heteroscedasticity.** Variance clusters around promos, festivals and weekends.
  This is what justifies EWMA / day-of-week variance scaling, and it makes
  Breusch-Pagan reject *honestly* in the flagship scenario — the diagnostic that
  appears in the demo is real, not decorative.

Every function here is pure: arrays in, arrays out, no I/O and no hidden state. The
randomness enters only through a :class:`SeedBook` passed by the caller.
"""

from __future__ import annotations

import numpy as np

from insight_copilot.datagen.world.seeds import SeedBook


def company_shock(
    seeds: SeedBook,
    n_days: int,
    *,
    phi: float,
    sigma0: float,
    scale: np.ndarray,
) -> np.ndarray:
    """The company-wide AR(1) demand shock, in log space.

    ``u[t] = phi * u[t-1] + sigma[t] * eta[t]``, where ``sigma[t] = sigma0 * scale[t]``
    carries the heteroscedasticity. The innovations ``eta`` are drawn as one vector
    addressed by the key ``("company_shock",)`` and indexed by day offset, so adding
    or removing an event never shifts them.

    The recursion is burned in from ``u[0] = 0``; over 1,096 days the initial
    condition is irrelevant (``phi**30 < 1e-13``), and starting from the stationary
    draw instead would make the first day's value depend on a second draw for no gain.
    """
    if not 0.0 <= phi < 1.0:
        raise ValueError(f"AR(1) phi must be in [0, 1), got {phi}")
    if scale.shape != (n_days,):
        raise ValueError(f"scale must be ({n_days},), got {scale.shape}")

    eta = seeds("company_shock").standard_normal(n_days)
    innovations = sigma0 * scale * eta
    shock = np.empty(n_days, dtype=np.float64)
    running = 0.0
    for day in range(n_days):
        running = phi * running + innovations[day]
        shock[day] = running
    return shock


def volatility_scale(
    *,
    promo_active: np.ndarray,
    in_festival_window: np.ndarray,
    dow_volatility: np.ndarray,
    promo_multiplier: float,
    festival_multiplier: float,
) -> np.ndarray:
    """``(n_days,)`` multiplicative volatility scale for the company shock.

    ``sigma[t] = sigma0 * (1 + a*promo) * (1 + b*festival) * dow_vol[t]``

    Kept separate from the level effects so that a promo makes a series *noisier*
    as well as *bigger*. A model that captures only the level change will leave
    structure in the squared residuals — which is exactly what Breusch-Pagan detects.
    """
    scale: np.ndarray = (
        (1.0 + promo_multiplier * promo_active.astype(np.float64))
        * (1.0 + festival_multiplier * in_festival_window.astype(np.float64))
        * dow_volatility
    )
    return scale


def idiosyncratic_noise(
    seeds: SeedBook,
    *,
    sku_ids: list[str],
    region: str,
    channel: str,
    n_days: int,
    sigma: np.ndarray,
) -> np.ndarray:
    """``(n_skus, n_days)`` per-cell lognormal noise, in log space.

    The scale is *inversely* related to base volume: a SKU selling three units a day
    is proportionally far noisier than one selling three thousand. That is both
    realistic and necessary — without it, every series has the same signal-to-noise
    ratio and the confidence engine has nothing to discriminate.

    One draw per (sku, region, channel) cell over the full history. The key is the
    cell identity; the position within the vector is the day index from the fixed
    horizon start, never a consumption order.
    """
    noise = np.empty((len(sku_ids), n_days), dtype=np.float64)
    for row, sku_id in enumerate(sku_ids):
        draws = seeds("demand_noise", sku_id, region, channel).standard_normal(n_days)
        noise[row] = sigma[row] * draws
    # Lognormal correction: exp(x) with x ~ N(0, s^2) has mean exp(s^2/2), so
    # subtracting it keeps the noise term mean-1 and leaves the level unbiased.
    return noise - 0.5 * (sigma[:, None] ** 2)


def idiosyncratic_sigma(
    base_units: np.ndarray,
    *,
    sigma_large: float,
    sigma_small: float,
    threshold: float,
) -> np.ndarray:
    """``(n_skus,)`` per-SKU noise scale, interpolated on log volume.

    Small cells get ``sigma_small``, large cells ``sigma_large``, with a smooth
    transition around ``threshold`` units per day so there is no artificial cliff
    that a changepoint detector would find.
    """
    log_ratio = np.log(np.maximum(base_units, 1e-6) / threshold)
    weight = 1.0 / (1.0 + np.exp(log_ratio))  # 1 for small cells, 0 for large
    sigma: np.ndarray = sigma_large + (sigma_small - sigma_large) * weight
    return sigma


def stochastic_round(values: np.ndarray, uniforms: np.ndarray) -> np.ndarray:
    """Round to integers without bias: ``floor(x) + 1[u < frac(x)]``.

    WHY not plain rounding: orders are whole units, and a slow-moving SKU at 0.4
    expected units a day would round to zero *every* day, erasing it from the data
    entirely. Stochastic rounding preserves the mean exactly and produces genuine
    runs of zero days for small cells — which is what makes the intermittent series
    a real Croston case rather than a label, and what makes leading digits of
    transaction amounts follow Benford.

    The uniforms are pre-drawn per cell by content key, so this is a pure function
    and the day loop stays free of randomness.
    """
    floor = np.floor(values)
    rounded: np.ndarray = floor + (uniforms < (values - floor)).astype(np.float64)
    return rounded


def poisson_counts(
    seeds: SeedBook,
    intensity: np.ndarray,
    *,
    sku_id: str,
    region: str,
    channel: str,
) -> np.ndarray:
    """Near-Poisson counting noise for an intermittent series.

    WHY Poisson rather than a rounded lognormal: at an intensity near 1 unit a day,
    the discreteness *is* the phenomenon. A Poisson draw produces genuine runs of
    zero days, which is what makes the Croston path in the adaptation matrix a real
    case rather than a label.
    """
    rng = seeds("intermittent_counts", sku_id, region, channel)
    counts: np.ndarray = rng.poisson(np.maximum(intensity, 0.0)).astype(np.float64)
    return counts
