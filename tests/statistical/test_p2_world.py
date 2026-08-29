"""P2 gate — the simulated world is deterministic, realistic, and hostile to naive methods.

The determinism test runs first and matters most. If it fails, the RNG is positional
somewhere and every ground-truth number downstream is fiction — nothing else in this
file is worth reading until it passes.

The remaining tests are the realism claim. When a judge asks "is this data
realistic?", the answer is this test run, not an assurance.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from statsmodels.stats.diagnostic import acorr_ljungbox, het_breuschpagan
from statsmodels.tsa.ar_model import AutoReg
from statsmodels.tsa.stattools import acf

from insight_copilot.datagen.events.overlay import DayEffects, EventOverlay, NoEvents
from insight_copilot.datagen.panel import SimulationPanel
from insight_copilot.datagen.simulate import Simulator
from insight_copilot.datagen.writer import write_truth_tables

from .conftest import ALTERNATE_SEED, SEED

pytestmark = pytest.mark.statistical


# ============================================================== determinism ===
class _ZeroMagnitudeEvent(EventOverlay):
    """An event that is present in the ledger and does nothing at all.

    Identity multipliers (1.0) and a zero addend are exact in IEEE-754, so a
    simulator whose randomness is content-addressed must produce bit-identical
    output with and without it. A simulator with a positional RNG anywhere will not.
    """

    def __init__(self, simulator: Simulator) -> None:
        n_skus = len(simulator.catalog.skus)
        n_regions = len(simulator.config.regions)
        n_channels = len(simulator.config.channels)
        n_warehouses = len(simulator.config.warehouse_ids)
        n_media = len(simulator.config.media.channels)
        self._effects = DayEffects(
            availability_cap=np.ones((n_warehouses, n_skus)),
            price_multiplier=np.ones((n_skus, n_regions)),
            media_multiplier=np.ones(n_media),
            demand_multiplier=np.ones((n_skus, n_regions, n_channels)),
            bulk_units=np.zeros((n_skus, n_regions, n_channels)),
        )
        self.window = range(800, 830)

    def effects_on(self, day_index: int) -> DayEffects:
        return self._effects if day_index in self.window else DayEffects()

    def describe(self) -> str:
        return "zero-magnitude event"


class _RealEvent(_ZeroMagnitudeEvent):
    """The same event with an actual magnitude, to prove the seam is not inert."""

    def __init__(self, simulator: Simulator) -> None:
        super().__init__(simulator)
        capped = np.array(self._effects.availability_cap, copy=True)
        capped[0] = 0.55
        self._effects = DayEffects(
            availability_cap=capped,
            price_multiplier=self._effects.price_multiplier,
            media_multiplier=self._effects.media_multiplier,
            demand_multiplier=self._effects.demand_multiplier,
            bulk_units=self._effects.bulk_units,
        )

    def describe(self) -> str:
        return "real event"


def test_a_zero_magnitude_event_changes_nothing(simulator: Simulator) -> None:
    """THE determinism gate. Everything downstream depends on this passing."""
    without = simulator.run(NoEvents()).checksum()
    with_null_event = simulator.run(_ZeroMagnitudeEvent(simulator)).checksum()
    assert with_null_event == without, (
        "a zero-magnitude event perturbed the simulation, which means some draw is "
        "addressed by stream position rather than by content key"
    )


def test_the_event_seam_is_not_inert(simulator: Simulator) -> None:
    """A real event must change the world, or the previous test proves nothing."""
    assert simulator.run(_RealEvent(simulator)).checksum() != simulator.run(NoEvents()).checksum()


def test_the_same_seed_reproduces_the_same_world(panel: SimulationPanel) -> None:
    assert Simulator.from_defaults(SEED).run().checksum() == panel.checksum()


def test_a_different_seed_produces_a_different_world(panel: SimulationPanel) -> None:
    assert Simulator.from_defaults(ALTERNATE_SEED).run().checksum() != panel.checksum()


def test_two_generations_write_byte_identical_parquet(
    simulator: Simulator, panel: SimulationPanel, tmp_path: Path
) -> None:
    """The on-disk artefact must be reproducible, not only the in-memory arrays.

    Checked at the byte level rather than by comparing dataframes: a column order or
    dtype change would alter every downstream checksum and must not pass silently.
    """
    first = write_truth_tables(simulator, panel, tmp_path / "a")
    second = write_truth_tables(simulator, simulator.run(), tmp_path / "b")
    assert first.checksum == second.checksum
    assert first.row_counts == second.row_counts

    for table in sorted(first.row_counts):
        name = f"{table}.parquet"
        left = (first.directory / name).read_bytes()
        right = (second.directory / name).read_bytes()
        assert left == right, f"{name} differs between two runs at the same seed"


# ============================================== structural (DataLayer 12.1) ===
def test_daily_revenue_has_a_significant_lag_seven_peak(daily_revenue: pd.Series) -> None:
    """Weekly seasonality must be discoverable, and must stand out from its neighbours.

    The series is de-trended with a 91-day centred mean rather than a shorter one:
    a 28-day window would absorb the weekly cycle it is supposed to reveal.
    """
    log_revenue = np.log(daily_revenue)
    slow = log_revenue.rolling(91, center=True, min_periods=30).mean()
    detrended = (log_revenue - slow).dropna()
    correlations = acf(detrended, nlags=22, fft=True)

    significance = 1.96 / np.sqrt(len(detrended))
    assert correlations[7] > significance, "no significant lag-7 autocorrelation"
    assert correlations[7] > correlations[6] + 0.15
    assert correlations[7] > correlations[8] + 0.15
    assert correlations[14] > significance, "the weekly cycle must persist to lag 14"


def test_the_planted_ar_one_coefficient_is_recovered(driver_residuals: np.ndarray) -> None:
    """phi = 0.35 +/- 0.08 after removing every observable driver."""
    fit = AutoReg(driver_residuals, lags=1).fit()
    phi = float(fit.params[1])
    assert 0.27 <= phi <= 0.43, f"recovered AR(1) phi = {phi:.3f}, expected 0.35 +/- 0.08"


def test_breusch_pagan_rejects_on_raw_residuals(
    driver_residuals: np.ndarray, driver_design: pd.DataFrame
) -> None:
    """Heteroscedasticity is planted, so the test MUST reject.

    This is what justifies EWMA / day-of-week variance scaling and Newey-West
    inference downstream. A dataset where Breusch-Pagan failed to reject would make
    the diagnostic in the demo decorative rather than real.
    """
    _, p_value, _, _ = het_breuschpagan(driver_residuals, driver_design.to_numpy())
    assert p_value < 0.05, f"Breusch-Pagan did not reject (p={p_value:.3f})"


def test_ljung_box_does_not_reject_after_whitening(driver_residuals: np.ndarray) -> None:
    """AR(1) whitening must leave approximately white innovations on a clean window."""
    innovations = AutoReg(driver_residuals, lags=1).fit().resid
    p_value = float(acorr_ljungbox(innovations, lags=[10], return_df=True)["lb_pvalue"].iloc[0])
    assert p_value > 0.05, f"innovations are still autocorrelated (p={p_value:.4f})"


def test_daily_national_revenue_cv_is_in_band(daily_revenue: pd.Series) -> None:
    """0.18-0.25: the design's sanity band for aggregate volatility."""
    coefficient = float(daily_revenue.std() / daily_revenue.mean())
    assert 0.18 <= coefficient <= 0.25, f"daily revenue CV = {coefficient:.3f}"


