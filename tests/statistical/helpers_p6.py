"""Shared setup for the P6 gate: an engine wired to the ingested warehouse.

Kept out of the test module so that file stays inside the four-hundred-line limit, and
named without a ``test_`` prefix so pytest does not collect it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.engine.attribute_where import Attributor
from insight_copilot.engine.cube import CubeWindow, national_factor, segment_actual_forecast
from insight_copilot.engine.dataset import EngineDataset
from insight_copilot.engine.detect import ConformalDetector, apply_fdr
from insight_copilot.engine.regression_baseline import RegressionBaseline, calendar_events
from insight_copilot.engine.series import Series
from insight_copilot.evals.elasticity import media_elasticities as library_elasticities
from insight_copilot.ingest.warehouse import Warehouse
from insight_copilot.security.audit import InMemoryAuditLog
from insight_copilot.security.compiler import ContractSQLCompiler
from insight_copilot.security.executor import QueryExecutor
from insight_copilot.security.identity import ROLES, Identity, SessionContext

SCENARIO_A_OUTAGE = (dt.date(2026, 3, 6), dt.date(2026, 3, 12))
"""``EV-2026-0306-OUTAGE`` — the DC-North pick-capacity failure. Ledger scoped effect
-7.34%, national isolated effect -2.97%."""

SCENARIO_A_WEEK = (dt.date(2026, 3, 9), dt.date(2026, 3, 15))
"""The reporting week the demo narrates. Ground truth for the combined scenario is
-11.94% against the counterfactual simulation."""

SCENARIO_C_WINDOW = (dt.date(2026, 3, 11), dt.date(2026, 3, 24))
"""``EV-2026-0311-AURORA-LAUNCH-PROMO`` — an 18-day-old SKU. Low detectability by
design: the engine must show restraint, not fire."""

HELD_OUT_WINDOWS: tuple[tuple[dt.date, dt.date], ...] = (
    (dt.date(2023, 11, 1), dt.date(2023, 11, 25)),
    (dt.date(2024, 10, 20), dt.date(2024, 11, 20)),
    (dt.date(2025, 2, 1), dt.date(2025, 3, 10)),
    (dt.date(2025, 10, 15), dt.date(2025, 11, 25)),
    (dt.date(2026, 2, 20), dt.date(2026, 4, 30)),
)
"""Windows excluded from every calibration set: the two festive quarters, the
paise-to-rupees window, and everything from Scenario A's first event onward.

Excluding them is not tuning. Conformal p-values are exact **under exchangeability**,
and a calibration set containing a planted outage is not exchangeable with a clean
holdout — it makes the outage look ordinary, which is the precise failure the
assumption warns about."""


@dataclass
class Engine:
    """Everything a P6 test needs, wired once."""

    dataset: EngineDataset
    warehouse: Warehouse
    session: SessionContext
    registry: ContractRegistry
    series: Series
    calendar: pd.DataFrame
    panel: pd.DataFrame

    def baseline(self, exclude: tuple[dt.date, dt.date] | None = None) -> RegressionBaseline:
        """A baseline fitted with a window held out, so it never learns the event."""
        model = RegressionBaseline(
            events=calendar_events(self.calendar),
            controls=self.panel[["date", "rainfall_mm", "temp_max_c", "discount_depth_pct"]],
        )
        training = self.series
        if exclude is not None:
            training = self.series.exclude(self.series.mask_between(*exclude))
        model.fit(training)
        return model

    def calibration_mask(self, *extra: tuple[dt.date, dt.date]) -> np.ndarray:
        """Clean days: everything outside the held-out windows and the caller's own."""
        mask = np.ones(len(self.series), dtype=bool)
        for start, end in (*HELD_OUT_WINDOWS, *extra):
            mask &= ~self.series.mask_between(start, end)
        return mask


def build_engine(warehouse: Warehouse, registry: ContractRegistry) -> Engine:
    """Wire the compiler, executor and dataset over an already-ingested warehouse."""
    audit = InMemoryAuditLog()
    dataset = EngineDataset(
        warehouse=warehouse,
        registry=registry,
        compiler=ContractSQLCompiler(registry, audit),
        executor=QueryExecutor(warehouse.connection, audit),
    )
    session = SessionContext(
        identity=Identity(
            user_id="analyst@example.com", display_name="Analyst", role=ROLES["analyst"]
        ),
        intent="p6_gate",
    )
    return Engine(
        dataset=dataset,
        warehouse=warehouse,
        session=session,
        registry=registry,
        series=dataset.kpi_series("net_revenue", session),
        calendar=warehouse.query("SELECT date, is_holiday FROM gold.dim_calendar ORDER BY date"),
        panel=dataset.national_panel(session),
    )


