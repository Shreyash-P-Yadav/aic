"""The scripted demo: build the world, load it, run the four scenarios, serve them.

One module so `make demo` and the E2E suite exercise **the same path**. A demo that
takes a different route through the code than the tests do is a demo that can break
without any test noticing.

The four scenarios, in the order a judge should see them:

* **A — the flagship.** A DC-North pick-capacity failure in March 2026, plus a media
  cut and a price rise in the same window and a post-dated competitor decoy. The
  ladder has to separate them.
* **B — abstention.** The MarTech feed goes dark; ``c4`` collapses and the engine
  declines to attribute rather than attributing to what it can still see.
* **C — restraint.** An 18-day-old launch. The right answer is not to fire.
* **D — the distractor.** A movement that is real, statistically clean, and below the
  contract's business floor. The right answer is silence.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from insight_copilot.api.state import AppState
from insight_copilot.demo_scan import ScanSpec, scan
from insight_copilot.engine.dataset import EngineDataset
from insight_copilot.errors import ServiceUnavailable
from insight_copilot.ingest.models import FreshnessStatus
from insight_copilot.logging import get_logger
from insight_copilot.security.compiler import ContractSQLCompiler
from insight_copilot.security.executor import QueryExecutor

logger = get_logger(__name__)

SCENARIO_WINDOW = (dt.date(2026, 3, 9), dt.date(2026, 3, 15))
"""The week the demo narrates. Ground truth is -11.94% against the counterfactual."""

DETECTION_WINDOW = (dt.date(2026, 3, 6), dt.date(2026, 3, 20))
"""The window held out of the baseline fit, so it never learns the event."""

CHART_DAYS = 180
"""Days of history the insight chart shows. Six months carries the annual seasonal
shape the baseline is modelling without drawing 939 points into a smear."""

CALIBRATION_EXCLUSIONS: tuple[tuple[dt.date, dt.date], ...] = (
    (dt.date(2023, 11, 1), dt.date(2023, 11, 25)),
    (dt.date(2024, 10, 20), dt.date(2024, 11, 20)),
    (dt.date(2025, 2, 1), dt.date(2025, 3, 10)),
    (dt.date(2025, 10, 15), dt.date(2025, 11, 25)),
    (dt.date(2026, 2, 20), dt.date(2026, 4, 30)),
)
"""Festive quarters, the unit-change window, and everything from Scenario A onward.
Conformal p-values are exact under exchangeability, and a calibration set containing a
planted outage is not exchangeable with a clean holdout."""


@dataclass
class DemoResult:
    """What the scripted run produced."""

    insights: list[str]
    detail: str


SCAN_SPECS: tuple[ScanSpec, ...] = (
    ScanSpec(
        kpi_id="net_revenue",
        cube_measure="net_revenue_inr",
        window=SCENARIO_WINDOW,
        detection_window=DETECTION_WINDOW,
        evidence_query="warehouse capacity outage north region fulfilment shortfall",
        entities=["North", "DC-North"],
        lever_change=-0.08,
        ladder=True,
    ),
    ScanSpec(
        kpi_id="unit_volume",
        cube_measure="units",
        window=SCENARIO_WINDOW,
        detection_window=DETECTION_WINDOW,
        evidence_query="pick capacity shortfall units shipped north warehouse",
        entities=["North", "DC-North"],
    ),
    ScanSpec(
        kpi_id="gross_margin_pct",
        cube_measure="",
        window=SCENARIO_WINDOW,
        detection_window=DETECTION_WINDOW,
        evidence_query="margin pressure discount pricing cost of goods",
    ),
)
"""Every KPI the demo scans, in the order the feed prioritises them.

Three rather than one, because a feed that ranks by impact with a single card on it is
not demonstrating ranking. ``gross_margin_pct`` carries no cube measure on purpose: it
is a ratio, and Adtributor's explanatory power is defined over an additive measure, so
attributing it would be arithmetic that looks right and means nothing. The scan reports
that it skipped attribution rather than silently naming no segment."""


def run_demo(state: AppState, world: object, warehouse: object) -> DemoResult:
    """Scan every configured KPI, store what each produced, and report the flagship."""
    dataset = _dataset(state, warehouse)
    documents = list(getattr(world, "documents", []))
    freshness = _freshness(state)
    stored: list[str] = []
    details: list[str] = []

    for spec in SCAN_SPECS:
        outcome = scan(
            spec,
            dataset=dataset,
            state=state,
            warehouse=warehouse,
            documents=documents,
            freshness=freshness,
            calibration_exclusions=CALIBRATION_EXCLUSIONS,
        )
        details.append(outcome.detail)
        if outcome.record is None:
            logger.info("demo.scan_empty", detail=outcome.detail)
            continue
        state.store(outcome.record)
        stored.append(outcome.record.insight_id)
        logger.info(
            "demo.insight",
            insight_id=outcome.record.insight_id,
            kpi_id=outcome.record.kpi_id,
            tier=outcome.record.tier,
        )

    flagship = next(
        (state.insights[item] for item in stored if state.insights[item].kpi_id == "net_revenue"),
        None,
    )
    if flagship is None or flagship.bundle is None:
        return DemoResult(insights=stored, detail="; ".join(details))
    bundle = flagship.bundle
    return DemoResult(
        insights=stored,
        detail=(
            f"{bundle.kpi_id} {bundle.delta_pct:+.2f}% on {bundle.period_start} "
            f"at p = {bundle.p_value:.4f}; tier {flagship.tier} "
            f"({len(stored)} of {len(SCAN_SPECS)} KPIs produced an insight)"
        ),
    )


def rescan(state: AppState, world: object, warehouse: object) -> DemoResult:
    """Re-run every scan against the world as it is NOW, replacing the stored insights.

    This is what makes a demo control mean something. Breaking a feed changes freshness,
    freshness moves the ``c4`` signal, and ``c4`` can force an abstention — but none of
    that reaches a viewer unless the engine runs again afterwards against the changed
    world. Previously the controls altered state that nothing re-read.
    """
    state.insights.clear()
    return run_demo(state, world, warehouse)


def _dataset(state: AppState, warehouse: object) -> EngineDataset:
    """Compiler-mediated access for the scans. Entitlements apply here as everywhere."""
    return EngineDataset(
        warehouse=warehouse,  # type: ignore[arg-type]  # Warehouse, attached by the caller
        registry=state.registry,
        compiler=ContractSQLCompiler(state.registry, state.audit),
        executor=QueryExecutor(warehouse.connection, state.audit),  # type: ignore[attr-defined]
    )


def _freshness(state: AppState) -> list[FreshnessStatus]:
    """Freshness from the harness, or an empty list when none is attached."""
    try:
        harness = state.harness
    except ServiceUnavailable:
        return []
    statuses: list[FreshnessStatus] = harness.freshness()  # type: ignore[attr-defined]
    return statuses
