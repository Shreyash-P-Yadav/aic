"""Fixtures for the P7 gate: a realistic healthy run the tests then break in one place.

Each test takes the healthy run and disables exactly one thing, so what the assertion
demonstrates is the effect of that one thing rather than the sum of a bespoke setup.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from insight_copilot.contracts.registry import ContractRegistry
from insight_copilot.engine.attribute_where import SegmentScore, WhereResult
from insight_copilot.engine.attribute_why import Diagnostics, DriverEstimate, WhyResult
from insight_copilot.engine.detect import Detection
from insight_copilot.engine.evidence import EvidenceRetriever
from insight_copilot.engine.pipeline import RunInputs
from insight_copilot.ingest.models import FreshnessStatus

NOW = dt.datetime(2026, 3, 29, 9, 0, tzinfo=dt.UTC)
OUTAGE_DAY = dt.date(2026, 3, 6)
SCENARIO_WEEK = (dt.date(2026, 3, 9), dt.date(2026, 3, 15))

REQUIRED_SOURCES = ["oms_orders"]
"""``net_revenue``'s own required sources, per its contract."""


def contracts() -> ContractRegistry:
    """The shipped contracts, loaded from the package."""
    import insight_copilot.contracts as package

    return ContractRegistry.from_directory(Path(package.__file__).resolve().parent)


def make_detection() -> Detection:
    """Scenario A's outage as the detector actually reported it in the P6 gate."""
    return Detection(
        kpi_id="net_revenue",
        segment="national",
        day=OUTAGE_DAY,
        observed=14_800_000.0,
        expected=24_800_000.0,
        method="conformal_ar_innovation",
        p_value=0.0039,
        statistic=3.54,
        detail="standardised innovation 3.54 against 700 calibration days",
        passed_fdr=True,
    )


def make_where() -> WhereResult:
    """Rung 1's verdict, with the bootstrap win rate the P6 gate measured."""
    top = SegmentScore(
        dimensions=("region",),
        members=("North",),
        actual=32_100_000.0,
        forecast=37_500_000.0,
        explanatory_power=0.507,
        surprise=0.00021,
        score=0.000106,
        observations=4200,
        stability=0.96,
    )
    return WhereResult(
        candidates=[top],
        reported=[top],
        coverage=0.685,
        total_delta=-10_680_616.0,
        is_named_cause=True,
        detail="region=North explains 51% of the gap with a bootstrap win rate of 96%",
    )


def make_why() -> WhyResult:
    """Rung 3's estimates, with the diagnostics and interval the P6 gate measured."""
    estimate = DriverEstimate(
        driver_id="price_index",
        coefficient=-1.6315,
        std_error=0.7015,
        p_value=0.02,
        cross_check_coefficient=-1.5980,
        vif=1.0,
    )
    fill = DriverEstimate(
        driver_id="fill_rate",
        coefficient=0.68,
        std_error=0.21,
        p_value=0.001,
        cross_check_coefficient=0.66,
        vif=1.1,
    )
    return WhyResult(
        estimates=[estimate, fill],
        diagnostics=Diagnostics(
            ljung_box_p=0.125,
            breusch_pagan_p=0.317,
            durbin_watson=2.63,
            holdout_mape=float("nan"),
            max_vif=1.0,
            n_observations=130,
        ),
        agreement_score=0.97,
        explained_fraction=0.62,
        method="ols_newey_west",
    )


def make_freshness(*, stale: set[str] | None = None) -> list[FreshnessStatus]:
    """Every source green, except the ones the caller names."""
    breached = stale or set()
    sources = [
        "oms_orders",
        "wms_fulfilment",
        "martech_weekly",
        "pim_products",
        "support_tickets",
    ]
    return [
        FreshnessStatus(
            source_id=source,
            state="red" if source in breached else "green",
            last_batch_id=f"{source[:3]}_20260328T0200_aaaa",
            last_received_at=NOW - dt.timedelta(hours=90 if source in breached else 7),
            latest_period="2026-03-27",
            age_hours=90.0 if source in breached else 7.0,
            sla_hours=6.0,
            next_due_at=NOW + dt.timedelta(hours=17),
            detail="fixture",
        )
        for source in sources
    ]


def healthy_run(registry: ContractRegistry, world: object) -> RunInputs:
    """A complete, healthy run over the real corpus. Tests break one thing at a time."""
    documents = getattr(world, "documents", [])
    evidence = EvidenceRetriever(documents).retrieve(
        "warehouse capacity outage north region fulfilment shortfall",
        effect_day=OUTAGE_DAY,
        entities=["North", "DC-North"],
        floor=registry.kpi("net_revenue").confidence_policy.evidence_floor,
    )
    return RunInputs(
        contract=registry.kpi("net_revenue"),
        detection=make_detection(),
        where=make_where(),
        why=make_why(),
        evidence=evidence,
        freshness=make_freshness(),
        required_sources=list(REQUIRED_SOURCES),
        dq_pass_rate=0.98,
        reconciliation_ok=True,
        restatement_exposure=0.05,
        history_days=900,
        price_effect=-926_696.0,
        volume_effect=22_614_746.0,
        mix_effect=2_338_307.0,
        baseline_value=1.0e8,
        lever_change=-0.08,
        observed_metrics={
            "price_index": 1.08,
            "discount_depth_pct": 12.0,
            "gross_margin_pct": 48.0,
        },
        period=SCENARIO_WEEK,
        watermark="2026-03-27",
    )
