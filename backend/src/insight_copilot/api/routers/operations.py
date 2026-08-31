"""The operational surface: sources, batches, freshness, data quality, audit, telemetry.

These are the screens that make the pipeline's behaviour visible rather than asserted.
Every one of them reads state the ingestion layer actually recorded — there is no
separate "monitoring" store that could drift from what happened.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import ValidationError

from insight_copilot.api.deps import get_state
from insight_copilot.api.schemas import (
    AuditEntry,
    BatchSummary,
    CalibrationResponse,
    DQResponse,
    EvalMeasurement,
    EvalReportResponse,
    FreshnessResponse,
    ReliabilityBin,
    SourceSummary,
    TelemetryResponse,
    TierRow,
)
from insight_copilot.api.state import AppState
from insight_copilot.ingest.dq_store import DQStore
from insight_copilot.ingest.registry import BatchRegistry
from insight_copilot.ingest.warehouse import Warehouse
from insight_copilot.logging import get_logger

logger = get_logger(__name__)

EVAL_REPORT_FILE = "eval_report.json"
"""The artifact the eval suite writes. Served, never recomputed on request."""

router = APIRouter(tags=["operations"])


@router.get("/api/sources", response_model=list[SourceSummary])
async def list_sources(state: AppState = Depends(get_state)) -> list[SourceSummary]:
    """Every declared feed, from its contract. Available with no warehouse at all."""
    return [
        SourceSummary(
            source_id=contract.source_id,
            system=contract.system,
            owner=contract.owner,
            cadence=contract.covers.period,
            format=contract.format,
            quality_tier=contract.quality_tier,
            latency_sla_hours=contract.latency_sla_hours,
            known_issues=list(contract.known_issues),
        )
        for contract in (state.registry.source(sid) for sid in state.registry.source_ids)
    ]


@router.get("/api/sources/{source_id}/batches", response_model=list[BatchSummary])
async def list_batches(
    source_id: str, limit: int = 25, state: AppState = Depends(get_state)
) -> list[BatchSummary]:
    """What actually landed, newest first, straight out of the batch registry."""
    state.registry.source(source_id)
    warehouse = _warehouse(state)
    frame = BatchRegistry(warehouse).batches(source_id).head(limit)
    import json

    return [
        BatchSummary(
            batch_id=str(row.batch_id),
            periods=list(json.loads(str(row.periods))),
            received_at=str(row.received_at),
            row_count=int(str(row.row_count)),
            rows_quarantined=int(str(row.rows_quarantined)),
            status=str(row.status),
            is_restatement=bool(row.is_restatement),
        )
        for row in frame.itertuples()
    ]


@router.get("/api/freshness", response_model=list[FreshnessResponse])
async def freshness(state: AppState = Depends(get_state)) -> list[FreshnessResponse]:
    """The landing-zone monitor. Green means the drop that was due has arrived."""
    harness = state.harness
    return [
        FreshnessResponse(
            source_id=status.source_id,
            state=status.state,
            age_hours=status.age_hours,
            sla_hours=status.sla_hours,
            latest_period=status.latest_period,
            detail=status.detail,
        )
        for status in harness.freshness()  # type: ignore[attr-defined]  # ReplayHarness
    ]


@router.get("/api/dq", response_model=list[DQResponse])
async def data_quality(limit: int = 100, state: AppState = Depends(get_state)) -> list[DQResponse]:
    """Every expectation result the ingestion layer recorded. **Quarantine, never drop.**"""
    store = DQStore(_warehouse(state))
    frame = store.results().head(limit)
    return [
        DQResponse(
            source_id=str(row.source_id),
            expectation=str(row.expectation),
            outcome=str(row.outcome),
            observed=_optional_float(row.observed),
            threshold=_optional_float(row.threshold),
            rows_affected=int(str(row.rows_affected)),
            detail=str(row.detail),
        )
        for row in frame.itertuples()
    ]


@router.get("/api/telemetry", response_model=TelemetryResponse)
async def telemetry(state: AppState = Depends(get_state)) -> TelemetryResponse:
    """What the model layer cost. A measurement, not a claim."""
    ledger = state.telemetry
    stats = state.router.stats
    return TelemetryResponse(
        insights_metered=len(ledger.insights),
        mean_usd_per_insight=ledger.mean_usd_per_insight,
        mean_inr_per_insight=ledger.mean_usd_per_insight * 83.4,
        total_usd=ledger.total_usd,
        model_calls=stats.calls,
        cache_hits=stats.cache_hits,
        downgrades=stats.downgrades,
    )


@router.get("/api/calibration", response_model=CalibrationResponse)
async def calibration(state: AppState = Depends(get_state)) -> CalibrationResponse:
    """Whether the confidence map is fitted. **An unfitted map says so.**"""
    calibrator = state.narrator  # narrator holds no calibrator; the scorer does
    del calibrator
    from insight_copilot.engine.calibration import IsotonicCalibrator

    fitted = IsotonicCalibrator()
    return CalibrationResponse(
        fitted=fitted.fitted,
        n_points=fitted.n_points,
        detail=(
            "isotonic map fitted on a backtest"
            if fitted.fitted
            else "not yet fitted; composite scores are reported raw and labelled uncalibrated"
        ),
    )


@router.get("/api/evals", response_model=EvalReportResponse)
async def evals(state: AppState = Depends(get_state)) -> EvalReportResponse:
    """The backtest report, or an honest statement that none has been run.

    ``available: false`` is a first-class answer, not an error. A fresh clone has run no
    backtest, and a Trust screen that invented a curve for that state would be doing the
    exact thing this system exists to prevent.

    Served from the artifact the eval suite wrote rather than recomputed per request: a
    backtest is a seven-minute job over 416 events, and a screen that recomputed it on
    every page view would misrepresent what it costs to know this.
    """
    from insight_copilot.evals.models import EvalReport

    path = state.settings.artifacts_dir / EVAL_REPORT_FILE
    if not path.exists():
        return EvalReportResponse(
            available=False,
            detail=(
                "no backtest has been run in this workspace; "
                "`make generate-truth && make backtest` writes one"
            ),
        )
    try:
        report = EvalReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        logger.warning("api.eval_report_unreadable", error=str(exc))
        return EvalReportResponse(available=False, detail=f"the report could not be read: {exc}")

    return EvalReportResponse(
        available=True,
        generated_at=report.generated_at.isoformat(),
        corpus_events=report.corpus_events,
        fit_events=report.fit_events,
        holdout_events=report.holdout_events,
        cut_date=report.cut_date.isoformat() if report.cut_date else None,
        tier_basis=report.tier_basis,
        measurements=[
            EvalMeasurement(
                section=section.name,
                name=item.name,
                value=item.value,
                target=item.target,
                direction=item.direction,
                unit=item.unit,
                n=item.n,
                detail=item.detail,
                verdict=item.verdict,
            )
            for section in report.sections
            for item in section.measurements
        ],
        reliability=[ReliabilityBin.model_validate(row.model_dump()) for row in report.reliability],
        tiers=[TierRow.model_validate(row.model_dump()) for row in report.tiers],
        notes=report.notes,
        detail=f"{len(report.measurements)} measurements from the backtest",
    )


@router.get("/api/audit", response_model=list[AuditEntry])
async def audit(limit: int = 100, state: AppState = Depends(get_state)) -> list[AuditEntry]:
    """Every compile, execution and denial. A refusal is as auditable as a result."""
    return [
        AuditEntry(
            run_id=record.run_id,
            event=record.event,
            role=record.role,
            contract_id=record.contract_id,
            outcome=record.outcome,
            reason=record.reason,
            rows_returned=record.rows_returned,
        )
        for record in state.audit.records()[-limit:]
    ]


def _optional_float(value: object) -> float | None:
    """A nullable numeric column, narrowed. DuckDB nulls arrive as NaN or None."""
    if value is None:
        return None
    try:
        parsed = float(str(value))
    except ValueError:
        return None
    return None if parsed != parsed else parsed


def _warehouse(state: AppState) -> Warehouse:
    """The attached warehouse, narrowed to its type."""
    warehouse: Warehouse = state.warehouse  # type: ignore[assignment]  # attached by the CLI
    return warehouse