def weekly_frame(warehouse: Warehouse) -> pd.DataFrame:
    """National weekly units, price, fill and media spend — the driver regression's input."""
    revenue = warehouse.query(
        "SELECT iso_week, sum(units) AS units, "
        "sum(units * unit_price_net) / nullif(sum(units), 0) AS asp, "
        "count(DISTINCT date) AS days FROM gold.fct_revenue_daily GROUP BY 1 ORDER BY 1"
    )
    media = warehouse.query(
        "SELECT iso_week, sum(spend_inr) AS spend FROM gold.fct_marketing_weekly GROUP BY 1"
    )
    fill = warehouse.query(
        "SELECT iso_week, 100.0 * sum(units_shipped_ok) / nullif(sum(units_ordered), 0) AS fill "
        "FROM gold.fct_fulfilment_daily GROUP BY 1"
    )
    frame = revenue.merge(media, on="iso_week").merge(fill, on="iso_week")
    frame = frame[(frame["days"] == 7) & (frame["units"] > 0)]
    return frame.sort_values("iso_week").reset_index(drop=True)


def scan_window(engine: Engine, window: tuple[dt.date, dt.date]):  # type: ignore[no-untyped-def]
    """Fit a baseline without the window, then score the window against it."""
    model = engine.baseline(exclude=window)
    expected = model.counterfactual(engine.series)
    test_mask = engine.series.mask_between(*window)
    calibration = engine.calibration_mask(window) & ~test_mask
    detections = ConformalDetector(alpha=0.01).scan(
        kpi_id="net_revenue",
        segment="national",
        series=engine.series,
        expected=expected,
        calibration_mask=calibration,
        test_mask=test_mask,
    )
    return apply_fdr(detections, 0.05)


def attribute_where(engine: Engine):  # type: ignore[no-untyped-def]
    """Run rung 1 over the scenario week."""
    model = engine.baseline(exclude=(dt.date(2026, 3, 1), dt.date(2026, 3, 25)))
    expected = model.counterfactual(engine.series)
    week = engine.series.mask_between(*SCENARIO_A_WEEK)
    window = CubeWindow.ending_before(*SCENARIO_A_WEEK)
    cube = engine.dataset.cube(engine.session, start=window.baseline_start, end=window.test_end)
    baseline_mask = engine.series.mask_between(window.baseline_start, window.baseline_end)
    factor = national_factor(
        float(expected[week].sum()), float(engine.series.values[baseline_mask].sum()), window
    )
    frame = segment_actual_forecast(
        cube,
        window,
        dimensions=["region", "channel", "category"],
        measure="net_revenue_inr",
        national_factor=factor,
    )
    return Attributor(seed=7).attribute(
        frame, ["region", "channel", "category"], actual_column="actual", forecast_column="forecast"
    )


def pvm_periods(engine: Engine) -> tuple[pd.DataFrame, pd.DataFrame]:
    """SKU-level price and units for the scenario week and the week before it."""

    def load(start: dt.date, end: dt.date) -> pd.DataFrame:
        return engine.warehouse.query(
            "SELECT product_sku, sum(units) AS units, "
            "sum(units * unit_price_net) / nullif(sum(units), 0) AS price "
            "FROM gold.fct_revenue_daily WHERE date BETWEEN $start AND $end "
            "GROUP BY 1 HAVING sum(units) > 0",
            {"start": start, "end": end},
        )

    before = load(
        SCENARIO_A_WEEK[0] - dt.timedelta(days=7), SCENARIO_A_WEEK[0] - dt.timedelta(days=1)
    )
    return before, load(*SCENARIO_A_WEEK)


def media_elasticities(engine: Engine) -> tuple[float, float]:
    """The naive and the DAG-specified blended marketing elasticity.

    Delegates to the library implementation the eval report also prints, so the gate and
    the report can never quote different numbers for the same quantity.
    """
    comparison = library_elasticities(engine.warehouse)
    return comparison.naive, comparison.dag_specified


def contracts_registry() -> ContractRegistry:
    """The shipped contracts, loaded from the package directory."""
    from pathlib import Path

    import insight_copilot.contracts as package

    return ContractRegistry.from_directory(Path(package.__file__).resolve().parent)