def test_at_least_one_series_is_genuinely_intermittent(
    simulator: Simulator, panel: SimulationPanel
) -> None:
    """A Croston case must exist in the data, not only in the adaptation matrix."""
    cells = simulator.assortment
    by_sku = np.zeros((len(simulator.catalog.skus), panel.units.shape[1]))
    np.add.at(by_sku, cells.sku_index, panel.units)
    zero_day_fraction = (by_sku == 0).mean(axis=1)
    assert (zero_day_fraction > 0.40).sum() >= 1, "no SKU exceeds 40% zero days"


def test_transaction_amounts_follow_benford(panel: SimulationPanel) -> None:
    """A genuine signature of naturally generated monetary data.

    Cheap, memorable, and a real credibility check: amounts assembled from a
    uniform grid or a single normal draw do not pass this.
    """
    amounts = (panel.units * panel.unit_price_net).ravel()
    amounts = amounts[amounts > 1.0]
    leading = (amounts / np.power(10.0, np.floor(np.log10(amounts)))).astype(int)
    observed = np.array([(leading == digit).mean() for digit in range(1, 10)])
    expected = np.log10(1.0 + 1.0 / np.arange(1, 10))
    mean_deviation = float(np.abs(observed - expected).mean())
    assert mean_deviation < 0.012, f"Benford mean absolute deviation = {mean_deviation:.4f}"


