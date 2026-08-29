"""Shared simulation fixtures.

A full 36-month run takes ~3 s, so it is built once per session and shared. The
fixtures are read-only by convention: no test mutates a panel.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm

from insight_copilot.datagen.panel import SimulationPanel
from insight_copilot.datagen.simulate import Simulator

SEED = 20260329
ALTERNATE_SEED = 8675309


@pytest.fixture(scope="session")
def simulator() -> Simulator:
    """The simulator over the shipped world config, at the canonical seed."""
    return Simulator.from_defaults(SEED)


@pytest.fixture(scope="session")
def panel(simulator: Simulator) -> SimulationPanel:
    """The factual run: no events, the world as it would be with nothing happening."""
    return simulator.run()


@pytest.fixture(scope="session")
def daily_revenue(simulator: Simulator, panel: SimulationPanel) -> pd.Series:
    """National net revenue per day, indexed by date."""
    return pd.Series(panel.net_revenue_by_day(), index=simulator.calendar.dates)


@pytest.fixture(scope="session")
def driver_design(simulator: Simulator, panel: SimulationPanel) -> pd.DataFrame:
    """The observable-driver design matrix used to recover the company shock.

    WHY these regressors and no others: the AR(1) recovery test asks whether the
    *planted* company-wide shock is recoverable from data, which means first removing
    the effects an analyst can actually observe — calendar, festivals, annual shape,
    promotion depth, media adstock, realised price and availability. Anything left is
    the structural shock plus idiosyncratic noise. Leaving an observable driver out
    would smuggle its persistence into the estimate and flatter (or spoil) the result.
    """
    calendar = simulator.calendar
    index = calendar.dates
    day_of_year = calendar.day_of_year

    design = pd.get_dummies(
        pd.Series(calendar.day_of_week, index=index), prefix="dow", drop_first=True
    ).astype(float)
    design["festival"] = np.log(calendar.festival_multiplier.mean(axis=0))
    design["trend"] = np.arange(len(index), dtype=float)
    for harmonic in (1, 2, 3):
        angle = 2.0 * np.pi * harmonic * day_of_year / 365.25
        design[f"sin{harmonic}"] = np.sin(angle)
        design[f"cos{harmonic}"] = np.cos(angle)
    design["promo_depth"] = panel.promo_depth.mean(axis=0)
    design["log_adstock"] = np.log(panel.media_adstock.sum(axis=(0, 1)))
    design["log_price"] = np.log(panel.unit_price_net.mean(axis=0))
    design["availability"] = panel.availability.mean(axis=0)
    return sm.add_constant(design)


@pytest.fixture(scope="session")
def driver_residuals(daily_revenue: pd.Series, driver_design: pd.DataFrame) -> np.ndarray:
    """Log-revenue residuals after removing every observable driver."""
    fit = sm.OLS(np.log(daily_revenue.to_numpy()), driver_design.to_numpy()).fit()
    residuals: np.ndarray = np.asarray(fit.resid)
    return residuals