def test_units_are_whole_numbers(panel: SimulationPanel) -> None:
    """Orders, shipments, stock and returns are counts, not fractions."""
    for name in (
        "units",
        "units_ordered",
        "units_shipped_ok",
        "on_hand",
        "in_transit",
        "returned_units",
    ):
        values: np.ndarray = getattr(panel, name)
        assert np.array_equal(values, np.round(values)), f"{name} is fractional"


# ============================================ domain plausibility (12.3) ======
def test_the_business_is_the_size_it_claims_to_be(
    simulator: Simulator, daily_revenue: pd.Series
) -> None:
    years = simulator.calendar.n_days / 365.25
    annual = float(daily_revenue.sum()) / years
    target = simulator.config.company.target_annual_net_revenue_inr
    assert abs(annual / target - 1.0) < 0.10, f"annual revenue Rs {annual / 1e7:.0f} cr"


def test_fill_rate_sits_in_the_cpg_service_band(panel: SimulationPanel) -> None:
    fill_rate = float(np.nanmean(panel.national_fill_rate()))
    assert 0.92 <= fill_rate <= 0.99, f"national fill rate = {fill_rate:.4f}"


def test_return_rate_is_category_appropriate(panel: SimulationPanel) -> None:
    """2-5% for home and personal care — far below apparel."""
    gross = float((panel.units * panel.unit_price_net).sum())
    rate = float(panel.returns_value.sum()) / gross
    assert 0.02 <= rate <= 0.05, f"return rate = {rate:.4f}"


def test_gross_margin_is_plausible(simulator: Simulator, panel: SimulationPanel) -> None:
    cells = simulator.assortment
    gross = float((panel.units * panel.unit_price_net).sum())
    cost = float((panel.units * simulator.catalog.unit_cost[cells.sku_index][:, None]).sum())
    margin = 1.0 - cost / gross
    assert 0.40 <= margin <= 0.62, f"blended gross margin = {margin:.3f}"


def test_d2c_share_is_near_its_target(simulator: Simulator, panel: SimulationPanel) -> None:
    cells = simulator.assortment
    revenue_by_cell = (panel.units * panel.unit_price_net).sum(axis=1)
    names = simulator.config.channel_ids
    total = revenue_by_cell.sum()
    share = {
        name: float(revenue_by_cell[cells.channel_index == index].sum() / total)
        for index, name in enumerate(names)
    }
    d2c = share["d2c_web"] + share["quick_commerce"]
    target = simulator.config.company.d2c_revenue_share_target
    assert abs(d2c - target) < 0.06, f"D2C share = {d2c:.3f}, target {target}"


def test_channel_day_of_week_patterns_differ_in_the_expected_direction(
    simulator: Simulator,
) -> None:
    """Quick-commerce peaks at the weekend; modern trade is weekday-heavy."""
    shape = simulator.geography.dow_shape
    names = simulator.config.channel_ids
    quick = shape[names.index("quick_commerce")]
    trade = shape[names.index("modern_trade")]
    weekend, weekday = slice(5, 7), slice(0, 5)
    assert quick[weekend].mean() > quick[weekday].mean()
    assert trade[weekday].mean() > trade[weekend].mean()

    amplitudes = (shape.max(axis=1) - shape.min(axis=1)) / 2.0
    assert 0.15 <= amplitudes.max() <= 0.40, "weekly amplitude outside the +/-15-30% band"


def test_no_impossible_quantities_or_prices(panel: SimulationPanel) -> None:
    assert (panel.units >= 0).all()
    assert (panel.on_hand >= 0).all()
    assert (panel.unit_price_net[panel.units > 0] > 0).all()
    assert (panel.list_price[panel.units > 0] >= panel.unit_price_net[panel.units > 0]).all()
    assert (panel.availability <= 1.0 + 1e-9).all()


# =================================================== planted pathologies ======
def test_festivals_have_a_pre_build_and_a_post_lull(simulator: Simulator) -> None:
    """Not a one-day spike. A detector treating it as a dummy mis-forecasts the lull.

    This is a deliberate trap for our own detector, so the shape has to actually be
    there: demand above baseline before the peak, and BELOW baseline after it.
    """
    calendar = simulator.calendar
    multiplier = calendar.festival_multiplier.mean(axis=0)
    diwali = next(w for w in calendar.festival_windows if w.name == "Diwali")
    peak = calendar.index_of(diwali.peak)

    assert multiplier[peak] > 1.4, "the festival peak is not present"
    assert multiplier[peak - 5] > 1.05, "no pre-build ramp"
    lull = multiplier[peak + 1 : peak + 6]
    assert lull.min() < 0.95, "no post-festival lull below baseline"


def test_marketing_spend_responds_to_prior_week_revenue(
    simulator: Simulator, panel: SimulationPanel
) -> None:
    """The planted endogeneity: budgets are not exogenous, which biases naive OLS.

    Without this correlation the marketing elasticity would be recoverable by a
    naive regression and the econometrics in the architecture would be theatre.
    """
    weeks = pd.Series(simulator.calendar.iso_week)
    revenue = pd.Series((panel.units * panel.unit_price_net).sum(axis=0))
    spend = pd.Series(panel.media_spend.sum(axis=(0, 1)))
    weekly = pd.DataFrame({"week": weeks, "revenue": revenue, "spend": spend})
    grouped = weekly.groupby("week", sort=False).sum(numeric_only=True)

    correlation = float(grouped["spend"].corr(grouped["revenue"].shift(1)))
    assert correlation > 0.10, f"spend does not respond to prior-week revenue (r={correlation:.3f})"


def test_the_collinear_media_pair_actually_moves_together(
    simulator: Simulator, panel: SimulationPanel
) -> None:
    """Paid social and display must be collinear inside the configured window.

    This is what the VIF gate has to catch: without it, the driver regression would
    report two precise coefficients where the data supports only one grouped effect.
    """
    config = simulator.config
    names = [channel.id for channel in config.media.channels]
    first, second = (names.index(channel) for channel in config.media.collinear_pair)
    dates = simulator.calendar.dates
    start, end = config.media.collinear_window

    # Correlate at the WEEKLY grain: that is the grain the MarTech feed delivers and
    # the grain the driver regression uses. Daily spend also carries per-channel
    # pacing, which is noise from the regression's point of view.
    weeks = pd.Series(simulator.calendar.iso_week)
    spend = pd.DataFrame(panel.media_spend.sum(axis=0).T, columns=names)
    spend["week"] = weeks
    weekly = spend.groupby("week", sort=False).sum(numeric_only=True)
    window_weeks = set(weeks[(dates.date >= start) & (dates.date <= end)].unique())
    inside = weekly.loc[weekly.index.isin(window_weeks)].corr().to_numpy()
    outside = weekly.loc[~weekly.index.isin(window_weeks)].corr().to_numpy()

    within = float(inside[first, second])
    baseline = float(outside[first, second])
    assert within > 0.60, f"collinear pair correlation inside the window = {within:.2f}"
    assert within > baseline + 0.25, "the collinearity is not confined to its window"

    # And it must stand out: if every pair were this correlated, no media coefficient
    # would be identifiable anywhere and the VIF gate would have nothing to isolate.
    off_diagonal = outside[~np.eye(len(names), dtype=bool)]
    assert float(np.median(off_diagonal)) < 0.45, "all media channels move together"


def test_the_regime_break_is_a_level_shift_in_price(simulator: Simulator) -> None:
    """A permanent price-list revision: the changepoint case, and a calibration
    window the conformal detector must exclude."""
    from insight_copilot.datagen.decisions.pricing import REGIME_BREAK_DATE, REGIME_BREAK_SIZE

    offset = simulator.calendar.index_of(REGIME_BREAK_DATE)
    prices = simulator.price_plan.list_price.mean(axis=(0, 1))
    before = prices[offset - 30 : offset].mean()
    after = prices[offset : offset + 30].mean()
    assert after / before == pytest.approx(1.0 + REGIME_BREAK_SIZE, rel=0.02)


def test_the_sparse_history_launch_exists_and_is_recent(simulator: Simulator) -> None:
    """Scenario C needs a product with ~18 days of history at the demo's 'today'."""
    import datetime as dt

    aurora = next(sku for sku in simulator.catalog.skus if sku.name.startswith("Aurora X"))
    days_of_history = (dt.date(2026, 3, 29) - aurora.launch_date).days
    assert 14 <= days_of_history <= 24, f"Aurora X has {days_of_history} days of history"
    assert aurora.is_in_window_launch
